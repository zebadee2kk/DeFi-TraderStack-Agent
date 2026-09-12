from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.daily_candidates import (
    BuyTheDipVolFilterStrategy,
    DualMomentumStrategy,
    MaRiskOffStrategy,
    ReferenceMaRiskOffStrategy,
    default_balanced_holdout_candidates,
    default_daily_robustness_candidates,
)
from traderstack.research.daily_robustness import (
    KRAKEN_DAILY_CAP_NOTE,
    is_promotion_series,
    render_daily_robustness_markdown,
    run_daily_robustness,
)
from traderstack.research.daily_robustness_cli import build_parser, run
from traderstack.research.miles_candidates import EmaCrossoverStrategy
from traderstack.research.yahoo_daily import parse_yahoo_chart, yahoo_symbol
from traderstack.strategies import Regime


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def make_candles(
    prices: list[float],
    *,
    symbol: str = "BTC/USD",
    interval: str = "1d",
    start: datetime | None = None,
    volumes: list[float] | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        volume = volumes[index] if volumes is not None else 1_000 + index
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=opened + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=volume,
            )
        )
    return tuple(candles)


def downtrend(count: int = 400, *, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    return make_candles([200.0 - 0.25 * index for index in range(count)], symbol=symbol)


def uptrend(count: int = 400, *, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    return make_candles([100.0 + 0.25 * index for index in range(count)], symbol=symbol)


def chop(count: int = 400, *, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    prices = [100.0 + (1.5 if index % 2 == 0 else -1.5) for index in range(count)]
    return make_candles(prices, symbol=symbol)


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _search(histories: dict[str, tuple[Candle, ...]], **overrides: object):
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "catalog_name": "legacy",
    }
    kwargs.update(overrides)
    return run_daily_robustness(histories, **kwargs)  # type: ignore[arg-type]


def test_catalog_is_pre_registered_and_includes_required_families() -> None:
    catalog = default_daily_robustness_candidates()
    ids = [item.candidate_id for item in catalog]
    assert len(ids) == len(set(ids))
    assert ids == [
        "ema_9_21",
        "ema_12_26",
        "ema_9_21_adx20",
        "ema_12_26_adx20",
        "ema_9_21_adx25",
        "ema_12_26_adx25",
        "dual_mom_21_126",
        "dip_mr_20_1_5_vol",
    ]
    families = {item.family for item in catalog}
    assert families == {"ema_cross", "dual_momentum", "buy_the_dip"}
    assert all(item.garch_sizing is False for item in catalog)


def test_balanced_catalog_is_pre_registered_and_frozen() -> None:
    catalog = default_balanced_holdout_candidates()
    ids = [item.candidate_id for item in catalog]
    assert len(ids) == len(set(ids))
    assert ids == [
        "ema_9_21",
        "ema_12_26",
        "ema_9_21_adx20",
        "ema_12_26_adx20",
        "ema_9_21_adx25",
        "ema_12_26_adx25",
        "ema_20_50",
        "ema_50_200",
        "ema_20_50_adx20",
        "ema_9_21_garch",
        "ema_20_50_garch",
        "dual_mom_12_60",
        "dual_mom_21_63",
        "dual_mom_21_126",
        "dual_mom_63_126",
        "dip_mr_20_1_5_vol",
        "dip_mr_20_2_0_vol",
        "ema_9_21_ma200_riskoff",
        "ema_20_50_ma200_riskoff",
    ]
    garch_ids = {item.candidate_id for item in catalog if item.garch_sizing}
    assert garch_ids == {"ema_9_21_garch", "ema_20_50_garch"}
    overlay = default_balanced_holdout_candidates(btc_overlay=uptrend(220, symbol="BTC/USD"))
    overlay_ids = [item.candidate_id for item in overlay]
    assert overlay_ids[-1] == "ema_9_21_btc_ma200_riskoff"
    assert "ema_9_21_btc_ma200_riskoff" not in ids


def test_dual_momentum_requires_both_lookbacks_to_agree() -> None:
    # Fast 3-bar return is negative while slow 10-bar return is positive.
    prices = [100.0 + 0.5 * index for index in range(20)]
    prices[-1] = prices[-2] - 2.0
    candles = make_candles(prices)
    signal = DualMomentumStrategy(
        strategy_id="dual",
        fast_lookback=3,
        slow_lookback=10,
    ).evaluate(candles, Regime.TRENDING_UP)
    assert signal.side is None
    assert "dual-mom" in signal.rationale

    down = DualMomentumStrategy(strategy_id="dual", fast_lookback=3, slow_lookback=10).evaluate(
        downtrend(40), Regime.TRENDING_DOWN
    )
    assert down.side is Side.SELL


def test_ma_riskoff_flattens_when_close_below_sma() -> None:
    inner = EmaCrossoverStrategy(strategy_id="ema", fast_span=3, slow_span=5)
    gated = MaRiskOffStrategy(strategy_id="ema_riskoff", inner=inner, ma_span=10)
    rising = make_candles([100.0 + index for index in range(20)])
    assert gated.evaluate(rising, Regime.TRENDING_UP).side is Side.BUY
    crash = make_candles([100.0 + index for index in range(15)] + [80.0, 79.0, 78.0, 77.0, 76.0])
    signal = gated.evaluate(crash, Regime.TRENDING_DOWN)
    assert signal.side is None
    assert "risk-off" in signal.rationale


def test_btc_reference_riskoff_is_point_in_time() -> None:
    btc = make_candles([100.0 + index for index in range(15)] + [80.0, 79.0, 78.0, 77.0, 76.0])
    eth = make_candles([50.0 + 0.5 * index for index in range(20)], symbol="ETH/USD")
    inner = EmaCrossoverStrategy(strategy_id="ema", fast_span=3, slow_span=5)
    gated = ReferenceMaRiskOffStrategy(
        strategy_id="ema_btc_riskoff",
        inner=inner,
        ma_span=10,
        reference_symbol="BTC/USD",
        reference_opened_at=tuple(candle.opened_at for candle in btc),
        reference_close=tuple(candle.close for candle in btc),
    )
    signal = gated.evaluate(eth, Regime.TRENDING_UP)
    assert signal.side is None
    assert "BTC/USD" in signal.rationale
    # Future BTC prints must not leak: truncate the overlay at the ETH as-of.
    early_eth = eth[:12]
    early = gated.evaluate(early_eth, Regime.TRENDING_UP)
    assert early.side is Side.BUY


def test_buy_the_dip_is_long_only_and_skips_vol_spikes() -> None:
    # A gradual, low-vol drift below the 20-bar mean should buy.
    base = [100.0 - 0.15 * index for index in range(70)]
    calm = make_candles(base)
    bought = BuyTheDipVolFilterStrategy(strategy_id="dip").evaluate(calm, Regime.RANGE)
    assert bought.side is Side.BUY

    # A late crash after a long quiet stretch trips the vol-spike filter.
    quiet = [100.0 - 0.05 * index for index in range(50)]
    crash = list(quiet)
    last = quiet[-1]
    for step in (0.92, 1.10, 0.88, 1.12, 0.85, 1.15, 0.80, 1.18, 0.75, 1.20, 0.70):
        last = last * step
        crash.append(last)
    crash[-1] = crash[-2] * 0.80
    spiked = BuyTheDipVolFilterStrategy(strategy_id="dip").evaluate(
        make_candles(crash), Regime.HIGH_VOLATILITY
    )
    assert spiked.side is None
    assert "vol filter" in spiked.rationale


def test_yahoo_parser_labels_non_kraken_and_drops_nulls() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1_700_000_000, 1_700_086_400, 1_700_172_800],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, None, 102.0],
                                "high": [101.0, None, 103.0],
                                "low": [99.0, None, 101.0],
                                "close": [100.5, None, 102.5],
                                "volume": [10.0, None, 12.0],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    candles = parse_yahoo_chart(payload, symbol="BTC/USD")
    assert yahoo_symbol("BTC/USD") == "BTC-USD"
    assert all(candle.symbol == "BTC-USD" for candle in candles)
    assert len(candles) == 2
    assert candles[0].close == 100.5
    assert candles[1].close == 102.5


def test_yahoo_parser_expands_invalid_ohlc_instead_of_dropping() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1_700_000_000, 1_700_086_400],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, 102.0],
                                "high": [101.0, 100.0],
                                "low": [99.0, 101.0],
                                "close": [100.5, 102.5],
                                "volume": [10.0, 12.0],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    candles = parse_yahoo_chart(payload, symbol="ETH-USD")
    assert len(candles) == 2
    assert candles[1].high >= candles[1].close
    assert candles[1].low <= candles[1].open


def test_yahoo_symbol_is_not_a_promotion_series() -> None:
    yahoo = make_candles([100.0 + index for index in range(10)], symbol="BTC-USD")
    from traderstack.research.miles_search import SeriesCandidateMetrics

    row = SeriesCandidateMetrics(
        asset=yahoo[0].symbol,
        interval="1d",
        candle_count=len(yahoo),
        research_bars=8,
        holdout_bars=2,
    )
    assert is_promotion_series(row) is False
    kraken = row.model_copy(update={"asset": "BTC/USD"})
    assert is_promotion_series(kraken) is True


def test_eth_only_winner_fails_multi_asset_bar() -> None:
    """#93-style ETH-heavy book: mean can look fine while BTC WF is not > 0."""
    report = _search(
        {
            "BTC/USD@1d": chop(360, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(360, symbol="ETH/USD"),
        }
    )
    ema = next(row for row in report.candidates if row.candidate_id == "ema_9_21")
    rendered = render_daily_robustness_markdown(report)
    assert "btc_walkforward_total_return_not_positive" in ema.ineligible_reasons or (
        ema.mean_wf_total_return is not None and not ema.eligible
    )
    assert ema.promoted is False
    if report.any_promoted:
        promoted = next(row for row in report.candidates if row.promoted)
        btc = next(s for s in promoted.per_series if s.asset == "BTC/USD")
        eth = next(s for s in promoted.per_series if s.asset == "ETH/USD")
        assert btc.walkforward_mean_total_return is not None
        assert eth.walkforward_mean_total_return is not None
        assert btc.walkforward_mean_total_return > 0
        assert eth.walkforward_mean_total_return > 0
    else:
        assert "multi-asset bar" in rendered
        assert "PAPER_PROMOTE_EMA_9_21=false" in rendered
    assert report.recommended_promote_flag is None or report.any_promoted
    if not report.ema_9_21_clears_multi_asset:
        assert "ema_9_21" in rendered


def test_both_assets_positive_wf_can_promote() -> None:
    report = _search(
        {
            "BTC/USD@1d": downtrend(360, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(360, symbol="ETH/USD"),
        }
    )
    ema = next(row for row in report.candidates if row.candidate_id == "ema_9_21")
    assert ema.mean_wf_total_return is not None
    assert ema.mean_wf_total_return > 0
    if report.any_promoted:
        assert report.recommended_promote_id in report.promoted_candidate_ids
        promoted = next(row for row in report.candidates if row.promoted)
        btc = next(s for s in promoted.per_series if s.asset == "BTC/USD")
        eth = next(s for s in promoted.per_series if s.asset == "ETH/USD")
        assert (btc.walkforward_mean_total_return or 0) > 0
        assert (eth.walkforward_mean_total_return or 0) > 0


def test_positive_mean_holdout_fails_when_btc_holdout_is_not() -> None:
    """ETH-only holdout tail must not promote under the balanced bar."""
    # Research: both assets trend down so the EMA shorts and WF totals are > 0.
    # Holdout: BTC reverses up (short loses) while ETH keeps falling (short wins).
    btc_research = downtrend(280, symbol="BTC/USD")
    eth_research = downtrend(280, symbol="ETH/USD")
    btc_holdout = make_candles(
        [btc_research[-1].close + 0.8 * index for index in range(1, 81)],
        symbol="BTC/USD",
        start=btc_research[-1].opened_at + timedelta(days=1),
    )
    eth_holdout = make_candles(
        [eth_research[-1].close - 1.6 * index for index in range(1, 81)],
        symbol="ETH/USD",
        start=eth_research[-1].opened_at + timedelta(days=1),
    )
    report = _search(
        {
            "BTC/USD@1d": btc_research + btc_holdout,
            "ETH/USD@1d": eth_research + eth_holdout,
        },
        require_balanced_holdout=True,
    )
    ema = next(row for row in report.candidates if row.candidate_id == "ema_9_21")
    btc = next(series for series in ema.per_series if series.asset == "BTC/USD")
    eth = next(series for series in ema.per_series if series.asset == "ETH/USD")
    assert (btc.walkforward_mean_total_return or 0) > 0
    assert (eth.walkforward_mean_total_return or 0) > 0
    assert btc.holdout is not None and eth.holdout is not None
    assert btc.holdout.excess_return <= 0
    assert eth.holdout.excess_return > 0
    if ema.mean_holdout_excess_return is not None and ema.mean_holdout_excess_return > 0:
        assert report.ema_9_21_clears_multi_asset is True
    assert "btc_holdout_excess_not_positive" in ema.ineligible_reasons
    assert ema.eligible is False
    assert report.ema_9_21_clears_balanced_holdout is False
    rendered = render_daily_robustness_markdown(report)
    assert "balanced-holdout bar: **FAIL**" in rendered
    assert "BTC holdout" in rendered


def test_both_assets_positive_holdout_can_clear_balanced_bar() -> None:
    report = _search(
        {
            "BTC/USD@1d": downtrend(360, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(360, symbol="ETH/USD"),
        },
        require_balanced_holdout=True,
    )
    ema = next(row for row in report.candidates if row.candidate_id == "ema_9_21")
    btc = next(series for series in ema.per_series if series.asset == "BTC/USD")
    eth = next(series for series in ema.per_series if series.asset == "ETH/USD")
    assert (btc.walkforward_mean_total_return or 0) > 0
    assert (eth.walkforward_mean_total_return or 0) > 0
    assert btc.holdout is not None and eth.holdout is not None
    assert btc.holdout.excess_return > 0
    assert eth.holdout.excess_return > 0
    assert report.ema_9_21_clears_balanced_holdout is True
    assert report.ema_9_21_clears_multi_asset is True
    if report.any_promoted:
        assert report.recommended_promote_id in report.promoted_candidate_ids


def test_holdout_tail_does_not_change_ranking() -> None:
    prefix = downtrend(280, symbol="BTC/USD")
    eth_prefix = downtrend(280, symbol="ETH/USD")
    holdout_a = make_candles(
        [prefix[-1].close - 0.2 * index for index in range(1, 81)],
        symbol="BTC/USD",
        start=prefix[-1].opened_at + timedelta(days=1),
    )
    holdout_b = make_candles(
        [prefix[-1].close + 0.8 * index for index in range(1, 81)],
        symbol="BTC/USD",
        start=prefix[-1].opened_at + timedelta(days=1),
    )
    eth_a = make_candles(
        [eth_prefix[-1].close - 0.2 * index for index in range(1, 81)],
        symbol="ETH/USD",
        start=eth_prefix[-1].opened_at + timedelta(days=1),
    )
    eth_b = make_candles(
        [eth_prefix[-1].close + 0.8 * index for index in range(1, 81)],
        symbol="ETH/USD",
        start=eth_prefix[-1].opened_at + timedelta(days=1),
    )
    a = _search({"BTC/USD@1d": prefix + holdout_a, "ETH/USD@1d": eth_prefix + eth_a})
    b = _search({"BTC/USD@1d": prefix + holdout_b, "ETH/USD@1d": eth_prefix + eth_b})
    assert a.selected_candidate_id == b.selected_candidate_id
    a_sel = next(row for row in a.candidates if row.candidate_id == a.selected_candidate_id)
    b_sel = next(row for row in b.candidates if row.candidate_id == b.selected_candidate_id)
    assert a_sel.mean_holdout_excess_return != b_sel.mean_holdout_excess_return


def test_yahoo_series_does_not_enter_promotion_average() -> None:
    kraken_btc = downtrend(360, symbol="BTC/USD")
    kraken_eth = downtrend(360, symbol="ETH/USD")
    yahoo_btc = uptrend(360, symbol="BTC-USD")
    without = _search({"BTC/USD@1d": kraken_btc, "ETH/USD@1d": kraken_eth})
    with_yahoo = _search(
        {
            "BTC/USD@1d": kraken_btc,
            "ETH/USD@1d": kraken_eth,
            "BTC-USD@1d": yahoo_btc,
        }
    )
    a = next(row for row in without.candidates if row.candidate_id == "ema_9_21")
    b = next(row for row in with_yahoo.candidates if row.candidate_id == "ema_9_21")
    assert a.mean_wf_total_return == pytest.approx(b.mean_wf_total_return or 0.0)
    assert any(series.asset == "BTC-USD" for series in b.per_series)


def test_markdown_reports_drawdown_trades_and_cap() -> None:
    report = _search(
        {
            "BTC/USD@1d": downtrend(360, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(360, symbol="ETH/USD"),
        }
    )
    text = render_daily_robustness_markdown(report)
    assert "Daily robustness report" in text
    assert "720" in text
    assert "WF maxDD" in text
    assert "holdout trades" in text
    assert "non-Kraken" in text
    assert "Holdout concentration" in text
    assert "balanced-holdout bar" in text
    assert "BTC holdout" in text
    assert KRAKEN_DAILY_CAP_NOTE.split("`")[0].strip() in text or "720" in text


def test_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    write_candles(btc, downtrend(280, symbol="BTC/USD"))
    write_candles(eth, downtrend(280, symbol="ETH/USD"))
    out_json = tmp_path / "ops" / "report.json"
    out_md = tmp_path / "ops" / "report.md"
    args = build_parser().parse_args(
        [
            "--candles",
            str(btc),
            "--candles",
            str(eth),
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
            "--min-trades",
            "1",
            "--fee-bps",
            "10",
            "--no-yahoo",
        ]
    )
    written_json, written_md = run(args, settings=settings())
    assert written_json.is_file()
    assert written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["selection_rule"] == "pre_registered_top1"
    assert payload["promotion_assets"] == ["BTC/USD", "ETH/USD"]
    assert payload["require_balanced_holdout"] is True
    assert payload["catalog_name"] == "balanced"
    assert "honesty" in payload
    ids = {row["candidate_id"] for row in payload["candidates"]}
    assert "ema_9_21" in ids
    assert "ema_20_50" in ids
    assert "ema_50_200" in ids
    assert "dual_mom_12_60" in ids
    assert "dual_mom_21_126" in ids
    assert "dip_mr_20_1_5_vol" in ids
    assert "ema_9_21_ma200_riskoff" in ids
    assert "ema_9_21_garch" in ids
    assert "ema_9_21_btc_ma200_riskoff" in ids
    text = written_md.read_text()
    assert "Daily robustness report" in text
    assert "Multiple testing" in text
    assert "balanced-holdout" in text.lower() or "BTC holdout excess" in text
