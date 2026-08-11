import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import websockets

from traderstack.market.models import MarketSource, MarketTick, ReferencePrice

COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}


class KrakenTickerProvider:
    def __init__(self, url: str = "wss://ws.kraken.com/v2") -> None:
        self.url = url

    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "params": {"channel": "ticker", "symbol": list(symbols), "snapshot": True},
                    }
                )
            )
            async for raw in ws:
                message = json.loads(raw)
                tick = parse_kraken_ticker(message)
                if tick is not None:
                    yield tick


def parse_kraken_ticker(message: dict[str, object]) -> MarketTick | None:
    if message.get("channel") != "ticker":
        return None
    data = message.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    row = data[0]
    symbol = row.get("symbol")
    bid = row.get("bid")
    ask = row.get("ask")
    last = row.get("last")
    if not isinstance(symbol, str):
        return None
    if not isinstance(bid, (int, float)):
        return None
    if not isinstance(ask, (int, float)):
        return None
    if not isinstance(last, (int, float)):
        return None
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol=symbol,
        observed_at=datetime.now(UTC),
        bid=float(bid),
        ask=float(ask),
        last=float(last),
    )


class CoinGeckoPriceProvider:
    def __init__(self, api_key: str | None = None, base_url: str = "https://api.coingecko.com/api/v3") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        ids = [COINGECKO_IDS[a] for a in assets if a in COINGECKO_IDS]
        if not ids:
            return []
        headers = {"x-cg-demo-api-key": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/simple/price",
                params={"ids": ",".join(ids), "vs_currencies": "usd"},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        now = datetime.now(UTC)
        reverse = {v: k for k, v in COINGECKO_IDS.items()}
        prices: list[ReferencePrice] = []
        for coin_id, row in payload.items():
            if coin_id in reverse and isinstance(row, dict) and isinstance(row.get("usd"), (int, float)):
                prices.append(
                    ReferencePrice(
                        source=MarketSource.COINGECKO,
                        asset=reverse[coin_id],
                        observed_at=now,
                        price=float(row["usd"]),
                    )
                )
        return prices


class CoinMarketCapPriceProvider:
    def __init__(self, api_key: str | None = None, base_url: str = "https://pro-api.coinmarketcap.com") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        path = "/v3/cryptocurrency/quotes/latest" if self.api_key else "/public-api/v3/cryptocurrency/quotes/latest"
        headers = {"X-CMC_PRO_API_KEY": self.api_key} if self.api_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                params={"symbol": ",".join(assets), "convert": "USD"},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", {})
        now = datetime.now(UTC)
        prices: list[ReferencePrice] = []
        if isinstance(data, dict):
            for asset, row in data.items():
                if not isinstance(row, dict):
                    continue
                quote = row.get("quote")
                usd = quote.get("USD") if isinstance(quote, dict) else None
                price = usd.get("price") if isinstance(usd, dict) else None
                if isinstance(price, (int, float)):
                    prices.append(
                        ReferencePrice(
                            source=MarketSource.COINMARKETCAP,
                            asset=str(asset).upper(),
                            observed_at=now,
                            price=float(price),
                        )
                    )
        return prices
