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
from traderstack.research.lead_lag import (
    BTC_TRADED_IDS,
    CONTROL_ID,
    CONTROL_IDS,
    CORE_IDS,
    DECISION_RULE,
    ETH_TRADED_IDS,
    FILL_RULE,
    LEADLAG_CATALOG_NOTE,
    LEADLAG_IDS,
    LEADLAG_RULES,
    MULTI_ASSET_GATE_RULE,
    OTHER_LEG_RULE,
    PAPER_PATH_READY,
    RESIDUAL_OMITTED_REASON,
    aligned_pair_days,
    btc_wf_fail_informational,
    eth_carried_informational,
    lead_trailing_return,
    leadlag_candidates,
    leadlag_position,
    leadlag_position_series,
    leadlag_signals,
    rank_leadlag_passers,
    render_lead_lag_markdown,
    run_lead_lag_search,
    skipped_leadlag_families,
)
from traderstack.research.lead_lag_cli import build_parser, run
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
    skip_indexes: frozenset[int] | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    skipped = skip_indexes or frozenset()
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        if index in skipped:
            continue
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


def _pair_histories(
    count: int = 300, *, start: datetime | None = None
) -> dict[str, tuple[Candle, ...]]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return {
        "BTC/USD@1d": uptrend(count, symbol="BTC/USD", start=opened),
        "ETH/USD@1d": uptrend(count, symbol="ETH/USD", start=opened),
    }


def _tiny_catalog():
    return leadlag_candidates(_pair_histories(80), include_control=True)


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
    return run_lead_lag_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


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
        family="lead_lag",
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
    assert not hasattr(cfg, "paper_promote_leadlag_eth_follow_lo_1")
    assert not hasattr(cfg, "paper_promote_lead_lag")


def test_catalog_and_bar_are_frozen_before_scoring() -> None:
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert PAPER_PATH_READY is True
    assert DECISION_RULE == "lead_closes_through_t"
    assert FILL_RULE == "next_bar_open"
    assert OTHER_LEG_RULE == "flat_on_aligned_pair_days"
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in LEADLAG_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in LEADLAG_RULES
    assert "CAN_AVERAGE_VENUES=false" in LEADLAG_RULES
    assert MULTI_ASSET_GATE_RULE == "btc_eth_both_legs_96_abc_other_leg_flat"
    assert MULTI_ASSET_GATE_RULE in LEADLAG_RULES
    assert OTHER_LEG_RULE in LEADLAG_RULES
    assert DECISION_RULE in LEADLAG_RULES
    assert RESIDUAL_OMITTED_REASON.split(";")[0] in LEADLAG_RULES
    assert "equal-weight portfolio metrics are not used" in LEADLAG_RULES.lower()
    assert "#116" in LEADLAG_RULES
    assert SECOND_PRINT_BARS == 720
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"
    catalog = leadlag_candidates(_pair_histories(40))
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert ids[:4] == [
        "leadlag_eth_follow_lo_1",
        "leadlag_eth_follow_lo_2",
        "leadlag_eth_follow_lo_3",
        "leadlag_eth_follow_lo_5",
    ]
    assert ids[4:7] == [
        "leadlag_eth_follow_ls_1",
        "leadlag_eth_follow_ls_2",
        "leadlag_eth_follow_ls_3",
    ]
    assert ids[7:10] == [
        "leadlag_eth_fade_lo_1",
        "leadlag_eth_fade_lo_2",
        "leadlag_eth_fade_lo_3",
    ]
    assert ids[10:12] == ["leadlag_btc_follow_lo_1", "leadlag_btc_follow_lo_2"]
    assert ids[-1] == CONTROL_ID
    assert set(LEADLAG_IDS) | CONTROL_IDS == set(CORE_IDS)
    assert set(ETH_TRADED_IDS) | set(BTC_TRADED_IDS) == set(LEADLAG_IDS)
    assert "ema_9_21" not in ids
    assert "rv_fade_1_0" not in ids
    assert "xs_mom_lo_21" not in ids
    assert "donchian_lo_20" not in ids
    assert "tsmom_lo_21" not in ids
    assert "bb_fade_20x2" not in ids
    assert "cal_dow_lo_mon" not in ids
    freeze = Path("docs/artifacts/strategy-search/lead-lag.md").read_text()
    assert "leadlag_eth_follow_lo_1" in freeze
    assert "leadlag_eth_follow_ls_3" in freeze
    assert "leadlag_eth_fade_lo_3" in freeze
    assert "leadlag_btc_follow_lo_2" in freeze
    assert "ma_cross_10_30" in freeze
    assert "PAPER_PROMOTE_*" in freeze
    assert "lead_closes_through_t" in freeze
    assert "Not yet run" in freeze or "Dual-print passers" in freeze
    assert LEADLAG_CATALOG_NOTE.startswith("Frozen catalog")


def test_missing_pair_skips_not_invented() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {"BTC/USD@1d": downtrend(40, symbol="BTC/USD", start=start)}
    catalog = leadlag_candidates(histories)
    assert [item.candidate_id for item in catalog] == [CONTROL_ID]
    skipped = skipped_leadlag_families(histories)
    assert {item["candidate_id"] for item in skipped} == set(LEADLAG_IDS)
    assert all("invent" in item["reason"] for item in skipped)


def test_short_history_skips_not_invented() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(1, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(1, symbol="ETH/USD", start=start),
    }
    catalog = leadlag_candidates(histories)
    assert [item.candidate_id for item in catalog] == [CONTROL_ID]
    skipped = skipped_leadlag_families(histories)
    assert {item["candidate_id"] for item in skipped} == set(LEADLAG_IDS)


def test_unpaired_days_are_skipped_not_zero_filled() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = make_candles([100.0, 101.0, 102.0, 103.0, 104.0], symbol="BTC/USD", start=start)
    eth = make_candles(
        [50.0, 51.0, 52.0, 53.0, 54.0],
        symbol="ETH/USD",
        start=start,
        skip_indexes=frozenset({2}),
    )
    pair = aligned_pair_days(btc, eth)
    assert [row[0] for row in pair] == [
        start,
        start + timedelta(days=1),
        start + timedelta(days=3),
        start + timedelta(days=4),
    ]
    mapping = leadlag_signals(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        traded="ETH",
        lead="BTC",
        lookback=1,
        book="follow_lo",
    )
    eth_ts = {ts for ts, _ in mapping["ETH/USD"]}
    assert start + timedelta(days=2) not in eth_ts
    assert start + timedelta(days=3) in eth_ts


def test_lead_return_uses_closes_through_t_not_t_plus_one() -> None:
    # BTC: 100, 100, 110, 50. L=1 at the 110 bar is +10%; 50 is t+1.
    btc_prices = [100.0, 100.0, 110.0, 50.0]
    eth_prices = [10.0, 10.0, 10.0, 10.0]
    start = datetime(2024, 1, 1, tzinfo=UTC)
    pair = aligned_pair_days(
        make_candles(btc_prices, symbol="BTC/USD", start=start),
        make_candles(eth_prices, symbol="ETH/USD", start=start),
    )
    lead_closes = tuple(row[1] for row in pair)
    assert lead_trailing_return(lead_closes, 2, 1) == pytest.approx(0.10)
    assert lead_trailing_return(lead_closes, 1, 1) == pytest.approx(0.0)
    series = leadlag_position_series(pair, lead="BTC", lookback=1, book="follow_lo")
    by_ts = dict(series)
    assert by_ts[start + timedelta(days=2)] == 1.0
    # The crash at t+1 must not rewrite the assignment at t.
    assert by_ts[start + timedelta(days=2)] == 1.0


def test_eth_gate_does_not_use_same_bar_eth() -> None:
    # BTC rises on the last bar; ETH crashes on the same bar.
    # Follow-ETH must still go long because the gate is lagged BTC.
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = make_candles([100.0, 100.0, 120.0], symbol="BTC/USD", start=start)
    eth = make_candles([50.0, 50.0, 1.0], symbol="ETH/USD", start=start)
    mapping = leadlag_signals(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        traded="ETH",
        lead="BTC",
        lookback=1,
        book="follow_lo",
    )
    last = start + timedelta(days=2)
    assert dict(mapping["ETH/USD"])[last] == 1.0
    assert dict(mapping["BTC/USD"])[last] == 0.0


def test_follow_and_fade_books() -> None:
    assert leadlag_position(0.05, book="follow_lo") == 1.0
    assert leadlag_position(-0.05, book="follow_lo") == 0.0
    assert leadlag_position(-0.05, book="follow_ls") == -1.0
    assert leadlag_position(0.0, book="follow_ls") == 0.0
    assert leadlag_position(-0.05, book="fade_lo") == 1.0
    assert leadlag_position(0.05, book="fade_lo") == 0.0


def test_other_leg_is_flat_on_aligned_days() -> None:
    histories = _pair_histories(10)
    eth_follow = leadlag_signals(histories, traded="ETH", lead="BTC", lookback=1, book="follow_lo")
    btc_follow = leadlag_signals(histories, traded="BTC", lead="ETH", lookback=1, book="follow_lo")
    assert eth_follow["ETH/USD"]
    assert all(value == 0.0 for _, value in eth_follow["BTC/USD"])
    assert all(value == 1.0 for _, value in eth_follow["ETH/USD"])
    assert all(value == 0.0 for _, value in btc_follow["ETH/USD"])
    assert all(value == 1.0 for _, value in btc_follow["BTC/USD"])


def test_voter_maps_long_short_and_flat() -> None:
    histories = _pair_histories(20)
    catalog = leadlag_candidates(histories)
    voter = next(item for item in catalog if item.candidate_id == "leadlag_eth_follow_ls_1")
    eth = histories["ETH/USD@1d"]
    btc = histories["BTC/USD@1d"]
    eth_signal = voter.strategy.evaluate(eth, Regime.RANGE)
    assert eth_signal.side is Side.BUY
    btc_signal = voter.strategy.evaluate(btc, Regime.RANGE)
    assert btc_signal.side is None
    warmup = voter.strategy.evaluate(eth[:1], Regime.RANGE)
    assert warmup.side is None
    assert "unpaired" in warmup.rationale or "warmup" in warmup.rationale


def test_control_cannot_enter_dual_print_ranking() -> None:
    rows = [
        _row(CONTROL_ID, kraken_combined=True, binance_combined=True, kraken_ho=0.50),
        _row(
            "leadlag_eth_follow_lo_1",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.08,
        ),
        _row(
            "leadlag_eth_follow_ls_1",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.40,
        ),
    ]
    passers = rank_leadlag_passers(rows)
    assert [row.candidate_id for row in passers] == ["leadlag_eth_follow_lo_1"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False
    assert all(row.candidate_id != CONTROL_ID for row in passers)


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "leadlag_eth_follow_lo_1",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.05,
            binance_ho=0.40,
        ),
        _row(
            "leadlag_eth_follow_lo_2",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "leadlag_eth_follow_ls_1",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.90,
        ),
    ]
    passers = rank_leadlag_passers(rows)
    assert [row.candidate_id for row in passers] == [
        "leadlag_eth_follow_lo_2",
        "leadlag_eth_follow_lo_1",
    ]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_eth_carried_mean_is_flagged_96_fail() -> None:
    rows = [
        _row(
            "leadlag_eth_follow_lo_1",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.07,
            kraken_btc_ho=-0.16,
            kraken_eth_ho=0.30,
        ),
        _row(
            "leadlag_eth_follow_ls_1",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=-0.02,
            kraken_btc_ho=-0.01,
            kraken_eth_ho=-0.03,
        ),
    ]
    flagged = eth_carried_informational(rows)
    assert [row.candidate_id for row in flagged] == ["leadlag_eth_follow_lo_1"]


def test_positive_holdout_losing_btc_wf_is_flagged() -> None:
    rows = [
        _row(
            "leadlag_btc_follow_lo_1",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.15,
            kraken_btc_ho=0.14,
            kraken_eth_ho=0.16,
            kraken_btc_wf=-0.04,
        ),
        _row(
            "leadlag_btc_follow_lo_2",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.10,
            kraken_btc_ho=0.08,
            kraken_eth_ho=0.12,
            kraken_btc_wf=0.02,
        ),
    ]
    flagged = btc_wf_fail_informational(rows)
    assert [row.candidate_id for row in flagged] == ["leadlag_btc_follow_lo_1"]


def test_empty_binance_is_success_and_cannot_promote() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=start),
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
    rendered = render_lead_lag_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "paper-executable on Kraken spot" in rendered
    assert "lead-lag" in rendered.lower()
    assert "other leg" in rendered.lower()
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
        },
        {
            "BTCUSDT@1d": downtrend(720, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(720, symbol="ETHUSDT", start=older),
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
    rendered = render_lead_lag_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert "Do not re-run dead EMA dual-prints" in rendered
    assert "#121" in rendered
    assert "equal-weight" in rendered.lower()
    assert "not #116" in rendered.lower() or "not same-bar residual" in rendered.lower()


def test_committed_live_report_is_empty_success() -> None:
    text = Path("docs/artifacts/strategy-search/lead-lag.md").read_text()
    assert "Dual-print passers: 0" in text
    assert "`keep_flag_false=true`" in text
    assert "Do not add a new promote flag" in text
    assert "PAPER_PROMOTE_*" in text
    assert "leadlag_eth_follow_lo_1" in text
    assert "leadlag_eth_follow_lo_5" in text
    assert "leadlag_btc_follow_lo_2" in text
    assert "leadlag_eth_follow_lo_5" in text
    assert settings().paper_promote_ema_9_21 is False
    assert not hasattr(settings(), "paper_promote_leadlag_eth_follow_lo_1")


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "lead-lag.md"

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
    out_json = tmp_path / "ops" / "lead_lag.json"
    out_md = tmp_path / "ops" / "lead_lag.md"
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
    assert "BTC→ETH lead-lag dual-print" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False
