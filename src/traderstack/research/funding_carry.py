"""Funding-rate / carry paper search (single-print unless two venues exist).

Pre-registered before any live pull (do not retune after seeing PnL).

Investigation (do not invent a series):

* Binance USDT-M ``/fapi/v1/fundingRate`` is historical and paginable when
  reachable; this environment typically gets HTTP 451.
* OKX ``/api/v5/public/funding-rate-history`` is public and typically
  returns ~90 days of 8h prints. That is **one venue / one history
  length**.
* A second candle venue (Binance.US older-720) without a second
  *funding* tape is not an independent funding print.
* Splitting one OKX tape into prefix/suffix is the same venue — not
  dual-print.
* Perp-spot basis is not on the public funding REST path and is not
  invented. Hedged carry PnL is funding income minus two-leg fees.

Print policy (frozen):

* Dual-print requires two **independent funding venues** (e.g. Binance
  and OKX) each covering BTC and ETH with a usable point count.
* Absent that, the run is **single-print** and **cannot promote**.
* #96+A+B+C hard gates need 720 aligned **daily** bars. A ~90d funding
  overlap cannot unlock them; they are recorded UNAVAILABLE, not faked.
* ``PAPER_PROMOTE_*`` stays default false. No live. Empty search is
  success. This module never writes a Settings pin.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.indicators import zscore
from traderstack.research.candidates import (
    SearchCandidate,
    _by_symbol,
    _feature_z_candidate,
    _ma,
    _mom,
    liquidation_z_agrees,
)
from traderstack.research.miles_candidates import EmaCrossoverStrategy
from traderstack.research.search import (
    CandidateSearchResult,
    StrategySearchReport,
    run_search,
)
from traderstack.strategies import Regime, StrategySignal

RANKING_KEY = "informational_wf_excess_single_print_cannot_promote"
SELECTION_RULE = "pre_registered_top1_informational"
PRINT_SINGLE = "single_print"
PRINT_DUAL = "dual_print"

REQUIRED_SYMBOLS = ("BTC/USD", "ETH/USD")
MIN_FUNDING_POINTS = 20
HARD_GATE_MIN_DAILY_BARS = 720
DEFAULT_INTERVAL = "4h"
ALLOWED_INTERVALS = ("4h", "1d", "1h")
CARRY_LEGS = 2
Z_LOOKBACK = 20

DEFAULT_TRAIN_SIZE = 180
DEFAULT_TEST_SIZE = 60
DEFAULT_STEP_SIZE = 60
DEFAULT_WARMUP = 31
SHORT_TRAIN_SIZE = 80
SHORT_TEST_SIZE = 40
SHORT_STEP_SIZE = 40
SHORT_WARMUP = 31
MIN_RESEARCH_BARS = SHORT_TRAIN_SIZE + SHORT_TEST_SIZE

FUNDING_Z_CATALOG: tuple[tuple[str, bool, float], ...] = (
    ("funding_z_fade_1_0", True, 1.0),
    ("funding_z_fade_1_5", True, 1.5),
    ("funding_z_fade_2_0", True, 2.0),
    ("funding_z_follow_1_0", False, 1.0),
    ("funding_z_follow_1_5", False, 1.5),
    ("funding_z_follow_2_0", False, 2.0),
)
OVERLAY_IDS: tuple[str, ...] = (
    "ema_9_21_funding_agree",
    "momentum_12_funding_agree",
)
CARRY_CATALOG: tuple[tuple[str, str, float | None, float | None], ...] = (
    ("carry_hedged_sign", "hedged cash-and-carry; always harvest |rate|", None, None),
    ("carry_hedged_abs_1bp", "hedged carry when |rate|>=1bp", 0.0001, None),
    ("carry_hedged_abs_3bp", "hedged carry when |rate|>=3bp", 0.0003, None),
    ("carry_hedged_z_1_5", "hedged carry when |z|>=1.5", None, 1.5),
)
CONTROL_IDS: frozenset[str] = frozenset({"ma_cross_10_30"})

FUNDING_Z_IDS: tuple[str, ...] = tuple(item[0] for item in FUNDING_Z_CATALOG)
CARRY_IDS: tuple[str, ...] = tuple(item[0] for item in CARRY_CATALOG)
CORE_IDS: tuple[str, ...] = FUNDING_Z_IDS + OVERLAY_IDS + CARRY_IDS + tuple(sorted(CONTROL_IDS))

FUNDING_CARRY_RULES = (
    "Pre-registered funding/carry search (frozen before any Kraken or "
    "funding-REST pull). Funding-z threshold voters and spot overlays "
    "instantiate only when an aligned funding series is supplied — never "
    "zero-filled. Hedged carry is a research model of cash-and-carry: "
    "received |funding| minus two-leg (spot+perp) fees on each flip; "
    "perp-spot basis is not invented and is not in the PnL. Dual-print "
    "requires two independent funding venues (e.g. Binance and OKX) each "
    "covering BTC and ETH. A second candle venue without a second funding "
    "tape is not dual-print. Same-venue prefix/suffix is not independent. "
    "Hard gates (#96+A+B+C) need 720 aligned daily bars; a ~90d OKX tape "
    "cannot unlock them. Absent two venues this run is SINGLE-PRINT and "
    "cannot promote. PAPER_PROMOTE_* stays default false. No live. "
    "Empty search is success."
)

FUNDING_CARRY_CATALOG_NOTE = (
    "Frozen catalog (K=13 when funding is present): funding-z fade/follow "
    "at |z|>=1.0 / 1.5 / 2.0 (spot signal); ema_9_21 and momentum_12 "
    "funding-agree overlays; hedged carry always-on plus |rate|>=1bp / "
    "3bp and |z|>=1.5; informational control ma_cross_10_30 on the same "
    "funding-overlap window. Do not grow this list after seeing PnL. "
    "Hedged carry is not paper-spot executable."
)


def _symbol_key(symbol: str) -> str:
    return symbol.upper()


def _lookup_series(
    mapping: dict[str, tuple[tuple[datetime, float], ...]] | None,
    symbol: str,
) -> tuple[tuple[datetime, float], ...] | None:
    if not mapping:
        return None
    key = _symbol_key(symbol)
    if key in mapping:
        return mapping[key]
    for name, series in mapping.items():
        if _symbol_key(name) == key:
            return series
    return None


def funding_usable(
    funding: tuple[tuple[datetime, float], ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    *,
    required: tuple[str, ...] = REQUIRED_SYMBOLS,
    min_points: int = MIN_FUNDING_POINTS,
) -> bool:
    """True only when every required symbol has a usable funding series."""
    if funding_by_symbol:
        for symbol in required:
            series = _lookup_series(funding_by_symbol, symbol)
            if series is None or len(series) < min_points:
                return False
        return True
    return funding is not None and len(funding) >= min_points


def venue_mean_points(
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
    *,
    required: tuple[str, ...] = REQUIRED_SYMBOLS,
) -> int:
    if not funding_usable(funding_by_symbol=funding_by_symbol, required=required):
        return 0
    assert funding_by_symbol is not None
    lengths = [len(_lookup_series(funding_by_symbol, symbol) or ()) for symbol in required]
    return int(sum(lengths) / len(lengths)) if lengths else 0


def choose_walkforward(
    n_research: int,
    *,
    train_size: int = DEFAULT_TRAIN_SIZE,
    test_size: int = DEFAULT_TEST_SIZE,
    step_size: int = DEFAULT_STEP_SIZE,
    warmup: int = DEFAULT_WARMUP,
) -> tuple[int, int, int, int] | None:
    """Return (train, test, step, warmup) that fit, or None if too short."""
    if n_research >= train_size + test_size and train_size > warmup and test_size > warmup:
        return train_size, test_size, step_size, warmup
    if (
        n_research >= MIN_RESEARCH_BARS
        and SHORT_TRAIN_SIZE > SHORT_WARMUP
        and SHORT_TEST_SIZE > SHORT_WARMUP
    ):
        return SHORT_TRAIN_SIZE, SHORT_TEST_SIZE, SHORT_STEP_SIZE, SHORT_WARMUP
    return None


def hard_gates_available(*, interval: str, aligned_bars: int) -> bool:
    return interval == "1d" and aligned_bars >= HARD_GATE_MIN_DAILY_BARS


def slice_to_funding_overlap(
    candles: tuple[Candle, ...],
    series: tuple[tuple[datetime, float], ...] | None,
) -> tuple[Candle, ...]:
    """Keep candles whose open is inside the funding tape. Skip-not-invent."""
    if not candles or not series:
        return ()
    first, last = series[0][0], series[-1][0]
    return tuple(candle for candle in candles if first <= candle.opened_at <= last)


def slice_histories_to_funding(
    histories: dict[str, tuple[Candle, ...]],
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
    funding: tuple[tuple[datetime, float], ...] | None = None,
) -> dict[str, tuple[Candle, ...]]:
    sliced: dict[str, tuple[Candle, ...]] = {}
    for key, candles in histories.items():
        if not candles:
            continue
        series = _lookup_series(funding_by_symbol, candles[0].symbol) or funding
        overlap = slice_to_funding_overlap(candles, series)
        if overlap:
            sliced[key] = overlap
    return sliced


@dataclass(frozen=True)
class FundingAgreeVoter:
    """Flatten a price voter unless funding-z agrees with the side (fade)."""

    inner: object
    strategy_id: str
    family: str
    funding: tuple[tuple[datetime, float], ...] = ()
    funding_by_symbol: tuple[tuple[str, tuple[tuple[datetime, float], ...]], ...] = ()
    lookback: int = Z_LOOKBACK
    entry_z: float = 1.0
    fade: bool = True

    def _series(self, symbol: str) -> tuple[tuple[datetime, float], ...]:
        key = symbol.upper()
        for name, series in self.funding_by_symbol:
            if name == key:
                return series
        return self.funding

    def _funding_z(self, candles: tuple[Candle, ...]) -> float | None:
        series = self._series(candles[-1].symbol)
        if not series:
            return None
        cutoff = candles[-1].opened_at
        recent = [value for ts, value in series if ts <= cutoff][-self.lookback :]
        if len(recent) < self.lookback:
            return None
        return zscore(recent[-1], recent)

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        evaluate = getattr(self.inner, "evaluate", None)
        if evaluate is None:
            raise TypeError("funding-agree inner voter is missing evaluate()")
        signal = evaluate(candles, regime)
        if signal.side is None:
            return signal.model_copy(update={"strategy_id": self.strategy_id})
        funding_z = self._funding_z(candles)
        if funding_z is None:
            return signal.model_copy(
                update={
                    "strategy_id": self.strategy_id,
                    "side": None,
                    "confidence": 0.0,
                    "rationale": f"{signal.rationale}; funding z unavailable",
                }
            )
        if not liquidation_z_agrees(
            signal.side, z_value=funding_z, entry_z=self.entry_z, fade=self.fade
        ):
            return signal.model_copy(
                update={
                    "strategy_id": self.strategy_id,
                    "side": None,
                    "confidence": 0.0,
                    "rationale": (
                        f"{signal.rationale}; funding z={funding_z:.3f} "
                        f"disagrees with {signal.side}"
                    ),
                }
            )
        return signal.model_copy(
            update={
                "strategy_id": self.strategy_id,
                "rationale": f"{signal.rationale}; funding z={funding_z:.3f} agrees",
            }
        )


def funding_z_candidates(
    *,
    funding: tuple[tuple[datetime, float], ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
) -> tuple[SearchCandidate, ...]:
    if not (funding or funding_by_symbol):
        return ()
    out: list[SearchCandidate] = []
    for candidate_id, fade, entry_z in FUNDING_Z_CATALOG:
        verb = "fade" if fade else "follow"
        out.append(
            _feature_z_candidate(
                candidate_id=candidate_id,
                family="funding_z",
                feature_name="funding_z",
                label=f"{verb} funding-rate z |z|>={entry_z:g}",
                values=funding,
                values_by_symbol=funding_by_symbol,
                fade=fade,
                entry_z=entry_z,
                lookback=Z_LOOKBACK,
            )
        )
    return tuple(out)


def overlay_candidates(
    *,
    funding: tuple[tuple[datetime, float], ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
) -> tuple[SearchCandidate, ...]:
    if not (funding or funding_by_symbol):
        return ()
    by_symbol = _by_symbol(funding_by_symbol)
    ema = EmaCrossoverStrategy(
        strategy_id="ema_9_21_funding_agree_inner", fast_span=9, slow_span=21
    )
    mom = _mom("momentum_12", lookback=12)
    return (
        SearchCandidate(
            candidate_id="ema_9_21_funding_agree",
            family="funding_z",
            label="EMA 9/21 (funding-z fade must agree)",
            params={
                "strategy_id": "ema_9_21_funding_agree",
                "fast_span": 9,
                "slow_span": 21,
                "funding_agree": True,
                "entry_z": 1.0,
            },
            strategy=FundingAgreeVoter(
                inner=ema,
                strategy_id="ema_9_21_funding_agree",
                family="ma_cross",
                funding=funding or (),
                funding_by_symbol=by_symbol,
            ),
            requires_feature="funding_z",
        ),
        SearchCandidate(
            candidate_id="momentum_12_funding_agree",
            family="funding_z",
            label="momentum 12 (funding-z fade must agree)",
            params={
                "strategy_id": "momentum_12_funding_agree",
                "lookback": 12,
                "funding_agree": True,
                "entry_z": 1.0,
            },
            strategy=FundingAgreeVoter(
                inner=mom.strategy,
                strategy_id="momentum_12_funding_agree",
                family="momentum",
                funding=funding or (),
                funding_by_symbol=by_symbol,
            ),
            requires_feature="funding_z",
        ),
    )


def spot_candidates(
    *,
    funding: tuple[tuple[datetime, float], ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
) -> tuple[SearchCandidate, ...]:
    if not (funding or funding_by_symbol):
        return ()
    return (
        funding_z_candidates(funding=funding, funding_by_symbol=funding_by_symbol)
        + overlay_candidates(funding=funding, funding_by_symbol=funding_by_symbol)
        + (_ma("ma_cross_10_30", short_window=10, long_window=30),)
    )


def skipped_funding_families(
    *,
    funding: tuple[tuple[datetime, float], ...] | None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> list[dict[str, str]]:
    if funding is not None or funding_by_symbol:
        return []
    skipped: list[dict[str, str]] = []
    for candidate_id, fade, entry_z in FUNDING_Z_CATALOG:
        verb = "fade" if fade else "follow"
        skipped.append(
            {
                "family": "funding_z",
                "candidate_id": candidate_id,
                "reason": (
                    f"{verb} funding-rate z |z|>={entry_z:g}: skipped — no "
                    "aligned funding series. Skip rather than invent a z."
                ),
            }
        )
    for candidate_id in OVERLAY_IDS:
        skipped.append(
            {
                "family": "funding_z",
                "candidate_id": candidate_id,
                "reason": (
                    f"{candidate_id}: skipped — no aligned funding series for the overlay gate."
                ),
            }
        )
    for candidate_id, label, *_rest in CARRY_CATALOG:
        skipped.append(
            {
                "family": "carry",
                "candidate_id": candidate_id,
                "reason": f"{label}: skipped — no aligned funding series.",
            }
        )
    return skipped


def _want_harvest(
    history: list[float],
    *,
    abs_threshold: float | None,
    z_threshold: float | None,
    lookback: int = Z_LOOKBACK,
) -> bool:
    if not history:
        return False
    last = history[-1]
    if abs_threshold is not None and abs(last) < abs_threshold:
        return False
    if z_threshold is not None:
        if len(history) < lookback:
            return False
        window = history[-lookback:]
        if abs(zscore(window[-1], window)) < z_threshold:
            return False
    return True


def _compound(returns: list[float]) -> float:
    equity = 1.0
    for item in returns:
        equity *= 1.0 + item
    return equity - 1.0


def score_hedged_carry(
    series: tuple[tuple[datetime, float], ...],
    *,
    abs_threshold: float | None,
    z_threshold: float | None,
    fee_bps: float,
    slippage_bps: float,
    legs: int = CARRY_LEGS,
    holdout_fraction: float = 0.20,
    train_size: int = DEFAULT_TRAIN_SIZE,
    test_size: int = DEFAULT_TEST_SIZE,
    step_size: int = DEFAULT_STEP_SIZE,
    min_trades: int = 1,
) -> dict[str, float | int | str | None]:
    """Point-in-time hedged carry on a single funding tape.

    Decision at print *i* uses only prints ``[:i]`` (the current rate is
    collected only if already in). Basis is not modeled.
    """
    cost = legs * (fee_bps + slippage_bps) / 10_000.0
    position = False
    flips = 0
    per_print: list[float] = []
    for index, (_ts, rate) in enumerate(series):
        history = [value for _when, value in series[:index]]
        want = _want_harvest(history, abs_threshold=abs_threshold, z_threshold=z_threshold)
        income = 0.0
        fee = 0.0
        if want != position:
            fee = cost
            flips += 1
            position = want
        if position:
            income = abs(rate)
        per_print.append(income - fee)

    if len(per_print) < 2:
        return {
            "print_count": len(series),
            "flips": flips,
            "skipped_reason": "funding tape too short to score",
            "mean_wf_total_return": None,
            "mean_wf_excess_return": None,
            "mean_holdout_total_return": None,
            "mean_holdout_excess_return": None,
            "total_wf_trades": 0,
            "total_holdout_trades": 0,
            "full_sample_total_return": None,
        }

    holdout_size = max(int(len(per_print) * holdout_fraction), 1)
    if holdout_size >= len(per_print):
        holdout_size = max(1, len(per_print) // 5)
    research = per_print[:-holdout_size]
    holdout = per_print[-holdout_size:]
    sizes = choose_walkforward(
        len(research),
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        warmup=0,
    )
    fold_totals: list[float] = []
    if sizes is not None:
        train, test, step, _warmup = sizes
        start = 0
        while True:
            test_start = start + train
            test_end = test_start + test
            if test_end > len(research):
                break
            fold_totals.append(_compound(research[test_start:test_end]))
            start += step
    holdout_total = _compound(holdout) if holdout else None
    wf_mean = sum(fold_totals) / len(fold_totals) if fold_totals else None
    return {
        "print_count": len(series),
        "research_prints": len(research),
        "holdout_prints": len(holdout),
        "flips": flips,
        "skipped_reason": None if fold_totals else "walkforward_insufficient_prints",
        "mean_wf_total_return": wf_mean,
        "mean_wf_excess_return": wf_mean,
        "mean_holdout_total_return": holdout_total,
        "mean_holdout_excess_return": holdout_total,
        "total_wf_trades": flips if fold_totals else 0,
        "total_holdout_trades": min_trades if holdout else 0,
        "full_sample_total_return": _compound(per_print),
        "fold_count": len(fold_totals),
    }


class CarryCandidateResult(BaseModel):
    candidate_id: str
    family: str = "carry"
    label: str
    executable_on_paper_spot: bool = False
    per_asset: dict[str, dict[str, float | int | str | None]] = Field(default_factory=dict)
    mean_wf_total_return: float | None = None
    mean_wf_excess_return: float | None = None
    mean_holdout_total_return: float | None = None
    mean_holdout_excess_return: float | None = None
    full_sample_total_return: float | None = None
    rankable: bool = False
    eligible: bool = False
    ineligible_reasons: list[str] = Field(default_factory=list)
    promoted: bool = False


class FundingCarryReport(BaseModel):
    generated_at: datetime
    interval: str
    print_kind: Literal["single_print", "dual_print"]
    primary_venue: str | None = None
    second_venue: str | None = None
    hard_gates_available: bool
    hard_gates_note: str
    wf_adapted: bool
    wf_train_size: int | None = None
    wf_test_size: int | None = None
    wf_step_size: int | None = None
    wf_warmup: int | None = None
    can_promote: bool
    keep_flag_false: bool = True
    ranking_key: str = RANKING_KEY
    selection_rule: str = SELECTION_RULE
    honesty: str
    catalog_note: str
    print_rules: str
    core_ids: list[str]
    scored_ids: list[str]
    control_ids: list[str]
    skipped_feature_families: list[dict[str, str]] = Field(default_factory=list)
    edge_notes: list[dict[str, str]] = Field(default_factory=list)
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    search: StrategySearchReport | None = None
    carry: list[CarryCandidateResult] = Field(default_factory=list)
    second_search: StrategySearchReport | None = None
    second_carry: list[CarryCandidateResult] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    any_promoted: bool = False
    promoted_candidate_ids: list[str] = Field(default_factory=list)
    recommended_promote_flag: str | None = None
    fee_bps: float
    slippage_bps: float
    carry_legs: int = CARRY_LEGS


def _clear_promotion(report: StrategySearchReport) -> StrategySearchReport:
    cleared = [
        row.model_copy(update={"promoted": False, "selected": row.selected})
        for row in report.candidates
    ]
    return report.model_copy(
        update={
            "candidates": cleared,
            "promoted_candidate_ids": [],
            "any_promoted": False,
            "allowed_promote_id": None,
            "honesty": (
                report.honesty + " This funding/carry search cannot flip "
                "PAPER_PROMOTE_*; a single-print or short tape is not a pin."
            ),
        }
    )


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _score_carry_catalog(
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
    funding: tuple[tuple[datetime, float], ...] | None,
    *,
    fee_bps: float,
    slippage_bps: float,
    holdout_fraction: float,
    train_size: int,
    test_size: int,
    step_size: int,
    min_trades: int,
    required: tuple[str, ...] = REQUIRED_SYMBOLS,
) -> list[CarryCandidateResult]:
    rows: list[CarryCandidateResult] = []
    for candidate_id, label, abs_threshold, z_threshold in CARRY_CATALOG:
        per_asset: dict[str, dict[str, float | int | str | None]] = {}
        symbols = required if funding_by_symbol else ("ALL",)
        for symbol in symbols:
            series = _lookup_series(funding_by_symbol, symbol) if symbol != "ALL" else funding
            if series is None:
                continue
            per_asset[symbol] = score_hedged_carry(
                series,
                abs_threshold=abs_threshold,
                z_threshold=z_threshold,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                holdout_fraction=holdout_fraction,
                train_size=train_size,
                test_size=test_size,
                step_size=step_size,
                min_trades=min_trades,
            )
        wf_total: list[float] = []
        ho_total: list[float] = []
        full: list[float] = []
        for metrics in per_asset.values():
            wf_value = metrics.get("mean_wf_total_return")
            ho_value = metrics.get("mean_holdout_total_return")
            full_value = metrics.get("full_sample_total_return")
            if isinstance(wf_value, float):
                wf_total.append(wf_value)
            if isinstance(ho_value, float):
                ho_total.append(ho_value)
            if isinstance(full_value, float):
                full.append(full_value)
        reasons: list[str] = []
        mean_wf = _mean(wf_total)
        mean_ho = _mean(ho_total)
        if mean_wf is None:
            reasons.append("walkforward_missing")
        elif mean_wf <= 0:
            reasons.append("walkforward_total_return_not_positive")
        if mean_ho is None:
            reasons.append("holdout_missing")
        elif mean_ho <= 0:
            reasons.append("holdout_excess_return_not_positive")
        rows.append(
            CarryCandidateResult(
                candidate_id=candidate_id,
                label=label,
                per_asset=per_asset,
                mean_wf_total_return=mean_wf,
                mean_wf_excess_return=mean_wf,
                mean_holdout_total_return=mean_ho,
                mean_holdout_excess_return=mean_ho,
                full_sample_total_return=_mean(full),
                rankable=mean_wf is not None,
                eligible=not reasons,
                ineligible_reasons=reasons,
            )
        )
    return rows


def run_funding_carry(
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    warmup: int = DEFAULT_WARMUP,
    train_size: int = DEFAULT_TRAIN_SIZE,
    test_size: int = DEFAULT_TEST_SIZE,
    step_size: int = DEFAULT_STEP_SIZE,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    interval: str = DEFAULT_INTERVAL,
    funding: tuple[tuple[datetime, float], ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    primary_venue: str | None = None,
    second_funding: tuple[tuple[datetime, float], ...] | None = None,
    second_funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    second_venue: str | None = None,
    second_histories: dict[str, tuple[Candle, ...]] | None = None,
    history_notes: list[dict[str, str]] | None = None,
    edge_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> FundingCarryReport:
    if not histories:
        raise ValueError("no candle histories provided")

    have_primary = funding_usable(funding, funding_by_symbol)
    have_second = funding_usable(second_funding, second_funding_by_symbol)
    print_kind: Literal["single_print", "dual_print"]
    if have_primary and have_second:
        print_kind = "dual_print"
    else:
        print_kind = "single_print"

    sliced = (
        slice_histories_to_funding(histories, funding_by_symbol, funding) if have_primary else {}
    )
    aligned_bars = min((len(item) for item in sliced.values()), default=0)
    gates_ok = hard_gates_available(interval=interval, aligned_bars=aligned_bars)
    n_research = int(aligned_bars * (1.0 - holdout_fraction)) if aligned_bars else 0
    sizes = choose_walkforward(
        n_research,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        warmup=warmup,
    )
    wf_adapted = False
    use_train, use_test, use_step, use_warmup = train_size, test_size, step_size, warmup
    if sizes is not None:
        use_train, use_test, use_step, use_warmup = sizes
        wf_adapted = sizes != (train_size, test_size, step_size, warmup)
    elif have_primary:
        wf_adapted = True

    catalog = spot_candidates(funding=funding, funding_by_symbol=funding_by_symbol)
    scored_ids = [item.candidate_id for item in catalog]
    if have_primary:
        scored_ids.extend(CARRY_IDS)

    search: StrategySearchReport | None = None
    generated = now
    if catalog and sliced:
        search = _clear_promotion(
            run_search(
                sliced,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                starting_equity=starting_equity,
                warmup=use_warmup,
                train_size=use_train,
                test_size=use_test,
                step_size=use_step,
                holdout_fraction=holdout_fraction,
                min_trades=min_trades,
                candidates=catalog,
                history_notes=history_notes,
                edge_notes=edge_notes,
                now=now,
                include_feature_candidates=False,
            )
        )
    if generated is None:
        generated = datetime.now(UTC)

    carry_rows = (
        _score_carry_catalog(
            funding_by_symbol,
            funding,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            holdout_fraction=holdout_fraction,
            train_size=use_train,
            test_size=use_test,
            step_size=use_step,
            min_trades=min_trades,
        )
        if have_primary
        else []
    )

    second_search: StrategySearchReport | None = None
    second_carry: list[CarryCandidateResult] = []
    dual_passers: list[str] = []
    if print_kind == PRINT_DUAL:
        second_sliced = slice_histories_to_funding(
            second_histories or histories,
            second_funding_by_symbol,
            second_funding,
        )
        second_catalog = spot_candidates(
            funding=second_funding, funding_by_symbol=second_funding_by_symbol
        )
        if second_catalog and second_sliced:
            second_search = _clear_promotion(
                run_search(
                    second_sliced,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    starting_equity=starting_equity,
                    warmup=use_warmup,
                    train_size=use_train,
                    test_size=use_test,
                    step_size=use_step,
                    holdout_fraction=holdout_fraction,
                    min_trades=min_trades,
                    candidates=second_catalog,
                    now=now,
                    include_feature_candidates=False,
                )
            )
        second_carry = _score_carry_catalog(
            second_funding_by_symbol,
            second_funding,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            holdout_fraction=holdout_fraction,
            train_size=use_train,
            test_size=use_test,
            step_size=use_step,
            min_trades=min_trades,
        )
        primary_eligible = {
            row.candidate_id
            for row in (search.candidates if search is not None else [])
            if row.eligible and row.candidate_id not in CONTROL_IDS
        }
        primary_eligible.update(row.candidate_id for row in carry_rows if row.eligible)
        second_eligible = {
            row.candidate_id
            for row in (second_search.candidates if second_search is not None else [])
            if row.eligible and row.candidate_id not in CONTROL_IDS
        }
        second_eligible.update(row.candidate_id for row in second_carry if row.eligible)
        dual_passers = sorted(primary_eligible & second_eligible)

    skipped = skipped_funding_families(
        funding=funding if have_primary else None,
        funding_by_symbol=funding_by_symbol if have_primary else None,
    )
    honesty = FUNDING_CARRY_RULES
    if print_kind == PRINT_SINGLE:
        honesty += (
            " This run is labeled SINGLE-PRINT and cannot promote, even if a "
            "funding-z or carry row would clear a fee-aware sign check."
        )
    if not have_primary:
        honesty += " No usable funding series — voters were skipped, not zero-filled."
    if not gates_ok:
        honesty += (
            " Hard gates (#96+A+B+C) are UNAVAILABLE on this overlap "
            f"(interval={interval}, aligned_bars={aligned_bars}; need 1d and "
            f">={HARD_GATE_MIN_DAILY_BARS})."
        )
    if wf_adapted:
        honesty += (
            f" Walk-forward sizes adapted to the funding overlap "
            f"(train={use_train} test={use_test} step={use_step} "
            f"warmup={use_warmup})."
        )
    if dual_passers:
        honesty += (
            f" Dual-print eligible names ({', '.join(dual_passers)}) are "
            "informational only; leave every PAPER_PROMOTE_* false."
        )

    generated_at = search.generated_at if search is not None else (now or generated)
    selected = search.selected_candidate_id if search is not None else None
    return FundingCarryReport(
        generated_at=generated_at,
        interval=interval,
        print_kind=print_kind,
        primary_venue=primary_venue,
        second_venue=second_venue if have_second else None,
        hard_gates_available=gates_ok,
        hard_gates_note=(
            "available"
            if gates_ok
            else (
                f"UNAVAILABLE: need interval=1d and >={HARD_GATE_MIN_DAILY_BARS} "
                f"aligned bars; got interval={interval}, aligned_bars={aligned_bars}"
            )
        ),
        wf_adapted=wf_adapted,
        wf_train_size=use_train if have_primary else None,
        wf_test_size=use_test if have_primary else None,
        wf_step_size=use_step if have_primary else None,
        wf_warmup=use_warmup if have_primary else None,
        can_promote=False,
        honesty=honesty,
        catalog_note=FUNDING_CARRY_CATALOG_NOTE,
        print_rules=FUNDING_CARRY_RULES,
        core_ids=list(CORE_IDS),
        scored_ids=scored_ids,
        control_ids=sorted(CONTROL_IDS),
        skipped_feature_families=skipped,
        edge_notes=list(edge_notes or []),
        history_notes=list(history_notes or []),
        search=search,
        carry=carry_rows,
        second_search=second_search,
        second_carry=second_carry,
        selected_candidate_id=selected,
        dual_print_passer_ids=dual_passers,
        any_promoted=False,
        promoted_candidate_ids=[],
        recommended_promote_flag=None,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2%}"


def _row_by_id(report: StrategySearchReport, candidate_id: str) -> CandidateSearchResult | None:
    for row in report.candidates:
        if row.candidate_id == candidate_id:
            return row
    return None


def render_funding_carry_markdown(report: FundingCarryReport) -> str:
    lines: list[str] = [
        "# Funding / carry strategy search",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. "
            f"interval=`{report.interval}`; "
            f"primary_venue=`{report.primary_venue or 'none'}`; "
            f"second_venue=`{report.second_venue or 'none'}`; "
            f"hard_gates_available=`{str(report.hard_gates_available).lower()}`; "
            f"can_promote=`{str(report.can_promote).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        (
            f"Core K={len(report.core_ids)}; scored ids={len(report.scored_ids)}; "
            f"ranking_key=`{report.ranking_key}` (informational)."
        ),
        (
            f"Costs: fee={report.fee_bps:g} bps + slippage={report.slippage_bps:g} bps "
            f"(spot overlays); hedged carry pays {report.carry_legs} legs × "
            f"(fee+slip) on each flip. Basis is not modeled."
        ),
        (
            "Walk-forward: "
            + (
                f"train={report.wf_train_size} test={report.wf_test_size} "
                f"step={report.wf_step_size} warmup={report.wf_warmup}"
                + (" (adapted to funding overlap)" if report.wf_adapted else "")
                if report.wf_train_size is not None
                else "not run (no funding series)"
            )
            + "."
        ),
        f"Hard gates: {report.hard_gates_note}.",
        "",
        "## What this does / does not claim",
        "",
        (
            "This is a paper-research catalog of funding-z thresholds, "
            "funding-agree spot overlays, and a modeled hedged cash-and-carry. "
            "It is **not** a live-capital claim, not a fabricated PnL, and "
            "not a reason to flip `PAPER_PROMOTE_*` or `TRADING_MODE`. "
            "Hedged carry is **not** executable on the Kraken paper-spot path."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.honesty,
        "",
        "## Print policy (frozen before scoring)",
        "",
        report.print_rules,
        "",
        "| print | when | can promote? |",
        "| --- | --- | --- |",
        (
            "| single-print | only one usable funding venue on BTC+ETH "
            "(typical: OKX ~90d; Binance HTTP 451) | **no** |"
        ),
        (
            "| dual-print | two independent funding venues each covering "
            "BTC and ETH | still **no** Settings flip; a passer would only "
            "justify a documented default-false pin |"
        ),
        "",
        "## Pre-registered catalog",
        "",
        report.catalog_note,
        "",
        f"Frozen ids: {', '.join(f'`{item}`' for item in report.core_ids)}.",
        "",
        "Unconditioned control (cannot promote): "
        + ", ".join(f"`{item}`" for item in report.control_ids)
        + ".",
        "",
        "## Data",
        "",
    ]
    if report.history_notes:
        for item in report.history_notes:
            detail = item.get("note") or item.get("reason") or ""
            symbol = item.get("symbol") or item.get("name") or ""
            if symbol and symbol != "?":
                lines.append(
                    f"- `{symbol}` {item.get('interval', '')} "
                    f"source={item.get('source', '?')} "
                    f"n={item.get('candles', item.get('candle_count', '?'))}"
                    + (f" — {detail}" if detail else "")
                )
            elif detail:
                lines.append(f"- {detail}")
    else:
        lines.append("- (no history notes)")

    lines.extend(["", "## Funding series", ""])
    if report.edge_notes:
        for item in report.edge_notes:
            lines.append(
                f"- `{item.get('name', '?')}` **{item.get('status', '?')}**: "
                f"{item.get('reason', '')} (source={item.get('source', '')}, "
                f"points={item.get('points', '0')})"
            )
    else:
        lines.append("- No funding-series fetch notes. Families were not supplied.")

    if report.skipped_feature_families:
        lines.extend(["", "## Skipped families", ""])
        for item in report.skipped_feature_families:
            lines.append(f"- `{item['candidate_id']}` ({item['family']}): {item['reason']}")

    lines.extend(
        [
            "",
            "## Spot-signal / overlay (walk-forward mean excess after fees)",
            "",
            (
                "Informational. Eligible under a fee-aware sign check does not mean "
                "promoted. Control cannot promote. Scored only on the funding-overlap "
                "window (skip-not-invent extra unfunded history)."
            ),
            "",
            "| rank | id | family | WF excess | WF total | holdout excess | eligible | control |",
            "| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |",
        ]
    )
    if report.search is None or not report.search.candidates:
        lines.append("| — | *(none scored)* |  |  |  |  |  |  |")
    else:
        ordered = sorted(
            report.search.candidates,
            key=lambda row: (
                row.rank is None,
                row.rank if row.rank is not None else 10_000,
                row.candidate_id,
            ),
        )
        for row in ordered:
            rank = str(row.rank) if row.rank is not None else "—"
            control = "yes" if row.candidate_id in CONTROL_IDS else "no"
            lines.append(
                f"| {rank} | `{row.candidate_id}` | {row.family} | "
                f"{_pct(row.mean_wf_excess_return)} | "
                f"{_pct(row.mean_wf_total_return)} | "
                f"{_pct(row.mean_holdout_excess_return)} | "
                f"{'yes' if row.eligible else 'no'} | {control} |"
            )

    lines.extend(
        [
            "",
            "## Hedged carry (modeled; basis not invented)",
            "",
            (
                "PnL = received |funding| while harvesting, minus two-leg "
                "(fee+slippage) on each flip. Decision at print *i* uses only "
                "prints before *i*. Excess is versus cash (0), not versus spot "
                "buy-and-hold. Not paper-spot executable."
            ),
            "",
            "| id | WF total | holdout total | full-sample | eligible |",
            "| --- | ---: | ---: | ---: | :---: |",
        ]
    )
    if not report.carry:
        lines.append("| *(none scored)* |  |  |  |  |")
    else:
        for carry_row in report.carry:
            lines.append(
                f"| `{carry_row.candidate_id}` | "
                f"{_pct(carry_row.mean_wf_total_return)} | "
                f"{_pct(carry_row.mean_holdout_total_return)} | "
                f"{_pct(carry_row.full_sample_total_return)} | "
                f"{'yes' if carry_row.eligible else 'no'} |"
            )

    lines.extend(["", "## Dual-print passers", ""])
    if report.print_kind != PRINT_DUAL:
        lines.append("Not a dual-print run. One venue / one history length cannot promote.")
    elif not report.dual_print_passer_ids:
        lines.append(
            "Dual-print was eligible (two independent funding venues) but "
            "no name cleared the fee-aware bar on **both** prints. "
            "Empty set is success."
        )
    else:
        lines.append(
            "Names that cleared the fee-aware bar on both funding venues "
            "(informational; no Settings pin): "
            + ", ".join(f"`{item}`" for item in report.dual_print_passer_ids)
            + "."
        )

    lines.extend(
        [
            "",
            "## Promotion decision",
            "",
            (
                "**No candidate is promoted.** "
                f"print_kind=`{report.print_kind}`; "
                f"hard_gates_available=`{str(report.hard_gates_available).lower()}`; "
                f"can_promote=`{str(report.can_promote).lower()}`; "
                "recommended_promote_flag=`none`. "
                "Leave every `PAPER_PROMOTE_*` false. Do not add a new pin. "
                "Do not enable live."
            ),
        ]
    )
    if report.selected_candidate_id and report.search is not None:
        selected = _row_by_id(report.search, report.selected_candidate_id)
        if selected is not None:
            lines.append(
                f"Informational spot-signal top-1 by WF excess was "
                f"`{selected.candidate_id}` "
                f"(WF excess={_pct(selected.mean_wf_excess_return)}, "
                f"WF total={_pct(selected.mean_wf_total_return)}, "
                f"holdout excess={_pct(selected.mean_holdout_excess_return)}; "
                f"eligible={selected.eligible})."
            )
    lines.append("")
    return "\n".join(lines)
