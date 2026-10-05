from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from traderstack.config import Settings
from traderstack.polymarket.wallet_signal_eval import SignalCandidate, build_signal_candidates
from traderstack.signal_warehouse import PostgresSignalWarehouse

_GLOBAL_ASSETS = {"GLOBAL", "ALL", "MARKET", "WORLD"}
_ASSET_ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("BTC", "BITCOIN"),
    "ETH": ("ETH", "ETHEREUM"),
    "SOL": ("SOL", "SOLANA"),
}


@dataclass(frozen=True)
class ProviderContext:
    source_id: str
    asset: str
    observed_at: datetime
    age_seconds: int
    payload: dict[str, object]
    observation_type: str = "legacy_provider"


@dataclass(frozen=True)
class FusedSignalContext:
    hypothesis: str
    wallet: str
    token_id: str
    condition_id: str | None
    signal_at: datetime
    title: str | None
    outcome: str | None
    provider_context: tuple[ProviderContext, ...]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _market_assets(candidate: SignalCandidate) -> set[str]:
    text = " ".join(
        part for part in (candidate.trade.title, candidate.trade.outcome) if part
    ).upper()
    tokens = set(re.findall(r"[A-Z0-9]+", text))
    assets: set[str] = set()
    for asset, aliases in _ASSET_ALIASES.items():
        if any(alias in tokens for alias in aliases):
            assets.add(asset)
    return assets


def _eligible_asset(asset: str, market_assets: set[str]) -> bool:
    normalized = asset.upper()
    return normalized in _GLOBAL_ASSETS or normalized in market_assets


def _native_payload(observation_type: str, payload: dict[str, object]) -> dict[str, object] | None:
    if observation_type == "news":
        return {
            "news": {
                "event_score": payload.get("event_score"),
                "adverse_event": payload.get("adverse_event"),
                "item_count": payload.get("item_count"),
            }
        }
    if observation_type == "social":
        return {
            "narrative": {
                "sentiment": payload.get("sentiment"),
                "mention_velocity_z": payload.get("mention_velocity_z"),
            }
        }
    if observation_type == "onchain":
        return {
            "onchain": {
                "exchange_netflow_z": payload.get("exchange_netflow_z"),
                "large_wallet_accumulation": payload.get("large_wallet_accumulation"),
            }
        }
    if observation_type == "altfins":
        return {"market": {"external_signal_score": payload.get("score")}}
    if observation_type == "onchain_regime":
        return {
            "onchain": {
                key: payload.get(key)
                for key in (
                    "mvrv_z",
                    "mvrv_z_percentile",
                    "nupl",
                    "as_of",
                    "feature_version",
                )
            }
        }
    return None


def _canonical_edge_payload(payload: dict[str, object]) -> dict[str, object] | None:
    edge = payload.get("edge")
    if not isinstance(edge, dict):
        return None
    return {"edge": dict(edge)}


def fuse_signal_context(
    candidates: list[SignalCandidate],
    provider_rows: list[dict[str, object]] | None = None,
    *,
    native_rows: list[dict[str, object]] | None = None,
    canonical_rows: list[dict[str, object]] | None = None,
    max_age_hours: float = 24.0,
) -> list[FusedSignalContext]:
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")

    max_age = timedelta(hours=max_age_hours)
    parsed: list[tuple[datetime, str, str, str, dict[str, object]]] = []

    # Backward-compatible legacy rows remain accepted for tests/tools, but the
    # production evaluator no longer loads duplicated provider_observations.
    for row in provider_rows or []:
        observed_at = row.get("observed_at")
        source_id = row.get("source_id")
        asset = row.get("asset")
        payload = row.get("payload")
        if (
            not isinstance(observed_at, datetime)
            or not isinstance(source_id, str)
            or not source_id
            or not isinstance(asset, str)
            or not asset
            or not isinstance(payload, dict)
        ):
            continue
        parsed.append(
            (_as_utc(observed_at), source_id, "legacy_provider", asset.upper(), payload)
        )

    for row in native_rows or []:
        observed_at = row.get("observed_at")
        source_id = row.get("source_id")
        observation_type = row.get("observation_type")
        asset = row.get("asset")
        payload = row.get("payload")
        if (
            not isinstance(observed_at, datetime)
            or not isinstance(source_id, str)
            or not source_id
            or not isinstance(observation_type, str)
            or not isinstance(asset, str)
            or not asset
            or not isinstance(payload, dict)
        ):
            continue
        normalized = _native_payload(observation_type, payload)
        if normalized is None:
            continue
        parsed.append(
            (_as_utc(observed_at), source_id, observation_type, asset.upper(), normalized)
        )

    for row in canonical_rows or []:
        observed_at = row.get("observed_at")
        asset = row.get("asset")
        payload = row.get("payload")
        if (
            not isinstance(observed_at, datetime)
            or not isinstance(asset, str)
            or not asset
            or not isinstance(payload, dict)
        ):
            continue
        normalized = _canonical_edge_payload(payload)
        if normalized is None:
            continue
        parsed.append(
            (
                _as_utc(observed_at),
                "canonical:feature",
                "canonical_feature",
                asset.upper(),
                normalized,
            )
        )

    fused: list[FusedSignalContext] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            item.trade.trade_at,
            item.wallet,
            item.trade.token_id,
            item.hypothesis,
        ),
    ):
        signal_at = _as_utc(candidate.trade.trade_at)
        market_assets = _market_assets(candidate)
        latest: dict[tuple[str, str, str], tuple[datetime, dict[str, object]]] = {}

        for observed_at, source_id, observation_type, asset, payload in parsed:
            if observed_at > signal_at:
                continue
            if signal_at - observed_at > max_age:
                continue
            if not _eligible_asset(asset, market_assets):
                continue
            key = (source_id, observation_type, asset)
            current = latest.get(key)
            if current is None or observed_at > current[0]:
                latest[key] = (observed_at, payload)

        context = tuple(
            ProviderContext(
                source_id=source_id,
                asset=asset,
                observed_at=observed_at,
                age_seconds=max(0, int((signal_at - observed_at).total_seconds())),
                payload=payload,
                observation_type=observation_type,
            )
            for (source_id, observation_type, asset), (observed_at, payload) in sorted(
                latest.items()
            )
        )
        fused.append(
            FusedSignalContext(
                hypothesis=candidate.hypothesis,
                wallet=candidate.wallet,
                token_id=candidate.trade.token_id,
                condition_id=candidate.trade.condition_id,
                signal_at=signal_at,
                title=candidate.trade.title,
                outcome=candidate.trade.outcome,
                provider_context=context,
            )
        )
    return fused

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Join point-in-time provider observations to Polymarket wallet signal candidates. "
            "Research only; produces no orders and grants no execution authority."
        )
    )
    parser.add_argument("--category", default="CRYPTO")
    parser.add_argument("--time-period", default="MONTH")
    parser.add_argument("--cohort-ttl-hours", type=float, default=168.0)
    parser.add_argument("--max-context-age-hours", type=float, default=24.0)
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
            signal_times = [_as_utc(item.trade.trade_at) for item in candidates]
            provider_rows = await warehouse.load_provider_observations(
                start=min(signal_times) - timedelta(hours=args.max_context_age_hours),
                end=max(signal_times),
                limit=args.warehouse_limit,
            )
    finally:
        await warehouse.close()

    fused = fuse_signal_context(
        candidates,
        provider_rows,
        max_age_hours=args.max_context_age_hours,
    )
    print(
        json.dumps(
            {
                "research_only": True,
                "execution_authority": False,
                "point_in_time_only": True,
                "category": args.category.upper(),
                "time_period": args.time_period.upper(),
                "max_context_age_hours": args.max_context_age_hours,
                "candidate_count": len(candidates),
                "provider_observation_count": len(provider_rows),
                "contexts_with_provider_data": sum(bool(item.provider_context) for item in fused),
                "contexts": [asdict(item) for item in fused],
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
