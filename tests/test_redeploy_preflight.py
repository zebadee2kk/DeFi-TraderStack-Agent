from traderstack.config import Settings
from traderstack.redeploy_preflight import (
    STRICT_RESOURCE_NAMES,
    build_static_checks,
    host_published_settings,
    resource_checks,
)
from traderstack.resource_audit import (
    BLOCKED_CREDENTIAL,
    IMPLEMENTED_NOT_PROVEN,
    ResourceRow,
)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "trading_mode": "paper",
        "kill_switch": True,
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def row(provider: str, *, configured: bool, status: str) -> ResourceRow:
    return ResourceRow(
        provider=provider,
        role="test",
        status=status,
        configured=configured,
        credential_source="env" if configured else "unset",
        network="not_probed",
        auth="not_probed",
        last_success="not_recorded",
        rows_24h=0,
        rows_7d=0,
        destination="test",
        stale="unknown",
        action=f"configure {provider}",
    )


def test_static_bootstrap_requires_paper_and_kill_switch() -> None:
    checks = {check.name: check for check in build_static_checks(settings())}
    assert checks["trading_mode"].ok
    assert checks["kill_switch_bootstrap"].ok
    assert checks["promotion_flags"].ok
    assert checks["experimental_execution_flags"].ok


def test_static_bootstrap_rejects_disengaged_kill_switch() -> None:
    checks = {check.name: check for check in build_static_checks(settings(kill_switch=False))}
    assert not checks["kill_switch_bootstrap"].ok


def test_static_bootstrap_rejects_promotion_pin() -> None:
    checks = {
        check.name: check for check in build_static_checks(settings(paper_promote_ema_9_21=True))
    }
    assert not checks["promotion_flags"].ok
    assert "paper_promote_ema_9_21" in checks["promotion_flags"].detail


def test_strict_resources_fail_when_keyed_source_missing() -> None:
    rows = [row("Polymarket Data API", configured=True, status="ACTIVE")]
    rows.extend(
        row(name, configured=False, status=BLOCKED_CREDENTIAL) for name in STRICT_RESOURCE_NAMES
    )
    checks = resource_checks(rows, strict_resources=True)
    dune = next(check for check in checks if check.name == "resource:Dune")
    assert not dune.ok
    assert dune.blocking


def test_non_strict_resources_report_missing_without_blocking() -> None:
    rows = [row("Polymarket Data API", configured=True, status="ACTIVE")]
    rows.extend(
        row(name, configured=False, status=BLOCKED_CREDENTIAL) for name in STRICT_RESOURCE_NAMES
    )
    checks = resource_checks(rows, strict_resources=False)
    assert all(check.ok or not check.blocking for check in checks)


def test_strict_resources_accept_configured_not_yet_proven_sources() -> None:
    rows = [row("Polymarket Data API", configured=True, status="ACTIVE")]
    rows.extend(
        row(name, configured=True, status=IMPLEMENTED_NOT_PROVEN) for name in STRICT_RESOURCE_NAMES
    )
    checks = resource_checks(rows, strict_resources=True)
    assert all(check.ok for check in checks)


def test_require_active_resources_rejects_configured_unproven() -> None:
    rows = [row("Polymarket Data API", configured=True, status="ACTIVE")]
    rows.extend(
        row(name, configured=True, status=IMPLEMENTED_NOT_PROVEN) for name in STRICT_RESOURCE_NAMES
    )
    checks = resource_checks(
        rows,
        strict_resources=True,
        require_active_resources=True,
    )
    dune = next(check for check in checks if check.name == "resource:Dune")
    assert not dune.ok
    assert dune.blocking


def test_require_active_resources_accepts_recent_successes() -> None:
    rows = [row("Polymarket Data API", configured=True, status="ACTIVE")]
    rows.extend(row(name, configured=True, status="ACTIVE") for name in STRICT_RESOURCE_NAMES)
    checks = resource_checks(
        rows,
        strict_resources=True,
        require_active_resources=True,
    )
    assert all(check.ok for check in checks)


def test_host_published_settings_rewrites_compose_dns_only() -> None:
    cfg = settings(
        database_url="postgresql+asyncpg://u:p@postgres:5432/traderstack",
        redis_url="redis://redis:6379/0",
    )
    host = host_published_settings(cfg)
    assert host.database_url == "postgresql+asyncpg://u:p@127.0.0.1:5432/traderstack"
    assert host.redis_url == "redis://127.0.0.1:6379/0"


def test_host_published_settings_leaves_existing_host_urls_alone() -> None:
    cfg = settings()
    host = host_published_settings(cfg)
    assert host.database_url == cfg.database_url
    assert host.redis_url == cfg.redis_url
