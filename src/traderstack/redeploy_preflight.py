from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass

from traderstack.config import Settings
from traderstack.resource_audit import (
    ACTIVE,
    apply_journal_health,
    BLOCKED_CREDENTIAL,
    build_rows,
    probe_public,
    ResourceRow,
)
from traderstack.signal_warehouse import PostgresSignalWarehouse


STRICT_RESOURCE_NAMES = (
    "Dune",
    "LunarCrush",
    "CryptoPanic",
    "Perplexity",
    "altFINS",
    "Crucix",
    "CoinGecko",
    "CoinMarketCap",
)

BASELINE_DISABLED_FLAGS = (
    "paper_garch_size",
    "paper_perp_hedge",
    "paper_carry_hedge_diagnostic",
    "opportunity_diagnostic_mode",
)


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str
    blocking: bool = True


def _bool_setting(settings: Settings, name: str) -> bool:
    return bool(getattr(settings, name, False))


def build_static_checks(settings: Settings) -> list[PreflightCheck]:
    checks = [
        PreflightCheck(
            name="trading_mode",
            ok=settings.trading_mode == "paper",
            detail=f"TRADING_MODE={settings.trading_mode}",
        ),
        PreflightCheck(
            name="kill_switch_bootstrap",
            ok=settings.kill_switch,
            detail=(
                "engaged; safe bootstrap"
                if settings.kill_switch
                else "disengaged; redeploy bootstrap must start fail-closed"
            ),
        ),
    ]

    promotion_flags = sorted(
        name
        for name, value in settings.model_dump().items()
        if name.startswith("paper_promote_") and isinstance(value, bool) and value
    )
    checks.append(
        PreflightCheck(
            name="promotion_flags",
            ok=not promotion_flags,
            detail=(
                "all PAPER_PROMOTE_* flags false"
                if not promotion_flags
                else "enabled: " + ", ".join(promotion_flags)
            ),
        )
    )

    active_baseline_flags = [
        name for name in BASELINE_DISABLED_FLAGS if _bool_setting(settings, name)
    ]
    checks.append(
        PreflightCheck(
            name="experimental_execution_flags",
            ok=not active_baseline_flags,
            detail=(
                "paper hedge/GARCH/diagnostic flags off"
                if not active_baseline_flags
                else "enabled: " + ", ".join(active_baseline_flags)
            ),
        )
    )
    return checks


def resource_checks(
    rows: list[ResourceRow],
    *,
    strict_resources: bool,
    require_active_resources: bool = False,
) -> list[PreflightCheck]:
    by_name = {row.provider: row for row in rows}
    checks: list[PreflightCheck] = []

    polymarket = by_name.get("Polymarket Data API")
    checks.append(
        PreflightCheck(
            name="polymarket_data_api",
            ok=polymarket is not None and polymarket.status == ACTIVE,
            detail=(
                f"{polymarket.status}; network={polymarket.network}"
                if polymarket is not None
                else "resource row missing"
            ),
        )
    )

    for name in STRICT_RESOURCE_NAMES:
        row = by_name.get(name)
        configured = row is not None and row.configured
        active_or_configured = configured and row.status not in {BLOCKED_CREDENTIAL}
        ready = row is not None and row.status == ACTIVE if require_active_resources else active_or_configured
        checks.append(
            PreflightCheck(
                name=f"resource:{name}",
                ok=ready if strict_resources or require_active_resources else True,
                detail=(
                    f"{row.status}; configured={row.configured}; "
                    f"credential_source={row.credential_source}; network={row.network}"
                    if row is not None
                    else "resource row missing"
                ),
                blocking=strict_resources or require_active_resources,
            )
        )
    return checks


async def database_check(settings: Settings) -> PreflightCheck:
    warehouse = PostgresSignalWarehouse(settings.database_url)
    try:
        await warehouse.initialize()
        await warehouse.load_features(limit=1)
        await warehouse.load_wallet_observations(limit=1)
        await warehouse.load_collector_health(limit=1)
    except Exception as exc:  # noqa: BLE001 - preflight must report the boundary.
        return PreflightCheck(
            name="signal_warehouse",
            ok=False,
            detail=f"{type(exc).__name__}: database/schema check failed",
        )
    finally:
        await warehouse.close()
    return PreflightCheck(
        name="signal_warehouse",
        ok=True,
        detail="database reachable; warehouse tables initialized/queryable",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed Grokbot redeploy preflight. Safe to log: no secret values are printed."
        )
    )
    parser.add_argument(
        "--strict-resources",
        action="store_true",
        help=(
            "require Dune, LunarCrush, CryptoPanic, Perplexity, altFINS and Crucix "
            "to be configured before declaring ready"
        ),
    )
    parser.add_argument(
        "--require-active-resources",
        action="store_true",
        help=(
            "post-start gate: require every strict resource to have ACTIVE health "
            "evidence, not merely configuration"
        ),
    )
    parser.add_argument(
        "--skip-network",
        action="store_true",
        help="skip read-only public endpoint probes",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    checks = build_static_checks(settings)

    rows = apply_journal_health(build_rows(settings))
    if not args.skip_network:
        rows = await probe_public(rows, settings)
    strict_resources = bool(args.strict_resources or args.require_active_resources)
    checks.extend(
        resource_checks(
            rows,
            strict_resources=strict_resources,
            require_active_resources=bool(args.require_active_resources),
        )
    )
    checks.append(await database_check(settings))

    ready = all(check.ok or not check.blocking for check in checks)
    payload = {
        "ready": ready,
        "mode": "bootstrap",
        "strict_resources": strict_resources,
        "require_active_resources": bool(args.require_active_resources),
        "checks": [asdict(check) for check in checks],
        "operator_actions": [
            row.action
            for row in rows
            if strict_resources
            and row.provider in STRICT_RESOURCE_NAMES
            and not row.configured
        ],
        "safety": {
            "execution_authority_changed": False,
            "live_capital_enabled": False,
            "bootstrap_requires_kill_switch": True,
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("READY" if ready else "NOT READY")
        for check in checks:
            marker = "PASS" if check.ok else ("WARN" if not check.blocking else "FAIL")
            print(f"{marker:4} {check.name}: {check.detail}")
        for action in payload["operator_actions"]:
            print(f"ACTION: {action}")
    return 0 if ready else 2


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
