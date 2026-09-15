"""Selection evidence attached to every search report (#135).

This is the composition layer between the pure statistics in
``research.overfitting``, the pre-registered print policy in
``research.era_prints``, and the shared scoring path
(``research.harder_gates.run_harder_gates``) that every dual-print
search family funnels through.

What a report gains
-------------------
* **print kind** — venue, era, both, or single (``era_prints``)
* **trial count** — how many catalog members were actually scored
* **DSR** — Deflated Sharpe Ratio for each trial, against the variance
  of the whole trial catalog
* **PBO** — CSCV probability of backtest overfitting for the catalog,
  so "0 passers" and "1 passer with PBO 0.6" are different outcomes
* **bootstrap CIs** on Sharpe and expectancy, and the bootstrap
  **trade-count floor**
* **era coverage** of the primary venue's series
* a **power table** saying what the window can and cannot resolve

What it cannot do
-----------------
It is an **additional** gate. ``evidence_gate_pass`` can only withhold:
it never lowers a threshold, never flips a ``PAPER_PROMOTE_*`` default,
and never makes a name that failed #96/A/B/C into a passer. An empty
``evidence_passer_ids`` is a successful result.

Observation unit — stated plainly
---------------------------------
Search reports strip per-bar and per-trade logs (``miles_search``
``_strip_trade_list``-style ``model_copy``), so the finest return sample
that survives into a report is the **walk-forward fold**: one net total
return per fold per promotion asset. Every statistic here is computed on
that sample and the reports say so. Fold returns are stacked
asset-by-asset (BTC folds oldest-first, then ETH, then SOL where it is
reported) to give the CSCV matrix enough rows; a missing asset is
skipped, never zero-filled.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.candles import periods_per_year as candle_periods_per_year
from traderstack.research.era_prints import (
    ERA_PRINT_RULE,
    EraCoverage,
    PrintKind,
    classify_print_kind,
    describe_print_kind,
    era_coverage,
)
from traderstack.research.overfitting import (
    DEFAULT_BOOTSTRAP_ITERATIONS,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_CONFIDENCE,
    DEFAULT_CSCV_SPLITS,
    DEFAULT_FLOOR_ITERATIONS,
    BootstrapInterval,
    DeflatedSharpeResult,
    PboResult,
    PowerRow,
    TradeCountFloor,
    annualise,
    bootstrap_interval,
    bootstrap_trade_floor,
    cscv_pbo,
    deflated_sharpe_ratio,
    power_table,
    sharpe_ratio,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Annotation-only: `from __future__ import annotations` keeps these as
    # strings at runtime, so importing them here would only serve to create an
    # import cycle (miles_search -> selection_evidence -> miles_search) the
    # moment a search module wants to carry an evidence block (#135).
    from traderstack.research.miles_search import CandidateSearchResult


# --- era prints / DSR / PBO (#135): pre-registered gate thresholds ---
# Frozen in version control, deliberately not Settings fields: a
# threshold an operator can move after seeing PnL is not a pre-registered
# test. Both are ADDITIONAL to #96 + A + B + C, never replacements.
DSR_MIN = 0.95
PBO_MAX = 0.50
# Promotion assets whose folds form the return sample, in stack order.
EVIDENCE_ASSETS: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")
OBSERVATION_UNIT = "walk_forward_fold"

EVIDENCE_RULE = (
    "Pre-registered selection evidence (frozen before any score). "
    f"DSR (Bailey & Lopez de Prado 2014, SSRN 2460551) must be >= {DSR_MIN:.2f} "
    f"and catalog PBO by CSCV (Bailey et al. 2016) must be <= {PBO_MAX:.2f}; "
    "the bootstrap CIs on Sharpe and on expectancy must both exclude "
    "zero; the observed trade count must clear the bootstrap trade-count "
    "floor (max of the configured fixed floor and the bootstrap answer — "
    "the bootstrap can only raise it). These are ADDITIONAL gates on top "
    "of #96 + A + B + C, never replacements, and no existing threshold is "
    "lowered by them. Statistics run on the walk-forward fold return "
    "sample, the finest sample that survives into a report. Every "
    "bootstrap draws from an explicit random.Random(seed), so a fixed "
    "seed reproduces every number; CSCV is exhaustive and has no seed. "
    "A statistic that cannot be computed is reported as skipped with a "
    "reason and WITHHOLDS the gate — it is never treated as a pass. An "
    "empty evidence-passer set is a successful result and never flips a "
    "PAPER_PROMOTE_* default."
)


class CandidateEvidence(BaseModel):
    """Per-trial selection evidence. Additional gate; withholds only."""

    candidate_id: str
    observations: int = 0
    total_trades: int = 0
    trial_sharpe: float | None = None
    trial_sharpe_annualised: float | None = None
    deflated: DeflatedSharpeResult = Field(default_factory=DeflatedSharpeResult)
    sharpe_ci: BootstrapInterval = Field(
        default_factory=lambda: BootstrapInterval(statistic="sharpe")
    )
    expectancy_ci: BootstrapInterval = Field(
        default_factory=lambda: BootstrapInterval(statistic="mean")
    )
    trade_floor: TradeCountFloor = Field(default_factory=TradeCountFloor)
    dsr_pass: bool = False
    sharpe_ci_pass: bool = False
    expectancy_ci_pass: bool = False
    trade_floor_pass: bool = False
    evidence_gate_pass: bool = False
    evidence_gate_reasons: list[str] = Field(default_factory=list)


class SelectionEvidence(BaseModel):
    """Catalog-level selection evidence written into every search report."""

    print_kind: PrintKind = PrintKind.SINGLE
    print_kind_detail: str = ""
    venue_print_available: bool = False
    era_coverage: EraCoverage | None = None
    trial_count: int = 0
    trials_with_returns: int = 0
    observation_unit: str = OBSERVATION_UNIT
    window_years: float | None = None
    periods_per_observation_year: float | None = None
    pbo: PboResult = Field(default_factory=PboResult)
    pbo_pass: bool = False
    dsr_min: float = DSR_MIN
    pbo_max: float = PBO_MAX
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED
    bootstrap_iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS
    confidence: float = DEFAULT_CONFIDENCE
    cscv_splits: int = DEFAULT_CSCV_SPLITS
    candidates: list[CandidateEvidence] = Field(default_factory=list)
    evidence_passer_ids: list[str] = Field(default_factory=list)
    any_evidence_passer: bool = False
    power: list[PowerRow] = Field(default_factory=list)
    rule: str = EVIDENCE_RULE
    era_rule: str = ERA_PRINT_RULE

    def for_candidate(self, candidate_id: str) -> CandidateEvidence | None:
        for row in self.candidates:
            if row.candidate_id == candidate_id:
                return row
        return None


def _fold_returns(
    row: CandidateSearchResult,
    *,
    interval: str,
    assets: Sequence[str] = EVIDENCE_ASSETS,
) -> tuple[list[float], list[float], int]:
    """``(fold total returns, fold expectancies, total trades)``.

    Assets are visited in the fixed order above and folds in time order,
    so the sample is deterministic. A series that is missing, was skipped,
    or produced no walk-forward is left out of the sample entirely — it is
    never represented by a zero. A fold with no trades contributes a total
    return but no expectancy observation, because a fold that did not
    trade has no per-trade expectancy to observe.
    """
    # Imported at call time, not module scope: `daily_robustness` imports
    # `miles_search`, so a module-level import here would close the same cycle
    # described above. By the time this runs both modules are loaded, and
    # Python serves the lookup from sys.modules. Deliberately the one shared
    # implementation rather than a second copy that could drift from it.
    from traderstack.research.daily_robustness import series_for_asset

    returns: list[float] = []
    expectancies: list[float] = []
    trades = 0
    for asset in assets:
        series = series_for_asset(row.per_series, asset, interval=interval)
        if series is None or series.walkforward is None:
            continue
        for fold in series.walkforward.folds:
            returns.append(fold.metrics.total_return)
            trades += fold.metrics.trades
            if fold.metrics.trades > 0:
                expectancies.append(fold.metrics.expectancy)
    return returns, expectancies, trades


def _observation_periods_per_year(interval: str, test_size: int) -> float | None:
    """Folds per year: bars per year divided by the bars in one fold."""
    if test_size <= 0:
        return None
    try:
        bars = candle_periods_per_year(interval)
    except (KeyError, ValueError):
        return None
    if bars <= 0:
        return None
    return bars / test_size


def _cscv_matrix(samples: list[list[float]]) -> list[list[float]]:
    """Rows = fold slices, columns = trials, truncated to the common length."""
    usable = [sample for sample in samples if sample]
    if len(usable) < 2:
        return []
    rows = min(len(sample) for sample in usable)
    if rows < 2:
        return []
    return [[sample[index] for sample in usable] for index in range(rows)]


def build_selection_evidence(
    rows: Sequence[CandidateSearchResult],
    *,
    primary_candles: Sequence[Candle] | None,
    primary_venue: str,
    venue_print_available: bool = False,
    interval: str = "1d",
    test_size: int = 60,
    configured_min_trades: int = 0,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    floor_iterations: int = DEFAULT_FLOOR_ITERATIONS,
    confidence: float = DEFAULT_CONFIDENCE,
    cscv_splits: int = DEFAULT_CSCV_SPLITS,
    assets: Sequence[str] = EVIDENCE_ASSETS,
) -> SelectionEvidence:
    """Build the evidence block for one catalog run.

    ``rows`` are the scored catalog members (the trials). ``primary_candles``
    is the venue series the era coverage is measured on.
    ``venue_print_available`` is the existing second-venue verdict, passed
    through unchanged: this function never decides that a venue print
    happened, it only records which kind of print the run has.
    """
    coverage = era_coverage(primary_candles, venue=primary_venue)
    kind = classify_print_kind(venue_print_available=venue_print_available, coverage=coverage)
    per_year = _observation_periods_per_year(interval, test_size)

    samples: list[list[float]] = []
    expectancy_samples: list[list[float]] = []
    trade_counts: list[int] = []
    trial_sharpes: list[float] = []
    for row in rows:
        returns, expectancies, trades = _fold_returns(row, interval=interval, assets=assets)
        samples.append(returns)
        expectancy_samples.append(expectancies)
        trade_counts.append(trades)
        sharpe = sharpe_ratio(returns)
        if sharpe is not None:
            trial_sharpes.append(sharpe)

    pbo = cscv_pbo(_cscv_matrix(samples), splits=cscv_splits)
    pbo_pass = bool(pbo.computed and pbo.pbo is not None and pbo.pbo <= PBO_MAX)

    catalog_reasons: list[str] = []
    if kind is PrintKind.SINGLE:
        catalog_reasons.append("single_print_no_independent_confirmation")
    if not pbo.computed:
        catalog_reasons.append(f"pbo_skipped:{pbo.skipped_reason}")
    elif not pbo_pass:
        catalog_reasons.append("pbo_above_maximum")

    candidates: list[CandidateEvidence] = []
    passers: list[str] = []
    for row, returns, expectancies, trades in zip(
        rows, samples, expectancy_samples, trade_counts, strict=True
    ):
        sharpe = sharpe_ratio(returns)
        deflated = deflated_sharpe_ratio(
            returns=returns,
            trial_sharpes=trial_sharpes,
            periods_per_year=per_year if per_year is not None else 1.0,
        )
        sharpe_ci = bootstrap_interval(
            returns,
            statistic="sharpe",
            confidence=confidence,
            iterations=iterations,
            seed=seed,
        )
        expectancy_ci = bootstrap_interval(
            expectancies,
            statistic="mean",
            confidence=confidence,
            iterations=iterations,
            seed=seed,
        )
        trades_per_observation = trades / len(expectancies) if expectancies else 1.0
        floor = bootstrap_trade_floor(
            expectancies,
            observed_trades=trades,
            configured_min_trades=configured_min_trades,
            observation_unit=OBSERVATION_UNIT,
            trades_per_observation=trades_per_observation,
            confidence=confidence,
            iterations=floor_iterations,
            seed=seed,
        )
        reasons = list(catalog_reasons)
        dsr_pass = bool(
            deflated.computed
            and deflated.deflated_sharpe is not None
            and deflated.deflated_sharpe >= DSR_MIN
        )
        if not deflated.computed:
            reasons.append(f"dsr_skipped:{deflated.skipped_reason}")
        elif not dsr_pass:
            reasons.append("deflated_sharpe_below_minimum")
        sharpe_ci_pass = bool(
            sharpe_ci.computed and sharpe_ci.low is not None and sharpe_ci.low > 0.0
        )
        if not sharpe_ci.computed:
            reasons.append(f"sharpe_ci_skipped:{sharpe_ci.skipped_reason}")
        elif not sharpe_ci_pass:
            reasons.append("sharpe_ci_does_not_exclude_zero_below")
        expectancy_ci_pass = bool(
            expectancy_ci.computed and expectancy_ci.low is not None and expectancy_ci.low > 0.0
        )
        if not expectancy_ci.computed:
            reasons.append(f"expectancy_ci_skipped:{expectancy_ci.skipped_reason}")
        elif not expectancy_ci_pass:
            reasons.append("expectancy_ci_does_not_exclude_zero_below")
        floor_pass = bool(floor.computed and floor.meets_floor)
        if not floor.computed:
            reasons.append(f"trade_floor_skipped:{floor.skipped_reason}")
        elif not floor_pass:
            reasons.append("observed_trades_below_bootstrap_floor")
        gate = not reasons
        evidence = CandidateEvidence(
            candidate_id=row.candidate_id,
            observations=len(returns),
            total_trades=trades,
            trial_sharpe=sharpe,
            trial_sharpe_annualised=(
                annualise(sharpe, per_year) if sharpe is not None and per_year is not None else None
            ),
            deflated=deflated,
            sharpe_ci=sharpe_ci,
            expectancy_ci=expectancy_ci,
            trade_floor=floor,
            dsr_pass=dsr_pass,
            sharpe_ci_pass=sharpe_ci_pass,
            expectancy_ci_pass=expectancy_ci_pass,
            trade_floor_pass=floor_pass,
            evidence_gate_pass=gate,
            evidence_gate_reasons=reasons,
        )
        candidates.append(evidence)
        if gate:
            passers.append(row.candidate_id)

    window_years = coverage.span_years
    return SelectionEvidence(
        print_kind=kind,
        print_kind_detail=describe_print_kind(kind, coverage),
        venue_print_available=venue_print_available,
        era_coverage=coverage,
        trial_count=len(rows),
        trials_with_returns=sum(1 for sample in samples if sample),
        window_years=window_years,
        periods_per_observation_year=per_year,
        pbo=pbo,
        pbo_pass=pbo_pass,
        bootstrap_seed=seed,
        bootstrap_iterations=iterations,
        confidence=confidence,
        cscv_splits=cscv_splits,
        candidates=candidates,
        evidence_passer_ids=sorted(passers),
        any_evidence_passer=bool(passers),
        power=power_table(years=window_years) if window_years else [],
    )


def _fmt(value: float | None, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def render_evidence_lines(
    evidence: SelectionEvidence | None,
    *,
    highlight_candidate_ids: Sequence[str] = (),
) -> list[str]:
    """Markdown block shared by every search renderer.

    Reporting order (see ``docs/EVALUATION-FRAMEWORK.md``): print kind
    first, then trial count, then DSR, then PBO, then the bootstrap
    intervals, then era coverage, then the power table.
    """
    if evidence is None:
        return [
            "## Selection evidence (#135)",
            "",
            "Not computed for this run. Absent evidence is not a pass.",
            "",
        ]
    lines = [
        "## Selection evidence (#135)",
        "",
        f"- **Print kind:** `{evidence.print_kind.value}` — {evidence.print_kind_detail}",
        (
            f"- **Trials scored (K):** {evidence.trial_count} "
            f"({evidence.trials_with_returns} with a usable return sample)"
        ),
        (
            f"- **Observation unit:** `{evidence.observation_unit}` "
            "(walk-forward folds; per-trade logs are stripped from reports)"
        ),
    ]
    if evidence.pbo.computed:
        lines.append(
            f"- **PBO (CSCV):** {_fmt(evidence.pbo.pbo, 3)} over "
            f"{evidence.pbo.combinations} combinations of "
            f"{evidence.pbo.splits} blocks "
            f"(max {evidence.pbo_max:.2f}; "
            f"{'PASS' if evidence.pbo_pass else 'FAIL'})"
        )
    else:
        lines.append(f"- **PBO (CSCV):** skipped — `{evidence.pbo.skipped_reason}` (withholds)")
    lines.append(
        f"- **Bootstrap:** seed `{evidence.bootstrap_seed}`, "
        f"{evidence.bootstrap_iterations} iterations, "
        f"{evidence.confidence:.0%} percentile CIs (fixed seed reproduces these numbers)"
    )
    lines.append(
        f"- **Evidence passers:** {len(evidence.evidence_passer_ids)}"
        + (
            f" (`{'`, `'.join(evidence.evidence_passer_ids)}`)"
            if evidence.evidence_passer_ids
            else " (none — an empty set is a successful result)"
        )
    )
    lines.append("")

    wanted = list(highlight_candidate_ids) or evidence.evidence_passer_ids
    shown = [row for row in evidence.candidates if row.candidate_id in set(wanted)]
    if shown:
        lines.extend(
            [
                (
                    "| candidate | obs | trades | SR (ann.) | DSR | Sharpe CI "
                    "| expectancy CI | trade floor | evidence |"
                ),
                "| --- | ---: | ---: | ---: | ---: | --- | --- | ---: | --- |",
            ]
        )
        for row in shown:
            sharpe_ci = (
                f"[{_fmt(row.sharpe_ci.low, 3)}, {_fmt(row.sharpe_ci.high, 3)}]"
                if row.sharpe_ci.computed
                else "skipped"
            )
            expectancy_ci = (
                f"[{_fmt(row.expectancy_ci.low, 4)}, {_fmt(row.expectancy_ci.high, 4)}]"
                if row.expectancy_ci.computed
                else "skipped"
            )
            floor = (
                f"{row.trade_floor.effective_min_trades}" if row.trade_floor.computed else "skipped"
            )
            lines.append(
                f"| `{row.candidate_id}` | {row.observations} | {row.total_trades} | "
                f"{_fmt(row.trial_sharpe_annualised, 3)} | "
                f"{_fmt(row.deflated.deflated_sharpe, 3)} | {sharpe_ci} | "
                f"{expectancy_ci} | {floor} | "
                f"{'PASS' if row.evidence_gate_pass else 'withheld'} |"
            )
        lines.append("")

    coverage = evidence.era_coverage
    if coverage is not None:
        lines.extend(
            [
                f"### Era coverage — `{coverage.venue}`",
                "",
                (
                    f"{coverage.total_bars} bars, {coverage.first} to "
                    f"{coverage.last} ({_fmt(coverage.span_years, 2)} years). "
                    f"Covered eras: {coverage.covered_eras} "
                    f"(>= {coverage.min_era_bars} bars each)."
                ),
                "",
                "| era | window | bars | covered |",
                "| --- | --- | ---: | --- |",
            ]
        )
        for span in coverage.spans:
            lines.append(
                f"| `{span.era_id}` | {span.start[:10]} → {span.end[:10]} | "
                f"{span.bars} | {'yes' if span.covered else 'no'} |"
            )
        lines.append("")

    if evidence.power:
        lines.extend(
            [
                "### Sharpe power at this window length",
                "",
                (
                    "`SE(SR) = sqrt((1 + SR^2 / 2) / T_years)` (Lo 2002). The "
                    "window, not the catalog, is the binding constraint."
                ),
                "",
                "| annual SR | SE | t-stat | years needed for t = 2 |",
                "| ---: | ---: | ---: | ---: |",
            ]
        )
        for power_row in evidence.power:
            lines.append(
                f"| {power_row.annual_sharpe:.2f} | {power_row.standard_error:.3f} | "
                f"{power_row.tstat:.2f} | {power_row.years_for_tstat_2:.1f} |"
            )
        lines.append("")
    lines.append(evidence.rule)
    lines.append("")
    return lines


__all__ = [
    "DSR_MIN",
    "EVIDENCE_ASSETS",
    "EVIDENCE_RULE",
    "OBSERVATION_UNIT",
    "PBO_MAX",
    "CandidateEvidence",
    "SelectionEvidence",
    "build_selection_evidence",
    "render_evidence_lines",
]
