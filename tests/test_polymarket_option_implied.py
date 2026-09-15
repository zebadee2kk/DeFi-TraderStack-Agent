"""The frozen option-implied digital model (#142): N(d2) from mark IV."""

from datetime import UTC, datetime, timedelta

from traderstack.market.deribit import OptionInstrument, OptionQuote
from traderstack.polymarket.crypto_models import PRIMARY_MODEL_VERSION
from traderstack.polymarket.option_implied import (
    SKIP_NO_BRACKETING_EXPIRY,
    SKIP_NO_QUOTES,
    SKIP_RESOLVED_OR_PAST,
    SKIP_SPARSE_CHAIN,
    implied_digital_probability,
)

NOW = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)
RESOLVES = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)
EXPIRY_LO = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
EXPIRY_HI = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)


def chain(
    expiries: tuple[datetime, ...],
    strikes: tuple[float, ...],
    *,
    forward: float = 76000.0,
    iv: float = 40.0,
    observed_at: datetime | None = None,
    option_type: str = "call",
) -> tuple[tuple[OptionQuote, ...], tuple[OptionInstrument, ...]]:
    quotes: list[OptionQuote] = []
    instruments: list[OptionInstrument] = []
    for index, expiry in enumerate(expiries):
        for strike in strikes:
            name = f"BTC-{index}-{int(strike)}-C"
            instruments.append(
                OptionInstrument(
                    instrument_name=name,
                    currency="BTC",
                    strike=strike,
                    option_type=option_type,  # type: ignore[arg-type]
                    expiry_at=expiry,
                )
            )
            quotes.append(
                OptionQuote(
                    instrument_name=name,
                    mark_iv=iv,
                    mark_price=0.05,
                    underlying_price=forward,
                    observed_at=observed_at or (NOW - timedelta(seconds=30 * (index + 1))),
                )
            )
    return tuple(quotes), tuple(instruments)


STRIKES = (70000.0, 74000.0, 78000.0, 82000.0)


def score(strike: float, **kwargs: object) -> float:
    quotes, instruments = chain((EXPIRY_LO, EXPIRY_HI), STRIKES, **kwargs)  # type: ignore[arg-type]
    result, reason = implied_digital_probability(
        quotes,
        instruments,
        strike=strike,
        resolves_at=RESOLVES,
        now=NOW,
        max_expiry_gap_hours=24.0,
    )
    assert reason is None, reason
    assert result is not None
    return result.probability


def test_probability_decreases_in_strike() -> None:
    values = [score(k) for k in (71000.0, 75000.0, 79000.0)]
    assert values == sorted(values, reverse=True)
    assert all(0.0 <= value <= 1.0 for value in values)


def test_probability_increases_in_forward() -> None:
    assert score(76000.0, forward=80000.0) > score(76000.0, forward=72000.0)


def test_at_the_forward_is_just_below_a_half() -> None:
    value = score(76000.0, forward=76000.0)
    assert 0.45 < value < 0.5


def test_two_bracketing_expiries_interpolate_total_variance() -> None:
    quotes, instruments = chain((EXPIRY_LO, EXPIRY_HI), STRIKES, iv=40.0)
    both, reason = implied_digital_probability(
        quotes,
        instruments,
        strike=75000.0,
        resolves_at=RESOLVES,
        now=NOW,
        max_expiry_gap_hours=24.0,
    )
    assert reason is None and both is not None
    assert both.expiry_lo == EXPIRY_LO
    assert both.expiry_hi == EXPIRY_HI
    # With a flat IV surface the interpolated sigma is that same IV.
    assert abs(both.sigma - 0.40) < 1e-9
    assert both.model_version == PRIMARY_MODEL_VERSION
    assert both.tau_hours == 10.0


def test_single_expiry_inside_the_gap_still_scores_and_records_it() -> None:
    quotes, instruments = chain((EXPIRY_LO,), STRIKES)
    result, reason = implied_digital_probability(
        quotes,
        instruments,
        strike=75000.0,
        resolves_at=RESOLVES,
        now=NOW,
        max_expiry_gap_hours=24.0,
    )
    assert reason is None and result is not None
    assert result.expiry_hi is None
    assert result.expiry_gap_hours == 8.0


def test_no_expiry_within_the_gap_is_a_skip() -> None:
    far = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
    quotes, instruments = chain((far,), STRIKES)
    result, reason = implied_digital_probability(
        quotes,
        instruments,
        strike=75000.0,
        resolves_at=RESOLVES,
        now=NOW,
        max_expiry_gap_hours=24.0,
    )
    assert result is None
    assert reason == SKIP_NO_BRACKETING_EXPIRY


def test_strikes_all_on_one_side_are_a_sparse_chain_skip() -> None:
    quotes, instruments = chain((EXPIRY_LO, EXPIRY_HI), STRIKES)
    result, reason = implied_digital_probability(
        quotes,
        instruments,
        strike=999000.0,
        resolves_at=RESOLVES,
        now=NOW,
        max_expiry_gap_hours=24.0,
    )
    assert result is None
    assert reason == SKIP_SPARSE_CHAIN


def test_resolution_in_the_past_is_a_skip() -> None:
    quotes, instruments = chain((EXPIRY_LO, EXPIRY_HI), STRIKES)
    result, reason = implied_digital_probability(
        quotes,
        instruments,
        strike=75000.0,
        resolves_at=NOW,
        now=NOW,
        max_expiry_gap_hours=24.0,
    )
    assert result is None
    assert reason == SKIP_RESOLVED_OR_PAST


def test_puts_only_chain_has_no_quotes() -> None:
    quotes, instruments = chain((EXPIRY_LO, EXPIRY_HI), STRIKES, option_type="put")
    result, reason = implied_digital_probability(
        quotes,
        instruments,
        strike=75000.0,
        resolves_at=RESOLVES,
        now=NOW,
        max_expiry_gap_hours=24.0,
    )
    assert result is None
    assert reason == SKIP_NO_QUOTES


def test_deribit_observed_at_is_the_oldest_used_quote() -> None:
    quotes, instruments = chain((EXPIRY_LO, EXPIRY_HI), STRIKES)
    result, reason = implied_digital_probability(
        quotes,
        instruments,
        strike=75000.0,
        resolves_at=RESOLVES,
        now=NOW,
        max_expiry_gap_hours=24.0,
    )
    assert reason is None and result is not None
    assert result.deribit_observed_at == min(quote.observed_at for quote in quotes)
