"""Venue symbol helpers for paper-research edge feeds.

Maps allowlisted assets (``BTC``) onto USDT-margined futures symbols
(``BTCUSDT``) used by Binance and Bybit public streams. These venues are
never an execution destination in this repo.
"""

from __future__ import annotations


def futures_symbol(asset: str, quote: str = "USDT") -> str:
    return f"{asset.strip().upper()}{quote.strip().upper()}"


def asset_from_futures_symbol(symbol: str, quote: str = "USDT") -> str | None:
    raw = symbol.strip().upper()
    suffix = quote.strip().upper()
    if raw.endswith(suffix) and len(raw) > len(suffix):
        return raw[: -len(suffix)]
    return None
