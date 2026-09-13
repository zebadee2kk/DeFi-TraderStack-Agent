"""ContinuousPaperService books paper fills after an ALLOW without --submit."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from prometheus_client import REGISTRY  # --- protective exit sizing (#130) ---

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


# --- protective exit sizing (#130) ---


def _exit_result(*, max_quantity: float | None = 1.0) -> RuntimeResult:
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC),
        bid=99.99,
        ask=100.01,
        last=100.0,
    )
    return RuntimeResult(
        tick=tick,
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            paper_order=PaperOrderIntent(
                decision_id="decision-exit",
                asset="BTC",
                side=Side.SELL,
                notional_usd=100.0,
                max_quantity=max_quantity,
            ),
            exit_reason="exit_stop_loss",
        ),
        trading_mode="paper",
    )


def _long_book(quantity: float) -> InMemoryPortfolioBook:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity, 100.0)
    book.mark("BTC", 100.0)
    return book


def _rejection_counter(reason: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "traderstack_paper_fill_rejections_total",
            {"symbol": "BTC/USD", "side": "sell", "reason": reason},
        )
        or 0.0
    )


@pytest.mark.asyncio
async def test_service_books_a_capped_exit_fill_to_flat_under_slippage() -> None:
    book = _long_book(1.0)
    ledger = ExecutionLedger()
    service = ContinuousPaperService(
        runtime=FakeRuntime(_exit_result()),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=False,
        execution_ledger=ledger,
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0),
        error_backoff_seconds=0,
    )
    captured: list[RuntimeResult] = []

    async def capture(result: RuntimeResult) -> None:
        captured.append(result)

    service.on_result = capture
    await service._run_symbol_safely("BTC/USD")

    assert captured[0].execution_status == PaperFillStatus.FILLED.value
    assert book.positions["BTC"].quantity == 0
    order = ledger.orders_for_decision("decision-exit")[0]
    assert order.state is OrderLifecycleState.FILLED
    assert order.requested_quantity == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_service_flags_an_exit_intent_larger_than_the_book_as_exit_sizing_invalid() -> None:
    book = _long_book(0.5)
    ledger = ExecutionLedger()
    service = ContinuousPaperService(
        runtime=FakeRuntime(_exit_result(max_quantity=1.0)),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=False,
        execution_ledger=ledger,
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0),
        error_backoff_seconds=0,
    )
    captured: list[RuntimeResult] = []

    async def capture(result: RuntimeResult) -> None:
        captured.append(result)

    service.on_result = capture
    before_exit = _rejection_counter("exit_sizing_invalid")
    before_plan = _rejection_counter("plan_rejected")
    cash_before = book.cash_usd
    await service._run_symbol_safely("BTC/USD")

    assert captured[0].execution_status == PaperFillStatus.REJECTED.value
    assert (captured[0].execution_reason or "").startswith("exit_sizing_invalid")
    assert book.positions["BTC"].quantity == pytest.approx(0.5)
    assert book.cash_usd == pytest.approx(cash_before)
    assert ledger.processed_fill_ids == set()
    assert _rejection_counter("exit_sizing_invalid") == before_exit + 1
    assert _rejection_counter("plan_rejected") == before_plan
