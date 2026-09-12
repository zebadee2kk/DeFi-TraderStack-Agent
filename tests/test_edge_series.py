from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.research.candidates import FeatureZVoter
from traderstack.research.edge_series import (
    BITMEX_BASIS_UNAVAILABLE,
    BITMEX_SUNSET_NOTE,
    BASIS_AWARE_MIN_ALIGNED_DAYS,
    BASIS_AWARE_WINDOW_END_UTC,
    HYPERLIQUID_BASIS_UNAVAILABLE,
    bitmex_current_mid_usd,
    fetch_binance_funding,
    fetch_binance_liquidations,
    fetch_bitmex_basis,
    fetch_bitmex_funding,
    fetch_bybit_funding,
    fetch_htx_basis,
    fetch_htx_funding,
    fetch_asilletto81_hyperliquid_basis,
    fetch_hyperliquid_basis,
    fetch_hyperliquid_funding,
    fetch_okx_funding,
    hyperliquid_current_mid_usd,
)
from traderstack.strategies import Regime


@pytest.mark.asyncio
async def test_binance_funding_records_http_451_as_skip() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(451, text="unavailable")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=transport
    ) as client:
        result = await fetch_binance_funding("BTC/USD", client=client)
    assert result.status == "skipped"
    assert "451" in result.reason


@pytest.mark.asyncio
async def test_binance_liquidations_skip_short_span() -> None:
    now = int(datetime(2026, 9, 12, tzinfo=UTC).timestamp() * 1000)

    async def handler(_request: httpx.Request) -> httpx.Response:
        rows = [
            {"time": now, "origQty": "1.0", "side": "SELL"},
            {"time": now + 3_600_000, "origQty": "2.0", "side": "BUY"},
        ]
        return httpx.Response(200, json=rows)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=transport
    ) as client:
        result = await fetch_binance_liquidations("BTC/USD", client=client)
    assert result.status == "skipped"
    assert "not a historical" in result.reason


@pytest.mark.asyncio
async def test_bybit_funding_records_http_403_as_skip() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            text=(
                "The Amazon CloudFront distribution is configured to block access from your country"
            ),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.bybit.com", transport=transport) as client:
        result = await fetch_bybit_funding("BTC/USD", client=client)
    assert result.status == "skipped"
    assert "403" in result.reason
    assert "country" in result.reason.lower() or "CloudFront" in result.reason


@pytest.mark.asyncio
async def test_bybit_funding_parses_pages_when_reachable() -> None:
    pages = [
        {
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "fundingRate": "0.0003",
                        "fundingRateTimestamp": "2000000",
                    },
                    {
                        "symbol": "BTCUSDT",
                        "fundingRate": "0.0001",
                        "fundingRateTimestamp": "1000000",
                    },
                ]
            },
        },
        {"retCode": 0, "result": {"list": []}},
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.bybit.com", transport=transport) as client:
        result = await fetch_bybit_funding("BTC/USD", client=client, limit_pages=3)
    assert result.status == "ok"
    assert len(result.points) == 2
    assert result.points[0][1] == 0.0001
    assert result.points[1][1] == 0.0003


@pytest.mark.asyncio
async def test_hyperliquid_funding_retries_http_429() -> None:
    pages = [
        httpx.Response(429, text="too many requests"),
        httpx.Response(
            200,
            json=[{"coin": "BTC", "fundingRate": "0.0004", "time": 1_000_000}],
        ),
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return pages[idx]

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz", transport=transport
    ) as client:
        result = await fetch_hyperliquid_funding(
            "BTC/USD", client=client, start_ms=1, limit_pages=2
        )
    assert result.status == "ok"
    assert len(result.points) == 1
    assert result.points[0][1] == 0.0004
    assert calls["n"] >= 2


@pytest.mark.asyncio
async def test_hyperliquid_funding_parses_pages() -> None:
    pages = [
        [
            {"coin": "ETH", "fundingRate": "0.0001", "premium": "0.0", "time": 1_000_000},
            {"coin": "ETH", "fundingRate": "-0.0002", "premium": "0.0", "time": 2_000_000},
        ],
        [],
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz", transport=transport
    ) as client:
        result = await fetch_hyperliquid_funding(
            "ETH/USD", client=client, start_ms=1, limit_pages=3
        )
    assert result.status == "ok"
    assert len(result.points) == 2
    assert result.points[0][1] == 0.0001
    assert result.points[1][1] == -0.0002
    assert "fundingHistory" in result.source


@pytest.mark.asyncio
async def test_okx_funding_parses_pages() -> None:
    pages = [
        {
            "code": "0",
            "data": [
                {"fundingTime": "1789200000000", "fundingRate": "0.0001"},
                {"fundingTime": "1789171200000", "fundingRate": "-0.0002"},
            ],
        },
        {"code": "0", "data": []},
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://www.okx.com", transport=transport) as client:
        result = await fetch_okx_funding("ETH/USD", client=client)
    assert result.status == "ok"
    assert len(result.points) == 2
    assert result.points[0][1] == -0.0002


@pytest.mark.asyncio
async def test_bitmex_funding_uses_settlement_not_daily_restatement() -> None:
    pages = [
        [
            {
                "timestamp": "2024-09-22T04:00:00.000Z",
                "symbol": "XBTUSD",
                "fundingInterval": "2000-01-01T08:00:00.000Z",
                "fundingRate": 0.0001,
                "fundingRateDaily": 0.0003,
            },
            {
                "timestamp": "2024-09-22T12:00:00.000Z",
                "symbol": "XBTUSD",
                "fundingInterval": "2000-01-01T08:00:00.000Z",
                "fundingRate": -0.0002,
                "fundingRateDaily": -0.0006,
            },
        ],
        [],
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://www.bitmex.com", transport=transport) as client:
        result = await fetch_bitmex_funding(
            "BTC/USD",
            client=client,
            start_iso="2024-09-22T00:00:00.000Z",
        )
    assert result.status == "ok"
    assert len(result.points) == 2
    assert result.points[0][1] == 0.0001
    assert result.points[1][1] == -0.0002
    assert 0.0003 not in {point[1] for point in result.points}
    assert "fundingRateDaily" in result.reason
    assert "/api/v1/funding" in result.source
    assert "sunset" in result.reason.lower()
    assert "23 September 2026" in BITMEX_SUNSET_NOTE


@pytest.mark.asyncio
async def test_htx_funding_uses_funding_rate_not_premium() -> None:
    pages = [
        {
            "status": "ok",
            "data": {
                "total_page": 2,
                "total_size": 2,
                "data": [
                    {
                        "funding_time": "1727006400000",
                        "funding_rate": "0.0001",
                        "realized_rate": None,
                        "avg_premium_index": "0.012",
                    },
                    {
                        "funding_time": "1726977600000",
                        "funding_rate": "-0.0002",
                        "realized_rate": None,
                        "avg_premium_index": "-0.003",
                    },
                ],
            },
        },
        {"status": "ok", "data": {"total_page": 2, "total_size": 2, "data": []}},
    ]
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.hbdm.com", transport=transport) as client:
        result = await fetch_htx_funding(
            "BTC/USD",
            client=client,
            lookback_days=800,
            limit_pages=4,
        )
    assert result.status == "ok"
    assert len(result.points) == 2
    assert result.points[0][1] == -0.0002
    assert result.points[1][1] == 0.0001
    assert 0.012 not in {point[1] for point in result.points}
    assert "avg_premium_index" in result.reason
    assert "swap_historical_funding_rate" in result.source


@pytest.mark.asyncio
async def test_htx_basis_is_mark_minus_index_not_premium() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if "mark_price_kline" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "data": [
                        {
                            "id": 1726963200,
                            "open": "100",
                            "close": "102",
                            "high": "103",
                            "low": "99",
                        }
                    ],
                },
            )
        if "history/index" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "data": [
                        {
                            "id": 1726963200,
                            "open": 100.0,
                            "close": 100.0,
                            "high": 101.0,
                            "low": 99.0,
                        }
                    ],
                },
            )
        return httpx.Response(404, text="no")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.hbdm.com", transport=transport) as client:
        result = await fetch_htx_basis("BTC/USD", client=client)
    assert result.status == "ok"
    assert len(result.points) == 1
    assert result.points[0][1] == pytest.approx(0.02)
    assert "premium" not in result.source
    assert "mark_price_kline" in result.source


@pytest.mark.asyncio
async def test_hyperliquid_basis_skips_current_only_and_refuses_premium() -> None:
    payload = [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
        [
            {
                "markPx": "77130.0",
                "oraclePx": "77172.1",
                "midPx": "77129.5",
                "premium": "-0.0005",
            },
            {"markPx": "2524.3", "oraclePx": "2525.43", "premium": "-0.0004"},
        ],
    ]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz", transport=transport
    ) as client:
        result = await fetch_hyperliquid_basis(
            "BTC/USD", client=client, prefer_archive=False
        )
    assert result.status == "skipped"
    assert result.points == ()
    assert "UNAVAILABLE" in result.reason
    assert "premium" in result.reason.lower()
    assert HYPERLIQUID_BASIS_UNAVAILABLE.split(".")[0] in result.reason
    assert "Current markPx/oraclePx observed" in result.reason
    assert result.points == ()
    snapshot = hyperliquid_current_mid_usd(payload, "BTC")
    assert snapshot == pytest.approx(77129.5)
    # Snapshot mid is for the paper soak only — basis fetch stays skipped.


@pytest.mark.asyncio
async def test_bitmex_basis_skips_and_refuses_premium_index() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/instrument"):
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "XBTUSD",
                        "markPrice": 77156.96,
                        "indicativeSettlePrice": 77155.45,
                        "midPrice": 77137.4,
                    }
                ],
            )
        if request.url.path.endswith("/trade/bucketed"):
            return httpx.Response(
                200,
                json=[
                    {
                        "timestamp": "2026-09-12T00:00:00.000Z",
                        "symbol": ".XBTUSDPI",
                        "close": -0.000299,
                    }
                ],
            )
        return httpx.Response(404, text="no")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://www.bitmex.com", transport=transport) as client:
        result = await fetch_bitmex_basis("BTC/USD", client=client)
    assert result.status == "skipped"
    assert result.points == ()
    assert "UNAVAILABLE" in result.reason
    assert BITMEX_BASIS_UNAVAILABLE.split(".")[0] in result.reason
    assert "funding-formula" in result.reason
    assert ".XBTUSDPI" in result.reason
    assert any(path.endswith("/instrument") for path in calls)
    assert bitmex_current_mid_usd(
        [{"symbol": "XBTUSD", "markPrice": 77156.96, "midPrice": 77137.4}]
    ) == pytest.approx(77137.4)


@pytest.mark.asyncio
async def test_bitmex_funding_records_http_error_as_skip() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://www.bitmex.com", transport=transport) as client:
        result = await fetch_bitmex_funding("ETH/USD", client=client)
    assert result.status == "skipped"
    assert "403" in result.reason


def test_feature_z_voter_uses_per_symbol_series() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = tuple(
        Candle(
            symbol="BTC/USD",
            interval="1h",
            opened_at=start + timedelta(hours=index),
            open=200.0 - 0.25 * index,
            high=201.0 - 0.25 * index,
            low=199.0 - 0.25 * index,
            close=200.0 - 0.25 * index,
            volume=1_000 + index,
        )
        for index in range(40)
    )
    btc = tuple((c.opened_at, 0.0 if index < 39 else 8.0) for index, c in enumerate(candles))
    eth = tuple((c.opened_at, 0.0 if index < 39 else -8.0) for index, c in enumerate(candles))
    voter = FeatureZVoter(
        strategy_id="funding_z_fade",
        feature_name="funding_z",
        values_by_symbol=(("BTC/USD", btc), ("ETH/USD", eth)),
        lookback=20,
        entry_z=1.5,
        fade=True,
    )
    btc_signal = voter.evaluate(candles, Regime.RANGE)
    eth_candles = tuple(c.model_copy(update={"symbol": "ETH/USD"}) for c in candles)
    eth_signal = voter.evaluate(eth_candles, Regime.RANGE)
    assert btc_signal.side is not None
    assert eth_signal.side is not None
    assert btc_signal.side != eth_signal.side

@pytest.mark.asyncio
async def test_asilletto81_basis_mark_minus_oracle(tmp_path, monkeypatch) -> None:
    import lz4.frame
    from datetime import UTC, datetime, timedelta
    from traderstack.research.edge_series import ASILLETTO81_CACHE_DIR

    day = datetime(2024, 6, 12, tzinfo=UTC)
    csv_text = (
        "time,coin,funding,open_interest,prev_day_px,day_ntl_vlm,premium,"
        "oracle_px,mark_px,mid_px,impact_bid_px,impact_ask_px\n"
        "2024-06-12T00:00:00Z,BTC,0,1,1,1,0,100.0,101.0,100.5,100.4,100.6\n"
        "2024-06-12T23:59:00Z,BTC,0,1,1,1,0,100.0,102.0,101.0,100.9,101.1\n"
        "2024-06-12T23:59:00Z,ETH,0,1,1,1,0,50.0,51.0,50.5,50.4,50.6\n"
    )
    payload = lz4.frame.compress(csv_text.encode())
    cache = tmp_path / "asset_ctxs"
    cache.mkdir()
    (cache / "20240612.csv.lz4").write_bytes(payload)

    async def fake_download(client, day, *, cache_dir):
        path = cache_dir / f"{day.strftime('%Y%m%d')}.csv.lz4"
        return path.read_bytes() if path.is_file() else None

    monkeypatch.setattr(
        "traderstack.research.edge_series._asilletto_download_day", fake_download
    )
    async with httpx.AsyncClient() as client:
        result = await fetch_asilletto81_hyperliquid_basis(
            "BTC/USD",
            client=client,
            start=day,
            end=day,
            cache_dir=cache,
        )
    assert result.status == "ok"
    assert len(result.points) == 1
    assert result.points[0][1] == pytest.approx(0.02)  # last mark 102 / oracle 100

