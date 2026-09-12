from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.bollinger_fade import (
    BOLLINGER_CATALOG_NOTE,
    BOLLINGER_IDS,
    BOLLINGER_RULES,
    CONTROL_ID,
    CONTROL_IDS,
    CORE_IDS,
    DECISION_RULE,
    EXISTING_MEAN_REVERSION_IDS,
    EXIT_RULE,
    FADE_IDS,
    FILL_RULE,
    MEAN_REVERSION_DISTINCT_NOTE,
    MULTI_ASSET_GATE_RULE,
    PAPER_PATH_READY,
    SQUEEZE_IDS,
    SQUEEZE_PERCENTILE_WINDOW,
    SQUEEZE_RULE,
    STDEV_RULE,
    bollinger_bands_at,
    bollinger_candidates,
    bollinger_position_series,
    bollinger_signals,
    btc_wf_fail_informational,
    eth_carried_informational,
    fade_position,
    rank_bollinger_passers,
    render_bollinger_fade_markdown,
    run_bollinger_fade_search,
    skipped_bollinger_families,
)
from traderstack.research.bollinger_fade_cli import build_parser, run
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
)
from traderstack.research.second_print import DOCUMENTED_PRIMARY_FIRST_ISO, SECOND_PRINT_BARS
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
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=opened + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def downtrend(
    count: int, *, symbol: str = "BTC/USD", start: datetime | None = None
) -> tuple[Candle, ...]:
    return make_candles(
        [200.0 - 0.25 * index for index in range(count)], symbol=symbol, start=start
    )


def uptrend(
    count: int, *, symbol: str = "BTC/USD", start: datetime | None = None
) -> tuple[Candle, ...]:
    return make_candles(
        [100.0 + 0.25 * index for index in range(count)], symbol=symbol, start=start
    )


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _histories(count: int = 300, *, start: datetime | None = None) -> dict[str, tuple[Candle, ...]]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return {
        "BTC/USD@1d": uptrend(count, symbol="BTC/USD", start=opened),
        "ETH/USD@1d": uptrend(count, symbol="ETH/USD", start=opened),
        "SOL/USD@1d": uptrend(count, symbol="SOL/USD", start=opened),
    }


def _tiny_catalog():
    return bollinger_candidates(_histories(80), include_control=True)


def _search(
    kraken: dict[str, tuple[Candle, ...]],
    binance: dict[str, tuple[Candle, ...]] | None = None,
    **overrides: object,
):
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "candidates": _tiny_catalog(),
    }
    kwargs.update(overrides)
    return run_bollinger_fade_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


def _row(
    candidate_id: str,
    *,
    kraken_combined: bool,
    binance_combined: bool,
    kraken_ho: float | None,
    binance_ho: float | None = None,
    kraken_btc_ho: float | None = None,
    kraken_eth_ho: float | None = None,
    kraken_btc_wf: float | None = None,
) -> DualPrintRow:
    return DualPrintRow(
        candidate_id=candidate_id,
        family="bb_fade",
        label=candidate_id,
        kraken_combined=kraken_combined,
        binance_combined=binance_combined,
        dual_print=kraken_combined and binance_combined,
        kraken_mean_holdout_excess=kraken_ho,
        binance_mean_holdout_excess=binance_ho,
        kraken_btc_holdout=kraken_btc_ho,
        kraken_eth_holdout=kraken_eth_ho,
        kraken_btc_wf=kraken_btc_wf,
    )


def test_promote_defaults_stay_false() -> None:
    cfg = settings()
    assert cfg.paper_promote_ema_9_21 is False
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.paper_promote_searched_strategies is False
    assert cfg.paper_garch_size is False
    assert not hasattr(cfg, "paper_promote_bb_fade_20x2")
    assert not hasattr(cfg, "paper_promote_bollinger")


def test_catalog_and_bar_are_frozen_before_scoring() -> None:
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert PAPER_PATH_READY is True
    assert DECISION_RULE == "closes_through_t"
    assert FILL_RULE == "next_bar_open"
    assert EXIT_RULE == "flat_when_inside_bands"
    assert STDEV_RULE == "sample_stdev_ddof_1"
    assert SQUEEZE_RULE == "expand_from_p20_of_prior_120_bandwidth_long_above_mid"
    assert SQUEEZE_PERCENTILE_WINDOW == 120
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in BOLLINGER_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in BOLLINGER_RULES
    assert "CAN_AVERAGE_VENUES=false" in BOLLINGER_RULES
    assert MULTI_ASSET_GATE_RULE == "btc_eth_signs_as_96_abc_sol_reported_not_required"
    assert MULTI_ASSET_GATE_RULE in BOLLINGER_RULES
    assert SECOND_PRINT_BARS == 720
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"
    catalog = bollinger_candidates(_histories(280))
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert ids[:3] == ["bb_fade_20x2", "bb_fade_20x2_5", "bb_fade_40x2"]
    assert ids[3:5] == ["bb_lo_fade_20x2", "bb_lo_fade_40x2"]
    assert ids[5:7] == ["bb_squeeze_break_20", "bb_squeeze_break_40"]
    assert ids[-1] == CONTROL_ID
    assert set(BOLLINGER_IDS) | CONTROL_IDS == set(CORE_IDS)
    assert set(FADE_IDS) | set(SQUEEZE_IDS) == set(BOLLINGER_IDS)
    assert "ema_9_21" not in ids
    assert "rv_fade_1_0" not in ids
    assert "xs_mom_lo_21" not in ids
    assert "donchian_lo_20" not in ids
    assert "tsmom_lo_21" not in ids
    for legacy in EXISTING_MEAN_REVERSION_IDS:
        assert legacy not in ids
    assert MEAN_REVERSION_DISTINCT_NOTE in BOLLINGER_RULES
    assert MEAN_REVERSION_DISTINCT_NOTE in BOLLINGER_CATALOG_NOTE
    assert "equal-weight portfolio metrics are not used" in BOLLINGER_RULES.lower()
    assert "not TSMOM" in BOLLINGER_RULES
    freeze = Path("docs/artifacts/strategy-search/bollinger-fade.md").read_text()
    assert "bb_fade_20x2" in freeze
    assert "bb_fade_20x2_5" in freeze
    assert "bb_squeeze_break_40" in freeze
    assert "ma_cross_10_30" in freeze
    assert "PAPER_PROMOTE_*" in freeze
    assert "closes_through_t" in freeze
    assert "flat_when_inside_bands" in freeze
    assert "Not yet run" in freeze or "Dual-print passers" in freeze


def test_missing_sol_does_not_skip_btc_eth_names() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(280, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(280, symbol="ETH/USD", start=start),
    }
    catalog = bollinger_candidates(histories)
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert skipped_bollinger_families(histories) == []


def test_short_history_skips_not_invented() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(10, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(10, symbol="ETH/USD", start=start),
    }
    catalog = bollinger_candidates(histories)
    assert [item.candidate_id for item in catalog] == [CONTROL_ID]
    skipped = skipped_bollinger_families(histories)
    assert {item["candidate_id"] for item in skipped} == set(BOLLINGER_IDS)
    assert all("invent" in item["reason"] for item in skipped)


def test_squeeze_needs_percentile_window_fade_does_not() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(80, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(80, symbol="ETH/USD", start=start),
    }
    catalog = bollinger_candidates(histories)
    ids = [item.candidate_id for item in catalog]
    assert "bb_fade_20x2" in ids
    assert "bb_lo_fade_40x2" in ids
    assert "bb_squeeze_break_20" not in ids
    assert "bb_squeeze_break_40" not in ids
    skipped = {item["candidate_id"] for item in skipped_bollinger_families(histories)}
    assert skipped == set(SQUEEZE_IDS)


def test_bands_use_closes_through_t_not_t_plus_one() -> None:
    prices = [100.0] * 20 + [120.0, 50.0]
    candles = make_candles(prices)
    at_spike = bollinger_bands_at(candles, 20, period=20, k=2.0)
    assert at_spike is not None
    assert candles[20].close == 120.0
    assert candles[20].close > at_spike.upper
    # The 50 close is t+1 and must not rewrite the spike bar's bands.
    later = bollinger_bands_at(candles, 20, period=20, k=2.0)
    assert later == at_spike
    series = dict(bollinger_position_series(candles, period=20, k=2.0, kind="fade"))
    assert series[candles[20].opened_at] == -1.0


def test_fade_short_above_upper_long_below_lower_flat_inside() -> None:
    spike = make_candles([100.0] * 19 + [120.0])
    dump = make_candles([100.0] * 19 + [80.0])
    inside = make_candles([100.0] * 19 + [120.0, 101.0])
    fade_short = dict(bollinger_position_series(spike, period=20, k=2.0, kind="fade"))
    fade_long = dict(bollinger_position_series(dump, period=20, k=2.0, kind="fade"))
    fade_flat = dict(bollinger_position_series(inside, period=20, k=2.0, kind="fade"))
    assert fade_short[spike[-1].opened_at] == -1.0
    assert fade_long[dump[-1].opened_at] == 1.0
    assert fade_flat[inside[-1].opened_at] == 0.0
    lo_spike = dict(bollinger_position_series(spike, period=20, k=2.0, kind="lo_fade"))
    lo_dump = dict(bollinger_position_series(dump, period=20, k=2.0, kind="lo_fade"))
    assert lo_spike[spike[-1].opened_at] == 0.0
    assert lo_dump[dump[-1].opened_at] == 1.0


def test_on_band_is_inside_not_short() -> None:
    candles = make_candles([100.0] * 20)
    bands = bollinger_bands_at(candles, 19, period=20, k=2.0)
    assert bands is not None
    assert bands.stdev == 0.0
    assert fade_position(bands.upper, bands, long_only=False) == 0.0
    assert fade_position(bands.lower, bands, long_only=False) == 0.0


def test_squeeze_longs_on_expansion_from_low_percentile() -> None:
    prices = [100.0] * 140 + [110.0]
    candles = make_candles(prices)
    series = dict(bollinger_position_series(candles, period=20, k=2.0, kind="squeeze"))
    assert series[candles[-1].opened_at] == 1.0
    fade = dict(bollinger_position_series(candles, period=20, k=2.0, kind="fade"))
    # Expansion above the mid is a fade *short* if it clears the upper band.
    assert fade[candles[-1].opened_at] in {-1.0, 0.0}
    assert fade[candles[-1].opened_at] != 1.0


def test_voter_maps_long_short_and_flat() -> None:
    spike = make_candles([100.0] * 19 + [120.0], symbol="BTC/USD")
    dump = make_candles([100.0] * 19 + [80.0], symbol="ETH/USD")
    histories = {"BTC/USD@1d": spike, "ETH/USD@1d": dump}
    catalog = bollinger_candidates(histories)
    voter = next(item for item in catalog if item.candidate_id == "bb_fade_20x2")
    short = voter.strategy.evaluate(spike, Regime.RANGE)
    long = voter.strategy.evaluate(dump, Regime.RANGE)
    warmup = voter.strategy.evaluate(spike[:5], Regime.RANGE)
    assert short.side is Side.SELL
    assert long.side is Side.BUY
    assert warmup.side is None
    assert "warmup" in warmup.rationale


def test_control_cannot_enter_dual_print_ranking() -> None:
    rows = [
        _row(CONTROL_ID, kraken_combined=True, binance_combined=True, kraken_ho=0.50),
        _row("bb_fade_20x2", kraken_combined=True, binance_combined=True, kraken_ho=0.08),
        _row("bb_lo_fade_20x2", kraken_combined=True, binance_combined=False, kraken_ho=0.40),
    ]
    passers = rank_bollinger_passers(rows)
    assert [row.candidate_id for row in passers] == ["bb_fade_20x2"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False
    assert all(row.candidate_id != CONTROL_ID for row in passers)


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "bb_fade_20x2",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.05,
            binance_ho=0.40,
        ),
        _row(
            "bb_fade_40x2",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "bb_lo_fade_20x2",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.90,
        ),
    ]
    passers = rank_bollinger_passers(rows)
    assert [row.candidate_id for row in passers] == ["bb_fade_40x2", "bb_fade_20x2"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_eth_carried_mean_is_flagged_96_fail() -> None:
    rows = [
        _row(
            "bb_fade_20x2",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.07,
            kraken_btc_ho=-0.16,
            kraken_eth_ho=0.30,
        ),
        _row(
            "bb_lo_fade_20x2",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=-0.02,
            kraken_btc_ho=-0.01,
            kraken_eth_ho=-0.03,
        ),
    ]
    flagged = eth_carried_informational(rows)
    assert [row.candidate_id for row in flagged] == ["bb_fade_20x2"]


def test_positive_holdout_losing_btc_wf_is_flagged() -> None:
    rows = [
        _row(
            "bb_fade_20x2",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.15,
            kraken_btc_ho=0.14,
            kraken_eth_ho=0.16,
            kraken_btc_wf=-0.04,
        ),
        _row(
            "bb_lo_fade_20x2",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.10,
            kraken_btc_ho=0.08,
            kraken_eth_ho=0.12,
            kraken_btc_wf=0.02,
        ),
    ]
    flagged = btc_wf_fail_informational(rows)
    assert [row.candidate_id for row in flagged] == ["bb_fade_20x2"]


def test_empty_binance_is_success_and_cannot_promote() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=start),
            "SOL/USD@1d": downtrend(240, symbol="SOL/USD", start=start),
        },
        {},
    )
    assert report.binance_slice.available is False
    assert report.any_dual_print_passer is False
    assert report.selected_candidate_id is None
    assert report.recommended_promote_flag is None
    assert report.keep_flag_false is True
    assert report.paper_path_ready is True
    assert report.multi_venue_bar_preregistered is True
    assert report.can_average_venues is False
    assert report.multi_asset_gate_rule == MULTI_ASSET_GATE_RULE
    rendered = render_bollinger_fade_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "paper-executable on Kraken spot" in rendered
    assert "Bollinger band-fade" in rendered
    assert "SOL reported" in rendered
    assert "mean_reversion_*" in rendered
    assert settings().paper_promote_ema_9_21_adx15 is False


def test_short_binance_slice_fails_closed() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2023, 1, 1, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=primary),
        },
        {
            "BTCUSDT@1d": downtrend(100, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(100, symbol="ETHUSDT", start=older),
        },
    )
    assert report.binance_slice.available is False
    assert "shorter than 720" in (report.binance_slice.fail_closed_reason or "")
    assert report.any_dual_print_passer is False
    assert report.keep_flag_false is True


def test_binance_older_slice_is_scored_and_cannot_promote() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=primary),
            "SOL/USD@1d": downtrend(240, symbol="SOL/USD", start=primary),
        },
        {
            "BTCUSDT@1d": downtrend(720, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(720, symbol="ETHUSDT", start=older),
            "SOLUSDT@1d": downtrend(720, symbol="SOLUSDT", start=older),
        },
        binance_source="binance_us_spot",
        candidates=None,
    )
    assert report.binance_slice.available is True
    assert report.binance_slice.overlaps_primary_window is False
    assert report.binance_slice.bars_btc == 720
    assert report.keep_flag_false is True
    assert all(row.can_promote is False for row in report.rows)
    assert CONTROL_ID not in report.dual_print_passer_ids
    rendered = render_bollinger_fade_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert "Do not re-run dead EMA dual-prints" in rendered
    assert "#119" in rendered
    assert "equal-weight" in rendered.lower()
    assert "mean_reversion_*" in rendered


def test_signals_do_not_require_paired_days() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = make_candles([100.0 + index for index in range(40)], symbol="BTC/USD", start=start)
    eth = make_candles([100.0] * 40, symbol="ETH/USD", start=start)[:30]
    mapping = bollinger_signals(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        period=20,
        k=2.0,
        kind="fade",
    )
    assert mapping["BTC/USD"]
    assert mapping["ETH/USD"]
    assert len(mapping["BTC/USD"]) != len(mapping["ETH/USD"])


def test_own_asset_bands_are_not_cross_sectional() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = make_candles([100.0] * 19 + [120.0], symbol="BTC/USD", start=start)
    eth = make_candles([100.0] * 19 + [80.0], symbol="ETH/USD", start=start)
    mapping = bollinger_signals(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        period=20,
        k=2.0,
        kind="fade",
    )
    assert mapping["BTC/USD"][-1][1] == -1.0
    assert mapping["ETH/USD"][-1][1] == 1.0


def test_committed_report_freeze_or_empty_success() -> None:
    text = Path("docs/artifacts/strategy-search/bollinger-fade.md").read_text()
    assert "bb_fade_20x2" in text
    assert "bb_squeeze_break_40" in text
    assert "ma_cross_10_30" in text
    assert "PAPER_PROMOTE_*" in text
    assert "keep_flag_false=true" in text or "`keep_flag_false=true`" in text
    assert "Not yet run" in text or "Dual-print passers: 0" in text
    assert settings().paper_promote_ema_9_21 is False
    assert not hasattr(settings(), "paper_promote_bb_fade_20x2")


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "bollinger-fade.md"

    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    btc_usdt = tmp_path / "btcusdt.json"
    eth_usdt = tmp_path / "ethusdt.json"
    write_candles(btc, downtrend(240, symbol="BTC/USD", start=primary))
    write_candles(eth, downtrend(240, symbol="ETH/USD", start=primary))
    write_candles(btc_usdt, downtrend(720, symbol="BTCUSDT", start=older))
    write_candles(eth_usdt, downtrend(720, symbol="ETHUSDT", start=older))
    out_json = tmp_path / "ops" / "bollinger_fade.json"
    out_md = tmp_path / "ops" / "bollinger_fade.md"
    parsed = build_parser().parse_args(
        [
            "--candles",
            str(btc),
            "--candles",
            str(eth),
            "--binance-candles",
            str(btc_usdt),
            "--binance-candles",
            str(eth_usdt),
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
        ]
    )
    written_json, written_md = run(parsed, settings=settings(), candidates=_tiny_catalog())
    assert written_json.is_file()
    assert written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["ranking_key"] == RANKING_KEY
    assert payload["keep_flag_false"] is True
    assert payload["paper_path_ready"] is True
    assert payload["multi_venue_bar_preregistered"] is True
    assert payload["can_average_venues"] is False
    assert payload["any_dual_print_passer"] is False
    assert payload["selected_candidate_id"] is None
    assert payload["multi_asset_gate_rule"] == MULTI_ASSET_GATE_RULE
    text = written_md.read_text()
    assert "Bollinger band-fade" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False
