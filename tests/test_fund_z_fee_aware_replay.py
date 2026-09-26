"""Tests for fund_z fee-aware multi-day historical REPLAY."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traderstack.config import Settings
from traderstack.research.fund_z_fee_aware_replay import (
    FEE_LADDERS,
    FeeLadder,
    run_fee_aware_replay,
    score_era,
)


def test_promote_defaults_remain_false() -> None:
    settings = Settings()
    assert settings.paper_promote_fund_z_harvest_sign_hold is False
    assert settings.paper_perp_hedge is False
    assert settings.paper_carry_hedge_diagnostic is False


def test_paper_fees_usd_ladder_matches_181() -> None:
    primary = next(l for l in FEE_LADDERS if l.primary)
    assert primary.ladder_id == "paper_fees_usd_10bps_x2"
    assert primary.open_cost_usd(100.0, 2) == 0.2


def test_fee_plus_slip_ladder() -> None:
    ladder = FeeLadder(
        ladder_id="x",
        label="x",
        fee_bps=10.0,
        slippage_bps=5.0,
        charge_slippage_in_fees_usd=True,
    )
    assert ladder.open_cost_usd(100.0, 2) == 0.3


def _synthetic_panel(*, n_days: int = 40, daily_abs: float = 0.0004) -> dict:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    panel = {}
    for i in range(n_days):
        day = start + timedelta(days=i)
        panel[day] = {"BTC": daily_abs, "ETH": daily_abs}
    return panel


def test_score_era_fee_positive_when_funding_covers() -> None:
    # 0.0004 * 100 * 2 assets = $0.08/day → 3d funding = $0.24 > $0.20 fees
    panel = _synthetic_panel(n_days=30, daily_abs=0.0004)
    era = score_era(
        panel,
        era_id="era_a",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 30, tzinfo=UTC),
        notional_per_asset_usd=100.0,
    )
    tumbling_primary = [
        a
        for a in era.aggs
        if a.mode == "tumbling" and a.n_days == 3 and a.ladder_id == "paper_fees_usd_10bps_x2"
    ]
    assert len(tumbling_primary) == 1
    agg = tumbling_primary[0]
    assert agg.n_windows == 10  # 30/3
    assert agg.mean_funding_usd == pytest.approx(0.24)
    assert agg.mean_fee_aware_paper_pnl_usd == pytest.approx(0.04)
    assert agg.fraction_fee_positive == 1.0
    assert agg.fee_survival_pass is True


def test_run_replay_can_promote_always_false() -> None:
    # Build panel covering both eras lightly
    panel = {}
    for year, month_start, n in ((2024, 1, 60), (2025, 5, 60)):
        start = datetime(year, month_start, 1, tzinfo=UTC)
        for i in range(n):
            day = start + timedelta(days=i)
            panel[day] = {"BTC": 0.0005, "ETH": 0.0005}
    report = run_fee_aware_replay(panel, notional_per_asset_usd=100.0)
    assert report.can_promote is False
    assert report.keep_flag_false is True
    assert report.mtm_omitted is True
    assert report.print_kind in {"dual_era", "single_era"}


def test_unavailable_when_empty_panel() -> None:
    report = run_fee_aware_replay({})
    assert report.print_kind == "unavailable"
    assert report.can_promote is False
