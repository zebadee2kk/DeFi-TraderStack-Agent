"""Tests for selective high-|funding| fee-aware historical REPLAY."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traderstack.config import Settings
from traderstack.research.fund_z_hiabs_fee_aware_replay import (
    FEE_LADDERS,
    run_hiabs_fee_aware_replay,
    score_era,
    threshold_usd,
)


def test_promote_defaults_false() -> None:
    assert Settings().paper_promote_fund_z_harvest_sign_hold is False


def test_primary_threshold_math() -> None:
    primary = next(ladder for ladder in FEE_LADDERS if ladder.primary)
    assert primary.open_cost_usd(100.0, 2) == pytest.approx(0.2)
    assert threshold_usd(primary, 100.0) == pytest.approx(0.1)


def _panel(values: list[float], start: datetime) -> dict[datetime, dict[str, float]]:
    # Values are combined funding USD at $100 per asset, split evenly by asset.
    return {
        start + timedelta(days=i): {"BTC": value / 200.0, "ETH": value / 200.0}
        for i, value in enumerate(values)
    }


def test_sparse_high_trailing_days_trigger_events_and_n2_covers_fees() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    values = [0.01] * 10 + [0.12, 0.11, 0.11, 0.11, 0.11]
    panel = _panel(values, start)
    era = score_era(panel, era_id="x", start=start, end=start + timedelta(days=14))
    primary = "paper_fees_usd_10bps_x2"
    n2 = next(a for a in era.aggs if a.mode == "event" and a.n_days == 2 and a.ladder_id == primary)
    assert n2.n_windows == 3
    assert n2.fraction_fee_positive == 1.0
    assert n2.fee_survival_pass is True


def test_no_lookahead_signal_day_not_in_hold_income() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    era = score_era(
        _panel([0.50, 0.01, 0.01], start), era_id="x", start=start, end=start + timedelta(days=2)
    )
    primary_n1 = next(
        a
        for a in era.aggs
        if a.mode == "event" and a.n_days == 1 and a.ladder_id == "paper_fees_usd_10bps_x2"
    )
    assert primary_n1.n_windows == 1
    assert primary_n1.mean_funding_usd == pytest.approx(0.01)
    assert primary_n1.mean_fee_aware_paper_pnl_usd == pytest.approx(-0.19)


def test_can_promote_always_false_and_reference_cannot_pass_into_passers() -> None:
    panel = {}
    for start in (datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 5, 1, tzinfo=UTC)):
        panel.update(_panel([0.12, 0.11, 0.11, 0.12, 0.11, 0.11], start))
    report = run_hiabs_fee_aware_replay(panel)
    assert report.can_promote is False
    assert report.keep_flag_false is True
    assert report.mtm_omitted is True
    assert report.le2d_path_exists is True
    assert all(
        "paper_fees_usd_10bps_x2" in passer for passer in report.dual_era_fee_survival_passers
    )


def test_empty_panel_unavailable_and_never_promotes() -> None:
    report = run_hiabs_fee_aware_replay({})
    assert report.print_kind == "unavailable"
    assert report.can_promote is False
    assert report.le2d_path_exists is False
