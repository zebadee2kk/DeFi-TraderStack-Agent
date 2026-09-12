from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traderstack.config import Settings
from traderstack.execution.hummingbot import ExecutionSafetyError
from traderstack.execution.ledger import ExecutionFill, ExecutionLedger, FeeSource
from traderstack.execution.paper_fill import PaperFillSimulator
from traderstack.execution.paper_perp import (
    PAPER_PERP_PATH_READY,
    PaperPerpBook,
    PaperPerpStatus,
    hedge_side,
    paper_perp_client_order_id,
)
from traderstack.killswitch import KillSwitch
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.research.funding_carry import PAPER_CARRY_PATH_READY


def _spot_fill(*, asset: str = "BTC", side: Side = Side.BUY, qty: float = 0.05) -> ExecutionFill:
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


def test_path_ready_is_soak_only_and_does_not_flip_promote_defaults() -> None:
    assert PAPER_PERP_PATH_READY is True
    assert PAPER_CARRY_PATH_READY is True
    defaults = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
    )
    assert defaults.paper_perp_hedge is False
    assert defaults.paper_promote_searched_strategies is False
    assert defaults.paper_promote_ema_9_21 is False
    assert defaults.paper_promote_ema_9_21_adx15 is False
    assert defaults.trading_mode == "paper"


def test_book_refuses_live_and_shadow() -> None:
    for mode in ("live", "shadow"):
        with pytest.raises(ExecutionSafetyError, match="outside paper mode"):
            PaperPerpBook(trading_mode=mode)


def test_hedge_skips_without_perp_mid_and_does_not_invent_spot_price() -> None:
    book = PaperPerpBook()
    spot = InMemoryPortfolioBook(starting_nav_usd=10_000)
    outcome = book.maybe_hedge_spot_fill(
        _spot_fill(),
        perp_mid_usd=None,
        decision_id="decision-1",
    )
    assert outcome.status is PaperPerpStatus.SKIPPED
    assert outcome.applied is False
    assert "perp mid missing" in (outcome.reason or "")
    assert book.positions == {}
    assert spot.nav_usd == pytest.approx(10_000)


def test_hedge_uses_explicit_perp_mid_opposite_side_and_is_ledger_backed() -> None:
    book = PaperPerpBook(paper_fee_bps=10.0, paper_slippage_bps=5.0)
    ledger = ExecutionLedger()
    fill = _spot_fill()
    outcome = book.maybe_hedge_spot_fill(
        fill,
        perp_mid_usd=20_100.0,
        decision_id="decision-1",
        ledger=ledger,
    )
    assert outcome.status is PaperPerpStatus.HEDGED
    assert outcome.position is not None
    assert outcome.position.side is hedge_side(fill.side)
    assert outcome.position.side is Side.SELL
    assert outcome.position.quantity == pytest.approx(fill.quantity)
    client_id = paper_perp_client_order_id("decision-1", "BTC")
    assert outcome.position.client_order_id == client_id
    assert client_id in {order.client_order_id for order in ledger.orders.values()}
    planned_first = next(iter(ledger.orders.values()))
    assert planned_first.client_order_id == client_id


def test_funding_credits_short_perp_on_positive_rate() -> None:
    book = PaperPerpBook(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    book.maybe_hedge_spot_fill(
        _spot_fill(qty=1.0),
        perp_mid_usd=20_000.0,
        decision_id="decision-1",
    )
    start = datetime(2024, 1, 1, tzinfo=UTC)
    settlements = tuple((start + timedelta(hours=8 * index), 0.001) for index in range(3))
    outcome = book.apply_funding(settlements, asset="BTC")
    assert outcome.status is PaperPerpStatus.FUNDING_APPLIED
    # Short 1 BTC at 20_000, +10 bps × 3 prints → +60 USD.
    assert outcome.funding_pnl_usd == pytest.approx(60.0)
    assert book.total_funding_pnl_usd() == pytest.approx(60.0)
    assert book.funding_prints_applied == 3


def test_funding_skips_when_no_settlements_supplied() -> None:
    book = PaperPerpBook()
    book.maybe_hedge_spot_fill(
        _spot_fill(),
        perp_mid_usd=20_000.0,
        decision_id="decision-1",
    )
    outcome = book.apply_funding((), asset="BTC")
    assert outcome.status is PaperPerpStatus.SKIPPED
    assert "refuse to invent" in (outcome.reason or "")
    assert book.total_funding_pnl_usd() == pytest.approx(0.0)


def test_kill_switch_withholds_hedge_and_funding() -> None:
    book = PaperPerpBook(kill_switch=KillSwitch(settings_flag=True))
    hedge = book.maybe_hedge_spot_fill(
        _spot_fill(),
        perp_mid_usd=20_000.0,
        decision_id="decision-1",
    )
    assert hedge.status is PaperPerpStatus.WITHHELD
    assert book.positions == {}
    funding = book.apply_funding(
        ((datetime(2024, 1, 1, tzinfo=UTC), 0.001),),
        asset="BTC",
    )
    assert funding.status is PaperPerpStatus.WITHHELD


def test_hedge_does_not_move_spot_nav() -> None:
    book = PaperPerpBook()
    spot = InMemoryPortfolioBook(starting_nav_usd=10_000)
    simulator = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=0.0)
    ledger = ExecutionLedger()
    filled = simulator.apply(
        PaperOrderIntent(decision_id="decision-1", asset="BTC", side=Side.BUY, notional_usd=1_000),
        mid_usd=20_000.0,
        ledger=ledger,
        portfolio=spot,
    )
    assert filled.applied
    nav_after_spot = spot.nav_usd
    hedge = book.maybe_hedge_spot_fill(
        filled.fill,  # type: ignore[arg-type]
        perp_mid_usd=20_050.0,
        decision_id="decision-1",
    )
    assert hedge.status is PaperPerpStatus.HEDGED
    assert spot.nav_usd == pytest.approx(nav_after_spot)


def test_duplicate_hedge_is_idempotent() -> None:
    book = PaperPerpBook()
    first = book.maybe_hedge_spot_fill(
        _spot_fill(),
        perp_mid_usd=20_000.0,
        decision_id="decision-1",
    )
    second = book.maybe_hedge_spot_fill(
        _spot_fill(),
        perp_mid_usd=20_000.0,
        decision_id="decision-1",
    )
    assert first.status is PaperPerpStatus.HEDGED
    assert second.status is PaperPerpStatus.DUPLICATE
    assert len(book.positions) == 1
