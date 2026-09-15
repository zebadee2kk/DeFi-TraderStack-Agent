"""Default-deny coverage for `policy_version` (#69 / SEC-2026-09-18).

SEC-2026-09-18 was "two audit records with identical `policy_version` can come
from runs with the pre-trade gate on and off". The first pass fixed that by
adding the missing names to `RISK_LIMIT_FIELDS` — but an include-list only ever
covers the names someone remembered, so the finding can recur the moment a new
gate is added under a name nobody thought to add.

These tests close that by construction: every `Settings` field must be
explicitly classified as a risk-engine limit, a control-plane gate, or
non-policy. An unclassified field fails, whatever it is called.
"""

from __future__ import annotations

import pytest

from traderstack.config import Settings
from traderstack.policy_fields import NON_POLICY_FIELDS
from traderstack.risk import (
    CONTROL_PLANE_FIELDS,
    POLICY_FIELDS,
    RISK_LIMIT_FIELDS,
    RiskEngine,
    derive_policy_version,
)


def settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def test_every_settings_field_is_explicitly_classified() -> None:
    """The default-deny guarantee: no field may be silently unversioned.

    If this fails, a `Settings` field was added without deciding whether it is
    policy. Add it to `RISK_LIMIT_FIELDS` or `CONTROL_PLANE_FIELDS` if it can
    change whether, or how large, an order is built or submitted; otherwise add
    it to `NON_POLICY_FIELDS` with a reason.
    """

    classified = set(RISK_LIMIT_FIELDS) | set(CONTROL_PLANE_FIELDS) | set(NON_POLICY_FIELDS)
    unclassified = sorted(set(Settings.model_fields) - classified)
    assert unclassified == [], (
        "unclassified Settings field(s) cannot affect policy_version: "
        f"{unclassified}. Classify each one (see NON_POLICY_FIELDS in policy_fields.py)."
    )


def test_no_field_is_classified_twice() -> None:
    """A field in two tuples would be ambiguous, and hashed twice."""

    assert set(RISK_LIMIT_FIELDS).isdisjoint(CONTROL_PLANE_FIELDS)
    assert set(POLICY_FIELDS).isdisjoint(NON_POLICY_FIELDS)


def test_no_classified_field_has_been_removed_from_settings() -> None:
    """A stale name in a tuple would make `risk_limits` raise at runtime."""

    classified = set(RISK_LIMIT_FIELDS) | set(CONTROL_PLANE_FIELDS) | set(NON_POLICY_FIELDS)
    assert sorted(classified - set(Settings.model_fields)) == []


# The gates SEC-2026-09-18 named that the first pass left out. Each of these
# changes whether an order is built or submitted without RiskEngine.evaluate
# seeing a different proposal.
@pytest.mark.parametrize(
    "change",
    [
        {"meta_agent_mode": "off"},
        {"intelligence_required": True},
        {"intelligence_block_on_adverse_news": False},
        {"reconcile_interval_seconds": 5.0},
        {"robinhood_chain_allowed_routers": "0xdeadbeef"},
        {"robinhood_chain_allowed_tokens": "0xfeedface"},
        {"trading_mode": "shadow"},
        {"paper_simulate_fills": False},
        {"execution_max_retries": 7},
        {"execution_submit_timeout_seconds": 99.0},
        # Sizes every protective exit since #130, so it is a policy input.
        {"paper_slippage_bps": 50.0},
    ],
)
def test_control_plane_gates_move_the_policy_version(change: dict[str, object]) -> None:
    assert derive_policy_version(settings()) != derive_policy_version(settings(**change))


@pytest.mark.parametrize(
    "change",
    [
        {"log_level": "DEBUG"},
        {"coingecko_calls_per_minute": 3},
        {"provider_timeout_seconds": 30.0},
        {"database_url": "postgresql://elsewhere/db"},
        {"intelligence_cache_seconds": 900},
    ],
)
def test_non_policy_settings_do_not_move_the_policy_version(change: dict[str, object]) -> None:
    assert derive_policy_version(settings()) == derive_policy_version(settings(**change))


def test_meta_agent_veto_mode_is_distinguishable_in_the_audit_trail() -> None:
    """The finding's own example, pinned end to end.

    `meta_agent_mode` decides whether a veto suppresses an order at all, so a
    veto run and an advisory run must never be indistinguishable by version.
    """

    veto = RiskEngine(settings(meta_agent_mode="veto")).policy_version
    advisory = RiskEngine(settings(meta_agent_mode="advisory")).policy_version
    off = RiskEngine(settings(meta_agent_mode="off")).policy_version
    assert len({veto, advisory, off}) == 3


def test_the_audit_limits_mapping_covers_both_halves() -> None:
    """An auditor can diff two records without the `.env` that produced them."""

    from traderstack.risk import risk_limits

    limits = risk_limits(settings())
    assert set(limits) == set(POLICY_FIELDS)
    for name in ("max_position_pct", "pretrade_backtest_enabled", "meta_agent_mode"):
        assert name in limits
