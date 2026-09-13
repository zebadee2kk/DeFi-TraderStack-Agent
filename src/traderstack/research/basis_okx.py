"""OKX daily point-in-time mark−index basis (#134). Research only.

Verified 2026-09-13 (unauthenticated, from this environment):

* ``GET /api/v5/market/history-mark-price-candles?instId=BTC-USDT-SWAP&bar=1Dutc``
  and ``GET /api/v5/market/history-index-candles?instId=BTC-USDT&bar=1Dutc``
  both return ``{"code":"0","data":[[ts_ms, o, h, l, c, confirm], ...]}``
  newest first, 100 rows per page. The **index** instId has no ``-SWAP``
  suffix (``BTC-USDT-SWAP`` on the index path returns code 51001).
* ``bar=1D`` is the **UTC+8** day (rows open at 16:00 UTC); ``1Dutc``
  opens at 00:00 UTC and is the bar that lines up with the funding
  tape's UTC-day sums. Any row whose timestamp is not a UTC midnight is
  skipped and counted, never relabelled.
* ``after=<ts_ms>`` pages **older** than the timestamp. ETH mark candles
  reach January 2020, BTC September 2020.
* The newest row is the current, uncommitted day (``confirm == "0"``) —
  dropped, never persisted.
* Rapid pagination has produced HTTP 403 from the WAF. That is a rate
  limit, not an empty tape: pages are walked serially with a pause and
  exponential backoff; after ``OKX_MAX_RETRIES`` the series is recorded
  as truncated / skipped, never filled.

Only mark and index candle paths are ever requested. ``/market/candles``
(last-trade) and any ``premium`` or funding path are refused by
:func:`traderstack.research.basis.refuse_forbidden_basis_source`.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from traderstack.research.basis import (
    basis_from_closes,
    refuse_forbidden_basis_source,
    utc_day,
)
from traderstack.research.edge_series import (
    EdgeSeriesFetch,
    _finish,
    _ms_to_dt,
    okx_swap,
)

OKX_MARK_CANDLES_PATH = "/api/v5/market/history-mark-price-candles"
OKX_INDEX_CANDLES_PATH = "/api/v5/market/history-index-candles"
OKX_BASIS_SOURCE = "okx:history-mark-price-candles−history-index-candles (USDT quote)"
OKX_PAGE_SIZE = 100
# UTC-aligned daily bar. Plain ``1D`` opens at 16:00 UTC (00:00 UTC+8).
OKX_BAR = "1Dutc"
_DAY_MS = 86_400_000
# Documented limit is ~10 requests / 2 s per IP; 0.25 s between pages
# keeps a serial walk well under it. 403/429 back off 2, 4, 8, 16, 32 s.
OKX_PAGE_PAUSE_SECONDS = 0.25
OKX_MAX_RETRIES = 5
OKX_RETRY_BASE_SECONDS = 2.0
# ~2450 daily rows from 2020 → 25 pages; 30 leaves headroom without
# letting a runaway cursor hammer the endpoint.
OKX_DAILY_LIMIT_PAGES = 30
OKX_RETRY_STATUSES: frozenset[int] = frozenset({403, 429, 500, 502, 503, 504})

SleepFn = Callable[[float], Awaitable[None]]


def okx_index_id(symbol: str) -> str:
    """``BTC/USD`` → ``BTC-USDT`` (the swap id with ``-SWAP`` stripped)."""
    swap = okx_swap(symbol)
    return swap.removesuffix("-SWAP")


def parse_okx_candle_page(payload: object) -> tuple[list[tuple[int, float]], int | None]:
    """Return ``(confirmed_rows, oldest_ts_ms)`` from one OKX candle page.

    Raises ``TypeError`` / ``ValueError`` on a non-``code=="0"`` payload
    or a malformed body. Rows with ``confirm != "1"`` (the uncommitted
    current bar) are dropped from the returned rows but still move the
    pagination cursor.
    """
    if not isinstance(payload, dict):
        raise TypeError("OKX candle payload is not an object")
    code = str(payload.get("code", ""))
    if code != "0":
        raise ValueError(f"OKX code {code or '?'}: {payload.get('msg', '')!s}"[:200])
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise TypeError("OKX candle data is not a list")
    confirmed: list[tuple[int, float]] = []
    oldest: int | None = None
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            ts_ms = int(str(row[0]))
            close = float(str(row[4]))
        except (TypeError, ValueError):
            continue
        if ts_ms <= 0:
            continue
        oldest = ts_ms if oldest is None else min(oldest, ts_ms)
        if str(row[5]) != "1":
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        confirmed.append((ts_ms, close))
    return confirmed, oldest


def parse_okx_candle_rows(payload: object) -> list[tuple[int, float]]:
    return parse_okx_candle_page(payload)[0]


@dataclass
class OkxCloses:
    closes: dict[datetime, float] = field(default_factory=dict)
    pages: int = 0
    truncated: bool = False
    note: str | None = None
    misaligned: int = 0


async def _okx_get_page(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, str],
    *,
    max_retries: int,
    retry_base_seconds: float,
    sleep: SleepFn,
) -> tuple[list[tuple[int, float]] | None, int | None, str | None]:
    """One page with backoff. Returns ``(rows, oldest_ts, error)``."""
    attempt = 0
    while True:
        try:
            response = await client.get(path, params=params)
        except httpx.HTTPError as exc:
            if attempt >= max_retries:
                return None, None, f"transport error after {attempt + 1} attempts ({exc})"
            await sleep(retry_base_seconds * (2**attempt))
            attempt += 1
            continue
        status = response.status_code
        if status in OKX_RETRY_STATUSES:
            if attempt >= max_retries:
                return (
                    None,
                    None,
                    (
                        f"HTTP {status} after {attempt + 1} attempts "
                        "(OKX rate limit / WAF — backed off, not an empty tape)"
                    ),
                )
            await sleep(retry_base_seconds * (2**attempt))
            attempt += 1
            continue
        if status != 200:
            return None, None, f"HTTP {status}"
        try:
            rows, oldest = parse_okx_candle_page(response.json())
        except (TypeError, ValueError) as exc:
            return None, None, f"unparsable OKX candle payload ({exc})"
        return rows, oldest, None


async def fetch_okx_daily_closes(
    client: httpx.AsyncClient,
    path: str,
    inst_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit_pages: int = OKX_DAILY_LIMIT_PAGES,
    page_size: int = OKX_PAGE_SIZE,
    pause_seconds: float = OKX_PAGE_PAUSE_SECONDS,
    max_retries: int = OKX_MAX_RETRIES,
    retry_base_seconds: float = OKX_RETRY_BASE_SECONDS,
    sleep: SleepFn = asyncio.sleep,
) -> OkxCloses:
    """Walk one OKX daily candle path older-than ``after`` at a polite rate.

    Keeps only confirmed rows inside ``[since, until]`` (UTC day opens).
    Stops on an empty page, a cursor that stops moving, the ``since``
    bound, or ``limit_pages`` (recorded as truncated). A page error after
    retries returns what was collected so far, marked truncated — or an
    empty result carrying the error when nothing was collected.
    """
    refuse_forbidden_basis_source(path)
    if path not in (OKX_MARK_CANDLES_PATH, OKX_INDEX_CANDLES_PATH):
        raise ValueError(f"refused OKX path {path!r}: only mark/index candle history is basis")
    result = OkxCloses()
    since_ms = int(utc_day(since).timestamp() * 1000) if since is not None else None
    until_ms = int(utc_day(until).timestamp() * 1000) if until is not None else None
    after: int | None = (
        int((utc_day(until) + timedelta(days=1)).timestamp() * 1000) if until is not None else None
    )
    for page in range(limit_pages):
        params = {"instId": inst_id, "bar": OKX_BAR, "limit": str(page_size)}
        if after is not None:
            params["after"] = str(after)
        rows, oldest, error = await _okx_get_page(
            client,
            path,
            params,
            max_retries=max_retries,
            retry_base_seconds=retry_base_seconds,
            sleep=sleep,
        )
        result.pages = page + 1
        if error is not None:
            result.note = error
            result.truncated = bool(result.closes)
            return result
        assert rows is not None
        for ts_ms, close in rows:
            if since_ms is not None and ts_ms < since_ms:
                continue
            if until_ms is not None and ts_ms > until_ms:
                continue
            if ts_ms % _DAY_MS != 0:
                result.misaligned += 1  # not a UTC day open: never relabel it
                continue
            result.closes[utc_day(_ms_to_dt(ts_ms))] = close
        if oldest is None:
            break  # empty page: start of history
        if after is not None and oldest >= after:
            break  # cursor did not move
        if since_ms is not None and oldest <= since_ms:
            break  # reached the window start
        after = oldest
        if pause_seconds > 0:
            await sleep(pause_seconds)
    else:
        result.truncated = True
        result.note = f"page limit {limit_pages} reached before the window start; series truncated, not filled"
    return result


async def fetch_okx_basis(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    since: datetime | None = None,
    until: datetime | None = None,
    limit_pages: int = OKX_DAILY_LIMIT_PAGES,
    pause_seconds: float = OKX_PAGE_PAUSE_SECONDS,
    max_retries: int = OKX_MAX_RETRIES,
    retry_base_seconds: float = OKX_RETRY_BASE_SECONDS,
    sleep: SleepFn = asyncio.sleep,
) -> EdgeSeriesFetch:
    """Daily ``(mark_close − index_close) / index_close`` on OKX. Skip-not-invent."""
    name = f"okx_basis:{symbol}"
    try:
        swap = okx_swap(symbol)
        index_id = okx_index_id(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="okx")
    mark = await fetch_okx_daily_closes(
        client,
        OKX_MARK_CANDLES_PATH,
        swap,
        since=since,
        until=until,
        limit_pages=limit_pages,
        pause_seconds=pause_seconds,
        max_retries=max_retries,
        retry_base_seconds=retry_base_seconds,
        sleep=sleep,
    )
    if not mark.closes:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason=f"OKX mark candles: {mark.note or 'empty series'}",
            source=OKX_BASIS_SOURCE,
        )
    if pause_seconds > 0:
        await sleep(pause_seconds)
    index = await fetch_okx_daily_closes(
        client,
        OKX_INDEX_CANDLES_PATH,
        index_id,
        since=since,
        until=until,
        limit_pages=limit_pages,
        pause_seconds=pause_seconds,
        max_retries=max_retries,
        retry_base_seconds=retry_base_seconds,
        sleep=sleep,
    )
    if not index.closes:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason=f"OKX index candles: {index.note or 'empty series'}",
            source=OKX_BASIS_SOURCE,
        )
    points, bounded_skips = basis_from_closes(mark.closes, index.closes)
    one_sided = len(set(mark.closes) ^ set(index.closes))
    notes = [
        (
            f"OKX public daily history-mark-price-candles ({swap}) close minus "
            f"history-index-candles ({index_id}) close over index; bar=1Dutc "
            "(UTC day open); confirm==1 rows only (uncommitted day dropped); "
            "USDT-margined swap vs USDT index — not premium, not last-trade, "
            "not funding-implied."
        ),
        (
            f"mark_pages={mark.pages} index_pages={index.pages} "
            f"misaligned_rows_skipped={mark.misaligned + index.misaligned} "
            f"one_sided_days_skipped={one_sided} bounded_skips={bounded_skips}."
        ),
    ]
    if mark.truncated:
        notes.append(f"mark series truncated: {mark.note}")
    if index.truncated:
        notes.append(f"index series truncated: {index.note}")
    return _finish(name, source=OKX_BASIS_SOURCE, points=points, ok_reason=" ".join(notes))
