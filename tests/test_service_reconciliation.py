from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.execution.ledger import ExecutionLedger, OrderLifecycleState
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.execution.planner import ExecutionPlanner, client_order_id_for
from traderstack.execution.reconcile import ExecutionReconciliationResult
from traderstack.execution.submitter import IdempotentSubmitter
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.reconciliation import ReconciliationResult
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService

RECEIPT = {
    "order_id": "venue-1",
    "account_name": "paper_account",
    "connector_name": "kraken_paper_trade",
    "trading_pair": "BTC-USD",
    "trade_type": "BUY",
    "amount": 0.05,
    "order_type": "MARKET",
    "price": 20_000,
    "status": "submitted",
}


def tick() -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC),
        bid=19_990,
        ask=20_010,
        last=20_000,
    )


def intent(decision_id: str = "decision-1") -> PaperOrderIntent:
    return PaperOrderIntent(
        decision_id=decision_id,
        asset="BTC",
        side=Side.BUY,
        notional_usd=1_000,
        venue="kraken_paper_trade",
    )


class FakeRuntime:
    """Runs the real submitter behind a stubbed data/decision pipeline."""

    def __init__(
        self, order: PaperOrderIntent, submitter: IdempotentSubmitter | None = None
    ) -> None:
        self.order = order
        self.submitter = submitter
        self.calls: list[bool] = []

    async def run_once(
        self, symbol: str, portfolio: object, *, submit: bool = False
    ) -> RuntimeResult:
        self.calls.append(submit)
        receipt = None
        status = None
        reason = None
        if submit and self.submitter is not None:
            outcome = await self.submitter.submit(
                self.order, execution_price_usd=20_000, reference_price_usd=20_000
            )
            receipt = outcome.receipt
            status = outcome.status.value
            reason = outcome.reason
        return RuntimeResult(
            tick=tick(),
            references=[],
            pipeline=PipelineResult(accepted_market_data=True, paper_order=self.order),
            execution_receipt=receipt,
            execution_status=status,
            execution_reason=reason,
        )


class FakeExecutionReconciler:
    def __init__(self, *results: ExecutionReconciliationResult | Exception) -> None:
        self.results = list(results)
        self.calls = 0

    async def reconcile_state(
        self, ledger: ExecutionLedger, portfolio: InMemoryPortfolioBook
    ) -> ExecutionReconciliationResult:
        self.calls += 1
        result = self.results.pop(0) if self.results else ExecutionReconciliationResult()
        if isinstance(result, Exception):
            raise result
        return result


class FakePortfolioReconciler:
    def __init__(self, *results: ReconciliationResult | Exception) -> None:
        self.results = list(results)
        self.calls = 0

    async def reconcile(self, portfolio: InMemoryPortfolioBook) -> ReconciliationResult:
        self.calls += 1
        result = self.results.pop(0) if self.results else clean_nav()
        if isinstance(result, Exception):
            raise result
        return result


class CountingResolver:
    def __init__(self, *answers: bool | Exception) -> None:
        self.answers = list(answers)
        self.calls = 0

    async def venue_knows_order(
        self,
        ledger: ExecutionLedger,
        *,
        client_order_id: str,
        trading_pair: str,
        trade_type: str,
        quantity: float,
    ) -> bool:
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else False
        if isinstance(answer, Exception):
            raise answer
        return answer


def clean_nav() -> ReconciliationResult:
    return ReconciliationResult(
        matched=True,
        internal_nav_usd=10_000,
        external_nav_usd=10_000,
        nav_difference_usd=0,
        nav_difference_bps=0,
    )


def drifting_nav() -> ReconciliationResult:
    return ReconciliationResult(
        matched=False,
        internal_nav_usd=10_000,
        external_nav_usd=9_900,
        nav_difference_usd=100,
        nav_difference_bps=100,
        reasons=["portfolio NAV drift 100.00 bps exceeds 25.00 bps"],
    )


def make_service(
    runtime: FakeRuntime,
    book: InMemoryPortfolioBook,
    ledger: ExecutionLedger,
    *,
    execution_reconciler: FakeExecutionReconciler | None = None,
    portfolio_reconciler: FakePortfolioReconciler | None = None,
    ledger_store: JsonExecutionLedgerStore | None = None,
    results: list[RuntimeResult] | None = None,
) -> ContinuousPaperService:
    async def on_result(result: RuntimeResult) -> None:
        if results is not None:
            results.append(result)

    return ContinuousPaperService(
        runtime=runtime,  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=True,
        error_backoff_seconds=0,
        execution_ledger=ledger,
        execution_reconciler=execution_reconciler,  # type: ignore[arg-type]
        portfolio_reconciler=portfolio_reconciler,  # type: ignore[arg-type]
        ledger_store=ledger_store,
        on_result=on_result,
    )


def submitter_for(
    ledger: ExecutionLedger,
    client: httpx.AsyncClient,
    *,
    resolver: object | None = None,
    ledger_store: JsonExecutionLedgerStore | None = None,
    max_retries: int = 2,
) -> IdempotentSubmitter:
    async def no_sleep(seconds: float) -> None:
        return None

    return IdempotentSubmitter(
        executor=HummingbotPaperExecutor("http://hummingbot", "u", "p", client=client),
        ledger=ledger,
        planner=ExecutionPlanner(lot_step=0.001, min_notional_usd=10),
        resolver=resolver,  # type: ignore[arg-type]
        ledger_store=ledger_store,
        max_retries=max_retries,
        backoff_seconds=0,
        sleep=no_sleep,
    )


@pytest.mark.asyncio
async def test_service_does_not_resubmit_a_duplicate_decision() -> None:
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        return httpx.Response(201, json=RECEIPT)

    ledger = ExecutionLedger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    results: list[RuntimeResult] = []
    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        runtime = FakeRuntime(intent(), submitter_for(ledger, client))
        service = make_service(runtime, book, ledger, results=results)
        await service._run_symbol_safely("BTC/USD")
        await service._run_symbol_safely("BTC/USD")

    assert posts == 1
    assert [r.execution_status for r in results] == ["submitted", "duplicate"]
    # The submitter's ledger entry is the only one; the service must not add a
    # second row keyed by the venue's order id.
    assert list(ledger.orders) == [client_order_id_for("decision-1")]


@pytest.mark.asyncio
async def test_blocked_flag_stops_submission_and_clears_after_a_good_reconcile() -> None:
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        return httpx.Response(201, json=RECEIPT)

    ledger = ExecutionLedger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    results: list[RuntimeResult] = []
    execution_reconciler = FakeExecutionReconciler(
        ExecutionReconciliationResult(
            conflicts=["order o1 is filled locally but open at the venue"]
        ),
        ExecutionReconciliationResult(),
    )
    portfolio_reconciler = FakePortfolioReconciler(clean_nav(), clean_nav())

    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        runtime = FakeRuntime(intent(), submitter_for(ledger, client))
        service = make_service(
            runtime,
            book,
            ledger,
            execution_reconciler=execution_reconciler,
            portfolio_reconciler=portfolio_reconciler,
            results=results,
        )

        assert not await service.reconcile_now()
        assert service.health.reconciliation_blocked
        assert not service.submission_enabled

        # The cycle still runs: data, decision and audit are unaffected.
        await service._run_symbol_safely("BTC/USD")
        assert runtime.calls == [False]
        assert posts == 0
        assert len(results) == 1
        assert book.marks_usd["BTC"] == pytest.approx(20_000)
        assert service.health.healthy

        assert await service.reconcile_now()
        assert not service.health.reconciliation_blocked
        assert service.submission_enabled

        await service._run_symbol_safely("BTC/USD")

    assert runtime.calls == [False, True]
    assert posts == 1
    assert results[-1].execution_status == "submitted"


@pytest.mark.asyncio
async def test_nav_drift_blocks_submission() -> None:
    ledger = ExecutionLedger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = make_service(
        FakeRuntime(intent()),
        book,
        ledger,
        execution_reconciler=FakeExecutionReconciler(),
        portfolio_reconciler=FakePortfolioReconciler(drifting_nav()),
    )

    assert not await service.reconcile_now()
    assert service.health.reconciliation_blocked
    assert "NAV drift" in (service.health.last_reconciliation_error or "")
    assert not service.submission_enabled


@pytest.mark.asyncio
async def test_unreachable_venue_blocks_submission() -> None:
    ledger = ExecutionLedger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = make_service(
        FakeRuntime(intent()),
        book,
        ledger,
        execution_reconciler=FakeExecutionReconciler(RuntimeError("hummingbot unreachable")),
        portfolio_reconciler=FakePortfolioReconciler(),
    )

    assert not await service.reconcile_now()
    assert service.health.reconciliation_blocked
    assert "hummingbot unreachable" in (service.health.last_reconciliation_error or "")


@pytest.mark.asyncio
async def test_timeout_marks_uncertain_then_reconciles_before_retrying(tmp_path: Path) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.TimeoutException("timed out", request=request)
        return httpx.Response(201, json=RECEIPT)

    ledger = ExecutionLedger()
    store = JsonExecutionLedgerStore(tmp_path / "execution_ledger.json")
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    results: list[RuntimeResult] = []
    # First pass: reconciliation itself is unavailable, so the order must stay
    # uncertain and unretried. Second pass: the venue disowns it, retry is safe.
    resolver = CountingResolver(RuntimeError("hummingbot unreachable"), False)

    async with httpx.AsyncClient(
        base_url="http://hummingbot", transport=httpx.MockTransport(handler)
    ) as client:
        runtime = FakeRuntime(
            intent(), submitter_for(ledger, client, resolver=resolver, ledger_store=store)
        )
        service = make_service(runtime, book, ledger, ledger_store=store, results=results)

        await service._run_symbol_safely("BTC/USD")
        assert attempts == 1
        assert resolver.calls == 1
        assert results[-1].execution_status == "uncertain"
        order = ledger.orders[client_order_id_for("decision-1")]
        assert order.state is OrderLifecycleState.SUBMISSION_UNCERTAIN

        persisted = await store.load()
        assert persisted is not None
        assert persisted.orders[client_order_id_for("decision-1")].state is (
            OrderLifecycleState.SUBMISSION_UNCERTAIN
        )

        await service._run_symbol_safely("BTC/USD")

    assert resolver.calls == 2, "a reconciliation pass gates every retry"
    assert attempts == 2
    assert results[-1].execution_status == "submitted"
    assert ledger.orders[client_order_id_for("decision-1")].state is OrderLifecycleState.SUBMITTED


@pytest.mark.asyncio
async def test_reconciliation_persists_the_ledger_and_portfolio(tmp_path: Path) -> None:
    ledger = ExecutionLedger()
    store = JsonExecutionLedgerStore(tmp_path / "execution_ledger.json")
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    saved: list[float] = []

    async def on_portfolio(portfolio: InMemoryPortfolioBook) -> None:
        saved.append(portfolio.nav_usd)

    service = make_service(
        FakeRuntime(intent()),
        book,
        ledger,
        execution_reconciler=FakeExecutionReconciler(
            ExecutionReconciliationResult(applied_fills=1, venue_orders=1)
        ),
        portfolio_reconciler=FakePortfolioReconciler(clean_nav()),
        ledger_store=store,
    )
    service.on_portfolio = on_portfolio

    assert await service.reconcile_now()
    assert saved == [10_000]
    assert store.path.exists()
    assert service.health.last_reconciliation_at is not None


@pytest.mark.asyncio
async def test_reconciliation_respects_the_configured_interval() -> None:
    ledger = ExecutionLedger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    execution_reconciler = FakeExecutionReconciler()
    service = make_service(
        FakeRuntime(intent()),
        book,
        ledger,
        execution_reconciler=execution_reconciler,
        portfolio_reconciler=FakePortfolioReconciler(),
    )
    service.reconcile_interval_seconds = 3_600

    await service._maybe_reconcile()
    await service._maybe_reconcile()
    assert execution_reconciler.calls == 1

    service.reconcile_interval_seconds = 0
    await service._maybe_reconcile()
    assert execution_reconciler.calls == 2


@pytest.mark.asyncio
async def test_service_without_reconcilers_never_blocks() -> None:
    ledger = ExecutionLedger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    service = make_service(FakeRuntime(intent()), book, ledger)

    await service._maybe_reconcile()
    assert not service.health.reconciliation_blocked
    assert service.submission_enabled
