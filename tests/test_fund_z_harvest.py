"""Unit tests for paper-perp fund-z harvest catalog."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.research.fund_z_harvest import (
    HARVEST_CATALOG,
    HARVEST_IDS,
    run_fund_z_harvest,
)


def _series(values: list[float], start: datetime | None = None):
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return tuple((opened + timedelta(days=i), v) for i, v in enumerate(values))


def test_catalog_ids_frozen() -> None:
    assert HARVEST_IDS == (
        "fund_z_harvest_z_1_0",
        "fund_z_harvest_z_1_5",
        "fund_z_harvest_z_2_0",
        "fund_z_harvest_abs_2bp",
        "fund_z_harvest_sign_hold",
    )
    assert len(HARVEST_CATALOG) == 5
    assert "carry_hedged_sign" not in HARVEST_IDS


def test_requires_dual_basis() -> None:
    funding = {
        "BTC/USD": _series([0.0001] * 800),
        "ETH/USD": _series([0.0001] * 800),
    }
    report = run_fund_z_harvest(
        hl_funding=funding,
        htx_funding=funding,
        okx_basis={},
        vision_basis={},
    )
    assert report.print_kind == "unavailable"
    assert report.dual_print_passers == 0
    assert report.can_promote is False
    assert report.keep_flag_false is True
