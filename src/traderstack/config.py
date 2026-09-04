from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://traderstack:traderstack@localhost:5432/traderstack"
    redis_url: str = "redis://localhost:6379/0"
    hummingbot_api_url: str = "http://localhost:8000"
    hummingbot_api_username: str | None = None
    hummingbot_api_password: SecretStr | None = None
    hummingbot_account_name: str = "paper_account"
    hummingbot_connector_name: str = "kraken_paper_trade"
    # Provider credentials (runtime-injected; never committed). A missing key
    # simply leaves that provider out of the intelligence set.
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
    # External intelligence handling in the live loop.
    intelligence_cache_seconds: float = Field(default=300.0, gt=0)
    intelligence_block_on_adverse_news: bool = True
    intelligence_required: bool = False

    trading_mode: Literal["paper", "shadow", "live"] = "paper"
    # Which venue supplies the primary execution-quality tick stream.
    venue_feed: Literal["kraken", "robinhood_chain"] = "kraken"
    paper_starting_nav_usd: float = 10_000
    mvp_assets: str = "BTC,ETH,SOL"
    max_reference_divergence_bps: float = Field(default=50.0, gt=0)
    max_market_data_age_seconds: float = Field(default=5.0, gt=0)
    max_position_pct: float = Field(default=0.10, gt=0, le=1)
    max_daily_loss_pct: float = Field(default=0.02, gt=0, le=1)
    max_account_drawdown_pct: float = Field(default=0.10, gt=0, le=1)
    kill_switch: bool = True

    # --- risk plane (Epic 7) ---
    # Every value below is deterministic risk policy. It is read from
    # version-controlled configuration only: no agent, LLM message, tool result
    # or runtime API may mutate it. Changing any of them changes
    # RiskEngine.policy_version, which is stamped into every audit record.
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

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(x.strip().upper() for x in self.mvp_assets.split(",") if x.strip())
