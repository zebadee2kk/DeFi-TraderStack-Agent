from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
)
from traderstack.research.second_print import DOCUMENTED_PRIMARY_FIRST_ISO, SECOND_PRINT_BARS
from traderstack.research.tsmom import (
    CONTROL_ID,
    CONTROL_IDS,
    CORE_IDS,
    DECISION_RULE,
    FILL_RULE,
    MULTI_ASSET_GATE_RULE,
    PAPER_PATH_READY,
    TSMOM_IDS,
    TSMOM_LOOKBACKS,
    TSMOM_RULES,
    VOL_SCALED_OMITTED_REASON,
    btc_wf_fail_informational,
    eth_carried_informational,
    rank_tsmom_passers,
    render_tsmom_markdown,
    run_tsmom_search,
    skipped_tsmom_families,
    trailing_close_to_close_return,
    tsmom_candidates,
    tsmom_position_series,
    tsmom_signals,
)
from traderstack.research.tsmom_cli import build_parser, run
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


def _momentum_histories(
    count: int = 300, *, start: datetime | None = None
) -> dict[str, tuple[Candle, ...]]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return {
        "BTC/USD@1d": uptrend(count, symbol="BTC/USD", start=opened),
        "ETH/USD@1d": uptrend(count, symbol="ETH/USD", start=opened),
        "SOL/USD@1d": uptrend(count, symbol="SOL/USD", start=opened),
    }


def _tiny_catalog():
    return tsmom_candidates(_momentum_histories(80), include_control=True)


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
    return run_tsmom_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


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
        family="tsmom",
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
    assert not hasattr(cfg, "paper_promote_tsmom_lo_21")
    assert not hasattr(cfg, "paper_promote_tsmom")


def test_catalog_and_bar_are_frozen_before_scoring() -> None:
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert PAPER_PATH_READY is True
    assert DECISION_RULE == "closes_through_t"
    assert FILL_RULE == "next_bar_open"
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in TSMOM_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in TSMOM_RULES
    assert "CAN_AVERAGE_VENUES=false" in TSMOM_RULES
    assert MULTI_ASSET_GATE_RULE == "btc_eth_signs_as_96_abc_sol_reported_not_required"
    assert MULTI_ASSET_GATE_RULE in TSMOM_RULES
    assert TSMOM_LOOKBACKS == (21, 63, 126, 252)
    assert SECOND_PRINT_BARS == 720
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"
    catalog = tsmom_candidates(_momentum_histories(280))
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert ids[:4] == ["tsmom_lo_21", "tsmom_lo_63", "tsmom_lo_126", "tsmom_lo_252"]
    assert ids[4:8] == ["tsmom_ls_21", "tsmom_ls_63", "tsmom_ls_126", "tsmom_ls_252"]
    assert ids[-1] == CONTROL_ID
    assert set(TSMOM_IDS) | CONTROL_IDS == set(CORE_IDS)
    assert "ema_9_21" not in ids
    assert "rv_fade_1_0" not in ids
    assert "xs_mom_lo_21" not in ids
    assert "donchian_lo_20" not in ids
    assert not any("_vol_" in item for item in ids)
    assert VOL_SCALED_OMITTED_REASON.split(";")[0] in TSMOM_RULES
    assert "equal-weight portfolio metrics are not used" in TSMOM_RULES.lower()
    assert "not Donchian / channel breakout" in TSMOM_RULES
    freeze = Path("docs/artifacts/strategy-search/tsmom.md").read_text()
    assert "tsmom_lo_21" in freeze
    assert "tsmom_ls_252" in freeze
    assert "ma_cross_10_30" in freeze
    assert "PAPER_PROMOTE_*" in freeze
    assert "closes_through_t" in freeze
    assert "Not yet run" in freeze or "Dual-print passers" in freeze


def test_missing_sol_does_not_skip_btc_eth_names() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(280, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(280, symbol="ETH/USD", start=start),
    }
    catalog = tsmom_candidates(histories)
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert skipped_tsmom_families(histories) == []


def test_short_history_skips_not_invented() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(10, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(10, symbol="ETH/USD", start=start),
    }
    catalog = tsmom_candidates(histories)
    assert [item.candidate_id for item in catalog] == [CONTROL_ID]
    skipped = skipped_tsmom_families(histories)
    assert {item["candidate_id"] for item in skipped} == set(TSMOM_IDS)
    assert all("invent" in item["reason"] for item in skipped)


def test_trailing_return_uses_close_through_t_not_t_plus_one() -> None:
    prices = [100.0] * 21 + [110.0, 50.0]
    candles = make_candles(prices)
    # index 21 is the first 21-day return: 110/100 - 1. The 50 close is t+1.
    assert trailing_close_to_close_return(candles, 21, 21) == pytest.approx(0.10)
    assert trailing_close_to_close_return(candles, 20, 21) is None
    series = tsmom_position_series(candles, lookback=21, long_short=False)
    assert series[0][1] == 1.0
    # Using the last bar (50) must not rewrite the prior assignment.
    assert dict(series)[candles[21].opened_at] == 1.0


def test_long_only_is_flat_on_negative_long_short_goes_short() -> None:
    prices = [110.0] * 21 + [90.0]
    candles = make_candles(prices)
    lo = dict(tsmom_position_series(candles, lookback=21, long_short=False))
    ls = dict(tsmom_position_series(candles, lookback=21, long_short=True))
    last = candles[-1].opened_at
    assert lo[last] == 0.0
    assert ls[last] == -1.0


def test_zero_return_is_flat_for_both_books() -> None:
    candles = make_candles([100.0] * 22)
    lo = tsmom_position_series(candles, lookback=21, long_short=False)
    ls = tsmom_position_series(candles, lookback=21, long_short=True)
    assert lo[-1][1] == 0.0
    assert ls[-1][1] == 0.0


def test_voter_maps_long_short_and_flat() -> None:
    histories = _momentum_histories(60)
    catalog = tsmom_candidates(histories)
    voter = next(item for item in catalog if item.candidate_id == "tsmom_ls_21")
    btc = histories["BTC/USD@1d"]
    signal = voter.strategy.evaluate(btc, Regime.RANGE)
    assert signal.side is Side.BUY
    warmup = voter.strategy.evaluate(btc[:10], Regime.RANGE)
    assert warmup.side is None
    assert "warmup" in warmup.rationale


def test_control_cannot_enter_dual_print_ranking() -> None:
    rows = [
        _row(CONTROL_ID, kraken_combined=True, binance_combined=True, kraken_ho=0.50),
        _row("tsmom_lo_21", kraken_combined=True, binance_combined=True, kraken_ho=0.08),
        _row("tsmom_ls_63", kraken_combined=True, binance_combined=False, kraken_ho=0.40),
    ]
    passers = rank_tsmom_passers(rows)
    assert [row.candidate_id for row in passers] == ["tsmom_lo_21"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False
    assert all(row.candidate_id != CONTROL_ID for row in passers)


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "tsmom_lo_21",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.05,
            binance_ho=0.40,
        ),
        _row(
            "tsmom_lo_63",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "tsmom_ls_21",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.90,
        ),
    ]
    passers = rank_tsmom_passers(rows)
    assert [row.candidate_id for row in passers] == ["tsmom_lo_63", "tsmom_lo_21"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_eth_carried_mean_is_flagged_96_fail() -> None:
    rows = [
        _row(
            "tsmom_lo_21",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.07,
            kraken_btc_ho=-0.16,
            kraken_eth_ho=0.30,
        ),
        _row(
            "tsmom_ls_21",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=-0.02,
            kraken_btc_ho=-0.01,
            kraken_eth_ho=-0.03,
        ),
    ]
    flagged = eth_carried_informational(rows)
    assert [row.candidate_id for row in flagged] == ["tsmom_lo_21"]


def test_positive_holdout_losing_btc_wf_is_flagged() -> None:
    rows = [
        _row(
            "tsmom_lo_21",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.15,
            kraken_btc_ho=0.14,
            kraken_eth_ho=0.16,
            kraken_btc_wf=-0.04,
        ),
        _row(
            "tsmom_ls_21",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.10,
            kraken_btc_ho=0.08,
            kraken_eth_ho=0.12,
            kraken_btc_wf=0.02,
        ),
    ]
    flagged = btc_wf_fail_informational(rows)
    assert [row.candidate_id for row in flagged] == ["tsmom_lo_21"]


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
    rendered = render_tsmom_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "paper-executable on Kraken spot" in rendered
    assert "Time-series momentum" in rendered
    assert "SOL reported" in rendered
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
    rendered = render_tsmom_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert "Do not re-run dead EMA dual-prints" in rendered
    assert "#118" in rendered
    assert "equal-weight" in rendered.lower()


def test_signals_do_not_require_paired_days() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = make_candles([100.0 + index for index in range(40)], symbol="BTC/USD", start=start)
    eth = make_candles([100.0] * 40, symbol="ETH/USD", start=start)[:30]
    mapping = tsmom_signals(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        lookback=21,
        long_short=False,
    )
    assert mapping["BTC/USD"]
    assert mapping["ETH/USD"]
    assert len(mapping["BTC/USD"]) != len(mapping["ETH/USD"])


def test_own_asset_return_is_not_cross_sectional() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = uptrend(40, symbol="BTC/USD", start=start)
    eth = downtrend(40, symbol="ETH/USD", start=start)
    mapping = tsmom_signals(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        lookback=21,
        long_short=True,
    )
    assert mapping["BTC/USD"][-1][1] == 1.0
    assert mapping["ETH/USD"][-1][1] == -1.0


def test_committed_live_report_is_empty_success() -> None:
    text = Path("docs/artifacts/strategy-search/tsmom.md").read_text()
    assert "Dual-print passers: 0" in text
    assert "`keep_flag_false=true`" in text
    assert "Do not add a new promote flag" in text
    assert "PAPER_PROMOTE_*" in text
    assert "tsmom_lo_21" in text
    assert "tsmom_ls_252" in text
    assert "tsmom_lo_63" in text
    assert "tsmom_ls_63" in text
    assert settings().paper_promote_ema_9_21 is False
    assert not hasattr(settings(), "paper_promote_tsmom_lo_21")


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "tsmom.md"

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
    out_json = tmp_path / "ops" / "tsmom.json"
    out_md = tmp_path / "ops" / "tsmom.md"
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
    assert "Time-series momentum dual-print" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False
