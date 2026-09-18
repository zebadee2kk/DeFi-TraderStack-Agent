"""Ensemble-trend dual-print search (#137): multi-lookback Donchian-on-close,
trailing stop, 25% vol target, top-20 point-in-time Kraken universe.

Pre-registered before any live pull (do not retune after seeing PnL).
Source rules: Zarattini, Pagani, Barbon, "Catching Crypto Trends"
(SSRN 5209907, 2025), via the CXO Advisory summary. This is **not** a
#118 Donchian N retune: #118 scored single high/low channels on two
assets; this family votes nine close-only lookbacks, trails a stop,
targets volatility, and forces non-members of a monthly point-in-time
universe flat.

Treatment (frozen): for each lookback N in {5, 10, 20, 30, 60, 90,
150, 250, 360}, that lookback's position opens long when
``close[t] > max(close over bars [t-N, t))`` — bar t never sets its
own level. On entry the stop is the midpoint of that prior N-bar close
channel ``(max_close + min_close) / 2``. On every later bar the stop is
``max(prior stop, current prior-window midpoint)`` and never ratchets
down; the position exits to flat when ``close[t] < stop``. Re-entry
needs a fresh breakout on a later bar (an exit bar never re-enters).

Ensemble weight on bar t = (open lookbacks / total lookbacks)
× min(0.25 / annualised 90-bar realised vol through close[t], 1.0),
long-only, capped at 1.0 (paper spot has no leverage; the paper's
leverage is not reproduced). Decision at close[t]; fill at t+1 open,
like every sibling family. Realised vol through bar t is allowed
because the decision is taken after close[t].

Universe (frozen): ``CANDIDATE_UNIVERSE`` Kraken USD spot pairs.
Monthly point-in-time snapshot using only bars strictly before the
month start: a name qualifies when it is listed for at least
``UNIVERSE_MIN_LISTED_BARS`` prior daily bars (a Kraken series that
hits the 720-bar public cap is inferred to predate the window) and
its median 30-bar close×volume is at least
``UNIVERSE_MEDIAN_DOLLAR_VOLUME_USD``; the top ``UNIVERSE_TOP_K`` by
that median are members. A non-member bar is forced flat. Kraken
REST serves only currently-listed pairs, so this window is
survivorship-biased (unlike the paper's universe) — stated in every
report header, never hidden.

Fees come from the frozen Kraken Pro tier table (``--kraken-tier``,
default tier 1 = 40/80 bps maker/taker; the taker leg is charged per
side; gate C still doubles) unless ``--fee-bps`` is explicit.

Scoring: the same #96+A+B+C combined gates as #104 on **BTC and ETH**
on the Kraken public daily 720 and the #102 Binance.US older-720; SOL
is reported, not a gate. Ranking key (frozen):
``mean_holdout_excess_among_dual_print_passers``. The informational
control ``ma_cross_10_30`` cannot enter the passer set. Era prints
(#133) and DSR / PBO (#135) are reported as **unavailable** until they
land; they are not invented. Attribution by asset and by lookback is
gross (close-to-close, no fees) and informational only.

Paper path: ``EnsembleTrendVoter`` emits BUY with ``score`` in [0, 1]
or ``side=None``; never SELL. RiskEngine is untouched and sizes from
Settings, so the engine can only reduce. No ``PAPER_PROMOTE_*`` field
is added here; ``build_ensemble_trend_paper_ensemble`` exists for a
future flag PR (default false) and is not wired into ``cli.py``.
Empty dual-print set is success. No live.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt

from pydantic import BaseModel, Field

from traderstack.candles import Candle, periods_per_year
from traderstack.indicators import simple_return, standard_deviation
from traderstack.models import Side
from traderstack.research.binance_spot import BINANCE_TAKER_BPS_NOTE
from traderstack.research.candidates import AlwaysOnTrendStrategy
from traderstack.research.daily_robustness import (
    KRAKEN_DAILY_CAP_NOTE,
    KRAKEN_PUBLIC_OHLC_MAX_BARS,
)
from traderstack.research.donchian_breakout import (
    ALIAS_TO_CANONICAL,
    _passer_table,
    _score_symbols_only,
    _slice_lines,
)
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
    _binance_slice_meta,
    _merge_row,
    _score,
    rank_dual_print_passers,
)
from traderstack.research.harder_gates import (
    HARDER_GATES_NOTE,
    CandidateHarderResult,
    _pct,
    kraken_daily_candles,
    paper_promote_flag_name,
)
from traderstack.research.harder_gates import (
    RANKING_KEY as KRAKEN_COMBINED_RANKING_KEY,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.second_print import (
    BINANCE_SLICE_RULE,
    SECOND_PRINT_BARS,
    SliceMeta,
    primary_first_opened_at,
    remap_binance_for_scoring,
    slice_ending_before,
)
from traderstack.strategies import Regime, StrategyEnsemble, StrategySignal

ENSEMBLE_LOOKBACKS: tuple[int, ...] = (5, 10, 20, 30, 60, 90, 150, 250, 360)
SHORT_LOOKBACKS: tuple[int, ...] = (5, 10, 20, 30, 60, 90)
VOL_TARGET_ANNUAL = 0.25
VOL_LOOKBACK = 90
MAX_LEVERAGE = 1.0
REBALANCE_THRESHOLD = 0.05
ENTRY_RULE = "close_above_prior_n_max_close"
STOP_RULE = "max_prior_stop_close_channel_midpoint"
# (candidate_id, lookbacks, vol_target_annual or None, min_open)
# min_open=0 preserves #137 open-fraction behaviour (no consensus floor).
ENSEMBLE_CATALOG: tuple[tuple[str, tuple[int, ...], float | None, int], ...] = (
    ("ens_trend_9lb_vt25", ENSEMBLE_LOOKBACKS, VOL_TARGET_ANNUAL, 0),
    ("ens_trend_6lb_vt25", SHORT_LOOKBACKS, VOL_TARGET_ANNUAL, 0),
    ("ens_trend_9lb_unit", ENSEMBLE_LOOKBACKS, None, 0),
)
ENSEMBLE_IDS: tuple[str, ...] = tuple(item[0] for item in ENSEMBLE_CATALOG)
CONTROL_ID = "ma_cross_10_30"
CONTROL_IDS: frozenset[str] = frozenset({CONTROL_ID})
CORE_IDS: tuple[str, ...] = ENSEMBLE_IDS + (CONTROL_ID,)

# --- ensemble-trend v2 consensus catalog (fresh ids; do not retune #137) ---
V2_VOL_TARGET_ANNUAL = 0.15
V2_MID_LOOKBACKS: tuple[int, ...] = (30, 60, 90, 150)
V2_LONG_LOOKBACKS: tuple[int, ...] = (60, 90, 150, 250)
V2_STRICT_LOOKBACKS: tuple[int, ...] = (20, 30, 60, 90, 150)
V2_CATALOG: tuple[tuple[str, tuple[int, ...], float | None, int], ...] = (
    ("ens_trend_v2_maj_mid_vt15", V2_MID_LOOKBACKS, V2_VOL_TARGET_ANNUAL, 2),
    ("ens_trend_v2_maj_long_vt15", V2_LONG_LOOKBACKS, V2_VOL_TARGET_ANNUAL, 2),
    ("ens_trend_v2_strict_mid_vt15", V2_STRICT_LOOKBACKS, V2_VOL_TARGET_ANNUAL, 3),
)
V2_IDS: tuple[str, ...] = tuple(item[0] for item in V2_CATALOG)
V2_CORE_IDS: tuple[str, ...] = V2_IDS + (CONTROL_ID,)
V2_CATALOG_NOTE = (
    f"Frozen ensemble-trend v2 consensus catalog (K={len(V2_CORE_IDS)}): "
    "`ens_trend_v2_maj_mid_vt15` (lookbacks {30,60,90,150}, min_open=2, 15% vol), "
    "`ens_trend_v2_maj_long_vt15` (lookbacks {60,90,150,250}, min_open=2, 15% vol), "
    "`ens_trend_v2_strict_mid_vt15` (lookbacks {20,30,60,90,150}, min_open=3, 15% vol), "
    f"plus informational control `{CONTROL_ID}` (cannot promote). Distinct from the "
    "#137 ENSEMBLE_CATALOG — do not retune either list after seeing PnL. "
    "PAPER_PROMOTE_* stays false."
)
CATALOGS: dict[str, tuple[tuple[str, tuple[int, ...], float | None, int], ...]] = {
    "default": ENSEMBLE_CATALOG,
    "v2": V2_CATALOG,
}
SECOND_PRINT_CONCURRENT = "concurrent_venue_harder_gates"
SECOND_PRINT_OLDER_720 = "older_720_ending_before_primary_first_bar"


def resolve_catalog(name: str) -> tuple[tuple[str, tuple[int, ...], float | None, int], ...]:
    """Return a frozen catalog by CLI name. Unknown names raise."""
    try:
        return CATALOGS[name]
    except KeyError as exc:
        raise ValueError(f"unknown catalog {name!r}; known: {sorted(CATALOGS)}") from exc


def catalog_core_ids(name: str) -> tuple[str, ...]:
    if name == "v2":
        return V2_CORE_IDS
    return CORE_IDS


def catalog_note_for(name: str) -> str:
    if name == "v2":
        return V2_CATALOG_NOTE
    return CATALOG_NOTE


GATE_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")
PAPER_PATH_READY = True
MULTI_ASSET_GATE_RULE = "btc_eth_signs_as_96_abc_sol_reported_not_required"
ERA_PRINTS_AVAILABLE = False
DSR_PBO_AVAILABLE = False

# Frozen Kraken USD spot pairs (probed 2026-09-14 with GET /0/public/OHLC
# interval=1440; every name below answered with committed daily bars).
# Kraken REST serves only currently-listed pairs: this is not the
# paper's survivorship-free universe. Membership is point-in-time from
# these series only; a name that fails the age or dollar-volume bar in
# a month is simply not a member that month. Do not grow or reorder
# after seeing PnL. Dropped before the first run because Kraken
# answered `EQuery:Invalid asset pair`: MATIC (now POL), EOS, MKR.
# Stablecoins (USDT, USDC) are excluded by rule: they are not trend
# assets. Names with fewer than 720 bars on Kraken (TON, HBAR, BNB,
# TRUMP, HYPE) are kept so the listing-age filter is exercised
# point-in-time rather than by hand.
CANDIDATE_UNIVERSE: tuple[str, ...] = (
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "XRP/USD",
    "DOGE/USD",
    "ADA/USD",
    "SUI/USD",
    "LINK/USD",
    "XMR/USD",
    "NEAR/USD",
    "UNI/USD",
    "LTC/USD",
    "ENA/USD",
    "PEPE/USD",
    "CRV/USD",
    "XLM/USD",
    "AAVE/USD",
    "AVAX/USD",
    "ONDO/USD",
    "TRX/USD",
    "BCH/USD",
    "INJ/USD",
    "ICP/USD",
    "FET/USD",
    "POL/USD",
    "ARB/USD",
    "DOT/USD",
    "JUP/USD",
    "ALGO/USD",
    "APT/USD",
    "ZEC/USD",
    "TAO/USD",
    "DASH/USD",
    "TON/USD",
    "HBAR/USD",
    "BNB/USD",
    "TRUMP/USD",
    "HYPE/USD",
)
UNIVERSE_MIN_LISTED_BARS = 365
UNIVERSE_DOLLAR_VOLUME_BARS = 30
UNIVERSE_MEDIAN_DOLLAR_VOLUME_USD = 2_000_000.0
UNIVERSE_TOP_K = 20

# Kraken Pro spot fee schedule (bps, maker/taker) by 30-day volume tier,
# frozen from the public schedule on 2026-09-14. Tier 1 is the pilot's
# tier (< $10k 30-day volume). Kept local behind fee_tier_taker_bps();
# #138 owns moving it into research/costs.py.
KRAKEN_PRO_TIERS: dict[int, tuple[float, float]] = {
    1: (40.0, 80.0),
    2: (30.0, 60.0),
    3: (22.0, 38.0),
    8: (8.0, 20.0),
    12: (0.0, 10.0),
}
DEFAULT_KRAKEN_TIER = 1

ENSEMBLE_RULES = (
    "Pre-registered ensemble-trend dual-print bar (#137; frozen before "
    "any Kraken or Binance.US score). Treatment: for each lookback N in "
    f"{{{', '.join(str(n) for n in ENSEMBLE_LOOKBACKS)}}}, entry rule "
    f"`{ENTRY_RULE}`: that lookback opens long when close[t] > max close "
    "of bars [t-N, t) (bar t never sets its own level). Stop rule "
    f"`{STOP_RULE}`: on entry the stop is the midpoint of the prior "
    "N-bar close channel; every later bar the stop is max(prior stop, "
    "current prior-window midpoint) and never ratchets down; exit to "
    "flat when close[t] < stop; re-entry needs a fresh breakout on a "
    "later bar. Ensemble weight = (open lookbacks / total lookbacks) × "
    f"min({VOL_TARGET_ANNUAL:g} / annualised {VOL_LOOKBACK}-bar realised "
    f"vol through close[t], 1.0), long-only, capped at {MAX_LEVERAGE:g} "
    "(paper spot has no leverage). Decision at close[t]; fill at t+1 "
    "open. Universe: frozen CANDIDATE_UNIVERSE Kraken USD spot pairs "
    "with a monthly point-in-time snapshot (bars strictly before the "
    f"month start only): listed ≥ {UNIVERSE_MIN_LISTED_BARS} prior daily "
    "bars (a 720-cap series is inferred to predate the window) and "
    f"median {UNIVERSE_DOLLAR_VOLUME_BARS}-bar close×volume ≥ "
    f"${UNIVERSE_MEDIAN_DOLLAR_VOLUME_USD:,.0f} (Kraken-local volume, "
    f"stricter than the paper's aggregate); top-{UNIVERSE_TOP_K} by that "
    "median are members; a non-member bar is forced flat. Kraken REST "
    "serves only currently-listed pairs, so this window is "
    "survivorship-biased (unlike the paper). Fees: Kraken Pro tier "
    "table (taker leg per side; default tier 1 = 80 bps) unless "
    "--fee-bps is explicit; gate C doubles. Multi-asset combined bar: "
    f"`{MULTI_ASSET_GATE_RULE}` — #96 balanced-holdout and A magnitude "
    "and B multi-window and C 2× fees on BTC and ETH; SOL is reported "
    "when present and is not a gate. Equal-weight portfolio metrics "
    "are not used. A dual-print passer must combined-PASS the Kraken "
    "primary 720-bar daily window AND the #102 Binance.US older-720 "
    f"(`{BINANCE_SLICE_RULE}`: {SECOND_PRINT_BARS} committed daily "
    "BTC+ETH bars ending strictly before the primary Kraken first "
    f"bar). Ranking key: {RANKING_KEY} — Kraken BTC+ETH mean holdout "
    "excess among dual-print passers (tie-break: candidate_id). "
    "Binance holdout is a gate only; "
    f"CAN_AVERAGE_VENUES={str(CAN_AVERAGE_VENUES).lower()}. "
    f"MULTI_VENUE_BAR_PREREGISTERED="
    f"{str(MULTI_VENUE_BAR_PREREGISTERED).lower()}. A Kraken-only "
    "combined-passer is not a dual-print passer and cannot promote. "
    f"The informational control {CONTROL_ID} cannot enter the passer "
    "set. Missing, short, or overlapping Binance fails closed (zero "
    "dual-print passers). Era prints (#133) and DSR / PBO (#135) are "
    f"era_prints_available={str(ERA_PRINTS_AVAILABLE).lower()} / "
    f"dsr_pbo_available={str(DSR_PBO_AVAILABLE).lower()} until they "
    "land; they are not invented. The shared harness charges fees on "
    "full equity at every rebalance regardless of fractional weight "
    "(cost-overstated, conservative). The precomputed series restarts "
    "stop state from the series start, like the #118 lookup voter. "
    "Paper-executable on Kraken spot BTC/USD+ETH/USD (SOL optional) "
    f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()}). "
    "PAPER_PROMOTE_* stays default false. No live. An empty dual-print "
    "set is success. Not a #118 Donchian N retune, not an EMA reprint, "
    "not a BTC−ETH residual reprint, not cross-sectional momentum, and "
    "not a carry/basis family."
)

CATALOG_NOTE = (
    f"Frozen catalog (K={len(CORE_IDS)}): `ens_trend_9lb_vt25` (all nine "
    "lookbacks, 25% vol target), `ens_trend_6lb_vt25` (lookbacks "
    f"{{{', '.join(str(n) for n in SHORT_LOOKBACKS)}}}, 25% vol target; "
    "pre-registered because the 720-bar Kraken cap leaves the "
    "nine-lookback book warmup-limited to ~359 decision bars — this is "
    "not a post-hoc retune), `ens_trend_9lb_unit` (all nine lookbacks, "
    "open-fraction weight without the vol scalar; informational "
    f"contrast), plus informational control {CONTROL_ID} (cannot "
    "promote). Do not grow this list after seeing PnL. Channels, stops "
    "and vol are built from venue-local closes; a missing or short "
    "series is skipped, never zero-filled. PAPER_PROMOTE_* stays false "
    "unless a committed dual-print report names a paper-only pin and "
    "an operator flips it."
)

UNIVERSE_SNAPSHOT_NOTE = (
    "Universe snapshot policy (frozen): on the first bar of each UTC "
    "month, using only bars strictly before that month, a name is a "
    f"member when it has ≥ {UNIVERSE_MIN_LISTED_BARS} prior daily bars "
    "(or its Kraken series hits the 720-bar public cap, which implies "
    "the listing predates the window) and its median "
    f"{UNIVERSE_DOLLAR_VOLUME_BARS}-bar close×volume is ≥ "
    f"${UNIVERSE_MEDIAN_DOLLAR_VOLUME_USD:,.0f}; the top-"
    f"{UNIVERSE_TOP_K} by that median are members for the whole month. "
    "Fewer than 20 qualifiers means a smaller book, never a relaxed "
    "bar. A non-member bar is forced flat. Membership never looks at "
    "bars inside or after the month it governs."
)

SURVIVORSHIP_NOTE = (
    "Survivorship: Kraken public REST returns OHLC only for pairs that "
    "are listed today, and at most 720 daily bars each. The frozen "
    "CANDIDATE_UNIVERSE therefore omits every delisted name and cannot "
    "reproduce the paper's survivorship-bias-free 2015–2025 universe. "
    "The monthly point-in-time snapshot removes look-ahead in "
    "membership only; it does not remove delisting bias. Treat any "
    "pass on this window as an upper bound until the #133 archives "
    "supply delisted histories."
)

WARMUP_NOTE = (
    "Warmup on the 720-bar cap: the nine-lookback book needs "
    f"{max(ENSEMBLE_LOOKBACKS) + 1} bars before its first assignment "
    f"(~{KRAKEN_PUBLIC_OHLC_MAX_BARS - max(ENSEMBLE_LOOKBACKS) - 1} "
    "decision bars remain), so early walk-forward folds are all-flat "
    "and min_trades may fail. That is reported as skipped / "
    "warmup-limited, never invented, and is why `ens_trend_6lb_vt25` "
    "is in the same frozen catalog."
)

PAPER_EXECUTABLE_PATH_NOTE = (
    "This family is paper-executable on Kraken spot. "
    "`EnsembleTrendVoter` is a candle-only voter: BUY with score in "
    "(0, 1] when the ensemble weight is positive, side=None otherwise, "
    "never SELL. When no precomputed series is registered for a symbol "
    "it recomputes `ensemble_trend_series` on the decision-time candles "
    "it is given, so the existing pre-trade gate can re-confirm it. The "
    "weight travels only as StrategySignal.score / confidence; "
    "RiskEngine sizes from Settings and can only reduce. The strategy's "
    "trailing stop is a research construct — runtime exits remain the "
    "EXIT_* rules. No perp, no leverage, no hedge book. A Settings pin "
    "is still added only if a committed dual-print passer exists, and "
    "then default false; none is added by #137."
)


def fee_tier_taker_bps(tier: int) -> float:
    """Taker bps per side for a frozen Kraken Pro tier. Unknown tier raises."""
    if tier not in KRAKEN_PRO_TIERS:
        raise ValueError(f"unknown Kraken Pro tier {tier!r}; known: {sorted(KRAKEN_PRO_TIERS)}")
    return KRAKEN_PRO_TIERS[tier][1]


def prior_close_channel(
    candles: tuple[Candle, ...],
    index: int,
    lookback: int,
) -> tuple[float, float] | None:
    """(max close, min close) over bars ``[index-lookback, index)``. No look-ahead."""
    if lookback <= 0 or index < lookback:
        return None
    window = candles[index - lookback : index]
    if len(window) < lookback:
        return None
    closes = [item.close for item in window]
    return max(closes), min(closes)


def lookback_state_series(
    candles: tuple[Candle, ...],
    lookback: int,
) -> tuple[tuple[datetime, bool, float | None], ...]:
    """Per-bar ``(opened_at, in_position, stop)`` for one lookback.

    Entry: close[t] > prior max close. Stop: channel midpoint at entry,
    then ``max(prior stop, current midpoint)``. Exit: close[t] < stop.
    An exit bar never re-enters; re-entry needs a later fresh breakout.
    """
    if lookback <= 0 or len(candles) < lookback + 1:
        return ()
    out: list[tuple[datetime, bool, float | None]] = []
    in_position = False
    stop: float | None = None
    closes = [item.close for item in candles]
    # Monotonic deques give the prior-window max/min in O(1) per bar so the
    # decision-time recompute in EnsembleTrendVoter stays cheap. The window
    # for bar ``index`` is ``[index-lookback, index)`` — bar index excluded —
    # exactly what prior_close_channel returns (asserted by tests).
    max_queue: deque[int] = deque()
    min_queue: deque[int] = deque()
    for position in range(lookback):
        _push_window(max_queue, min_queue, closes, position)
    for index in range(lookback, len(candles)):
        prior_max = closes[max_queue[0]]
        prior_min = closes[min_queue[0]]
        midpoint = (prior_max + prior_min) / 2.0
        close = closes[index]
        if in_position:
            stop = midpoint if stop is None else max(stop, midpoint)
            if close < stop:
                in_position = False
                stop = None
        elif close > prior_max:
            in_position = True
            stop = midpoint
        out.append((candles[index].opened_at, in_position, stop))
        # Slide the window forward: bar ``index`` enters, ``index-lookback`` leaves.
        _push_window(max_queue, min_queue, closes, index)
        if max_queue[0] <= index - lookback:
            max_queue.popleft()
        if min_queue[0] <= index - lookback:
            min_queue.popleft()
    return tuple(out)


def _push_window(
    max_queue: deque[int],
    min_queue: deque[int],
    closes: list[float],
    position: int,
) -> None:
    while max_queue and closes[max_queue[-1]] <= closes[position]:
        max_queue.pop()
    max_queue.append(position)
    while min_queue and closes[min_queue[-1]] >= closes[position]:
        min_queue.pop()
    min_queue.append(position)


def realised_vol_annualised(
    candles: tuple[Candle, ...],
    index: int,
    lookback: int = VOL_LOOKBACK,
) -> float | None:
    """Annualised std of the last ``lookback`` simple returns ending at ``index``.

    Uses closes through bar ``index`` (the decision is taken after
    close[t]). Needs ``lookback + 1`` closes; otherwise None (skip).
    """
    if lookback < 2 or index < lookback or index >= len(candles):
        return None
    window = candles[index - lookback : index + 1]
    returns = [
        simple_return(window[position - 1].close, window[position].close)
        for position in range(1, len(window))
    ]
    if len(returns) < lookback:
        return None
    return standard_deviation(returns) * sqrt(periods_per_year(candles[0].interval))


def _vol_scalar(vol: float | None, vol_target: float | None) -> float | None:
    if vol_target is None:
        return 1.0
    if vol is None:
        return None
    if vol <= 0.0:
        return MAX_LEVERAGE
    return min(vol_target / vol, MAX_LEVERAGE)


def ensemble_trend_series(
    candles: tuple[Candle, ...],
    *,
    lookbacks: tuple[int, ...] = ENSEMBLE_LOOKBACKS,
    vol_target: float | None = VOL_TARGET_ANNUAL,
    vol_lookback: int = VOL_LOOKBACK,
    min_open: int = 0,
) -> tuple[tuple[datetime, float, int], ...]:
    """Point-in-time ``(opened_at, weight, open_count)`` per bar.

    Starts once every lookback has a prior channel (and the vol window
    exists when a target is set). Weight is in ``[0, MAX_LEVERAGE]``.
    A bar without a realised-vol estimate is skipped, never zero-filled.
    When ``min_open > 0`` and ``open_count < min_open``, weight is forced
    to 0 (v2 consensus floor); ``min_open=0`` preserves #137 behaviour.
    """
    if not lookbacks or any(item <= 0 for item in lookbacks):
        return ()
    if min_open < 0:
        raise ValueError(f"min_open must be >= 0, got {min_open}")
    total = len(lookbacks)
    start = max(lookbacks)
    if vol_target is not None:
        start = max(start, vol_lookback)
    if len(candles) < start + 1:
        return ()
    states = {
        n: {ts: in_position for ts, in_position, _stop in lookback_state_series(candles, n)}
        for n in lookbacks
    }
    out: list[tuple[datetime, float, int]] = []
    for index in range(start, len(candles)):
        ts = candles[index].opened_at
        open_count = sum(1 for n in lookbacks if states[n].get(ts, False))
        scalar = _vol_scalar(
            realised_vol_annualised(candles, index, vol_lookback) if vol_target else None,
            vol_target,
        )
        if scalar is None:
            continue
        if min_open and open_count < min_open:
            weight = 0.0
        else:
            weight = (open_count / total) * scalar
        weight = max(0.0, min(weight, MAX_LEVERAGE))
        out.append((ts, weight, open_count))
    return tuple(out)


def _canonical(symbol: str) -> str:
    return ALIAS_TO_CANONICAL.get(symbol.upper(), symbol.upper())


def _month_start(moment: datetime) -> datetime:
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def universe_snapshots(
    histories: dict[str, tuple[Candle, ...]],
    *,
    min_listed_bars: int = UNIVERSE_MIN_LISTED_BARS,
    dollar_volume_bars: int = UNIVERSE_DOLLAR_VOLUME_BARS,
    min_median_dollar_volume: float = UNIVERSE_MEDIAN_DOLLAR_VOLUME_USD,
    top_k: int = UNIVERSE_TOP_K,
    cap_bars: int = KRAKEN_PUBLIC_OHLC_MAX_BARS,
) -> dict[datetime, frozenset[str]]:
    """Monthly point-in-time membership keyed by UTC month start.

    Uses only bars strictly before each month start. Keys are
    canonical symbols (``BTC/USD``). A month with no qualifier maps to
    an empty set (every name forced flat), never to an invented list.
    """
    by_symbol: dict[str, tuple[Candle, ...]] = {}
    for candles in histories.values():
        if not candles:
            continue
        by_symbol[_canonical(candles[0].symbol)] = tuple(
            sorted(candles, key=lambda item: item.opened_at)
        )
    if not by_symbol:
        return {}
    months: set[datetime] = set()
    for candles in by_symbol.values():
        for candle in candles:
            months.add(_month_start(candle.opened_at))
    snapshots: dict[datetime, frozenset[str]] = {}
    for month in sorted(months):
        ranked: list[tuple[float, str]] = []
        for symbol, candles in by_symbol.items():
            prior = [item for item in candles if item.opened_at < month]
            listed_long_enough = len(prior) >= min_listed_bars or len(candles) >= cap_bars
            if not listed_long_enough or len(prior) < dollar_volume_bars:
                continue
            recent = prior[-dollar_volume_bars:]
            median = _median([item.close * item.volume for item in recent])
            if median < min_median_dollar_volume:
                continue
            ranked.append((median, symbol))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        snapshots[month] = frozenset(symbol for _median_value, symbol in ranked[:top_k])
    return snapshots


def apply_membership(
    symbol: str,
    series: tuple[tuple[datetime, float, int], ...],
    snapshots: dict[datetime, frozenset[str]],
) -> tuple[tuple[datetime, float, int], ...]:
    """Force weight to 0 on bars whose month does not list ``symbol``."""
    canonical = _canonical(symbol)
    out: list[tuple[datetime, float, int]] = []
    for ts, weight, open_count in series:
        members = snapshots.get(_month_start(ts), frozenset())
        out.append((ts, weight if canonical in members else 0.0, open_count))
    return tuple(out)


def ensemble_attribution(
    histories: dict[str, tuple[Candle, ...]],
    *,
    lookbacks: tuple[int, ...] = ENSEMBLE_LOOKBACKS,
    vol_target: float | None = VOL_TARGET_ANNUAL,
    min_open: int = 0,
    snapshots: dict[datetime, frozenset[str]] | None = None,
) -> tuple[dict[str, float], dict[int, float]]:
    """Gross close-to-close contribution by asset and by lookback (informational).

    Per bar t the ensemble contributes ``weight[t] × (close[t+1]/close[t] − 1)``
    and lookback N contributes ``scalar[t] × member[t] × in_pos_N[t] / total
    × r[t+1]``; the lookback sums equal the ensemble sum per asset exactly.
    No fees, no slippage — legibility only, never a gate.
    """
    by_asset: dict[str, float] = {}
    by_lookback: dict[int, float] = {n: 0.0 for n in lookbacks}
    for candles in histories.values():
        if not candles:
            continue
        symbol = _canonical(candles[0].symbol)
        series = ensemble_trend_series(
            candles, lookbacks=lookbacks, vol_target=vol_target, min_open=min_open
        )
        if snapshots is not None:
            series = apply_membership(symbol, series, snapshots)
        if not series:
            continue
        index_by_ts = {candle.opened_at: position for position, candle in enumerate(candles)}
        states = {
            n: {ts: in_position for ts, in_position, _stop in lookback_state_series(candles, n)}
            for n in lookbacks
        }
        asset_sum = 0.0
        for ts, weight, open_count in series:
            position = index_by_ts[ts]
            if position + 1 >= len(candles):
                continue
            forward = simple_return(candles[position].close, candles[position + 1].close)
            asset_sum += weight * forward
            if open_count == 0 or weight == 0.0:
                continue
            per_open = weight / open_count
            for n in lookbacks:
                if states[n].get(ts, False):
                    by_lookback[n] += per_open * forward
        by_asset[symbol] = asset_sum
    return by_asset, by_lookback


@dataclass(frozen=True)
class EnsembleTrendVoter:
    """Look up (or recompute) the same-bar ensemble weight. Long-only."""

    strategy_id: str
    lookbacks: tuple[int, ...] = ENSEMBLE_LOOKBACKS
    vol_target: float | None = VOL_TARGET_ANNUAL
    min_open: int = 0
    signals_by_symbol: tuple[tuple[str, tuple[tuple[datetime, float, int], ...]], ...] = ()

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        cutoff = candles[-1].opened_at
        symbol = candles[-1].symbol
        registered = self.series_for(symbol)
        if registered:
            by_ts = {ts: (weight, count) for ts, weight, count in registered}
            found = by_ts.get(cutoff)
            source = "precomputed"
        else:
            computed = ensemble_trend_series(
                candles,
                lookbacks=self.lookbacks,
                vol_target=self.vol_target,
                min_open=self.min_open,
            )
            found = None
            if computed and computed[-1][0] == cutoff:
                found = (computed[-1][1], computed[-1][2])
            source = "decision-time recompute"
        if found is None:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="ensemble_trend: no same-bar assignment (warmup / skipped)",
            )
        weight, open_count = found
        weight = max(0.0, min(weight, MAX_LEVERAGE))
        side: Side | None = Side.BUY if weight > 0.0 else None
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=symbol,
            side=side,
            score=weight,
            confidence=weight,
            regime=regime,
            rationale=(
                f"ensemble_trend weight={weight:.3f} open={open_count}/"
                f"{len(self.lookbacks)} ({source}; long-only)"
            ),
        )

    def series_for(self, symbol: str) -> tuple[tuple[datetime, float, int], ...]:
        key = symbol.upper()
        for name, series in self.signals_by_symbol:
            if name == key:
                return series
        return ()


def _histories_by_canonical(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, tuple[Candle, ...]]:
    out: dict[str, tuple[Candle, ...]] = {}
    for candles in histories.values():
        if not candles:
            continue
        canonical = ALIAS_TO_CANONICAL.get(candles[0].symbol.upper())
        if canonical is None:
            continue
        out[canonical] = candles
    return out


def ensemble_trend_signals(
    histories: dict[str, tuple[Candle, ...]],
    *,
    lookbacks: tuple[int, ...],
    vol_target: float | None,
    min_open: int = 0,
    snapshots: dict[datetime, frozenset[str]] | None = None,
) -> dict[str, tuple[tuple[datetime, float, int], ...]]:
    """Per-gate-asset assignments under membership. Missing assets omitted."""
    by_canonical = _histories_by_canonical(histories)
    per_asset: dict[str, tuple[tuple[datetime, float, int], ...]] = {}
    for asset, candles in by_canonical.items():
        series = ensemble_trend_series(
            candles, lookbacks=lookbacks, vol_target=vol_target, min_open=min_open
        )
        if snapshots is not None:
            series = apply_membership(asset, series, snapshots)
        if series:
            per_asset[asset] = series
    if not per_asset:
        return {}
    mapping: dict[str, tuple[tuple[datetime, float, int], ...]] = {}
    for alias, canonical in ALIAS_TO_CANONICAL.items():
        if canonical in per_asset:
            mapping[alias] = per_asset[canonical]
    return mapping


def _control_candidate() -> SearchCandidate:
    return SearchCandidate(
        candidate_id=CONTROL_ID,
        family="control",
        label="always-on MA 10/30 (informational; cannot promote)",
        params={"short_window": 10, "long_window": 30, "strategy_id": CONTROL_ID},
        strategy=AlwaysOnTrendStrategy(
            strategy_id=CONTROL_ID,
            short_window=10,
            long_window=30,
        ),
    )


def _book_label(
    *,
    lookbacks: tuple[int, ...],
    vol_target: float | None,
    min_open: int = 0,
) -> str:
    sizing = f"{vol_target:.0%} vol target (90d)" if vol_target is not None else "unit weight"
    consensus = f", min_open={min_open}" if min_open else ""
    return (
        f"long-only ensemble Donchian-on-close {{{','.join(str(n) for n in lookbacks)}}} "
        f"+ trailing midpoint stop × {sizing}{consensus}"
    )


def ensemble_trend_candidates(
    histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    include_control: bool = True,
    snapshots: dict[datetime, frozenset[str]] | None = None,
    catalog: tuple[tuple[str, tuple[int, ...], float | None, int], ...] | None = None,
) -> tuple[SearchCandidate, ...]:
    """Instantiate a frozen catalog. Missing / short series → that name omitted."""
    out: list[SearchCandidate] = []
    source = histories or {}
    if snapshots is None:
        snapshots = universe_snapshots(source)
    active = catalog if catalog is not None else ENSEMBLE_CATALOG
    for candidate_id, lookbacks, vol_target, min_open in active:
        mapping = ensemble_trend_signals(
            source,
            lookbacks=lookbacks,
            vol_target=vol_target,
            min_open=min_open,
            snapshots=snapshots,
        )
        if not mapping:
            continue
        by_symbol = tuple((key.upper(), values) for key, values in sorted(mapping.items()))
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family="ensemble_trend",
                label=_book_label(lookbacks=lookbacks, vol_target=vol_target, min_open=min_open),
                params={
                    "lookbacks": list(lookbacks),
                    "vol_target_annual": vol_target,
                    "vol_lookback": VOL_LOOKBACK if vol_target is not None else None,
                    "min_open": min_open,
                    "max_leverage": MAX_LEVERAGE,
                    "entry_rule": ENTRY_RULE,
                    "stop_rule": STOP_RULE,
                    "universe_top_k": UNIVERSE_TOP_K,
                    "strategy_id": candidate_id,
                    "multi_asset_gate": MULTI_ASSET_GATE_RULE,
                },
                strategy=EnsembleTrendVoter(
                    strategy_id=candidate_id,
                    lookbacks=lookbacks,
                    vol_target=vol_target,
                    min_open=min_open,
                    signals_by_symbol=by_symbol,
                ),
                # --- ensemble trend (#137 / v2): fractional long-only weight ---
                weight_from_score=True,
            )
        )
    if include_control:
        out.append(_control_candidate())
    return tuple(out)


def skipped_ensemble_families(
    histories: dict[str, tuple[Candle, ...]],
    *,
    snapshots: dict[datetime, frozenset[str]] | None = None,
    catalog: tuple[tuple[str, tuple[int, ...], float | None, int], ...] | None = None,
) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    if snapshots is None:
        snapshots = universe_snapshots(histories)
    active = catalog if catalog is not None else ENSEMBLE_CATALOG
    for candidate_id, lookbacks, vol_target, min_open in active:
        mapping = ensemble_trend_signals(
            histories,
            lookbacks=lookbacks,
            vol_target=vol_target,
            min_open=min_open,
            snapshots=snapshots,
        )
        if mapping:
            continue
        need = max(lookbacks) + 1
        if vol_target is not None:
            need = max(need, VOL_LOOKBACK + 1)
        skipped.append(
            {
                "family": "ensemble_trend",
                "candidate_id": candidate_id,
                "reason": (
                    f"{_book_label(lookbacks=lookbacks, vol_target=vol_target, min_open=min_open)}"
                    f": skipped — need venue-local daily closes with at least {need} bars"
                    " (warmup-limited on the 720-bar cap). Skip rather than invent "
                    "or zero-fill closes."
                ),
            }
        )
    return skipped


def rank_ensemble_passers(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Frozen ranking key among ensemble dual-print passers. Control excluded."""
    eligible = [row for row in rows if row.candidate_id not in CONTROL_IDS]
    return rank_dual_print_passers(eligible)


def eth_carried_informational(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Positive mean HO with a losing BTC holdout — #96 FAIL, not an edge."""
    flagged: list[DualPrintRow] = []
    for row in rows:
        if row.candidate_id in CONTROL_IDS:
            continue
        mean_ho = row.kraken_mean_holdout_excess
        btc_ho = row.kraken_btc_holdout
        if mean_ho is None or btc_ho is None:
            continue
        if mean_ho > 0 and btc_ho <= 0:
            flagged.append(row)
    return flagged


class UniverseSummary(BaseModel):
    candidate_universe: list[str]
    pulled_symbols: list[str] = Field(default_factory=list)
    skipped_symbols: list[str] = Field(default_factory=list)
    min_listed_bars: int = UNIVERSE_MIN_LISTED_BARS
    dollar_volume_bars: int = UNIVERSE_DOLLAR_VOLUME_BARS
    min_median_dollar_volume_usd: float = UNIVERSE_MEDIAN_DOLLAR_VOLUME_USD
    top_k: int = UNIVERSE_TOP_K
    member_count_by_month: dict[str, int] = Field(default_factory=dict)
    members_last: list[str] = Field(default_factory=list)
    snapshot_note: str = UNIVERSE_SNAPSHOT_NOTE
    survivorship_note: str = SURVIVORSHIP_NOTE


class EnsembleTrendReport(BaseModel):
    generated_at: datetime
    ranking_key: str
    selection_rule: str
    multi_asset_gate_rule: str
    catalog_k_core: int
    catalog_k_scored: int
    catalog_ids: list[str]
    catalog_note: str
    fee_bps: float
    slippage_bps: float
    kraken_tier: int | None = None
    fee_source: str
    train_size: int
    test_size: int
    step_size: int
    holdout_fraction: float
    min_trades: int
    primary_first: str
    primary_first_source: str
    primary_last: str | None = None
    primary_bars: int | None = None
    primary_bars_eth: int | None = None
    primary_bars_sol: int | None = None
    binance_slice: SliceMeta
    binance_source: str | None = None
    universe: UniverseSummary
    era_prints_available: bool = ERA_PRINTS_AVAILABLE
    dsr_pbo_available: bool = DSR_PBO_AVAILABLE
    attribution_by_asset: dict[str, dict[str, float]] = Field(default_factory=dict)
    attribution_by_lookback: dict[str, dict[str, float]] = Field(default_factory=dict)
    paper_path_ready: bool = True
    multi_venue_bar_preregistered: bool = True
    can_average_venues: bool = False
    can_enter_promotion_average: bool = False
    keep_flag_false: bool = True
    rows: list[DualPrintRow] = Field(default_factory=list)
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    kraken_combined_passer_ids: list[str] = Field(default_factory=list)
    binance_combined_passer_ids: list[str] = Field(default_factory=list)
    eth_carried_ids: list[str] = Field(default_factory=list)
    skipped_feature_families: list[dict[str, str]] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    recommended_promote_flag: str | None = None
    any_dual_print_passer: bool = False
    honesty: str
    recommendation: str
    rules: str = ENSEMBLE_RULES
    gates_note: str = HARDER_GATES_NOTE
    fee_note: str = BINANCE_TAKER_BPS_NOTE
    kraken_cap_note: str = KRAKEN_DAILY_CAP_NOTE
    warmup_note: str = WARMUP_NOTE
    paper_path_note: str = PAPER_EXECUTABLE_PATH_NOTE
    data_notes: list[str] = Field(default_factory=list)


def _recommendation(
    *,
    selected_id: str | None,
    dual_ids: list[str],
    kraken_ids: list[str],
    binance_meta: SliceMeta,
    eth_carried: list[str],
) -> str:
    lines = [
        (
            "**Keep every `PAPER_PROMOTE_*=false`.** This search does not "
            "flip a pin and does not enable live. An empty dual-print set "
            "is the successful outcome."
        ),
        "",
        (
            f"- Dual-print passers: {len(dual_ids)}"
            + (f" (`{'`, `'.join(dual_ids)}`)" if dual_ids else " (none)")
            + "."
        ),
        (
            f"- Kraken combined-passers (informational; control excluded "
            f"from ranking): {len(kraken_ids)}"
            + (f" (`{'`, `'.join(kraken_ids)}`)" if kraken_ids else "")
            + ". A Kraken-only passer cannot promote."
        ),
        (
            f"- Binance.US `{BINANCE_SLICE_RULE}`: "
            f"{'scored' if binance_meta.available else 'FAIL-CLOSED'} "
            f"({binance_meta.venue}; {binance_meta.bars_btc} BTC / "
            f"{binance_meta.bars_eth} ETH / {binance_meta.bars_sol} SOL; "
            f"{binance_meta.first} → {binance_meta.last})."
        ),
        (f"- Multi-asset gate: `{MULTI_ASSET_GATE_RULE}` (SOL reported, not required)."),
        (
            f"- Era prints: era_prints_available={str(ERA_PRINTS_AVAILABLE).lower()} "
            f"(#133 pending); DSR / PBO: dsr_pbo_available="
            f"{str(DSR_PBO_AVAILABLE).lower()} (#135 pending). Re-run and "
            "re-commit when they land; nothing here is invented."
        ),
        (
            f"- Paper path: ready on Kraken spot BTC/ETH "
            f"(SOL optional; PAPER_PATH_READY={str(PAPER_PATH_READY).lower()}); "
            "long-only, score in [0, 1], RiskEngine can only reduce."
        ),
    ]
    if eth_carried:
        lines.append(
            "- #96 FAIL (ETH-carried informational mean HO; BTC holdout "
            f"≤ 0): {', '.join(f'`{item}`' for item in eth_carried)}. "
            "A positive mean with a losing BTC holdout is not an edge."
        )
    if selected_id is None:
        lines.append(
            "- Dual-print top-1: **none**. Do not add a new promote flag. "
            "Leave every existing `PAPER_PROMOTE_*` false."
        )
    else:
        flag = paper_promote_flag_name(selected_id)
        lines.append(
            f"- Dual-print top-1: `{selected_id}` by `{RANKING_KEY}`. "
            f"Documented paper-only name would be `{flag}` "
            "(default **false** if added, in its own PR). This run does not add or flip it."
        )
    lines.append(
        "- Do not enable live. Do not fabricate PnL. Do not widen "
        "RISK_MAX_OPEN_POSITIONS, MVP_ASSETS or PAPER_PROMOTE_UNIVERSE "
        "for a 20-name book (see docs/EXECUTION-ARCHITECTURE.md)."
    )
    return "\n".join(lines)


def _universe_summary(
    histories: dict[str, tuple[Candle, ...]],
    snapshots: dict[datetime, frozenset[str]],
    *,
    skipped_symbols: list[str],
) -> UniverseSummary:
    pulled = sorted({_canonical(c[0].symbol) for c in histories.values() if c})
    months = sorted(snapshots)
    return UniverseSummary(
        candidate_universe=list(CANDIDATE_UNIVERSE),
        pulled_symbols=pulled,
        skipped_symbols=sorted(skipped_symbols),
        member_count_by_month={m.date().isoformat(): len(snapshots[m]) for m in months},
        members_last=sorted(snapshots[months[-1]]) if months else [],
    )


def _concurrent_slice_meta(
    *,
    raw_second: dict[str, tuple[Candle, ...]],
    scored: dict[str, tuple[Candle, ...]],
    venue_source: str | None,
    min_bars: int = 365,
) -> SliceMeta:
    """Same-window second venue (Coinbase): overlap with primary is allowed."""
    score_btc = scored.get("BTC/USD@1d")
    score_eth = scored.get("ETH/USD@1d")
    score_sol = scored.get("SOL/USD@1d")
    short = (
        score_btc is None
        or score_eth is None
        or len(score_btc) < min_bars
        or len(score_eth) < min_bars
    )
    first = score_btc[0].opened_at.isoformat() if score_btc else None
    last = score_btc[-1].opened_at.isoformat() if score_btc else None
    if not raw_second:
        reason = "second venue daily missing or failed (empty print is success)"
    elif short:
        reason = (
            f"second venue shorter than {min_bars} committed bars "
            f"(BTC={len(score_btc or ())}, ETH={len(score_eth or ())}); fail closed"
        )
    else:
        reason = None
    return SliceMeta(
        rule=SECOND_PRINT_CONCURRENT,
        venue=venue_source or "coinbase",
        available=reason is None and not short,
        bars_btc=len(score_btc or ()),
        bars_eth=len(score_eth or ()),
        bars_sol=len(score_sol or ()),
        first=first,
        last=last,
        overlaps_primary_window=True,
        overlaps_primary_holdout=False,
        fail_closed_reason=reason,
    )


def run_ensemble_trend_search(
    kraken_histories: dict[str, tuple[Candle, ...]],
    binance_histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    candidates: tuple[SearchCandidate, ...] | None = None,
    binance_source: str | None = None,
    kraken_tier: int | None = None,
    fee_source: str = "explicit",
    universe_skipped: list[str] | None = None,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
    catalog_name: str = "default",
    second_print_mode: str | None = None,
) -> EnsembleTrendReport:
    """Score a frozen catalog on both prints. ``kraken_histories`` may hold
    the whole candidate universe; only BTC/ETH/SOL are harness-scored, the
    rest feed the point-in-time membership snapshot.

    ``catalog_name`` selects ``default`` (#137) or ``v2`` (consensus).
    ``second_print_mode`` defaults to older-720 for default catalog and
    concurrent Coinbase harder-gates for v2.
    """
    generated = now or datetime.now(UTC)
    active_spec = resolve_catalog(catalog_name)
    note = catalog_note_for(catalog_name)
    core_ids = catalog_core_ids(catalog_name)
    mode = second_print_mode or (
        SECOND_PRINT_CONCURRENT if catalog_name == "v2" else SECOND_PRINT_OLDER_720
    )

    kraken = _score_symbols_only(kraken_histories)
    if not kraken:
        raise ValueError("no Kraken BTC/ETH/SOL daily histories provided")
    primary_first, primary_source = primary_first_opened_at(kraken)
    btc = kraken_daily_candles(kraken, "BTC/USD")
    eth = kraken_daily_candles(kraken, "ETH/USD")
    sol = kraken_daily_candles(kraken, "SOL/USD")
    primary_last = btc[-1].opened_at.isoformat() if btc else None
    primary_bars = len(btc) if btc else None

    snapshots = universe_snapshots(kraken_histories)
    catalog = (
        candidates
        if candidates is not None
        else ensemble_trend_candidates(kraken_histories, snapshots=snapshots, catalog=active_spec)
    )
    skipped = skipped_ensemble_families(kraken_histories, snapshots=snapshots, catalog=active_spec)

    raw_second = binance_histories or {}
    if mode == SECOND_PRINT_CONCURRENT:
        # Concurrent venue (Coinbase): score USD symbols directly; overlap OK.
        remapped = _score_symbols_only(raw_second)
        if not remapped and raw_second:
            remapped = _score_symbols_only(remap_binance_for_scoring(raw_second))
        binance_meta = _concurrent_slice_meta(
            raw_second=raw_second,
            scored=remapped,
            venue_source=binance_source or "coinbase",
        )
    else:
        sliced_binance = {
            key: slice_ending_before(candles, before=primary_first)
            for key, candles in raw_second.items()
        }
        remapped = _score_symbols_only(remap_binance_for_scoring(sliced_binance))
        binance_meta = _binance_slice_meta(
            raw_binance=raw_second,
            remapped=remapped,
            primary_first=primary_first,
            binance_source=binance_source,
        )

    kraken_report = _score(
        kraken,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=catalog,
        now=generated,
    )
    kraken_by_id = {row.candidate_id: row for row in kraken_report.candidates}

    binance_by_id: dict[str, CandidateHarderResult] = {}
    if binance_meta.available:
        if candidates is not None:
            binance_catalog = candidates
        else:
            # Membership on the second print is computed from the scored
            # second-venue series only; BTC/ETH/SOL see the same rule.
            binance_catalog = ensemble_trend_candidates(remapped, catalog=active_spec)
        binance_report = _score(
            remapped,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
            holdout_fraction=holdout_fraction,
            min_trades=min_trades,
            candidates=binance_catalog,
            now=generated,
        )
        binance_by_id = {row.candidate_id: row for row in binance_report.candidates}

    rows = [
        _merge_row(
            candidate,
            kraken_by_id.get(candidate.candidate_id),
            binance_by_id.get(candidate.candidate_id),
        )
        for candidate in catalog
    ]
    passers = rank_ensemble_passers(rows)
    selected = passers[0] if passers else None
    dual_ids = [row.candidate_id for row in passers]
    kraken_ids = [
        row.candidate_id
        for row in sorted(
            (
                item
                for item in rows
                if item.kraken_combined and item.candidate_id not in CONTROL_IDS
            ),
            key=lambda item: (
                item.kraken_combined_rank if item.kraken_combined_rank is not None else 10**9,
                item.candidate_id,
            ),
        )
    ]
    binance_ids = [
        row.candidate_id
        for row in rows
        if row.binance_combined and row.candidate_id not in CONTROL_IDS
    ]
    eth_carried = eth_carried_informational(rows)
    eth_carried_ids = [row.candidate_id for row in eth_carried]
    recommended = paper_promote_flag_name(selected.candidate_id) if selected is not None else None

    attribution_by_asset: dict[str, dict[str, float]] = {}
    attribution_by_lookback: dict[str, dict[str, float]] = {}
    gate_histories = _histories_by_canonical(kraken)
    for candidate_id, lookbacks, vol_target, min_open in active_spec:
        by_asset, by_lookback = ensemble_attribution(
            gate_histories,
            lookbacks=lookbacks,
            vol_target=vol_target,
            min_open=min_open,
            snapshots=snapshots,
        )
        attribution_by_asset[candidate_id] = by_asset
        attribution_by_lookback[candidate_id] = {str(n): v for n, v in by_lookback.items()}

    honesty = (
        ENSEMBLE_RULES
        + " "
        + note
        + f" catalog_name={catalog_name}; second_print_mode={mode}."
        + f" This run scored K={len(catalog)} (core ids frozen at "
        f"{len(core_ids)}). Fees: {fee_bps:g} bps ({fee_source}"
        + (f", Kraken Pro tier {kraken_tier}" if kraken_tier is not None else "")
        + f") + slippage {slippage_bps:g} bps. "
        f"Kraken combined-passers (ex-control): {len(kraken_ids)}. "
        f"Binance combined-passers (ex-control): {len(binance_ids)}. "
        f"Dual-print passers: {len(dual_ids)}."
    )
    if eth_carried_ids:
        honesty += (
            " Informational #96 FAIL (ETH-carried mean HO): "
            + ", ".join(f"`{item}`" for item in eth_carried_ids)
            + "."
        )
    if selected is None:
        honesty += (
            " No dual-print passer. Leave every PAPER_PROMOTE_* false. "
            "Do not add a new promote flag."
        )
    else:
        honesty += (
            f" Dual-print top-1 is `{selected.candidate_id}` by "
            f"{RANKING_KEY}. Document a paper-only pin only; default "
            "false; do not enable live."
        )

    notes = list(data_notes or [])
    if not btc or not eth:
        notes.append(
            "BTC and/or ETH daily series missing on Kraken. Combined "
            "gates cannot pass. Skip-not-invent; do not zero-fill."
        )
    if sol:
        notes.append(f"SOL/USD present ({len(sol)} bars); reported, not a gate.")
    else:
        notes.append("SOL/USD absent; reported as n/a, not invented.")

    return EnsembleTrendReport(
        generated_at=generated,
        ranking_key=RANKING_KEY,
        selection_rule=SELECTION_RULE,
        multi_asset_gate_rule=MULTI_ASSET_GATE_RULE,
        catalog_k_core=len(core_ids),
        catalog_k_scored=len(catalog),
        catalog_ids=[item.candidate_id for item in catalog],
        catalog_note=note,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        kraken_tier=kraken_tier,
        fee_source=fee_source,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        primary_first=primary_first.isoformat(),
        primary_first_source=primary_source,
        primary_last=primary_last,
        primary_bars=primary_bars,
        primary_bars_eth=len(eth) if eth else None,
        primary_bars_sol=len(sol) if sol else None,
        binance_slice=binance_meta,
        binance_source=binance_source,
        universe=_universe_summary(
            kraken_histories, snapshots, skipped_symbols=list(universe_skipped or [])
        ),
        era_prints_available=ERA_PRINTS_AVAILABLE,
        dsr_pbo_available=DSR_PBO_AVAILABLE,
        attribution_by_asset=attribution_by_asset,
        attribution_by_lookback=attribution_by_lookback,
        paper_path_ready=PAPER_PATH_READY,
        multi_venue_bar_preregistered=MULTI_VENUE_BAR_PREREGISTERED,
        can_average_venues=CAN_AVERAGE_VENUES,
        can_enter_promotion_average=CAN_ENTER_PROMOTION_AVERAGE,
        keep_flag_false=True,
        rows=rows,
        dual_print_passer_ids=dual_ids,
        kraken_combined_passer_ids=kraken_ids,
        binance_combined_passer_ids=binance_ids,
        eth_carried_ids=eth_carried_ids,
        skipped_feature_families=skipped,
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        recommended_promote_flag=recommended,
        any_dual_print_passer=bool(dual_ids),
        honesty=honesty,
        recommendation=_recommendation(
            selected_id=selected.candidate_id if selected is not None else None,
            dual_ids=dual_ids,
            kraken_ids=kraken_ids,
            binance_meta=binance_meta,
            eth_carried=eth_carried_ids,
        ),
        data_notes=notes,
    )


def _attribution_lines(report: EnsembleTrendReport) -> list[str]:
    lines: list[str] = [
        "## Attribution (gross close-to-close; informational, not a gate)",
        "",
        (
            "Per bar the ensemble contributes weight[t] × (close[t+1]/close[t] − 1); "
            "each lookback's share is its open fraction of that weight. No fees or "
            "slippage. The lookback columns sum to the asset total for each book."
        ),
        "",
        "| book | asset | gross contribution |",
        "| --- | --- | ---: |",
    ]
    for book, by_asset in report.attribution_by_asset.items():
        if not by_asset:
            lines.append(f"| `{book}` | — | n/a (skipped) |")
        for asset in sorted(by_asset):
            lines.append(f"| `{book}` | {asset} | {_pct(by_asset[asset])} |")
    lines.extend(["", "| book | lookback | gross contribution |", "| --- | ---: | ---: |"])
    for book, by_lookback in report.attribution_by_lookback.items():
        for lookback in sorted(by_lookback, key=int):
            lines.append(f"| `{book}` | {lookback} | {_pct(by_lookback[lookback])} |")
    return lines


def render_ensemble_trend_markdown(report: EnsembleTrendReport) -> str:
    dual_rows = [
        row for row in report.rows if row.dual_print and row.candidate_id not in CONTROL_IDS
    ]
    dual_rows.sort(key=lambda row: row.dual_print_rank or 10**9)
    kraken_rows = [
        row for row in report.rows if row.kraken_combined and row.candidate_id not in CONTROL_IDS
    ]
    kraken_rows.sort(key=lambda row: row.kraken_combined_rank or 10**9)
    binance_rows = [
        row for row in report.rows if row.binance_combined and row.candidate_id not in CONTROL_IDS
    ]
    binance_rows.sort(key=lambda row: row.candidate_id)
    universe = report.universe
    tier_text = (
        f"Kraken Pro tier {report.kraken_tier} taker"
        if report.kraken_tier is not None
        else "explicit --fee-bps"
    )
    lines: list[str] = [
        "# Ensemble trend dual-print (#137; BTC+ETH gate; SOL reported; top-20 PIT universe)",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Catalog K scored={report.catalog_k_scored} "
            f"(frozen core={report.catalog_k_core}; "
            f"ranking_key=`{report.ranking_key}`)."
        ),
        (
            f"Costs: fee={report.fee_bps:g} bps per side ({tier_text}; "
            f"source=`{report.fee_source}`) + slippage={report.slippage_bps:g} bps. "
            f"Walk-forward: train={report.train_size} test={report.test_size} "
            f"step={report.step_size}; holdout_fraction={report.holdout_fraction:.0%}."
        ),
        (
            f"Primary Kraken first bar: {report.primary_first} "
            f"(source=`{report.primary_first_source}`; last="
            f"{report.primary_last or 'n/a'}; bars BTC="
            f"{report.primary_bars or 'n/a'} / ETH="
            f"{report.primary_bars_eth or 'n/a'} / SOL="
            f"{report.primary_bars_sol or 'n/a'})."
        ),
        (
            f"`era_prints_available={str(report.era_prints_available).lower()}` (#133 pending); "
            f"`dsr_pbo_available={str(report.dsr_pbo_available).lower()}` (#135 pending); "
            f"`multi_asset_gate_rule={report.multi_asset_gate_rule}`; "
            f"`multi_venue_bar_preregistered="
            f"{str(report.multi_venue_bar_preregistered).lower()}`; "
            f"`can_average_venues={str(report.can_average_venues).lower()}`; "
            f"`paper_path_ready={str(report.paper_path_ready).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        (
            f"Universe: {len(universe.candidate_universe)} frozen candidates, "
            f"{len(universe.pulled_symbols)} pulled, "
            f"{len(universe.skipped_symbols)} skipped; membership top-{universe.top_k} "
            f"by median {universe.dollar_volume_bars}-bar close×volume ≥ "
            f"${universe.min_median_dollar_volume_usd:,.0f} with ≥ "
            f"{universe.min_listed_bars} prior bars; last snapshot "
            f"{len(universe.members_last)} members."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.honesty,
        "",
        "## Universe snapshot policy (frozen before scoring)",
        "",
        universe.snapshot_note,
        "",
        universe.survivorship_note,
        "",
        "Frozen candidate universe: " + ", ".join(f"`{s}`" for s in universe.candidate_universe),
        "",
        (
            "Pulled: "
            + (", ".join(f"`{s}`" for s in universe.pulled_symbols) or "none")
            + ". Skipped (not invented): "
            + (", ".join(f"`{s}`" for s in universe.skipped_symbols) or "none")
            + "."
        ),
        "",
        "| month | members |",
        "| --- | ---: |",
    ]
    if universe.member_count_by_month:
        for month, count in universe.member_count_by_month.items():
            lines.append(f"| {month} | {count} |")
    else:
        lines.append("| — | 0 |")
    lines.extend(
        [
            "",
            "Last snapshot members: "
            + (", ".join(f"`{s}`" for s in universe.members_last) or "none")
            + ".",
            "",
            "## Fee tier (frozen)",
            "",
            "| Kraken Pro tier | maker bps | taker bps |",
            "| ---: | ---: | ---: |",
        ]
    )
    for tier in sorted(KRAKEN_PRO_TIERS):
        maker, taker = KRAKEN_PRO_TIERS[tier]
        marker = " (default)" if tier == DEFAULT_KRAKEN_TIER else ""
        lines.append(f"| {tier}{marker} | {maker:g} | {taker:g} |")
    lines.extend(
        [
            "",
            (
                "The taker leg is charged per side by the shared harness on full "
                "equity at every rebalance (fractional weights are cost-overstated; "
                "conservative). Gate C doubles fee and slippage. Post-only maker "
                "realism is #138."
            ),
            "",
            "## Dual-print bar (frozen before scoring)",
            "",
            report.rules,
            "",
            "| print | rule | can enter ranking average? |",
            "| --- | --- | --- |",
            (
                "| Kraken primary 720 | public Spot daily, 720-bar cap; "
                f"#96+A+B+C on BTC+ETH (SOL reported); rank among "
                f"dual-print passers by `{report.ranking_key}` "
                "| **Kraken mean HO only** |"
            ),
            (
                "| Binance.US older 720 | same #102 definition: 720 committed "
                "daily BTC+ETH bars ending before the primary Kraken first "
                "bar; SOL optional report-only; must combined-PASS "
                "| **no** (gate only; not averaged) |"
            ),
            (
                f"| Kraken-only combined ranking (`{KRAKEN_COMBINED_RANKING_KEY}`) "
                "| informational | no |"
            ),
            (
                "| Era prints 2016-19 / 2020-22 / 2022-24 / 2024-26 (#133) + DSR / PBO (#135) "
                "| **unavailable in this run** — not scored, not invented | n/a |"
            ),
            "",
            "## Multi-asset gate (frozen)",
            "",
            (
                f"`{report.multi_asset_gate_rule}`: require BTC and ETH "
                "walk-forward total > 0 and holdout excess > 0, plus A/B/C, "
                "exactly as #96+#104. SOL walk-forward and holdout are "
                "printed in the tables when the series exists and **do not** "
                "gate. Equal-weight portfolio metrics were considered and "
                "**rejected** before scoring. The 20-name book is a research "
                "construct: the paper path still cycles only "
                "`Settings.effective_cycle_symbols` under `RISK_MAX_OPEN_POSITIONS`."
            ),
            "",
            "## Treatment (frozen)",
            "",
            (
                "For each lookback N the position opens long when close[t] > max "
                "close of bars `[t-N, t)`; the stop starts at the prior close-channel "
                "midpoint and ratchets to max(prior stop, current midpoint); exit "
                "when close[t] < stop; re-entry needs a fresh breakout. Weight = "
                "open fraction × min(0.25 / 90-bar annualised realised vol, 1). "
                "Long-only, capped at 1.0 (no leverage). Decision at close[t]; "
                "fill at t+1 open. A missing series is skipped, never zero-filled."
            ),
            "",
            report.warmup_note,
            "",
            "## Pre-registered catalog",
            "",
            report.catalog_note,
            "",
            ("Frozen core ids: " + ", ".join(f"`{item}`" for item in CORE_IDS) + "."),
            "",
            "## Paper path",
            "",
            report.paper_path_note,
            "",
            "## Kraken public OHLC cap",
            "",
            report.kraken_cap_note,
            "",
        ]
    )
    if report.data_notes:
        lines.extend(["## Data", ""])
        for note in report.data_notes:
            lines.append(f"- {note}")
        lines.append("")
    if report.skipped_feature_families:
        lines.extend(["## Skipped (not invented)", ""])
        for item in report.skipped_feature_families:
            lines.append(f"- `{item['candidate_id']}`: {item['reason']}")
        lines.append("")

    lines.extend(
        [
            "## Binance.US second print (required gate)",
            "",
            report.fee_note,
            "",
        ]
    )
    lines.extend(_slice_lines(report.binance_slice))
    lines.extend(
        [
            "",
            (
                "`api.binance.com` is HTTP 451 from this environment; "
                "`api.binance.us` is labeled **Binance.US**, not Binance.com. "
                "A short or overlapping BTC/ETH series fails closed. Empty "
                "Binance means zero dual-print passers (success). Missing "
                "SOL on Binance is report-only (not a gate)."
            ),
            "",
            "## Dual-print passers (promotion ranking)",
            "",
            (
                f"Frozen ranking key: `{report.ranking_key}`. Only ensemble "
                "names that already clear combined on **both** prints "
                f"appear here. `{CONTROL_ID}` is excluded. Empty table = "
                "no promotee (success). A new Settings pin is added only "
                "in a separate PR, default false."
            ),
            "",
        ]
    )
    lines.extend(_passer_table(dual_rows, venue="kraken"))
    lines.extend(
        [
            "",
            "## Kraken combined-passers (informational)",
            "",
        ]
    )
    lines.extend(_passer_table(kraken_rows, venue="kraken"))
    lines.extend(
        [
            "",
            "## Binance.US combined-passers (informational)",
            "",
        ]
    )
    lines.extend(_passer_table(binance_rows, venue="binance"))
    lines.extend(["", "## All rows (both prints)", ""])
    lines.extend(_passer_table(list(report.rows), venue="kraken"))
    lines.extend(["", "Binance side:", ""])
    lines.extend(_passer_table(list(report.rows), venue="binance"))
    lines.append("")
    lines.extend(_attribution_lines(report))
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            report.recommendation,
            "",
            "## Gates",
            "",
            report.gates_note,
            "",
        ]
    )
    return "\n".join(lines)


def ensemble_trend_paper_voter() -> EnsembleTrendVoter:
    """The pre-registered nine-lookback book, recomputed at decision time."""
    return EnsembleTrendVoter(strategy_id="ens_trend_9lb_vt25")


def build_ensemble_trend_paper_ensemble() -> StrategyEnsemble:
    """Sole paper voter: `ens_trend_9lb_vt25`. Not wired into cli.py by #137.

    A future flag PR (default false) may register it; the voter is
    long-only, its score is in [0, 1], and RiskEngine still sizes from
    Settings.
    """
    return StrategyEnsemble(
        extra_voters=(ensemble_trend_paper_voter(),),
        min_agreeing=1,
        suppress_defaults=True,
    )
