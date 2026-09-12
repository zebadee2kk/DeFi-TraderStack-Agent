"""Paper fills cannot run live, cannot double-book, and cannot outrun the halt."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from traderstack.config import Settings
from traderstack.execution.hummingbot import ExecutionSafetyError
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.paper_fill import PaperFillSimulator
from traderstack.killswitch import KillSwitch
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService


def test_paper_simulate_fills_cannot_be_rewritten_on_live_settings() -> None:
    settings = Settings(paper_simulate_fills=True, paper_slippage_bps=5.0)
    with pytest.raises(ValidationError):
        settings.paper_simulate_fills = False  # type: ignore[misc]
    with pytest.raises(ValidationError):
        settings.paper_slippage_bps = 0.0  # type: ignore[misc]
    assert settings.paper_simulate_fills is True
    assert settings.paper_slippage_bps == pytest.approx(5.0)


def test_simulator_refuses_live_and_shadow() -> None:
    intent = PaperOrderIntent(decision_id="d1", asset="BTC", side=Side.BUY, notional_usd=100)
    for mode in ("live", "shadow"):
        simulator = PaperFillSimulator(trading_mode=mode)
        with pytest.raises(ExecutionSafetyError, match="outside paper mode"):
            simulator.apply(
                intent,
                mid_usd=20_000.0,
                ledger=ExecutionLedger(),
                portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
            )


@pytest.mark.asyncio
async def test_engaged_kill_switch_cannot_be_bypassed_by_a_stale_paper_order() -> None:
    """Even if run_once still returns a paper_order, the service must withhold."""

    result = RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=19_990,
            ask=20_010,
            last=20_000,
        ),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            paper_order=PaperOrderIntent(
                decision_id="stale-allow",
                asset="BTC",
                side=Side.BUY,
                notional_usd=1_000,
            ),
        ),
        trading_mode="paper",
    )

    class FakeRuntime:
        async def run_once(self, symbol, portfolio, *, submit=False):
            return result

    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=FakeRuntime(),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(),
        kill_switch=KillSwitch(settings_flag=True),
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")

    assert book.nav_usd == pytest.approx(10_000)
    assert not book.positions


def test_paper_fill_cannot_increase_approved_notional() -> None:
    intent = PaperOrderIntent(decision_id="sized", asset="BTC", side=Side.BUY, notional_usd=100.0)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    ledger = ExecutionLedger()
    simulator = PaperFillSimulator(paper_fee_bps=0.0, paper_slippage_bps=0.0)

    outcome = simulator.apply(intent, mid_usd=20_000.0, ledger=ledger, portfolio=book)

    assert outcome.applied
    assert outcome.plan is not None
    assert outcome.plan.notional_usd <= intent.notional_usd + 1e-9
    spent = 10_000 - float(book.cash_usd or 0.0)
    assert spent <= intent.notional_usd + 1e-6
