"""Promotion gate: searched strategies become paper voters only after a win.

`PAPER_PROMOTE_SEARCHED_STRATEGIES` (default false) is the operator switch.
Even when it is true, this module re-applies the numeric gate to the search
report and refuses to register a voter that does not have fee-aware
walk-forward excess return above the floor and enough trades. A missing
report, an empty promoted set, or a feature-only winner (no OHLC voter)
fails closed: the paper process does not start with a silent fallback to
the weak baseline MA ensemble under the promotion flag.
"""

from __future__ import annotations

from pathlib import Path

from traderstack.config import Settings
from traderstack.research.candidates import build_price_strategy
from traderstack.research.search import StrategySearchReport
from traderstack.strategies import StrategyEnsemble

PRICE_FAMILIES: frozenset[str] = frozenset({"ma_cross", "momentum", "mean_reversion"})


class PromotionError(RuntimeError):
    """Raised when promotion is requested but no legal voter can be registered."""


def load_search_report(path: Path) -> StrategySearchReport:
    return StrategySearchReport.model_validate_json(path.read_text())


def row_clears_gate(
    *,
    mean_wf_excess_return: float | None,
    total_wf_trades: int,
    mean_holdout_excess_return: float | None,
    min_trades: int,
    min_wf_excess_return: float,
    require_holdout_confirmation: bool,
    mean_wf_total_return: float | None = None,
    require_wf_total_return: bool = True,
    min_wf_total_return: float = 0.0,
) -> bool:
    wf_ok = (
        mean_wf_excess_return is not None
        and mean_wf_excess_return > min_wf_excess_return
        and total_wf_trades >= min_trades
    )
    if not wf_ok:
        return False
    if require_wf_total_return and (
        mean_wf_total_return is None or mean_wf_total_return <= min_wf_total_return
    ):
        return False
    if not require_holdout_confirmation:
        return True
    return (
        mean_holdout_excess_return is not None and mean_holdout_excess_return > min_wf_excess_return
    )


def promoted_price_voters(report: StrategySearchReport, settings: Settings) -> tuple[object, ...]:
    """Rebuild price-only voters that both the report and the live gate accept."""
    voters: list[object] = []
    wanted = set(report.promoted_candidate_ids)
    pin = settings.paper_promote_searched_strategy_id.strip()
    if pin and pin not in wanted:
        raise PromotionError(
            f"PAPER_PROMOTE_SEARCHED_STRATEGY_ID={pin!r} is not in the report's "
            f"promoted set {sorted(wanted) or '[]'}. The documented path pins "
            "exactly one holdout-passing id; leave the flag false otherwise."
        )
    for row in report.candidates:
        if row.candidate_id not in wanted or not row.promoted:
            continue
        if row.family not in PRICE_FAMILIES:
            raise PromotionError(
                f"promoted candidate {row.candidate_id!r} is family {row.family!r}; "
                "feature voters cannot register on the Kraken Spot OHLC paper path"
            )
        if row.requires_feature:
            raise PromotionError(
                f"promoted candidate {row.candidate_id!r} requires feature "
                f"{row.requires_feature!r}; feature voters cannot register on "
                "the Kraken Spot OHLC paper path"
            )
        if not row_clears_gate(
            mean_wf_excess_return=row.mean_wf_excess_return,
            total_wf_trades=row.total_wf_trades,
            mean_holdout_excess_return=row.mean_holdout_excess_return,
            min_trades=settings.paper_search_min_trades,
            min_wf_excess_return=settings.paper_search_min_wf_excess_return,
            require_holdout_confirmation=settings.paper_search_require_holdout,
            mean_wf_total_return=row.mean_wf_total_return,
            require_wf_total_return=settings.paper_search_require_wf_total_return,
            min_wf_total_return=settings.paper_search_min_wf_total_return,
        ):
            continue
        pin = settings.paper_promote_searched_strategy_id.strip()
        if pin and row.candidate_id != pin:
            continue
        voters.append(build_price_strategy(row.family, row.params))
    return tuple(voters)


def build_paper_ensemble(settings: Settings) -> StrategyEnsemble:
    """Promoted single-voter committee, or an empty default ensemble.

    Promotion off (default) returns `StrategyEnsemble()` so the caller can
    keep the paper-research ensemble from `cli.paper_research_ensemble`.
    Promotion on registers only gate-clearing searched voters and
    suppresses the unpromoted defaults — never a silent MA fallback.
    """
    if not settings.paper_promote_searched_strategies:
        return StrategyEnsemble()

    path = Path(settings.paper_search_report_path)
    if not path.is_file():
        raise PromotionError(
            "PAPER_PROMOTE_SEARCHED_STRATEGIES=true but "
            f"{path} is missing. Leave the flag false or write a search report."
        )
    report = load_search_report(path)
    voters = promoted_price_voters(report, settings)
    if not voters:
        raise PromotionError(
            "PAPER_PROMOTE_SEARCHED_STRATEGIES=true but no candidate cleared "
            "the fee-aware walk-forward promotion gate. Leave the flag false; "
            "do not treat the baseline MA ensemble as a searched winner."
        )
    return StrategyEnsemble(
        extra_voters=voters,
        min_agreeing=1,
        suppress_defaults=True,
    )


def describe_promotion(settings: Settings) -> tuple[str, str]:
    """`(value, detail)` for `traderstack-check-config`. Never raises."""
    if not settings.paper_promote_searched_strategies:
        pin = settings.paper_promote_searched_strategy_id.strip()
        extra = f"; pin={pin}" if pin else ""
        return "no", f"default; searched strategies are not paper voters{extra}"
    path = Path(settings.paper_search_report_path)
    if not path.is_file():
        return "yes", f"report missing: {path}"
    try:
        report = load_search_report(path)
        voters = promoted_price_voters(report, settings)
    except (OSError, ValueError, PromotionError) as exc:
        return "yes", f"report unusable: {exc}"
    if not voters:
        return "yes", "report has no gate-clearing promoted voter"
    ids = ", ".join(getattr(voter, "strategy_id", type(voter).__name__) for voter in voters)
    pin = settings.paper_promote_searched_strategy_id.strip()
    suffix = f" (pinned {pin})" if pin else ""
    return "yes", f"voters: {ids}{suffix}"
