"""Digital probability P(S_T > K) from the Deribit chain (#142).

Pure and deterministic: no network, no ``Settings``, no clock of its own. The
model is frozen and versioned (``PRIMARY_MODEL_VERSION``) so the tape records
which arithmetic produced each probability:

1. keep call quotes with a positive mark IV, a positive mark price and an
   expiry still in the future;
2. pick the two Deribit expiries that bracket the Polymarket resolution time
   (either side may be missing; the nearest must be within
   ``max_expiry_gap_hours``);
3. inside each chosen expiry, linearly interpolate mark IV in strike at K
   (both a strike at or below and a strike at or above K must exist);
4. interpolate total variance w = sigma^2 * tau linearly in tau to the
   resolution time (with one expiry only, hold sigma flat);
5. P = N(d2) with forward = the quote rows' ``underlying_price`` and r = 0.

A Deribit daily expires 08:00 UTC while the Polymarket market resolves 16:00
UTC, so ``expiry_gap_hours`` is always recorded: this is a comparable
probability, not an identical payoff, and no arbitrage is implied.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import datetime

from traderstack.market.deribit import OptionInstrument, OptionQuote
from traderstack.polymarket.crypto_models import (
    PRIMARY_MODEL_VERSION,
    OptionImpliedProbability,
)
from traderstack.polymarket.edge import normal_cdf

_HOURS_PER_YEAR = 365.0 * 24.0

SKIP_NO_QUOTES = "no_option_quotes"
SKIP_NO_BRACKETING_EXPIRY = "no_bracketing_expiry"
SKIP_SPARSE_CHAIN = "sparse_chain"
SKIP_RESOLVED_OR_PAST = "resolved_or_past"
SKIP_DEGENERATE_INPUTS = "degenerate_inputs"


class _ExpirySlice:
    """Usable call quotes for one expiry, indexed by strike."""

    __slots__ = ("expiry_at", "rows", "tau_years")

    def __init__(self, expiry_at: datetime, tau_years: float) -> None:
        self.expiry_at = expiry_at
        self.tau_years = tau_years
        self.rows: list[tuple[float, OptionQuote]] = []


def _interpolate_iv(
    rows: Sequence[tuple[float, OptionQuote]], strike: float
) -> tuple[float, float, tuple[OptionQuote, ...]] | None:
    """Return (iv_percent, forward, rows used) at ``strike``, or None.

    Requires a listed strike at or below and at or above ``strike``: the chain
    is interpolated, never extrapolated.
    """

    ordered = sorted(rows, key=lambda item: item[0])
    below = [item for item in ordered if item[0] <= strike]
    above = [item for item in ordered if item[0] >= strike]
    if not below or not above:
        return None
    k_lo, quote_lo = below[-1]
    k_hi, quote_hi = above[0]
    if k_hi == k_lo:
        return quote_lo.mark_iv, quote_lo.underlying_price, (quote_lo,)
    weight = (strike - k_lo) / (k_hi - k_lo)
    iv = quote_lo.mark_iv + weight * (quote_hi.mark_iv - quote_lo.mark_iv)
    forward = 0.5 * (quote_lo.underlying_price + quote_hi.underlying_price)
    return iv, forward, (quote_lo, quote_hi)


def implied_digital_probability(
    quotes: Iterable[OptionQuote],
    instruments: Iterable[OptionInstrument],
    *,
    strike: float,
    resolves_at: datetime,
    now: datetime,
    max_expiry_gap_hours: float,
) -> tuple[OptionImpliedProbability | None, str | None]:
    """Return ``(probability, None)`` or ``(None, skip_reason)``.

    A missing or unusable chain is a skip with a named reason, never a guessed
    probability and never a zero.
    """

    if strike <= 0:
        return None, SKIP_DEGENERATE_INPUTS
    tau_res_hours = (resolves_at - now).total_seconds() / 3600.0
    if tau_res_hours <= 0:
        return None, SKIP_RESOLVED_OR_PAST
    tau_res = tau_res_hours / _HOURS_PER_YEAR

    by_name = {row.instrument_name: row for row in instruments}
    slices: dict[datetime, _ExpirySlice] = {}
    for quote in quotes:
        instrument = by_name.get(quote.instrument_name)
        if instrument is None or instrument.option_type != "call":
            continue
        if quote.mark_iv <= 0 or quote.mark_price <= 0:
            continue
        tau_hours = (instrument.expiry_at - now).total_seconds() / 3600.0
        if tau_hours <= 0:
            continue
        chain = slices.get(instrument.expiry_at)
        if chain is None:
            chain = _ExpirySlice(instrument.expiry_at, tau_hours / _HOURS_PER_YEAR)
            slices[instrument.expiry_at] = chain
        chain.rows.append((instrument.strike, quote))

    if not slices:
        return None, SKIP_NO_QUOTES

    expiries = sorted(slices)
    at_or_before = [item for item in expiries if item <= resolves_at]
    at_or_after = [item for item in expiries if item >= resolves_at]
    expiry_lo = at_or_before[-1] if at_or_before else None
    expiry_hi = at_or_after[0] if at_or_after else None

    gap = max_expiry_gap_hours
    candidates: list[_ExpirySlice] = []
    for expiry in (expiry_lo, expiry_hi):
        if expiry is None:
            continue
        hours = abs((expiry - resolves_at).total_seconds()) / 3600.0
        if hours <= gap:
            candidates.append(slices[expiry])
    if not candidates:
        return None, SKIP_NO_BRACKETING_EXPIRY

    usable: list[tuple[_ExpirySlice, float, float, tuple[OptionQuote, ...]]] = []
    for chain in candidates:
        interpolated = _interpolate_iv(chain.rows, strike)
        if interpolated is None:
            continue
        iv, forward, used = interpolated
        usable.append((chain, iv, forward, used))
    if not usable:
        return None, SKIP_SPARSE_CHAIN

    usable.sort(key=lambda item: item[0].expiry_at)
    used_rows: list[OptionQuote] = []
    for _, _, _, rows_used in usable:
        used_rows.extend(rows_used)

    if len(usable) == 2:
        lo, hi = usable
        w_lo = (lo[1] / 100.0) ** 2 * lo[0].tau_years
        w_hi = (hi[1] / 100.0) ** 2 * hi[0].tau_years
        span = hi[0].tau_years - lo[0].tau_years
        if span <= 0:
            w_res = w_lo
        else:
            weight = (tau_res - lo[0].tau_years) / span
            w_res = w_lo + weight * (w_hi - w_lo)
    else:
        only = usable[0]
        w_res = (only[1] / 100.0) ** 2 * tau_res

    if w_res <= 0:
        return None, SKIP_DEGENERATE_INPUTS
    sigma = math.sqrt(w_res / tau_res)
    # Forward from the expiry nearest the resolution time.
    nearest = min(usable, key=lambda item: abs((item[0].expiry_at - resolves_at).total_seconds()))
    forward = nearest[2]
    if forward <= 0 or sigma <= 0:
        return None, SKIP_DEGENERATE_INPUTS

    d2 = (math.log(forward / strike) - 0.5 * sigma * sigma * tau_res) / (sigma * math.sqrt(tau_res))
    probability = min(1.0, max(0.0, normal_cdf(d2)))
    gap_hours = abs((nearest[0].expiry_at - resolves_at).total_seconds()) / 3600.0

    return (
        OptionImpliedProbability(
            probability=probability,
            model_version=PRIMARY_MODEL_VERSION,
            expiry_lo=expiry_lo,
            expiry_hi=expiry_hi,
            expiry_gap_hours=gap_hours,
            n_strikes_used=len({row.instrument_name for row in used_rows}),
            forward=forward,
            sigma=sigma,
            tau_hours=tau_res_hours,
            deribit_observed_at=min(row.observed_at for row in used_rows),
        ),
        None,
    )
