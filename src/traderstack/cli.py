import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog
from prometheus_client import start_http_server
from pydantic import SecretStr
from redis.asyncio import Redis

from traderstack._fs import DurableStateError
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
from traderstack.config import Settings, require_runtime_trading_mode
from traderstack.eventing import FanoutResultSink, PostgresRuntimeEventStore, RedisRuntimePublisher
from traderstack.execution.hummingbot import HummingbotPaperExecutor

# --- execution hardening (Epic 8) ---
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.execution.paper_fill import PaperFillSimulator
from traderstack.execution.paper_perp import PaperPerpBook
from traderstack.execution.planner import ExecutionPlanner
from traderstack.execution.reconcile import HummingbotExecutionReconciler
from traderstack.execution.shadow import ShadowLedger, ShadowRecorder
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
from traderstack.market.book_ticker import BookTickerProvider
from traderstack.market.crucix import (
    CrucixIntelProvider,
    crucix_effective_base_url,
    crucix_should_register,
)
from traderstack.market.intelligence_providers import (
    CryptoPanicNewsProvider,
    DuneOnChainProvider,
    LunarCrushSocialProvider,
)
from traderstack.market.kraken_candles import KrakenCandleProvider
from traderstack.market.kraken_rest import KrakenRestTickerProvider, require_paper_kraken_rest
from traderstack.market.liquidations import BinanceForceOrderProvider
from traderstack.market.perplexity import PerplexityNewsProvider
from traderstack.market.providers import (
    BookSnapshotProvider,
    CandleHistoryProvider,
    EdgeFeedCollector,
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
from traderstack.metrics import record_trading_mode  # shadow-live (Roadmap Phase 7)
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.pretrade import PreTradeBacktestGate
from traderstack.reconciliation import HummingbotPortfolioReconciler
from traderstack.risk import RiskEngine
from traderstack.risk_audit import JsonlRiskAuditTrail
from traderstack.runtime import PaperRuntime, RuntimeResult
from traderstack.service import ContinuousPaperService
from traderstack.strategies import PaperResearchStrategy, StrategyEnsemble
from traderstack.tracing import configure_tracing  # observability (Epic 9)
from traderstack.walkforward import WalkForwardEvaluator

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

_log = structlog.get_logger("traderstack.cli")


# --- durability (#67) ---
async def load_persisted_state(
    checkpoint_store: JsonPortfolioCheckpointStore,
    ledger_store: JsonExecutionLedgerStore,
    *,
    starting_nav_usd: float,
) -> tuple[InMemoryPortfolioBook, ExecutionLedger, str | None]:
    """Load the checkpoint and the idempotency ledger.

    A missing file is a fresh start. An existing-but-empty or unparsable file
    is a halt: the error string is returned so the caller can mark
    ``RuntimeHealth`` and refuse submission. The in-memory objects returned
    alongside a halt must not be treated as authoritative — they exist only
    so the process can expose health and exit without minting a new ledger.
    """

    durable_error: str | None = None
    try:
        portfolio = await checkpoint_store.load()
    except DurableStateError as exc:
        _log.error("corrupt_portfolio_checkpoint", error=str(exc), path=str(checkpoint_store.path))
        durable_error = str(exc)
        portfolio = None
    if portfolio is None:
        portfolio = InMemoryPortfolioBook(starting_nav_usd)

    try:
        execution_ledger = await ledger_store.load()
    except DurableStateError as exc:
        _log.error("corrupt_execution_ledger", error=str(exc), path=str(ledger_store.path))
        durable_error = str(exc)
        execution_ledger = None
    if execution_ledger is None:
        execution_ledger = ExecutionLedger()

    return portfolio, execution_ledger, durable_error


def paper_research_ensemble(settings: Settings) -> StrategyEnsemble:
    """Build the pre-trade ensemble, applying paper-research voters only on paper.

    Live/shadow keep the default two-of-three candle ensemble even if
    ``PAPER_RESEARCH_MODE`` is true. Paper research never changes risk limits.
    """
    if not settings.paper_research_active:
        return StrategyEnsemble()
    # Optional intel (and unset edge slots such as Crucix) cannot vote in the
    # candle ensemble. When they are intentionally off, a single healthy
    # candle-side signal is enough to form consensus; when they are
    # configured, keep the two-voter bar. The baseline is symbol-agnostic
    # and is attached once for every allowlisted asset the service cycles.
    min_agreeing = 1 if not settings.optional_intelligence_configured else 2
    return StrategyEnsemble(
        paper_research_strategy=PaperResearchStrategy(),
        min_agreeing=min_agreeing,
    )


def build_pretrade_gate(settings: Settings) -> PreTradeBacktestGate:
    # --- strategy search / paper voters ---
    from traderstack.research.promotion import build_paper_ensemble
    from traderstack.research.search import research_fee_bps

    # Promotion off (default): keep the paper-research ensemble from main.
    # PAPER_PROMOTE_EMA_9_21 (paper only) registers the documented Miles
    # daily winner, forces daily candles (1d / 1440), and takes precedence
    # over the #89 search-report gate.
    # PAPER_PROMOTE_EMA_9_21_ADX15 (paper only) registers the expanded
    # harder-gates combined-passer top-1. PAPER_PROMOTE_EMA_9_21 wins if
    # both are set. Also forces daily candles.
    # PAPER_PROMOTE_SEARCHED_STRATEGIES: only gate-clearing searched voters;
    # never a silent fallback to the unpromoted MA baseline.
    if settings.paper_promote_ema_9_21_active:
        from traderstack.research.miles_candidates import build_ema_9_21_paper_ensemble

        ensemble = build_ema_9_21_paper_ensemble()
    elif settings.paper_promote_ema_9_21_adx15_active:
        from traderstack.research.miles_candidates import build_ema_9_21_adx15_paper_ensemble

        ensemble = build_ema_9_21_adx15_paper_ensemble()
    elif settings.paper_promote_searched_strategies:
        ensemble = build_paper_ensemble(settings)
    else:
        ensemble = paper_research_ensemble(settings)
    backtester = BaselineBacktester(
        ensemble=ensemble,
        starting_equity=settings.paper_starting_nav_usd,
        fee_bps=research_fee_bps(settings.pretrade_fee_bps, settings.paper_fee_bps),
        slippage_bps=settings.pretrade_slippage_bps,
    )
    return PreTradeBacktestGate(
        backtester=backtester,
        min_candles=settings.pretrade_min_candles,
        max_candle_age_seconds=settings.effective_pretrade_max_candle_age_seconds,
        # --- miles-inspired ema_9_21 paper voter ---
        required_candle_interval=(
            settings.effective_pretrade_candle_interval
            if settings.paper_daily_promote_active
            else None
        ),
        min_excess_return=settings.effective_pretrade_min_excess_return,
        # --- miles-inspired ema_9_21 paper voter ---
        # Promote+paper uses PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT so the
        # daily research envelope (~23% WF maxDD) is not rejected by the
        # 1h PRETRADE_MAX_DRAWDOWN_PCT=0.15 bar. Live/shadow stay on 0.15.
        max_drawdown=settings.effective_pretrade_max_drawdown_pct,
        # --- paper daily promote DD series ---
        # Research (#95–#100) reports walk-forward maxDD with train
        # warmup, not full-history backtest DD. Promote path matches that
        # definition; live/shadow keep the isolated test-slice evaluator
        # and still compare the full-history book to 0.15.
        walkforward=WalkForwardEvaluator(
            backtester=backtester,
            train_warmup=settings.paper_daily_promote_active,
        ),
        compare_full_history_drawdown=not settings.paper_daily_promote_active,
        min_sharpe=settings.effective_pretrade_min_sharpe,
        min_trades=settings.effective_pretrade_min_trades,
        require_walkforward=settings.pretrade_require_walkforward,
        # --- paper pretrade thresholds ---
        min_total_return=settings.effective_pretrade_min_total_return,
        min_walkforward_excess_return=settings.effective_pretrade_min_walkforward_excess_return,
    )


def _secret(value: SecretStr | None) -> str | None:
    """Return a usable secret, or None when the value is missing/blank.

    A copied `.env.example` leaves `FOO_API_KEY=` as an empty string. Treating
    that as "set" would register optional providers that then 401/404 every
    cycle. Whitespace-only values are also unset.
    """
    if value is None:
        return None
    text = value.get_secret_value().strip()
    return text or None


# --- providers (Epic 2/3): provider health, quota and caching wrapper ----------


def build_provider_registry(
    settings: Settings,
    name: str,
    *,
    calls_per_minute: int | None = None,
    calls_per_day: int | None = None,
    cache_ttl_seconds: float = 0.0,
    last_good_ttl_seconds: float = 0.0,
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
        last_good_ttl_seconds=last_good_ttl_seconds,
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

    Blank or whitespace-only keys are treated as unset so a copied `.env.example`
    does not register providers that then 401/404 every cycle.

    Crucix, when opted in, is registered on ``fail_closed_news`` so a timeout
    or error blocks new risk. Optional news providers stay fail-open.

    Every fetcher is wrapped through a per-provider `ProviderRegistry`
    (timeout, circuit breaker, quota) - see build_provider_registry above.
    """
    quota = settings.intelligence_provider_calls_per_minute

    onchain = None
    dune_key = _secret(settings.dune_api_key)
    if dune_key is not None:
        query_ids = parse_dune_query_ids(settings.dune_query_ids)
        if query_ids:
            onchain = registered_fetcher(
                DuneOnChainProvider(api_key=dune_key, query_ids=query_ids).fetch,
                build_provider_registry(settings, "dune", calls_per_minute=quota),
            )

    social = None
    lunarcrush_key = _secret(settings.lunarcrush_api_key)
    if lunarcrush_key is not None:
        social = registered_fetcher(
            LunarCrushSocialProvider(api_key=lunarcrush_key).fetch,
            build_provider_registry(settings, "lunarcrush", calls_per_minute=quota),
        )

    news: list[NewsFetcher] = []
    cryptopanic_key = _secret(settings.cryptopanic_api_key)
    if cryptopanic_key is not None:
        news.append(
            registered_fetcher(
                CryptoPanicNewsProvider(
                    auth_token=cryptopanic_key,
                    api_plan=settings.cryptopanic_api_plan,
                ).fetch,
                build_provider_registry(settings, "cryptopanic", calls_per_minute=quota),
            )
        )
    perplexity_key = _secret(settings.perplexity_api_key)
    if perplexity_key is not None:
        news.append(
            registered_fetcher(
                PerplexityNewsProvider(api_key=perplexity_key).fetch,
                build_provider_registry(settings, "perplexity", calls_per_minute=quota),
            )
        )

    # --- providers (Epic 3): altFINS technical-signal slot ---------------------
    altfins = None
    altfins_key = _secret(settings.altfins_api_key)
    if altfins_key is not None:
        altfins = registered_fetcher(
            AltFinsSignalProvider(api_key=altfins_key).fetch,
            build_provider_registry(settings, "altfins", calls_per_minute=quota),
        )

    # --- crucix intel (fail-closed on outage) ---
    fail_closed_news: list[NewsFetcher] = []
    crucix_key = _secret(settings.crucix_api_key)
    if crucix_should_register(
        enabled=settings.crucix_enabled,
        base_url=settings.crucix_base_url,
        api_key=crucix_key,
    ):
        fail_closed_news.append(
            registered_fetcher(
                CrucixIntelProvider(
                    base_url=crucix_effective_base_url(settings.crucix_base_url),
                    api_key=crucix_key,
                ).fetch,
                build_provider_registry(settings, "crucix", calls_per_minute=quota),
            )
        )
    # --- end crucix intel ---

    if onchain is None and social is None and not news and altfins is None and not fail_closed_news:
        return None
    return IntelligenceOrchestrator(
        onchain=onchain,
        social=social,
        news=tuple(news),
        cache=IntelligenceCache(max_age_seconds=settings.intelligence_cache_seconds),
        require_any_external=settings.intelligence_required,
        altfins=altfins,
        fail_closed_news=tuple(fail_closed_news),
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
    anthropic_key = _secret(settings.anthropic_api_key)
    if anthropic_key is None:
        if mode is MetaAgentMode.VETO:
            raise RuntimeError("META_AGENT_MODE=veto requires ANTHROPIC_API_KEY")
        return None
    client = AnthropicMetaAgentClient(
        api_key=anthropic_key,
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
    # --- shadow-live (Roadmap Phase 7) ---
    parser.add_argument("--shadow-ledger-path", default="var/audit/shadow_intents.jsonl")
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
    # --- shadow-live (Roadmap Phase 7) ---
    shadow_ledger: ShadowLedger | None = None,
) -> ContinuousPaperService:
    trading_mode = require_runtime_trading_mode(settings.trading_mode)
    record_trading_mode(trading_mode)
    # --- venue feed (kraken_rest) ---
    require_paper_kraken_rest(settings.trading_mode, settings.venue_feed)

    # --- paper-trading acceptance (Epic 10) ---
    venue_client = overrides.venue_client if overrides is not None else None

    executor = None
    # --- execution hardening (Epic 8) ---
    submitter = None
    execution_reconciler = None
    portfolio_reconciler = None
    # --- shadow-live (Roadmap Phase 7) ---
    # Shadow never places venue orders: --submit is ignored, Hummingbot is not
    # constructed, and reconcilers stay unwired. The decision pipeline still runs.
    shadow_recorder = None
    venue_submit = submit and trading_mode == "paper"
    if trading_mode == "shadow":
        planner = ExecutionPlanner(
            lot_step=settings.execution_lot_step,
            min_notional_usd=settings.execution_min_notional_usd,
            max_slippage_bps=settings.execution_max_slippage_bps,
        )
        if shadow_ledger is None:
            shadow_ledger = ShadowLedger(Path("var/audit/shadow_intents.jsonl"))
        shadow_recorder = ShadowRecorder(ledger=shadow_ledger, planner=planner)
    if venue_submit:
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
            # --- paper fees (#66) ---
            paper_fee_bps=settings.paper_fee_bps,
        )
        # Local paper fills are the book of record when PAPER_SIMULATE_FILLS
        # is on. Comparing that NAV to a Hummingbot paper account that may
        # never fill would trip MAX_NAV_DRIFT_BPS and freeze new risk.
        if not settings.paper_simulate_fills:
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

    # --- paper fill simulation ---
    # Wired independently of --submit / Hummingbot. Compose app.command has
    # neither; this is how a dry-run ALLOW moves NAV, cash, drawdown and fees.
    paper_fill_simulator = None
    if trading_mode == "paper" and settings.paper_simulate_fills:
        if execution_ledger is None:
            execution_ledger = ExecutionLedger()
        paper_fill_simulator = PaperFillSimulator(
            planner=ExecutionPlanner(
                lot_step=settings.execution_lot_step,
                min_notional_usd=settings.execution_min_notional_usd,
                max_slippage_bps=settings.execution_max_slippage_bps,
            ),
            paper_fee_bps=settings.paper_fee_bps,
            paper_slippage_bps=settings.paper_slippage_bps,
            trading_mode=trading_mode,
        )

    # --- paper perp / hedge stub ---
    paper_perp_book = None
    if trading_mode == "paper" and settings.paper_perp_hedge:
        paper_perp_book = PaperPerpBook(
            trading_mode=trading_mode,
            paper_fee_bps=settings.paper_fee_bps,
            paper_slippage_bps=settings.paper_slippage_bps,
            kill_switch=kill_switch,
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
        # --- miles-inspired GARCH sizing (paper research) ---
        feature_builder=(
            CandleMarketFeatureBuilder(
                garch_enabled=settings.paper_garch_size_active,
                garch_target_vol_ann=settings.paper_garch_target_vol,
            )
            if pretrade_gate
            else None
        ),
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
        # --- paper daily promote universe (#100 honesty) ---
        if settings.paper_daily_promote_active:
            allowed = set(settings.effective_promote_universe_symbols)
            symbols = tuple(symbol for symbol in symbols if symbol in allowed)
        if not symbols:
            if settings.paper_daily_promote_active:
                raise RuntimeError(
                    "no ROBINHOOD_CHAIN_POOLS match the paper promote universe "
                    f"({', '.join(settings.effective_promote_universe_symbols) or 'empty'}); "
                    "the #100 envelope is Kraken Spot BTC/USD + ETH/USD"
                )
            raise RuntimeError("no ROBINHOOD_CHAIN_POOLS match MVP_ASSETS")
    elif settings.venue_feed == "kraken_rest":
        # --- venue feed (kraken_rest) ---
        # Paper-only public Spot Ticker poll. No book channel on REST.
        venue = KrakenRestTickerProvider(
            poll_interval_seconds=settings.kraken_rest_poll_seconds,
        )
        # --- paper daily promote universe (#100 honesty) ---
        symbols = settings.effective_cycle_symbols
    else:
        venue = KrakenTickerProvider(
            max_reconnect_attempts=settings.kraken_max_reconnect_attempts,
            backoff_base_seconds=settings.kraken_backoff_base_seconds,
            backoff_max_seconds=settings.kraken_backoff_max_seconds,
            stale_after_seconds=settings.kraken_stale_after_seconds,
        )
        # --- paper daily promote universe (#100 honesty) ---
        symbols = settings.effective_cycle_symbols
        # --- providers (Epic 2): order-book snapshot handling -------------------
        if settings.kraken_book_enabled:
            book = KrakenBookProvider(
                depth=settings.kraken_book_depth,
                max_reconnect_attempts=settings.kraken_max_reconnect_attempts,
                backoff_base_seconds=settings.kraken_backoff_base_seconds,
                backoff_max_seconds=settings.kraken_backoff_max_seconds,
                stale_after_seconds=settings.kraken_stale_after_seconds,
            )

    # --- paper daily promote universe (#100 honesty) ---
    if settings.paper_daily_promote_active and not symbols:
        raise RuntimeError(
            "PAPER_PROMOTE_UNIVERSE / MVP_ASSETS / {BTC/USD, ETH/USD} intersection "
            "is empty; the daily promote path refuses to cycle a name outside "
            "the #100 envelope"
        )

    # --- paper-research edge data plane ---
    # Streaming collectors, same reconnect loop as Kraken. Not ProviderRegistry
    # wrapped (long-lived subscriptions). Never an execution venue.
    liquidations: BinanceForceOrderProvider | None = None
    book_ticker: BookTickerProvider | None = None
    edge_collectors: list[EdgeFeedCollector] = []
    if settings.binance_liq_enabled:
        liquidations = BinanceForceOrderProvider(
            url=settings.binance_liq_url,
            assets=settings.assets,
            window_seconds=settings.binance_liq_window_seconds,
            baseline_seconds=settings.binance_liq_baseline_seconds,
            count_cap=settings.binance_liq_count_cap,
            max_age_seconds=settings.binance_liq_max_age_seconds,
            max_reconnect_attempts=settings.edge_max_reconnect_attempts,
            backoff_base_seconds=settings.edge_backoff_base_seconds,
            backoff_max_seconds=settings.edge_backoff_max_seconds,
            stale_after_seconds=settings.binance_liq_stale_after_seconds,
        )
        edge_collectors.append(liquidations)
    if settings.book_ticker_enabled:
        book_ticker = BookTickerProvider(
            venue=settings.book_ticker_venue,
            url=settings.book_ticker_url,
            assets=settings.assets,
            quote=settings.book_ticker_quote,
            max_age_seconds=settings.book_ticker_max_age_seconds,
            max_reconnect_attempts=settings.edge_max_reconnect_attempts,
            backoff_base_seconds=settings.edge_backoff_base_seconds,
            backoff_max_seconds=settings.edge_backoff_max_seconds,
            stale_after_seconds=settings.book_ticker_stale_after_seconds,
        )
        edge_collectors.append(book_ticker)

    # --- providers (Epic 2/3): provider health, quota and caching wrapper ------
    # --- paper reference resilience ---
    # Paper uses a longer cache and last-good reuse so a CoinGecko 429 does
    # not fail-close every cycle. Live/shadow keep the short TTL and never
    # serve a last-good mid after a fetch failure.
    reference_registry_kwargs = {
        "cache_ttl_seconds": settings.effective_reference_cache_seconds,
        "last_good_ttl_seconds": settings.effective_reference_last_good_seconds,
    }
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
        # --- miles-inspired ema_9_21 paper voter ---
        # Promote path forces 1d (Kraken 1440). PRETRADE_CANDLE_INTERVAL=1h
        # must not silently feed the daily-validated EMA.
        candle_interval=settings.effective_pretrade_candle_interval,
        # Promote path forces 720 (Kraken / #95–#100 window).
        # PRETRADE_CANDLE_COUNT=400 is the 1h MA lookback.
        candle_count=settings.effective_pretrade_candle_count,
        intelligence=intelligence,
        # --- meta-agent (Epic 6) ---
        meta_reviewer=build_meta_reviewer(settings),
        # --- end meta-agent (Epic 6) ---
        candle_sink=candle_sink,  # persistence (Epic 2)
        submitter=submitter,  # execution hardening (Epic 8)
        book=book,  # providers (Epic 2)
        # --- paper-research edge data plane ---
        liquidations=liquidations,
        book_ticker=book_ticker,
        # --- shadow-live (Roadmap Phase 7) ---
        trading_mode=trading_mode,
        shadow_recorder=shadow_recorder,
    )
    return ContinuousPaperService(
        runtime=runtime,
        portfolio=portfolio,
        symbols=symbols,
        submit=venue_submit,
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
        # --- paper fill simulation ---
        paper_fill_simulator=paper_fill_simulator,
        # --- paper perp / hedge stub ---
        paper_perp_book=paper_perp_book,
        # --- paper-research edge data plane ---
        edge_collectors=tuple(edge_collectors),
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
    # --- execution hardening (Epic 8) / durability (#67) ---
    # The ledger is the cross-restart idempotency record: loading it is what
    # stops a decision whose order is already live from being submitted twice.
    # An existing-but-corrupt file is halt, never a silent fresh start.
    ledger_store = JsonExecutionLedgerStore(Path(args.ledger_path))
    portfolio, execution_ledger, durable_error = await load_persisted_state(
        checkpoint_store,
        ledger_store,
        starting_nav_usd=settings.paper_starting_nav_usd,
    )
    # --- shadow-live (Roadmap Phase 7) ---
    shadow_ledger = (
        ShadowLedger(Path(args.shadow_ledger_path)) if settings.trading_mode == "shadow" else None
    )

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
        shadow_ledger=shadow_ledger,
    )
    # --- durability (#67) ---
    if durable_error is not None:
        service.submit = False
        service.health.record_durable_state_failure(durable_error)
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
