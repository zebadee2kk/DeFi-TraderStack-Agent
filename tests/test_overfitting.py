"""Vendored selection-bias statistics (#135).

Every formula here is checked against a value a reviewer can look up
independently: standard normal quantiles, the moments of a known sample,
the normal special case of the PSR, and the calibration of CSCV PBO on a
pure-noise catalog. The bootstrap is checked for reproducibility under a
fixed seed and for never touching the global RNG.
"""

from __future__ import annotations

import random
import statistics

import pytest

from traderstack.research.overfitting import (
    DEFAULT_BOOTSTRAP_SEED,
    EULER_MASCHERONI,
    analytic_observation_floor,
    annualise,
    annualised_sharpe_standard_error,
    bootstrap_interval,
    bootstrap_trade_floor,
    cscv_pbo,
    deannualise,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    kurtosis,
    normal_cdf,
    normal_ppf,
    power_table,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
    sharpe_standard_error,
    skewness,
    stdev,
    years_for_sharpe_tstat,
)

# Published standard-normal quantiles (any statistics table).
KNOWN_QUANTILES = {
    0.5: 0.0,
    0.75: 0.6744897501960817,
    0.9: 1.2815515655446004,
    0.95: 1.6448536269514722,
    0.975: 1.959963984540054,
    0.99: 2.3263478740408408,
    0.995: 2.5758293035489004,
    0.999: 3.090232306167813,
    0.025: -1.959963984540054,
    0.001: -3.090232306167813,
}


@pytest.mark.parametrize(("probability", "expected"), sorted(KNOWN_QUANTILES.items()))
def test_normal_ppf_matches_published_quantiles(probability: float, expected: float) -> None:
    assert normal_ppf(probability) == pytest.approx(expected, abs=1e-12)


def test_normal_ppf_inverts_the_cdf_across_the_open_interval() -> None:
    worst = max(abs(normal_cdf(normal_ppf(step / 2000)) - step / 2000) for step in range(1, 2000))
    assert worst < 1e-12


def test_normal_ppf_rejects_probabilities_outside_the_open_interval() -> None:
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            normal_ppf(bad)


def test_normal_cdf_matches_known_values() -> None:
    assert normal_cdf(0.0) == pytest.approx(0.5)
    assert normal_cdf(1.959963984540054) == pytest.approx(0.975, abs=1e-12)
    assert normal_cdf(-1.0) == pytest.approx(0.15865525393145707, abs=1e-12)


def test_moments_match_hand_computed_values() -> None:
    sample = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    # Symmetric sample: zero skew. Uniform 1..8 has raw kurtosis 1.7619...
    assert skewness(sample) == pytest.approx(0.0, abs=1e-12)
    assert kurtosis(sample) == pytest.approx(1.7619047619047619, abs=1e-12)
    assert stdev(sample) == pytest.approx(statistics.stdev(sample))
    assert stdev(sample, population=True) == pytest.approx(statistics.pstdev(sample))


def test_moments_are_skips_not_zeros_on_short_or_flat_samples() -> None:
    assert skewness([1.0, 2.0]) is None
    assert kurtosis([1.0, 2.0]) is None
    assert stdev([3.0, 3.0, 3.0, 3.0]) is None
    assert sharpe_ratio([3.0]) is None


def test_sharpe_annualisation_round_trips() -> None:
    assert deannualise(annualise(0.1, 252), 252) == pytest.approx(0.1)


def test_psr_normal_case_equals_the_normal_cdf_of_the_tstat() -> None:
    # With g3 = 0 and g4 = 3 the PSR denominator is sqrt(1 + SR^2/2), so
    # PSR reduces to Phi(SR * sqrt(n - 1) / sqrt(1 + SR^2/2)).
    observed, observations = 0.2, 100
    expected = normal_cdf(observed * (observations - 1) ** 0.5 / (1 + 0.5 * observed**2) ** 0.5)
    assert probabilistic_sharpe_ratio(
        observed_sharpe=observed,
        benchmark_sharpe=0.0,
        observations=observations,
        skew=0.0,
        raw_kurtosis=3.0,
    ) == pytest.approx(expected, abs=1e-12)


def test_expected_max_sharpe_matches_the_published_closed_form() -> None:
    variance, trials = 0.25, 50
    expected = variance**0.5 * (
        (1 - EULER_MASCHERONI) * normal_ppf(1 - 1 / trials)
        + EULER_MASCHERONI * normal_ppf(1 - 1 / (trials * 2.718281828459045))
    )
    got = expected_max_sharpe(trial_sharpe_variance=variance, trials=trials)
    assert got is not None
    assert got == pytest.approx(expected, rel=1e-9)


def test_expected_max_sharpe_grows_with_the_number_of_trials() -> None:
    few = expected_max_sharpe(trial_sharpe_variance=0.1, trials=5)
    many = expected_max_sharpe(trial_sharpe_variance=0.1, trials=500)
    assert few is not None and many is not None
    assert many > few > 0


def test_expected_max_sharpe_skips_on_one_trial_or_no_dispersion() -> None:
    assert expected_max_sharpe(trial_sharpe_variance=0.1, trials=1) is None
    assert expected_max_sharpe(trial_sharpe_variance=0.0, trials=10) is None


def test_sharpe_standard_error_matches_the_power_formula() -> None:
    # Issue #135: SE ~= sqrt((1 + SR^2/2)/T). At T = 2, SR = 1 that is 0.87.
    assert annualised_sharpe_standard_error(1.0, 2.0) == pytest.approx(0.8660254, abs=1e-6)
    assert sharpe_standard_error(1.0, 2) == pytest.approx(0.8660254, abs=1e-6)
    # A t-stat of 2 at SR = 1 needs about six years.
    assert years_for_sharpe_tstat(1.0, 2.0) == pytest.approx(6.0, abs=1e-9)


def test_power_table_says_two_years_cannot_resolve_a_unit_sharpe() -> None:
    rows = power_table(years=2.0)
    unit = next(row for row in rows if row.annual_sharpe == 1.0)
    assert unit.tstat < 2.0
    assert unit.years_for_tstat_2 == pytest.approx(6.0)
    assert all(row.years_for_tstat_2 > row.years for row in rows if row.annual_sharpe <= 1.5)


def test_deflated_sharpe_is_below_the_probabilistic_sharpe_for_a_searched_winner() -> None:
    rng = random.Random(7)
    trial_sharpes = [rng.gauss(0.0, 0.1) for _ in range(100)]
    returns = [rng.gauss(0.01, 0.05) for _ in range(60)]
    result = deflated_sharpe_ratio(returns=returns, trial_sharpes=trial_sharpes)
    assert result.computed
    assert result.probabilistic_sharpe is not None and result.deflated_sharpe is not None
    # Deflation can only subtract confidence, never add it.
    assert result.deflated_sharpe < result.probabilistic_sharpe
    assert result.expected_max_sharpe is not None and result.expected_max_sharpe > 0


def test_a_strategy_can_pass_raw_sharpe_and_fail_dsr() -> None:
    """The #135 acceptance case, at the level of the statistic itself.

    Same return sample, two catalogs. Against a one-trial catalog the
    Sharpe stands up (PSR well above 0.95). Against a 500-trial catalog
    with dispersed trial Sharpes, the expected maximum from noise alone
    overtakes it and the DSR collapses below the 0.95 bar.
    """
    rng = random.Random(135)
    returns = [rng.gauss(0.012, 0.05) for _ in range(120)]

    raw = sharpe_ratio(returns)
    assert raw is not None and raw > 0
    unsearched = probabilistic_sharpe_ratio(
        observed_sharpe=raw, benchmark_sharpe=0.0, observations=len(returns)
    )
    assert unsearched is not None
    assert unsearched > 0.95, "raw Sharpe must clear the ordinary significance bar"

    searched = deflated_sharpe_ratio(
        returns=returns,
        trial_sharpes=[rng.gauss(0.0, 0.25) for _ in range(500)],
    )
    assert searched.computed
    assert searched.deflated_sharpe is not None
    assert searched.deflated_sharpe < 0.95, "DSR must fail once the search is accounted for"


def test_deflated_sharpe_skips_with_a_reason_rather_than_returning_zero() -> None:
    for returns, trials, reason in (
        ([0.1], [0.1, 0.2], "fewer_than_two_return_observations"),
        ([0.1, 0.1, 0.1], [0.1, 0.2], "return_sample_has_no_dispersion"),
        ([0.1, 0.2, 0.3], [0.1], "fewer_than_two_trials"),
        ([0.1, 0.2, 0.3], [0.1, 0.1, 0.1], "trial_sharpes_have_no_dispersion"),
    ):
        result = deflated_sharpe_ratio(returns=returns, trial_sharpes=trials)
        assert not result.computed
        assert result.deflated_sharpe is None
        assert result.skipped_reason == reason


def test_bootstrap_interval_is_reproducible_and_never_uses_the_global_rng() -> None:
    rng = random.Random(3)
    sample = [rng.gauss(0.01, 0.02) for _ in range(40)]

    random.seed(1)
    first = bootstrap_interval(sample, statistic="mean")
    global_state_after = random.random()

    random.seed(1)
    second = bootstrap_interval(sample, statistic="mean")
    assert random.random() == global_state_after, "global RNG must be untouched"

    assert (first.low, first.high, first.point) == (second.low, second.high, second.point)
    assert first.computed and first.seed == DEFAULT_BOOTSTRAP_SEED


def test_bootstrap_interval_seed_changes_the_answer_but_not_the_point_estimate() -> None:
    rng = random.Random(4)
    sample = [rng.gauss(0.01, 0.05) for _ in range(50)]
    a = bootstrap_interval(sample, statistic="sharpe", seed=1)
    b = bootstrap_interval(sample, statistic="sharpe", seed=2)
    assert a.point == b.point
    assert (a.low, a.high) != (b.low, b.high)


def test_bootstrap_interval_brackets_a_clearly_positive_mean() -> None:
    sample = [0.02] * 10 + [0.03] * 10 + [0.01] * 10
    interval = bootstrap_interval(sample, statistic="mean")
    assert interval.computed and interval.excludes_zero
    assert interval.low is not None and interval.low > 0
    assert interval.point is not None
    assert interval.low <= interval.point <= (interval.high or 0.0)


def test_bootstrap_interval_skips_rather_than_reporting_a_zero_width_interval() -> None:
    assert bootstrap_interval([0.1]).skipped_reason == "fewer_than_two_observations"
    assert bootstrap_interval([0.1, 0.1, 0.1]).skipped_reason == "sample_has_no_dispersion"


def test_bootstrap_interval_rejects_an_unknown_statistic() -> None:
    with pytest.raises(ValueError):
        bootstrap_interval([0.1, 0.2], statistic="sortino")


def test_bootstrap_trade_floor_agrees_with_the_analytic_cross_check() -> None:
    rng = random.Random(21)
    sample = [rng.gauss(0.004, 0.02) for _ in range(60)]
    floor = bootstrap_trade_floor(sample, observed_trades=60, configured_min_trades=3)
    analytic = analytic_observation_floor(sample, confidence=0.95)
    assert floor.computed and floor.required_observations is not None and analytic is not None
    assert abs(floor.required_observations - analytic) <= max(2, analytic // 4)


def test_bootstrap_trade_floor_only_ever_raises_the_configured_minimum() -> None:
    rng = random.Random(22)
    noisy = [rng.gauss(0.0005, 0.05) for _ in range(40)]
    floor = bootstrap_trade_floor(noisy, observed_trades=40, configured_min_trades=3)
    assert floor.computed
    assert floor.effective_min_trades >= floor.configured_min_trades == 3
    assert floor.required_trades is not None and floor.required_trades > 3
    assert not floor.meets_floor, "40 noisy trades must not clear a much larger floor"


def test_bootstrap_trade_floor_scales_by_trades_per_observation() -> None:
    rng = random.Random(23)
    sample = [rng.gauss(0.004, 0.02) for _ in range(60)]
    # The assertion is a *scaling* relationship between two calls made with
    # identical settings, so it holds at any resample count; 100 keeps the
    # coverage-traced inner loop cheap without weakening what is proved.
    one = bootstrap_trade_floor(
        sample, observed_trades=60, trades_per_observation=1.0, iterations=100
    )
    five = bootstrap_trade_floor(
        sample,
        observed_trades=300,
        observation_unit="walk_forward_fold",
        trades_per_observation=5.0,
        iterations=100,
    )
    assert one.required_observations == five.required_observations
    assert one.required_trades is not None and five.required_trades is not None
    assert five.required_trades == 5 * one.required_trades


def test_bootstrap_trade_floor_is_reproducible() -> None:
    rng = random.Random(24)
    sample = [rng.gauss(0.003, 0.02) for _ in range(50)]
    first = bootstrap_trade_floor(sample, observed_trades=50)
    second = bootstrap_trade_floor(sample, observed_trades=50)
    assert first.required_observations == second.required_observations


def test_bootstrap_trade_floor_skips_on_a_degenerate_sample() -> None:
    floor = bootstrap_trade_floor([0.1], observed_trades=1, configured_min_trades=3)
    assert not floor.computed
    assert floor.skipped_reason == "fewer_than_two_observations"
    assert floor.required_trades is None
    # The configured floor survives the skip; nothing is lowered.
    assert floor.effective_min_trades == 3


def _noise_matrix(seed: int, rows: int = 24, trials: int = 20) -> list[list[float]]:
    rng = random.Random(seed)
    return [[rng.gauss(0.0, 1.0) for _ in range(trials)] for _ in range(rows)]


def test_cscv_pbo_is_about_one_half_on_a_pure_noise_catalog() -> None:
    """Calibration check from Bailey et al. (2016).

    For a catalog with no real edge the in-sample winner's out-of-sample
    rank is uniform, so PBO averages 0.5. Any single run is noisy, so the
    check is on the mean over many independent catalogs.
    """
    values = []
    for seed in range(40):
        result = cscv_pbo(_noise_matrix(seed))
        assert result.computed and result.pbo is not None
        values.append(result.pbo)
    assert 0.35 < statistics.mean(values) < 0.65


def test_cscv_pbo_is_low_when_one_trial_has_a_genuine_edge() -> None:
    rng = random.Random(9)
    matrix = [[rng.gauss(0.0, 1.0) for _ in range(19)] + [rng.gauss(3.0, 1.0)] for _ in range(24)]
    result = cscv_pbo(matrix)
    assert result.computed and result.pbo is not None
    assert result.pbo < 0.1
    assert result.median_logit is not None and result.median_logit > 0


def test_cscv_pbo_is_exhaustive_and_therefore_exactly_reproducible() -> None:
    matrix = _noise_matrix(5)
    first, second = cscv_pbo(matrix), cscv_pbo(matrix)
    assert first.pbo == second.pbo
    assert first.median_logit == second.median_logit
    assert first.combinations == second.combinations > 0


def test_cscv_pbo_skips_with_a_reason_on_unusable_input() -> None:
    assert cscv_pbo([]).skipped_reason == "fewer_than_two_trials"
    assert cscv_pbo([[0.1]]).skipped_reason == "fewer_than_two_trials"
    assert cscv_pbo([[0.1, 0.2], [0.3]]).skipped_reason == "ragged_matrix"
    assert cscv_pbo([[0.1, 0.2], [0.3, 0.4]]).skipped_reason == "fewer_rows_than_minimum_splits"


def test_cscv_pbo_picks_blocks_that_waste_the_fewest_rows() -> None:
    result = cscv_pbo(_noise_matrix(1, rows=14, trials=10))
    assert result.computed
    assert result.splits % 2 == 0
    assert 14 % result.splits <= 2
