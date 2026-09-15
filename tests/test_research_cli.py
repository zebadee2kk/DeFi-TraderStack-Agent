import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.candles import Candle
from traderstack.research.cli import build_parser, load_candles_from_json, run


def make_candles_json(path: Path, count: int = 400) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    price = 100.0
    rows = []
    for index in range(count):
        previous = price
        price = price + 0.5
        rows.append(
            {
                "symbol": "BTC/USD",
                "interval": "1h",
                "opened_at": (start + timedelta(hours=index)).isoformat(),
                "open": previous,
                "high": max(previous, price) * 1.002,
                "low": min(previous, price) * 0.998,
                "close": price,
                "volume": 1_000 + index,
            }
        )
    path.write_text(json.dumps(rows))


def test_load_candles_from_json_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "candles.json"
    make_candles_json(path, count=10)
    candles = load_candles_from_json(path)
    assert len(candles) == 10
    assert all(isinstance(candle, Candle) for candle in candles)
    assert candles[0].symbol == "BTC/USD"


def test_run_produces_a_full_research_report(tmp_path: Path) -> None:
    path = tmp_path / "candles.json"
    make_candles_json(path)
    args = build_parser().parse_args(["--candles", str(path)])
    report = run(args)

    assert report.candle_count == 400
    assert report.metrics.trades >= 1
    assert set(report.baselines) == {
        "buy_and_hold",
        "time_series_momentum",
        "ma_trend",
        "mean_reversion",
        "volatility_target",
    }
    assert set(report.excess) == set(report.baselines)
    assert report.attribution.total_trades == report.metrics.trades

    payload = report.to_json()
    json.dumps(payload)  # must be JSON-serializable
    assert payload["asset"] == "BTC/USD"

    rendered = report.render()
    assert "Baselines (excess over each)" in rendered
    assert "Performance Attribution" in rendered


def test_run_handles_too_few_candles_for_walkforward(tmp_path: Path) -> None:
    path = tmp_path / "candles.json"
    make_candles_json(path, count=50)
    args = build_parser().parse_args(
        ["--candles", str(path), "--train-size", "40", "--test-size", "40"]
    )
    report = run(args)
    assert report.walkforward is None
    rendered = report.render()
    assert "insufficient candles" in rendered


# --- fee realism (#138) ---
def test_research_cli_defaults_to_the_pilot_tier_and_stamps_the_report(tmp_path: Path) -> None:
    path = tmp_path / "candles.json"
    make_candles_json(path)
    report = run(build_parser().parse_args(["--candles", str(path)]))
    assert report.fee_bps == 80.0
    assert report.slippage_bps == 5.0
    assert report.fee_tier is not None
    assert report.fee_tier.tier_id == "kraken_pro_spot_t1"
    payload = report.to_json()
    assert payload["fee_bps"] == 80.0
    assert payload["fee_tier"]["taker_bps"] == 80.0
    assert payload["fee_tier"]["role"] == "taker"
    rendered = report.render()
    assert "Costs: fee=80 bps + slippage=5 bps" in rendered
    assert "Fee tier: Tier 1 ($0+ 30d) maker 40 / taker 80 bps" in rendered

    explicit = run(build_parser().parse_args(["--candles", str(path), "--fee-bps", "10"]))
    assert explicit.fee_bps == 10.0
    assert explicit.fee_tier is not None and explicit.fee_tier.tier_id == "explicit"
    assert explicit.metrics.total_fees < report.metrics.total_fees

    tiered = run(
        build_parser().parse_args(["--candles", str(path), "--fee-tier", "kraken_pro_spot_t8"])
    )
    assert tiered.fee_bps == 20.0
    assert tiered.fee_tier is not None and tiered.fee_tier.tier_id == "kraken_pro_spot_t8"
