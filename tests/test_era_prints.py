"""Pre-registered era print policy (#135).

The eras are frozen before scoring, so these tests assert the *policy*
(what the windows are, that they are disjoint, that coverage needs real
bars) rather than any particular run's numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

from traderstack.candles import Candle
from traderstack.research.era_prints import (
    DEFAULT_MIN_ERA_BARS,
    PRE_REGISTERED_ERAS,
    REQUIRED_INDEPENDENT_ERAS,
    EraCoverage,
    PrintKind,
    classify_print_kind,
    describe_print_kind,
    era_coverage,
    era_for,
)


def daily(
    count: int, *, start: datetime, symbol: str = "BTC/USD", step_days: int = 1
) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    for index in range(count):
        price = 100.0 + index
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=start + timedelta(days=index * step_days),
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1_000.0,
            )
        )
    return tuple(candles)


def test_the_pre_registered_eras_are_the_ones_named_in_the_issue() -> None:
    assert [era.era_id for era in PRE_REGISTERED_ERAS] == [
        "2016-2019",
        "2020-2022",
        "2022-2024",
        "2024-2026",
    ]
    assert PRE_REGISTERED_ERAS[0].start == datetime(2016, 1, 1, tzinfo=UTC)
    assert PRE_REGISTERED_ERAS[-1].end == datetime(2026, 1, 1, tzinfo=UTC)


def test_eras_are_disjoint_and_contiguous() -> None:
    for earlier, later in pairwise(PRE_REGISTERED_ERAS):
        assert earlier.end <= later.start
        assert earlier.end == later.start, "eras must tile the decade with no gap"
    # A boundary instant belongs to exactly one era (half-open windows).
    boundary = datetime(2022, 1, 1, tzinfo=UTC)
    matched = [era.era_id for era in PRE_REGISTERED_ERAS if era.contains(boundary)]
    assert matched == ["2022-2024"]


def test_era_for_places_a_bar_in_at_most_one_era() -> None:
    assert era_for(datetime(2017, 6, 1, tzinfo=UTC)) is not None
    assert era_for(datetime(2017, 6, 1, tzinfo=UTC)).era_id == "2016-2019"  # type: ignore[union-attr]
    assert era_for(datetime(2015, 12, 31, tzinfo=UTC)) is None
    assert era_for(datetime(2026, 1, 1, tzinfo=UTC)) is None


def test_a_two_year_single_era_window_is_not_two_prints() -> None:
    """The #135 complaint, stated as a test.

    720 daily bars inside one era covers one era. Whatever venue it came
    from, that is a single print unless a second venue also scored it.
    """
    candles = daily(720, start=datetime(2024, 1, 2, tzinfo=UTC))
    coverage = era_coverage(candles, venue="kraken_spot")
    assert coverage.covered_eras == 1
    assert coverage.covered_era_ids == ["2024-2026"]
    assert not coverage.has_independent_eras
    assert classify_print_kind(venue_print_available=False, coverage=coverage) is PrintKind.SINGLE
    # A second venue over the same window is a venue print, named as such.
    assert classify_print_kind(venue_print_available=True, coverage=coverage) is PrintKind.VENUE


def test_two_covered_eras_on_one_venue_are_an_era_print() -> None:
    candles = daily(1000, start=datetime(2020, 1, 1, tzinfo=UTC)) + daily(
        400, start=datetime(2024, 1, 1, tzinfo=UTC)
    )
    coverage = era_coverage(candles, venue="kraken_spot")
    assert coverage.covered_eras >= REQUIRED_INDEPENDENT_ERAS
    assert coverage.has_independent_eras
    assert classify_print_kind(venue_print_available=False, coverage=coverage) is PrintKind.ERA
    assert classify_print_kind(venue_print_available=True, coverage=coverage) is PrintKind.BOTH


def test_an_era_needs_enough_bars_before_it_counts() -> None:
    thin = daily(DEFAULT_MIN_ERA_BARS - 1, start=datetime(2020, 1, 1, tzinfo=UTC))
    coverage = era_coverage(thin, venue="kraken_spot")
    span = next(row for row in coverage.spans if row.era_id == "2020-2022")
    assert span.bars == DEFAULT_MIN_ERA_BARS - 1
    assert not span.covered
    assert coverage.covered_eras == 0


def test_bars_outside_every_pre_registered_era_are_not_counted() -> None:
    coverage = era_coverage(daily(400, start=datetime(2014, 1, 1, tzinfo=UTC)), venue="kraken_spot")
    assert coverage.total_bars == 400
    assert coverage.covered_eras == 0
    assert all(span.bars == 0 for span in coverage.spans)


def test_a_missing_series_is_a_skip_not_a_covered_era() -> None:
    for empty in (None, ()):
        coverage = era_coverage(empty, venue="kraken_spot")
        assert coverage.total_bars == 0
        assert coverage.covered_eras == 0
        assert not coverage.has_independent_eras
        assert coverage.span_years is None
        assert classify_print_kind(venue_print_available=False, coverage=coverage) is (
            PrintKind.SINGLE
        )


def test_classify_never_upgrades_on_absent_coverage() -> None:
    assert classify_print_kind(venue_print_available=False, coverage=None) is PrintKind.SINGLE
    assert classify_print_kind(venue_print_available=True, coverage=None) is PrintKind.VENUE


def test_span_years_reports_the_observed_window_length() -> None:
    coverage = era_coverage(daily(731, start=datetime(2024, 1, 1, tzinfo=UTC)), venue="kraken_spot")
    assert coverage.span_years is not None
    assert 1.9 < coverage.span_years < 2.1


def test_describe_print_kind_names_the_kind_it_was_given() -> None:
    coverage = EraCoverage(venue="kraken_spot", covered_era_ids=["2020-2022", "2022-2024"])
    assert "single print" in describe_print_kind(PrintKind.SINGLE, coverage)
    assert "venue print" in describe_print_kind(PrintKind.VENUE, coverage)
    assert "era print" in describe_print_kind(PrintKind.ERA, coverage)
    assert "2020-2022" in describe_print_kind(PrintKind.ERA, coverage)
    assert "venue+era" in describe_print_kind(PrintKind.BOTH, coverage)
