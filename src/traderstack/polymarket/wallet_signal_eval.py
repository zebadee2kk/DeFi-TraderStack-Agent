from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from traderstack.config import Settings
from traderstack.market.registry import ProviderRegistry
from traderstack.polymarket.data_api import DataPricePoint, PolymarketDataClient
from traderstack.polymarket.wallet_cohorts import CohortMember, leaderboard_member
from traderstack.provider_health_journal import DEFAULT_PROVIDER_HEALTH_PATH, ProviderHealthJournal
from traderstack.signal_warehouse import PostgresSignalWarehouse

HypothesisId = Literal[
    "persistent_top10_follow",
    "top3_follow",
    "persistent_top10_fade",
]

HYPOTHESES: tuple[HypothesisId, ...] = (
    "persistent_top10_follow",
    "top3_follow",
    "persistent_top10_fade",
)


@dataclass(frozen=True)
class WalletTrade:
    wallet: str
    trade_at: datetime
    observed_at: datetime
    side: str
    token_id: str
    condition_id: str | None
    size: float
    leader_price: float
    outcome: str | None
    title: str | None
    transaction_hash: str | None


@dataclass(frozen=True)
class EligibleCohort:
    member: CohortMember
    appearances_to_date: int


@dataclass(frozen=True)
class SignalCandidate:
    hypothesis: HypothesisId
    cohort_snapshot_id: str
    cohort_snapshot_at: datetime
    wallet: str
    rank: int | None
    appearances_to_date: int
    trade: WalletTrade
    direction: int


@dataclass(frozen=True)
class ScoredSignal:
    hypothesis: HypothesisId
    wallet: str
    token_id: str
    condition_id: str | None
    trade_at: datetime
    cohort_snapshot_at: datetime
    copy_delay_seconds: int
    hold_seconds: int
    cost_bps_per_side: float
    copied_notional_usd: float
    entry_timestamp: int
    entry_price: float
    exit_timestamp: int
    exit_price: float
    gross_pnl_usd: float
    cost_usd: float
    net_pnl_usd: float
    direction: int
    title: str | None
    outcome: str | None


@dataclass(frozen=True)
class EvalSummary:
    hypothesis: HypothesisId
    split: str
    copy_delay_seconds: int
    hold_seconds: int
    cost_bps_per_side: float
    signals: int
    gross_pnl_usd: float
    net_pnl_usd: float
    win_rate: float | None
    max_drawdown_usd: float
    mean_net_pnl_usd: float | None


@dataclass
class PacedPriceLookup:
    lookup: Callable[[str, int], Awaitable[DataPricePoint | None]]
    calls_per_minute: int = 100
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    monotonic: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if not 1 <= self.calls_per_minute <= 120:
            raise ValueError("calls_per_minute must be between 1 and 120")
        self._cache: dict[tuple[str, int], DataPricePoint | None] = {}
        self._last_network_call_at: float | None = None
        self._lock = asyncio.Lock()

    async def __call__(self, token_id: str, timestamp: int) -> DataPricePoint | None:
        key = (token_id, timestamp)
        if key in self._cache:
            return self._cache[key]

        async with self._lock:
            if key in self._cache:
                return self._cache[key]

            interval = 60.0 / self.calls_per_minute
            now = self.monotonic()
            if self._last_network_call_at is not None:
                wait = interval - (now - self._last_network_call_at)
                if wait > 0:
                    await self.sleep(wait)

            value = await self.lookup(token_id, timestamp)
            self._last_network_call_at = self.monotonic()
            self._cache[key] = value
            return value

    @property
    def cached_points(self) -> int:
        return len(self._cache)


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _trade_time(value: object) -> datetime | None:
    timestamp = _int(value)
    if timestamp is None or timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def parse_trade_observations(rows: list[dict[str, object]]) -> list[WalletTrade]:
    seen: set[tuple[object, ...]] = set()
    trades: list[WalletTrade] = []

    for observation in rows:
        if observation.get("observation_type") != "trades":
            continue
        wallet = observation.get("wallet")
        observed_at = observation.get("observed_at")
        payload = observation.get("payload")
        if not isinstance(wallet, str) or not isinstance(observed_at, datetime):
            continue
        if not isinstance(payload, list):
            continue

        for raw in payload:
            if not isinstance(raw, dict):
                continue
            trade_at = _trade_time(raw.get("timestamp"))
            token_raw = raw.get("asset") or raw.get("token_id") or raw.get("tokenId")
            side_raw = raw.get("side")
            size = _float(raw.get("size"))
            price = _float(raw.get("price"))
            if (
                trade_at is None
                or not isinstance(token_raw, str)
                or not token_raw.strip()
                or not isinstance(side_raw, str)
                or size is None
                or size <= 0
                or price is None
                or not 0 < price < 1
            ):
                continue
            side = side_raw.upper()
            if side not in {"BUY", "SELL"}:
                continue

            transaction_hash_raw = raw.get("transaction_hash") or raw.get("transactionHash")
            transaction_hash = (
                str(transaction_hash_raw) if transaction_hash_raw is not None else None
            )
            condition_raw = raw.get("condition_id") or raw.get("conditionId")
            condition_id = str(condition_raw) if condition_raw is not None else None
            outcome_raw = raw.get("outcome")
            title_raw = raw.get("title")
            key = (
                transaction_hash,
                token_raw,
                int(trade_at.timestamp()),
                side,
                round(size, 12),
                round(price, 12),
                wallet.lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            trades.append(
                WalletTrade(
                    wallet=wallet.lower(),
                    trade_at=trade_at,
                    observed_at=observed_at.astimezone(UTC),
                    side=side,
                    token_id=token_raw.strip(),
                    condition_id=condition_id,
                    size=size,
                    leader_price=price,
                    outcome=str(outcome_raw) if outcome_raw is not None else None,
                    title=str(title_raw) if title_raw is not None else None,
                    transaction_hash=transaction_hash,
                )
            )
    return sorted(trades, key=lambda trade: (trade.trade_at, trade.wallet, trade.token_id))


def build_cohort_timeline(
    rows: list[dict[str, object]],
    *,
    category: str | None = None,
    time_period: str | None = None,
) -> dict[str, list[EligibleCohort]]:
    members = [member for row in rows if (member := leaderboard_member(row)) is not None]
    if category is not None:
        category_upper = category.upper()
        members = [member for member in members if member.category == category_upper]
    if time_period is not None:
        period_upper = time_period.upper()
        members = [member for member in members if member.time_period == period_upper]

    by_wallet: dict[str, list[CohortMember]] = {}
    for member in members:
        by_wallet.setdefault(member.wallet, []).append(member)

    output: dict[str, list[EligibleCohort]] = {}
    for wallet, wallet_members in by_wallet.items():
        ordered = sorted(wallet_members, key=lambda item: item.snapshot_at)
        output[wallet] = [
            EligibleCohort(member=member, appearances_to_date=index + 1)
            for index, member in enumerate(ordered)
        ]
    return output


def _eligible(hypothesis: HypothesisId, cohort: EligibleCohort) -> bool:
    rank = cohort.member.rank
    if rank is None:
        return False
    if hypothesis in {"persistent_top10_follow", "persistent_top10_fade"}:
        return rank <= 10 and cohort.appearances_to_date >= 2
    if hypothesis == "top3_follow":
        return rank <= 3
    return False


def _direction(hypothesis: HypothesisId) -> int:
    return -1 if hypothesis == "persistent_top10_fade" else 1


def build_signal_candidates(
    *,
    leaderboard_rows: list[dict[str, object]],
    trade_rows: list[dict[str, object]],
    category: str | None,
    time_period: str | None,
    cohort_ttl_hours: float,
) -> list[SignalCandidate]:
    if cohort_ttl_hours <= 0:
        raise ValueError("cohort_ttl_hours must be positive")
    timeline = build_cohort_timeline(
        leaderboard_rows,
        category=category,
        time_period=time_period,
    )
    trades = parse_trade_observations(trade_rows)
    ttl = timedelta(hours=cohort_ttl_hours)
    candidates: list[SignalCandidate] = []

    for trade in trades:
        # First executable slice is BUY-only. Mirroring a SELL would require
        # proving inventory/opposite-token availability and is therefore not
        # silently modelled as an executable copy.
        if trade.side != "BUY":
            continue
        cohorts = timeline.get(trade.wallet, [])
        prior = [
            cohort
            for cohort in cohorts
            if cohort.member.snapshot_at <= trade.trade_at
            and trade.trade_at <= cohort.member.snapshot_at + ttl
        ]
        if not prior:
            continue
        cohort = max(prior, key=lambda item: item.member.snapshot_at)
        for hypothesis in HYPOTHESES:
            if not _eligible(hypothesis, cohort):
                continue
            candidates.append(
                SignalCandidate(
                    hypothesis=hypothesis,
                    cohort_snapshot_id=cohort.member.snapshot_id,
                    cohort_snapshot_at=cohort.member.snapshot_at,
                    wallet=trade.wallet,
                    rank=cohort.member.rank,
                    appearances_to_date=cohort.appearances_to_date,
                    trade=trade,
                    direction=_direction(hypothesis),
                )
            )
    return candidates


def _acceptable_price(
    point: DataPricePoint | None,
    *,
    target_timestamp: int,
    max_resolution_seconds: int,
    max_staleness_seconds: int,
) -> bool:
    if point is None:
        return False
    if not 0 < point.price < 1:
        return False
    if point.timestamp > target_timestamp:
        return False
    if target_timestamp - point.timestamp > max_staleness_seconds:
        return False
    return not (
        point.resolution_seconds is not None and point.resolution_seconds > max_resolution_seconds
    )


async def score_candidates(
    candidates: list[SignalCandidate],
    *,
    price_lookup: Callable[[str, int], Awaitable[DataPricePoint | None]],
    copy_delay_seconds: int,
    hold_seconds: int,
    cost_bps_per_side: float,
    target_notional_usd: float,
    copy_fraction_of_leader: float,
    max_resolution_seconds: int,
    max_staleness_seconds: int,
    max_signals: int,
) -> tuple[list[ScoredSignal], dict[str, int]]:
    if copy_delay_seconds < 0:
        raise ValueError("copy_delay_seconds cannot be negative")
    if hold_seconds <= 0:
        raise ValueError("hold_seconds must be positive")
    if cost_bps_per_side < 0:
        raise ValueError("cost_bps_per_side cannot be negative")
    if target_notional_usd <= 0:
        raise ValueError("target_notional_usd must be positive")
    if not 0 < copy_fraction_of_leader <= 1:
        raise ValueError("copy_fraction_of_leader must be in (0, 1]")
    if max_signals <= 0:
        raise ValueError("max_signals must be positive")

    cache: dict[tuple[str, int], DataPricePoint | None] = {}
    scored: list[ScoredSignal] = []
    skipped = {
        "price_unavailable_or_too_coarse": 0,
        "capacity_too_small": 0,
        "max_signals": 0,
    }

    async def lookup(token_id: str, timestamp: int) -> DataPricePoint | None:
        key = (token_id, timestamp)
        if key not in cache:
            cache[key] = await price_lookup(token_id, timestamp)
        return cache[key]

    for candidate in sorted(candidates, key=lambda item: item.trade.trade_at):
        if len(scored) >= max_signals:
            skipped["max_signals"] += 1
            continue
        trade = candidate.trade
        signal_timestamp = int(trade.trade_at.timestamp())
        entry_target = signal_timestamp + copy_delay_seconds
        exit_target = entry_target + hold_seconds
        entry = await lookup(trade.token_id, entry_target)
        exit_point = await lookup(trade.token_id, exit_target)
        if not _acceptable_price(
            entry,
            target_timestamp=entry_target,
            max_resolution_seconds=max_resolution_seconds,
            max_staleness_seconds=max_staleness_seconds,
        ) or not _acceptable_price(
            exit_point,
            target_timestamp=exit_target,
            max_resolution_seconds=max_resolution_seconds,
            max_staleness_seconds=max_staleness_seconds,
        ):
            skipped["price_unavailable_or_too_coarse"] += 1
            continue
        assert entry is not None and exit_point is not None

        leader_notional = trade.size * trade.leader_price
        copied_notional = min(
            target_notional_usd,
            leader_notional * copy_fraction_of_leader,
        )
        if copied_notional < 1.0:
            skipped["capacity_too_small"] += 1
            continue

        shares = copied_notional / entry.price
        gross = candidate.direction * shares * (exit_point.price - entry.price)
        cost_rate = cost_bps_per_side / 10_000.0
        cost = shares * (entry.price + exit_point.price) * cost_rate
        net = gross - cost
        scored.append(
            ScoredSignal(
                hypothesis=candidate.hypothesis,
                wallet=candidate.wallet,
                token_id=trade.token_id,
                condition_id=trade.condition_id,
                trade_at=trade.trade_at,
                cohort_snapshot_at=candidate.cohort_snapshot_at,
                copy_delay_seconds=copy_delay_seconds,
                hold_seconds=hold_seconds,
                cost_bps_per_side=cost_bps_per_side,
                copied_notional_usd=copied_notional,
                entry_timestamp=entry.timestamp,
                entry_price=entry.price,
                exit_timestamp=exit_point.timestamp,
                exit_price=exit_point.price,
                gross_pnl_usd=gross,
                cost_usd=cost,
                net_pnl_usd=net,
                direction=candidate.direction,
                title=trade.title,
                outcome=trade.outcome,
            )
        )
    return scored, skipped


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown


def summarize(
    scored: list[ScoredSignal],
    *,
    holdout_fraction: float,
) -> list[EvalSummary]:
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be in (0, 1)")
    summaries: list[EvalSummary] = []

    for hypothesis in HYPOTHESES:
        rows = sorted(
            (row for row in scored if row.hypothesis == hypothesis),
            key=lambda row: row.trade_at,
        )
        if not rows:
            continue
        split_index = max(1, int(len(rows) * (1.0 - holdout_fraction)))
        split_index = min(split_index, len(rows))
        groups = (
            ("discovery", rows[:split_index]),
            ("holdout", rows[split_index:]),
            ("all", rows),
        )
        for split, group in groups:
            if not group:
                continue
            pnls = [row.net_pnl_usd for row in group]
            wins = sum(pnl > 0 for pnl in pnls)
            summaries.append(
                EvalSummary(
                    hypothesis=hypothesis,
                    split=split,
                    copy_delay_seconds=group[0].copy_delay_seconds,
                    hold_seconds=group[0].hold_seconds,
                    cost_bps_per_side=group[0].cost_bps_per_side,
                    signals=len(group),
                    gross_pnl_usd=sum(row.gross_pnl_usd for row in group),
                    net_pnl_usd=sum(pnls),
                    win_rate=wins / len(group),
                    max_drawdown_usd=_max_drawdown(pnls),
                    mean_net_pnl_usd=sum(pnls) / len(group),
                )
            )
    return summaries


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
            "Evaluate pre-registered point-in-time Polymarket wallet follow/fade hypotheses. "
            "Research only; produces no orders."
        )
    )
    parser.add_argument("--category", default="CRYPTO")
    parser.add_argument("--time-period", default="MONTH")
    parser.add_argument("--cohort-ttl-hours", type=float, default=168.0)
    parser.add_argument("--copy-delays", type=_csv_ints, default=(60, 300, 900))
    parser.add_argument("--hold-hours", type=float, default=24.0)
    parser.add_argument("--cost-bps", type=_csv_floats, default=(25.0, 50.0, 100.0))
    parser.add_argument("--target-notional-usd", type=float, default=10.0)
    parser.add_argument("--copy-fraction", type=float, default=0.10)
    parser.add_argument("--max-resolution-seconds", type=int, default=1800)
    parser.add_argument("--max-staleness-seconds", type=int, default=1800)
    parser.add_argument("--holdout-fraction", type=float, default=0.30)
    parser.add_argument("--max-signals", type=int, default=500)
    parser.add_argument(
        "--price-calls-per-minute",
        type=int,
        default=100,
        help="pace unique Polymarket price-history calls below the 120/min provider ceiling",
    )
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
    finally:
        await warehouse.close()

    candidates = build_signal_candidates(
        leaderboard_rows=leaderboard_rows,
        trade_rows=trade_rows,
        category=args.category,
        time_period=args.time_period,
        cohort_ttl_hours=args.cohort_ttl_hours,
    )

    registry = ProviderRegistry(
        name="polymarket_data",
        timeout_seconds=min(settings.provider_timeout_seconds, 20.0),
        calls_per_minute=120,
        failure_threshold=3,
        health_recorder=ProviderHealthJournal(DEFAULT_PROVIDER_HEALTH_PATH).record,
    )
    client = PolymarketDataClient(registry=registry)
    paced_price_lookup = PacedPriceLookup(
        lookup=client.price_as_of,
        calls_per_minute=args.price_calls_per_minute,
    )

    all_runs: list[dict[str, object]] = []
    hold_seconds = int(args.hold_hours * 3600)
    for delay in args.copy_delays:
        for cost_bps in args.cost_bps:
            scored, skipped = await score_candidates(
                candidates,
                price_lookup=paced_price_lookup,
                copy_delay_seconds=delay,
                hold_seconds=hold_seconds,
                cost_bps_per_side=cost_bps,
                target_notional_usd=args.target_notional_usd,
                copy_fraction_of_leader=args.copy_fraction,
                max_resolution_seconds=args.max_resolution_seconds,
                max_staleness_seconds=args.max_staleness_seconds,
                max_signals=args.max_signals,
            )
            all_runs.append(
                {
                    "copy_delay_seconds": delay,
                    "cost_bps_per_side": cost_bps,
                    "candidate_count": len(candidates),
                    "scored_count": len(scored),
                    "skipped": skipped,
                    "summaries": [
                        asdict(summary)
                        for summary in summarize(
                            scored,
                            holdout_fraction=args.holdout_fraction,
                        )
                    ],
                }
            )

    print(
        json.dumps(
            {
                "research_only": True,
                "execution_authority": False,
                "category": args.category.upper(),
                "time_period": args.time_period.upper(),
                "hypotheses": list(HYPOTHESES),
                "cohort_ttl_hours": args.cohort_ttl_hours,
                "hold_hours": args.hold_hours,
                "target_notional_usd": args.target_notional_usd,
                "copy_fraction_of_leader": args.copy_fraction,
                "max_resolution_seconds": args.max_resolution_seconds,
                "max_staleness_seconds": args.max_staleness_seconds,
                "holdout_fraction": args.holdout_fraction,
                "price_calls_per_minute": args.price_calls_per_minute,
                "unique_price_points_fetched": paced_price_lookup.cached_points,
                "runs": all_runs,
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
