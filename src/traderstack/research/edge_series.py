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
* Bybit ``GET /v5/market/funding/history`` — public when reachable; this
  environment typically gets HTTP 403 (CloudFront country block).
* Deribit ``public/get_funding_rate_history`` is reachable but returns
  the 8h interest restated every hour. Using each row as a settlement
  would invent 8× carry — not wired.
* Gate / Bitget / MEXC / dYdX public funding REST can also respond here;
  they are not blended into this adapter. See the edge-status memo.

Cross-venue divergence is not built here (needs two aligned venues).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

BINANCE_FAPI_BASE = "https://fapi.binance.com"
OKX_BASE = "https://www.okx.com"
BYBIT_BASE = "https://api.bybit.com"
HYPERLIQUID_BASE = "https://api.hyperliquid.xyz"

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
HYPERLIQUID_PAGE_SIZE = 500
HYPERLIQUID_DEFAULT_LOOKBACK_DAYS = 180

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
            detail = (
                "HTTP 403 (CloudFront / country block — unavailable in this environment)"
            )
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
        return EdgeSeriesFetch(
            name=name, status="skipped", reason=str(exc), source="hyperliquid"
        )
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    cursor = (
        start_ms
        if start_ms is not None
        else now_ms - lookback_days * 24 * 3600 * 1000
    )
    points: list[tuple[datetime, float]] = []
    try:
        for _ in range(limit_pages):
            response = await client.post(
                "/info",
                json={"type": "fundingHistory", "coin": coin, "startTime": cursor},
            )
            response.raise_for_status()
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
    except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
        return _geo_or_http_skip(name, "hyperliquid", exc)
    return _finish(
        name,
        source="hyperliquid:/info fundingHistory",
        points=points,
        ok_reason=(
            "Hyperliquid public fundingHistory (hourly; paginated; "
            f"lookback {lookback_days}d)"
        ),
    )


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
