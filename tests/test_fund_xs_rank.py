"""Unit tests for HL asilletto cross-sectional funding-rank catalog."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from traderstack.research.fund_xs_rank import (
    CONTROL_IDS,
    CORE_UNIVERSE,
    RANK_CATALOG,
    RANK_IDS,
    run_fund_xs_rank,
)


def test_catalog_ids_frozen() -> None:
    assert RANK_IDS == (
        "fund_xs_rank_ls_k3",
        "fund_xs_rank_ls_k5",
        "fund_xs_rank_ls_k8",
        "fund_xs_rank_short_top_k5",
        "fund_xs_rank_long_bottom_k5",
        "fund_xs_rank_ew_flat",
    )
    assert len(RANK_CATALOG) == 6
    assert "fund_z_harvest_sign_hold" not in RANK_IDS
    assert "fund_div_hl_htx_fade_1_0" not in RANK_IDS
    assert CONTROL_IDS == frozenset({"fund_xs_rank_ew_flat"})
    assert "BTC" in CORE_UNIVERSE and "ETH" in CORE_UNIVERSE
    assert len(CORE_UNIVERSE) == 100


def test_unavailable_without_panel() -> None:
    report = run_fund_xs_rank({})
    assert report.print_kind == "unavailable"
    assert report.dual_print_passers == 0
    assert report.can_promote is False
    assert report.keep_flag_false is True


def test_dual_era_scores_synthetic_panel() -> None:
    # Build a long synthetic panel spanning both eras with >=8 coins.
    coins = list(CORE_UNIVERSE[:12])  # includes BTC, ETH (indices 18,28 in full list — force them)
    if "BTC" not in coins:
        coins[0] = "BTC"
    if "ETH" not in coins:
        coins[1] = "ETH"
    panel: dict[datetime, dict[str, float]] = {}
    start = datetime(2024, 1, 1, tzinfo=UTC)
    # 880 calendar days covers both eras through 2026-06-01
    for i in range(880):
        day = start + timedelta(days=i)
        if day > datetime(2026, 6, 1, tzinfo=UTC):
            break
        # Cross-sectional dispersion: coin j funding = (j - mean) * scale + noise by day
        vals = {}
        for j, coin in enumerate(coins):
            # Persistent rank signal + small day noise
            vals[coin] = (j - len(coins) / 2) * 1e-4 + ((i + j) % 7) * 1e-6
        panel[day] = vals
    report = run_fund_xs_rank(panel, fee_bps=5.0, slippage_bps=5.0)
    assert report.print_kind == "dual_print"
    assert report.dual_print_passers >= 0
    assert report.can_promote is False
    assert any(c.candidate_id == "fund_xs_rank_ew_flat" for c in report.candidates)
    flat = next(c for c in report.candidates if c.candidate_id == "fund_xs_rank_ew_flat")
    assert flat.is_control is True
    assert flat.eligible is False
