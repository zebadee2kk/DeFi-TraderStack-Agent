"""Unit tests for funding-momentum (rate-change) catalog."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.research.fund_mom_delta import (
    CONTROL_IDS,
    MOM_CATALOG,
    MOM_IDS,
    run_fund_mom_delta,
)


def _series(values: list[float], start: datetime | None = None):
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return tuple((opened + timedelta(days=i), v) for i, v in enumerate(values))


def test_catalog_ids_frozen() -> None:
    assert MOM_IDS == (
        "fund_mom_delta_sign",
        "fund_mom_delta_z_1_0",
        "fund_mom_delta_z_1_5",
        "fund_mom_delta_z_2_0",
        "fund_mom_confirm_sign",
        "fund_mom_flat",
    )
    assert len(MOM_CATALOG) <= 6
    assert "fund_z_harvest_sign_hold" not in MOM_IDS
    assert "fund_spread_btc_eth_sign_hold" not in MOM_IDS
    assert "fund_xs_rank_ls_k3" not in MOM_IDS
    assert CONTROL_IDS == frozenset({"fund_mom_flat"})


def test_unavailable_without_funding() -> None:
    report = run_fund_mom_delta({}, {})
    assert report.print_kind == "unavailable"
    assert report.dual_print_passers == 0
    assert report.can_promote is False
    assert report.keep_flag_false is True


def test_concurrent_scores_synthetic() -> None:
    n = 800
    # Mild oscillating funding so deltas are non-zero.
    btc = _series([0.0001 * ((-1) ** i) for i in range(n)])
    eth = _series([0.00005 * ((-1) ** i) for i in range(n)])
    funding = {"BTC/USD": btc, "ETH/USD": eth}
    report = run_fund_mom_delta(
        hl_funding=funding,
        htx_funding=funding,
        fee_bps=5.0,
        slippage_bps=5.0,
    )
    assert report.print_kind == "dual_print"
    assert report.dual_mode == "concurrent_venues"
    assert report.can_promote is False
    assert report.keep_flag_false is True
    flat = next(c for c in report.primary if c.candidate_id == "fund_mom_flat")
    assert flat.is_control is True
    assert flat.eligible is False
