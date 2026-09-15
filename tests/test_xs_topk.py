from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.cross_sectional_momentum import XS_IDS
from traderstack.research.universe import LIQUIDITY_FILTER_RULE, liquidity_snapshots
from traderstack.research.xs_topk import (
    CONTROL_ID,
    CORE_IDS,
    DSR_PBO_STATUS,
    ERA_IDS,
    MIN_CROSS_SECTION,
    PAPER_PATH_READY,
    PILOT_TIER_TAKER_BPS,
    PORTFOLIO_BAR_RULE,
    RANKING_KEY,
    REBALANCE_RULE,
    TOPK_CATALOG,
    TOPK_IDS,
    TOPK_KS,
    TOPK_LOOKBACKS,
    TOPK_SKIP_DAYS,
    XS_TOPK_RULES,
    CandidatePrint,
    EraCell,
    PrintMeta,
    PrintResult,
    RebalanceDecision,
    TopKRow,
    _weights_for,
    aligned_closes_by_symbol,
    basket_equity_path,
    build_xs_topk_report,
    dual_print_rows,
    ew_universe_control_targets,
    rank_topk_passers,
    render_xs_topk_markdown,
    score_print,
    simulate_basket,
    topk_targets,
    voter_from_decisions,
)
from traderstack.research.xs_topk_cli import (
    UNIVERSE_LISTING_FILENAME,
    build_parser,
    cache_path,
    load_universe_file,
    run,
)
from traderstack.strategies import Regime

START = datetime(2024, 1, 1, tzinfo=UTC)  # a Monday
assert START.weekday() == 0


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
    symbol: str,
    interval: str = "1d",
    start: datetime = START,
    volume: float = 1_000.0,
) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=start + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=volume,
            )
        )
    return tuple(candles)


def _prices(index: int, days: int, *, drift: float | None = None) -> list[float]:
    """Deterministic, distinct paths: drift by rank plus a phase-shifted wobble."""
    slope = drift if drift is not None else 0.0006 * (index - 5)
    out = [100.0]
    for day in range(1, days):
        wobble = 0.004 * math.sin(day / 6.0 + index)
        out.append(out[-1] * (1.0 + slope + wobble))
    return out


def universe_histories(
    n: int = 12, days: int = 420, *, start: datetime = START
) -> dict[str, tuple[Candle, ...]]:
    return {
        f"N{i:02d}/USD@1d": make_candles(
            _prices(i, days), symbol=f"N{i:02d}/USD", start=start, volume=1_000.0 * (n - i)
        )
        for i in range(n)
    }


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _first_nonempty(decisions: tuple[RebalanceDecision, ...]) -> RebalanceDecision:
    return next(item for item in decisions if item.weights)


# ---------------------------------------------------------------------------
# Frozen catalog and settings
# ---------------------------------------------------------------------------


def test_promote_defaults_stay_false() -> None:
    values = settings()
    assert values.trading_mode == "paper"
    assert values.paper_promote_searched_strategies is False
    assert values.paper_promote_ema_9_21 is False
    assert values.paper_promote_ema_9_21_adx15 is False
    assert not any(name.startswith("paper_promote_xs_topk") for name in type(values).model_fields)


def test_catalog_and_bar_are_frozen_before_scoring() -> None:
    assert TOPK_LOOKBACKS == (21, 63, 126)
    assert TOPK_SKIP_DAYS == 7
    assert TOPK_KS == (3, 5)
    assert len(TOPK_CATALOG) == 12
    assert TOPK_IDS == (
        "xs_topk_ew_21_k3",
        "xs_topk_ew_21_k5",
        "xs_topk_ew_63_k3",
        "xs_topk_ew_63_k5",
        "xs_topk_ew_126_k3",
        "xs_topk_ew_126_k5",
        "xs_topk_iv_21_k3",
        "xs_topk_iv_21_k5",
        "xs_topk_iv_63_k3",
        "xs_topk_iv_63_k5",
        "xs_topk_iv_126_k3",
        "xs_topk_iv_126_k5",
    )
    assert CORE_IDS[-1] == CONTROL_ID == "ew_bh_universe"
    assert len(CORE_IDS) == 13
    assert not set(TOPK_IDS) & set(XS_IDS)
    for token in (
        RANKING_KEY,
        PORTFOLIO_BAR_RULE,
        LIQUIDITY_FILTER_RULE,
        REBALANCE_RULE,
        "DSR",
        "PBO",
        "#135",
        "MIN_CROSS_SECTION=10",
    ):
        assert token in XS_TOPK_RULES
    assert DSR_PBO_STATUS == "not_computed_pending_135"
    assert PILOT_TIER_TAKER_BPS == 80.0
    assert ERA_IDS == ("2016-2019", "2020-2022", "2022-2024", "2024-2026")
    assert PAPER_PATH_READY is True


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------


def test_skip_week_score_excludes_last_seven_days() -> None:
    histories = universe_histories()
    snapshots = liquidity_snapshots(histories)
    decisions = topk_targets(histories, snapshots, lookback=21, k=3, weighting="ew")
    target = [item for item in decisions if item.weights][3]
    at = target.decided_at
    loser = next(
        name for name in sorted(aligned_closes_by_symbol(histories)) if name not in target.weights
    )

    def _bumped(from_offset: int, to_offset: int) -> dict[str, tuple[Candle, ...]]:
        bumped = dict(histories)
        candles = bumped[f"{loser}@1d"]
        prices = [candle.close for candle in candles]
        for index, candle in enumerate(candles):
            if (
                at - timedelta(days=from_offset)
                <= candle.opened_at
                <= at - timedelta(days=to_offset)
            ):
                prices[index] = prices[index] * 3.0
        bumped[f"{loser}@1d"] = make_candles(prices, symbol=loser, volume=candles[0].volume)
        return bumped

    inside_skip = topk_targets(_bumped(6, 0), snapshots, lookback=21, k=3, weighting="ew")
    same_day = next(item for item in inside_skip if item.decided_at == at)
    assert same_day.weights == target.weights  # jump inside the skip week is invisible
    at_edge = topk_targets(_bumped(7, 7), snapshots, lookback=21, k=3, weighting="ew")
    edge_day = next(item for item in at_edge if item.decided_at == at)
    assert loser in edge_day.weights  # close[t-7] is the scoring endpoint


def test_rebalance_only_on_monday_utc_and_fills_next_open() -> None:
    histories = universe_histories()
    snapshots = liquidity_snapshots(histories)
    decisions = topk_targets(histories, snapshots, lookback=21, k=3, weighting="ew")
    assert decisions and all(item.decided_at.weekday() == 0 for item in decisions)
    first = _first_nonempty(decisions)
    path = dict(basket_equity_path(histories, (first,), cost_bps=10.0, starting_equity=10_000.0))
    assert path[first.decided_at] == pytest.approx(10_000.0)
    assert path[first.decided_at - timedelta(days=1)] == pytest.approx(10_000.0)
    assert path[first.decided_at + timedelta(days=1)] != pytest.approx(10_000.0)


def test_missing_bar_skips_name_not_zero_filled() -> None:
    histories = universe_histories()
    snapshots = liquidity_snapshots(histories)
    decisions = topk_targets(histories, snapshots, lookback=21, k=3, weighting="ew")
    target = [item for item in decisions if item.weights][3]
    at = target.decided_at
    victim = min(target.weights)
    gapped = dict(histories)
    gapped[f"{victim}@1d"] = tuple(
        candle
        for candle in histories[f"{victim}@1d"]
        if candle.opened_at != at - timedelta(days=TOPK_SKIP_DAYS)
    )
    redo = topk_targets(gapped, snapshots, lookback=21, k=3, weighting="ew")
    same_day = next(item for item in redo if item.decided_at == at)
    assert victim not in same_day.weights
    assert len(same_day.weights) == 3
    assert all(weight > 0 for weight in same_day.weights.values())
    assert same_day.rankable == target.rankable - 1
    affected = {at, at + timedelta(days=21)}
    for before, after in zip(decisions, redo, strict=True):
        if before.decided_at not in affected:
            assert before.weights == after.weights


def test_thin_cross_section_is_flat_week() -> None:
    histories = universe_histories(n=MIN_CROSS_SECTION - 1, days=200)
    snapshots = liquidity_snapshots(histories)
    decisions = topk_targets(histories, snapshots, lookback=21, k=3, weighting="ew")
    with_snapshot = [item for item in decisions if item.reason != "no_universe_snapshot"]
    assert with_snapshot
    assert all(item.reason == "thin_cross_section" and not item.weights for item in with_snapshot)
    metrics = simulate_basket(histories, decisions, cost_bps=85.0)
    assert metrics is not None
    assert metrics.flat_weeks == len(decisions)
    assert metrics.total_return == pytest.approx(0.0)
    assert metrics.total_fees == 0.0


def test_universe_membership_is_point_in_time() -> None:
    histories = universe_histories(n=12, days=420)
    late_start = START + timedelta(days=200)
    histories["LATE/USD@1d"] = make_candles(
        _prices(0, 220, drift=0.02), symbol="LATE/USD", start=late_start, volume=1e9
    )
    snapshots = liquidity_snapshots(histories)
    first_member = next(snap.snapshot_at for snap in snapshots if "LATE/USD" in snap.names)
    assert first_member >= late_start + timedelta(days=30)
    decisions = topk_targets(histories, snapshots, lookback=21, k=3, weighting="ew")
    assert not any(
        "LATE/USD" in item.weights for item in decisions if item.decided_at < first_member
    )
    assert any("LATE/USD" in item.weights for item in decisions if item.decided_at >= first_member)


def test_weights_long_only_sum_to_one_and_iv_favours_low_vol() -> None:
    histories = universe_histories()
    snapshots = liquidity_snapshots(histories)
    for weighting in ("ew", "iv"):
        for k in TOPK_KS:
            decisions = topk_targets(histories, snapshots, lookback=21, k=k, weighting=weighting)
            for item in decisions:
                if not item.weights:
                    continue
                assert len(item.weights) == k
                assert sum(item.weights.values()) == pytest.approx(1.0)
                assert all(weight > 0 for weight in item.weights.values())
                if weighting == "ew":
                    assert all(weight == pytest.approx(1.0 / k) for weight in item.weights.values())
    calm = [100.0 * (1.0 + 0.001 * (i % 2)) for i in range(40)]
    wild = [100.0 * (1.0 + 0.05 * ((i % 2) - 0.5)) for i in range(40)]
    closes = aligned_closes_by_symbol(
        {
            "CALM/USD@1d": make_candles(calm, symbol="CALM/USD"),
            "WILD/USD@1d": make_candles(wild, symbol="WILD/USD"),
        }
    )
    at = START + timedelta(days=39)
    weights = _weights_for(["CALM/USD", "WILD/USD"], weighting="iv", closes=closes, at=at)
    assert weights["CALM/USD"] > weights["WILD/USD"] > 0
    assert sum(weights.values()) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        _weights_for(["CALM/USD"], weighting="xx", closes=closes, at=at)


# ---------------------------------------------------------------------------
# Basket simulator: turnover, fees, control
# ---------------------------------------------------------------------------


def test_turnover_and_fee_drag_reported() -> None:
    flat = {
        "A/USD@1d": make_candles([10.0] * 60, symbol="A/USD"),
        "B/USD@1d": make_candles([10.0] * 60, symbol="B/USD"),
    }
    rotate = (
        RebalanceDecision(decided_at=START, weights={"A/USD": 1.0}),
        RebalanceDecision(decided_at=START + timedelta(days=7), weights={"B/USD": 1.0}),
    )
    free = simulate_basket(flat, rotate, cost_bps=0.0, starting_equity=10_000.0)
    assert free is not None
    assert free.traded_fraction == pytest.approx(3.0)
    assert free.one_way_turnover == pytest.approx(1.5)
    assert free.total_fees == 0.0 and free.total_return == pytest.approx(0.0)
    assert free.rebalances == 2

    research = simulate_basket(flat, rotate, cost_bps=15.0, starting_equity=10_000.0)
    pilot = simulate_basket(flat, rotate, cost_bps=PILOT_TIER_TAKER_BPS + 5.0)
    assert research is not None and pilot is not None
    c = 0.0085
    assert pilot.total_fees == pytest.approx(10_000.0 * c * (3.0 - c))
    assert pilot.fee_drag == pytest.approx(pilot.total_fees / 10_000.0)
    assert pilot.fee_drag > research.fee_drag > 0
    assert pilot.total_return < research.total_return < 0

    hold = (
        RebalanceDecision(decided_at=START, weights={"A/USD": 0.5, "B/USD": 0.5}),
        RebalanceDecision(
            decided_at=START + timedelta(days=7), weights={"A/USD": 0.5, "B/USD": 0.5}
        ),
    )
    steady = simulate_basket(flat, hold, cost_bps=0.0)
    assert steady is not None
    assert steady.traded_fraction == pytest.approx(1.0)  # only the initial buy


def test_window_start_carries_in_the_latest_prior_decision() -> None:
    flat = {
        "A/USD@1d": make_candles([10.0] * 30, symbol="A/USD"),
        "B/USD@1d": make_candles([10.0] * 30, symbol="B/USD"),
    }
    decisions = (
        RebalanceDecision(decided_at=START, weights={"A/USD": 1.0}),
        RebalanceDecision(decided_at=START + timedelta(days=7), weights={"B/USD": 1.0}),
    )
    later = simulate_basket(flat, decisions, cost_bps=100.0, start=START + timedelta(days=10))
    assert later is not None
    # Only the B decision is carried in: one fill of 1.0 traded, one-way 0.5.
    assert later.rebalances == 1
    assert later.traded_fraction == pytest.approx(1.0)
    assert later.total_fees == pytest.approx(100.0)
    untouched = simulate_basket(flat, decisions, cost_bps=100.0, start=START - timedelta(days=1))
    assert untouched is not None and untouched.rebalances == 2


def test_print_without_covered_era_does_not_count_against_dual_print() -> None:
    a = "xs_topk_ew_21_k3"
    covered = _print(
        "coinbase",
        {
            a: [
                _cell("coinbase", "2020-2022", passed=True, excess=0.10),
                _cell("coinbase", "2022-2024", passed=True, excess=0.10),
            ]
        },
    )
    uncovered = _print("kraken", {}, holdout_pass=False)
    row = next(item for item in dual_print_rows([covered, uncovered]) if item.candidate_id == a)
    assert row.venues == ["coinbase", "kraken"]
    assert row.holdout_failures == 0 and row.dual_print is True


def test_missing_open_skips_fill_and_missing_close_keeps_last_mark() -> None:
    a = make_candles([10.0] * 20, symbol="A/USD")
    b = make_candles([10.0] * 20, symbol="B/USD")
    gap_open = START + timedelta(days=1)
    histories = {
        "A/USD@1d": tuple(c for c in a if c.opened_at != gap_open),
        "B/USD@1d": tuple(c for c in b if c.opened_at != START + timedelta(days=5)),
    }
    decisions = (RebalanceDecision(decided_at=START, weights={"A/USD": 0.5, "B/USD": 0.5}),)
    metrics = simulate_basket(histories, decisions, cost_bps=0.0)
    assert metrics is not None
    assert metrics.fills_skipped == 1  # A had no open on the fill bar
    assert metrics.stale_marks == 1  # B had no close on day 5
    assert metrics.total_return == pytest.approx(0.0)


def test_control_is_ew_bh_of_same_universe_and_cannot_rank() -> None:
    histories = universe_histories()
    snapshots = liquidity_snapshots(histories)
    control = ew_universe_control_targets(histories, snapshots)
    assert len(control) == len(snapshots)
    for decision, snapshot in zip(control, snapshots, strict=True):
        assert decision.decided_at >= snapshot.snapshot_at
        assert set(decision.weights) == set(snapshot.names)
        assert all(w == pytest.approx(1.0 / len(snapshot.names)) for w in decision.weights.values())
    row = TopKRow(candidate_id=CONTROL_ID, family="control", label="c", dual_print=True)
    row.mean_era_excess_pilot = 9.9
    assert rank_topk_passers([row]) == []


# ---------------------------------------------------------------------------
# Prints, eras, dual print, ranking
# ---------------------------------------------------------------------------


def test_single_era_single_venue_cannot_dual_print() -> None:
    histories = universe_histories()
    result = score_print("kraken", histories, source="synthetic")
    assert result.meta.status == "ok"
    assert result.meta.eras_covered == ["2024-2026"]
    assert result.meta.names_loaded == 12
    assert [item.candidate_id for item in result.candidates] == list(CORE_IDS)
    for candidate in result.candidates:
        assert candidate.covered_cells == 1
        assert candidate.full_pilot is not None and candidate.full_research is not None
        assert candidate.full_pilot.fee_drag >= candidate.full_research.fee_drag
    control = result.candidates[-1]
    assert control.print_pass is False and control.passed_cells == 0
    report = build_xs_topk_report(
        [result],
        fee_bps=10.0,
        slippage_bps=5.0,
        pilot_fee_bps=PILOT_TIER_TAKER_BPS,
        starting_equity=10_000.0,
        holdout_fraction=0.2,
    )
    assert report.keep_flag_false is True
    assert report.any_dual_print_passer is False
    assert report.selected_candidate_id is None
    assert all(row.dual_print is False and row.can_promote is False for row in report.rows)
    assert all(row.passed_cells <= 1 for row in report.rows)
    text = render_xs_topk_markdown(report)
    assert "Dual-print passers: 0" in text
    assert "no name can dual-print on this data" in text
    assert "`keep_flag_false=true`" in text
    assert DSR_PBO_STATUS in text


def _cell(venue: str, era_id: str, *, passed: bool, excess: float) -> EraCell:
    return EraCell(
        venue=venue,
        era_id=era_id,
        covered=True,
        bars=700,
        excess_vs_control_pilot=excess,
        bar_pass=passed,
        fail_reasons=[] if passed else ["pilot_excess_vs_ew_bh_le_0"],
    )


def _print(
    venue: str,
    cells: dict[str, list[EraCell]],
    *,
    holdout_pass: bool = True,
) -> PrintResult:
    candidates: list[CandidatePrint] = []
    for candidate_id in CORE_IDS:
        own = cells.get(candidate_id, [])
        is_control = candidate_id == CONTROL_ID
        passed = sum(1 for cell in own if cell.bar_pass)
        candidates.append(
            CandidatePrint(
                candidate_id=candidate_id,
                venue=venue,
                cells=own,
                covered_cells=len(own),
                passed_cells=passed,
                failed_cells=len(own) - passed,
                holdout_excess_pilot=0.01 if holdout_pass else -0.01,
                holdout_pass=holdout_pass and not is_control,
                print_pass=bool(own) and passed == len(own) and holdout_pass and not is_control,
            )
        )
    meta = PrintMeta(
        venue=venue,
        source="hand",
        status="ok",
        names_loaded=20,
        eras_covered=sorted({cell.era_id for own in cells.values() for cell in own}),
    )
    return PrintResult(meta=meta, candidates=candidates)


def test_two_venues_same_era_and_two_eras_one_venue_both_count_as_dual_print() -> None:
    a, b = "xs_topk_ew_21_k3", "xs_topk_iv_63_k5"
    two_venues = [
        _print("kraken", {a: [_cell("kraken", "2024-2026", passed=True, excess=0.05)]}),
        _print("coinbase", {a: [_cell("coinbase", "2024-2026", passed=True, excess=0.15)]}),
    ]
    rows = dual_print_rows(two_venues)
    row_a = next(row for row in rows if row.candidate_id == a)
    assert row_a.dual_print is True and row_a.passed_cells == 2
    assert row_a.mean_era_excess_pilot == pytest.approx(0.10)

    two_eras = [
        _print(
            "coinbase",
            {
                a: [
                    _cell("coinbase", "2020-2022", passed=True, excess=0.10),
                    _cell("coinbase", "2022-2024", passed=True, excess=0.10),
                ],
                b: [
                    _cell("coinbase", "2020-2022", passed=True, excess=0.30),
                    _cell("coinbase", "2022-2024", passed=True, excess=0.10),
                ],
                CONTROL_ID: [
                    _cell("coinbase", "2020-2022", passed=True, excess=9.0),
                    _cell("coinbase", "2022-2024", passed=True, excess=9.0),
                ],
            },
        )
    ]
    report = build_xs_topk_report(
        two_eras,
        fee_bps=10.0,
        slippage_bps=5.0,
        pilot_fee_bps=PILOT_TIER_TAKER_BPS,
        starting_equity=10_000.0,
        holdout_fraction=0.2,
    )
    assert report.any_dual_print_passer is True
    assert report.dual_print_passer_ids == [b, a]  # ranked by mean era excess
    assert report.selected_candidate_id == b
    assert report.recommended_promote_flag == "PAPER_PROMOTE_XS_TOPK_IV_63_K5"
    assert not hasattr(settings(), "paper_promote_xs_topk_iv_63_k5")
    selected = next(row for row in report.rows if row.candidate_id == b)
    assert selected.selected is True and selected.can_promote is False
    control = next(row for row in report.rows if row.candidate_id == CONTROL_ID)
    assert control.dual_print is False
    assert report.keep_flag_false is True
    text = render_xs_topk_markdown(report)
    assert "default **false** if added" in text
    assert "| 1 | `xs_topk_iv_63_k5` |" in text

    tie = [
        _print(
            "coinbase",
            {
                a: [
                    _cell("coinbase", "2020-2022", passed=True, excess=0.10),
                    _cell("coinbase", "2022-2024", passed=True, excess=0.10),
                ],
                b: [
                    _cell("coinbase", "2020-2022", passed=True, excess=0.10),
                    _cell("coinbase", "2022-2024", passed=True, excess=0.10),
                ],
            },
        )
    ]
    ranked = rank_topk_passers(dual_print_rows(tie))
    assert [row.candidate_id for row in ranked] == [a, b]  # candidate_id tie-break


def test_era_failure_in_any_long_era_fails_the_bar() -> None:
    a = "xs_topk_ew_63_k5"
    prints = [
        _print(
            "coinbase",
            {
                a: [
                    _cell("coinbase", "2020-2022", passed=True, excess=0.40),
                    _cell("coinbase", "2022-2024", passed=False, excess=-0.20),
                    _cell("coinbase", "2024-2026", passed=True, excess=0.10),
                ]
            },
        )
    ]
    row = next(item for item in dual_print_rows(prints) if item.candidate_id == a)
    assert row.passed_cells == 2 and row.failed_cells == 1
    assert row.dual_print is False
    holdout_fail = [
        _print(
            "coinbase",
            {
                a: [
                    _cell("coinbase", "2020-2022", passed=True, excess=0.40),
                    _cell("coinbase", "2022-2024", passed=True, excess=0.20),
                ]
            },
            holdout_pass=False,
        )
    ]
    row = next(item for item in dual_print_rows(holdout_fail) if item.candidate_id == a)
    assert row.holdout_failures == 1 and row.dual_print is False


# ---------------------------------------------------------------------------
# Paper voter
# ---------------------------------------------------------------------------


def test_voter_same_bar_only_long_or_flat() -> None:
    histories = universe_histories()
    snapshots = liquidity_snapshots(histories)
    decisions = topk_targets(histories, snapshots, lookback=21, k=3, weighting="ew")
    voter = voter_from_decisions("xs_topk_ew_21_k3", decisions)
    first = _first_nonempty(decisions)
    name = min(first.weights)
    candles = tuple(c for c in histories[f"{name}@1d"] if c.opened_at <= first.decided_at)
    signal = voter.evaluate(candles, Regime.RANGE)
    assert signal.side is Side.BUY and signal.score == pytest.approx(1.0 / 3.0)
    off = voter.evaluate(candles[:-1], Regime.RANGE)
    assert off.side is None and "skipped" in off.rationale
    for decision in decisions:
        for symbol in aligned_closes_by_symbol(histories):
            series = tuple(
                c for c in histories[f"{symbol}@1d"] if c.opened_at <= decision.decided_at
            )
            if series:
                assert voter.evaluate(series, Regime.RANGE).side is not Side.SELL


# ---------------------------------------------------------------------------
# Committed report and CLI
# ---------------------------------------------------------------------------


def test_committed_live_report_is_empty_success() -> None:
    text = Path("docs/artifacts/strategy-search/xs-topk.md").read_text()
    assert "Dual-print passers: 0" in text
    assert "`keep_flag_false=true`" in text
    assert "Do not add a new promote flag" in text
    assert "PAPER_PROMOTE_*" in text
    assert "Universe listing: `kraken_asset_pairs` fetched 2026-09-" in text
    assert f"DSR / PBO: `{DSR_PBO_STATUS}`" in text
    assert "no name can dual-print on this data" in text
    assert not hasattr(settings(), "paper_promote_xs_topk_ew_21_k3")


def test_cli_candles_dir_writes_json_and_md(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles-dir", "kraken", "x"])
    assert args.output_md.name == "xs-topk.md"
    assert args.pilot_fee_bps == PILOT_TIER_TAKER_BPS

    long_dir = tmp_path / "kraken"
    short_dir = tmp_path / "coinbase"
    long_dir.mkdir()
    short_dir.mkdir()
    for key, candles in universe_histories().items():
        write_candles(long_dir / (key.replace("/", "_") + ".json"), candles)
    for key, candles in universe_histories(days=300).items():
        write_candles(short_dir / (key.replace("/", "_") + ".json"), candles)
    (short_dir / "tiny.json").write_text(json.dumps([]))
    hourly = make_candles([1.0, 1.0, 1.0], symbol="H/USD", interval="1h")
    write_candles(short_dir / "hourly.json", hourly)
    universe_file = tmp_path / "universe.json"
    universe_file.write_text(json.dumps([f"N{i:02d}/USD" for i in range(12)] + ["XBT/USD"]))
    assert load_universe_file(universe_file)[-1] == "N11/USD"
    args = build_parser().parse_args(
        [
            "--candles-dir",
            "kraken",
            str(long_dir),
            "--candles-dir",
            "coinbase",
            str(short_dir),
            "--universe-file",
            str(universe_file),
            "--output-json",
            str(tmp_path / "out.json"),
            "--output-md",
            str(tmp_path / "out.md"),
        ]
    )
    out_json, out_md = run(args, settings())
    payload = json.loads(out_json.read_text())
    assert payload["ranking_key"] == RANKING_KEY
    assert payload["keep_flag_false"] is True
    assert payload["paper_path_ready"] is True
    assert payload["any_dual_print_passer"] is False
    assert payload["fee_bps"] == 10.0 and payload["pilot_fee_bps"] == PILOT_TIER_TAKER_BPS
    assert [item["meta"]["venue"] for item in payload["prints"]] == ["kraken", "coinbase"]
    assert payload["prints"][0]["meta"]["eras_covered"] == ["2024-2026"]
    assert payload["prints"][1]["meta"]["eras_covered"] == []
    assert payload["prints"][1]["meta"]["names_skipped"] == 2
    text = out_md.read_text()
    assert text.index("## Pre-registered header") < text.index("## Data sources reached")
    assert text.index("## Data sources reached") < text.index("## Dual-print passers")
    assert "| `kraken` | candles_dir:" in text and "**ok**" in text
    assert "Skipped on `coinbase`" in text


def test_cli_universe_unavailable_is_success(tmp_path: Path) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": ["EService:Unavailable"]})

    args = build_parser().parse_args(
        [
            "--live",
            "--sleep-seconds",
            "0",
            "--output-json",
            str(tmp_path / "out.json"),
            "--output-md",
            str(tmp_path / "out.md"),
        ]
    )
    transport = httpx.MockTransport(handler)
    out_json, out_md = run(
        args,
        settings(),
        client=httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport),
    )
    payload = json.loads(out_json.read_text())
    assert payload["any_dual_print_passer"] is False
    assert payload["prints"][0]["meta"]["status"] == "skipped"
    assert payload["prints"][0]["meta"]["names_loaded"] == 0
    text = out_md.read_text()
    assert "universe unavailable; nothing scored; empty is success" in text
    assert "kraken_asset_pairs: skipped" in text
    assert (tmp_path / UNIVERSE_LISTING_FILENAME).exists()


def _ohlc_rows(count: int, *, start: datetime, price: float) -> list[list[object]]:
    rows: list[list[object]] = []
    for index in range(count):
        ts = int((start + timedelta(days=index)).timestamp())
        p = price * (1.0 + 0.001 * index)
        rows.append([ts, str(p), str(p * 1.01), str(p * 0.99), str(p), str(p), "5.0", 3])
    return rows


def test_cli_live_pulls_pairs_with_mock_transport(tmp_path: Path) -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path + "?" + str(request.url.params))
        if request.url.path == "/0/public/AssetPairs":
            return httpx.Response(
                200,
                json={
                    "error": [],
                    "result": {
                        "XXBTZUSD": {
                            "altname": "XBTUSD",
                            "wsname": "XBT/USD",
                            "quote": "ZUSD",
                            "status": "online",
                        },
                        "XETHZUSD": {
                            "altname": "ETHUSD",
                            "wsname": "ETH/USD",
                            "quote": "ZUSD",
                            "status": "online",
                        },
                        "SOLUSD": {
                            "altname": "SOLUSD",
                            "wsname": "SOL/USD",
                            "quote": "USD",
                            "status": "online",
                        },
                        "USDTZUSD": {
                            "altname": "USDTUSD",
                            "wsname": "USDT/USD",
                            "quote": "ZUSD",
                            "status": "online",
                        },
                    },
                },
            )
        pair = request.url.params["pair"]
        if pair == "SOLUSD":
            return httpx.Response(200, json={"error": ["EQuery:Unknown asset pair"], "result": {}})
        rows = _ohlc_rows(80, start=START, price=100.0 if pair == "XBTUSD" else 10.0)
        last = int(rows[-1][0])  # type: ignore[call-overload]
        return httpx.Response(200, json={"error": [], "result": {pair: rows, "last": last}})

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    write_candles(cache_path(cache_dir, "ETH/USD"), make_candles([5.0] * 80, symbol="ETH/USD"))
    args = build_parser().parse_args(
        [
            "--live",
            "--sleep-seconds",
            "0",
            "--cache-dir",
            str(cache_dir),
            "--output-json",
            str(tmp_path / "out.json"),
            "--output-md",
            str(tmp_path / "out.md"),
        ]
    )
    transport = httpx.MockTransport(handler)
    out_json, _ = run(
        args,
        settings(),
        client=httpx.AsyncClient(base_url="https://api.kraken.com", transport=transport),
    )
    payload = json.loads(out_json.read_text())
    meta = payload["prints"][0]["meta"]
    assert meta["status"] == "ok"
    assert meta["names_loaded"] == 2 and meta["names_skipped"] == 1
    assert not any("ETHUSD" in call for call in calls)  # served from the cache
    assert cache_path(cache_dir, "BTC/USD").exists()  # fetched pair written back
    assert any("1 pairs reused from --cache-dir" in note for note in payload["data_notes"])
    assert any("SOL/USD: fetch skipped" in reason for reason in meta["skip_reasons"])
    assert payload["universe_listing_source"] == "kraken_asset_pairs"
    assert payload["universe_listing_size"] == 3
    assert payload["universe_listing_fetched_at"]
    listing = json.loads((tmp_path / UNIVERSE_LISTING_FILENAME).read_text())
    assert [item["canonical"] for item in listing["pairs"]] == ["BTC/USD", "ETH/USD", "SOL/USD"]
    assert calls[0].startswith("/0/public/AssetPairs")
    assert not any("USDTUSD" in call for call in calls)
    # Three names cannot form a cross-section: every week is flat, nothing invented.
    assert payload["any_dual_print_passer"] is False
    first = payload["prints"][0]["candidates"][0]
    assert first["flat_weeks"] == first["decisions"]
