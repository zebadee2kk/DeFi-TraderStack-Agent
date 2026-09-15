"""Binance Spot daily klines, labeled non-Kraken / report-only.

``GET https://api.binance.com/api/v3/klines`` is the requested global
Spot path. This environment receives HTTP 451 (geo-restricted) from
that host; ``https://api.binance.us/api/v3/klines`` is the reachable
public Spot fallback and is labeled **Binance.US**, not Binance.com.

Quote is USDT (``BTCUSDT`` / ``ETHUSDT``), not Kraken USD. Closes can
differ. This module never enters a promotion average with Kraken.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from traderstack.candles import Candle, interval_to_seconds

BINANCE_COM_BASE = "https://api.binance.com"
BINANCE_US_BASE = "https://api.binance.us"
BINANCE_KLINES_PATH = "/api/v3/klines"
BINANCE_INTERVAL = "1d"
BINANCE_KLINE_LIMIT = 1000
DEFAULT_BINANCE_SYMBOLS = ("BTCUSDT", "ETHUSDT")
BINANCE_SOURCE_COM = "binance_com_spot"
BINANCE_SOURCE_US = "binance_us_spot"
BINANCE_SOURCE_RESTRICTED = "binance_com_http_451"

# Lowest published Binance.US Spot taker is typically 10 bps; we still
# charge the same Kraken-tier research costs (#138) rather than invent a
# cheaper venue schedule or a rebate.
BINANCE_TAKER_BPS_NOTE = (
    "Binance.US Spot published taker is typically 10 bps at the lowest "
    "listed tier. This print uses the same research costs as the Kraken "
    "print: `max(PRETRADE_FEE_BPS, PAPER_FEE_TIER taker)` + "
    "`PRETRADE_SLIPPAGE_BPS` (exact numbers in the report's fee tier "
    "line; gate C doubles both) so costs stay comparable. Binance.US's "
    "own taker is not substituted and no maker rebate is assumed. Not a "
    "VIP study. Quote is USDT, not USD."
)


def parse_binance_kline(
    row: object,
    *,
    symbol: str,
    interval: str = BINANCE_INTERVAL,
) -> Candle:
    """Reduce one Binance kline array to a committed daily candle."""
    if not isinstance(row, list) or len(row) < 6:
        raise TypeError("Binance kline row must be a list of at least 6 fields")
    opened_ms = int(row[0])
    open_f = float(row[1])
    high_f = float(row[2])
    low_f = float(row[3])
    close_f = float(row[4])
    volume_f = float(row[5])
    if open_f <= 0 or high_f <= 0 or low_f <= 0 or close_f <= 0:
        raise ValueError("Binance kline prices must be positive")
    high_f = max(high_f, open_f, close_f)
    low_f = min(low_f, open_f, close_f)
    return Candle(
        symbol=symbol.upper(),
        interval=interval,
        opened_at=datetime.fromtimestamp(opened_ms / 1000.0, tz=UTC),
        open=open_f,
        high=high_f,
        low=low_f,
        close=close_f,
        volume=volume_f,
    )


def parse_binance_klines(
    payload: object,
    *,
    symbol: str,
    interval: str = BINANCE_INTERVAL,
    drop_uncommitted_today: bool = True,
) -> tuple[Candle, ...]:
    """Parse a klines JSON array. Drops today's UTC bar when still open."""
    if isinstance(payload, dict):
        message = payload.get("msg") or payload.get("message") or str(payload)
        raise TypeError(f"Binance klines error: {message}")
    if not isinstance(payload, list):
        raise TypeError("Binance klines payload must be an array")
    candles = [parse_binance_kline(row, symbol=symbol, interval=interval) for row in payload]
    candles.sort(key=lambda candle: candle.opened_at)
    if drop_uncommitted_today and candles:
        candles = _drop_uncommitted(candles, interval=interval)
    return tuple(candles)


def _drop_uncommitted(candles: list[Candle], *, interval: str) -> list[Candle]:
    """Drop the last bar when its close is still in the future."""
    if not candles:
        return candles
    if interval == "1d":
        today = datetime.now(UTC).date()
        if candles[-1].opened_at.date() >= today:
            return candles[:-1]
        return candles
    seconds = interval_to_seconds(interval)
    close_at = candles[-1].opened_at + timedelta(seconds=seconds)
    if close_at > datetime.now(UTC):
        return candles[:-1]
    return candles


async def _get_klines(
    client: httpx.AsyncClient,
    *,
    symbol: str,
    end_time_ms: int | None,
    limit: int,
    interval: str = BINANCE_INTERVAL,
) -> object:
    params: dict[str, str | int] = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit,
    }
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    response = await client.get(BINANCE_KLINES_PATH, params=params)
    response.raise_for_status()
    return response.json()


async def download_binance_spot_daily(
    symbol: str,
    *,
    end_before: datetime | None = None,
    max_candles: int = 720,
    client: httpx.AsyncClient | None = None,
    bases: tuple[str, ...] = (BINANCE_COM_BASE, BINANCE_US_BASE),
    interval: str = BINANCE_INTERVAL,
) -> tuple[tuple[Candle, ...], str, list[str]]:
    """Fetch one Spot series. Tries ``api.binance.com`` then ``.us``.

    Default interval is daily. ``4h`` / ``1h`` use the same hosts and
    the same older-slice ``end_before`` rule. Returns
    ``(candles, source_label, notes)``. An empty series is a successful
    research outcome — it is not treated as confirmation.
    """
    notes: list[str] = []
    end_ms: int | None = None
    if end_before is not None:
        if end_before.tzinfo is None:
            end_before = end_before.replace(tzinfo=UTC)
        # Inclusive last open is the calendar day before ``end_before``.
        last_open = end_before.timestamp() - 1.0
        end_ms = int(last_open * 1000.0)

    last_error = "no Binance Spot host attempted"
    hosts = (("injected", ""),) if client is not None else tuple((base, base) for base in bases)
    for label, base in hosts:
        owned = client is None
        active = client or httpx.AsyncClient(base_url=base, timeout=30)
        try:
            payload = await _get_klines(
                active,
                symbol=symbol,
                end_time_ms=end_ms,
                limit=min(BINANCE_KLINE_LIMIT, max(max_candles, 1) + 5),
                interval=interval,
            )
        except httpx.HTTPStatusError as exc:
            last_error = f"{base or label} HTTP {exc.response.status_code}"
            notes.append(f"{symbol}: {last_error}")
            if exc.response.status_code == 451:
                notes.append(
                    f"{base or label} is geo-restricted (HTTP 451); not treated as confirmation."
                )
            if not owned:
                break
            continue
        except (OSError, TypeError, ValueError, httpx.HTTPError) as exc:
            last_error = f"{base or label}: {exc}"
            notes.append(f"{symbol}: {last_error}")
            if not owned:
                break
            continue
        finally:
            if owned:
                await active.aclose()

        try:
            candles = parse_binance_klines(payload, symbol=symbol, interval=interval)
        except (TypeError, ValueError) as exc:
            last_error = f"{base or label} parse failed: {exc}"
            notes.append(f"{symbol}: {last_error}")
            if not owned:
                break
            continue
        if end_before is not None:
            candles = tuple(item for item in candles if item.opened_at < end_before)
        if max_candles and len(candles) > max_candles:
            candles = candles[-max_candles:]
        host = str(active.base_url) if not owned else base
        source = BINANCE_SOURCE_US if "binance.us" in host else BINANCE_SOURCE_COM
        if source == BINANCE_SOURCE_US and client is None and BINANCE_COM_BASE in bases:
            notes.append(
                f"{symbol}: {BINANCE_COM_BASE} unavailable or restricted; "
                f"using {base} (labeled Binance.US, not Binance.com)."
            )
        return candles, source, notes

    notes.append(f"{symbol}: Binance Spot {interval} skipped ({last_error})")
    return (), BINANCE_SOURCE_RESTRICTED, notes


async def download_binance_spot_histories(
    symbols: tuple[str, ...] = DEFAULT_BINANCE_SYMBOLS,
    *,
    end_before: datetime | None = None,
    max_candles: int = 720,
    client: httpx.AsyncClient | None = None,
    bases: tuple[str, ...] = (BINANCE_COM_BASE, BINANCE_US_BASE),
    interval: str = BINANCE_INTERVAL,
) -> tuple[dict[str, tuple[Candle, ...]], str | None, list[str]]:
    """Keys are ``SYMBOL@interval``. ``source`` is the host that served a series."""
    histories: dict[str, tuple[Candle, ...]] = {}
    notes: list[str] = []
    source: str | None = None
    for symbol in symbols:
        candles, fetched_source, item_notes = await download_binance_spot_daily(
            symbol,
            end_before=end_before,
            max_candles=max_candles,
            client=client,
            bases=bases,
            interval=interval,
        )
        notes.extend(item_notes)
        if not candles:
            continue
        histories[f"{candles[0].symbol}@{candles[0].interval}"] = candles
        source = fetched_source
        first = candles[0].opened_at.isoformat()
        last = candles[-1].opened_at.isoformat()
        notes.append(
            f"{candles[0].symbol}@{candles[0].interval}: {len(candles)} committed "
            f"{fetched_source} {candles[0].interval} bars {first} → {last} "
            "(non-Kraken; report-only)"
        )
    return histories, source, notes
