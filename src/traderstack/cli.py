import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from prometheus_client import start_http_server
from pydantic import SecretStr
from redis.asyncio import Redis

from traderstack.agents.claude import AnthropicMetaAgentClient
from traderstack.agents.review import (
    DailyBudget,
    EvidenceCache,
    MetaAgentMode,
    MetaAgentReviewer,
)
from traderstack.agents.specialists import SpecialistCommittee
from traderstack.audit import JsonlAuditSink
from traderstack.backtest import BaselineBacktester
from traderstack.candle_store import PostgresCandleStore  # persistence (Epic 2)
from traderstack.candles import Candle  # persistence (Epic 2)
from traderstack.checkpoint import JsonPortfolioCheckpointStore

# --- risk plane (Epic 7) ---
from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.config import Settings
from traderstack.eventing import FanoutResultSink, PostgresRuntimeEventStore, RedisRuntimePublisher
from traderstack.execution.hummingbot import HummingbotPaperExecutor

# --- execution hardening (Epic 8) ---
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.execution.planner import ExecutionPlanner
from traderstack.execution.reconcile import HummingbotExecutionReconciler
from traderstack.execution.submitter import IdempotentSubmitter
from traderstack.intelligence_orchestrator import (
    IntelligenceCache,
    IntelligenceOrchestrator,
    NewsFetcher,
)
from traderstack.killswitch import KillSwitch, install_signal_handler
from traderstack.logging_config import configure_logging  # observability (Epic 9)
from traderstack.market.adapters import (
    CoinGeckoPriceProvider,
    CoinMarketCapPriceProvider,
    KrakenBookProvider,
    KrakenTickerProvider,
)
from traderstack.market.altfins import AltFinsSignalProvider
from traderstack.market.intelligence_providers import (
    CryptoPanicNewsProvider,
    DuneOnChainProvider,
    LunarCrushSocialProvider,
)
from traderstack.market.kraken_candles import KrakenCandleProvider
from traderstack.market.perplexity import PerplexityNewsProvider
from traderstack.market.providers import (
    BookSnapshotProvider,
    CandleHistoryProvider,
    ReferencePriceProvider,
    VenueMarketDataProvider,
)
from traderstack.market.registry import (
    ProviderRegistry,
    RegisteredCandleHistoryProvider,
    RegisteredReferencePriceProvider,
    registered_fetcher,
)
from traderstack.market.robinhood_chain_feed import swap_feed_from_settings
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.pretrade import PreTradeBacktestGate
from traderstack.reconciliation import HummingbotPortfolioReconciler
from traderstack.risk import RiskEngine
from traderstack.risk_audit import JsonlRiskAuditTrail
from traderstack.runtime import PaperRuntime, RuntimeResult
from traderstack.service import ContinuousPaperService
from traderstack.tracing import configure_tracing  # observability (Epic 9)

ResultHandler = Callable[[RuntimeResult], Awaitable[None]]
CandleSink = Callable[[tuple[Candle, ...]], Awaitable[None]]  # persistence (Epic 2)


# --- paper-trading acceptance (Epic 10) ---
@dataclass(frozen=True)
class ServiceOverrides:
    """Doubles for the *external edges* of the service, used by `traderstack-soak`.

    Only the network-facing providers and the venue HTTP client are replaceable.
    Everything the acceptance drills are actually about -- pipeline, risk engine,
    pre-trade gate, planner, submitter, ledger, reconcilers, kill switch, audit
    trails -- is still built here exactly as it is for a live paper run, which is
    the entire point of running the soak through `build_service` rather than a
    parallel assembly.
    """

    venue: VenueMarketDataProvider | None = None
    references: tuple[ReferencePriceProvider, ...] | None = None
    candles: CandleHistoryProvider | None = None
    symbols: tuple[str, ...] | None = None
    #: Shared httpx client for the Hummingbot executor and both reconcilers.
    venue_client: httpx.AsyncClient | None = None


# --- end paper-trading acceptance (Epic 10) ---


def build_pretrade_gate(settings: Settings) -> PreTradeBacktestGate:
    backtester = BaselineBacktester(
        starting_equity=settings.paper_starting_nav_usd,
        fee_bps=settings.pretrade_fee_bps,
        slippage_bps=settings.pretrade_slippage_bps,
    )
    return PreTradeBacktestGate(
        backtester=backtester,
        min_candles=settings.pretrade_min_candles,
        max_candle_age_seconds=settings.pretrade_max_candle_age_seconds,
        min_excess_return=settings.pretrade_min_excess_return,
        max_drawdown=settings.pretrade_max_drawdown_pct,
        min_sharpe=settings.pretrade_min_sharpe,
        min_trades=settings.pretrade_min_trades,
        require_walkforward=settings.pretrade_require_walkforward,
    )


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


# --- providers (Epic 2/3): provider health, quota and caching wrapper ----------


def build_provider_registry(
    settings: Settings,
    name: str,
    *,
    calls_per_minute: int | None = None,
    calls_per_day: int | None = None,
    cache_ttl_seconds: float = 0.0,
) -> ProviderRegistry:
    """One `ProviderRegistry` per named provider, using the shared timeout/
    breaker defaults from settings plus that provider's own quota/cache.
    """
    return ProviderRegistry(
        name=name,
        timeout_seconds=settings.provider_timeout_seconds,
        failure_threshold=settings.provider_failure_threshold,
        cooldown_seconds=settings.provider_breaker_cooldown_seconds,
        calls_per_minute=calls_per_minute,
        calls_per_day=calls_per_day,
        cache_ttl_seconds=cache_ttl_seconds,
    )


def parse_dune_query_ids(raw: str) -> dict[str, int]:
    query_ids: dict[str, int] = {}
    for spec in raw.split(","):
        spec = spec.strip()
        if not spec:
            continue
        asset, _, query_id = spec.partition(":")
        if not asset.strip() or not query_id.strip().isdigit():
            raise RuntimeError(f"malformed DUNE_QUERY_IDS entry: {spec!r}")
        query_ids[asset.strip().upper()] = int(query_id.strip())
    return query_ids


def build_intelligence(settings: Settings) -> IntelligenceOrchestrator | None:
    """Assemble every intelligence provider that has credentials; None if there are none.

    Every fetcher is wrapped through a per-provider `ProviderRegistry`
    (timeout, circuit breaker, quota) - see build_provider_registry above.
    """
    quota = settings.intelligence_provider_calls_per_minute

    onchain = None
    if settings.dune_api_key is not None:
        query_ids = parse_dune_query_ids(settings.dune_query_ids)
        if query_ids:
            onchain = registered_fetcher(
                DuneOnChainProvider(
                    api_key=settings.dune_api_key.get_secret_value(), query_ids=query_ids
                ).fetch,
                build_provider_registry(settings, "dune", calls_per_minute=quota),
            )

    social = None
    if settings.lunarcrush_api_key is not None:
        social = registered_fetcher(
            LunarCrushSocialProvider(api_key=settings.lunarcrush_api_key.get_secret_value()).fetch,
            build_provider_registry(settings, "lunarcrush", calls_per_minute=quota),
        )

    news: list[NewsFetcher] = []
    if settings.cryptopanic_api_key is not None:
        news.append(
            registered_fetcher(
                CryptoPanicNewsProvider(
                    auth_token=settings.cryptopanic_api_key.get_secret_value(),
                    api_plan=settings.cryptopanic_api_plan,
                ).fetch,
                build_provider_registry(settings, "cryptopanic", calls_per_minute=quota),
            )
        )
    if settings.perplexity_api_key is not None:
        news.append(
            registered_fetcher(
                PerplexityNewsProvider(
                    api_key=settings.perplexity_api_key.get_secret_value()
                ).fetch,
                build_provider_registry(settings, "perplexity", calls_per_minute=quota),
            )
        )

    # --- providers (Epic 3): altFINS technical-signal slot ---------------------
    altfins = None
    if settings.altfins_api_key is not None:
        altfins = registered_fetcher(
            AltFinsSignalProvider(api_key=settings.altfins_api_key.get_secret_value()).fetch,
            build_provider_registry(settings, "altfins", calls_per_minute=quota),
        )

    if onchain is None and social is None and not news and altfins is None:
        return None
    return IntelligenceOrchestrator(
        onchain=onchain,
        social=social,
        news=tuple(news),
        cache=IntelligenceCache(max_age_seconds=settings.intelligence_cache_seconds),
        require_any_external=settings.intelligence_required,
        altfins=altfins,
    )


# --- meta-agent (Epic 6) ---
def build_meta_reviewer(settings: Settings) -> MetaAgentReviewer | None:
    """Construct the constrained meta-agent, or None when it is not in play.

    The Anthropic client is only built when a key is present and the mode is not
    `off`. Veto mode without a key is a startup error rather than a silent
    downgrade: an operator who asked for a veto gate must not get no gate.
    """
    mode = MetaAgentMode(settings.meta_agent_mode)
    if mode is MetaAgentMode.OFF:
        return None
    if settings.anthropic_api_key is None:
        if mode is MetaAgentMode.VETO:
            raise RuntimeError("META_AGENT_MODE=veto requires ANTHROPIC_API_KEY")
        return None
    client = AnthropicMetaAgentClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.meta_agent_model,
        max_tokens=settings.meta_agent_max_tokens,
        timeout_seconds=settings.meta_agent_timeout_seconds,
    )
    return MetaAgentReviewer(
        client=client,
        mode=mode,
        model=settings.meta_agent_model,
        timeout_seconds=settings.meta_agent_timeout_seconds,
        committee=SpecialistCommittee(),
        cache=EvidenceCache(ttl_seconds=settings.meta_agent_cache_seconds),
        budget=DailyBudget(
            max_calls=settings.meta_agent_max_calls_per_day,
            max_tokens=settings.meta_agent_max_tokens_per_day,
        ),
        input_cost_per_mtok=settings.meta_agent_input_cost_per_mtok,
        output_cost_per_mtok=settings.meta_agent_output_cost_per_mtok,
    )


# --- end meta-agent (Epic 6) ---


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the guarded continuous paper trading service")
    parser.add_argument("--submit", action="store_true", help="submit approved paper orders")
    parser.add_argument("--audit-path", default="var/audit/runtime.jsonl")
    parser.add_argument("--checkpoint-path", default="var/state/portfolio.json")
    # --- risk plane (Epic 7) ---
    parser.add_argument("--risk-audit-path", default="var/audit/risk_decisions.jsonl")
    # --- execution hardening (Epic 8) ---
    parser.add_argument("--ledger-path", default="var/state/execution_ledger.json")
    parser.add_argument("--cycle-seconds", type=float, default=5.0)
    parser.add_argument("--metrics-port", type=int, default=9108)
    parser.add_argument(
        "--persistent-events",
        action="store_true",
        help="also persist runtime events to PostgreSQL and publish them to Redis",
    )
    return parser


def build_service(
    settings: Settings,
    *,
    submit: bool,
    cycle_seconds: float,
    portfolio: InMemoryPortfolioBook,
    on_result: ResultHandler,
    checkpoint_store: JsonPortfolioCheckpointStore,
    candle_sink: CandleSink | None = None,  # persistence (Epic 2)
    kill_switch: KillSwitch | None = None,
    circuit_breaker: StrategyCircuitBreaker | None = None,
    risk_audit: JsonlRiskAuditTrail | None = None,
    # --- execution hardening (Epic 8) ---
    execution_ledger: ExecutionLedger | None = None,
    ledger_store: JsonExecutionLedgerStore | None = None,
    # --- paper-trading acceptance (Epic 10) ---
    overrides: ServiceOverrides | None = None,
) -> ContinuousPaperService:
    if settings.trading_mode != "paper":
        raise RuntimeError("continuous paper service requires TRADING_MODE=paper")

    # --- paper-trading acceptance (Epic 10) ---
    venue_client = overrides.venue_client if overrides is not None else None

    executor = None
    # --- execution hardening (Epic 8) ---
    submitter = None
    execution_reconciler = None
    portfolio_reconciler = None
    if submit:
        if settings.hummingbot_api_username is None or settings.hummingbot_api_password is None:
            raise RuntimeError("paper submission requires Hummingbot API credentials")
        password = settings.hummingbot_api_password.get_secret_value()
        executor = HummingbotPaperExecutor(
            base_url=settings.hummingbot_api_url,
            username=settings.hummingbot_api_username,
            password=password,
            account_name=settings.hummingbot_account_name,
            connector_name=settings.hummingbot_connector_name,
            timeout_seconds=settings.execution_submit_timeout_seconds,
            client=venue_client,  # paper-trading acceptance (Epic 10)
        )
        # Reconcilers double as the retry gate: nothing is resubmitted until one
        # of them has confirmed the venue does not know the client order id.
        execution_reconciler = HummingbotExecutionReconciler(
            base_url=settings.hummingbot_api_url,
            username=settings.hummingbot_api_username,
            password=password,
            account_name=settings.hummingbot_account_name,
            connector_name=settings.hummingbot_connector_name,
            client=venue_client,  # paper-trading acceptance (Epic 10)
        )
        portfolio_reconciler = HummingbotPortfolioReconciler(
            base_url=settings.hummingbot_api_url,
            username=settings.hummingbot_api_username,
            password=password,
            account_name=settings.hummingbot_account_name,
            connector_name=settings.hummingbot_connector_name,
            max_nav_difference_bps=settings.max_nav_drift_bps,
            client=venue_client,  # paper-trading acceptance (Epic 10)
        )
        if execution_ledger is None:
            execution_ledger = ExecutionLedger()
        submitter = IdempotentSubmitter(
            executor=executor,
            ledger=execution_ledger,
            planner=ExecutionPlanner(
                lot_step=settings.execution_lot_step,
                min_notional_usd=settings.execution_min_notional_usd,
                max_slippage_bps=settings.execution_max_slippage_bps,
            ),
            resolver=execution_reconciler,
            ledger_store=ledger_store,
            timeout_seconds=settings.execution_submit_timeout_seconds,
            max_retries=settings.execution_max_retries,
        )

    pretrade_gate = None
    candle_provider = None
    if settings.pretrade_backtest_enabled:
        pretrade_gate = build_pretrade_gate(settings)
        # --- providers (Epic 2/3): provider health, quota and caching wrapper --
        candle_provider = RegisteredCandleHistoryProvider(
            overrides.candles
            if overrides is not None and overrides.candles is not None
            else KrakenCandleProvider(),
            build_provider_registry(
                settings,
                "kraken_candles",
                calls_per_minute=settings.candle_provider_calls_per_minute,
            ),
        )

    intelligence = build_intelligence(settings)
    if settings.intelligence_required and intelligence is None:
        raise RuntimeError(
            "INTELLIGENCE_REQUIRED=true but no intelligence provider has credentials"
        )

    pipeline = VerticalSlicePipeline(
        # --- risk plane (Epic 7) --- live halt + strategy breaker, not the
        # static settings flag alone.
        risk_engine=RiskEngine(settings, kill_switch=kill_switch, circuit_breaker=circuit_breaker),
        max_tick_age_seconds=settings.max_market_data_age_seconds,
        max_spread_bps=settings.max_spread_bps,
        max_reference_divergence_bps=settings.max_reference_divergence_bps,
        pretrade_gate=pretrade_gate,
        feature_builder=CandleMarketFeatureBuilder() if pretrade_gate else None,
        block_on_adverse_news=settings.intelligence_block_on_adverse_news,
        require_external_intelligence=settings.intelligence_required,
    )
    venue: VenueMarketDataProvider
    book: BookSnapshotProvider | None = None
    if settings.venue_feed == "robinhood_chain":
        swap_feed = swap_feed_from_settings(settings)
        venue = swap_feed
        symbols = tuple(
            pool.symbol
            for pool in swap_feed.pools
            if pool.symbol.split("/", 1)[0].upper() in settings.assets
        )
        if not symbols:
            raise RuntimeError("no ROBINHOOD_CHAIN_POOLS match MVP_ASSETS")
    else:
        venue = KrakenTickerProvider(
            max_reconnect_attempts=settings.kraken_max_reconnect_attempts,
            backoff_base_seconds=settings.kraken_backoff_base_seconds,
            backoff_max_seconds=settings.kraken_backoff_max_seconds,
            stale_after_seconds=settings.kraken_stale_after_seconds,
        )
        symbols = tuple(f"{asset}/USD" for asset in settings.assets)
        # --- providers (Epic 2): order-book snapshot handling -------------------
        if settings.kraken_book_enabled:
            book = KrakenBookProvider(
                depth=settings.kraken_book_depth,
                max_reconnect_attempts=settings.kraken_max_reconnect_attempts,
                backoff_base_seconds=settings.kraken_backoff_base_seconds,
                backoff_max_seconds=settings.kraken_backoff_max_seconds,
                stale_after_seconds=settings.kraken_stale_after_seconds,
            )

    # --- providers (Epic 2/3): provider health, quota and caching wrapper ------
    reference_registry_kwargs = {"cache_ttl_seconds": settings.reference_price_cache_seconds}
    # (registry name, provider, calls/minute, calls/day)
    reference_specs: tuple[tuple[str, ReferencePriceProvider, int | None, int | None], ...] = (
        (
            "coingecko",
            CoinGeckoPriceProvider(api_key=_secret(settings.coingecko_api_key)),
            settings.coingecko_calls_per_minute,
            settings.coingecko_calls_per_day,
        ),
        (
            "coinmarketcap",
            CoinMarketCapPriceProvider(api_key=_secret(settings.coinmarketcap_api_key)),
            settings.coinmarketcap_calls_per_minute,
            settings.coinmarketcap_calls_per_day,
        ),
    )
    # --- paper-trading acceptance (Epic 10) ---
    if overrides is not None:
        if overrides.venue is not None:
            venue = overrides.venue
        if overrides.symbols is not None:
            symbols = overrides.symbols
        if overrides.references is not None:
            # Substituted providers keep the real registry wrapper (timeout,
            # breaker, cache) but carry no vendor quota, since they are not the
            # vendor.
            reference_specs = tuple(
                (f"reference_{index}", source, None, None)
                for index, source in enumerate(overrides.references)
            )
    # --- end paper-trading acceptance (Epic 10) ---
    references = tuple(
        RegisteredReferencePriceProvider(
            source,
            build_provider_registry(
                settings,
                name,
                calls_per_minute=per_minute,
                calls_per_day=per_day,
                **reference_registry_kwargs,
            ),
        )
        for name, source, per_minute, per_day in reference_specs
    )
    runtime = PaperRuntime(
        venue=venue,
        references=references,
        pipeline=pipeline,
        executor=executor,
        candles=candle_provider,
        candle_interval=settings.pretrade_candle_interval,
        candle_count=settings.pretrade_candle_count,
        intelligence=intelligence,
        # --- meta-agent (Epic 6) ---
        meta_reviewer=build_meta_reviewer(settings),
        # --- end meta-agent (Epic 6) ---
        candle_sink=candle_sink,  # persistence (Epic 2)
        submitter=submitter,  # execution hardening (Epic 8)
        book=book,  # providers (Epic 2)
    )
    return ContinuousPaperService(
        runtime=runtime,
        portfolio=portfolio,
        symbols=symbols,
        submit=submit,
        cycle_interval_seconds=cycle_seconds,
        on_result=on_result,
        on_portfolio=checkpoint_store.save,
        # --- risk plane (Epic 7) ---
        kill_switch=kill_switch,
        risk_audit=risk_audit,
        settings=settings,
        # --- execution hardening (Epic 8) ---
        execution_ledger=execution_ledger,
        execution_reconciler=execution_reconciler,
        portfolio_reconciler=portfolio_reconciler,
        ledger_store=ledger_store,
        reconcile_interval_seconds=settings.reconcile_interval_seconds,
    )


async def _main_async(args: argparse.Namespace) -> None:
    settings = Settings()
    configure_logging(settings)  # observability (Epic 9)
    configure_tracing()  # observability (Epic 9): no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set
    # --- risk plane (Epic 7) ---
    install_signal_handler()
    # The Redis halt channel only exists if a client is actually wired; without
    # one KillSwitch.from_settings fails closed rather than pretending.
    kill_switch_redis = (
        Redis.from_url(settings.redis_url, decode_responses=True)
        if settings.kill_switch_redis_enabled
        else None
    )
    kill_switch = KillSwitch.from_settings(settings, redis_client=kill_switch_redis)
    circuit_breaker = StrategyCircuitBreaker.from_settings(settings)
    risk_audit = JsonlRiskAuditTrail(Path(args.risk_audit_path))
    checkpoint_store = JsonPortfolioCheckpointStore(
        Path(args.checkpoint_path), circuit_breaker=circuit_breaker
    )
    portfolio = await checkpoint_store.load()
    if portfolio is None:
        portfolio = InMemoryPortfolioBook(settings.paper_starting_nav_usd)

    # --- execution hardening (Epic 8) ---
    # The ledger is the cross-restart idempotency record: loading it is what
    # stops a decision whose order is already live from being submitted twice.
    ledger_store = JsonExecutionLedgerStore(Path(args.ledger_path))
    execution_ledger = await ledger_store.load() or ExecutionLedger()

    sinks: list[ResultHandler] = [JsonlAuditSink(Path(args.audit_path))]
    postgres: PostgresRuntimeEventStore | None = None
    redis: RedisRuntimePublisher | None = None
    candle_store: PostgresCandleStore | None = None  # persistence (Epic 2)
    candle_sink: CandleSink | None = None  # persistence (Epic 2)
    if args.persistent_events:
        postgres = PostgresRuntimeEventStore(settings.database_url)
        await postgres.initialize()
        redis = RedisRuntimePublisher(settings.redis_url)
        sinks.extend((postgres, redis))
        # --- persistence (Epic 2): also append fetched candle history to Postgres ---
        candle_store = PostgresCandleStore(settings.database_url)
        await candle_store.initialize()
        candle_sink = candle_store.append_many
        # --- end persistence (Epic 2) ---

    start_http_server(args.metrics_port)
    service = build_service(
        settings,
        submit=args.submit,
        cycle_seconds=args.cycle_seconds,
        portfolio=portfolio,
        on_result=FanoutResultSink(tuple(sinks)),
        checkpoint_store=checkpoint_store,
        candle_sink=candle_sink,  # persistence (Epic 2)
        # --- risk plane (Epic 7) ---
        kill_switch=kill_switch,
        circuit_breaker=circuit_breaker,
        risk_audit=risk_audit,
        # --- execution hardening (Epic 8) ---
        execution_ledger=execution_ledger,
        ledger_store=ledger_store,
    )
    try:
        await service.run()
    finally:
        if postgres is not None:
            await postgres.close()
        if redis is not None:
            await redis.close()
        if candle_store is not None:  # persistence (Epic 2)
            await candle_store.close()
        if kill_switch_redis is not None:  # --- risk plane (Epic 7) ---
            await kill_switch_redis.aclose()


def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
