"""The on-chain regime gate is versioned into `policy_version` (#139).

The gate in `pipeline.process` can reject a BUY that the same cycle would have
built with the gate off, without `RiskEngine.evaluate` ever seeing a different
proposal. That is the SEC-2026-09-18 shape, so the three fields that decide its
verdict are control plane and must move the digest; the endpoint it reads from
must not. The gate can only ever *add* a rejection, so none of this lets it
authorise anything -- pinned here alongside the versioning.
"""

from __future__ import annotations

import pytest

from traderstack.config import Settings
from traderstack.policy_fields import NON_POLICY_FIELDS
from traderstack.risk import CONTROL_PLANE_FIELDS, RISK_LIMIT_FIELDS, derive_policy_version


def settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "onchain_regime_gate_enabled",
        "onchain_regime_max_percentile",
        "onchain_regime_source_asset",
    ],
)
def test_gate_fields_are_control_plane(field: str) -> None:
    assert field in CONTROL_PLANE_FIELDS
    assert field not in RISK_LIMIT_FIELDS
    assert field not in NON_POLICY_FIELDS


def test_endpoint_is_non_policy() -> None:
    assert "coinmetrics_base_url" in NON_POLICY_FIELDS
    assert "coinmetrics_base_url" not in CONTROL_PLANE_FIELDS
    assert "coinmetrics_base_url" not in RISK_LIMIT_FIELDS


@pytest.mark.parametrize(
    "change",
    [
        {"onchain_regime_gate_enabled": True},
        {"onchain_regime_max_percentile": 0.5},
        {"onchain_regime_source_asset": "eth"},
    ],
)
def test_gate_changes_move_the_policy_version(change: dict[str, object]) -> None:
    assert derive_policy_version(settings()) != derive_policy_version(settings(**change))


def test_endpoint_change_leaves_the_policy_version_alone() -> None:
    moved = settings(coinmetrics_base_url="https://example.invalid")
    assert derive_policy_version(settings()) == derive_policy_version(moved)


def test_the_gate_is_off_by_default() -> None:
    """Turning it on can only withhold; it must still be opt-in."""

    assert settings().onchain_regime_gate_enabled is False
