"""Yahoo Finance daily OHLC (yfinance-compatible), labeled non-Kraken.

This is an optional longer-history A/B for daily robustness. It is **not**
the paper path. Closes can differ from Kraken Spot; weekends and exchange
holidays appear as Yahoo chooses; volume is Yahoo's BTC-USD / ETH-USD
series, not Kraken Spot volume.

Uses the public chart endpoint that yfinance also reads
(``GET https://query1.finance.yahoo.com/v8/finance/chart/{ticker}``).
No ``yfinance`` package dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from traderstack.candles import Candle

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_SOURCE = "yahoo_finance_yfinance"
# 2014-09-17T00:00:00Z: first Yahoo BTC-USD daily. ETH starts later; Yahoo clips.
# ``range=max`` downsamples crypto to monthly; period1/period2 keeps 1d.
YAHOO_PERIOD1_UNIX = 1_410_912_000
YAHOO_PERIOD1_ISO = "2014-09-17T00:00:00+00:00"
# Browser-like UA: the chart endpoint often 429s a bare Python client.
_YAHOO_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; traderstack-daily-robustness/0.1; research-only)"),
    "Accept": "application/json",
}

YAHOO_TICKERS: dict[str, str] = {
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
    "BTC/USD": "BTC-USD",
    "ETH/USD": "ETH-USD",
}


def yahoo_symbol(ticker: str) -> str:
    """Canonical non-Kraken symbol label used in reports (BTC-USD, not BTC/USD)."""
    key = ticker.upper()
    mapped = YAHOO_TICKERS.get(key, key)
    return mapped.replace("/", "-")


def parse_yahoo_chart(
    payload: object,
    *,
    symbol: str,
    interval: str = "1d",
) -> tuple[Candle, ...]:
    """Reduce a Yahoo chart JSON payload to committed daily candles.

    Rows with a missing close are dropped (Yahoo pads some calendars with
    nulls). The last bar is dropped when its date is today UTC so an
    uncommitted session cannot leak into a backtest.
    """
    if not isinstance(payload, dict):
        raise TypeError("Yahoo chart payload must be an object")
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise TypeError("Yahoo chart payload missing chart")
    error = chart.get("error")
    if error:
        raise ValueError(f"Yahoo chart error: {error}")
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        raise ValueError("Yahoo chart returned no result")
    result = results[0]
    if not isinstance(result, dict):
        raise TypeError("Yahoo chart result is not an object")
    timestamps = result.get("timestamp")
    if not isinstance(timestamps, list) or not timestamps:
        raise ValueError("Yahoo chart missing timestamps")
    indicators = result.get("indicators")
    if not isinstance(indicators, dict):
        raise TypeError("Yahoo chart missing indicators")
    quotes = indicators.get("quote")
    if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
        raise TypeError("Yahoo chart missing quote")
    quote = quotes[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    if not (
        len(opens) == len(highs) == len(lows) == len(closes) == len(volumes) == len(timestamps)
    ):
        raise ValueError("Yahoo chart arrays are misaligned")

    labeled = yahoo_symbol(symbol)
    candles: list[Candle] = []
    for ts, open_, high, low, close, volume in zip(
        timestamps, opens, highs, lows, closes, volumes, strict=True
    ):
        if close is None or open_ is None or high is None or low is None:
            continue
        open_f = float(open_)
        high_f = float(high)
        low_f = float(low)
        close_f = float(close)
        if open_f <= 0 or close_f <= 0:
            continue
        # Yahoo crypto prints often violate OHLC containment after splits /
        # adjustments. Expand high/low to contain open/close rather than
        # drop a decade of bars. This A/B is already labeled non-Kraken.
        high_f = max(high_f, open_f, close_f)
        low_f = min(low_f if low_f > 0 else min(open_f, close_f), open_f, close_f)
        if high_f < low_f:
            continue
        opened = datetime.fromtimestamp(int(ts), tz=UTC)
        candles.append(
            Candle(
                symbol=labeled,
                interval=interval,
                opened_at=opened,
                open=open_f,
                high=high_f,
                low=low_f,
                close=close_f,
                volume=float(volume or 0.0),
            )
        )
    candles.sort(key=lambda candle: candle.opened_at)
    if candles:
        today = datetime.now(UTC).date()
        if candles[-1].opened_at.date() >= today:
            candles = candles[:-1]
    return tuple(candles)


async def download_yahoo_daily(
    ticker: str,
    *,
    range_label: str = "max",
    interval: str = "1d",
    client: httpx.AsyncClient | None = None,
) -> tuple[Candle, ...]:
    """Fetch the longest Yahoo daily series the public chart API will return.

    ``range=max`` is *not* used: Yahoo then downsamples crypto to monthly
    (``dataGranularity=1mo``). ``period1``/``period2`` keeps ``interval=1d``.
    ``range_label`` is accepted for compatibility and ignored.
    """
    del range_label
    yahoo_ticker = YAHOO_TICKERS.get(ticker.upper(), ticker)
    period2 = int(datetime.now(UTC).timestamp())
    params = {
        "interval": interval,
        "period1": str(YAHOO_PERIOD1_UNIX),
        "period2": str(period2),
    }
    url = YAHOO_CHART_URL.format(ticker=yahoo_ticker)

    async def _get(active: httpx.AsyncClient) -> object:
        response = await active.get(url, params=params, headers=_YAHOO_HEADERS)
        response.raise_for_status()
        return response.json()

    if client is not None:
        payload = await _get(client)
    else:
        async with httpx.AsyncClient(timeout=30) as owned:
            payload = await _get(owned)
    return parse_yahoo_chart(payload, symbol=yahoo_ticker, interval=interval)


async def download_yahoo_histories(
    tickers: tuple[str, ...] = ("BTC-USD", "ETH-USD"),
    *,
    range_label: str = "max",
    client: httpx.AsyncClient | None = None,
) -> dict[str, tuple[Candle, ...]]:
    """Keys are ``TICKER@1d`` using the non-Kraken Yahoo symbol."""
    owned = client is None
    active = client or httpx.AsyncClient(timeout=30)
    try:
        out: dict[str, tuple[Candle, ...]] = {}
        for ticker in tickers:
            candles = await download_yahoo_daily(ticker, range_label=range_label, client=active)
            if candles:
                out[f"{candles[0].symbol}@{candles[0].interval}"] = candles
        return out
    finally:
        if owned:
            await active.aclose()
