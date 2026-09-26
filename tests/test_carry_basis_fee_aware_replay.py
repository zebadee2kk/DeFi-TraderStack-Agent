"""Tests for carry+basis fee-aware multi-day REPLAY."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traderstack.config import Settings
from traderstack.research.carry_basis_fee_aware_replay import (
    run_carry_basis_replay,
    score_venue,
)
from traderstack.research.fund_z_fee_aware_replay import FEE_LADDERS


def test_promote_defaults_remain_false() -> None:
    s = Settings()
    assert s.paper_promote_fund_z_harvest_sign_hold is False
    assert s.paper_perp_hedge is False


def _panels(n: int = 30, fund: float = 0.0004, basis_step: float = 0.0):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    funding = {}
    basis = {}
    for i in range(n):
        day = start + timedelta(days=i)
        funding[day] = {"BTC": fund, "ETH": fund}
        # declining basis → positive carry basis pnl
        b = 0.01 - i * basis_step
        basis[day] = {"BTC": b, "ETH": b}
    return funding, basis


def test_score_venue_includes_basis() -> None:
    funding, basis = _panels(n=30, fund=0.0004, basis_step=0.0001)
    # funding 3d = 0.24; basis over 2 steps/window approx 0.0001*100*2*2 = 0.04
    venue = score_venue(
        funding,
        basis,
        venue_id="t",
        basis_venue="okx",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 30, tzinfo=UTC),
        notional_per_asset_usd=100.0,
    )
    agg = next(
        a
        for a in venue.aggs
        if a.mode == "tumbling" and a.n_days == 3 and a.ladder_id == "paper_fees_usd_10bps_x2"
    )
    assert agg.n_windows == 10
    assert agg.mean_funding_usd == pytest.approx(0.24)
    assert agg.mean_basis_usd == pytest.approx(0.04)
    assert agg.mean_fee_aware_paper_pnl_usd == pytest.approx(0.08)


def test_run_can_promote_false() -> None:
    funding, basis = _panels(n=40, fund=0.0005, basis_step=0.0)
    report = run_carry_basis_replay(funding, basis, basis)
    assert report.can_promote is False
    assert report.keep_flag_false is True
    assert report.print_kind == "dual_basis"


def test_primary_ladder_cost() -> None:
    primary = next(l for l in FEE_LADDERS if l.primary)
    assert primary.open_cost_usd(100.0, 2) == 0.2
