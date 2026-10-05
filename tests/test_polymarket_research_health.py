from datetime import UTC, datetime

import pytest

from traderstack.config import Settings
from traderstack.intelligence import NewsSnapshot
from traderstack.polymarket.research_health import (
    PROVIDER_NAME,
    ResearchProviderHealth,
    assess_crucix_research_health,
    health_row,
)


@pytest.mark.asyncio
async def test_unconfigured_crucix_is_explicit_research_health_failure() -> None:
    report = await assess_crucix_research_health(
        Settings(
            crucix_enabled=False,
            crucix_base_url="",
            crucix_api_key=None,
        )
    )

    assert report.provider == PROVIDER_NAME
    assert report.state == "not_configured"
    assert not report.configured
    assert not report.operational_probe


@pytest.mark.asyncio
async def test_configured_crucix_requires_successful_operational_probe() -> None:
    async def probe(asset: str) -> NewsSnapshot:
        assert asset == "BTC"
        return NewsSnapshot(
            asset=asset,
            event_score=0.2,
            adverse_event=False,
            item_count=1,
            source_id="crucix:data",
        )

    report = await assess_crucix_research_health(
        Settings(crucix_enabled=True),
        probe=probe,
    )

    assert report.state == "active"
    assert report.configured
    assert report.operational_probe
    assert report.error_type is None


@pytest.mark.asyncio
async def test_failed_crucix_probe_is_unavailable_without_error_text() -> None:
    async def probe(_: str) -> NewsSnapshot:
        raise RuntimeError("secret-bearing upstream detail")

    report = await assess_crucix_research_health(
        Settings(crucix_enabled=True),
        probe=probe,
    )

    assert report.state == "unavailable"
    assert report.error_type == "RuntimeError"
    assert "secret" not in str(report)


def test_research_health_row_marks_non_active_state_unhealthy() -> None:
    observed_at = datetime(2026, 10, 5, 10, tzinfo=UTC)
    row = health_row(
        ResearchProviderHealth(
            provider=PROVIDER_NAME,
            state="not_configured",
            configured=False,
            operational_probe=False,
        ),
        observed_at=observed_at,
    )

    assert row["provider"] == PROVIDER_NAME
    assert row["state"] == "not_configured"
    payload = row["payload"]
    assert isinstance(payload, dict)
    assert payload["healthy"] is False
    assert payload["research_program"] == "polymarket_wallet_world_signal"
    assert len(str(row["event_key"])) == 64
