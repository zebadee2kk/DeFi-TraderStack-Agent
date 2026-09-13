"""Unit tests for the #135 evidence layer (DSR / PBO / bootstrap / era policy)."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta

import pytest

from traderstack.candles import Candle
from traderstack.research.daily_candidates import default_expanded_harder_gates_candidates
from traderstack.research.daily_robustness import run_daily_robustness
from traderstack.research.evidence import (
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_RESAMPLES,
    CSCV_MAX_GROUPS,
    CSCV_MIN_GROUPS,
    DSR_MIN,
    ERA_MIN_BARS,
    ERA_WINDOWS,
    EVIDENCE_RULES,
    EVIDENCE_SEED,
    PBO_MAX,
    PRINT_KIND_ERA,
    PRINT_KIND_VENUE,
    CatalogEvidence,
    block_bootstrap_ci,
    bootstrap_expectancy_ci,
    bootstrap_sharpe_ci,
    cscv_pbo,
    deflated_sharpe,
    era_coverage,
    evaluate_catalog_evidence,
    expected_max_sharpe,
    moments,
    period_sharpe,
    power_table_rows,
    probabilistic_sharpe,
    render_era_coverage_lines,
    render_evidence_lines,
    sharpe_standard_error,
    trades_needed_to_exclude_zero,
    years_for_t_stat,
)


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


def uptrend(count: int, *, symbol: str, start: datetime | None = None) -> tuple[Candle, ...]:
    return make_candles([100.0 + 0.5 * index for index in range(count)], symbol=symbol, start=start)


def downtrend(count: int, *, symbol: str, start: datetime | None = None) -> tuple[Candle, ...]:
    return make_candles(
        [200.0 - 0.25 * index for index in range(count)], symbol=symbol, start=start
    )


# Alternating +1.2% / -0.8%: mean 0.2%, sd ~1.0%, per-bar Sharpe ~0.20,
# zero skew, kurtosis 1 (two-point distribution). Fully deterministic.
STRONG_RETURNS = [0.012, -0.008] * 72


def test_frozen_constants_and_era_windows() -> None:
    assert EVIDENCE_SEED == 20260913
    assert BOOTSTRAP_RESAMPLES == 2000
    assert BOOTSTRAP_CONFIDENCE == 0.95
    assert DSR_MIN == 0.95
    assert PBO_MAX == 0.50
    assert CSCV_MIN_GROUPS == 4
    assert CSCV_MAX_GROUPS == 16
    assert ERA_MIN_BARS == 720
    assert PRINT_KIND_VENUE == "venue"
    assert PRINT_KIND_ERA == "era"
    assert ERA_WINDOWS == (
        ("era_1_2016_2019", "2016-01-01", "2019-12-31"),
        ("era_2_2020_2022h1", "2020-01-01", "2022-06-30"),
        ("era_3_2022h2_2024h1", "2022-07-01", "2024-06-30"),
        ("era_4_2024h2_2026", "2024-07-01", "2026-12-31"),
    )
    for token in ("DSR >= 0.95", "PBO <= 0.50", "2000 resamples", "seed 20260913"):
        assert token in EVIDENCE_RULES
    assert "additional gates, never replacements" in EVIDENCE_RULES
    assert "empty evidence-passer set is success" in EVIDENCE_RULES


def test_power_table_reproduces_the_brief() -> None:
    rows = {row.sharpe: row for row in power_table_rows()}
    assert rows[1.0].se_2y == pytest.approx(0.87, abs=0.005)
    assert rows[1.0].years_for_t2 == pytest.approx(6.0, abs=1e-9)
    assert rows[0.5].se_2y == pytest.approx(0.75, abs=1e-9)
    assert rows[0.5].years_for_t2 == pytest.approx(18.0, abs=1e-9)
    assert rows[2.0].se_2y == pytest.approx(1.22, abs=0.005)
    assert sharpe_standard_error(1.0, 0.0) is None
    assert years_for_t_stat(0.0) is None
    assert years_for_t_stat(1.0, t=0.0) is None


def test_expected_max_sharpe_is_zero_below_two_trials_and_monotone() -> None:
    assert expected_max_sharpe(1, 0.5) == 0.0
    assert expected_max_sharpe(0, 0.5) == 0.0
    assert expected_max_sharpe(50, 0.0) == 0.0
    assert expected_max_sharpe(50, -1.0) == 0.0
    small = expected_max_sharpe(10, 0.04)
    large_n = expected_max_sharpe(200, 0.04)
    large_v = expected_max_sharpe(10, 0.16)
    assert 0 < small < large_n
    assert small < large_v
    assert expected_max_sharpe(200, 0.04) == pytest.approx(0.5531, abs=1e-3)


def test_probabilistic_sharpe_matches_hand_computation() -> None:
    # (0.1 * sqrt(99)) / sqrt(1 + (3-1)/4 * 0.01) = 0.99253 -> Phi = 0.8395
    assert probabilistic_sharpe(0.1, 0.0, 100, 0.0, 3.0) == pytest.approx(0.8395, abs=1e-3)
    assert probabilistic_sharpe(0.1, 0.0, 1, 0.0, 3.0) is None
    # Huge positive skew with a positive SR can make the radicand non-positive.
    assert probabilistic_sharpe(2.0, 0.0, 100, 5.0, 0.0) is None


def test_moments_and_period_sharpe() -> None:
    stats = moments(STRONG_RETURNS)
    assert stats is not None
    assert stats.n == 144
    assert stats.mean == pytest.approx(0.002)
    assert stats.skew == pytest.approx(0.0, abs=1e-12)
    assert stats.kurtosis == pytest.approx(1.0)
    assert period_sharpe(STRONG_RETURNS) == pytest.approx(0.2, abs=0.002)
    assert moments([0.01]) is None
    assert moments([0.01, 0.01, 0.01]) is not None
    assert period_sharpe([0.01, 0.01, 0.01]) is None
    assert period_sharpe([0.01]) is None


def test_can_pass_raw_sharpe_and_fail_dsr() -> None:
    """Acceptance criterion: positive raw Sharpe, DSR below 0.95 once N=200 trials are declared."""
    raw = period_sharpe(STRONG_RETURNS)
    assert raw is not None and raw > 0
    rng = random.Random(3)
    trial_sharpes = [rng.gauss(0.0, 0.2) for _ in range(200)]
    deflated = deflated_sharpe(STRONG_RETURNS, trial_sharpes)
    assert deflated.trial_count == 200
    assert deflated.trial_variance > 0
    assert deflated.sr0 > raw
    assert deflated.dsr is not None
    assert deflated.dsr < DSR_MIN
    assert deflated.reason is None


def test_single_trial_strong_signal_passes_dsr() -> None:
    deflated = deflated_sharpe(STRONG_RETURNS, [0.2])
    assert deflated.trial_count == 1
    assert deflated.sr0 == 0.0
    assert deflated.dsr is not None
    assert deflated.dsr >= DSR_MIN


def test_deflated_sharpe_fails_closed_with_reasons() -> None:
    short = deflated_sharpe([0.01], [0.1, 0.2])
    assert short.dsr is None
    assert short.reason == "holdout_returns_too_short"
    flat = deflated_sharpe([0.01, 0.01, 0.01], [0.1, 0.2])
    assert flat.dsr is None
    assert flat.reason == "period_sharpe_undefined"


def test_bootstrap_is_seeded_and_deterministic() -> None:
    first = bootstrap_sharpe_ci(STRONG_RETURNS, 365.0, resamples=300)
    second = bootstrap_sharpe_ci(STRONG_RETURNS, 365.0, resamples=300)
    other = bootstrap_sharpe_ci(STRONG_RETURNS, 365.0, resamples=300, seed=EVIDENCE_SEED + 1)
    assert first is not None and second is not None and other is not None
    assert first.model_dump() == second.model_dump()
    assert (first.low, first.high) != (other.low, other.high)
    assert first.low <= first.point <= first.high
    assert first.seed == EVIDENCE_SEED
    assert first.block_len == max(1, round(len(STRONG_RETURNS) ** (1.0 / 3.0)))
    assert first.resamples == 300


def test_bootstrap_degenerate_inputs_are_none() -> None:
    assert bootstrap_sharpe_ci([0.01], 365.0) is None
    assert bootstrap_sharpe_ci([0.01, 0.01, 0.01], 365.0, resamples=50) is None
    assert bootstrap_expectancy_ci([0.02]) is None
    assert block_bootstrap_ci([0.1, 0.2], lambda s: None, resamples=10) is None
    assert block_bootstrap_ci([0.1, 0.2], lambda s: sum(s), resamples=1) is None
    assert block_bootstrap_ci([0.1, 0.2], lambda s: sum(s), confidence=1.0) is None


def test_expectancy_ci_excludes_zero_for_strong_sample_and_trades_needed_is_monotone() -> None:
    strong = [0.02, 0.03, 0.01, 0.04, 0.05, 0.02, 0.03, 0.01]
    ci = bootstrap_expectancy_ci(strong)
    assert ci is not None
    assert ci.low > 0
    assert ci.low <= ci.point <= ci.high
    needed = trades_needed_to_exclude_zero(strong)
    assert needed is not None and needed >= 1
    noisier = [0.02, 0.03, -0.05, 0.04, 0.05, -0.04, 0.03, 0.01]
    noisier_needed = trades_needed_to_exclude_zero(noisier)
    assert noisier_needed is not None and noisier_needed > needed
    assert trades_needed_to_exclude_zero([-0.01, -0.02, 0.0]) is None
    assert trades_needed_to_exclude_zero([0.01]) is None
    assert trades_needed_to_exclude_zero([0.01, 0.01]) is None


def test_cscv_dominant_trial_has_zero_pbo() -> None:
    matrix = {"dominant": [2.0] * 8, **{f"t{index}": [0.0] * 8 for index in range(5)}}
    result = cscv_pbo(matrix)
    assert result.pbo == 0.0
    assert result.groups == 8
    assert result.combinations == 70
    assert result.trials == 6
    assert result.reason is None


def test_cscv_seeded_noise_is_stable_and_inside_unit_interval() -> None:
    rng = random.Random(1)
    matrix = {f"t{index}": [rng.gauss(0.0, 1.0) for _ in range(8)] for index in range(10)}
    first = cscv_pbo(matrix)
    second = cscv_pbo(dict(reversed(list(matrix.items()))))
    assert first.pbo is not None
    assert 0.0 < first.pbo < 1.0
    assert first.model_dump() == second.model_dump()


def test_cscv_edge_cases_fail_closed_with_reasons() -> None:
    too_few = cscv_pbo({"a": [1.0, 2.0, 3.0], "b": [0.0, 1.0, 2.0]})
    assert too_few.pbo is None
    assert too_few.reason == "fewer_than_4_groups"
    assert too_few.dropped_oldest_fold is True
    odd = cscv_pbo({"a": [1.0] * 9, "b": [0.0] * 9})
    assert odd.pbo == 0.0
    assert odd.groups == 8
    assert odd.dropped_oldest_fold is True
    assert odd.folds == 9
    big = cscv_pbo({"a": [1.0] * 20, "b": [0.0] * 20, "c": [0.5] * 20})
    assert big.groups == CSCV_MAX_GROUPS
    assert big.merged_folds is True
    assert big.combinations == 12870
    assert big.pbo == 0.0
    assert cscv_pbo({"a": [1.0] * 8}).reason == "fewer_than_2_trials"
    assert cscv_pbo({"a": [1.0] * 8, "b": [1.0] * 6}).reason == "fold_count_mismatch_across_trials"


def test_era_coverage_marks_only_covered_eras_scoreable() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    rows = era_coverage(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=start),
        },
        venue="kraken",
    )
    assert [row.era for row in rows] == [era for era, _s, _e in ERA_WINDOWS]
    assert all(row.venue == "kraken" for row in rows)
    by_era = {row.era: row for row in rows}
    assert by_era["era_4_2024h2_2026"].bars == 720
    assert by_era["era_4_2024h2_2026"].scoreable is True
    assert by_era["era_4_2024h2_2026"].first == start.isoformat()
    for era in ("era_1_2016_2019", "era_2_2020_2022h1", "era_3_2022h2_2024h1"):
        assert by_era[era].bars == 0
        assert by_era[era].scoreable is False
        assert by_era[era].reason == f"fewer_than_{ERA_MIN_BARS}_bars_in_era"
    short = era_coverage({"BTC/USD@1d": downtrend(719, symbol="BTC/USD", start=start)}, venue="k")
    assert short[-1].bars == 719
    assert short[-1].scoreable is False
    empty = era_coverage({}, venue="none")
    assert len(empty) == len(ERA_WINDOWS)
    assert all(row.reason == "no_series" and not row.scoreable for row in empty)
    rendered = render_era_coverage_lines(rows)
    assert any("era_4_2024h2_2026" in line and "| yes |" in line for line in rendered)
    assert render_era_coverage_lines([])[-1].startswith("| — |")


def _catalog() -> tuple:
    return tuple(
        item
        for item in default_expanded_harder_gates_candidates()
        if item.candidate_id in {"ema_9_21", "ema_9_21_adx15"}
    )


def _robustness_report():
    start = datetime(2024, 9, 22, tzinfo=UTC)
    return run_daily_robustness(
        {
            "BTC/USD@1d": uptrend(480, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(480, symbol="ETH/USD", start=start),
        },
        fee_bps=10.0,
        slippage_bps=5.0,
        train_size=80,
        test_size=40,
        step_size=40,
        holdout_fraction=0.2,
        min_trades=1,
        candidates=_catalog(),
        now=datetime(2026, 9, 13, tzinfo=UTC),
    )


def test_evaluate_catalog_evidence_on_real_robustness_output_round_trips() -> None:
    report = _robustness_report()
    first = evaluate_catalog_evidence(report, resamples=200)
    second = evaluate_catalog_evidence(report, resamples=200)
    assert first.model_dump_json() == second.model_dump_json()
    assert first.trial_count == len(_catalog())
    assert first.print_kind == PRINT_KIND_VENUE
    assert first.seed == EVIDENCE_SEED
    assert first.dsr_min == DSR_MIN and first.pbo_max == PBO_MAX
    assert set(first.pbo_by_asset) == {"BTC/USD", "ETH/USD", "SOL/USD"}
    assert first.excluded_trials_by_asset["SOL/USD"] == [item.candidate_id for item in _catalog()]
    assert first.pbo_by_asset["SOL/USD"].reason == "no_walkforward_folds"
    for candidate in first.candidates:
        assets = [entry.asset for entry in candidate.series]
        assert assets == ["BTC/USD", "ETH/USD"]
        for entry in candidate.series:
            assert entry.bars > 0
            # holdout returns were captured before the trade log was stripped
            assert entry.period_sharpe is not None or entry.reasons
        if not candidate.evidence_pass:
            assert candidate.reasons
    payload = json.loads(first.model_dump_json())
    restored = CatalogEvidence.model_validate(payload)
    assert restored.model_dump_json() == first.model_dump_json()
    # holdout evidence inputs are on the series rows, not on the stripped folds
    for row in report.candidates:
        for series in row.per_series:
            assert series.holdout is not None
            assert series.holdout.period_returns == []
            assert len(series.holdout_period_returns) == series.holdout_bars - 1
            assert series.walkforward is not None
            assert all(fold.metrics.period_returns == [] for fold in series.walkforward.folds)


def test_render_evidence_lines_reports_none_as_skip() -> None:
    lines = render_evidence_lines(None, heading="## Evidence")
    assert lines[0] == "## Evidence"
    assert any("skip, never a zero" in line for line in lines)
    evidence = evaluate_catalog_evidence(_robustness_report(), resamples=100)
    rendered = "\n".join(render_evidence_lines(evidence))
    assert "trial count N=2" in rendered
    assert "DSR_MIN=0.95" in rendered
    assert "SOL/USD (reported, not gated)" in rendered
    assert "no_walkforward_folds" in rendered
    assert "`ema_9_21`" in rendered
