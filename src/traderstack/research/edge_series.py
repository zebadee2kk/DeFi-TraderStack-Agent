"""Offline edge-feature series for strategy search.

Tries free public REST first. Nothing is invented: a missing, geo-blocked, or
too-short series is skipped and the reason is recorded.

Binance USDT-M (preferred when reachable):

* ``GET /fapi/v1/fundingRate`` — historical, paginable, no key.
* ``GET /futures/data/openInterestHist`` — typically last ~30 days.
* Liquidations — **no usable public historical REST**. ``/fapi/v1/allForceOrders``
  is recent-only (and often geo-blocked, HTTP 451). The live stream is
  ``!forceOrder@arr``. data.binance.vision USDT-M ``liquidationSnapshot`` was
  removed. This adapter records a skip rather than synthesising z-scores.

OKX (used when Binance is unreachable from this environment):

* ``GET /api/v5/public/funding-rate-history`` — ~90 days of 8h prints.
* ``GET /api/v5/rubik/stat/contracts/open-interest-history`` — 1h OI, paginable.
* ``GET /api/v5/public/liquidation-orders`` — ~100 recent fills (hours, not
  months). Skipped for historical z.

Second independent funding tapes (skip-not-invent; do not blend):

* Hyperliquid ``POST /info`` ``fundingHistory`` — public, hourly, paginable
  from listing (~2023). Typically reachable from this environment.
* BitMEX ``GET /api/v1/funding`` — public settlements (XBTUSD from 2016,
  ETHUSD from 2018). **Sunset:** official closure 23 September 2026
  04:00 UTC (risk limits from 26 August 2026 04:00 UTC;
  https://www.bitmex.com/blog/bitmex-closure). Historical tapes may
  still be fetched as dead-end documentation. Not a long-term
  dual-print, basis, or paper-hedge venue. Uses ``fundingRate`` only.
* HTX linear-swap ``GET /linear-swap-api/v1/swap_historical_funding_rate``
  — public 8h ``funding_rate`` from 2020-10-21 on BTC-USDT and
  ETH-USDT (~2150d / ≥720 UTC daily sums). ``realized_rate`` is null
  on every historical page probed here; ``avg_premium_index`` is the
  funding-formula premium and is not used. Replacement long tape
  after the BitMEX sunset.
* Bybit ``GET /v5/market/funding/history`` — public when reachable; this
  environment typically gets HTTP 403 (CloudFront country block).
* Deribit ``public/get_funding_rate_history`` is reachable but returns
  the 8h interest restated every hour. Using each row as a settlement
  would invent 8× carry — not wired.
* Gate / Bitget / MEXC / dYdX public funding REST can also respond here;
  they are not blended into this adapter. See the edge-status memo.

PIT perp−spot basis (skip-not-invent; do not blend):

* Hyperliquid public REST exposes **current** ``markPx`` / ``oraclePx`` /
  ``midPx`` on ``metaAndAssetCtxs`` only. There is no historical
  mark−index or perp-mid−spot-mid tape. ``fundingHistory.premium`` is
  the funding-formula input, not a PIT perp−spot mid — do not treat it
  as basis. ``candleSnapshot`` is last-trade OHLC, not mid.
* BitMEX public REST exposes **current** ``markPrice`` /
  ``indicativeSettlePrice`` / ``midPrice`` on ``/instrument``.
  Historical ``.XBTUSDPI`` / ``.ETHUSDPI`` are the funding-formula
  premium index (same class as Hyperliquid premium — not wired).
  ``quote/bucketed`` + ``.BXBT``/``.BETH`` can form perp-mid−index;
  that is not mark−index and not perp-mid−spot-mid, and Hyperliquid
  cannot pair it, so it is not wired as a promoting basis series.
* HTX public REST exposes daily ``linear_swap_mark_price_kline`` and
  ``index`` history (size cap 2000, ~1999d from 2021-03-23). That is
  mark−index on **one** venue. Dual-print basis still needs the same
  construction on Hyperliquid for the scored window.
* HuggingFace ``asiletto81/hyperliquid`` ``asset_ctxs`` is a public
  ≥720d Hyperliquid mark−index tape (883 contiguous days,
  2024-01-01 → 2026-06-01, ``mark_px``/``oracle_px``). The live
  Kraken 720 ending ~2026-09-11 aligns only ~618 days, so
  basis-aware dual-print freezes the scored window ending
  ``BASIS_AWARE_WINDOW_END_UTC`` (2026-06-01) with ≥720 aligned
  days **before** scoring. Official HL S3 stays requester-pays 403.
  Do not stitch Binance Vision into the HL leg.
* Dual-print basis requires the requested construction on **both**
  venues for the scored window. Absent that, basis is UNAVAILABLE.

Cross-venue divergence is not built here (needs two aligned venues).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

BINANCE_FAPI_BASE = "https://fapi.binance.com"
OKX_BASE = "https://www.okx.com"
BYBIT_BASE = "https://api.bybit.com"
HYPERLIQUID_BASE = "https://api.hyperliquid.xyz"
BITMEX_BASE = "https://www.bitmex.com"
HTX_BASE = "https://api.hbdm.com"

_BINANCE_SYMBOL: dict[str, str] = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
}
_OKX_SWAP: dict[str, str] = {
    "BTC/USD": "BTC-USDT-SWAP",
    "ETH/USD": "ETH-USDT-SWAP",
    "SOL/USD": "SOL-USDT-SWAP",
}
_BYBIT_SYMBOL: dict[str, str] = {
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "SOL/USD": "SOLUSDT",
}
_HYPERLIQUID_COIN: dict[str, str] = {
    "BTC/USD": "BTC",
    "ETH/USD": "ETH",
    "SOL/USD": "SOL",
}
_BITMEX_SYMBOL: dict[str, str] = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
}
_HTX_CONTRACT: dict[str, str] = {
    "BTC/USD": "BTC-USDT",
    "ETH/USD": "ETH-USDT",
}
HYPERLIQUID_PAGE_SIZE = 500
HYPERLIQUID_DEFAULT_LOOKBACK_DAYS = 180
# Daily hard gates need ~720 aligned days. Hourly fundingHistory is
# paginable from listing (~2023-05); 800d is enough to cover a Kraken
# 720-bar daily window without inventing prints.
HYPERLIQUID_DAILY_LOOKBACK_DAYS = 800
HYPERLIQUID_DAILY_LIMIT_PAGES = 48
HYPERLIQUID_MAX_RETRIES = 6
HYPERLIQUID_RETRY_BASE_SECONDS = 1.5
HYPERLIQUID_PAGE_PAUSE_SECONDS = 0.2
HYPERLIQUID_SYMBOL_PAUSE_SECONDS = 2.0
BITMEX_PAGE_SIZE = 500
BITMEX_DEFAULT_LOOKBACK_DAYS = 180
# Daily hard gates need ~720 aligned days. BitMEX 8h settlements are
# paginable from listing (XBTUSD 2016 / ETHUSD 2018); 800d covers a
# Kraken 720-bar daily window without inventing prints or using
# fundingRateDaily (a restated multiple of the settlement).
BITMEX_DAILY_LOOKBACK_DAYS = 800
BITMEX_DAILY_LIMIT_PAGES = 8
BITMEX_PAGE_PAUSE_SECONDS = 0.25
# BitMEX official closure (not a long-term dual-print venue):
# 23 September 2026 04:00 UTC. Historical fetches stay available
# as dead-end documentation; venue pick excludes it.
BITMEX_SUNSET_UTC = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
BITMEX_SUNSET_NOTE = (
    "BitMEX official closure 23 September 2026 04:00 UTC "
    "(risk limits from 26 August 2026 04:00 UTC; new registrations "
    "already stopped). https://www.bitmex.com/blog/bitmex-closure. "
    "Not a long-term dual-print, funding, basis, or paper-hedge venue."
)
HTX_PAGE_SIZE = 100
HTX_DEFAULT_LOOKBACK_DAYS = 180
# Daily hard gates need ~720 aligned days. HTX 8h funding_rate is
# paginable from 2020-10-21; 800d covers a Kraken 720-bar daily
# window. page_size is capped at 100 here (200 asked → 100 returned).
HTX_DAILY_LOOKBACK_DAYS = 800
HTX_DAILY_LIMIT_PAGES = 28
HTX_PAGE_PAUSE_SECONDS = 0.2
HTX_BASIS_SIZE = 2000
# Coverage-driven freeze for HL+HTX basis-aware dual-print.
# asiletto81/hyperliquid asset_ctxs ends 2026-06-01; the live Kraken720
# ending ~2026-09-11 only aligns ~617d. Do not retune after seeing PnL.
# See docs/artifacts/strategy-search/basis-window-freeze.md.
BASIS_AWARE_WINDOW_END_UTC = datetime(2026, 6, 1, tzinfo=UTC)
BASIS_AWARE_MIN_ALIGNED_DAYS = 720
ASILLETTO81_HL_DATASET = "asiletto81/hyperliquid"
ASILLETTO81_HL_ASSET_CTXS_PREFIX = (
    "https://huggingface.co/datasets/asiletto81/hyperliquid/resolve/main/asset_ctxs"
)
ASILLETTO81_HL_ARCHIVE_FIRST_UTC = datetime(2024, 1, 1, tzinfo=UTC)
ASILLETTO81_HL_ARCHIVE_LAST_UTC = datetime(2026, 6, 1, tzinfo=UTC)
# Official BitMEX sunset. Still fetched for notes; never selected
# as a promoting / dual-print / paper-hedge default venue.
SUNSET_FUNDING_VENUES: frozenset[str] = frozenset({"bitmex"})

MIN_LIQUIDATION_SPAN_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class EdgeSeriesFetch:
    name: str
    status: Literal["ok", "skipped"]
    reason: str
    source: str = ""
    points: tuple[tuple[datetime, float], ...] = ()
    first: datetime | None = None
    last: datetime | None = None

    def as_note(self) -> dict[str, str]:
        payload = {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "source": self.source,
            "points": str(len(self.points)),
        }
        if self.first is not None:
            payload["first"] = self.first.isoformat()
        if self.last is not None:
            payload["last"] = self.last.isoformat()
        return payload


@dataclass
class EdgeBundle:
    """Per-asset series plus the skip/ok notes for the report."""

    funding: dict[str, tuple[tuple[datetime, float], ...]] = field(default_factory=dict)
    open_interest: dict[str, tuple[tuple[datetime, float], ...]] = field(default_factory=dict)
    liquidation: dict[str, tuple[tuple[datetime, float], ...]] = field(default_factory=dict)
    notes: list[EdgeSeriesFetch] = field(default_factory=list)

    def series_for(
        self, kind: Literal["funding", "open_interest", "liquidation"]
    ) -> dict[str, tuple[tuple[datetime, float], ...]] | None:
        mapping = {
            "funding": self.funding,
            "open_interest": self.open_interest,
            "liquidation": self.liquidation,
        }[kind]
        return mapping or None


def _ms_to_dt(value: float | str) -> datetime:
    timestamp = float(value)
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _finish(
    name: str,
    *,
    source: str,
    points: list[tuple[datetime, float]],
    ok_reason: str,
) -> EdgeSeriesFetch:
    ordered = sorted({ts: value for ts, value in points}.items())
    if not ordered:
        return EdgeSeriesFetch(name=name, status="skipped", reason="empty series", source=source)
    return EdgeSeriesFetch(
        name=name,
        status="ok",
        reason=ok_reason,
        source=source,
        points=tuple(ordered),
        first=ordered[0][0],
        last=ordered[-1][0],
    )


def binance_contract(symbol: str) -> str:
    key = symbol.upper()
    if key in _BINANCE_SYMBOL:
        return _BINANCE_SYMBOL[key]
    raise ValueError(f"no Binance USDT-M mapping for {symbol!r}")


def okx_swap(symbol: str) -> str:
    key = symbol.upper()
    if key in _OKX_SWAP:
        return _OKX_SWAP[key]
    raise ValueError(f"no OKX swap mapping for {symbol!r}")


def bybit_contract(symbol: str) -> str:
    key = symbol.upper()
    if key in _BYBIT_SYMBOL:
        return _BYBIT_SYMBOL[key]
    raise ValueError(f"no Bybit linear mapping for {symbol!r}")


def hyperliquid_coin(symbol: str) -> str:
    key = symbol.upper()
    if key in _HYPERLIQUID_COIN:
        return _HYPERLIQUID_COIN[key]
    raise ValueError(f"no Hyperliquid coin mapping for {symbol!r}")


def bitmex_contract(symbol: str) -> str:
    key = symbol.upper()
    if key in _BITMEX_SYMBOL:
        return _BITMEX_SYMBOL[key]
    raise ValueError(f"no BitMEX mapping for {symbol!r}")


def htx_contract(symbol: str) -> str:
    key = symbol.upper()
    if key in _HTX_CONTRACT:
        return _HTX_CONTRACT[key]
    raise ValueError(f"no HTX linear-swap mapping for {symbol!r}")


def _iso_to_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _geo_or_http_skip(name: str, source: str, exc: BaseException) -> EdgeSeriesFetch:
    detail = str(exc)
    response_text = ""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            response_text = response.text or ""
        except (httpx.HTTPError, TypeError, ValueError):
            response_text = ""
    lowered = f"{detail} {response_text}".lower()
    if "451" in detail or "451" in response_text:
        detail = "HTTP 451 (geo-blocked / unavailable in this environment)"
    elif "403" in detail or "403" in response_text:
        if "cloudfront" in lowered or "country" in lowered:
            detail = "HTTP 403 (CloudFront / country block — unavailable in this environment)"
        else:
            detail = "HTTP 403 (forbidden in this environment)"
    return EdgeSeriesFetch(
        name=name,
        status="skipped",
        reason=detail,
        source=source,
    )


async def fetch_binance_funding(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    start_ms: int | None = None,
    limit_pages: int = 8,
) -> EdgeSeriesFetch:
    name = f"binance_funding:{symbol}"
    try:
        contract = binance_contract(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="binance")
    points: list[tuple[datetime, float]] = []
    cursor = start_ms
    try:
        for _ in range(limit_pages):
            params: dict[str, Any] = {"symbol": contract, "limit": 1000}
            if cursor is not None:
                params["startTime"] = cursor
            response = await client.get("/fapi/v1/fundingRate", params=params)
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or not rows:
                break
            new = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ts = _ms_to_dt(row["fundingTime"])
                points.append((ts, float(row["fundingRate"])))
                new += 1
            last_ms = int(rows[-1]["fundingTime"])
            if last_ms <= (cursor or 0) or new == 0:
                break
            cursor = last_ms + 1
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        return _geo_or_http_skip(name, "binance", exc)
    return _finish(
        name,
        source="binance:/fapi/v1/fundingRate",
        points=points,
        ok_reason="USDT-M fundingRate pages (public, no key)",
    )


async def fetch_binance_open_interest(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    period: str = "1h",
) -> EdgeSeriesFetch:
    name = f"binance_oi:{symbol}"
    try:
        contract = binance_contract(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="binance")
    try:
        response = await client.get(
            "/futures/data/openInterestHist",
            params={"symbol": contract, "period": period, "limit": 500},
        )
        response.raise_for_status()
        rows = response.json()
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        return _geo_or_http_skip(name, "binance", exc)
    if not isinstance(rows, list):
        return EdgeSeriesFetch(
            name=name, status="skipped", reason="unexpected OI payload", source="binance"
        )
    points: list[tuple[datetime, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _ms_to_dt(row["timestamp"])
        raw = row.get("sumOpenInterest") or row.get("openInterest")
        if raw is None:
            continue
        points.append((ts, float(raw)))
    return _finish(
        name,
        source="binance:/futures/data/openInterestHist",
        points=points,
        ok_reason="USDT-M openInterestHist (public; typically last ~30d)",
    )


async def fetch_binance_liquidations(
    symbol: str,
    *,
    client: httpx.AsyncClient,
) -> EdgeSeriesFetch:
    """Probe the public force-order REST; skip unless the span is usable."""
    name = f"binance_liquidation:{symbol}"
    try:
        contract = binance_contract(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="binance")
    try:
        response = await client.get(
            "/fapi/v1/allForceOrders",
            params={"symbol": contract, "limit": 1000},
        )
        response.raise_for_status()
        rows = response.json()
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason=(
                f"{_geo_or_http_skip(name, 'binance', exc).reason}. "
                "No public USDT-M historical liquidation REST; "
                "live WS is !forceOrder@arr; Vision um/liquidationSnapshot removed."
            ),
            source="binance",
        )
    if not isinstance(rows, list) or not rows:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason=(
                "allForceOrders empty or missing. Historical USDT-M liquidation "
                "aggregates are not publicly restful; do not zero-fill."
            ),
            source="binance",
        )
    hourly: dict[datetime, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _ms_to_dt(row.get("time") or row.get("T") or 0)
        hour = ts.replace(minute=0, second=0, microsecond=0)
        qty = float(row.get("origQty") or row.get("q") or 0.0)
        side = str(row.get("side") or row.get("S") or "").upper()
        signed = -qty if side == "SELL" else qty
        hourly[hour] = hourly.get(hour, 0.0) + signed
    points = sorted(hourly.items())
    if len(points) < 2:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason="allForceOrders too short to build an hourly z series",
            source="binance",
        )
    span = (points[-1][0] - points[0][0]).total_seconds()
    if span < MIN_LIQUIDATION_SPAN_SECONDS:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason=(
                f"allForceOrders span {span / 3600:.1f}h < 7d; not a historical "
                "liquidation aggregate. Live WS only."
            ),
            source="binance",
            points=tuple(points),
            first=points[0][0],
            last=points[-1][0],
        )
    return _finish(
        name,
        source="binance:/fapi/v1/allForceOrders",
        points=points,
        ok_reason="hourly signed force-order notional (rare; usually too short)",
    )


async def fetch_okx_funding(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    limit_pages: int = 8,
) -> EdgeSeriesFetch:
    name = f"okx_funding:{symbol}"
    try:
        inst = okx_swap(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="okx")
    points: list[tuple[datetime, float]] = []
    cursor: str | None = None
    try:
        for _ in range(limit_pages):
            params: dict[str, Any] = {"instId": inst, "limit": 100}
            if cursor is not None:
                params["after"] = cursor
            response = await client.get("/api/v5/public/funding-rate-history", params=params)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                points.append((_ms_to_dt(row["fundingTime"]), float(row["fundingRate"])))
            next_cursor = str(rows[-1]["fundingTime"])
            if next_cursor == cursor:
                break
            cursor = next_cursor
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        return _geo_or_http_skip(name, "okx", exc)
    return _finish(
        name,
        source="okx:/api/v5/public/funding-rate-history",
        points=points,
        ok_reason="OKX swap funding-rate-history (public; ~90d of 8h prints)",
    )


async def fetch_bybit_funding(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    limit_pages: int = 8,
) -> EdgeSeriesFetch:
    """Linear USDT funding history. Typically HTTP 403 from this environment."""
    name = f"bybit_funding:{symbol}"
    try:
        contract = bybit_contract(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="bybit")
    points: list[tuple[datetime, float]] = []
    end_time: int | None = None
    try:
        for _ in range(limit_pages):
            params: dict[str, Any] = {
                "category": "linear",
                "symbol": contract,
                "limit": 200,
            }
            if end_time is not None:
                params["endTime"] = end_time
            response = await client.get("/v5/market/funding/history", params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return EdgeSeriesFetch(
                    name=name,
                    status="skipped",
                    reason="unexpected Bybit funding payload",
                    source="bybit",
                )
            ret_code = payload.get("retCode")
            if ret_code not in (0, "0", None):
                return EdgeSeriesFetch(
                    name=name,
                    status="skipped",
                    reason=f"Bybit retCode={ret_code} {payload.get('retMsg', '')}".strip(),
                    source="bybit",
                )
            result = payload.get("result")
            rows = result.get("list") if isinstance(result, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            oldest_ms: int | None = None
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ts = _ms_to_dt(row["fundingRateTimestamp"])
                points.append((ts, float(row["fundingRate"])))
                raw_ms = int(row["fundingRateTimestamp"])
                oldest_ms = raw_ms if oldest_ms is None else min(oldest_ms, raw_ms)
            if oldest_ms is None or oldest_ms <= (end_time or 0):
                break
            end_time = oldest_ms - 1
            if len(rows) < 200:
                break
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        return _geo_or_http_skip(name, "bybit", exc)
    return _finish(
        name,
        source="bybit:/v5/market/funding/history",
        points=points,
        ok_reason="Bybit linear funding-history (public; paginated newest-first)",
    )


async def _hyperliquid_post_info(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> httpx.Response:
    """POST /info with backoff on HTTP 429. Does not invent a body."""
    last_exc: BaseException | None = None
    for attempt in range(HYPERLIQUID_MAX_RETRIES):
        try:
            response = await client.post("/info", json=payload)
            if response.status_code == 429:
                last_exc = httpx.HTTPStatusError(
                    "429 Too Many Requests",
                    request=response.request,
                    response=response,
                )
                await asyncio.sleep(HYPERLIQUID_RETRY_BASE_SECONDS * (2**attempt))
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                last_exc = exc
                await asyncio.sleep(HYPERLIQUID_RETRY_BASE_SECONDS * (2**attempt))
                continue
            raise
    assert last_exc is not None
    raise last_exc


async def hyperliquid_post_info(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> httpx.Response:
    """Public wrapper for POST /info. Does not invent a body."""

    return await _hyperliquid_post_info(client, payload)


async def fetch_hyperliquid_funding(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    start_ms: int | None = None,
    limit_pages: int = 16,
    lookback_days: int = HYPERLIQUID_DEFAULT_LOOKBACK_DAYS,
) -> EdgeSeriesFetch:
    """Hourly public fundingHistory. Paginate forward from startTime."""
    name = f"hyperliquid_funding:{symbol}"
    try:
        coin = hyperliquid_coin(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="hyperliquid")
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    cursor = start_ms if start_ms is not None else now_ms - lookback_days * 24 * 3600 * 1000
    points: list[tuple[datetime, float]] = []
    stopped_early = ""
    try:
        for page in range(limit_pages):
            response = await _hyperliquid_post_info(
                client,
                {"type": "fundingHistory", "coin": coin, "startTime": cursor},
            )
            rows = response.json()
            if not isinstance(rows, list) or not rows:
                break
            last_ms = cursor
            new = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ts = _ms_to_dt(row["time"])
                points.append((ts, float(row["fundingRate"])))
                last_ms = max(last_ms, int(row["time"]))
                new += 1
            if new == 0 or last_ms <= cursor:
                break
            cursor = last_ms + 1
            if len(rows) < HYPERLIQUID_PAGE_SIZE:
                break
            if page + 1 < limit_pages and HYPERLIQUID_PAGE_PAUSE_SECONDS:
                await asyncio.sleep(HYPERLIQUID_PAGE_PAUSE_SECONDS)
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        if not points:
            return _geo_or_http_skip(name, "hyperliquid", exc)
        stopped_early = f"; pagination stopped ({exc})"
    suffix = stopped_early
    return _finish(
        name,
        source="hyperliquid:/info fundingHistory",
        points=points,
        ok_reason=(
            f"Hyperliquid public fundingHistory (hourly; paginated; "
            f"lookback {lookback_days}d){suffix}"
        ),
    )


async def fetch_bitmex_funding(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    start_iso: str | None = None,
    limit_pages: int = 8,
    lookback_days: int = BITMEX_DEFAULT_LOOKBACK_DAYS,
) -> EdgeSeriesFetch:
    """Public settlement tape. Uses fundingRate only — never fundingRateDaily."""
    name = f"bitmex_funding:{symbol}"
    try:
        contract = bitmex_contract(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="bitmex")
    if start_iso is None:
        start = datetime.now(UTC) - timedelta(days=lookback_days)
        cursor = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    else:
        cursor = start_iso
    points: list[tuple[datetime, float]] = []
    stopped_early = ""
    try:
        for page in range(limit_pages):
            response = await client.get(
                "/api/v1/funding",
                params={
                    "symbol": contract,
                    "count": BITMEX_PAGE_SIZE,
                    "reverse": "false",
                    "startTime": cursor,
                },
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or not rows:
                break
            last_ts: datetime | None = None
            new = 0
            for row in rows:
                if not isinstance(row, dict) or "fundingRate" not in row:
                    continue
                # Settlement print. fundingRateDaily restates the same
                # interval as a daily multiple (3× on 8h, 1× on the early
                # 24h era) — treating it as a second print invents carry.
                ts = _iso_to_dt(str(row["timestamp"]))
                points.append((ts, float(row["fundingRate"])))
                last_ts = ts if last_ts is None else max(last_ts, ts)
                new += 1
            if new == 0 or last_ts is None:
                break
            cursor = (last_ts + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if len(rows) < BITMEX_PAGE_SIZE:
                break
            if page + 1 < limit_pages and BITMEX_PAGE_PAUSE_SECONDS:
                await asyncio.sleep(BITMEX_PAGE_PAUSE_SECONDS)
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        if not points:
            return _geo_or_http_skip(name, "bitmex", exc)
        stopped_early = f"; pagination stopped ({exc})"
    suffix = stopped_early
    return _finish(
        name,
        source="bitmex:/api/v1/funding",
        points=points,
        ok_reason=(
            f"BitMEX public funding settlements (paginated; fundingRate "
            f"only, not fundingRateDaily; lookback {lookback_days}d; "
            f"sunset venue — {BITMEX_SUNSET_NOTE}){suffix}"
        ),
    )


async def fetch_htx_funding(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    lookback_days: int = HTX_DEFAULT_LOOKBACK_DAYS,
    limit_pages: int = 8,
) -> EdgeSeriesFetch:
    """Public 8h ``funding_rate`` tape. Never uses premium or realized_rate."""
    name = f"htx_funding:{symbol}"
    try:
        contract = htx_contract(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="htx")
    start = datetime.now(UTC) - timedelta(days=lookback_days)
    points: list[tuple[datetime, float]] = []
    stopped_early = ""
    try:
        for page in range(limit_pages):
            response = await client.get(
                "/linear-swap-api/v1/swap_historical_funding_rate",
                params={
                    "contract_code": contract,
                    "page_index": page + 1,
                    "page_size": HTX_PAGE_SIZE,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                break
            data = payload.get("data")
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            oldest_on_page: datetime | None = None
            new = 0
            for row in rows:
                if not isinstance(row, dict) or "funding_rate" not in row:
                    continue
                # Settlement print. avg_premium_index is the
                # funding-formula premium (same class as HL premium /
                # BitMEX .XBTUSDPI) — not used. realized_rate is null
                # on every historical page probed here; do not invent
                # it and do not treat the null as a zero settlement.
                ts = _ms_to_dt(row["funding_time"])
                if ts < start:
                    continue
                points.append((ts, float(row["funding_rate"])))
                oldest_on_page = ts if oldest_on_page is None else min(oldest_on_page, ts)
                new += 1
            if new == 0:
                break
            if oldest_on_page is not None and oldest_on_page <= start:
                break
            if len(rows) < HTX_PAGE_SIZE:
                break
            if page + 1 < limit_pages and HTX_PAGE_PAUSE_SECONDS:
                await asyncio.sleep(HTX_PAGE_PAUSE_SECONDS)
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        if not points:
            return _geo_or_http_skip(name, "htx", exc)
        stopped_early = f"; pagination stopped ({exc})"
    return _finish(
        name,
        source="htx:/linear-swap-api/v1/swap_historical_funding_rate",
        points=points,
        ok_reason=(
            f"HTX linear-swap public funding_rate (paginated 8h; "
            f"not avg_premium_index; realized_rate unused/null; "
            f"lookback {lookback_days}d){stopped_early}"
        ),
    )


HYPERLIQUID_BASIS_UNAVAILABLE = (
    "UNAVAILABLE: Hyperliquid public REST has current markPx/oraclePx/midPx "
    "only (metaAndAssetCtxs). fundingHistory.premium is the funding-formula "
    "input, not a PIT perp−spot mid, and is not used. candleSnapshot is "
    "last-trade, not mid. HuggingFace asiletto81/hyperliquid asset_ctxs "
    "is the historical mark_px/oracle_px path for the frozen window ending "
    "2026-06-01; if that fetch fails or yields <720 days inside the freeze, "
    "basis stays skipped. Official S3 is requester-pays 403. Do not stitch "
    "Binance Vision into HL. Skip-not-invent."
)

BITMEX_BASIS_UNAVAILABLE = (
    "UNAVAILABLE: BitMEX is sunsetting (official closure 23 September "
    "2026 04:00 UTC; https://www.bitmex.com/blog/bitmex-closure) and "
    "is not a long-term basis venue. Public REST still has current "
    "markPrice / indicativeSettlePrice / midPrice only. Historical "
    ".XBTUSDPI / .ETHUSDPI is the funding-formula premium index (same "
    "class as Hyperliquid premium — not used). quote/bucketed + "
    ".BXBT/.BETH can form perp-mid−index, which is not mark−index and "
    "not perp-mid−spot-mid. Skip-not-invent."
)

_BITMEX_PREMIUM_INDEX: dict[str, str] = {
    "BTC/USD": ".XBTUSDPI",
    "ETH/USD": ".ETHUSDPI",
}


def hyperliquid_current_mid_usd(payload: object, coin: str) -> float | None:
    """Current ``midPx`` snapshot. Not a PIT basis point; not for scoring."""

    ctx = _hyperliquid_ctx_for(payload, coin)
    if ctx is None:
        return None
    raw = ctx.get("midPx")
    if raw is None:
        return None
    try:
        mid = float(raw)
    except (TypeError, ValueError):
        return None
    return mid if mid > 0 else None


def bitmex_current_mid_usd(payload: object) -> float | None:
    """Current ``midPrice`` snapshot. Not a PIT basis point; not for scoring."""

    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return None
    raw = payload[0].get("midPrice")
    if raw is None:
        return None
    try:
        mid = float(raw)
    except (TypeError, ValueError):
        return None
    return mid if mid > 0 else None


def htx_current_mid_usd(payload: object) -> float | None:
    """Current bid/ask mid from HTX merged ticker or BBO. Not mark/last."""

    tick: dict[str, Any] | None = None
    if isinstance(payload, dict):
        raw_tick = payload.get("tick")
        if isinstance(raw_tick, dict):
            tick = raw_tick
        else:
            ticks = payload.get("ticks")
            if isinstance(ticks, list) and ticks and isinstance(ticks[0], dict):
                tick = ticks[0]
    if tick is None:
        return None
    bid = tick.get("bid")
    ask = tick.get("ask")
    bid_px = bid[0] if isinstance(bid, list) and bid else None
    ask_px = ask[0] if isinstance(ask, list) and ask else None
    if bid_px is None or ask_px is None:
        return None
    try:
        bid_f = float(bid_px)
        ask_f = float(ask_px)
    except (TypeError, ValueError):
        return None
    if bid_f <= 0 or ask_f <= 0 or ask_f < bid_f:
        return None
    mid = (bid_f + ask_f) / 2.0
    return mid if mid > 0 else None


def _hyperliquid_ctx_for(payload: object, coin: str) -> dict[str, Any] | None:
    if not isinstance(payload, list) or len(payload) < 2:
        return None
    meta, ctxs = payload[0], payload[1]
    if not isinstance(meta, dict) or not isinstance(ctxs, list):
        return None
    universe = meta.get("universe")
    if not isinstance(universe, list):
        return None
    for index, row in enumerate(universe):
        if isinstance(row, dict) and row.get("name") == coin and index < len(ctxs):
            ctx = ctxs[index]
            return ctx if isinstance(ctx, dict) else None
    return None


ASILLETTO81_CACHE_DIR = Path("var/ops/basis_cache/asilletto81/asset_ctxs")
ASILLETTO81_COMPACT_PATH = Path("var/ops/basis_cache/asilletto81/daily_mark_oracle.json")


def utc_day(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return datetime(ts.year, ts.month, ts.day, tzinfo=UTC)


def truncate_points_to_end(
    points: tuple[tuple[datetime, float], ...] | list[tuple[datetime, float]],
    end: datetime,
) -> tuple[tuple[datetime, float], ...]:
    end_d = utc_day(end)
    return tuple((ts, value) for ts, value in points if utc_day(ts) <= end_d)


def freeze_window_start(
    end: datetime | None = None, *, days: int = BASIS_AWARE_MIN_ALIGNED_DAYS
) -> datetime:
    end_d = utc_day(end or BASIS_AWARE_WINDOW_END_UTC)
    return end_d - timedelta(days=days - 1)


def _asilletto_yyyymmdd(day: datetime) -> str:
    return utc_day(day).strftime("%Y%m%d")


def _asilletto_decompress(payload: bytes) -> str:
    try:
        import lz4.frame
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("lz4 package required for asiletto81 asset_ctxs") from exc
    return lz4.frame.decompress(payload).decode("utf-8")


def _asilletto_last_mark_oracle(csv_text: str, coin: str) -> tuple[float, float] | None:
    last: tuple[float, float] | None = None
    for row in csv.DictReader(io.StringIO(csv_text)):
        if (row.get("coin") or "").strip() != coin:
            continue
        try:
            mark = float(row["mark_px"])
            oracle = float(row["oracle_px"])
        except (KeyError, TypeError, ValueError):
            continue
        if mark <= 0 or oracle <= 0:
            continue
        last = (mark, oracle)
    return last


async def _asilletto_download_day(
    client: httpx.AsyncClient,
    day: datetime,
    *,
    cache_dir: Path,
) -> bytes | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{_asilletto_yyyymmdd(day)}.csv.lz4"
    if path.is_file() and path.stat().st_size > 0:
        return path.read_bytes()
    url = f"{ASILLETTO81_HL_ASSET_CTXS_PREFIX}/{_asilletto_yyyymmdd(day)}.csv.lz4"
    try:
        response = await client.get(url, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code != 200 or not response.content:
        return None
    head = response.content[:32].lstrip()
    if head.startswith((b"<", b"{", b"Invalid")):
        return None
    path.write_bytes(response.content)
    return response.content


def _load_asilletto_compact_basis(
    coin: str,
    *,
    start: datetime,
    end: datetime,
    path: Path | None = None,
) -> list[tuple[datetime, float]] | None:
    """Load precomputed daily (mark-oracle)/oracle if compact cache exists."""
    compact = path or ASILLETTO81_COMPACT_PATH
    if not compact.is_file():
        return None
    try:
        payload = json.loads(compact.read_text())
        rows = payload.get("series", {}).get(coin)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(rows, list) or not rows:
        return None
    start_d = utc_day(start)
    end_d = utc_day(end)
    points: list[tuple[datetime, float]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 4:
            continue
        try:
            day = datetime.fromisoformat(str(row[0])).replace(tzinfo=UTC)
            basis = float(row[3])
        except (TypeError, ValueError):
            continue
        day = utc_day(day)
        if start_d <= day <= end_d:
            points.append((day, basis))
    return points


async def fetch_asilletto81_hyperliquid_basis(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    start: datetime | None = None,
    end: datetime | None = None,
    cache_dir: Path | None = None,
) -> EdgeSeriesFetch:
    """Daily PIT mark−index from HF asiletto81/hyperliquid asset_ctxs."""
    name = f"hyperliquid_basis:{symbol}"
    try:
        coin = hyperliquid_coin(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="asilletto81")

    start_d = utc_day(start or freeze_window_start())
    end_d = utc_day(end or BASIS_AWARE_WINDOW_END_UTC)
    if end_d > ASILLETTO81_HL_ARCHIVE_LAST_UTC:
        end_d = utc_day(ASILLETTO81_HL_ARCHIVE_LAST_UTC)
    if start_d < ASILLETTO81_HL_ARCHIVE_FIRST_UTC:
        start_d = utc_day(ASILLETTO81_HL_ARCHIVE_FIRST_UTC)
    if start_d > end_d:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason="asilletto81 freeze window empty",
            source="asilletto81/hyperliquid asset_ctxs",
        )

    # Prefer day-file cache when cache_dir is explicit (test isolation /
    # operator-supplied lz4 store). Compact JSON is default-cache only.
    compact_points = None
    if cache_dir is None:
        compact_points = _load_asilletto_compact_basis(coin, start=start_d, end=end_d)
    if compact_points is not None:
        return _finish(
            name,
            source="huggingface:asiletto81/hyperliquid compact daily_mark_oracle",
            points=compact_points,
            ok_reason=(
                f"asilletto81 compact daily (mark_px-oracle_px)/oracle_px for {coin}; "
                f"{len(compact_points)} days in [{start_d.date()}→{end_d.date()}]."
            ),
        )

    cache = cache_dir or ASILLETTO81_CACHE_DIR
    points: list[tuple[datetime, float]] = []
    missing = 0
    day = start_d
    while day <= end_d:
        payload = await _asilletto_download_day(client, day, cache_dir=cache)
        if payload is None:
            missing += 1
            day = day + timedelta(days=1)
            continue
        try:
            pair = _asilletto_last_mark_oracle(_asilletto_decompress(payload), coin)
        except Exception:  # noqa: BLE001 - corrupt day file is skipped, never invented.
            missing += 1
            day = day + timedelta(days=1)
            continue
        if pair is None:
            missing += 1
            day = day + timedelta(days=1)
            continue
        mark, oracle = pair
        points.append((day, (mark - oracle) / oracle))
        day = day + timedelta(days=1)

    return _finish(
        name,
        source="huggingface:asiletto81/hyperliquid asset_ctxs mark_px−oracle_px",
        points=points,
        ok_reason=(
            f"asilletto81 daily last (mark_px-oracle_px)/oracle_px for {coin}; "
            f"{len(points)} days in [{start_d.date()}→{end_d.date()}], "
            f"missing={missing} skipped-not-invented. Frozen end "
            f"{BASIS_AWARE_WINDOW_END_UTC.date()}."
        ),
    )


async def fetch_hyperliquid_basis(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    start: datetime | None = None,
    end: datetime | None = None,
    cache_dir: Path | None = None,
    prefer_archive: bool = True,
) -> EdgeSeriesFetch:
    """PIT mark−index: HF asiletto81 archive (frozen window) or skip.

    Live REST metaAndAssetCtxs remains current-only and is never scored as
    a historical tape. Missing archive days are skipped, not invented.
    """
    name = f"hyperliquid_basis:{symbol}"
    if prefer_archive:
        # Use a bare client for HF CDN (not the Hyperliquid base_url).
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as hf_client:
            archive = await fetch_asilletto81_hyperliquid_basis(
                symbol,
                client=hf_client,
                start=start,
                end=end,
                cache_dir=cache_dir,
            )
        if archive.status == "ok" and len(archive.points) >= BASIS_AWARE_MIN_ALIGNED_DAYS:
            return archive
        if archive.status == "ok":
            return EdgeSeriesFetch(
                name=name,
                status="skipped",
                reason=(
                    f"asilletto81 returned {len(archive.points)} days "
                    f"(need >={BASIS_AWARE_MIN_ALIGNED_DAYS} inside freeze "
                    f"ending {BASIS_AWARE_WINDOW_END_UTC.date()}). " + archive.reason
                ),
                source=archive.source,
            )
        archive_note = archive.reason
    else:
        archive_note = "archive fetch disabled"
    try:
        coin = hyperliquid_coin(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="hyperliquid")
    extra = f" Archive note: {archive_note}."
    try:
        response = await _hyperliquid_post_info(client, {"type": "metaAndAssetCtxs"})
        payload = response.json()
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        return _geo_or_http_skip(name, "hyperliquid", exc)
    ctx = _hyperliquid_ctx_for(payload, coin)
    if ctx is not None and ctx.get("markPx") is not None and ctx.get("oraclePx") is not None:
        extra += " Current markPx/oraclePx observed; snapshot only."
    return EdgeSeriesFetch(
        name=name,
        status="skipped",
        reason=HYPERLIQUID_BASIS_UNAVAILABLE + extra,
        source="hyperliquid:/info metaAndAssetCtxs",
    )


async def fetch_bitmex_basis(
    symbol: str,
    *,
    client: httpx.AsyncClient,
) -> EdgeSeriesFetch:
    """Probe for a PIT mark−index / perp-mid−spot-mid tape. Do not invent."""
    name = f"bitmex_basis:{symbol}"
    try:
        contract = bitmex_contract(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="bitmex")
    extra = ""
    try:
        response = await client.get("/api/v1/instrument", params={"symbol": contract})
        response.raise_for_status()
        rows = response.json()
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            row = rows[0]
            if row.get("markPrice") is not None and row.get("indicativeSettlePrice") is not None:
                extra = " Current markPrice/indicativeSettlePrice observed; snapshot only."
        premium = _BITMEX_PREMIUM_INDEX.get(symbol.upper())
        if premium:
            probe = await client.get(
                "/api/v1/trade/bucketed",
                params={
                    "symbol": premium,
                    "binSize": "1d",
                    "count": 1,
                    "reverse": "true",
                    "partial": "false",
                },
            )
            if probe.status_code == 200:
                extra += (
                    f" {premium} historical premium index exists and is not used "
                    "(funding-formula input, not mark−index)."
                )
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        return _geo_or_http_skip(name, "bitmex", exc)
    return EdgeSeriesFetch(
        name=name,
        status="skipped",
        reason=BITMEX_BASIS_UNAVAILABLE + extra,
        source="bitmex:/api/v1/instrument",
    )


async def fetch_htx_basis(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    size: int = HTX_BASIS_SIZE,
) -> EdgeSeriesFetch:
    """Daily mark−index from public HTX klines. Premium index is not used."""
    name = f"htx_basis:{symbol}"
    try:
        contract = htx_contract(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="htx")
    try:
        mark_response = await client.get(
            "/index/market/history/linear_swap_mark_price_kline",
            params={
                "contract_code": contract,
                "period": "1day",
                "size": min(size, HTX_BASIS_SIZE),
            },
        )
        mark_response.raise_for_status()
        index_response = await client.get(
            "/index/market/history/index",
            params={
                "symbol": contract,
                "period": "1day",
                "size": min(size, HTX_BASIS_SIZE),
            },
        )
        index_response.raise_for_status()
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        return _geo_or_http_skip(name, "htx", exc)
    try:
        mark_rows = _htx_kline_rows(mark_response.json())
        index_rows = _htx_kline_rows(index_response.json())
    except (TypeError, ValueError, KeyError) as exc:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason=f"unparsable HTX mark/index kline ({exc})",
            source="htx:/index/market/history",
        )
    index_by_id = {row[0]: row[1] for row in index_rows}
    points: list[tuple[datetime, float]] = []
    for ts_id, mark_close in mark_rows:
        index_close = index_by_id.get(ts_id)
        if index_close is None or index_close <= 0:
            continue
        points.append((_ms_to_dt(ts_id), (mark_close - index_close) / index_close))
    return _finish(
        name,
        source="htx:/index/market/history mark_price_kline−index",
        points=points,
        ok_reason=(
            "HTX public daily mark_price_kline close minus index close "
            "over index (not last-trade; not premium_index). Single-venue "
            "tape; dual-print basis still needs Hyperliquid on the same "
            "window."
        ),
    )


def _htx_kline_rows(payload: object) -> list[tuple[int, float]]:
    if not isinstance(payload, dict):
        raise TypeError("HTX kline payload is not an object")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise TypeError("HTX kline data is not a list")
    parsed: list[tuple[int, float]] = []
    for row in rows:
        if not isinstance(row, dict) or "id" not in row or "close" not in row:
            continue
        ts_id = int(row["id"])
        close = float(row["close"])
        if ts_id <= 0 or close <= 0:
            continue
        parsed.append((ts_id, close))
    return parsed


async def fetch_okx_open_interest(
    symbol: str,
    *,
    client: httpx.AsyncClient,
    period: str = "1H",
    limit_pages: int = 50,
) -> EdgeSeriesFetch:
    name = f"okx_oi:{symbol}"
    try:
        inst = okx_swap(symbol)
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="okx")
    points: list[tuple[datetime, float]] = []
    end: str | None = None
    try:
        for _ in range(limit_pages):
            params: dict[str, Any] = {"instId": inst, "period": period, "limit": 100}
            if end is not None:
                params["end"] = end
            response = await client.get(
                "/api/v5/rubik/stat/contracts/open-interest-history", params=params
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            new = 0
            oldest_ms: int | None = None
            for row in rows:
                if not isinstance(row, list) or len(row) < 2:
                    continue
                ts = _ms_to_dt(row[0])
                points.append((ts, float(row[1])))
                new += 1
                raw_ms = int(row[0])
                oldest_ms = raw_ms if oldest_ms is None else min(oldest_ms, raw_ms)
            if new == 0 or oldest_ms is None:
                break
            next_end = str(oldest_ms - 1)
            if next_end == end:
                break
            end = next_end
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        return _geo_or_http_skip(name, "okx", exc)
    return _finish(
        name,
        source="okx:/api/v5/rubik/stat/contracts/open-interest-history",
        points=points,
        ok_reason="OKX rubik 1h open-interest-history (public, paginated)",
    )


async def fetch_okx_liquidations(
    symbol: str,
    *,
    client: httpx.AsyncClient,
) -> EdgeSeriesFetch:
    name = f"okx_liquidation:{symbol}"
    try:
        uly = okx_swap(symbol).removesuffix("-SWAP")
    except ValueError as exc:
        return EdgeSeriesFetch(name=name, status="skipped", reason=str(exc), source="okx")
    try:
        response = await client.get(
            "/api/v5/public/liquidation-orders",
            params={"instType": "SWAP", "uly": uly, "state": "filled"},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        return _geo_or_http_skip(name, "okx", exc)
    rows = payload.get("data") if isinstance(payload, dict) else None
    details: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("details"), list):
                details.extend(item for item in row["details"] if isinstance(item, dict))
    if len(details) < 2:
        return EdgeSeriesFetch(
            name=name,
            status="skipped",
            reason=(
                "OKX liquidation-orders returned too few fills for a historical "
                "hourly z (typically hours of recent prints, not 90–180d)."
            ),
            source="okx",
        )
    times = [_ms_to_dt(item.get("ts") or item.get("time") or 0) for item in details]
    span = (max(times) - min(times)).total_seconds()
    return EdgeSeriesFetch(
        name=name,
        status="skipped",
        reason=(
            f"OKX liquidation-orders span {span / 3600:.1f}h across {len(details)} "
            "fills — not a historical aggregate. Skip rather than invent a z."
        ),
        source="okx",
        first=min(times),
        last=max(times),
    )


async def fetch_edge_bundle(
    symbols: tuple[str, ...],
    *,
    timeout: float = 20.0,
) -> EdgeBundle:
    """Best-effort public series. Binance first; OKX if Binance is skipped."""
    bundle = EdgeBundle()
    async with httpx.AsyncClient(base_url=BINANCE_FAPI_BASE, timeout=timeout) as binance:
        for symbol in symbols:
            funding = await fetch_binance_funding(symbol, client=binance)
            bundle.notes.append(funding)
            oi = await fetch_binance_open_interest(symbol, client=binance)
            bundle.notes.append(oi)
            liq = await fetch_binance_liquidations(symbol, client=binance)
            bundle.notes.append(liq)
            if funding.status == "ok":
                bundle.funding[symbol.upper()] = funding.points
            if oi.status == "ok":
                bundle.open_interest[symbol.upper()] = oi.points
            if liq.status == "ok":
                bundle.liquidation[symbol.upper()] = liq.points

    need_okx_funding = any(symbol.upper() not in bundle.funding for symbol in symbols)
    need_okx_oi = any(symbol.upper() not in bundle.open_interest for symbol in symbols)
    need_okx_liq_note = True
    if need_okx_funding or need_okx_oi or need_okx_liq_note:
        async with httpx.AsyncClient(base_url=OKX_BASE, timeout=timeout) as okx:
            for symbol in symbols:
                if symbol.upper() not in bundle.funding:
                    funding = await fetch_okx_funding(symbol, client=okx)
                    bundle.notes.append(funding)
                    if funding.status == "ok":
                        bundle.funding[symbol.upper()] = funding.points
                if symbol.upper() not in bundle.open_interest:
                    oi = await fetch_okx_open_interest(symbol, client=okx)
                    bundle.notes.append(oi)
                    if oi.status == "ok":
                        bundle.open_interest[symbol.upper()] = oi.points
                if symbol.upper() not in bundle.liquidation:
                    liq = await fetch_okx_liquidations(symbol, client=okx)
                    bundle.notes.append(liq)
                    if liq.status == "ok":
                        bundle.liquidation[symbol.upper()] = liq.points
    return bundle
