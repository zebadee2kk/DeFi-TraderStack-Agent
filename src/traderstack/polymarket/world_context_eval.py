from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Final

from traderstack.config import Settings
from traderstack.market.registry import ProviderRegistry
from traderstack.polymarket.data_api import PolymarketDataClient
from traderstack.polymarket.wallet_signal_eval import (
    HYPOTHESES,
    PacedPriceLookup,
    ScoredSignal,
    build_signal_candidates,
    score_candidates,
)
from traderstack.polymarket.world_signal_fusion import FusedSignalContext, fuse_signal_context
from traderstack.provider_health_journal import DEFAULT_PROVIDER_HEALTH_PATH, ProviderHealthJournal
from traderstack.research.overfitting import (
    DEFAULT_BOOTSTRAP_ITERATIONS,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_CONFIDENCE,
    bootstrap_interval,
    deflated_sharpe_ratio,
    mean,
    sharpe_ratio,
)
from traderstack.signal_warehouse import PostgresSignalWarehouse

CONTEXT_IDS: Final[tuple[str, ...]] = (
    "baseline_all",
    "context_available",
    "news_adverse",
    "news_event_high",
    "narrative_attention_high",
    "narrative_sentiment_extreme",
    "onchain_flow_extreme",
    "wallet_accumulation_extreme",
    "external_technical_extreme",
    "liquidation_stress",
)
TRIALS_PER_BASE_GRID: Final[int] = len(CONTEXT_IDS)
DISCOVERY_MIN_SIGNALS: Final[int] = 30
HOLDOUT_MIN_SIGNALS: Final[int] = 15


@dataclass(frozen=True)
class IncrementalInterval:
    computed: bool
    skipped_reason: str | None
    observations: int
    treatment_observations: int
    iterations: int
    confidence: float
    seed: int
    point: float | None
    low: float | None
    high: float | None
    excludes_zero: bool


@dataclass(frozen=True)
class ContextCell:
    hypothesis: str
    context_id: str
    split: str
    copy_delay_seconds: int
    cost_bps_per_side: float
    signals: int
    baseline_signals: int
    coverage: float | None
    gross_pnl_usd: float
    net_pnl_usd: float
    mean_net_pnl_usd: float | None
    baseline_mean_net_pnl_usd: float | None
    incremental_mean_net_pnl_usd: float | None
    win_rate: float | None
    max_drawdown_usd: float
    sample_bar_met: bool
    sample_bar_required: int
    mean_net_pnl_ci: dict[str, object]
    incremental_mean_ci: dict[str, object]
    deflated_sharpe: dict[str, object]


def _nested(payload: dict[str, object], path: tuple[str, ...]) -> object | None:
    value: object = payload
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
        if value is None:
            return None
    return value


def _floats(context: FusedSignalContext, path: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    for row in context.provider_context:
        value = _nested(row.payload, path)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and math.isfinite(float(value)):
            values.append(float(value))
    return values


def _bools(context: FusedSignalContext, path: tuple[str, ...]) -> list[bool]:
    values: list[bool] = []
    for row in context.provider_context:
        value = _nested(row.payload, path)
        if isinstance(value, bool):
            values.append(value)
    return values


def context_matches(context: FusedSignalContext | None, context_id: str) -> bool:
    if context_id not in CONTEXT_IDS:
        raise ValueError(f"unknown context_id: {context_id}")
    if context_id == "baseline_all":
        return True
    if context is None:
        return False
    if context_id == "context_available":
        return bool(context.provider_context)
    if context_id == "news_adverse":
        return any(_bools(context, ("news", "adverse_event")))
    if context_id == "news_event_high":
        return any(value >= 0.50 for value in _floats(context, ("news", "event_score")))
    if context_id == "narrative_attention_high":
        return any(
            abs(value) >= 1.0 for value in _floats(context, ("narrative", "mention_velocity_z"))
        )
    if context_id == "narrative_sentiment_extreme":
        return any(abs(value) >= 0.50 for value in _floats(context, ("narrative", "sentiment")))
    if context_id == "onchain_flow_extreme":
        return any(
            abs(value) >= 1.5 for value in _floats(context, ("onchain", "exchange_netflow_z"))
        )
    if context_id == "wallet_accumulation_extreme":
        return any(
            abs(value) >= 0.50
            for value in _floats(context, ("onchain", "large_wallet_accumulation"))
        )
    if context_id == "external_technical_extreme":
        return any(
            abs(value) >= 0.50 for value in _floats(context, ("market", "external_signal_score"))
        )
    liquidation = _floats(context, ("edge", "liq_notional_long_z")) + _floats(
        context, ("edge", "liq_notional_short_z")
    )
    return any(abs(value) >= 1.5 for value in liquidation)


def _signal_key(
    hypothesis: str,
    wallet: str,
    token_id: str,
    trade_at: datetime,
) -> tuple[str, str, str, datetime]:
    return hypothesis, wallet.lower(), token_id, trade_at


def build_context_index(
    contexts: list[FusedSignalContext],
) -> dict[tuple[str, str, str, datetime], FusedSignalContext]:
    output: dict[tuple[str, str, str, datetime], FusedSignalContext] = {}
    for context in contexts:
        key = _signal_key(
            context.hypothesis,
            context.wallet,
            context.token_id,
            context.signal_at,
        )
        existing = output.get(key)
        if existing is None or len(context.provider_context) > len(existing.provider_context):
            output[key] = context
    return output


def _context_for(
    signal: ScoredSignal,
    index: dict[tuple[str, str, str, datetime], FusedSignalContext],
) -> FusedSignalContext | None:
    return index.get(
        _signal_key(
            signal.hypothesis,
            signal.wallet,
            signal.token_id,
            signal.trade_at,
        )
    )


def _max_drawdown(rows: list[ScoredSignal]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for row in rows:
        equity += row.net_pnl_usd
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def bootstrap_incremental_mean(
    baseline: list[ScoredSignal],
    matches: list[bool],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> IncrementalInterval:
    if len(baseline) != len(matches):
        raise ValueError("baseline and matches must have equal length")
    treatment = [row.net_pnl_usd for row, matched in zip(baseline, matches, strict=True) if matched]
    baseline_pnl = [row.net_pnl_usd for row in baseline]
    baseline_mean = mean(baseline_pnl)
    treatment_mean = mean(treatment)
    point = (
        None if baseline_mean is None or treatment_mean is None else treatment_mean - baseline_mean
    )

    def skipped(reason: str) -> IncrementalInterval:
        return IncrementalInterval(
            computed=False,
            skipped_reason=reason,
            observations=len(baseline),
            treatment_observations=len(treatment),
            iterations=iterations,
            confidence=confidence,
            seed=seed,
            point=point,
            low=None,
            high=None,
            excludes_zero=False,
        )

    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if len(baseline) < 2:
        return skipped("fewer_than_two_baseline_observations")
    if len(treatment) < 2:
        return skipped("fewer_than_two_treatment_observations")

    rng = random.Random(seed)
    draws: list[float] = []
    size = len(baseline)
    for _ in range(iterations):
        indices = [rng.randrange(size) for _ in range(size)]
        all_draw = [baseline[index].net_pnl_usd for index in indices]
        treatment_draw = [baseline[index].net_pnl_usd for index in indices if matches[index]]
        if not treatment_draw:
            continue
        all_mean = mean(all_draw)
        treatment_draw_mean = mean(treatment_draw)
        if all_mean is not None and treatment_draw_mean is not None:
            draws.append(treatment_draw_mean - all_mean)

    if len(draws) < 2:
        return skipped("bootstrap_draws_degenerate")

    tail = (1.0 - confidence) / 2.0
    low = _percentile(draws, tail)
    high = _percentile(draws, 1.0 - tail)
    return IncrementalInterval(
        computed=True,
        skipped_reason=None,
        observations=len(baseline),
        treatment_observations=len(treatment),
        iterations=iterations,
        confidence=confidence,
        seed=seed,
        point=point,
        low=low,
        high=high,
        excludes_zero=low > 0.0 or high < 0.0,
    )


def _split_rows(
    rows: list[ScoredSignal],
    *,
    holdout_fraction: float,
) -> dict[str, list[ScoredSignal]]:
    if not 0.0 < holdout_fraction < 1.0:
        raise ValueError("holdout_fraction must be in (0, 1)")
    ordered = sorted(rows, key=lambda row: row.trade_at)
    if not ordered:
        return {"discovery": [], "holdout": [], "all": []}
    split_index = max(1, int(len(ordered) * (1.0 - holdout_fraction)))
    split_index = min(split_index, len(ordered))
    return {
        "discovery": ordered[:split_index],
        "holdout": ordered[split_index:],
        "all": ordered,
    }


def _sample_floor(split: str, discovery_min: int, holdout_min: int) -> int:
    if split == "discovery":
        return discovery_min
    if split == "holdout":
        return holdout_min
    return discovery_min + holdout_min


def evaluate_context_grid(
    scored: list[ScoredSignal],
    contexts: list[FusedSignalContext],
    *,
    holdout_fraction: float = 0.30,
    discovery_min: int = DISCOVERY_MIN_SIGNALS,
    holdout_min: int = HOLDOUT_MIN_SIGNALS,
) -> list[ContextCell]:
    if discovery_min <= 0 or holdout_min <= 0:
        raise ValueError("sample floors must be positive")
    index = build_context_index(contexts)
    cells: list[ContextCell] = []

    for hypothesis in HYPOTHESES:
        hypothesis_rows = [row for row in scored if row.hypothesis == hypothesis]
        splits = _split_rows(hypothesis_rows, holdout_fraction=holdout_fraction)
        if hypothesis_rows:
            delay = hypothesis_rows[0].copy_delay_seconds
            cost = hypothesis_rows[0].cost_bps_per_side
        else:
            delay = scored[0].copy_delay_seconds if scored else 0
            cost = scored[0].cost_bps_per_side if scored else 0.0

        for split, baseline in splits.items():
            baseline_mean = mean([row.net_pnl_usd for row in baseline])
            context_rows: dict[str, list[ScoredSignal]] = {}
            match_vectors: dict[str, list[bool]] = {}
            for context_id in CONTEXT_IDS:
                matches = [
                    context_matches(_context_for(row, index), context_id) for row in baseline
                ]
                match_vectors[context_id] = matches
                context_rows[context_id] = [
                    row for row, matched in zip(baseline, matches, strict=True) if matched
                ]

            floor = _sample_floor(split, discovery_min, holdout_min)
            per_context_sharpes = {
                context_id: sharpe_ratio(
                    [
                        row.net_pnl_usd / row.copied_notional_usd
                        for row in context_rows[context_id]
                        if row.copied_notional_usd > 0
                    ]
                )
                for context_id in CONTEXT_IDS
            }
            catalog_ready = all(
                len(context_rows[context_id]) >= floor
                and per_context_sharpes[context_id] is not None
                for context_id in CONTEXT_IDS
            )
            trial_sharpes = [
                value
                for context_id in CONTEXT_IDS
                if (value := per_context_sharpes[context_id]) is not None
            ]

            for context_id in CONTEXT_IDS:
                treatment = context_rows[context_id]
                pnls = [row.net_pnl_usd for row in treatment]
                treatment_mean = mean(pnls)
                incremental = (
                    None
                    if baseline_mean is None or treatment_mean is None
                    else treatment_mean - baseline_mean
                )
                floor_met = len(treatment) >= floor
                mean_ci = bootstrap_interval(pnls, statistic="mean")
                incremental_ci = bootstrap_incremental_mean(
                    baseline,
                    match_vectors[context_id],
                )
                normalized = [
                    row.net_pnl_usd / row.copied_notional_usd
                    for row in treatment
                    if row.copied_notional_usd > 0
                ]
                if floor_met and catalog_ready:
                    dsr = deflated_sharpe_ratio(
                        returns=normalized,
                        trial_sharpes=trial_sharpes,
                    ).model_dump(mode="json")
                else:
                    dsr = {
                        "computed": False,
                        "skipped_reason": (
                            "minimum_signal_count_not_met"
                            if not floor_met
                            else "catalog_sample_support_incomplete"
                        ),
                        "trials": TRIALS_PER_BASE_GRID,
                        "observations": len(normalized),
                    }

                cells.append(
                    ContextCell(
                        hypothesis=hypothesis,
                        context_id=context_id,
                        split=split,
                        copy_delay_seconds=delay,
                        cost_bps_per_side=cost,
                        signals=len(treatment),
                        baseline_signals=len(baseline),
                        coverage=(len(treatment) / len(baseline) if baseline else None),
                        gross_pnl_usd=sum(row.gross_pnl_usd for row in treatment),
                        net_pnl_usd=sum(pnls),
                        mean_net_pnl_usd=treatment_mean,
                        baseline_mean_net_pnl_usd=baseline_mean,
                        incremental_mean_net_pnl_usd=incremental,
                        win_rate=(sum(value > 0.0 for value in pnls) / len(pnls) if pnls else None),
                        max_drawdown_usd=_max_drawdown(treatment),
                        sample_bar_met=floor_met,
                        sample_bar_required=floor,
                        mean_net_pnl_ci=mean_ci.model_dump(mode="json"),
                        incremental_mean_ci=asdict(incremental_ci),
                        deflated_sharpe=dsr,
                    )
                )
    return cells


def _csv_ints(value: str) -> tuple[int, ...]:
    values = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not values or any(item < 0 for item in values):
        raise argparse.ArgumentTypeError("expected comma-separated non-negative integers")
    return values


def _csv_floats(value: str) -> tuple[float, ...]:
    values = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if not values or any(item < 0 for item in values):
        raise argparse.ArgumentTypeError("expected comma-separated non-negative numbers")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the pre-registered wallet x world-context grid. "
            "Research only; no production configuration is mutated."
        )
    )
    parser.add_argument("--category", default="CRYPTO")
    parser.add_argument("--time-period", default="MONTH")
    parser.add_argument("--cohort-ttl-hours", type=float, default=168.0)
    parser.add_argument("--max-context-age-hours", type=float, default=24.0)
    parser.add_argument("--copy-delays", type=_csv_ints, default=(60, 300, 900))
    parser.add_argument("--hold-hours", type=float, default=24.0)
    parser.add_argument("--cost-bps", type=_csv_floats, default=(25.0, 50.0, 100.0))
    parser.add_argument("--target-notional-usd", type=float, default=10.0)
    parser.add_argument("--copy-fraction", type=float, default=0.10)
    parser.add_argument("--max-resolution-seconds", type=int, default=1800)
    parser.add_argument("--max-staleness-seconds", type=int, default=1800)
    parser.add_argument("--holdout-fraction", type=float, default=0.30)
    parser.add_argument("--max-signals", type=int, default=500)
    parser.add_argument("--price-calls-per-minute", type=int, default=100)
    parser.add_argument("--warehouse-limit", type=int, default=100000)
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    warehouse = PostgresSignalWarehouse(settings.database_url)
    try:
        leaderboard_rows = await warehouse.load_wallet_observations(
            observation_type="leaderboard",
            limit=args.warehouse_limit,
        )
        trade_rows = await warehouse.load_wallet_observations(
            observation_type="trades",
            limit=args.warehouse_limit,
        )
        candidates = build_signal_candidates(
            leaderboard_rows=leaderboard_rows,
            trade_rows=trade_rows,
            category=args.category,
            time_period=args.time_period,
            cohort_ttl_hours=args.cohort_ttl_hours,
        )
        provider_rows: list[dict[str, object]] = []
        if candidates:
            signal_times = [candidate.trade.trade_at for candidate in candidates]
            provider_rows = await warehouse.load_provider_observations(
                start=min(signal_times) - timedelta(hours=args.max_context_age_hours),
                end=max(signal_times),
                limit=args.warehouse_limit,
            )
    finally:
        await warehouse.close()

    contexts = fuse_signal_context(
        candidates,
        provider_rows,
        max_age_hours=args.max_context_age_hours,
    )

    registry = ProviderRegistry(
        name="polymarket_data",
        timeout_seconds=min(settings.provider_timeout_seconds, 20.0),
        calls_per_minute=120,
        failure_threshold=3,
        health_recorder=ProviderHealthJournal(DEFAULT_PROVIDER_HEALTH_PATH).record,
    )
    client = PolymarketDataClient(registry=registry)
    lookup = PacedPriceLookup(
        lookup=client.price_as_of,
        calls_per_minute=args.price_calls_per_minute,
    )

    hold_seconds = int(args.hold_hours * 3600)
    runs: list[dict[str, object]] = []
    for delay in args.copy_delays:
        for cost_bps in args.cost_bps:
            scored, skipped = await score_candidates(
                candidates,
                price_lookup=lookup,
                copy_delay_seconds=delay,
                hold_seconds=hold_seconds,
                cost_bps_per_side=cost_bps,
                target_notional_usd=args.target_notional_usd,
                copy_fraction_of_leader=args.copy_fraction,
                max_resolution_seconds=args.max_resolution_seconds,
                max_staleness_seconds=args.max_staleness_seconds,
                max_signals=args.max_signals,
            )
            runs.append(
                {
                    "copy_delay_seconds": delay,
                    "cost_bps_per_side": cost_bps,
                    "candidate_count": len(candidates),
                    "scored_count": len(scored),
                    "skipped": skipped,
                    "cells": [
                        asdict(cell)
                        for cell in evaluate_context_grid(
                            scored,
                            contexts,
                            holdout_fraction=args.holdout_fraction,
                        )
                    ],
                    "pbo": {
                        "computed": False,
                        "skipped_reason": (
                            "context filters have non-common signal support; "
                            "zero-filling missing treatment observations is forbidden"
                        ),
                    },
                }
            )

    print(
        json.dumps(
            {
                "research_only": True,
                "execution_authority": False,
                "point_in_time_only": True,
                "catalog_frozen_in_issue_193": True,
                "context_ids": list(CONTEXT_IDS),
                "context_cells_per_base_grid": TRIALS_PER_BASE_GRID,
                "grid_cell_count_expected": (
                    len(HYPOTHESES) * len(args.copy_delays) * len(args.cost_bps) * len(CONTEXT_IDS)
                ),
                "split_row_count_expected": (
                    len(HYPOTHESES)
                    * len(args.copy_delays)
                    * len(args.cost_bps)
                    * len(CONTEXT_IDS)
                    * 3
                ),
                "base_configuration_count": (
                    len(HYPOTHESES) * len(args.copy_delays) * len(args.cost_bps)
                ),
                "discovery_min_signals": DISCOVERY_MIN_SIGNALS,
                "holdout_min_signals": HOLDOUT_MIN_SIGNALS,
                "holdout_fraction": args.holdout_fraction,
                "unique_price_points_fetched": lookup.cached_points,
                "runs": runs,
            },
            default=str,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
