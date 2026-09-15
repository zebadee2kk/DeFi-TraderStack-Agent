"""Selection evidence wired into the shared search report path (#135).

These tests exercise the composition layer and the one shared scoring
path (`run_harder_gates`) that every dual-print search family funnels
through, so a passing run here is evidence for all of them at once.
"""

from __future__ import annotations

import random
import statistics
from datetime import UTC, datetime, timedelta

import pytest

from traderstack.backtest import BacktestMetrics
from traderstack.candles import Candle
from traderstack.research.era_prints import PrintKind
from traderstack.research.miles_search import (
    CandidateSearchResult,
    SeriesCandidateMetrics,
)
from traderstack.research.selection_evidence import (
    DSR_MIN,
    PBO_MAX,
    build_selection_evidence,
    render_evidence_lines,
)
from traderstack.walkforward import WalkForwardFold, WalkForwardReport

START = datetime(2024, 1, 1, tzinfo=UTC)


def daily(count: int, *, start: datetime = START, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    candles: list[Candle] = []
    for index in range(count):
        price = 100.0 + index * 0.1
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=start + timedelta(days=index),
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1_000.0,
            )
        )
    return tuple(candles)


def metrics(
    total_return: float, *, trades: int = 6, expectancy: float | None = None
) -> BacktestMetrics:
    return BacktestMetrics(
        starting_equity=10_000.0,
        ending_equity=10_000.0 * (1.0 + total_return),
        total_return=total_return,
        benchmark_return=0.0,
        excess_return=total_return,
        max_drawdown=0.05,
        sharpe=total_return * 4,
        trades=trades,
        expectancy=total_return / trades if expectancy is None else expectancy,
    )


def series(
    returns: list[float], *, asset: str = "BTC/USD", trades: int = 6
) -> SeriesCandidateMetrics:
    folds = [
        WalkForwardFold(
            train_start=index * 60,
            train_end=index * 60 + 180,
            test_start=index * 60 + 180,
            test_end=index * 60 + 240,
            metrics=metrics(value, trades=trades),
        )
        for index, value in enumerate(returns)
    ]
    return SeriesCandidateMetrics(
        asset=asset,
        interval="1d",
        candle_count=720,
        research_bars=576,
        holdout_bars=144,
        walkforward=WalkForwardReport(
            folds=folds,
            mean_total_return=sum(returns) / len(returns) if returns else 0.0,
            mean_excess_return=0.0,
            mean_sharpe=0.0,
            worst_drawdown=0.1,
        ),
        walkforward_trades=trades * len(folds),
    )


def candidate(
    candidate_id: str, returns: list[float], *, assets: tuple[str, ...] = ("BTC/USD", "ETH/USD")
) -> CandidateSearchResult:
    return CandidateSearchResult(
        candidate_id=candidate_id,
        family="momentum",
        label=candidate_id,
        params={},
        signal_version="v1",
        per_series=[series(returns, asset=asset) for asset in assets],
    )


def noisy_catalog(size: int, *, seed: int, folds: int = 8) -> list[CandidateSearchResult]:
    rng = random.Random(seed)
    return [
        candidate(f"trial_{index:02d}", [rng.gauss(0.0, 0.03) for _ in range(folds)])
        for index in range(size)
    ]


# Bootstrap precision is a knob, not a property under test. Every assertion in
# this module is on a field's presence, a gate verdict, a print kind, DSR or
# PBO — DSR and PBO use no bootstrap at all, and the interval assertions below
# are on samples whose sign is unambiguous at any resample count. Production
# defaults (2000 / 400) stay exercised by
# test_evidence_carries_every_field_the_acceptance_criteria_name, which passes
# no overrides, so the default path is never left untested.
#
# This matters for CI wall-clock rather than runtime: coverage line-tracing
# through the resample loop costs >6x the untraced time, so a 2000-iteration
# bootstrap over a 20-candidate catalog dominates the suite under --cov.
FAST = {"iterations": 200, "floor_iterations": 100}


def test_evidence_carries_every_field_the_acceptance_criteria_name() -> None:
    evidence = build_selection_evidence(
        noisy_catalog(12, seed=1),
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        venue_print_available=True,
        configured_min_trades=3,
    )
    assert evidence.print_kind is PrintKind.VENUE
    assert evidence.print_kind_detail
    assert evidence.trial_count == 12
    assert evidence.era_coverage is not None
    assert evidence.era_coverage.covered_era_ids == ["2024-2026"]
    assert evidence.power, "the power table must be reported"
    first = evidence.candidates[0]
    assert first.deflated.trials == 12
    assert first.sharpe_ci.statistic == "sharpe"
    assert first.expectancy_ci.statistic == "mean"
    assert first.trade_floor.observation_unit == "walk_forward_fold"
    assert evidence.pbo.computed


def test_an_empty_evidence_passer_set_is_a_normal_outcome() -> None:
    evidence = build_selection_evidence(
        noisy_catalog(20, seed=2),
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        venue_print_available=False,
        configured_min_trades=3,
        **FAST,
    )
    assert evidence.evidence_passer_ids == []
    assert not evidence.any_evidence_passer
    # And the reason is recorded, not implied.
    assert all(row.evidence_gate_reasons for row in evidence.candidates)


def test_single_print_alone_withholds_every_candidate() -> None:
    evidence = build_selection_evidence(
        noisy_catalog(10, seed=3),
        primary_candles=daily(300),
        primary_venue="kraken_spot",
        venue_print_available=False,
        **FAST,
    )
    assert evidence.print_kind is PrintKind.SINGLE
    assert not evidence.any_evidence_passer
    assert all(
        "single_print_no_independent_confirmation" in row.evidence_gate_reasons
        for row in evidence.candidates
    )


# A fixed zero-mean, unit-spread pattern. Scaling it and adding a
# constant gives a fold-return series with an exactly known Sharpe, so a
# catalog's trial-Sharpe dispersion can be dialled in rather than drawn.
UNIT_PATTERN = (1.0, -1.0, 0.5, -0.5, 1.5, -1.5, 0.25, -0.25)


def with_sharpe(target: float, *, scale: float = 0.02) -> list[float]:
    spread = statistics.stdev(UNIT_PATTERN)
    return [target * scale + value * scale / spread for value in UNIT_PATTERN]


def test_a_candidate_can_pass_raw_sharpe_and_fail_the_dsr_gate() -> None:
    """#135 acceptance: pass raw Sharpe, fail DSR.

    One genuinely good-looking trial (per-fold Sharpe about 1.1, so a raw
    PSR far above 0.95) is dropped into a 60-member catalog of noise
    trials whose Sharpes are widely dispersed. That dispersion is exactly
    what the DSR deflates against: the expected maximum Sharpe a
    60-trial search produces from noise alone overtakes the winner's
    margin, the DSR falls below ``DSR_MIN``, and the evidence gate
    withholds it.
    """
    rng = random.Random(135)
    winner = candidate("winner", [0.02 + rng.gauss(0.0, 0.02) for _ in range(8)])
    noise = [
        candidate(
            f"noise_{index:02d}",
            [rng.gauss(0.0, 0.02 + 0.01 * (index % 5)) for _ in range(8)],
        )
        for index in range(59)
    ]

    evidence = build_selection_evidence(
        [winner, *noise],
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        venue_print_available=True,
        configured_min_trades=3,
        **FAST,
    )
    row = evidence.for_candidate("winner")
    assert row is not None

    # Raw Sharpe evidence is strong: the undeflated PSR clears 0.95 and
    # the bootstrap Sharpe CI excludes zero.
    assert row.trial_sharpe is not None and row.trial_sharpe > 0.8
    assert row.sharpe_ci.computed and row.sharpe_ci_pass
    assert row.deflated.probabilistic_sharpe is not None
    assert row.deflated.probabilistic_sharpe > 0.95

    # DSR, against the same catalog, is not.
    assert row.deflated.computed
    assert row.deflated.expected_max_sharpe is not None
    assert row.deflated.expected_max_sharpe > 0.0
    assert row.deflated.deflated_sharpe is not None
    assert row.deflated.deflated_sharpe < DSR_MIN
    assert row.deflated.deflated_sharpe < row.deflated.probabilistic_sharpe
    assert not row.dsr_pass
    assert "deflated_sharpe_below_minimum" in row.evidence_gate_reasons
    assert not row.evidence_gate_pass
    assert "winner" not in evidence.evidence_passer_ids


def test_the_same_sharpe_survives_deflation_when_the_search_was_narrow() -> None:
    """The mirror image: little trial dispersion, little to deflate.

    Same observed Sharpe, but a three-member catalog whose trial Sharpes
    sit close together. ``E[max SR]`` is then small and the DSR stays
    above the bar — which is what makes the failure above a statement
    about the *search*, not about the strategy.
    """
    catalog = [
        candidate("winner", with_sharpe(1.10)),
        candidate("near_a", with_sharpe(1.05)),
        candidate("near_b", with_sharpe(1.00)),
    ]
    evidence = build_selection_evidence(
        catalog,
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        venue_print_available=True,
        **FAST,
    )
    row = evidence.for_candidate("winner")
    assert row is not None and row.deflated.computed
    assert row.deflated.expected_max_sharpe is not None
    assert row.deflated.expected_max_sharpe < 0.1
    assert row.deflated.deflated_sharpe is not None
    assert row.deflated.deflated_sharpe >= DSR_MIN
    assert row.dsr_pass


def test_evidence_is_reproducible_under_a_fixed_seed() -> None:
    catalog = noisy_catalog(8, seed=4)
    kwargs = {
        "primary_candles": daily(720),
        "primary_venue": "kraken_spot",
        "venue_print_available": True,
    }
    first = build_selection_evidence(catalog, **kwargs)  # type: ignore[arg-type]
    second = build_selection_evidence(catalog, **kwargs)  # type: ignore[arg-type]
    assert first.model_dump_json() == second.model_dump_json()


def test_evidence_does_not_touch_the_global_rng() -> None:
    catalog = noisy_catalog(6, seed=5)
    random.seed(99)
    build_selection_evidence(catalog, primary_candles=daily(720), primary_venue="kraken_spot")
    after = random.random()
    random.seed(99)
    assert random.random() == after


def test_a_different_seed_moves_the_bootstrap_but_not_the_point_estimates() -> None:
    catalog = noisy_catalog(6, seed=6)
    a = build_selection_evidence(
        catalog,
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        seed=1,
        **FAST,
    )
    b = build_selection_evidence(
        catalog,
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        seed=2,
        **FAST,
    )
    assert [row.trial_sharpe for row in a.candidates] == [row.trial_sharpe for row in b.candidates]
    assert a.pbo.pbo == b.pbo.pbo, "CSCV is exhaustive and has no seed"
    assert [row.sharpe_ci.low for row in a.candidates] != [
        row.sharpe_ci.low for row in b.candidates
    ]


def test_a_missing_series_is_skipped_rather_than_zero_filled() -> None:
    present = candidate("has_eth", [0.01, 0.02, -0.01, 0.03, 0.0, 0.01, 0.02, -0.02])
    absent = candidate(
        "btc_only", [0.01, 0.02, -0.01, 0.03, 0.0, 0.01, 0.02, -0.02], assets=("BTC/USD",)
    )
    evidence = build_selection_evidence(
        [present, absent],
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        **FAST,
    )
    with_eth = evidence.for_candidate("has_eth")
    without = evidence.for_candidate("btc_only")
    assert with_eth is not None and without is not None
    # Exactly the BTC folds, with nothing invented for the missing ETH leg.
    assert with_eth.observations == 16
    assert without.observations == 8


def test_a_trial_with_no_walkforward_is_a_skip_with_a_reason() -> None:
    empty = CandidateSearchResult(
        candidate_id="no_data",
        family="momentum",
        label="no_data",
        params={},
        signal_version="v1",
        per_series=[],
    )
    evidence = build_selection_evidence(
        [empty, *noisy_catalog(4, seed=7)],
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        **FAST,
    )
    row = evidence.for_candidate("no_data")
    assert row is not None
    assert row.observations == 0
    assert row.trial_sharpe is None
    assert not row.evidence_gate_pass
    assert any(reason.startswith("dsr_skipped:") for reason in row.evidence_gate_reasons)


def test_pbo_is_reported_so_zero_passers_and_a_weak_passer_differ() -> None:
    evidence = build_selection_evidence(
        noisy_catalog(16, seed=8, folds=10),
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        venue_print_available=True,
        **FAST,
    )
    assert evidence.pbo.computed
    assert evidence.pbo.pbo is not None
    assert 0.0 <= evidence.pbo.pbo <= 1.0
    assert evidence.pbo_max == PBO_MAX
    assert evidence.pbo_pass == (evidence.pbo.pbo <= PBO_MAX)


def test_render_evidence_lines_names_print_kind_trials_pbo_and_eras() -> None:
    evidence = build_selection_evidence(
        noisy_catalog(8, seed=9),
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        venue_print_available=True,
        **FAST,
    )
    text = "\n".join(render_evidence_lines(evidence, highlight_candidate_ids=["trial_00"]))
    assert "Print kind" in text
    assert "Trials scored (K):** 8" in text
    assert "PBO (CSCV)" in text
    assert "Era coverage" in text
    assert "2024-2026" in text
    assert "Sharpe power at this window length" in text
    assert "`trial_00`" in text


def test_render_evidence_lines_says_absent_evidence_is_not_a_pass() -> None:
    text = "\n".join(render_evidence_lines(None))
    assert "Absent evidence is not a pass" in text


@pytest.mark.parametrize("min_trades", [0, 3, 25])
def test_the_bootstrap_floor_never_lowers_the_configured_minimum(min_trades: int) -> None:
    evidence = build_selection_evidence(
        noisy_catalog(6, seed=10),
        primary_candles=daily(720),
        primary_venue="kraken_spot",
        configured_min_trades=min_trades,
        **FAST,
    )
    for row in evidence.candidates:
        assert row.trade_floor.configured_min_trades == min_trades
        assert row.trade_floor.effective_min_trades >= min_trades


# --- the shared scoring path itself ---------------------------------------


def trending(
    count: int, *, symbol: str, drift: float, start: datetime = START
) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        previous = price
        price = price * (1.0 + drift)
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=start + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000.0 + index,
            )
        )
    return tuple(candles)


def harder_gates_report(**overrides: object):
    from traderstack.research.daily_candidates import default_balanced_holdout_candidates
    from traderstack.research.harder_gates import run_harder_gates

    histories = {
        "BTC/USD@1d": trending(720, symbol="BTC/USD", drift=0.001),
        "ETH/USD@1d": trending(720, symbol="ETH/USD", drift=0.0012),
    }
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "candidates": default_balanced_holdout_candidates()[:4],
    }
    kwargs.update(overrides)
    return run_harder_gates(histories, **kwargs)  # type: ignore[arg-type]


def test_the_shared_scoring_path_attaches_evidence_to_every_row() -> None:
    report = harder_gates_report()
    assert report.selection_evidence is not None
    assert report.selection_evidence.trial_count == len(report.candidates)
    for row in report.candidates:
        assert row.print_kind == report.selection_evidence.print_kind.value
        assert row.trial_count == report.selection_evidence.trial_count
        assert isinstance(row.evidence_gate_pass, bool)
        if not row.evidence_gate_pass:
            assert row.evidence_gate_reasons


def test_a_single_venue_run_reports_a_single_print_and_promotes_nothing() -> None:
    report = harder_gates_report()
    assert report.selection_evidence is not None
    # No second venue was declared, and 720 bars from 2024 cover one era.
    assert report.selection_evidence.print_kind is PrintKind.SINGLE
    assert report.evidence_passer_ids == []
    assert report.promoted_candidate_ids == []
    assert report.any_promoted is False
    assert "Print kind: single" in report.honesty


def test_the_evidence_gate_withholds_a_combined_passer_rather_than_promoting_it() -> None:
    """The additional gate takes promotion away and gives it to nobody."""
    from traderstack.research.harder_gates import (
        CandidateHarderResult,
        apply_combined_promotion,
        withhold_promotion_without_evidence,
    )

    rows = [
        CandidateHarderResult(
            candidate_id="top",
            family="momentum",
            label="top",
            combined=True,
            mean_holdout_excess=0.09,
            evidence_gate_pass=False,
            evidence_gate_reasons=["deflated_sharpe_below_minimum"],
        ),
        CandidateHarderResult(
            candidate_id="runner_up",
            family="momentum",
            label="runner_up",
            combined=True,
            mean_holdout_excess=0.04,
            evidence_gate_pass=True,
        ),
    ]
    selected = apply_combined_promotion(rows)
    assert selected is not None and selected.candidate_id == "top"
    assert selected.promoted is True

    withheld = withhold_promotion_without_evidence(selected)
    assert withheld == "top"
    assert rows[0].promoted is False
    assert rows[0].promotion_withheld_by_evidence is True
    # Nothing is promoted in its place, least of all the runner-up whose
    # evidence did pass: the gate only ever withholds.
    assert all(row.promoted is False for row in rows)
    assert rows[1].promotion_withheld_by_evidence is False


def test_withholding_is_a_no_op_when_the_evidence_gate_passed() -> None:
    from traderstack.research.harder_gates import (
        CandidateHarderResult,
        withhold_promotion_without_evidence,
    )

    row = CandidateHarderResult(
        candidate_id="clean",
        family="momentum",
        label="clean",
        combined=True,
        promoted=True,
        evidence_gate_pass=True,
    )
    assert withhold_promotion_without_evidence(row) is None
    assert row.promoted is True
    assert withhold_promotion_without_evidence(None) is None


def test_the_evidence_block_survives_a_json_round_trip() -> None:
    from traderstack.research.harder_gates import HarderGatesReport

    report = harder_gates_report()
    restored = HarderGatesReport.model_validate_json(report.model_dump_json())
    assert restored.selection_evidence is not None
    assert report.selection_evidence is not None
    assert restored.selection_evidence.model_dump() == report.selection_evidence.model_dump()
