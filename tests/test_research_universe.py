from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.research.universe import (
    EXCLUDED_BASES,
    LIQUIDITY_FILTER_RULE,
    UNIVERSE_SOURCE_NOTE,
    canonical_from_symbol,
    canonical_symbol,
    dollar_volume_series,
    eligible_names,
    fetch_kraken_usd_pairs,
    histories_by_canonical,
    is_excluded_base,
    liquidity_snapshots,
    parse_asset_pairs,
    snapshot_for,
)


def _pair(wsname: str, *, quote: str = "ZUSD", status: str = "online") -> dict[str, object]:
    return {
        "altname": wsname.replace("/", ""),
        "wsname": wsname,
        "base": wsname.partition("/")[0],
        "quote": quote,
        "status": status,
    }


def _payload() -> dict[str, object]:
    return {
        "error": [],
        "result": {
            "XXBTZUSD": _pair("XBT/USD"),
            "XETHZUSD": _pair("ETH/USD"),
            "SOLUSD": _pair("SOL/USD", quote="USD"),
            "XDGUSD": _pair("XDG/USD"),
            "ADAEUR": _pair("ADA/EUR", quote="ZEUR"),
            "ACAUSD": _pair("ACA/USD", status="cancel_only"),
            "XXBTZUSD.d": _pair("XBT/USD"),
            "USDTZUSD": _pair("USDT/USD"),
            "USDCUSD": _pair("USDC/USD"),
            "PYUSDUSD": _pair("PYUSD/USD"),
            "ZEURZUSD": _pair("EUR/USD"),
            "WBTCUSD": _pair("WBTC/USD"),
            "PAXGUSD": _pair("PAXG/USD"),
            "NOWS": {"altname": "NOWSUSD", "quote": "ZUSD", "status": "online"},
        },
    }


def make_candles(
    prices: list[float],
    *,
    symbol: str,
    start: datetime,
    volume: float = 1_000.0,
    volumes: list[float] | None = None,
) -> tuple[Candle, ...]:
    out: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        out.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=start + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.001,
                low=min(previous, price) * 0.999,
                close=price,
                volume=volumes[index] if volumes is not None else volume,
            )
        )
    return tuple(out)


@pytest.mark.asyncio
async def test_fetch_kraken_usd_pairs_keeps_online_usd_and_aliases() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport) as client:
        pairs = await fetch_kraken_usd_pairs(client)

    assert calls == ["/0/public/AssetPairs"]
    canonical = [pair.canonical for pair in pairs]
    assert canonical == ["BTC/USD", "DOGE/USD", "ETH/USD", "SOL/USD"]
    btc = next(pair for pair in pairs if pair.canonical == "BTC/USD")
    assert btc.wsname == "XBT/USD"
    assert btc.altname == "XBTUSD"
    assert btc.pair_key == "XXBTZUSD"
    # ZUSD and USD quotes both accepted; EUR, cancel_only, dark-pool,
    # stablecoin, fiat, wrapped and tokenised-gold rows all dropped.
    assert "ADA/USD" not in canonical
    assert "ACA/USD" not in canonical
    assert "USDT/USD" not in canonical
    assert "EUR/USD" not in canonical
    assert "WBTC/USD" not in canonical
    assert "PAXG/USD" not in canonical


def test_parse_asset_pairs_rejects_malformed_payloads() -> None:
    with pytest.raises(TypeError):
        parse_asset_pairs([])
    with pytest.raises(TypeError):
        parse_asset_pairs({"error": [], "result": []})
    with pytest.raises(TypeError):
        parse_asset_pairs({"error": [], "result": {"X": "not-a-row"}})
    with pytest.raises(TypeError):
        parse_asset_pairs(
            {"error": [], "result": {"X": {"quote": 7, "status": "online", "wsname": "A/USD"}}}
        )
    with pytest.raises(TypeError):
        parse_asset_pairs(
            {"error": [], "result": {"X": {"quote": "ZUSD", "status": "online", "wsname": 5}}}
        )
    with pytest.raises(RuntimeError):
        parse_asset_pairs({"error": ["EGeneral:Temporary lockout"], "result": {}})


def test_exclusion_rule_and_canonical_symbols() -> None:
    assert is_excluded_base("USDT") and is_excluded_base("AUSD") and is_excluded_base("RLUSD")
    assert is_excluded_base("dai") and is_excluded_base("WBTC") and is_excluded_base("EUR")
    assert not is_excluded_base("BTC") and not is_excluded_base("USUAL")
    assert "USDT" not in EXCLUDED_BASES  # caught by the prefix rule, not the list
    assert canonical_symbol("xbt") == "BTC/USD"
    assert canonical_symbol("XDG") == "DOGE/USD"
    assert canonical_from_symbol("BTC-USD") == "BTC/USD"
    assert canonical_from_symbol("BTCUSDT") == "BTC/USD"
    assert canonical_from_symbol("ETHUSD") == "ETH/USD"
    assert canonical_from_symbol("XBT/USD") == "BTC/USD"
    with pytest.raises(ValueError):
        canonical_from_symbol("BTC/EUR")
    with pytest.raises(ValueError):
        canonical_from_symbol("BTC")
    with pytest.raises(ValueError):
        canonical_symbol("  ")
    assert "top_20_pit" in LIQUIDITY_FILTER_RULE
    assert "survivorship" in UNIVERSE_SOURCE_NOTE


def test_liquidity_snapshots_use_only_pre_snapshot_bars() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    days = 62
    spike_index = 31  # 2024-02-01, the snapshot day itself
    histories = {
        "A@1d": make_candles([10.0] * days, symbol="A/USD", start=start, volume=300.0),
        "B@1d": make_candles([10.0] * days, symbol="B/USD", start=start, volume=200.0),
        "C@1d": make_candles(
            [10.0] * days,
            symbol="C/USD",
            start=start,
            volumes=[1.0 if i != spike_index else 1e9 for i in range(days)],
        ),
    }
    snapshots = liquidity_snapshots(histories, top_n=2)
    assert [snap.snapshot_at for snap in snapshots] == [
        datetime(2024, 2, 1, tzinfo=UTC),
        datetime(2024, 3, 1, tzinfo=UTC),
    ]
    february = snapshots[0]
    # C's spike on the snapshot day is not visible to the February decision.
    assert february.names == ["A/USD", "B/USD"]
    assert february.candidates_considered == 3
    assert february.median_dollar_volume["A/USD"] == pytest.approx(3_000.0)
    # The March snapshot sees the spike as one of 29 values; the median is unmoved.
    assert snapshots[1].names == ["A/USD", "B/USD"]


def test_liquidity_snapshots_skip_short_history_and_zero_volume() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "A@1d": make_candles([10.0] * 62, symbol="A/USD", start=start, volume=300.0),
        # listed mid-January: fewer than 30 bars before 2024-02-01 -> skipped in Feb
        "LATE@1d": make_candles(
            [10.0] * 47, symbol="LATE/USD", start=start + timedelta(days=15), volume=9_999.0
        ),
        "ZERO@1d": make_candles([10.0] * 62, symbol="ZERO/USD", start=start, volume=0.0),
    }
    snapshots = liquidity_snapshots(histories)
    assert snapshots[0].names == ["A/USD"]
    assert snapshots[0].candidates_skipped == 2
    # By March LATE has a full trailing window and ranks first; ZERO never ranks.
    assert snapshots[1].names == ["LATE/USD", "A/USD"]
    assert "ZERO/USD" not in snapshots[1].names


def test_liquidity_snapshots_empty_and_top_n_cap() -> None:
    assert liquidity_snapshots({}) == ()
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        f"N{i}@1d": make_candles([1.0] * 40, symbol=f"N{i}/USD", start=start, volume=float(i + 1))
        for i in range(5)
    }
    snapshots = liquidity_snapshots(histories, top_n=3)
    assert len(snapshots) == 1
    assert snapshots[0].names == ["N4/USD", "N3/USD", "N2/USD"]
    with pytest.raises(ValueError):
        liquidity_snapshots(histories, top_n=0)


def test_snapshot_for_and_eligible_names_require_history_at_t() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "A@1d": make_candles([1.0] * 40, symbol="A/USD", start=start),
        "B@1d": make_candles([1.0] * 40, symbol="B/USD", start=start),
    }
    snapshots = liquidity_snapshots(histories)
    assert snapshot_for(snapshots, start) is None
    at = datetime(2024, 2, 5, tzinfo=UTC)
    chosen = snapshot_for(snapshots, at)
    assert chosen is not None and chosen.snapshot_at == datetime(2024, 2, 1, tzinfo=UTC)
    closes = {
        name: {candle.opened_at: candle.close for candle in candles}
        for name, candles in histories_by_canonical(histories).items()
    }
    assert eligible_names(chosen, closes, at=at, min_bars=36) == ("A/USD", "B/USD")
    assert eligible_names(chosen, closes, at=at, min_bars=37) == ()
    series = dollar_volume_series(histories["A@1d"])
    assert series[start] == pytest.approx(1_000.0)
