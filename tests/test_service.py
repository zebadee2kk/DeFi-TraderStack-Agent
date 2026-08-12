from datetime import UTC, datetime

import pytest

from traderstack.execution.hummingbot import HummingbotOrderReceipt
from traderstack.execution.ledger import ExecutionLedger, OrderLifecycleState
from traderstack.execution.reconcile import ReconcileOutcome
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


@pytest.mark.asyncio
async def test_service_registers_submission_without_treating_it_as_fill() -> None:
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC),
        bid=19_990,
        ask=20_010,
        last=20_000,
    )
    order = PaperOrderIntent(
        decision_id="decision-1",
        asset="BTC",
        side=Side.BUY,
        notional_usd=1_000,
    )
    pipeline = PipelineResult(accepted_market_data=True, paper_order=order)
    receipt = HummingbotOrderReceipt(
        order_id="paper-1",
        account_name="paper_account",
        connector_name="kraken_paper_trade",
        trading_pair="BTC-USD",
        trade_type="BUY",
        amount=0.05,
        order_type="MARKET",
        price=20_000,
        status="created",
    )
    result = RuntimeResult(
        tick=tick,
        references=[],
        pipeline=pipeline,
        execution_receipt=receipt,
    )
    runtime = FakeRuntime(result)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    ledger = ExecutionLedger()
    service = ContinuousPaperService(
        runtime=runtime,  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=True,
        execution_ledger=ledger,
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")

    snapshot = book.snapshot()
    assert runtime.calls == [("BTC/USD", True)]
    assert snapshot.cash_usd == pytest.approx(10_000)
    assert snapshot.asset_exposure_usd == {}
    assert ledger.orders["paper-1"].state is OrderLifecycleState.SUBMITTED
    assert ledger.orders["paper-1"].filled_quantity == 0


@pytest.mark.asyncio
async def test_service_marks_accepted_data_without_execution() -> None:
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="ETH/USD",
        observed_at=datetime.now(UTC),
        bid=999,
        ask=1_001,
        last=1_000,
    )
    result = RuntimeResult(
        tick=tick,
        references=[],
        pipeline=PipelineResult(accepted_market_data=True),
    )
    runtime = FakeRuntime(result)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=runtime,  # type: ignore[arg-type]
        portfolio=book,
        symbols=("ETH/USD",),
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("ETH/USD")

    assert book.marks_usd["ETH"] == pytest.approx(1_000)


@pytest.mark.asyncio
async def test_service_does_not_mark_rejected_data() -> None:
    tick = MarketTick(
        source=MarketSource.KRAKEN,
        symbol="ETH/USD",
        observed_at=datetime.now(UTC),
        bid=999,
        ask=1_001,
        last=1_000,
    )
    result = RuntimeResult(
        tick=tick,
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=False,
            rejection_reasons=["reference_price_divergence"],
        ),
    )
    runtime = FakeRuntime(result)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = ContinuousPaperService(
        runtime=runtime,  # type: ignore[arg-type]
        portfolio=book,
        symbols=("ETH/USD",),
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("ETH/USD")

    assert "ETH" not in book.marks_usd


class StubReconciler:
    def __init__(self, applied: int = 0, fail: bool = False) -> None:
        self.applied = applied
        self.fail = fail
        self.calls = 0

    async def reconcile(self, ledger, portfolio) -> ReconcileOutcome:
        self.calls += 1
        if self.fail:
            raise RuntimeError("hummingbot unavailable")
        return ReconcileOutcome(applied_fills=self.applied)


def _idle_service(reconciler, **overrides) -> ContinuousPaperService:
    values = {
        "runtime": FakeRuntime(
            RuntimeResult(
                tick=MarketTick(
                    source=MarketSource.KRAKEN,
                    symbol="BTC/USD",
                    observed_at=datetime.now(UTC),
                    bid=999,
                    ask=1_001,
                    last=1_000,
                ),
                references=[],
                pipeline=PipelineResult(accepted_market_data=False),
            )
        ),
        "portfolio": InMemoryPortfolioBook(starting_nav_usd=10_000),
        "symbols": ("BTC/USD",),
        "execution_ledger": ExecutionLedger(),
        "reconciler": reconciler,
        "error_backoff_seconds": 0,
    }
    values.update(overrides)
    return ContinuousPaperService(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_reconcile_checkpoints_portfolio_after_applied_fills() -> None:
    checkpoints: list[float] = []

    async def capture(book: InMemoryPortfolioBook) -> None:
        checkpoints.append(book.nav_usd)

    reconciler = StubReconciler(applied=1)
    service = _idle_service(reconciler, on_portfolio=capture)

    await service._reconcile_if_due()

    assert reconciler.calls == 1
    assert checkpoints == [pytest.approx(10_000)]


@pytest.mark.asyncio
async def test_reconcile_respects_interval_throttle() -> None:
    reconciler = StubReconciler()
    service = _idle_service(reconciler, reconcile_interval_seconds=3_600)

    await service._reconcile_if_due()
    await service._reconcile_if_due()

    assert reconciler.calls == 1


@pytest.mark.asyncio
async def test_sustained_reconcile_failures_halt_service() -> None:
    reconciler = StubReconciler(fail=True)
    service = _idle_service(
        reconciler,
        reconcile_interval_seconds=0,
        max_consecutive_reconcile_failures=3,
    )

    for _ in range(3):
        await service._reconcile_if_due()

    assert reconciler.calls == 3
    assert service._stop_event.is_set()


@pytest.mark.asyncio
async def test_reconcile_skipped_without_ledger() -> None:
    reconciler = StubReconciler()
    service = _idle_service(reconciler, execution_ledger=None)

    await service._reconcile_if_due()

    assert reconciler.calls == 0
