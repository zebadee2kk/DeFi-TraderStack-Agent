from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from traderstack.config import Settings
from traderstack.intelligence import NewsSnapshot
from traderstack.market.crucix import (
    CrucixIntelProvider,
    crucix_effective_base_url,
    crucix_should_register,
)
from traderstack.signal_warehouse import PostgresSignalWarehouse

PROVIDER_NAME = "polymarket_research:crucix"
CrucixProbe = Callable[[str], Awaitable[NewsSnapshot]]


def _secret(value: object) -> str | None:
    getter = getattr(value, "get_secret_value", None)
    raw = getter() if callable(getter) else value
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    return stripped or None


@dataclass(frozen=True)
class ResearchProviderHealth:
    provider: str
    state: str
    configured: bool
    operational_probe: bool
    error_type: str | None = None


async def assess_crucix_research_health(
    settings: Settings,
    *,
    probe: CrucixProbe | None = None,
) -> ResearchProviderHealth:
    api_key = _secret(settings.crucix_api_key)
    configured = crucix_should_register(
        enabled=settings.crucix_enabled,
        base_url=settings.crucix_base_url,
        api_key=api_key,
    )
    if not configured:
        return ResearchProviderHealth(
            provider=PROVIDER_NAME,
            state="not_configured",
            configured=False,
            operational_probe=False,
        )

    if probe is None:
        provider = CrucixIntelProvider(
            base_url=crucix_effective_base_url(settings.crucix_base_url),
            api_key=api_key,
        )
        probe = provider.fetch

    try:
        snapshot = await probe("BTC")
    except Exception as exc:  # noqa: BLE001 - health boundary reports type only.
        return ResearchProviderHealth(
            provider=PROVIDER_NAME,
            state="unavailable",
            configured=True,
            operational_probe=True,
            error_type=type(exc).__name__,
        )

    if not isinstance(snapshot, NewsSnapshot):
        return ResearchProviderHealth(
            provider=PROVIDER_NAME,
            state="unavailable",
            configured=True,
            operational_probe=True,
            error_type="invalid_snapshot",
        )
    return ResearchProviderHealth(
        provider=PROVIDER_NAME,
        state="active",
        configured=True,
        operational_probe=True,
    )


def health_row(
    report: ResearchProviderHealth,
    *,
    observed_at: datetime,
) -> dict[str, object]:
    payload = {
        **asdict(report),
        "healthy": report.state == "active",
        "research_program": "polymarket_wallet_world_signal",
    }
    canonical = json.dumps(
        {
            "observed_at": observed_at.isoformat(),
            **payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "event_key": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "observed_at": observed_at,
        "provider": report.provider,
        "state": report.state,
        "payload": payload,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record Crucix operational health for the Polymarket wallet/world-signal "
            "research program. Read-only; changes no trading authority."
        )
    )
    parser.add_argument(
        "--require-healthy",
        action="store_true",
        help="exit non-zero unless Crucix is configured and the read-only probe succeeds",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    report = await assess_crucix_research_health(settings)
    observed_at = datetime.now(UTC)
    warehouse = PostgresSignalWarehouse(settings.database_url)
    await warehouse.initialize()
    try:
        inserted = await warehouse.append_collector_health(
            [health_row(report, observed_at=observed_at)]
        )
    finally:
        await warehouse.close()

    print(
        json.dumps(
            {
                **asdict(report),
                "healthy": report.state == "active",
                "row_inserted": inserted,
                "execution_authority_changed": False,
            },
            sort_keys=True,
        )
    )
    if args.require_healthy and report.state != "active":
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
