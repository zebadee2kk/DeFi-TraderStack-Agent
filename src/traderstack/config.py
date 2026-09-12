from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `frozen=True` is part of the Zone C guarantee in docs/RISK-PRINCIPLES.md:
    # risk policy is version-controlled configuration, so nothing in-process --
    # an agent, a tool result, a compromised adapter -- can rewrite a limit on a
    # live `Settings` the `RiskEngine` already holds. Changing a limit requires a
    # configuration change and a restart, which is the promotion gate.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://traderstack:traderstack@localhost:5432/traderstack"
    redis_url: str = "redis://localhost:6379/0"
    hummingbot_api_url: str = "http://localhost:8000"
    hummingbot_api_username: str | None = None
    hummingbot_api_password: SecretStr | None = None
    hummingbot_account_name: str = "paper_account"
    hummingbot_connector_name: str = "kraken_paper_trade"
    # Provider credentials (runtime-injected; never committed). A missing or
    # blank key simply leaves that provider out of the intelligence set.
    coingecko_api_key: SecretStr | None = None
    coinmarketcap_api_key: SecretStr | None = None
    dune_api_key: SecretStr | None = None
    # "BTC:123456,ETH:234567" — Dune query id per asset returning one row with
    # exchange_netflow_z and large_wallet_accumulation columns.
    dune_query_ids: str = ""
    lunarcrush_api_key: SecretStr | None = None
    cryptopanic_api_key: SecretStr | None = None
    cryptopanic_api_plan: str = "developer"
    perplexity_api_key: SecretStr | None = None
    # --- meta-agent (Epic 6) ---
    # Anthropic credentials and the bounded review budget. A missing key leaves
    # the meta-agent uncalled (advisory) or fails startup (veto).
    anthropic_api_key: SecretStr | None = None
    # off = never called; advisory = called and recorded only; veto = a veto or a
    # failed review suppresses the paper order for that cycle.
    meta_agent_mode: Literal["off", "advisory", "veto"] = "advisory"
    meta_agent_model: str = "claude-haiku-4-5"
    meta_agent_max_tokens: int = Field(default=512, gt=0)
    meta_agent_timeout_seconds: float = Field(default=20.0, gt=0)
    # Daily budgets; 0 disables the limit. Exceeding one makes the reviewer
    # unavailable, which fails closed in veto mode.
    meta_agent_max_calls_per_day: int = Field(default=2_000, ge=0)
    meta_agent_max_tokens_per_day: int = Field(default=2_000_000, ge=0)
    # Identical evidence inside this window reuses the previous decision.
    meta_agent_cache_seconds: float = Field(default=60.0, ge=0)
    # Operator-supplied USD per million tokens, used only for cost telemetry.
    meta_agent_input_cost_per_mtok: float = Field(default=1.0, ge=0)
    meta_agent_output_cost_per_mtok: float = Field(default=5.0, ge=0)
    # --- end meta-agent (Epic 6) ---
    altfins_api_key: SecretStr | None = None
    # --- crucix intel ---
    # Local/operator Crucix alert service. Off unless CRUCIX_ENABLED=true or a
    # URL / API key is set. Adverse flags only add rejections.
    crucix_enabled: bool = False
    crucix_base_url: str = ""
    crucix_api_key: SecretStr | None = None
    # --- end crucix intel ---
    # External intelligence handling in the live loop.
    intelligence_cache_seconds: float = Field(default=300.0, gt=0)
    intelligence_block_on_adverse_news: bool = True
    intelligence_required: bool = False

    # --- providers (Epic 2/3): health, quota and caching wrapper ---------------
    # Defaults for every provider wrapped by traderstack.market.registry
    # (reference prices, candle history, intelligence fetchers). See the
    # "Selection policy" in docs/PROVIDER-CAPABILITY-MATRIX.md.
    provider_timeout_seconds: float = Field(default=10.0, gt=0)
    provider_failure_threshold: int = Field(default=3, gt=0)
    provider_breaker_cooldown_seconds: float = Field(default=30.0, gt=0)
    # Reference-price polling cache: the pipeline still sees the cached
    # observed_at, so this must stay well under max_market_data_age_seconds.
    reference_price_cache_seconds: float = Field(default=20.0, ge=0)
    # CoinGecko Demo free tier is documented around 30 req/min; CoinMarketCap
    # Basic's free allowance is small and daily-bucketed. None disables that
    # budget dimension. Re-verify against each vendor's current plan.
    coingecko_calls_per_minute: int | None = Field(default=25, gt=0)
    coingecko_calls_per_day: int | None = None
    coinmarketcap_calls_per_minute: int | None = Field(default=10, gt=0)
    coinmarketcap_calls_per_day: int | None = Field(default=300, gt=0)
    candle_provider_calls_per_minute: int | None = None
    intelligence_provider_calls_per_minute: int | None = None
    # --- paper reference resilience ---
    # TRADING_MODE=paper only. A longer TTL plus last-good reuse so a CoinGecko
    # 429 does not fail-close every cycle. Live/shadow ignore these and keep
    # the short cache / no last-good fail-closed posture. Last-good still
    # carries the original observed_at; a moved market fails
    # reference_price_divergence rather than trading a stale mid blindly.
    paper_reference_cache_seconds: float = Field(default=120.0, ge=0)
    paper_reference_last_good_seconds: float = Field(default=300.0, ge=0)

    # --- providers (Epic 2): Kraken WS resilience -------------------------------
    kraken_max_reconnect_attempts: int = Field(default=10, gt=0)
    kraken_backoff_base_seconds: float = Field(default=1.0, gt=0)
    kraken_backoff_max_seconds: float = Field(default=30.0, gt=0)
    kraken_stale_after_seconds: float = Field(default=30.0, gt=0)
    # Order-book snapshots (Epic 2): opt-in, Kraken-venue only. The pipeline
    # doesn't consume this yet; it's surfaced on RuntimeResult for a future
    # order-book depth risk check.
    kraken_book_enabled: bool = False
    kraken_book_depth: int = Field(default=10, gt=0)
    # --- venue feed (kraken_rest) ---
    # Poll interval for VENUE_FEED=kraken_rest (public Spot /0/public/Ticker).
    # Keep well under MAX_MARKET_DATA_AGE_SECONDS so a poll is never stale
    # solely because we slept too long.
    kraken_rest_poll_seconds: float = Field(default=1.0, gt=0)
    # --- end venue feed (kraken_rest) ---

    # --- paper-research edge data plane ---------------------------------------
    # Opt-in research feeds. Never an execution venue: they do not add Binance
    # or Bybit order routing, and RiskEngine does not read their features to
    # size or authorize a trade. Streaming reconnect uses the shared loop in
    # market.streaming (same pattern as Kraken ticker/book).
    binance_liq_enabled: bool = False
    binance_liq_url: str = "wss://fstream.binance.com/ws/!forceOrder@arr"
    binance_liq_window_seconds: float = Field(default=60.0, gt=0)
    binance_liq_baseline_seconds: float = Field(default=900.0, gt=0)
    binance_liq_count_cap: int = Field(default=20, gt=0)
    # 0 disables application-level staleness (liquidations are sparse; WS pings
    # remain the liveness signal).
    binance_liq_stale_after_seconds: float = Field(default=0.0, ge=0)
    binance_liq_max_age_seconds: float = Field(default=0.0, ge=0)
    book_ticker_enabled: bool = False
    book_ticker_venue: Literal["binance", "bybit"] = "binance"
    # Empty uses the venue default (Binance USDT-M combined bookTicker, or
    # Bybit v5 linear public). Not an execution endpoint.
    book_ticker_url: str = ""
    book_ticker_quote: str = "USDT"
    book_ticker_max_age_seconds: float = Field(default=5.0, gt=0)
    book_ticker_stale_after_seconds: float = Field(default=30.0, gt=0)
    edge_max_reconnect_attempts: int = Field(default=10, gt=0)
    edge_backoff_base_seconds: float = Field(default=1.0, gt=0)
    edge_backoff_max_seconds: float = Field(default=30.0, gt=0)

    trading_mode: Literal["paper", "shadow", "live"] = "paper"
    # paper  = decisions + optional Hummingbot paper submit
    # shadow = same decision/risk/meta-agent pipeline; records would-have-been
    #          orders; never calls a venue (Roadmap Phase 7)
    # live   = rejected at service construction; no live-capital path exists
    # Which venue supplies the primary execution-quality tick stream.
    # kraken_rest is a paper-only public REST fallback when WS hangs.
    venue_feed: Literal["kraken", "kraken_rest", "robinhood_chain"] = "kraken"
    paper_starting_nav_usd: float = 10_000
    mvp_assets: str = "BTC,ETH,SOL"
    max_reference_divergence_bps: float = Field(default=50.0, gt=0)
    max_market_data_age_seconds: float = Field(default=5.0, gt=0)
    # Market-data quality gate on the raw venue tick, evaluated by the pipeline
    # BEFORE any feature vector or proposal exists (rejection: spread_limit_exceeded).
    # Distinct from the risk engine's RISK_MAX_SPREAD_BPS below, which gates the
    # feature vector's spread reading as tier 4 of the risk policy (Zone C,
    # version-controlled, folded into RiskEngine.policy_version). See
    # docs/EXECUTION-ARCHITECTURE.md, "Two spread limits, deliberately".
    max_spread_bps: float = Field(default=30.0, gt=0)
    max_position_pct: float = Field(default=0.10, gt=0, le=1)
    max_daily_loss_pct: float = Field(default=0.02, gt=0, le=1)
    max_account_drawdown_pct: float = Field(default=0.10, gt=0, le=1)
    kill_switch: bool = True

    # --- risk plane (Epic 7) ---
    # Every value below is deterministic risk policy. It is read from
    # version-controlled configuration only: no agent, LLM message, tool result
    # or runtime API may mutate it. Changing any of them — plus the pretrade /
    # execution / market-data / chain-policy fields listed in RISK_LIMIT_FIELDS
    # (SEC-2026-09-18) — changes RiskEngine.policy_version, which is stamped
    # into every audit record.
    #
    # Manual policy label. Bump it when the *meaning* of the policy changes even
    # though no numeric limit did.
    risk_policy_label: str = "mvp-v1"
    # Portfolio-level exposure controls.
    max_open_positions: int = Field(default=5, gt=0)
    min_cash_reserve_pct: float = Field(default=0.05, ge=0, lt=1)
    max_gross_exposure_pct: float = Field(default=0.60, gt=0, le=1)
    # Stale-state shutdown: refuse new risk when the portfolio view is older
    # than this. Default response to inconsistent state is no new risk.
    max_portfolio_state_age_seconds: float = Field(default=60.0, gt=0)
    # Asset/venue liquidity gate applied inside the risk engine (independent of
    # the pipeline's own market-data spread check).
    risk_max_spread_bps: float = Field(default=30.0, gt=0)
    # Volatility targeting. Approved notional is scaled by
    # target_volatility / observed_volatility, and never scaled *up* above what
    # the proposal asked for.
    volatility_sizing_enabled: bool = True
    target_volatility: float = Field(default=0.02, gt=0)
    # Strategy circuit breaker.
    strategy_max_consecutive_losses: int = Field(default=3, gt=0)
    strategy_drawdown_window: int = Field(default=10, gt=0)
    strategy_max_rolling_drawdown_pct: float = Field(default=0.05, gt=0, le=1)
    strategy_breaker_cooldown_seconds: float = Field(default=3_600.0, gt=0)
    # Operator kill switch outside the LLM runtime. The sentinel file and the
    # Redis key are both writable by an operator with no access to this process.
    kill_switch_file: str = "var/state/KILL"
    kill_switch_redis_key: str = "traderstack:kill_switch"
    kill_switch_redis_enabled: bool = False
    # Append-only, hash-chained risk-decision audit trail.
    risk_audit_path: str = "var/audit/risk_decisions.jsonl"

    # Pre-trade self-check: every proposal is re-validated by backtesting the
    # strategy ensemble over recent candle history before it reaches the risk
    # engine. Missing, stale or insufficient history rejects the trade.
    pretrade_backtest_enabled: bool = True
    pretrade_candle_interval: str = "1h"
    pretrade_candle_count: int = Field(default=400, gt=0)
    pretrade_min_candles: int = Field(default=250, gt=0)
    pretrade_max_candle_age_seconds: float = Field(default=7_200.0, gt=0)
    pretrade_min_excess_return: float = 0.0
    pretrade_max_drawdown_pct: float = Field(default=0.15, gt=0, le=1)
    pretrade_min_sharpe: float = 0.0
    pretrade_min_trades: int = Field(default=3, ge=0)
    pretrade_require_walkforward: bool = True
    pretrade_fee_bps: float = Field(default=10.0, ge=0)
    pretrade_slippage_bps: float = Field(default=5.0, ge=0)
    # --- paper fees (#66) ---
    # Charged on a fill when the venue reports no fee (paper connectors
    # typically don't). Applied to cash, realized PnL, NAV, daily loss and
    # drawdown so the risk breakers are not systematically optimistic.
    # Default matches PRETRADE_FEE_BPS.
    paper_fee_bps: float = Field(default=10.0, ge=0)

    # --- paper research mode ---
    # Documented paper default. When TRADING_MODE=paper, the pre-trade ensemble
    # includes a candle-only baseline voter so a dry-run can reach an
    # intentional risk decision from Kraken OHLC alone (empty intel, no Crucix,
    # no edge fields). Live/shadow ignore this flag — see paper_research_active.
    # Does not bypass RiskEngine, the kill switch, or raise notionals.
    paper_research_mode: bool = True
    # --- paper pretrade thresholds ---
    # TRADING_MODE=paper only. Documented paper defaults for a candle-only
    # baseline on ~400-bar Kraken 1h Spot. Require *non-catastrophic*
    # evidence (total return at/above this floor, at least one completed
    # trade) and keep the gate enabled. A 16-day MA path can lose a few
    # percent on a pullback even when the current tilt is healthy — that
    # is not a blow-up, and PAPER_PRETRADE_MIN_TOTAL_RETURN=0.0 blocked
    # every BTC/SOL cycle on the WSL retest. Beating costless buy-and-hold
    # (excess_return>=0) and printing a non-negative Sharpe over ~16 days
    # remains the live/shadow promotion bar. Live/shadow always use
    # PRETRADE_MIN_* above; these paper floors never apply there.
    paper_pretrade_min_total_return: float = -0.15
    paper_pretrade_min_excess_return: float = -0.10
    paper_pretrade_min_sharpe: float = -10.0
    paper_pretrade_min_trades: int = Field(default=1, ge=0)
    paper_pretrade_min_walkforward_excess_return: float = -0.10

    # --- execution hardening (Epic 8) ---
    # Venue state is authoritative for execution. The service re-reads venue
    # orders/fills and NAV on this interval; a failed pass or NAV drift beyond
    # MAX_NAV_DRIFT_BPS blocks *new* submissions until a later pass is clean.
    reconcile_interval_seconds: float = Field(default=60.0, gt=0)
    max_nav_drift_bps: float = Field(default=25.0, gt=0)
    # Execution planner constraints applied to every approved intent.
    execution_min_notional_usd: float = Field(default=10.0, gt=0)
    execution_lot_step: float = Field(default=1e-8, gt=0)
    execution_max_slippage_bps: float = Field(default=50.0, gt=0)
    # Submission timeout and bounded retries. A timeout never implies failure:
    # retries only happen after reconciliation proves the venue does not know
    # the client order id.
    execution_submit_timeout_seconds: float = Field(default=10.0, gt=0)
    execution_max_retries: int = Field(default=2, ge=0)

    # Robinhood Chain (EVM-compatible) network identity and on-chain execution
    # policy. rpc_url/chain_id must be sourced from Robinhood's own official chain
    # documentation, never guessed or hardcoded — a wrong chain id or endpoint can
    # silently sign against the wrong network. This module treats them as unset by
    # default and fails closed until an operator supplies verified values.
    robinhood_chain_rpc_url: str | None = None
    robinhood_chain_id: int | None = Field(default=None, gt=0)
    robinhood_chain_explorer_url: str | None = None
    robinhood_chain_native_currency: str = "ETH"
    robinhood_chain_connector_name: str = "robinhood_chain"
    # "SYMBOL:0xcontract:decimals,SYMBOL:0xcontract:decimals"
    robinhood_chain_allowed_tokens: str = ""
    # "0xrouter,0xrouter"
    robinhood_chain_allowed_routers: str = ""
    # Real-time swap feed (read-only): websocket JSON-RPC endpoint, watched pools
    # and the Uniswap v4 PoolManager address (needed only for v4 pools).
    # Pool spec: "SYMBOL:v3|v4:0xpool_or_poolid:dec0:dec1:token0|token1:fee_bps,..."
    robinhood_chain_ws_url: str | None = None
    robinhood_chain_pools: str = ""
    robinhood_chain_v4_pool_manager: str = ""
    robinhood_chain_max_notional_usd: float = Field(default=0.0, ge=0)
    robinhood_chain_max_gas_limit: int = Field(default=500_000, gt=0)
    robinhood_chain_max_gas_price_gwei: float = Field(default=5.0, gt=0)

    # --- polymarket weather research (paper-only, opt-in) ---
    # Isolated from the crypto paper loop: ContinuousPaperService never reads
    # these. Enabling them only documents intent for traderstack-check-config
    # and traderstack-polymarket-weather-paper. There is no private-key field
    # on purpose — CLOB writes are not implemented.
    polymarket_weather_enabled: bool = False
    polymarket_gamma_base_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_base_url: str = "https://clob.polymarket.com"
    # MIN_EDGE: model-implied probability minus CLOB mid, after fee haircut.
    polymarket_weather_min_edge: float = Field(default=0.08, ge=0, lt=1)
    # Prefer warm/stable climates as the research default. Unknown slugs fail closed.
    polymarket_weather_cities: str = "honolulu,san_diego,miami,phoenix,singapore,lisbon"
    polymarket_weather_forecast_provider: Literal["open_meteo", "noaa"] = "open_meteo"
    polymarket_weather_open_meteo_base_url: str = "https://api.open-meteo.com"
    polymarket_weather_noaa_base_url: str = "https://api.weather.gov"
    polymarket_weather_noaa_user_agent: str = (
        "DeFi-TraderStack-Agent/0.1 (paper research; no live orders)"
    )
    # Assumed 1-day high-temp error (°F). A research prior, not a skill score.
    polymarket_weather_sigma_f: float = Field(default=2.5, gt=0)
    polymarket_weather_paper_notional_usd: float = Field(default=10.0, gt=0)
    polymarket_weather_ledger_path: str = "var/audit/polymarket_weather_paper.jsonl"
    polymarket_weather_tag_slug: str = "weather"
    polymarket_weather_max_markets: int = Field(default=40, gt=0)
    polymarket_weather_cache_seconds: float = Field(default=60.0, ge=0)
    polymarket_weather_calls_per_minute: int | None = Field(default=20, gt=0)
    polymarket_weather_min_mid: float = Field(default=0.02, ge=0, lt=1)
    polymarket_weather_max_mid: float = Field(default=0.98, gt=0, le=1)
    polymarket_weather_fee_haircut: float = Field(default=0.02, ge=0, lt=1)

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(x.strip().upper() for x in self.mvp_assets.split(",") if x.strip())

    # --- paper research mode ---
    def _secret_configured(self, value: SecretStr | None) -> bool:
        return value is not None and bool(value.get_secret_value().strip())

    @property
    def optional_intelligence_configured(self) -> bool:
        """True when at least one optional intel/edge provider has usable credentials.

        Crucix and other unset edge slots are treated the same as a missing key:
        they do not count. Used only to decide the paper-research min-voter
        rule; it never feeds the risk engine.
        """
        return (
            (self._secret_configured(self.dune_api_key) and bool(self.dune_query_ids.strip()))
            or self._secret_configured(self.lunarcrush_api_key)
            or self._secret_configured(self.cryptopanic_api_key)
            or self._secret_configured(self.perplexity_api_key)
            or self._secret_configured(self.altfins_api_key)
        )

    @property
    def paper_research_active(self) -> bool:
        """Paper-research looseness applies only on the paper path."""
        return self.trading_mode == "paper" and self.paper_research_mode

    # --- paper reference resilience / paper pretrade thresholds ---
    @property
    def paper_reference_resilience_active(self) -> bool:
        """Last-good / longer reference cache apply only on the paper path."""
        return self.trading_mode == "paper"

    @property
    def effective_reference_cache_seconds(self) -> float:
        if self.paper_reference_resilience_active:
            return self.paper_reference_cache_seconds
        return self.reference_price_cache_seconds

    @property
    def effective_reference_last_good_seconds(self) -> float:
        if self.paper_reference_resilience_active:
            return self.paper_reference_last_good_seconds
        return 0.0

    @property
    def effective_pretrade_min_excess_return(self) -> float:
        if self.trading_mode == "paper":
            return self.paper_pretrade_min_excess_return
        return self.pretrade_min_excess_return

    @property
    def effective_pretrade_min_sharpe(self) -> float:
        if self.trading_mode == "paper":
            return self.paper_pretrade_min_sharpe
        return self.pretrade_min_sharpe

    @property
    def effective_pretrade_min_trades(self) -> int:
        if self.trading_mode == "paper":
            return self.paper_pretrade_min_trades
        return self.pretrade_min_trades

    @property
    def effective_pretrade_min_total_return(self) -> float | None:
        """Paper requires a total-return floor; live/shadow do not add this check."""
        if self.trading_mode == "paper":
            return self.paper_pretrade_min_total_return
        return None

    @property
    def effective_pretrade_min_walkforward_excess_return(self) -> float:
        if self.trading_mode == "paper":
            return self.paper_pretrade_min_walkforward_excess_return
        return 0.0

    # --- paper-only Polymarket weather research ---
    @property
    def polymarket_weather_city_slugs(self) -> tuple[str, ...]:
        return tuple(
            x.strip().lower().replace(" ", "_")
            for x in self.polymarket_weather_cities.split(",")
            if x.strip()
        )


# Modes the continuous service may actually run. `live` is accepted by Settings
# so an operator misconfiguration is visible to `traderstack-check-config`, but
# `require_runtime_trading_mode` rejects it before any venue client is built.
SUPPORTED_RUNTIME_MODES: frozenset[str] = frozenset({"paper", "shadow"})


def require_runtime_trading_mode(mode: str) -> str:
    """Single choke point: paper and shadow may run; live is always rejected."""

    if mode == "live":
        raise RuntimeError(
            "TRADING_MODE=live is rejected; live capital is out of scope until "
            "the remaining gates in docs/MVP-BACKLOG.md close"
        )
    if mode not in SUPPORTED_RUNTIME_MODES:
        raise RuntimeError(f"unsupported trading mode: {mode}")
    return mode
