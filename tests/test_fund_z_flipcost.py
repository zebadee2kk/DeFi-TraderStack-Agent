"""Unit tests for fund_z flip-cost / hold-gate catalog."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.research.fund_z_flipcost import (
    CONTROL_IDS,
    FLIPCOST_CATALOG,
    FLIPCOST_IDS,
    N_PAPER_BE,
    N_RESEARCH_BE,
    _flipcost_per_print,
    _open_cost,
    run_fund_z_flipcost,
)


def _series(values: list[float], start: datetime | None = None):
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return tuple((opened + timedelta(days=i), v) for i, v in enumerate(values))


def test_catalog_ids_frozen() -> None:
    assert FLIPCOST_IDS == (
        "fund_z_flipcost_be3d",
        "fund_z_flipcost_be5d",
        "fund_z_flipcost_be3d_sticky",
        "fund_z_flipcost_be5d_sticky",
        "fund_z_flipcost_sign_hold_ref",
        "fund_z_flipcost_flat",
    )
    assert len(FLIPCOST_CATALOG) <= 6
    assert "fund_z_harvest_sign_hold" not in FLIPCOST_IDS
    assert "carry_hedged_sign" not in FLIPCOST_IDS
    assert CONTROL_IDS == frozenset({"fund_z_flipcost_flat"})
    assert N_RESEARCH_BE == 3
    assert N_PAPER_BE == 5


def test_requires_dual_basis() -> None:
    funding = {
        "BTC/USD": _series([0.0001] * 800),
        "ETH/USD": _series([0.0001] * 800),
    }
    report = run_fund_z_flipcost(
        hl_funding=funding,
        htx_funding=funding,
        okx_basis={},
        vision_basis={},
    )
    assert report.print_kind == "unavailable"
    assert report.dual_print_passers == 0
    assert report.can_promote is False
    assert report.keep_flag_false is True


def test_magnitude_gate_enters_only_when_amortizable() -> None:
    cost = _open_cost(5.0, 5.0)
    # Below threshold for N=3: 3 * rate < cost
    low = cost / 3.0 / 2.0
    # Above threshold
    high = cost / 3.0 * 2.0
    series = _series([low] * 5 + [high] * 10 + [low] * 5)
    per, flips, _bd, mean_hold = _flipcost_per_print(
        series,
        mode="magnitude",
        n_days=3,
        sticky=False,
        fee_bps=5.0,
        slippage_bps=5.0,
    )
    assert flips >= 1
    assert len(per) == len(series)
    assert mean_hold >= 1.0


def test_sticky_holds_minimum_n_days() -> None:
    cost = _open_cost(5.0, 5.0)
    high = cost / 3.0 * 2.0
    low = cost / 3.0 / 10.0
    # Enter on high, then immediately low — sticky should keep for 3 days
    series = _series([high, high, low, low, low, low, low])
    _per, _flips, _bd, mean_hold = _flipcost_per_print(
        series,
        mode="magnitude",
        n_days=3,
        sticky=True,
        fee_bps=5.0,
        slippage_bps=5.0,
    )
    assert mean_hold >= 3.0


def test_concurrent_scores_synthetic() -> None:
    n = 800
    # Mostly high funding so magnitude gates stay in; mild noise.
    cost = _open_cost(5.0, 5.0)
    high = cost / 3.0 * 1.5
    btc = _series([high * (1.0 + 0.01 * ((-1) ** i)) for i in range(n)])
    eth = _series([high * (0.9 + 0.01 * ((-1) ** i)) for i in range(n)])
    funding = {"BTC/USD": btc, "ETH/USD": eth}
    basis = {
        "BTC/USD": _series([0.0001] * n),
        "ETH/USD": _series([0.0001] * n),
    }
    report = run_fund_z_flipcost(
        hl_funding=funding,
        htx_funding=funding,
        okx_basis=basis,
        vision_basis=basis,
        fee_bps=5.0,
        slippage_bps=5.0,
    )
    assert report.print_kind == "dual_print"
    assert report.can_promote is False
    assert report.keep_flag_false is True
    flat = next(c for c in report.primary if c.candidate_id == "fund_z_flipcost_flat")
    assert flat.is_control is True
    assert flat.eligible is False
    ref = next(c for c in report.primary if c.candidate_id == "fund_z_flipcost_sign_hold_ref")
    assert ref.mean_hold_days is not None
