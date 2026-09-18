"""Vol-target size overlay on frozen ma_cross_10_30 (paper research).

Pre-registered catalog: unit-weight control ``ma_cross_10_30`` plus
reduce-only realised-vol scalars at 15% / 25% / 50% annualised
(``ma_cross_10_30_vt15|vt25|vt50``). Direction is always-on SMA 10/30.
Sizing uses ``sign(side) * min(target / ann_realised_vol, 1.0)`` via
miles ``weight_from_score``. Dual-print = Kraken x Coinbase spot BTC/ETH
at pilot 80+5 bps. Control cannot promote. Never flips ``PAPER_PROMOTE_*``.
Skip-not-invent; empty dual-print is success.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
from typing import Literal

from pydantic import BaseModel, Field

from traderstack.candles import Candle, periods_per_year
from traderstack.indicators import moving_average, realized_volatility
from traderstack.models import Side
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.miles_search import (
    MilesSearchReport,
    run_miles_search,
)
from traderstack.strategies import Regime, StrategySignal

VOL_TARGET_RULES = (
    "Pre-registered vol-target size overlay on frozen ma_cross_10_30 "
    "(frozen before any score). Direction: always-on SMA short=10 / long=30. "
    "Overlays size with min(target_ann / ann_realised_vol_20, 1.0) where "
    "ann_realised_vol is std of the last 20 simple close-to-close returns "
    "through the decision bar times sqrt(periods_per_year). Insufficient "
    "history -> flat (skip-not-invent, never zero-filled). Max leverage 1.0 "
    "(reduce-only). Catalog: control ma_cross_10_30 (unit +/-1, cannot "
    "promote) + ma_cross_10_30_vt15/vt25/vt50. Dual-print = Kraken x "
    "Coinbase spot BTC/ETH; venues never averaged. Pilot fee 80+5 bps. "
    "PAPER_PROMOTE_* stays default false. Empty dual-print set is success. "
    "Not a Miles EMA+GARCH reprint, not session-gap, not funding-div."
)

CONTROL_ID = "ma_cross_10_30"
CONTROL_IDS: frozenset[str] = frozenset({CONTROL_ID})

# (id, target_vol_ann or None for unit weight)
VOL_TARGET_CATALOG: tuple[tuple[str, float | None], ...] = (
    (CONTROL_ID, None),
    ("ma_cross_10_30_vt15", 0.15),
    ("ma_cross_10_30_vt25", 0.25),
    ("ma_cross_10_30_vt50", 0.50),
)
VOL_TARGET_IDS: tuple[str, ...] = tuple(item[0] for item in VOL_TARGET_CATALOG)
OVERLAY_IDS: tuple[str, ...] = tuple(
    cid for cid, target in VOL_TARGET_CATALOG if target is not None
)
CORE_IDS: tuple[str, ...] = VOL_TARGET_IDS

SHORT_WINDOW = 10
LONG_WINDOW = 30
VOL_LOOKBACK = 20
MAX_LEVERAGE = 1.0
REQUIRED_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD")
PAPER_PATH_READY = True


def ann_realised_vol(candles: tuple[Candle, ...], lookback: int = VOL_LOOKBACK) -> float | None:
    """Annualised realised vol through the last bar; None if insufficient."""
    if lookback < 2 or len(candles) <= lookback:
        return None
    try:
        per_bar = realized_volatility(candles, lookback)
    except ValueError:
        return None
    if per_bar < 0:
        return None
    return per_bar * sqrt(periods_per_year(candles[0].interval))


def vol_scalar(vol_ann: float | None, target_ann: float | None) -> float | None:
    """Reduce-only scalar in (0, max_leverage]; None means stand aside."""
    if target_ann is None:
        return 1.0
    if vol_ann is None:
        return None
    if vol_ann <= 0.0:
        return MAX_LEVERAGE
    return min(target_ann / vol_ann, MAX_LEVERAGE)


@dataclass(frozen=True)
class VolTargetMaStrategy:
    """Always-on SMA cross; optional realised-vol size encoded in score."""

    strategy_id: str
    short_window: int = SHORT_WINDOW
    long_window: int = LONG_WINDOW
    vol_target_ann: float | None = None
    vol_lookback: int = VOL_LOOKBACK

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        if len(candles) < self.long_window:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol if candles else "",
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="insufficient candles for SMA cross",
            )
        short = moving_average(candles, self.short_window)
        long = moving_average(candles, self.long_window)
        side = Side.BUY if short >= long else Side.SELL
        scalar = vol_scalar(ann_realised_vol(candles, self.vol_lookback), self.vol_target_ann)
        if scalar is None:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="vol scalar unavailable; skip-not-invent",
            )
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=scalar,
            confidence=min(scalar, 1.0),
            regime=regime,
            rationale=(
                f"sma {self.short_window}/{self.long_window}; "
                f"vol_scalar={scalar:.4f} target={self.vol_target_ann}"
            ),
        )


def vol_target_candidates() -> tuple[SearchCandidate, ...]:
    out: list[SearchCandidate] = []
    for candidate_id, target in VOL_TARGET_CATALOG:
        strategy = VolTargetMaStrategy(
            strategy_id=candidate_id,
            vol_target_ann=target,
        )
        is_control = target is None
        label = (
            f"SMA {SHORT_WINDOW}/{LONG_WINDOW} unit weight (control)"
            if is_control
            else (
                f"SMA {SHORT_WINDOW}/{LONG_WINDOW} vol-target "
                f"{target:.0%} ann / {VOL_LOOKBACK}d (cap {MAX_LEVERAGE:g})"
            )
        )
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family="ma_cross" if is_control else "ma_cross_vol_target",
                label=label,
                params={
                    "short_window": SHORT_WINDOW,
                    "long_window": LONG_WINDOW,
                    "vol_target_ann": target,
                    "vol_lookback": VOL_LOOKBACK if target is not None else None,
                    "max_leverage": MAX_LEVERAGE,
                    "control": is_control,
                },
                strategy=strategy,
                garch_sizing=False,
                weight_from_score=True,
            )
        )
    return tuple(out)


def _clear_miles_promotion(report: MilesSearchReport) -> MilesSearchReport:
    cleared = [
        row.model_copy(update={"promoted": False, "selected": False}) for row in report.candidates
    ]
    return report.model_copy(
        update={
            "candidates": cleared,
            "promoted_candidate_ids": [],
            "any_promoted": False,
            "selected_candidate_id": None,
        }
    )


class VolTargetReport(BaseModel):
    generated_at: datetime
    rules: str = VOL_TARGET_RULES
    print_kind: Literal["single_print", "dual_print", "unavailable"] = "unavailable"
    primary_candle_venue: str = "kraken"
    second_candle_venue: str | None = None
    fee_bps: float
    slippage_bps: float
    core_ids: list[str] = Field(default_factory=lambda: list(CORE_IDS))
    control_ids: list[str] = Field(default_factory=lambda: sorted(CONTROL_IDS))
    overlay_ids: list[str] = Field(default_factory=lambda: list(OVERLAY_IDS))
    paper_path_ready: bool = PAPER_PATH_READY
    can_promote: bool = False
    keep_flag_false: bool = True
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    aligned_bars_primary: int = 0
    aligned_bars_second: int = 0
    primary: MilesSearchReport | None = None
    second: MilesSearchReport | None = None
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    tip_sha: str | None = None


def _eligible_ids(report: MilesSearchReport | None) -> set[str]:
    if report is None:
        return set()
    return {
        row.candidate_id
        for row in report.candidates
        if row.eligible and row.candidate_id not in CONTROL_IDS
    }


def run_vol_target(
    histories: dict[str, tuple[Candle, ...]],
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    second_histories: dict[str, tuple[Candle, ...]] | None = None,
    primary_candle_venue: str = "kraken",
    second_candle_venue: str | None = "coinbase",
    history_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
    tip_sha: str | None = None,
) -> VolTargetReport:
    generated = now or datetime.now(UTC)
    catalog = vol_target_candidates()
    notes = list(history_notes or [])

    if not histories or len(histories) < len(REQUIRED_SYMBOLS):
        return VolTargetReport(
            generated_at=generated,
            print_kind="unavailable",
            primary_candle_venue=primary_candle_venue,
            second_candle_venue=second_candle_venue,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
            tip_sha=tip_sha,
        )

    primary = _clear_miles_promotion(
        run_miles_search(
            histories,
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
            data_notes=[VOL_TARGET_RULES],
        )
    )
    aligned_primary = min((len(item) for item in histories.values()), default=0)

    second: MilesSearchReport | None = None
    aligned_second = 0
    print_kind: Literal["single_print", "dual_print", "unavailable"] = "single_print"
    if second_histories and len(second_histories) >= len(REQUIRED_SYMBOLS):
        second = _clear_miles_promotion(
            run_miles_search(
                second_histories,
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
                data_notes=[VOL_TARGET_RULES],
            )
        )
        aligned_second = min((len(item) for item in second_histories.values()), default=0)
        print_kind = "dual_print"

    dual_passers = sorted(_eligible_ids(primary) & _eligible_ids(second))
    return VolTargetReport(
        generated_at=generated,
        print_kind=print_kind,
        primary_candle_venue=primary_candle_venue,
        second_candle_venue=second_candle_venue if second is not None else None,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        dual_print_passer_ids=dual_passers,
        dual_print_passers=len(dual_passers),
        aligned_bars_primary=aligned_primary,
        aligned_bars_second=aligned_second,
        primary=primary,
        second=second,
        history_notes=notes,
        tip_sha=tip_sha,
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _table(lines: list[str], report: MilesSearchReport | None, title: str) -> None:
    lines.extend(["", f"## {title}", ""])
    if report is None:
        lines.append("No search result (skipped / unavailable).")
        return
    lines.append(
        "| rank | id | family | WF excess | WF total | holdout excess | eligible | control |"
    )
    lines.append("| ---: | --- | --- | ---: | ---: | ---: | :---: | :---: |")
    ranked = sorted(
        report.candidates,
        key=lambda row: (
            -(row.mean_wf_excess_return if row.mean_wf_excess_return is not None else -1e18),
            row.candidate_id,
        ),
    )
    for index, row in enumerate(ranked, start=1):
        lines.append(
            f"| {index} | `{row.candidate_id}` | {row.family} | "
            f"{_pct(row.mean_wf_excess_return)} | {_pct(row.mean_wf_total_return)} | "
            f"{_pct(row.mean_holdout_excess_return)} | "
            f"{'yes' if row.eligible else 'no'} | "
            f"{'yes' if row.candidate_id in CONTROL_IDS else 'no'} |"
        )


def render_vol_target_markdown(report: VolTargetReport) -> str:
    tip = report.tip_sha or "unknown"
    lines = [
        "# Vol-target overlay on ma_cross_10_30 SPOT dual-print (Kraken x Coinbase)",
        "",
        f"**Repo tip at score:** `{tip}`.",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. primary_candle=`{report.primary_candle_venue}`; "
            f"second_candle=`{report.second_candle_venue}`; "
            f"paper_path_ready=`{str(report.paper_path_ready).lower()}`; "
            f"can_promote=`{str(report.can_promote).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        (f"Core ids={len(report.core_ids)}; dual_print_passers=`{report.dual_print_passers}`."),
        (
            f"Costs: fee={report.fee_bps:g} bps + slippage={report.slippage_bps:g} bps "
            "(pilot spot). Reduce-only vol scalar; no leverage."
        ),
        (
            f"Aligned bars: primary={report.aligned_bars_primary}, "
            f"second={report.aligned_bars_second}."
        ),
        "",
        "## What this does / does not claim",
        "",
        (
            "Paper-research vol-target size overlay on frozen `ma_cross_10_30`. "
            "**Not** a live-capital claim, **not** a reason to flip `PAPER_PROMOTE_*`. "
            "Empty dual-print set is success. Control alone cannot promote."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.rules,
        "",
        "## Pre-registered catalog",
        "",
        "Frozen ids: " + ", ".join(f"`{cid}`" for cid in report.core_ids) + ".",
        "",
        "Overlays: " + ", ".join(f"`{cid}`" for cid in report.overlay_ids) + ".",
        "",
        f"Control (cannot promote): `{CONTROL_ID}`.",
    ]
    if report.history_notes:
        lines.extend(["", "## Candle notes", ""])
        for note in report.history_notes:
            lines.append(
                f"- `{note.get('name', note.get('symbol', '?'))}`: "
                f"{note.get('reason', note.get('status', ''))}"
            )
    _table(lines, report.primary, f"Primary candle print (`{report.primary_candle_venue}`)")
    if report.second is not None:
        _table(
            lines,
            report.second,
            f"Second candle print (`{report.second_candle_venue}`)",
        )
    lines.extend(["", "## Dual-print passers", ""])
    if report.dual_print_passer_ids:
        lines.append(
            "Passers: " + ", ".join(f"`{cid}`" for cid in report.dual_print_passer_ids) + "."
        )
    else:
        lines.append(
            f"**dual_print_passers={report.dual_print_passers}.** "
            "Empty dual-print set is the successful outcome. "
            "Leave every `PAPER_PROMOTE_*=false`."
        )
    lines.extend(
        [
            "",
            "## Promote",
            "",
            (
                f"**No candidate is promoted.** print_kind=`{report.print_kind}`; "
                f"can_promote=`false`; keep_flag_false=`true`."
            ),
            "",
        ]
    )
    return "\n".join(lines) + "\n"
