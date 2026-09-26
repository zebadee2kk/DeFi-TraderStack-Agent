"""Tests for fee-aware paper PnL harvest helpers (skip-not-invent)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionFill, FeeSource
from traderstack.execution.paper_perp import FeeAwarePaperPnL, PaperPerpBook
from traderstack.models import Side


def _fill(*, asset: str = "BTC", side: Side = Side.BUY, qty: float = 0.05) -> ExecutionFill:
    return ExecutionFill(
        fill_id="paper-fill:decision-1",
        order_id="decision-1",
        asset=asset,
        side=side,
        quantity=qty,
        price_usd=20_000.0,
        fee_usd=1.0,
        fee_source=FeeSource.MODELLED,
    )


def test_promote_defaults_remain_false() -> None:
    settings = Settings()
    assert settings.paper_perp_hedge is False
    assert settings.paper_carry_hedge_diagnostic is False
    assert settings.paper_promote_searched_strategies is False
    assert settings.paper_promote_ema_9_21 is False
    assert settings.paper_promote_ema_9_21_adx15 is False


def test_total_fees_accumulate_on_hedge() -> None:
    book = PaperPerpBook(paper_fee_bps=10.0, paper_slippage_bps=0.0)
    outcome = book.maybe_hedge_spot_fill(
        _fill(qty=1.0),
        perp_mid_usd=20_000.0,
        decision_id="decision-1",
    )
    assert outcome.status.value == "paper_perp_hedged"
    assert book.total_fees_usd == pytest.approx(20.0)
    assert outcome.fee_usd == pytest.approx(20.0)


def test_unrealized_mtm_short_gains_when_mid_falls() -> None:
    book = PaperPerpBook(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    book.maybe_hedge_spot_fill(
        _fill(qty=1.0, side=Side.BUY),
        perp_mid_usd=20_000.0,
        decision_id="decision-1",
    )
    mtm, marked, skipped = book.unrealized_mtm_usd({"BTC": 19_000.0})
    assert skipped == ()
    assert marked == ("BTC",)
    assert mtm == pytest.approx(1_000.0)


def test_harvest_unavailable_when_mark_missing() -> None:
    book = PaperPerpBook(paper_fee_bps=10.0, paper_slippage_bps=0.0)
    book.maybe_hedge_spot_fill(
        _fill(qty=1.0),
        perp_mid_usd=20_000.0,
        decision_id="decision-1",
    )
    snap = book.harvest_fee_aware_paper_pnl({})
    assert isinstance(snap, FeeAwarePaperPnL)
    assert snap.marks_incomplete is True
    assert snap.fee_aware_paper_pnl_usd is None
    assert snap.skipped_assets == ("BTC",)
    assert snap.fees_usd == pytest.approx(20.0)


def test_harvest_fee_aware_paper_pnl_complete() -> None:
    book = PaperPerpBook(paper_fee_bps=10.0, paper_slippage_bps=0.0)
    book.maybe_hedge_spot_fill(
        _fill(qty=1.0, side=Side.BUY),
        perp_mid_usd=20_000.0,
        decision_id="decision-1",
    )
    start = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
    book.apply_funding(((start, 0.001),), asset="BTC", mark_usd=20_000.0)
    snap = book.harvest_fee_aware_paper_pnl({"BTC": 20_000.0})
    assert snap.marks_incomplete is False
    assert snap.funding_pnl_usd == pytest.approx(20.0)
    assert snap.unrealized_mtm_usd == pytest.approx(0.0)
    assert snap.fees_usd == pytest.approx(20.0)
    assert snap.fee_aware_paper_pnl_usd == pytest.approx(0.0)
