"""Bounded typed values and frozen pre-registration constants for the #142 tape.

Nothing here carries a size, a side, a notional or a limit: a wedge row is an
observation, never an instruction. The rules below are frozen *before* the tape
exists so the slice-2 evaluator cannot be tuned to the data it scores.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class CryptoAsset(StrEnum):
    BTC = "BTC"
    ETH = "ETH"


class WedgeRowStatus(StrEnum):
    OK = "ok"
    STALE_POLYMARKET = "stale_polymarket"
    STALE_DERIBIT = "stale_deribit"
    NO_TWO_SIDED_BOOK = "no_two_sided_book"
    NO_OPTION_PROBABILITY = "no_option_probability"


class CrucixStatus(StrEnum):
    """Known-clear is the only status that is not a stand-aside."""

    CLEAR = "clear"
    ADVERSE = "adverse"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


class ParsedCryptoThresholdMarket(BaseModel):
    """Deterministic parse of one Gamma threshold market."""

    market_id: str
    condition_id: str | None = None
    question: str
    asset: CryptoAsset
    strike_usd: float = Field(gt=0)
    resolves_at: datetime
    yes_token_id: str
    no_token_id: str
    event_slug: str | None = None
    resolution_text_ok: bool = False


class OptionImpliedProbability(BaseModel):
    """P(S_T > K) from the Deribit chain, with the inputs that produced it."""

    probability: float = Field(ge=0, le=1)
    model_version: str
    expiry_lo: datetime | None = None
    expiry_hi: datetime | None = None
    expiry_gap_hours: float = Field(ge=0)
    n_strikes_used: int = Field(ge=0)
    forward: float = Field(gt=0)
    sigma: float = Field(ge=0)
    tau_hours: float = Field(gt=0)
    deribit_observed_at: datetime


class CryptoWedgeRow(BaseModel):
    """One point-in-time observation appended to the wedge tape.

    There is deliberately no size, side, notional or limit field: this record
    cannot be read as an instruction by anything downstream.
    """

    venue: Literal["polymarket_vs_deribit"] = "polymarket_vs_deribit"
    trading_mode: Literal["paper"] = "paper"
    execution: Literal["paper_tape_only"] = "paper_tape_only"
    venue_submitted: Literal[False] = False
    strategy_id: str = "polymarket_crypto_threshold_wedge"
    status: WedgeRowStatus
    market_id: str
    question: str | None = None
    asset: CryptoAsset
    strike_usd: float = Field(gt=0)
    resolves_at: datetime
    observed_at: datetime
    poly_mid: float | None = Field(default=None, ge=0, le=1)
    poly_best_bid: float | None = Field(default=None, ge=0, le=1)
    poly_best_ask: float | None = Field(default=None, ge=0, le=1)
    poly_book_ts: datetime | None = None
    deribit_prob: float | None = Field(default=None, ge=0, le=1)
    model_version: str | None = None
    expiry_lo: datetime | None = None
    expiry_hi: datetime | None = None
    expiry_gap_hours: float | None = None
    deribit_ts: datetime | None = None
    wedge: float | None = None
    crucix_adverse: bool | None = None
    crucix_status: CrucixStatus
    resolution_text_ok: bool = False
    reasons: list[str] = Field(default_factory=list)


# --- frozen pre-registration (#142) -----------------------------------------
# Set before a single tape row exists. Changing any of these invalidates the
# pre-registration and must be a new, separately named model/rules version.
PRIMARY_MODEL_VERSION = "bs_n_d2_markiv_interp_v1"
PREREGISTERED_WEDGE_THRESHOLD = 0.05
MIN_ROWS_PER_PRINT = 20
MIN_TRADES_PER_PRINT = 8
# Polymarket Fee Structure V2: fee = shares * 0.07 * p * (1 - p), capped at
# 1.75 USD per 100 shares. Taken from the issue, not from venue payload text.
POLYMARKET_CRYPTO_TAKER_FEE_RATE = 0.07
POLYMARKET_CRYPTO_TAKER_FEE_CAP_PER_100_SHARES = 1.75
# Deribit option taker: 0.0003 BTC/ETH per contract, capped at 12.5% of premium.
DERIBIT_OPTION_TAKER_FEE_BTC = 0.0003
DERIBIT_OPTION_TAKER_FEE_PREMIUM_CAP = 0.125
DERIBIT_PERP_TAKER_BPS = 5.0
MULTI_PRINT_BAR_PREREGISTERED = True
# Documented as *not* a Settings field: no PAPER_PROMOTE_* default may flip,
# and this slice ships no promotion path at all.
DEFAULT_PROMOTE_FLAG = "PAPER_PROMOTE_POLYMARKET_CRYPTO_WEDGE"

CRYPTO_WEDGE_RULES = f"""\
Polymarket crypto-threshold vs Deribit option-implied wedge - pre-registered (#142)

Universe: Polymarket daily "Will the price of <Bitcoin|Ethereum> be above $K on
  <Month D>?" threshold markets (resolution 16:00 UTC on the Binance BTC/USDT or
  ETH/USDT 1-minute close at noon ET), matched against the Deribit option chain
  for the same currency.
Point-in-time by construction: every row is captured while the market is open and
  carries both venue timestamps (CLOB book `timestamp`, oldest Deribit quote
  `creation_timestamp`). A row may never be scored with a settlement price as its
  mid, and slice 2 must refuse rows with observed_at >= resolves_at.
Freshness: a row whose Polymarket book or oldest used Deribit quote is older than
  POLYMARKET_CRYPTO_MAX_STALENESS_SECONDS is recorded as stale_* and never scored.
  A one-sided book is no_two_sided_book. A missing series is a skip, never a zero.
Model: {PRIMARY_MODEL_VERSION} - mark-IV linearly interpolated in strike inside each
  Deribit expiry that brackets the resolution time, total variance interpolated
  linearly in time, forward = row underlying_price, r = 0, P = N(d2). The Deribit
  expiry (08:00 UTC) is not the Polymarket resolution instant (16:00 UTC): the
  recorded expiry_gap_hours says so. This is a comparable probability, not an
  identical payoff, and no arbitrage is claimed.
Wedge: poly_mid - deribit_prob. Frozen decision threshold |wedge| >=
  {PREREGISTERED_WEDGE_THRESHOLD}, fixed before any tape row exists.
Crucix stand-aside: a row only enters a trade mask when Crucix is positively
  known clear. adverse, unavailable and not_configured are all stand-aside. The
  gate can only remove trades (apply_crucix_gate returns a subset of its input
  mask); it has no size or side output and never reaches RiskEngine.
Fees (frozen, from the issue, never from venue payload text): Polymarket taker
  = shares * {POLYMARKET_CRYPTO_TAKER_FEE_RATE} * p * (1 - p), capped at
  {POLYMARKET_CRYPTO_TAKER_FEE_CAP_PER_100_SHARES} USD per 100 shares; Deribit
  option taker = {DERIBIT_OPTION_TAKER_FEE_BTC} of the underlying per contract,
  capped at {DERIBIT_OPTION_TAKER_FEE_PREMIUM_CAP:.3f} of premium; a delta-hedge
  perp leg costs {DERIBIT_PERP_TAKER_BPS:g} bps taker.
Reporting: unhedged and hedged PnL reported separately, with controls
  always_hold and fade_the_mid computed on the same trade mask.
Print bar: MULTI_PRINT_BAR_PREREGISTERED = {MULTI_PRINT_BAR_PREREGISTERED}; a claim
  needs two independent prints (BTC vs ETH, or non-overlapping resolution dates),
  MIN_ROWS_PER_PRINT = {MIN_ROWS_PER_PRINT} and MIN_TRADES_PER_PRINT =
  {MIN_TRADES_PER_PRINT}. {DEFAULT_PROMOTE_FLAG} is NOT a Settings field and this
  slice ships no promotion path.
Empty is success: a cycle that discovers no open event, or an evaluation with no
  qualifying rows, is a successful result and is reported as such.
"""
