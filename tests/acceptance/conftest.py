"""Shared assembly for the Epic 10 acceptance drills.

Each drill drives a real ``ContinuousPaperService`` -- real pipeline, real risk
engine, real pre-trade gate, real submitter/ledger/reconciler, real audit trails
-- for a bounded number of cycles. The only fakes are the fault-injecting
wrappers in ``traderstack.acceptance.faults`` and the seeded synthetic market in
``traderstack.acceptance.market``; nothing here touches the network, a database
or the clock.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from traderstack.acceptance.faults import (
    FaultBoard,
    FaultyCandleProvider,
    FaultyEventSink,
    FaultyExecutionReconciler,
    FaultyIntelligence,
    FaultyMetaAgentClient,
    FaultyPortfolioBook,
    FaultyPortfolioReconciler,
    FaultyReferenceProvider,
    FaultyRiskEngine,
    FaultyVenueApi,
    FaultyVenueFeed,
    RaiseFault,
    SentinelFileFault,
)
from traderstack.acceptance.market import SyntheticMarket
from traderstack.agents.review import MetaAgentMode, MetaAgentReviewer
from traderstack.audit import JsonlAuditSink
from traderstack.backtest import BaselineBacktester
from traderstack.candles import Candle
from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.config import Settings
from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.execution.planner import ExecutionPlanner
from traderstack.execution.submitter import IdempotentSubmitter
from traderstack.killswitch import KillSwitch
from traderstack.market.models import MarketSource, MarketTick
from traderstack.market.registry import (
    ProviderRegistry,
    RegisteredCandleHistoryProvider,
    RegisteredReferencePriceProvider,
)
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.pretrade import PreTradeBacktestGate
from traderstack.risk_audit import JsonlRiskAuditTrail
from traderstack.runtime import PaperRuntime, RuntimeResult
from traderstack.service import ContinuousPaperService

SYMBOL = "BTC/USD"


def acceptance_settings(tmp_path: Path, **overrides: object) -> Settings:
    """Deterministic settings for a drill: halt clear, limits real, paths local."""

    values: dict[str, object] = {
        "kill_switch": False,
        "kill_switch_file": str(tmp_path / "state" / "KILL"),
        "kill_switch_redis_enabled": False,
        "trading_mode": "paper",
        "mvp_assets": "BTC,ETH,SOL",
        "paper_starting_nav_usd": 10_000.0,
        "hummingbot_api_username": "operator",
        "hummingbot_api_password": "secret",
        "risk_audit_path": str(tmp_path / "audit" / "risk_decisions.jsonl"),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def permissive_pretrade_gate() -> PreTradeBacktestGate:
    """The real gate, with thresholds wide enough that a synthetic uptrend passes.

    The point of the drills is the *failure* paths around the gate (missing and
    stale history), not whether a random walk clears a live performance bar, so
    the performance thresholds are relaxed and the freshness/sufficiency ones
    are left at their real semantics.
    """

    return PreTradeBacktestGate(
        backtester=BaselineBacktester(starting_equity=10_000.0),
        min_candles=120,
        max_candle_age_seconds=7_200.0,
        min_excess_return=-10.0,
        max_drawdown=1.0,
        min_sharpe=-1_000.0,
        min_trades=0,
        require_walkforward=False,
        min_walkforward_excess_return=-10.0,
    )


@dataclass
class AcceptanceHarness:
    """One assembled service plus every fake and fault it was built from."""

    settings: Settings
    market: SyntheticMarket
    board: FaultBoard
    service: ContinuousPaperService
    portfolio: FaultyPortfolioBook
    venue_feed: FaultyVenueFeed
    references: tuple[FaultyReferenceProvider, ...]
    reference_registries: tuple[ProviderRegistry, ...]
    candles: FaultyCandleProvider
    candle_registry: ProviderRegistry
    intelligence: FaultyIntelligence
    meta_client: FaultyMetaAgentClient
    venue_api: FaultyVenueApi
    ledger: ExecutionLedger
    ledger_store: JsonExecutionLedgerStore
    risk_audit: JsonlRiskAuditTrail
    risk_failure: RaiseFault
    kill_sentinel: SentinelFileFault
    audit_sink: FaultyEventSink
    checkpoint_store: JsonPortfolioCheckpointStore
    execution_reconciler: FaultyExecutionReconciler | None = None
    portfolio_reconciler: FaultyPortfolioReconciler | None = None
    results: list[RuntimeResult] = field(default_factory=list)
    _client: httpx.AsyncClient | None = None

    async def cycle(self, symbol: str = SYMBOL) -> RuntimeResult | None:
        """Run exactly one symbol cycle and return the result it recorded."""

        before = len(self.results)
        await self.service._run_symbol_safely(symbol)
        return self.results[-1] if len(self.results) > before else None

    async def cycles(self, count: int, symbol: str = SYMBOL) -> None:
        for _ in range(count):
            await self.cycle(symbol)

    @property
    def last(self) -> RuntimeResult:
        return self.results[-1]

    def reasons(self) -> list[str]:
        return list(self.last.pipeline.rejection_reasons)

    def risk_reasons(self) -> list[str]:
        result = self.last.pipeline.risk_result
        return list(result.reasons) if result is not None else []

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


async def build_harness(
    tmp_path: Path,
    *,
    submit: bool = True,
    symbols: tuple[str, ...] = (SYMBOL,),
    seed: int = 7,
    pretrade: bool = True,
    intelligence: bool = True,
    meta_mode: MetaAgentMode = MetaAgentMode.OFF,
    reconcilers: bool = False,
    settings_overrides: dict[str, object] | None = None,
    provider_failure_threshold: int = 3,
    provider_timeout_seconds: float = 0.05,
    reference_cache_seconds: float = 0.0,
    starting_nav_usd: float = 10_000.0,
) -> AcceptanceHarness:
    """Assemble a real service around the fault-injecting fakes."""

    settings = acceptance_settings(
        tmp_path,
        provider_failure_threshold=provider_failure_threshold,
        provider_timeout_seconds=provider_timeout_seconds,
        provider_breaker_cooldown_seconds=3_600.0,
        paper_starting_nav_usd=starting_nav_usd,
        **(settings_overrides or {}),
    )
    board = FaultBoard()
    market = SyntheticMarket(symbols=symbols, seed=seed)

    def tick_of(symbol: str) -> MarketTick:
        return market.tick(symbol)

    def candles_of(symbol: str, resolution: str, count: int) -> tuple[Candle, ...]:
        return market.candles(symbol, count=count)

    venue_feed = FaultyVenueFeed(tick_of=tick_of, board=board)
    reference_specs = (
        ("coingecko", MarketSource.COINGECKO),
        ("coinmarketcap", MarketSource.COINMARKETCAP),
    )
    references = tuple(
        FaultyReferenceProvider(name=name, price_of=market.price_of, source=source, board=board)
        for name, source in reference_specs
    )
    reference_registries = tuple(
        ProviderRegistry(
            name=provider.name,
            timeout_seconds=settings.provider_timeout_seconds,
            failure_threshold=settings.provider_failure_threshold,
            cooldown_seconds=settings.provider_breaker_cooldown_seconds,
            cache_ttl_seconds=reference_cache_seconds,
        )
        for provider in references
    )
    wrapped_references = tuple(
        RegisteredReferencePriceProvider(provider, registry)
        for provider, registry in zip(references, reference_registries, strict=True)
    )

    candles = FaultyCandleProvider(candles_of=candles_of, board=board)
    candle_registry = ProviderRegistry(
        name="candles",
        timeout_seconds=settings.provider_timeout_seconds,
        failure_threshold=settings.provider_failure_threshold,
        cooldown_seconds=settings.provider_breaker_cooldown_seconds,
    )
    wrapped_candles = RegisteredCandleHistoryProvider(candles, candle_registry)

    faulty_intelligence = FaultyIntelligence(board=board)
    meta_client = FaultyMetaAgentClient(board=board)

    kill_sentinel = SentinelFileFault("kill_switch_file", Path(settings.kill_switch_file))
    board.register(kill_sentinel)
    kill_switch = KillSwitch.from_settings(settings)

    risk_failure = RaiseFault("risk_engine_error")
    board.register(risk_failure)
    risk_engine = FaultyRiskEngine(
        settings,
        kill_switch=kill_switch,
        circuit_breaker=StrategyCircuitBreaker.from_settings(settings),
        failure=risk_failure,
    )

    gate = permissive_pretrade_gate() if pretrade else None
    pipeline = VerticalSlicePipeline(
        risk_engine=risk_engine,
        max_tick_age_seconds=settings.max_market_data_age_seconds,
        max_reference_divergence_bps=settings.max_reference_divergence_bps,
        pretrade_gate=gate,
        feature_builder=CandleMarketFeatureBuilder() if gate is not None else None,
        block_on_adverse_news=settings.intelligence_block_on_adverse_news,
        require_external_intelligence=settings.intelligence_required,
    )

    venue_api = FaultyVenueApi(nav_usd=starting_nav_usd, board=board)
    client = venue_api.client()
    executor = HummingbotPaperExecutor(
        base_url=venue_api.base_url,
        username="operator",
        password="secret",
        client=client,
    )

    ledger = ExecutionLedger()
    ledger_store = JsonExecutionLedgerStore(tmp_path / "state" / "execution_ledger.json")

    async def no_sleep(seconds: float) -> None:
        return None

    submitter = IdempotentSubmitter(
        executor=executor,
        ledger=ledger,
        planner=ExecutionPlanner(
            lot_step=settings.execution_lot_step,
            min_notional_usd=settings.execution_min_notional_usd,
            max_slippage_bps=settings.execution_max_slippage_bps,
        ),
        resolver=None,
        ledger_store=ledger_store,
        timeout_seconds=settings.execution_submit_timeout_seconds,
        max_retries=settings.execution_max_retries,
        backoff_seconds=0.0,
        sleep=no_sleep,
    )

    reviewer: MetaAgentReviewer | None = None
    if meta_mode is not MetaAgentMode.OFF:
        reviewer = MetaAgentReviewer(
            client=meta_client,
            mode=meta_mode,
            model="acceptance-drill",
            timeout_seconds=0.05,
        )

    runtime = PaperRuntime(
        venue=venue_feed,
        references=wrapped_references,
        pipeline=pipeline,
        executor=executor,
        candles=wrapped_candles if gate is not None else None,
        candle_interval="1h",
        candle_count=320,
        intelligence=faulty_intelligence if intelligence else None,
        meta_reviewer=reviewer,
        submitter=submitter if submit else None,
    )

    portfolio = FaultyPortfolioBook(starting_nav_usd=starting_nav_usd)
    results: list[RuntimeResult] = []

    async def collect(result: RuntimeResult) -> None:
        results.append(result)

    audit_sink = FaultyEventSink(
        name="audit", delegate=JsonlAuditSink(tmp_path / "audit" / "runtime.jsonl"), board=board
    )

    async def on_result(result: RuntimeResult) -> None:
        await collect(result)
        await audit_sink(result)

    checkpoint_store = JsonPortfolioCheckpointStore(tmp_path / "state" / "portfolio.json")
    risk_audit = JsonlRiskAuditTrail(Path(settings.risk_audit_path))

    execution_reconciler = FaultyExecutionReconciler(board=board) if reconcilers else None
    portfolio_reconciler = (
        FaultyPortfolioReconciler(board=board, max_nav_difference_bps=settings.max_nav_drift_bps)
        if reconcilers
        else None
    )

    service = ContinuousPaperService(
        runtime=runtime,
        portfolio=portfolio,
        symbols=symbols,
        submit=submit,
        cycle_interval_seconds=0.0,
        error_backoff_seconds=0.0,
        on_result=on_result,
        on_portfolio=checkpoint_store.save,
        execution_ledger=ledger,
        kill_switch=kill_switch,
        risk_audit=risk_audit,
        settings=settings,
        execution_reconciler=execution_reconciler,
        portfolio_reconciler=portfolio_reconciler,
        ledger_store=ledger_store,
        reconcile_interval_seconds=0.0,
    )

    return AcceptanceHarness(
        settings=settings,
        market=market,
        board=board,
        service=service,
        portfolio=portfolio,
        venue_feed=venue_feed,
        references=references,
        reference_registries=reference_registries,
        candles=candles,
        candle_registry=candle_registry,
        intelligence=faulty_intelligence,
        meta_client=meta_client,
        venue_api=venue_api,
        ledger=ledger,
        ledger_store=ledger_store,
        risk_audit=risk_audit,
        risk_failure=risk_failure,
        kill_sentinel=kill_sentinel,
        audit_sink=audit_sink,
        checkpoint_store=checkpoint_store,
        execution_reconciler=execution_reconciler,
        portfolio_reconciler=portfolio_reconciler,
        results=results,
        _client=client,
    )


HarnessFactory = Callable[..., Awaitable["AcceptanceHarness"]]


@pytest.fixture
async def harness(tmp_path: Path):
    """Factory fixture: ``await harness(...)`` builds a fresh drill harness."""

    built: list[AcceptanceHarness] = []

    async def factory(**kwargs: object) -> AcceptanceHarness:
        instance = await build_harness(tmp_path, **kwargs)  # type: ignore[arg-type]
        built.append(instance)
        return instance

    yield factory

    for instance in built:
        instance.board.disarm_all()
        await instance.aclose()
