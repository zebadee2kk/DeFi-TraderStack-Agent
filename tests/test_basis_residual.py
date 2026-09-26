"""Unit tests for basis residual catalog."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.research.basis_residual import (
    BASIS_RESID_CATALOG,
    BASIS_RESID_IDS,
    CORE_IDS,
    dual_basis_gate,
    run_basis_residual,
    score_basis_residual,
)


def _series(values: list[float], start: datetime | None = None):
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return tuple((opened + timedelta(days=i), v) for i, v in enumerate(values))


def test_catalog_ids_frozen() -> None:
    assert BASIS_RESID_IDS == (
        "basis_resid_mr_fade_1_0",
        "basis_resid_mr_fade_1_5",
        "basis_resid_mr_fade_2_0",
        "basis_resid_mom_follow_1_0",
        "basis_resid_mom_follow_1_5",
        "basis_resid_mom_follow_2_0",
    )
    assert len(BASIS_RESID_CATALOG) == 6
    assert len(CORE_IDS) == 7


def test_score_basis_residual_short_tape() -> None:
    metrics = score_basis_residual(
        _series([0.001, 0.002]),
        fade=True,
        entry_z=1.5,
        fee_bps=5.0,
        slippage_bps=5.0,
    )
    assert metrics["mean_wf_total_return"] is None


def test_dual_basis_gate_and_unavailable() -> None:
    short = {"BTC/USD": _series([0.001] * 10), "ETH/USD": _series([0.001] * 10)}
    ok, notes = dual_basis_gate(short, short)
    assert ok is False
    assert any(n["status"] == "skipped" for n in notes)
    report = run_basis_residual(okx_basis=short, vision_basis=short)
    assert report.print_kind == "unavailable"
    assert report.dual_print_passers == 0
    assert report.can_promote is False
    assert report.keep_flag_false is True
