"""Invariants touched by #66 (honest paper NAV) and #67 (ledger-backed halt).

A torn idempotency ledger is the one way the duplicate-order guard can be
lost. Treating it as a fresh start would license a double submission.
Fees that never hit the book would leave daily-loss and drawdown breakers
systematically optimistic.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from traderstack._fs import DurableStateError
from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.cli import load_persisted_state
from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger, ExecutionOrder, OrderLifecycleState
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.health import RuntimeHealth
from traderstack.models import RiskDecision, Side, TradeProposal
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk import RiskEngine
from traderstack.service import ContinuousPaperService


def test_paper_fee_bps_cannot_be_rewritten_on_live_settings() -> None:
    settings = Settings(paper_fee_bps=10.0)
    with pytest.raises(ValidationError):
        settings.paper_fee_bps = 0.0  # type: ignore[misc]
    assert settings.paper_fee_bps == pytest.approx(10.0)


def test_fee_adjusted_nav_cannot_be_ignored_by_the_risk_engine() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000, fee_usd=250)
    snapshot = book.snapshot()
    # Gross NAV would still be 10_000; fee-adjusted is 9_750 → daily loss.
    assert snapshot.nav_usd == pytest.approx(9_750)

    result = RiskEngine(
        Settings(kill_switch=False, max_daily_loss_pct=0.02, mvp_assets="BTC,ETH,SOL")
    ).evaluate(
        TradeProposal(
            strategy_id="s",
            asset="BTC",
            side=Side.BUY,
            confidence=0.5,
            requested_notional_usd=100,
            thesis="ignore the fees",
            source_freshness_seconds=1,
        ),
        snapshot,
    )
    assert result.decision is RiskDecision.REJECT
    assert "daily_loss_limit_reached" in result.reasons


@pytest.mark.asyncio
async def test_corrupt_ledger_cannot_be_treated_as_a_fresh_start(tmp_path: Path) -> None:
    path = tmp_path / "execution_ledger.json"
    # A previously submitted order that a fresh ledger would forget.
    store = JsonExecutionLedgerStore(path)
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="ts-live",
            decision_id="already-sent",
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.05,
            state=OrderLifecycleState.SUBMITTED,
        )
    )
    await store.save(ledger)
    path.write_text("", encoding="utf-8")

    with pytest.raises(DurableStateError):
        await store.load()

    _book, _empty, error = await load_persisted_state(
        JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
        store,
        starting_nav_usd=10_000,
    )
    assert error is not None

    health = RuntimeHealth()
    health.record_durable_state_failure(error)
    service = ContinuousPaperService(
        runtime=object(),  # type: ignore[arg-type]
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        symbols=("BTC/USD",),
        submit=True,
        health=health,
    )
    assert not service.submission_enabled
    assert not service.health.healthy
