"""Weekly / low-turnover trend dual-print (Hypothesis C, 2026-09-26).

Frozen ``wk_trend_*`` catalog on Friday-UTC weekly bars resampled from
existing Kraken x Coinbase daily archives. Weekly-scaled #96+A+B+C.
Pilot fees 80+5. Never flips ``PAPER_PROMOTE_*``. Empty dual-print set
is success. Spot-executable path (unlike fund_z paper-perp).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.models import Side
from traderstack.research.harder_gates import (
    FEE_STRESS_MULTIPLIER,
    MAGNITUDE_RATIO_MIN,
    holdout_magnitude_ratio,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.miles_search import (
    evaluate_candidate_on_series,
    walkforward_candidate_on_window,
)
from traderstack.strategies import Regime, StrategySignal

# --- frozen recipe knobs (do not retune after PnL) ---
WEEKLY_INTERVAL = "1w"
RESAMPLE_RULE = "friday_utc_close"
TRAIN_SIZE = 40
TEST_SIZE = 10
STEP_SIZE = 10
HOLDOUT_FRACTION = 0.20
MIN_TRADES = 2
MULTIWINDOW_COUNT = 3
MULTIWINDOW_BARS = 34
MULTIWINDOW_TRAIN = 24
MULTIWINDOW_TEST = 10
MULTIWINDOW_MIN_PASSES = 2
MIN_WEEKLY_BARS = MULTIWINDOW_COUNT * MULTIWINDOW_BARS  # 102
DEFAULT_FEE_BPS = 80.0
DEFAULT_SLIPPAGE_BPS = 5.0
DEFAULT_KRAKEN_TIER = 1
KRAKEN_PRO_TIERS: dict[int, float] = {1: 80.0}
SECOND_PRINT_CONCURRENT = "concurrent_venue_harder_gates"
RANKING_KEY = "mean_holdout_excess_among_dual_print_passers"
PAPER_PATH_READY = True
CONTROL_IDS: frozenset[str] = frozenset()

GATE_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD")
REPORT_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")
ALIAS_TO_CANONICAL: dict[str, str] = {
    "BTC/USD": "BTC/USD",
    "BTCUSDT": "BTC/USD",
    "BTC-USD": "BTC/USD",
    "XBT/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
    "ETHUSDT": "ETH/USD",
    "ETH-USD": "ETH/USD",
    "SOL/USD": "SOL/USD",
    "SOLUSDT": "SOL/USD",
    "SOL-USD": "SOL/USD",
}

# (id, kind, p1, p2) — kind in {ma, donch, tsmom}
WEEKLY_CATALOG: tuple[tuple[str, str, int, int], ...] = (
    ("wk_trend_ma_4_12", "ma", 4, 12),
    ("wk_trend_ma_10_40", "ma", 10, 40),
    ("wk_trend_donch_20", "donch", 20, 0),
    ("wk_trend_donch_40", "donch", 40, 0),
    ("wk_trend_tsmom_12", "tsmom", 12, 0),
    ("wk_trend_tsmom_26", "tsmom", 26, 0),
)
WEEKLY_IDS: tuple[str, ...] = tuple(item[0] for item in WEEKLY_CATALOG)

WEEKLY_RULES = (
    "Pre-registered weekly / low-turnover trend dual-print "
    "(Hypothesis C, frozen before score). Resample: Friday UTC close "
    f"week (`{RESAMPLE_RULE}`) from existing 1d archives to `{WEEKLY_INTERVAL}`. "
    "Catalog: long-only weekly SMA cross (4/12, 10/40), weekly Donchian "
    "breakout+midpoint exit (20, 40), weekly TSMOM sign (12, 26). "
    f"WF train={TRAIN_SIZE}/test={TEST_SIZE}/step={STEP_SIZE}/"
    f"holdout={HOLDOUT_FRACTION}/min_trades={MIN_TRADES}. "
    f"Gate B: {MULTIWINDOW_COUNT}x{MULTIWINDOW_BARS} weekly windows, "
    f"in-window train={MULTIWINDOW_TRAIN}/test={MULTIWINDOW_TEST}, "
    f"min_passes={MULTIWINDOW_MIN_PASSES}. Gate A ratio "
    f"{MAGNITUDE_RATIO_MIN}; Gate C {FEE_STRESS_MULTIPLIER:g}x fees. "
    f"Dual-print: `{SECOND_PRINT_CONCURRENT}` Kraken x Coinbase. "
    f"Fees pilot {DEFAULT_FEE_BPS:g}+{DEFAULT_SLIPPAGE_BPS:g} bps. "
    "Not a retune of ens_trend_v2 / daily TSMOM / Donchian / xs-topk / "
    "sess-gap / vol-target / oi_mom. PAPER_PROMOTE_* stays false. "
    "Empty dual-print set is success. Spot-executable on Kraken."
)

WEEKLY_CATALOG_NOTE = (
    "Frozen catalog (K=6): "
    + ", ".join(f"`{i}`" for i in WEEKLY_IDS)
    + ". Do not grow after seeing PnL."
)


def _friday_of(day: datetime) -> datetime:
    """UTC midnight of the Friday in the same Mon-Sun week as ``day``."""
    d = day.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    # Monday=0 .. Sunday=6; Friday=4
    monday = d - timedelta(days=d.weekday())
    return monday + timedelta(days=4)


def resample_daily_to_friday_weekly(
    daily: tuple[Candle, ...],
) -> tuple[Candle, ...]:
    """Aggregate Mon-Fri daily bars into Friday-stamped weekly OHLCV.

    Skip weeks with no Friday bar (skip-not-invent). Weekend-only days
    never open a week alone.
    """
    if not daily:
        return ()
    symbol = daily[0].symbol
    # bucket: friday_ts -> list of Mon-Fri candles
    buckets: dict[datetime, list[Candle]] = {}
    for bar in daily:
        # Archives are expected to be daily; non-daily rows are still
        # bucketed by calendar week (caller supplies 1d dirs).
        opened = bar.opened_at.astimezone(UTC)
        if opened.weekday() > 4:
            continue  # Sat/Sun ignored for week construction
        friday = _friday_of(opened)
        buckets.setdefault(friday, []).append(bar)

    weekly: list[Candle] = []
    for friday in sorted(buckets):
        members = buckets[friday]
        # require an actual Friday bar
        friday_bars = [b for b in members if b.opened_at.astimezone(UTC).weekday() == 4]
        if not friday_bars:
            continue
        members_sorted = sorted(members, key=lambda b: b.opened_at)
        o = members_sorted[0].open
        h = max(b.high for b in members_sorted)
        lo = min(b.low for b in members_sorted)
        c = friday_bars[-1].close
        v = sum(b.volume for b in members_sorted)
        # ensure high/low contain open/close
        h = max(h, o, c)
        lo = min(lo, o, c)
        weekly.append(
            Candle(
                symbol=symbol,
                interval=WEEKLY_INTERVAL,
                opened_at=friday,
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=v,
            )
        )
    return tuple(weekly)


def resample_histories(
    histories: dict[str, tuple[Candle, ...]],
) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    """Resample every daily series; skip empties with notes."""
    out: dict[str, tuple[Candle, ...]] = {}
    notes: list[str] = []
    for key, candles in histories.items():
        if not candles:
            notes.append(f"{key}: empty daily; skipped")
            continue
        weekly = resample_daily_to_friday_weekly(candles)
        if not weekly:
            notes.append(f"{key}: no Friday weeks after resample; skipped")
            continue
        sym = weekly[0].symbol
        out[f"{sym}@{WEEKLY_INTERVAL}"] = weekly
        notes.append(
            f"{key}: {len(candles)} daily -> {len(weekly)} weekly "
            f"({weekly[0].opened_at.date()} -> {weekly[-1].opened_at.date()})"
        )
    return out, notes


def _sma(closes: list[float], window: int, index: int) -> float | None:
    if index + 1 < window or window <= 0:
        return None
    chunk = closes[index + 1 - window : index + 1]
    if len(chunk) < window or any(x <= 0 for x in chunk):
        return None
    return sum(chunk) / window


def ma_position_series(
    candles: tuple[Candle, ...], *, fast: int, slow: int
) -> tuple[tuple[datetime, float], ...]:
    if fast <= 0 or slow <= 0 or fast >= slow or len(candles) < slow:
        return ()
    closes = [b.close for b in candles]
    out: list[tuple[datetime, float]] = []
    for i in range(slow - 1, len(candles)):
        f = _sma(closes, fast, i)
        s = _sma(closes, slow, i)
        if f is None or s is None:
            continue
        out.append((candles[i].opened_at, 1.0 if f > s else 0.0))
    return tuple(out)


def tsmom_position_series(
    candles: tuple[Candle, ...], *, lookback: int
) -> tuple[tuple[datetime, float], ...]:
    if lookback <= 0 or len(candles) < lookback + 1:
        return ()
    out: list[tuple[datetime, float]] = []
    for i in range(lookback, len(candles)):
        start = candles[i - lookback].close
        end = candles[i].close
        if start <= 0 or end <= 0:
            continue
        ret = end / start - 1.0
        out.append((candles[i].opened_at, 1.0 if ret > 0 else 0.0))
    return tuple(out)


def donchian_position_series(
    candles: tuple[Candle, ...], *, lookback: int
) -> tuple[tuple[datetime, float], ...]:
    """Long when close > prior N max close; exit when close < channel midpoint."""
    if lookback <= 0 or len(candles) < lookback + 1:
        return ()
    out: list[tuple[datetime, float]] = []
    in_pos = False
    for i in range(lookback, len(candles)):
        prior = candles[i - lookback : i]
        prior_closes = [b.close for b in prior]
        prior_high = max(prior_closes)
        prior_low = min(prior_closes)
        mid = 0.5 * (prior_high + prior_low)
        close = candles[i].close
        if not in_pos:
            if close > prior_high:
                in_pos = True
        else:
            if close < mid:
                in_pos = False
        out.append((candles[i].opened_at, 1.0 if in_pos else 0.0))
    return tuple(out)


@dataclass(frozen=True)
class WeeklyAssignmentVoter:
    """Look up a precomputed same-bar long-only assignment (0 or 1)."""

    strategy_id: str
    signals_by_symbol: tuple[tuple[str, tuple[tuple[datetime, float], ...]], ...] = ()

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        cutoff = candles[-1].opened_at
        series = self.series_for(candles[-1].symbol)
        by_ts = {ts: value for ts, value in series}
        value = by_ts.get(cutoff)
        if value is None or value == 0.0:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="wk_trend: flat / warmup",
            )
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=Side.BUY,
            score=1.0,
            confidence=1.0,
            regime=regime,
            rationale="wk_trend: long",
        )

    def series_for(self, symbol: str) -> tuple[tuple[datetime, float], ...]:
        key = symbol.upper()
        for name, series in self.signals_by_symbol:
            if name.upper() == key:
                return series
        canonical = ALIAS_TO_CANONICAL.get(key)
        if canonical is None:
            return ()
        for name, series in self.signals_by_symbol:
            if ALIAS_TO_CANONICAL.get(name.upper()) == canonical:
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


def _position_for(
    kind: str, candles: tuple[Candle, ...], p1: int, p2: int
) -> tuple[tuple[datetime, float], ...]:
    if kind == "ma":
        return ma_position_series(candles, fast=p1, slow=p2)
    if kind == "donch":
        return donchian_position_series(candles, lookback=p1)
    if kind == "tsmom":
        return tsmom_position_series(candles, lookback=p1)
    return ()


def weekly_trend_candidates(
    histories: dict[str, tuple[Candle, ...]],
) -> tuple[SearchCandidate, ...]:
    by_canonical = _histories_by_canonical(histories)
    out: list[SearchCandidate] = []
    for candidate_id, kind, p1, p2 in WEEKLY_CATALOG:
        per_asset: dict[str, tuple[tuple[datetime, float], ...]] = {}
        for asset, candles in by_canonical.items():
            series = _position_for(kind, candles, p1, p2)
            if series:
                per_asset[asset] = series
        if not per_asset:
            continue
        by_symbol: list[tuple[str, tuple[tuple[datetime, float], ...]]] = []
        for alias, canonical in ALIAS_TO_CANONICAL.items():
            if canonical in per_asset:
                by_symbol.append((alias, per_asset[canonical]))
        label = {
            "ma": f"weekly SMA {p1}/{p2} long-only",
            "donch": f"weekly Donchian {p1} breakout+mid exit",
            "tsmom": f"weekly TSMOM sign {p1} long-only",
        }[kind]
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family="wk_trend",
                label=label,
                params={"kind": kind, "p1": p1, "p2": p2, "interval": WEEKLY_INTERVAL},
                strategy=WeeklyAssignmentVoter(
                    strategy_id=candidate_id,
                    signals_by_symbol=tuple(by_symbol),
                ),
            )
        )
    return tuple(out)


class AssetGateMetrics(BaseModel):
    symbol: str
    wf_total: float | None = None
    holdout_excess: float | None = None
    wf_trades: int = 0
    skipped_reason: str | None = None


class WeeklyCandidateResult(BaseModel):
    candidate_id: str
    label: str
    family: str = "wk_trend"
    per_asset: dict[str, AssetGateMetrics] = Field(default_factory=dict)
    mean_wf_total: float | None = None
    mean_holdout_excess: float | None = None
    gate96: bool = False
    gate_a: bool = False
    gate_b: bool = False
    gate_c: bool = False
    combined: bool = False
    magnitude_ratio: float | None = None
    multiwindow_passes: int = 0
    notes: list[str] = Field(default_factory=list)


class WeeklyTrendReport(BaseModel):
    generated_at: datetime
    recipe_commit: str | None = None
    print_kind: Literal["single_print", "dual_print", "unavailable"] = "unavailable"
    primary_venue: str = "kraken"
    second_venue: str | None = "coinbase"
    second_print_rule: str = SECOND_PRINT_CONCURRENT
    resample_rule: str = RESAMPLE_RULE
    fee_bps: float = DEFAULT_FEE_BPS
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS
    kraken_tier: int | None = DEFAULT_KRAKEN_TIER
    train_size: int = TRAIN_SIZE
    test_size: int = TEST_SIZE
    step_size: int = STEP_SIZE
    holdout_fraction: float = HOLDOUT_FRACTION
    min_trades: int = MIN_TRADES
    multiwindow_bars: int = MULTIWINDOW_BARS
    core_ids: list[str] = Field(default_factory=lambda: list(WEEKLY_IDS))
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    can_promote: bool = False
    keep_flag_false: bool = True
    paper_path_ready: bool = PAPER_PATH_READY
    rules: str = WEEKLY_RULES
    catalog_note: str = WEEKLY_CATALOG_NOTE
    history_notes: list[str] = Field(default_factory=list)
    primary: list[WeeklyCandidateResult] = Field(default_factory=list)
    second: list[WeeklyCandidateResult] = Field(default_factory=list)
    primary_weekly_bars: dict[str, int] = Field(default_factory=dict)
    second_weekly_bars: dict[str, int] = Field(default_factory=dict)

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _mean(vals: list[float]) -> float | None:
    if not vals:
        return None
    return sum(vals) / len(vals)


def _score_asset(
    candidate: SearchCandidate,
    candles: tuple[Candle, ...],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
) -> AssetGateMetrics:
    symbol = candles[0].symbol if candles else "unknown"
    row = evaluate_candidate_on_series(
        candidate,
        candles,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=TRAIN_SIZE,
        test_size=TEST_SIZE,
        step_size=STEP_SIZE,
        holdout_fraction=HOLDOUT_FRACTION,
        garch_min_train=50,
        garch_refit_every=20,
        garch_target_vol_ann=0.20,
    )
    return AssetGateMetrics(
        symbol=symbol,
        wf_total=row.walkforward_mean_total_return,
        holdout_excess=(None if row.holdout is None else row.holdout.excess_return),
        wf_trades=row.walkforward_trades,
        skipped_reason=row.skipped_reason,
    )


def _gate96_asset(m: AssetGateMetrics) -> bool:
    return (
        m.wf_total is not None
        and m.wf_total > 0
        and m.holdout_excess is not None
        and m.holdout_excess > 0
        and m.wf_trades >= MIN_TRADES
    )


def _multiwindow_passes(
    candidate: SearchCandidate,
    candles: tuple[Candle, ...],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
) -> int:
    if len(candles) < MIN_WEEKLY_BARS:
        return 0
    # take the most recent 3 * 34 bars
    window_src = candles[-MIN_WEEKLY_BARS:]
    passes = 0
    for w in range(MULTIWINDOW_COUNT):
        start = w * MULTIWINDOW_BARS
        end = start + MULTIWINDOW_BARS
        slice_bars = window_src[start:end]
        if len(slice_bars) < MULTIWINDOW_TRAIN + MULTIWINDOW_TEST:
            continue
        try:
            wf = walkforward_candidate_on_window(
                candidate,
                slice_bars,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                starting_equity=starting_equity,
                train_size=MULTIWINDOW_TRAIN,
                test_size=MULTIWINDOW_TEST,
                step_size=MULTIWINDOW_TEST,
            )
        except ValueError:
            continue
        if wf.mean_total_return > 0:
            passes += 1
    return passes


def _score_candidate_on_venue(
    candidate: SearchCandidate,
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float,
    starting_equity: float,
) -> WeeklyCandidateResult:
    by_canonical = _histories_by_canonical(histories)
    per_asset: dict[str, AssetGateMetrics] = {}
    notes: list[str] = []
    for symbol in REPORT_SYMBOLS:
        candles = by_canonical.get(symbol)
        if candles is None:
            notes.append(f"{symbol}: missing; skipped")
            continue
        if len(candles) < MIN_WEEKLY_BARS:
            notes.append(f"{symbol}: {len(candles)} weekly bars < {MIN_WEEKLY_BARS}; gate short")
        per_asset[symbol] = _score_asset(
            candidate,
            candles,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
        )

    btc = per_asset.get("BTC/USD")
    eth = per_asset.get("ETH/USD")
    gate96 = bool(btc is not None and eth is not None and _gate96_asset(btc) and _gate96_asset(eth))
    ratio = holdout_magnitude_ratio(
        None if btc is None else btc.holdout_excess,
        None if eth is None else eth.holdout_excess,
    )
    gate_a = bool(
        ratio is not None
        and ratio >= MAGNITUDE_RATIO_MIN
        and btc is not None
        and eth is not None
        and (btc.holdout_excess or 0) > 0
        and (eth.holdout_excess or 0) > 0
    )

    # Gate B: both BTC and ETH must clear min_passes on their own tapes
    b_passes = []
    for symbol in GATE_SYMBOLS:
        candles = by_canonical.get(symbol)
        if candles is None:
            b_passes.append(0)
            continue
        b_passes.append(
            _multiwindow_passes(
                candidate,
                candles,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                starting_equity=starting_equity,
            )
        )
    multiwindow_passes = min(b_passes) if b_passes else 0
    gate_b = multiwindow_passes >= MULTIWINDOW_MIN_PASSES

    # Gate C: 2x fees still clear #96 signs on BTC+ETH
    stress_fee = fee_bps * FEE_STRESS_MULTIPLIER
    stress_slip = slippage_bps * FEE_STRESS_MULTIPLIER
    stress_ok = True
    for symbol in GATE_SYMBOLS:
        candles = by_canonical.get(symbol)
        if candles is None:
            stress_ok = False
            break
        stressed = _score_asset(
            candidate,
            candles,
            fee_bps=stress_fee,
            slippage_bps=stress_slip,
            starting_equity=starting_equity,
        )
        if not _gate96_asset(stressed):
            stress_ok = False
            break
    gate_c = stress_ok

    wf_vals = [
        m.wf_total for sym, m in per_asset.items() if sym in GATE_SYMBOLS and m.wf_total is not None
    ]
    ho_vals = [
        m.holdout_excess
        for sym, m in per_asset.items()
        if sym in GATE_SYMBOLS and m.holdout_excess is not None
    ]
    combined = bool(gate96 and gate_a and gate_b and gate_c)
    return WeeklyCandidateResult(
        candidate_id=candidate.candidate_id,
        label=candidate.label,
        per_asset=per_asset,
        mean_wf_total=_mean([v for v in wf_vals if v is not None]),
        mean_holdout_excess=_mean([v for v in ho_vals if v is not None]),
        gate96=gate96,
        gate_a=gate_a,
        gate_b=gate_b,
        gate_c=gate_c,
        combined=combined,
        magnitude_ratio=ratio,
        multiwindow_passes=multiwindow_passes,
        notes=notes,
    )


def _venue_bar_counts(histories: dict[str, tuple[Candle, ...]]) -> dict[str, int]:
    by_canonical = _histories_by_canonical(histories)
    return {sym: len(by_canonical[sym]) for sym in REPORT_SYMBOLS if sym in by_canonical}


def _venue_usable(histories: dict[str, tuple[Candle, ...]]) -> bool:
    by_canonical = _histories_by_canonical(histories)
    for symbol in GATE_SYMBOLS:
        candles = by_canonical.get(symbol)
        if candles is None or len(candles) < MIN_WEEKLY_BARS:
            return False
    return True


def run_weekly_trend_search(
    kraken_daily: dict[str, tuple[Candle, ...]],
    coinbase_daily: dict[str, tuple[Candle, ...]] | None = None,
    *,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    starting_equity: float = 10_000.0,
    kraken_tier: int | None = DEFAULT_KRAKEN_TIER,
    recipe_commit: str | None = None,
    history_notes: list[str] | None = None,
    now: datetime | None = None,
    era_daily: dict[str, tuple[Candle, ...]] | None = None,
) -> WeeklyTrendReport:
    generated = now or datetime.now(UTC)
    notes = list(history_notes or [])

    kraken_weekly, kn = resample_histories(kraken_daily)
    notes.extend(f"kraken: {n}" for n in kn)
    if not _venue_usable(kraken_weekly):
        notes.append(
            f"kraken weekly BTC+ETH each need >= {MIN_WEEKLY_BARS} bars; print unavailable"
        )
        return WeeklyTrendReport(
            generated_at=generated,
            recipe_commit=recipe_commit,
            print_kind="unavailable",
            second_venue=None,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            kraken_tier=kraken_tier,
            history_notes=notes,
            primary_weekly_bars=_venue_bar_counts(kraken_weekly),
        )

    second_weekly: dict[str, tuple[Candle, ...]] = {}
    second_label: str | None = "coinbase"
    second_rule = SECOND_PRINT_CONCURRENT
    if coinbase_daily:
        second_weekly, sn = resample_histories(coinbase_daily)
        notes.extend(f"coinbase: {n}" for n in sn)
    if not _venue_usable(second_weekly):
        notes.append("coinbase concurrent weekly short/missing; trying era fallback")
        second_weekly = {}
        if era_daily:
            era_weekly, en = resample_histories(era_daily)
            notes.extend(f"era: {n}" for n in en)
            # non-overlapping: era last week must end before primary first week
            primary_first = min(c[0].opened_at for c in kraken_weekly.values() if c)
            era_ok = _venue_usable(era_weekly)
            if era_ok:
                era_last = max(c[-1].opened_at for c in era_weekly.values() if c)
                if era_last < primary_first:
                    second_weekly = era_weekly
                    second_label = "coinbase_era_2022_2024"
                    second_rule = "older_era_ending_before_primary_first_week"
                    notes.append(
                        f"era fallback accepted: last={era_last.date()} < "
                        f"primary_first={primary_first.date()}"
                    )
                else:
                    notes.append(
                        f"era overlaps primary (era_last={era_last.date()} >= "
                        f"{primary_first.date()}); skipped"
                    )
            else:
                notes.append("era weekly short/missing; skipped")
        if not second_weekly:
            notes.append("no usable second print; dual-print unavailable (success if empty)")
            # still score primary for transparency
            candidates = weekly_trend_candidates(kraken_weekly)
            primary_rows = [
                _score_candidate_on_venue(
                    c,
                    kraken_weekly,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    starting_equity=starting_equity,
                )
                for c in candidates
            ]
            return WeeklyTrendReport(
                generated_at=generated,
                recipe_commit=recipe_commit,
                print_kind="single_print",
                second_venue=None,
                second_print_rule=second_rule,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                kraken_tier=kraken_tier,
                history_notes=notes,
                primary=primary_rows,
                primary_weekly_bars=_venue_bar_counts(kraken_weekly),
                dual_print_passers=0,
            )

    # Rebuild candidates per venue so assignments match venue-local closes.
    primary_cands = weekly_trend_candidates(kraken_weekly)
    second_cands = weekly_trend_candidates(second_weekly)
    primary_rows = [
        _score_candidate_on_venue(
            c,
            kraken_weekly,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
        )
        for c in primary_cands
    ]
    second_by_id = {c.candidate_id: c for c in second_cands}
    second_rows = []
    for crow in primary_rows:
        sc = second_by_id.get(crow.candidate_id)
        if sc is None:
            second_rows.append(
                WeeklyCandidateResult(
                    candidate_id=crow.candidate_id,
                    label=crow.label,
                    notes=["missing on second venue"],
                )
            )
            continue
        second_rows.append(
            _score_candidate_on_venue(
                sc,
                second_weekly,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                starting_equity=starting_equity,
            )
        )

    primary_ok = {r.candidate_id for r in primary_rows if r.combined}
    second_ok = {r.candidate_id for r in second_rows if r.combined}
    passers = sorted(primary_ok & second_ok)

    return WeeklyTrendReport(
        generated_at=generated,
        recipe_commit=recipe_commit,
        print_kind="dual_print",
        second_venue=second_label,
        second_print_rule=second_rule,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        kraken_tier=kraken_tier,
        history_notes=notes,
        primary=primary_rows,
        second=second_rows,
        primary_weekly_bars=_venue_bar_counts(kraken_weekly),
        second_weekly_bars=_venue_bar_counts(second_weekly),
        dual_print_passer_ids=passers,
        dual_print_passers=len(passers),
        can_promote=False,
        keep_flag_false=True,
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _yn(flag: bool) -> str:
    return "yes" if flag else "no"


def render_weekly_trend_markdown(report: WeeklyTrendReport) -> str:
    lines = [
        "# Weekly / low-turnover trend dual-print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Recipe commit: `{report.recipe_commit or 'unknown'}`. "
            f"Print kind: **{report.print_kind}**. "
            f"venues=`{report.primary_venue}` x `{report.second_venue or 'none'}`; "
            f"resample=`{report.resample_rule}`; "
            f"second_rule=`{report.second_print_rule}`; "
            f"fees={report.fee_bps:g}+{report.slippage_bps:g} bps"
            + (f" (Kraken Pro tier {report.kraken_tier})" if report.kraken_tier is not None else "")
            + f"; can_promote=`{str(report.can_promote).lower()}`; "
            f"keep_flag_false=`{str(report.keep_flag_false).lower()}`; "
            f"dual_print_passers=`{report.dual_print_passers}`; "
            f"paper_path_ready=`{str(report.paper_path_ready).lower()}`"
        ),
        "",
        "## Rules",
        "",
        report.rules,
        "",
        report.catalog_note,
        "",
        "## History / resample notes",
        "",
    ]
    for note in report.history_notes:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            f"Primary weekly bars: `{report.primary_weekly_bars}`",
            f"Second weekly bars: `{report.second_weekly_bars}`",
            "",
            f"## Primary print ({report.primary_venue})",
            "",
            "| id | WF | holdout | #96 | A | B | C | combined |",
            "| --- | ---: | ---: | :---: | :---: | :---: | :---: | :---: |",
        ]
    )
    for row in report.primary:
        lines.append(
            f"| `{row.candidate_id}` | {_pct(row.mean_wf_total)} | "
            f"{_pct(row.mean_holdout_excess)} | {_yn(row.gate96)} | "
            f"{_yn(row.gate_a)} | {_yn(row.gate_b)} | {_yn(row.gate_c)} | "
            f"{_yn(row.combined)} |"
        )
    lines.extend(
        [
            "",
            f"## Second print ({report.second_venue or 'none'})",
            "",
            "| id | WF | holdout | #96 | A | B | C | combined |",
            "| --- | ---: | ---: | :---: | :---: | :---: | :---: | :---: |",
        ]
    )
    for row in report.second:
        lines.append(
            f"| `{row.candidate_id}` | {_pct(row.mean_wf_total)} | "
            f"{_pct(row.mean_holdout_excess)} | {_yn(row.gate96)} | "
            f"{_yn(row.gate_a)} | {_yn(row.gate_b)} | {_yn(row.gate_c)} | "
            f"{_yn(row.combined)} |"
        )
    lines.extend(
        [
            "",
            "## Dual-print passers",
            "",
            (
                ", ".join(f"`{i}`" for i in report.dual_print_passer_ids)
                if report.dual_print_passer_ids
                else "**0** dual-print passers."
            ),
            "",
            "## Promotion decision",
            "",
            (
                "**No candidate is promoted.** can_promote=false; "
                "keep_flag_false=true. Leave every PAPER_PROMOTE_*=false. "
                "No live path. Spot-executable only if a future pin PR names "
                "a dual-print passer (default false)."
            ),
            "",
        ]
    )
    return "\n".join(lines)
