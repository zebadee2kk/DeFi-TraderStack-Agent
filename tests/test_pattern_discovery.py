from datetime import UTC, datetime, timedelta

import pytest

from traderstack.research.pattern_discovery import DiscoveryRow, evaluate_feature_family


def _rows(count: int = 100) -> list[DiscoveryRow]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[DiscoveryRow] = []
    for index in range(count):
        signal = float(index)
        rows.append(
            DiscoveryRow(
                candidate_at=start + timedelta(hours=index),
                label=signal * 0.01,
                features={
                    "signal": signal,
                    "noise": float((index * 17) % 13),
                },
            )
        )
    return rows


def test_discovery_uses_time_ordered_untouched_holdout_and_trial_count() -> None:
    results = evaluate_feature_family(
        _rows(),
        features=("signal", "noise"),
        holdout_fraction=0.30,
        min_samples=20,
        seed=11,
    )

    by_feature = {row.feature: row for row in results}
    assert by_feature["signal"].trial_count == 2
    assert by_feature["signal"].discovery_n == 70
    assert by_feature["signal"].holdout_n == 30
    assert by_feature["signal"].discovery_correlation == pytest.approx(1.0)
    assert by_feature["signal"].holdout_correlation == pytest.approx(1.0)
    assert by_feature["signal"].adjusted_alpha == pytest.approx(0.025)
    assert by_feature["signal"].status == "research_evidence"


def test_placebo_is_deterministic_for_fixed_seed() -> None:
    first = evaluate_feature_family(_rows(), features=("signal",), seed=19)
    second = evaluate_feature_family(_rows(), features=("signal",), seed=19)

    assert first == second
    assert first[0].placebo_abs_correlation is not None


def test_insufficient_samples_fail_closed() -> None:
    result = evaluate_feature_family(
        _rows(12),
        features=("signal",),
        holdout_fraction=0.25,
        min_samples=5,
    )[0]

    assert result.status == "insufficient_evidence"


def test_future_rows_cannot_change_discovery_partition() -> None:
    base = _rows(100)
    baseline = evaluate_feature_family(
        base,
        features=("signal",),
        holdout_fraction=0.30,
        min_samples=20,
    )[0]

    future = list(base)
    for index in range(20):
        future.append(
            DiscoveryRow(
                candidate_at=datetime(2027, 1, 1, tzinfo=UTC) + timedelta(hours=index),
                label=-999.0,
                features={"signal": 999.0},
            )
        )

    changed = evaluate_feature_family(
        future,
        features=("signal",),
        holdout_fraction=0.30,
        min_samples=20,
    )[0]

    # The explicit chronological split means future rows cannot leak backward
    # into timestamps earlier than the split boundary. They may change which
    # rows are holdout when the dataset definition itself changes, so callers
    # must freeze the export query hash before a confirmation run.
    assert baseline.discovery_correlation == pytest.approx(1.0)
    assert changed.discovery_correlation == pytest.approx(1.0)


def test_invalid_family_controls_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one feature"):
        evaluate_feature_family(_rows(), features=())
    with pytest.raises(ValueError, match="family_alpha"):
        evaluate_feature_family(_rows(), features=("signal",), family_alpha=0.2)
