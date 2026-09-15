"""ContinuousPaperService books paper fills after an ALLOW without --submit."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from traderstack.execution.ledger import ExecutionLedger, OrderLifecycleState
from traderstack.execution.paper_fill import PaperFillSimulator, PaperFillStatus
from traderstack.killswitch import KillSwitch
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService


class FakeRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result
        self.calls: list[tuple[str, bool]] = []

    async def run_once(self, symbol, portfolio, *, submit=False):
        self.calls.append((symbol, submit))
        return self.result


def _tick() -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC),
        bid=19_990,
        ask=20_010,
        last=20_000,
    )


def _allowed_result() -> RuntimeResult:
    return RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            paper_order=PaperOrderIntent(
                decision_id="decision-allow",
                asset="BTC",
                side=Side.BUY,
                notional_usd=1_000,
            ),
        ),
        trading_mode="paper",
    )


@pytest.mark.asyncio
async def test_service_paper_allow_without_submit_moves_nav() -> None:
    result = _allowed_result()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    ledger = ExecutionLedger()
    service = ContinuousPaperService(
        runtime=FakeRuntime(result),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=False,
        execution_ledger=ledger,
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0),
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")

    assert service.runtime.calls == [("BTC/USD", False)]
    assert book.nav_usd != pytest.approx(10_000)
    assert book.cash_usd is not None and book.cash_usd < 10_000
    assert book.positions["BTC"].quantity > 0
    assert any(order.state is OrderLifecycleState.FILLED for order in ledger.orders.values())


@pytest.mark.asyncio
async def test_service_paper_fee_reduces_nav() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=False,
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=0.0),
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")

    # Zero slippage, mark at last == mid: NAV drop is the modelled fee.
    assert book.nav_usd < 10_000
    fees = sum(position.fees_paid_usd for position in book.positions.values())
    assert fees > 0
    assert book.nav_usd == pytest.approx(10_000 - fees)


@pytest.mark.asyncio
async def test_service_restart_does_not_double_fill() -> None:
    ledger = ExecutionLedger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    simulator = PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0)
    first = ContinuousPaperService(
        runtime=FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        execution_ledger=ledger,
        paper_fill_simulator=simulator,
        error_backoff_seconds=0,
    )
    await first._run_symbol_safely("BTC/USD")
    nav_after = book.nav_usd

    restarted = ContinuousPaperService(
        runtime=FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        execution_ledger=ledger,
        paper_fill_simulator=simulator,
        error_backoff_seconds=0,
    )
    await restarted._run_symbol_safely("BTC/USD")

    assert book.nav_usd == pytest.approx(nav_after)
    assert len(ledger.processed_fill_ids) == 1


@pytest.mark.asyncio
async def test_kill_switch_withholds_paper_fill() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(),
        kill_switch=KillSwitch(settings_flag=True),
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")

    assert book.nav_usd == pytest.approx(10_000)
    assert book.positions.get("BTC") is None or book.positions["BTC"].quantity == 0
    assert service.runtime.calls == [("BTC/USD", False)]


@pytest.mark.asyncio
async def test_shadow_result_is_never_filled() -> None:
    result = _allowed_result().model_copy(update={"trading_mode": "shadow"})
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=FakeRuntime(result),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(),
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")

    assert book.nav_usd == pytest.approx(10_000)


@pytest.mark.asyncio
async def test_reconciliation_block_withholds_paper_fill() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(),
        error_backoff_seconds=0,
    )
    service.health.record_reconciliation_failure("venue unreachable")

    captured: list[RuntimeResult] = []

    async def capture(result: RuntimeResult) -> None:
        captured.append(result)

    service.on_result = capture
    await service._run_symbol_safely("BTC/USD")

    assert book.nav_usd == pytest.approx(10_000)
    assert captured[0].execution_status == PaperFillStatus.WITHHELD.value


# --- fee realism (#138) ---
@pytest.mark.asyncio
async def test_service_tier_taker_fee_reduces_nav_by_notional_times_eighty_bps() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=False,
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=80.0, paper_slippage_bps=0.0),
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")

    position = book.positions["BTC"]
    # Zero slippage, mark at last == mid: the NAV drop is quantity * price * 0.008.
    expected_fee = position.quantity * 20_000 * 80.0 / 10_000
    assert position.fees_paid_usd == pytest.approx(expected_fee)
    assert book.nav_usd == pytest.approx(10_000 - expected_fee)
    assert expected_fee == pytest.approx(8.0, rel=1e-3)
