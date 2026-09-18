"""Long-only top-k cross-sectional momentum on a wide Kraken USD universe (#140).

Pre-registered before any live pull (do not retune after seeing PnL).

This is a **new family with a new portfolio bar**, not an edit of #117.
The #117 module scores each asset separately through the per-asset
#96+A+B+C harder gates and cannot express a basket equity curve; its
own rules text rejected equal-weight portfolio metrics for that bar.
Here the unit of evaluation is the **basket**.

Treatment (frozen):

- Universe: the point-in-time Kraken USD spot universe from
  ``research.universe`` — a frozen dated listing, then monthly top-20
  by trailing 30-day median dollar volume using only bars strictly
  before each snapshot date.
- Score on each **Monday UTC** close ``t``: ``close[t-7] /
  close[t-7-N] - 1`` for ``N in {21, 63, 126}`` (a one-week skip).
  A name missing either close, or with fewer than ``N + 8`` bars
  through ``t``, is skipped for that rebalance — never zero-filled.
- Fewer than ``MIN_CROSS_SECTION = 10`` rankable names -> the week is
  flat and counted, never ranked on a thin subset.
- Long the top ``k in {3, 5}``; weights equal (``ew``) or inverse
  trailing-30-day sample volatility (``iv``), normalised to 1.
  Long-only, no leverage, no shorts.
- Decision on close ``t``; fill at the next bar's open. Positions
  drift between rebalances. One-way turnover and fee drag are
  reported at the research cost (10 + 5 bps) and at the frozen
  pilot-tier taker cost (Kraken Pro tier 1, 80 bps + 5 bps slippage).
- Control ``ew_bh_universe``: equal weight of the same monthly
  snapshot names, refreshed at each snapshot, otherwise buy-and-hold.
  It is scored on every print and **cannot** enter the passer set.

Portfolio bar (frozen, at the pilot-tier cost): in **every covered
era** the basket's net total return > 0, net Sharpe > 0 and net
excess over ``ew_bh_universe`` > 0, and the print's last-20% holdout
net excess over the control > 0. A family that only works in one era
fails. A cell (venue × era) is covered when the print has at least
``MIN_ERA_BARS`` daily bars inside the era; uncovered cells are
skipped, not failed.

Dual print: a candidate is a **dual-print passer** only when at least
two independent covered cells (distinct venues or non-overlapping
eras) pass and no covered cell or holdout fails. One venue over one
era therefore cannot promote by construction.

Ranking key (frozen): ``mean_era_excess_vs_ew_bh_among_dual_print_passers``
— mean pilot-cost net excess over the control across covered cells,
among names that already dual-printed. Tie-break: ``candidate_id``.

Deflated Sharpe and PBO are **not computed** here; they land with the
shared era-print policy (#135) and are printed as
``not_computed_pending_135``. ``ERAS`` is a local constant until then.

RiskEngine layering is documented, not widened: ``max(TOPK_KS) = 5``
equals the ``MAX_OPEN_POSITIONS`` default, ``5 × MAX_POSITION_PCT
(0.10) = 0.50`` sits under ``MAX_GROSS_EXPOSURE_PCT (0.60)``, and the
runtime allowlist (``MVP_ASSETS``, ``PAPER_PROMOTE_UNIVERSE``) is
unchanged. ``paper_path_ready`` means candle-only long/flat signals
bookable by ``paper_simulate_fills`` on Kraken spot — not that the
runtime cycles twenty names. No Settings field, no ``PAPER_PROMOTE_*``
flip, an empty passer set is success. No live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from math import sqrt

from pydantic import BaseModel, Field

from traderstack.backtest import _mean, _sharpe, _sortino, _std
from traderstack.candles import Candle, periods_per_year
from traderstack.models import Side
from traderstack.research.daily_robustness import KRAKEN_DAILY_CAP_NOTE
from traderstack.research.harder_gates import _pct, _ratio, _verdict, paper_promote_flag_name
from traderstack.research.universe import (
    EXCLUSION_RULE,
    LIQUIDITY_FILTER_RULE,
    UNIVERSE_SOURCE_NOTE,
    UniverseSnapshot,
    histories_by_canonical,
    liquidity_snapshots,
    snapshot_for,
)
from traderstack.strategies import Regime, StrategySignal

TOPK_LOOKBACKS: tuple[int, ...] = (21, 63, 126)
TOPK_SKIP_DAYS = 7
TOPK_KS: tuple[int, ...] = (3, 5)
TOPK_WEIGHTS: tuple[str, ...] = ("ew", "iv")
VOL_LOOKBACK = 30
MIN_HISTORY_MARGIN = 8
MIN_CROSS_SECTION = 10
REBALANCE_RULE = "monday_utc_close_fill_next_open"
# (candidate_id, lookback, k, weighting)
TOPK_CATALOG: tuple[tuple[str, int, int, str], ...] = tuple(
    (f"xs_topk_{weighting}_{lookback}_k{k}", lookback, k, weighting)
    for weighting in TOPK_WEIGHTS
    for lookback in TOPK_LOOKBACKS
    for k in TOPK_KS
)
TOPK_IDS: tuple[str, ...] = tuple(item[0] for item in TOPK_CATALOG)
CONTROL_ID = "ew_bh_universe"
CONTROL_IDS: frozenset[str] = frozenset({CONTROL_ID})
CORE_IDS: tuple[str, ...] = TOPK_IDS + (CONTROL_ID,)

LOWTURN_LOOKBACKS: tuple[int, ...] = (126, 252, 378)
LOWTURN_KS: tuple[int, ...] = (3, 5)
LOWTURN_WEIGHTS: tuple[str, ...] = ("ew", "iv")
# Fresh lower-turnover catalog (new ids). Do not retune TOPK_CATALOG after PnL.
LOWTURN_CATALOG: tuple[tuple[str, int, int, str], ...] = tuple(
    (f"xs_topk_lt_{weighting}_{lookback}_k{k}", lookback, k, weighting)
    for weighting in LOWTURN_WEIGHTS
    for lookback in LOWTURN_LOOKBACKS
    for k in LOWTURN_KS
)
LOWTURN_IDS: tuple[str, ...] = tuple(item[0] for item in LOWTURN_CATALOG)
LOWTURN_CORE_IDS: tuple[str, ...] = LOWTURN_IDS + (CONTROL_ID,)
LOWTURN_CATALOG_NOTE = (
    f"Frozen lower-turnover catalog (K={len(LOWTURN_CORE_IDS)}): "
    f"`xs_topk_lt_{{ew|iv}}_{{N}}_k{{3|5}}` for N in {list(LOWTURN_LOOKBACKS)} "
    f"({len(LOWTURN_IDS)} baskets) plus informational control `{CONTROL_ID}` "
    "(cannot promote). Distinct from the default K=13 TOPK_CATALOG - do not "
    "retune either list after seeing PnL. PAPER_PROMOTE_* stays false."
)
CATALOGS: dict[str, tuple[tuple[str, int, int, str], ...]] = {
    "default": TOPK_CATALOG,
    "lowturn": LOWTURN_CATALOG,
}
FAMILY = "xs_topk"


@dataclass(frozen=True)
class Era:
    era_id: str
    start: datetime
    end: datetime  # exclusive


# --- era policy (#140; supersede with #135 shared policy) ---
ERAS: tuple[Era, ...] = (
    Era("2016-2019", datetime(2016, 1, 1, tzinfo=UTC), datetime(2020, 1, 1, tzinfo=UTC)),
    Era("2020-2022", datetime(2020, 1, 1, tzinfo=UTC), datetime(2022, 1, 1, tzinfo=UTC)),
    Era("2022-2024", datetime(2022, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)),
    Era("2024-2026", datetime(2024, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
)
MIN_ERA_BARS = 365
ERA_IDS: tuple[str, ...] = tuple(era.era_id for era in ERAS)

# docs/artifacts/research/odds-brief-2026-09-13.md section 5, Kraken Pro
# spot fee table, tier 1 ("$0+" 30-day volume): taker 0.80% per side.
PILOT_TIER_TAKER_BPS = 80.0
PILOT_TIER_LABEL = "Kraken Pro spot tier 1 ($0+ 30d volume) taker 0.80% per side"
RESEARCH_FEE_BPS = 10.0
RESEARCH_SLIPPAGE_BPS = 5.0

RANKING_KEY = "mean_era_excess_vs_ew_bh_among_dual_print_passers"
SELECTION_RULE = "top1_by_ranking_key_tiebreak_candidate_id"
PORTFOLIO_BAR_RULE = (
    "pilot_cost_net_return_pos_and_net_sharpe_pos_and_excess_vs_ew_bh_pos_"
    "in_every_covered_era_and_print_holdout_excess_pos"
)
DUAL_PRINT_RULE = "two_independent_covered_cells_pass_and_no_covered_cell_or_holdout_fails"
DSR_PBO_STATUS = "not_computed_pending_135"
PAPER_PATH_READY = True
CAN_AVERAGE_VENUES = False
CAN_ENTER_PROMOTION_AVERAGE = False
MULTI_VENUE_BAR_PREREGISTERED = True

XS_TOPK_RULES = (
    "Pre-registered long-only top-k cross-sectional momentum bar on the "
    "point-in-time Kraken USD spot universe (frozen before any score). "
    f"Universe: `{LIQUIDITY_FILTER_RULE}` on a frozen dated AssetPairs "
    f"listing ({EXCLUSION_RULE}). Score on each Monday UTC close t: "
    f"close[t-{TOPK_SKIP_DAYS}] / close[t-{TOPK_SKIP_DAYS}-N] - 1 for N in "
    f"{list(TOPK_LOOKBACKS)} (one-week skip). A name missing either close "
    f"or with fewer than N+{MIN_HISTORY_MARGIN} bars through t is skipped for "
    f"that rebalance, never zero-filled. Fewer than MIN_CROSS_SECTION="
    f"{MIN_CROSS_SECTION} rankable names -> flat week (counted). Long the "
    f"top k in {list(TOPK_KS)}; weights `ew` (1/k) or `iv` (inverse trailing "
    f"{VOL_LOOKBACK}-day sample vol, normalised to 1); long-only, no "
    f"leverage, no shorts. Rebalance rule `{REBALANCE_RULE}`: decide on "
    "close t, fill at the next bar open, drift between rebalances. "
    "Turnover and fee drag are reported at research 10+5 bps and at the "
    f"frozen pilot-tier cost ({PILOT_TIER_LABEL}; {PILOT_TIER_TAKER_BPS:g} "
    "bps + 5 bps slippage). Control `ew_bh_universe` = equal weight of the "
    "same monthly snapshot names, refreshed at each snapshot, otherwise "
    f"buy-and-hold; it cannot promote. Portfolio bar `{PORTFOLIO_BAR_RULE}` "
    "at the pilot cost: every covered era needs net return > 0, net Sharpe "
    "> 0 and net excess over the control > 0, plus the print's last-20% "
    "holdout net excess > 0; a family that only works in one era fails. "
    f"A cell (venue x era) is covered with >= {MIN_ERA_BARS} daily bars "
    f"inside the era; eras {list(ERA_IDS)} are a local constant pending the "
    f"#135 shared era policy. Dual print `{DUAL_PRINT_RULE}`: two "
    "independent covered cells (distinct venues or non-overlapping eras) "
    "must pass and none may fail; one venue over one era cannot promote. "
    f"Ranking key: {RANKING_KEY} (tie-break: candidate_id); "
    f"CAN_AVERAGE_VENUES={str(CAN_AVERAGE_VENUES).lower()}; "
    f"MULTI_VENUE_BAR_PREREGISTERED={str(MULTI_VENUE_BAR_PREREGISTERED).lower()}. "
    f"DSR / PBO: {DSR_PBO_STATUS} (Deflated Sharpe and PBO land with #135). "
    "Paper-executable on Kraken spot as candle-only long/flat signals "
    f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()}); the runtime "
    "allowlist and RiskEngine limits are documented, not widened. "
    "PAPER_PROMOTE_* stays default false. No live. An empty dual-print set "
    "is success. Not a #117 top-1 reprint."
)

CATALOG_NOTE = (
    f"Frozen catalog (K={len(CORE_IDS)}): `xs_topk_{{ew|iv}}_{{N}}_k{{3|5}}` "
    f"for N in {list(TOPK_LOOKBACKS)} ({len(TOPK_IDS)} baskets) plus the "
    f"informational control `{CONTROL_ID}` (cannot promote). Do not grow "
    "this list after seeing PnL. PAPER_PROMOTE_* stays false unless a "
    "committed dual-print report names a paper-only pin and an operator "
    "flips it (default false if ever added)."
)

PAPER_EXECUTABLE_PATH_NOTE = (
    "This family is paper-executable on Kraken spot as candle-only "
    "long/flat signals per name: `CrossSectionalTopKVoter` emits Side.BUY "
    "on an assigned bar and no side otherwise (never Side.SELL); "
    "paper_simulate_fills already books that. No perp, no funding, no "
    "hedge book, no invented basis. `paper_path_ready` does NOT mean the "
    "runtime cycles twenty names: MVP_ASSETS and PAPER_PROMOTE_UNIVERSE "
    "are unchanged and would reject most universe names with "
    "`asset_not_allowlisted` — that is correct layering. A Settings pin is "
    "added only if a committed dual-print passer exists, and then default "
    "false."
)

MAX_POSITIONS_LAYERING_NOTE = (
    f"RiskEngine layering (documented, not widened): max(TOPK_KS)={max(TOPK_KS)} "
    "equals the MAX_OPEN_POSITIONS default (5); "
    f"{max(TOPK_KS)} x MAX_POSITION_PCT (0.10) = {max(TOPK_KS) * 0.10:.2f} fits "
    "under MAX_GROSS_EXPOSURE_PCT (0.60); `max_positions_reached` remains the "
    "binding control. This family reads no Settings and cannot raise any "
    "limit, side, asset list or size."
)


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------


def _sample_stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    deviation = _std(values)
    return deviation if deviation > 0 else None


def aligned_closes_by_symbol(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, dict[datetime, float]]:
    """Canonical ``BASE/USD`` -> ``opened_at`` -> close (positive closes only)."""
    out: dict[str, dict[datetime, float]] = {}
    for name, candles in histories_by_canonical(histories).items():
        series = {candle.opened_at: candle.close for candle in candles if candle.close > 0}
        if series:
            out[name] = series
    return out


def opens_by_symbol(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, dict[datetime, float]]:
    out: dict[str, dict[datetime, float]] = {}
    for name, candles in histories_by_canonical(histories).items():
        series = {candle.opened_at: candle.open for candle in candles if candle.open > 0}
        if series:
            out[name] = series
    return out


def trading_calendar(closes: dict[str, dict[datetime, float]]) -> tuple[datetime, ...]:
    days: set[datetime] = set()
    for series in closes.values():
        days.update(series)
    return tuple(sorted(days))


@dataclass(frozen=True)
class MarketTables:
    """Close / open lookups and the union calendar, built once per print."""

    closes: dict[str, dict[datetime, float]]
    opens: dict[str, dict[datetime, float]]
    calendar: tuple[datetime, ...]


def market_tables(histories: dict[str, tuple[Candle, ...]]) -> MarketTables:
    closes = aligned_closes_by_symbol(histories)
    return MarketTables(
        closes=closes, opens=opens_by_symbol(histories), calendar=trading_calendar(closes)
    )


class RebalanceDecision(BaseModel):
    decided_at: datetime
    weights: dict[str, float] = Field(default_factory=dict)
    rankable: int = 0
    reason: str | None = None


def _trailing_vol(series: dict[datetime, float], at: datetime, lookback: int) -> float | None:
    dated = sorted(ts for ts in series if ts <= at)
    window = dated[-(lookback + 1) :]
    if len(window) < lookback + 1:
        return None
    prices = [series[ts] for ts in window]
    returns = [later / earlier - 1.0 for earlier, later in pairwise(prices)]
    return _sample_stdev(returns)


def _weights_for(
    ranked: list[str],
    *,
    weighting: str,
    closes: dict[str, dict[datetime, float]],
    at: datetime,
) -> dict[str, float]:
    if not ranked:
        return {}
    if weighting == "ew":
        share = 1.0 / len(ranked)
        return {name: share for name in ranked}
    if weighting != "iv":
        raise ValueError(f"unknown weighting {weighting!r}")
    raw: dict[str, float] = {}
    for name in ranked:
        vol = _trailing_vol(closes[name], at, VOL_LOOKBACK)
        if vol is None:
            continue
        raw[name] = 1.0 / vol
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {name: value / total for name, value in raw.items()}


def topk_targets(
    histories: dict[str, tuple[Candle, ...]],
    snapshots: tuple[UniverseSnapshot, ...],
    *,
    lookback: int,
    k: int,
    weighting: str,
) -> tuple[RebalanceDecision, ...]:
    """Monday-UTC top-k decisions with a one-week skip. Skip-not-invent."""
    if lookback <= 0 or k <= 0:
        raise ValueError("lookback and k must be positive")
    closes = aligned_closes_by_symbol(histories)
    calendar = trading_calendar(closes)
    min_bars = lookback + MIN_HISTORY_MARGIN
    out: list[RebalanceDecision] = []
    for at in calendar:
        if at.weekday() != 0:
            continue
        snapshot = snapshot_for(snapshots, at)
        if snapshot is None:
            out.append(RebalanceDecision(decided_at=at, reason="no_universe_snapshot"))
            continue
        recent_at = at - timedelta(days=TOPK_SKIP_DAYS)
        base_at = at - timedelta(days=TOPK_SKIP_DAYS + lookback)
        scores: list[tuple[float, str]] = []
        for name in snapshot.names:
            series = closes.get(name)
            if not series:
                continue
            recent = series.get(recent_at)
            base = series.get(base_at)
            if recent is None or base is None or series.get(at) is None:
                continue
            if sum(1 for ts in series if ts <= at) < min_bars:
                continue
            if weighting == "iv" and _trailing_vol(series, at, VOL_LOOKBACK) is None:
                continue
            scores.append((recent / base - 1.0, name))
        if len(scores) < MIN_CROSS_SECTION:
            out.append(
                RebalanceDecision(decided_at=at, rankable=len(scores), reason="thin_cross_section")
            )
            continue
        scores.sort(key=lambda item: (-item[0], item[1]))
        chosen = [name for _, name in scores[:k]]
        weights = _weights_for(chosen, weighting=weighting, closes=closes, at=at)
        out.append(RebalanceDecision(decided_at=at, weights=weights, rankable=len(scores)))
    return tuple(out)


def ew_universe_control_targets(
    histories: dict[str, tuple[Candle, ...]],
    snapshots: tuple[UniverseSnapshot, ...],
) -> tuple[RebalanceDecision, ...]:
    """Equal weight of each snapshot's names, decided on the first bar on or
    after the snapshot date, filled next open, then held until the next
    snapshot (the issue's 'equal-weight buy-and-hold of the same universe')."""
    closes = aligned_closes_by_symbol(histories)
    calendar = trading_calendar(closes)
    out: list[RebalanceDecision] = []
    for snapshot in snapshots:
        at = next((day for day in calendar if day >= snapshot.snapshot_at), None)
        if at is None:
            continue
        names = [name for name in snapshot.names if closes.get(name, {}).get(at) is not None]
        if not names:
            out.append(RebalanceDecision(decided_at=at, reason="no_priced_member"))
            continue
        share = 1.0 / len(names)
        out.append(
            RebalanceDecision(
                decided_at=at, weights={name: share for name in names}, rankable=len(names)
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Basket simulator
# ---------------------------------------------------------------------------


class BasketMetrics(BaseModel):
    bars: int
    first: str
    last: str
    starting_equity: float = Field(gt=0)
    ending_equity: float = Field(gt=0)
    total_return: float
    max_drawdown: float = Field(ge=0)
    sharpe: float
    sortino: float = 0.0
    annualized_volatility: float = Field(default=0.0, ge=0)
    total_fees: float = Field(ge=0)
    fee_drag: float = Field(ge=0)
    traded_fraction: float = Field(ge=0)
    one_way_turnover: float = Field(ge=0)
    one_way_turnover_per_year: float = Field(ge=0)
    rebalances: int = 0
    flat_weeks: int = 0
    fills_skipped: int = 0
    stale_marks: int = 0


def _max_drawdown(path: list[float]) -> float:
    peak = path[0]
    worst = 0.0
    for value in path:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, 1.0 - value / peak)
    return worst


@dataclass(frozen=True)
class BasketRun:
    calendar: list[datetime]
    path: list[float]
    fees: float
    traded: float
    rebalances: int
    flat_weeks: int
    fills_skipped: int
    stale_marks: int


def run_basket(
    histories: dict[str, tuple[Candle, ...]] | MarketTables,
    decisions: tuple[RebalanceDecision, ...],
    *,
    cost_bps: float,
    starting_equity: float = 10_000.0,
    start: datetime | None = None,
    end: datetime | None = None,
) -> BasketRun | None:
    """Long-only basket: fill each decision at the next bar's open, pay
    ``cost_bps`` on traded notional, drift between rebalances, mark daily.

    A target name with no open on the fill bar is skipped for that fill
    (counted), a held name with no close on a bar keeps its last mark
    (counted). A window starting after the first decision carries the
    latest prior decision in and fills it at the first bar's open.
    Returns None when the window has fewer than two bars.
    """
    if cost_bps < 0 or starting_equity <= 0:
        raise ValueError("cost_bps must be >= 0 and starting_equity > 0")
    tables = histories if isinstance(histories, MarketTables) else market_tables(histories)
    closes = tables.closes
    opens = tables.opens
    calendar = [
        day
        for day in tables.calendar
        if (start is None or day >= start) and (end is None or day < end)
    ]
    if len(calendar) < 2:
        return None
    by_date = {decision.decided_at: decision for decision in decisions}
    cash = starting_equity
    units: dict[str, float] = {}
    last_mark: dict[str, float] = {}
    # A window that starts mid-history carries in the most recent decision
    # made before its first bar, filled at that bar's open, so an era cell
    # or a holdout compares baskets that are both invested from day one
    # rather than one that waits for its next scheduled rebalance.
    pending: RebalanceDecision | None = max(
        (item for item in decisions if item.decided_at < calendar[0]),
        key=lambda item: item.decided_at,
        default=None,
    )
    path: list[float] = []
    fees = 0.0
    traded = 0.0
    rebalances = 0
    flat_weeks = 0
    fills_skipped = 0
    stale_marks = 0
    for day in calendar:
        if pending is not None:
            names = sorted(set(units) | set(pending.weights))
            prices: dict[str, float | None] = {name: opens.get(name, {}).get(day) for name in names}
            equity_open = cash
            for name in names:
                price = prices[name]
                held = units.get(name, 0.0)
                equity_open += held * (price if price is not None else last_mark.get(name, 0.0))
            for name in names:
                price = prices[name]
                if price is None:
                    fills_skipped += 1
                    continue
                target = pending.weights.get(name, 0.0) * equity_open
                current = units.get(name, 0.0) * price
                delta = target - current
                if abs(delta) <= 1e-12:
                    continue
                cost = abs(delta) * cost_bps / 10_000.0
                cash -= delta + cost
                fees += cost
                traded += abs(delta) / equity_open if equity_open > 0 else 0.0
                if target <= 0.0:
                    units.pop(name, None)
                else:
                    units[name] = target / price
                    last_mark[name] = price
            rebalances += 1
            pending = None
        equity = cash
        for name, held in units.items():
            close = closes.get(name, {}).get(day)
            if close is None:
                stale_marks += 1
                close = last_mark.get(name, 0.0)
            else:
                last_mark[name] = close
            equity += held * close
        path.append(equity)
        decision = by_date.get(day)
        if decision is not None:
            pending = decision
            if not decision.weights:
                flat_weeks += 1
    return BasketRun(
        calendar=calendar,
        path=path,
        fees=fees,
        traded=traded,
        rebalances=rebalances,
        flat_weeks=flat_weeks,
        fills_skipped=fills_skipped,
        stale_marks=stale_marks,
    )


def basket_equity_path(
    histories: dict[str, tuple[Candle, ...]] | MarketTables,
    decisions: tuple[RebalanceDecision, ...],
    *,
    cost_bps: float,
    starting_equity: float = 10_000.0,
) -> tuple[tuple[datetime, float], ...]:
    run = run_basket(histories, decisions, cost_bps=cost_bps, starting_equity=starting_equity)
    if run is None:
        return ()
    return tuple(zip(run.calendar, run.path, strict=True))


def simulate_basket(
    histories: dict[str, tuple[Candle, ...]] | MarketTables,
    decisions: tuple[RebalanceDecision, ...],
    *,
    cost_bps: float,
    starting_equity: float = 10_000.0,
    start: datetime | None = None,
    end: datetime | None = None,
) -> BasketMetrics | None:
    """``run_basket`` reduced to ``BasketMetrics`` (None when < 2 bars)."""
    run = run_basket(
        histories,
        decisions,
        cost_bps=cost_bps,
        starting_equity=starting_equity,
        start=start,
        end=end,
    )
    if run is None:
        return None
    calendar, path = run.calendar, run.path
    fees, traded = run.fees, run.traded
    returns = [later / earlier - 1.0 for earlier, later in pairwise(path) if earlier > 0]
    per_year = periods_per_year("1d")
    years = max((calendar[-1] - calendar[0]).days, 1) / 365.0
    one_way = traded / 2.0
    ending = path[-1]
    if ending <= 0:
        ending = 1e-9
    return BasketMetrics(
        bars=len(calendar),
        first=calendar[0].isoformat(),
        last=calendar[-1].isoformat(),
        starting_equity=starting_equity,
        ending_equity=ending,
        total_return=ending / starting_equity - 1.0,
        max_drawdown=_max_drawdown(path),
        sharpe=_sharpe(returns, per_year),
        sortino=_sortino(returns, per_year),
        annualized_volatility=_std(returns) * sqrt(per_year),
        total_fees=fees,
        fee_drag=fees / starting_equity,
        traded_fraction=traded,
        one_way_turnover=one_way,
        one_way_turnover_per_year=one_way / years,
        rebalances=run.rebalances,
        flat_weeks=run.flat_weeks,
        fills_skipped=run.fills_skipped,
        stale_marks=run.stale_marks,
    )


# ---------------------------------------------------------------------------
# Era cells, prints, rows
# ---------------------------------------------------------------------------


class EraCell(BaseModel):
    venue: str
    era_id: str
    covered: bool = False
    bars: int = 0
    first: str | None = None
    last: str | None = None
    research: BasketMetrics | None = None
    pilot: BasketMetrics | None = None
    control_research: BasketMetrics | None = None
    control_pilot: BasketMetrics | None = None
    excess_vs_control_research: float | None = None
    excess_vs_control_pilot: float | None = None
    bar_pass: bool = False
    fail_reasons: list[str] = Field(default_factory=list)


class CandidatePrint(BaseModel):
    candidate_id: str
    venue: str
    cells: list[EraCell] = Field(default_factory=list)
    full_research: BasketMetrics | None = None
    full_pilot: BasketMetrics | None = None
    holdout_first: str | None = None
    holdout_excess_pilot: float | None = None
    holdout_pass: bool = False
    covered_cells: int = 0
    passed_cells: int = 0
    failed_cells: int = 0
    print_pass: bool = False
    decisions: int = 0
    flat_weeks: int = 0


class PrintMeta(BaseModel):
    venue: str
    source: str
    status: str = "skipped"
    names_loaded: int = 0
    names_skipped: int = 0
    skip_reasons: list[str] = Field(default_factory=list)
    first: str | None = None
    last: str | None = None
    bars_max: int = 0
    snapshots: int = 0
    snapshot_first: str | None = None
    snapshot_last: str | None = None
    names_ever_in_universe: int = 0
    eras_covered: list[str] = Field(default_factory=list)
    fail_closed_reason: str | None = None


class PrintResult(BaseModel):
    meta: PrintMeta
    candidates: list[CandidatePrint] = Field(default_factory=list)


class TopKRow(BaseModel):
    candidate_id: str
    family: str = FAMILY
    label: str
    lookback: int | None = None
    k: int | None = None
    weighting: str | None = None
    venues: list[str] = Field(default_factory=list)
    covered_cells: int = 0
    passed_cells: int = 0
    failed_cells: int = 0
    holdout_failures: int = 0
    dual_print: bool = False
    dual_print_rank: int | None = None
    mean_era_excess_pilot: float | None = None
    pilot_net_return_by_venue: dict[str, float | None] = Field(default_factory=dict)
    research_net_return_by_venue: dict[str, float | None] = Field(default_factory=dict)
    control_pilot_return_by_venue: dict[str, float | None] = Field(default_factory=dict)
    one_way_turnover_per_year_by_venue: dict[str, float | None] = Field(default_factory=dict)
    pilot_fee_drag_by_venue: dict[str, float | None] = Field(default_factory=dict)
    research_fee_drag_by_venue: dict[str, float | None] = Field(default_factory=dict)
    selected: bool = False
    can_promote: bool = False


def _label(lookback: int, k: int, weighting: str) -> str:
    scheme = "equal-weight" if weighting == "ew" else "inverse-vol"
    return (
        f"long-only top-{k} by {lookback}d trailing return (7d skip), "
        f"{scheme}, weekly, PIT top-20 Kraken USD universe"
    )


def _covered_bars(calendar: tuple[datetime, ...], era: Era) -> list[datetime]:
    return [day for day in calendar if era.start <= day < era.end]


def _cell(
    *,
    venue: str,
    era: Era,
    tables: MarketTables,
    decisions: tuple[RebalanceDecision, ...],
    control: tuple[RebalanceDecision, ...],
    research_cost: float,
    pilot_cost: float,
    starting_equity: float,
    is_control: bool,
) -> EraCell:
    days = _covered_bars(tables.calendar, era)
    cell = EraCell(venue=venue, era_id=era.era_id, bars=len(days))
    if len(days) < MIN_ERA_BARS:
        cell.fail_reasons.append(f"not_covered_{len(days)}_bars_lt_{MIN_ERA_BARS}")
        return cell
    cell.covered = True
    cell.first = days[0].isoformat()
    cell.last = days[-1].isoformat()

    def _sim(targets: tuple[RebalanceDecision, ...], cost_bps: float) -> BasketMetrics | None:
        return simulate_basket(
            tables,
            targets,
            cost_bps=cost_bps,
            starting_equity=starting_equity,
            start=era.start,
            end=era.end,
        )

    cell.research = _sim(decisions, research_cost)
    cell.pilot = _sim(decisions, pilot_cost)
    cell.control_research = _sim(control, research_cost)
    cell.control_pilot = _sim(control, pilot_cost)
    if cell.research is not None and cell.control_research is not None:
        cell.excess_vs_control_research = (
            cell.research.total_return - cell.control_research.total_return
        )
    if cell.pilot is None or cell.control_pilot is None:
        cell.fail_reasons.append("no_basket_path")
        return cell
    cell.excess_vs_control_pilot = cell.pilot.total_return - cell.control_pilot.total_return
    if is_control:
        cell.fail_reasons.append("control_cannot_pass")
        return cell
    if cell.pilot.total_return <= 0:
        cell.fail_reasons.append("pilot_net_return_le_0")
    if cell.pilot.sharpe <= 0:
        cell.fail_reasons.append("pilot_net_sharpe_le_0")
    if cell.excess_vs_control_pilot <= 0:
        cell.fail_reasons.append("pilot_excess_vs_ew_bh_le_0")
    cell.bar_pass = not cell.fail_reasons
    return cell


def _holdout_start(calendar: tuple[datetime, ...], holdout_fraction: float) -> datetime | None:
    if not 0 < holdout_fraction < 1 or len(calendar) < 5:
        return None
    size = max(int(len(calendar) * holdout_fraction), 2)
    if size >= len(calendar):
        return None
    return calendar[-size]


def score_print(
    venue: str,
    histories: dict[str, tuple[Candle, ...]],
    *,
    source: str,
    fee_bps: float = RESEARCH_FEE_BPS,
    slippage_bps: float = RESEARCH_SLIPPAGE_BPS,
    pilot_fee_bps: float = PILOT_TIER_TAKER_BPS,
    starting_equity: float = 10_000.0,
    holdout_fraction: float = 0.20,
    skip_reasons: list[str] | None = None,
    names_skipped: int = 0,
    catalog: tuple[tuple[str, int, int, str], ...] = TOPK_CATALOG,
) -> PrintResult:
    """Score the frozen catalog and the control on one venue print."""
    by_name = histories_by_canonical(histories)
    meta = PrintMeta(
        venue=venue,
        source=source,
        names_loaded=len(by_name),
        names_skipped=names_skipped,
        skip_reasons=list(skip_reasons or [])[:25],
    )
    if not by_name:
        meta.fail_closed_reason = "no daily histories loaded; nothing scored (empty is success)"
        return PrintResult(meta=meta)
    tables = market_tables(by_name)
    closes = tables.closes
    calendar = tables.calendar
    meta.first = calendar[0].isoformat()
    meta.last = calendar[-1].isoformat()
    meta.bars_max = max(len(series) for series in closes.values())
    snapshots = liquidity_snapshots(by_name)
    meta.snapshots = len(snapshots)
    if not snapshots:
        meta.fail_closed_reason = (
            "no monthly liquidity snapshot could be formed (need a full trailing "
            "30-day dollar-volume window before a month start); nothing scored"
        )
        return PrintResult(meta=meta)
    meta.status = "ok"
    meta.snapshot_first = snapshots[0].snapshot_at.isoformat()
    meta.snapshot_last = snapshots[-1].snapshot_at.isoformat()
    ever: set[str] = set()
    for snapshot in snapshots:
        ever.update(snapshot.names)
    meta.names_ever_in_universe = len(ever)
    meta.eras_covered = [
        era.era_id for era in ERAS if len(_covered_bars(calendar, era)) >= MIN_ERA_BARS
    ]
    research_cost = fee_bps + slippage_bps
    pilot_cost = pilot_fee_bps + slippage_bps
    holdout_start = _holdout_start(calendar, holdout_fraction)
    control = ew_universe_control_targets(by_name, snapshots)

    def _candidate(
        candidate_id: str, decisions: tuple[RebalanceDecision, ...], *, is_control: bool
    ) -> CandidatePrint:
        row = CandidatePrint(candidate_id=candidate_id, venue=venue)
        row.decisions = len(decisions)
        row.flat_weeks = sum(1 for item in decisions if not item.weights)
        row.full_research = simulate_basket(
            tables, decisions, cost_bps=research_cost, starting_equity=starting_equity
        )
        row.full_pilot = simulate_basket(
            tables, decisions, cost_bps=pilot_cost, starting_equity=starting_equity
        )
        for era in ERAS:
            row.cells.append(
                _cell(
                    venue=venue,
                    era=era,
                    tables=tables,
                    decisions=decisions,
                    control=control,
                    research_cost=research_cost,
                    pilot_cost=pilot_cost,
                    starting_equity=starting_equity,
                    is_control=is_control,
                )
            )
        row.covered_cells = sum(1 for cell in row.cells if cell.covered)
        row.passed_cells = sum(1 for cell in row.cells if cell.covered and cell.bar_pass)
        row.failed_cells = row.covered_cells - row.passed_cells
        if holdout_start is not None:
            row.holdout_first = holdout_start.isoformat()
            mine = simulate_basket(
                tables,
                decisions,
                cost_bps=pilot_cost,
                starting_equity=starting_equity,
                start=holdout_start,
            )
            theirs = simulate_basket(
                tables,
                control,
                cost_bps=pilot_cost,
                starting_equity=starting_equity,
                start=holdout_start,
            )
            if mine is not None and theirs is not None:
                row.holdout_excess_pilot = mine.total_return - theirs.total_return
                row.holdout_pass = row.holdout_excess_pilot > 0 and not is_control
        row.print_pass = (
            not is_control and row.covered_cells > 0 and row.failed_cells == 0 and row.holdout_pass
        )
        return row

    rows: list[CandidatePrint] = []
    for candidate_id, lookback, k, weighting in catalog:
        decisions = topk_targets(by_name, snapshots, lookback=lookback, k=k, weighting=weighting)
        rows.append(_candidate(candidate_id, decisions, is_control=False))
    rows.append(_candidate(CONTROL_ID, control, is_control=True))
    return PrintResult(meta=meta, candidates=rows)


def _row_from_prints(
    candidate_id: str,
    prints: list[PrintResult],
    *,
    catalog: tuple[tuple[str, int, int, str], ...],
) -> TopKRow:
    spec = next((item for item in catalog if item[0] == candidate_id), None)
    if spec is None:
        row = TopKRow(
            candidate_id=candidate_id,
            family="control",
            label="equal-weight buy-and-hold of the same PIT universe (cannot promote)",
        )
    else:
        row = TopKRow(
            candidate_id=candidate_id,
            label=_label(spec[1], spec[2], spec[3]),
            lookback=spec[1],
            k=spec[2],
            weighting=spec[3],
        )
    excesses: list[float] = []
    for result in prints:
        found = next(
            (item for item in result.candidates if item.candidate_id == candidate_id), None
        )
        if found is None or result.meta.status != "ok":
            continue
        venue = result.meta.venue
        row.venues.append(venue)
        if found.covered_cells > 0:
            # A print with no covered era contributes nothing to the bar,
            # in either direction; its holdout is informational only.
            row.covered_cells += found.covered_cells
            row.passed_cells += found.passed_cells
            row.failed_cells += found.failed_cells
            if found.holdout_excess_pilot is None or not found.holdout_pass:
                row.holdout_failures += 1
            for cell in found.cells:
                if cell.covered and cell.excess_vs_control_pilot is not None:
                    excesses.append(cell.excess_vs_control_pilot)
        row.pilot_net_return_by_venue[venue] = (
            found.full_pilot.total_return if found.full_pilot else None
        )
        row.research_net_return_by_venue[venue] = (
            found.full_research.total_return if found.full_research else None
        )
        row.one_way_turnover_per_year_by_venue[venue] = (
            found.full_pilot.one_way_turnover_per_year if found.full_pilot else None
        )
        row.pilot_fee_drag_by_venue[venue] = found.full_pilot.fee_drag if found.full_pilot else None
        row.research_fee_drag_by_venue[venue] = (
            found.full_research.fee_drag if found.full_research else None
        )
        control_cell = next(
            (item for item in result.candidates if item.candidate_id == CONTROL_ID), None
        )
        row.control_pilot_return_by_venue[venue] = (
            control_cell.full_pilot.total_return
            if control_cell is not None and control_cell.full_pilot is not None
            else None
        )
    if excesses:
        row.mean_era_excess_pilot = _mean(excesses)
    row.dual_print = (
        candidate_id not in CONTROL_IDS
        and row.failed_cells == 0
        and row.holdout_failures == 0
        and row.passed_cells >= 2
    )
    row.can_promote = False
    return row


def dual_print_rows(
    prints: list[PrintResult],
    *,
    catalog: tuple[tuple[str, int, int, str], ...] = TOPK_CATALOG,
) -> list[TopKRow]:
    ids = [item[0] for item in catalog] + [CONTROL_ID]
    return [_row_from_prints(candidate_id, prints, catalog=catalog) for candidate_id in ids]


def rank_topk_passers(rows: list[TopKRow]) -> list[TopKRow]:
    """Frozen ranking among dual-print passers. Control excluded."""
    passers = [row for row in rows if row.dual_print and row.candidate_id not in CONTROL_IDS]
    passers.sort(
        key=lambda row: (
            -(row.mean_era_excess_pilot if row.mean_era_excess_pilot is not None else -1e9),
            row.candidate_id,
        )
    )
    for index, row in enumerate(passers, start=1):
        row.dual_print_rank = index
    return passers


# ---------------------------------------------------------------------------
# Paper voter (same-bar lookup, long/flat only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossSectionalTopKVoter:
    """Look up a precomputed same-bar basket weight. Long or flat, never short."""

    strategy_id: str
    weights_by_symbol: tuple[tuple[str, tuple[tuple[datetime, float], ...]], ...] = ()

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        cutoff = candles[-1].opened_at
        by_ts = dict(self.series_for(candles[-1].symbol))
        weight = by_ts.get(cutoff)
        if weight is None or weight <= 0:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="xs_topk: no same-bar assignment (skipped or flat)",
            )
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=Side.BUY,
            score=min(1.0, weight),
            confidence=1.0,
            regime=regime,
            rationale=f"xs_topk weight={weight:.3f}",
        )

    def series_for(self, symbol: str) -> tuple[tuple[datetime, float], ...]:
        key = symbol.upper()
        for name, series in self.weights_by_symbol:
            if name == key:
                return series
        return ()


def voter_from_decisions(
    strategy_id: str, decisions: tuple[RebalanceDecision, ...]
) -> CrossSectionalTopKVoter:
    per_symbol: dict[str, list[tuple[datetime, float]]] = {}
    for decision in decisions:
        for name, weight in decision.weights.items():
            per_symbol.setdefault(name.upper(), []).append((decision.decided_at, weight))
    return CrossSectionalTopKVoter(
        strategy_id=strategy_id,
        weights_by_symbol=tuple(
            (name, tuple(series)) for name, series in sorted(per_symbol.items())
        ),
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class XsTopKReport(BaseModel):
    generated_at: datetime
    ranking_key: str = RANKING_KEY
    selection_rule: str = SELECTION_RULE
    portfolio_bar_rule: str = PORTFOLIO_BAR_RULE
    dual_print_rule: str = DUAL_PRINT_RULE
    liquidity_filter_rule: str = LIQUIDITY_FILTER_RULE
    rebalance_rule: str = REBALANCE_RULE
    exclusion_rule: str = EXCLUSION_RULE
    dsr_pbo_status: str = DSR_PBO_STATUS
    era_ids: list[str] = Field(default_factory=lambda: list(ERA_IDS))
    min_era_bars: int = MIN_ERA_BARS
    universe_listing_fetched_at: str | None = None
    universe_listing_source: str | None = None
    universe_listing_size: int = 0
    catalog_k_core: int = len(CORE_IDS)
    catalog_ids: list[str] = Field(default_factory=lambda: list(CORE_IDS))
    catalog_note: str = CATALOG_NOTE
    catalog_name: str = "default"
    fee_bps: float
    slippage_bps: float
    pilot_fee_bps: float
    pilot_tier_label: str = PILOT_TIER_LABEL
    starting_equity: float
    holdout_fraction: float
    paper_path_ready: bool = PAPER_PATH_READY
    multi_venue_bar_preregistered: bool = MULTI_VENUE_BAR_PREREGISTERED
    can_average_venues: bool = CAN_AVERAGE_VENUES
    can_enter_promotion_average: bool = CAN_ENTER_PROMOTION_AVERAGE
    keep_flag_false: bool = True
    prints: list[PrintResult] = Field(default_factory=list)
    rows: list[TopKRow] = Field(default_factory=list)
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    single_print_passer_ids: list[str] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    recommended_promote_flag: str | None = None
    any_dual_print_passer: bool = False
    honesty: str
    recommendation: str
    rules: str = XS_TOPK_RULES
    universe_note: str = UNIVERSE_SOURCE_NOTE
    kraken_cap_note: str = KRAKEN_DAILY_CAP_NOTE
    paper_path_note: str = PAPER_EXECUTABLE_PATH_NOTE
    layering_note: str = MAX_POSITIONS_LAYERING_NOTE
    data_notes: list[str] = Field(default_factory=list)


def _recommendation(
    *,
    selected_id: str | None,
    dual_ids: list[str],
    single_ids: list[str],
    prints: list[PrintResult],
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
            f"- Single-print bar passers (informational; cannot promote): {len(single_ids)}"
            + (f" (`{'`, `'.join(single_ids)}`)" if single_ids else "")
            + "."
        ),
    ]
    for result in prints:
        meta = result.meta
        lines.append(
            f"- Print `{meta.venue}` ({meta.source}): **{meta.status}**; "
            f"names loaded {meta.names_loaded}, skipped {meta.names_skipped}; "
            f"eras covered {meta.eras_covered or 'none'}"
            + (f"; {meta.fail_closed_reason}" if meta.fail_closed_reason else "")
            + "."
        )
    covered = sorted({era for result in prints for era in result.meta.eras_covered})
    venues_ok = [result.meta.venue for result in prints if result.meta.status == "ok"]
    if len(venues_ok) < 2 and len(covered) < 2:
        lines.append(
            "- Independent prints available: "
            f"{len(venues_ok)} venue(s) x {len(covered)} covered era(s) — fewer "
            "than two independent cells, so **no name can dual-print on this "
            "data** (empty is success; a second venue or an older era from "
            "#133 is required)."
        )
    lines.append(f"- DSR / PBO: `{DSR_PBO_STATUS}`.")
    lines.append(
        f"- Paper path: candle-only long/flat on Kraken spot "
        f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()}); runtime allowlist unchanged."
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
            "(default **false** if added). This run does not flip it."
        )
    lines.append(
        "- Do not enable live. Do not fabricate PnL. Do not widen "
        "MAX_OPEN_POSITIONS, MVP_ASSETS or PAPER_PROMOTE_UNIVERSE for this "
        "family. Do not re-run the #117 top-1 catalog on the same window."
    )
    return "\n".join(lines)


def resolve_catalog(name: str) -> tuple[tuple[str, int, int, str], ...]:
    """Return a frozen named catalog. Unknown names raise."""
    try:
        return CATALOGS[name]
    except KeyError as exc:
        known = ", ".join(sorted(CATALOGS))
        raise ValueError(f"unknown catalog {name!r}; known: {known}") from exc


def catalog_core_ids(catalog: tuple[tuple[str, int, int, str], ...]) -> tuple[str, ...]:
    return tuple(item[0] for item in catalog) + (CONTROL_ID,)


def catalog_note_for(name: str) -> str:
    if name == "lowturn":
        return LOWTURN_CATALOG_NOTE
    if name == "default":
        return CATALOG_NOTE
    return f"Named catalog {name!r}. PAPER_PROMOTE_* stays false."


def build_xs_topk_report(
    prints: list[PrintResult],
    *,
    fee_bps: float,
    slippage_bps: float,
    pilot_fee_bps: float,
    starting_equity: float,
    holdout_fraction: float,
    universe_listing_fetched_at: str | None = None,
    universe_listing_source: str | None = None,
    universe_listing_size: int = 0,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
    catalog: tuple[tuple[str, int, int, str], ...] | None = None,
    catalog_name: str = "default",
) -> XsTopKReport:
    generated = now or datetime.now(UTC)
    if catalog is None:
        catalog = resolve_catalog(catalog_name)
    rows = dual_print_rows(prints, catalog=catalog)
    passers = rank_topk_passers(rows)
    selected = passers[0] if passers else None
    if selected is not None:
        selected.selected = True
    dual_ids = [row.candidate_id for row in passers]
    single_ids = sorted(
        row.candidate_id
        for row in rows
        if row.candidate_id not in CONTROL_IDS
        and not row.dual_print
        and row.covered_cells > 0
        and row.failed_cells == 0
        and row.holdout_failures == 0
    )
    honesty = (
        XS_TOPK_RULES
        + " "
        + catalog_note_for(catalog_name)
        + f" This run scored K={len(catalog) + 1} (core ids frozen at {len(catalog_core_ids(catalog))}) on "
        f"{len(prints)} print(s). Single-print bar passers (ex-control): {len(single_ids)}. "
        f"Dual-print passers: {len(dual_ids)}."
    )
    if selected is None:
        honesty += (
            " No dual-print passer. Leave every PAPER_PROMOTE_* false. "
            "Do not add a new promote flag."
        )
    else:
        honesty += (
            f" Dual-print top-1 is `{selected.candidate_id}` by {RANKING_KEY}. "
            "Document a paper-only pin only; default false; do not enable live."
        )
    return XsTopKReport(
        generated_at=generated,
        universe_listing_fetched_at=universe_listing_fetched_at,
        universe_listing_source=universe_listing_source,
        universe_listing_size=universe_listing_size,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        pilot_fee_bps=pilot_fee_bps,
        starting_equity=starting_equity,
        holdout_fraction=holdout_fraction,
        keep_flag_false=True,
        prints=prints,
        rows=rows,
        dual_print_passer_ids=dual_ids,
        single_print_passer_ids=single_ids,
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        recommended_promote_flag=(
            paper_promote_flag_name(selected.candidate_id) if selected is not None else None
        ),
        any_dual_print_passer=bool(dual_ids),
        honesty=honesty,
        recommendation=_recommendation(
            selected_id=selected.candidate_id if selected is not None else None,
            dual_ids=dual_ids,
            single_ids=single_ids,
            prints=prints,
        ),
        data_notes=list(data_notes or []),
        catalog_k_core=len(catalog_core_ids(catalog)),
        catalog_ids=list(catalog_core_ids(catalog)),
        catalog_note=catalog_note_for(catalog_name),
        catalog_name=catalog_name,
    )


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _metric(value: float | None, fmt: str = "pct") -> str:
    if value is None:
        return "n/a"
    if fmt == "pct":
        return _pct(value)
    return _ratio(value)


def _print_source_table(report: XsTopKReport) -> list[str]:
    lines = [
        (
            "| print | source | status | names loaded | names skipped | window | bars (max) | "
            "snapshots | eras covered | fail-closed reason |"
        ),
        "| --- | --- | :---: | ---: | ---: | --- | ---: | ---: | --- | --- |",
    ]
    if not report.prints:
        lines.append("| — | — | skipped | 0 | 0 | n/a | 0 | 0 | none | no print loaded |")
    for result in report.prints:
        meta = result.meta
        window = f"{meta.first or 'n/a'} → {meta.last or 'n/a'}"
        lines.append(
            f"| `{meta.venue}` | {meta.source} | **{meta.status}** | {meta.names_loaded} | "
            f"{meta.names_skipped} | {window} | {meta.bars_max} | {meta.snapshots} | "
            f"{', '.join(meta.eras_covered) or 'none'} | {meta.fail_closed_reason or '—'} |"
        )
    return lines


def _era_table(report: XsTopKReport) -> list[str]:
    lines = [
        (
            "| id | print | era | covered | bars | net ret (10+5) | net ret (pilot) | "
            "control (pilot) | excess vs ew_bh (pilot) | Sharpe (pilot) | maxDD (pilot) | "
            "one-way turnover/yr | fee drag (10+5) | fee drag (pilot) | bar |"
        ),
        (
            "| --- | --- | --- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | :---: |"
        ),
    ]
    any_row = False
    for result in report.prints:
        for candidate in result.candidates:
            for cell in candidate.cells:
                if not cell.covered:
                    continue
                any_row = True
                pilot = cell.pilot
                research = cell.research
                control = cell.control_pilot
                verdict = (
                    "control" if candidate.candidate_id in CONTROL_IDS else _verdict(cell.bar_pass)
                )
                lines.append(
                    f"| `{candidate.candidate_id}` | `{cell.venue}` | {cell.era_id} | yes | "
                    f"{cell.bars} | {_metric(research.total_return if research else None)} | "
                    f"{_metric(pilot.total_return if pilot else None)} | "
                    f"{_metric(control.total_return if control else None)} | "
                    f"{_metric(cell.excess_vs_control_pilot)} | "
                    f"{_metric(pilot.sharpe if pilot else None, 'ratio')} | "
                    f"{_metric(pilot.max_drawdown if pilot else None)} | "
                    f"{_metric(pilot.one_way_turnover_per_year if pilot else None, 'ratio')} | "
                    f"{_metric(research.fee_drag if research else None)} | "
                    f"{_metric(pilot.fee_drag if pilot else None)} | {verdict} |"
                )
    if not any_row:
        lines.append(
            "| — | — | — | no | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | — |"
        )
    return lines


def _row_table(report: XsTopKReport) -> list[str]:
    lines = [
        (
            "| id | N | k | w | prints | covered | passed | failed | holdout fails | "
            "mean era excess (pilot) | dual-print | rank | selected | can promote |"
        ),
        (
            "| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | :---: | ---: | "
            ":---: | :---: |"
        ),
    ]
    ordered = sorted(
        report.rows,
        key=lambda row: (
            0 if row.candidate_id not in CONTROL_IDS else 1,
            row.dual_print_rank if row.dual_print_rank is not None else 10**9,
            row.candidate_id,
        ),
    )
    for row in ordered:
        lines.append(
            f"| `{row.candidate_id}` | {row.lookback if row.lookback is not None else '—'} | "
            f"{row.k if row.k is not None else '—'} | {row.weighting or '—'} | "
            f"{', '.join(row.venues) or 'none'} | {row.covered_cells} | {row.passed_cells} | "
            f"{row.failed_cells} | {row.holdout_failures} | "
            f"{_metric(row.mean_era_excess_pilot)} | {'yes' if row.dual_print else 'no'} | "
            f"{row.dual_print_rank if row.dual_print_rank is not None else '—'} | "
            f"{'yes' if row.selected else 'no'} | no |"
        )
    return lines


def render_xs_topk_markdown(report: XsTopKReport) -> str:
    lines: list[str] = [
        "# Long-only top-k cross-sectional momentum (wide Kraken USD universe)",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        "",
        "## Pre-registered header (frozen before any result below)",
        "",
        (
            f"- Universe listing: `{report.universe_listing_source or 'n/a'}` fetched "
            f"{report.universe_listing_fetched_at or 'n/a'}; "
            f"{report.universe_listing_size} candidate pairs after exclusions."
        ),
        f"- Exclusion rule: {report.exclusion_rule}",
        f"- Liquidity filter: `{report.liquidity_filter_rule}` (monthly, point-in-time).",
        (
            f"- Catalog `{report.catalog_name}`: see catalog_note/ids below; skip {TOPK_SKIP_DAYS}d; default-grid reference N={list(TOPK_LOOKBACKS)} (K=13 untouched); "
            f"k in {list(TOPK_KS)}; weights {list(TOPK_WEIGHTS)}; rebalance "
            f"`{report.rebalance_rule}`; MIN_CROSS_SECTION={MIN_CROSS_SECTION}; "
            f"eligibility N+{MIN_HISTORY_MARGIN} bars."
        ),
        f"- Ranking key: `{report.ranking_key}` (selection `{report.selection_rule}`).",
        f"- Portfolio bar: `{report.portfolio_bar_rule}`.",
        f"- Dual-print rule: `{report.dual_print_rule}`.",
        (
            f"- Eras (local constant pending #135): {report.era_ids}; a cell is covered "
            f"with >= {report.min_era_bars} daily bars."
        ),
        (
            f"- Costs: research fee={report.fee_bps:g} bps + slippage={report.slippage_bps:g} "
            f"bps; pilot tier taker={report.pilot_fee_bps:g} bps + slippage="
            f"{report.slippage_bps:g} bps ({report.pilot_tier_label}). The bar and the "
            "ranking use the pilot print."
        ),
        f"- Holdout: last {report.holdout_fraction:.0%} of each print (pilot cost).",
        f"- DSR / PBO: `{report.dsr_pbo_status}`.",
        (
            f"- `multi_venue_bar_preregistered={str(report.multi_venue_bar_preregistered).lower()}`; "
            f"`can_average_venues={str(report.can_average_venues).lower()}`; "
            f"`paper_path_ready={str(report.paper_path_ready).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        "",
        "## Data sources reached",
        "",
        "Print kind: committed daily spot OHLC bars per name; a skipped series is a skip, never a zero.",
        "",
    ]
    lines.extend(_print_source_table(report))
    lines.extend(
        [
            "",
            "## Honesty / pre-registered rules",
            "",
            report.honesty,
            "",
            "## Universe (point-in-time within a frozen listing)",
            "",
            report.universe_note,
            "",
            "## Pre-registered catalog",
            "",
            report.catalog_note,
            "",
            ("Frozen core ids: " + ", ".join(f"`{item}`" for item in report.catalog_ids) + "."),
            "",
            "## Paper path and RiskEngine layering",
            "",
            report.paper_path_note,
            "",
            report.layering_note,
            "",
            "## Kraken public OHLC cap",
            "",
            report.kraken_cap_note,
            "",
        ]
    )
    if report.data_notes:
        lines.extend(["## Data notes", ""])
        for note in report.data_notes:
            lines.append(f"- {note}")
        lines.append("")
    for result in report.prints:
        meta = result.meta
        if meta.skip_reasons:
            lines.extend([f"## Skipped on `{meta.venue}` (not invented)", ""])
            for reason in meta.skip_reasons:
                lines.append(f"- {reason}")
            if meta.names_skipped > len(meta.skip_reasons):
                lines.append(f"- … {meta.names_skipped - len(meta.skip_reasons)} more skipped.")
            lines.append("")
    lines.extend(
        [
            "## Dual-print passers (promotion ranking)",
            "",
            (
                f"Frozen ranking key: `{report.ranking_key}`. Only baskets that pass the "
                "portfolio bar on at least two independent covered cells with no failing "
                f"cell appear here. `{CONTROL_ID}` is excluded. Empty table = no promotee "
                "(success). A new Settings pin is added only if this table is non-empty, "
                "and then default **false**."
            ),
            "",
            "| dual rank | id | mean era excess vs ew_bh (pilot) | cells passed | selected | can flip flag |",
            "| ---: | --- | ---: | ---: | :---: | :---: |",
        ]
    )
    dual = [row for row in report.rows if row.dual_print and row.candidate_id not in CONTROL_IDS]
    dual.sort(key=lambda row: row.dual_print_rank or 10**9)
    if not dual:
        lines.append("| — | — | n/a | 0 | no | no |")
    for row in dual:
        lines.append(
            f"| {row.dual_print_rank} | `{row.candidate_id}` | "
            f"{_metric(row.mean_era_excess_pilot)} | {row.passed_cells} | "
            f"{'yes' if row.selected else 'no'} | no |"
        )
    lines.extend(
        [
            "",
            "## Era table (every covered venue x era cell; turnover and fee drag at both costs)",
            "",
            (
                "Net returns are basket total returns over the era. Fee drag is total "
                "fees / starting equity over the era at each cost print. One-way turnover "
                "per year is half the traded fraction of equity, annualised. Weekly "
                "rebalancing of a five-name basket is where this family usually dies; "
                "the pilot column makes that visible."
            ),
            "",
        ]
    )
    lines.extend(_era_table(report))
    lines.extend(["", "## Full catalog (informational)", ""])
    lines.extend(_row_table(report))
    lines.extend(
        [
            "",
            "## Operator recommendation",
            "",
            report.recommendation,
            "",
            (
                f"`keep_flag_false={str(report.keep_flag_false).lower()}`. "
                "Do not fabricate PnL. Do not enable live. Do not average venues. "
                "Do not widen MAX_OPEN_POSITIONS or the runtime allowlist for this "
                "family. Do not re-run the #117 top-1 catalog on the same window."
            ),
            "",
        ]
    )
    return "\n".join(lines)
