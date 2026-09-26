"""Regression: host fee-aware probe mode wiring for fund_z promote pin."""

from __future__ import annotations

import ast
from pathlib import Path

PROBE = Path("ops/paper_carry_pnl_soak/host_fee_aware_probe.py")


def test_probe_supports_fund_z_mode_and_signal() -> None:
    src = PROBE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Smoke-level: mode choices and promote pin present without executing network.
    assert "fund_z" in src
    assert "PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD" in src or (
        "paper_promote_fund_z_harvest_sign_hold" in src
    )
    assert "FUND_Z_HARVEST_SIGN_HOLD_SIGNAL" in src
    assert "funding_interval_expectation" in src
    assert "HL funding" in src or "~1h" in src
    # Ensure carry mode still available for #176 reuse.
    assert "carry" in src
    assert "CARRY_DIAGNOSTIC_SIGNAL" in src
    assert isinstance(tree, ast.Module)


def test_recipe_preregistered_for_fund_z_multi_hour() -> None:
    recipe = Path("docs/recipes/ops/paper-fund-z-fee-aware-multi-hour-soak-recipe-2026-09-26.md")
    text = recipe.read_text(encoding="utf-8")
    assert "PRE-REGISTRATION" in text
    assert "PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD" in text
    assert "fund_z_harvest_sign_hold" in text
    assert "PAPER ONLY" in text.upper() or "PAPER ONLY" in text
