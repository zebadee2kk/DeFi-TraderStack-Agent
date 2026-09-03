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
    trading_mode: Literal["paper", "shadow", "live"] = "paper"
    paper_starting_nav_usd: float = 10_000
    mvp_assets: str = "BTC,ETH,SOL"
    max_reference_divergence_bps: float = Field(default=50.0, gt=0)
    max_market_data_age_seconds: float = Field(default=5.0, gt=0)
    max_position_pct: float = Field(default=0.10, gt=0, le=1)
    max_daily_loss_pct: float = Field(default=0.02, gt=0, le=1)
    max_account_drawdown_pct: float = Field(default=0.10, gt=0, le=1)
    kill_switch: bool = True

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
    robinhood_chain_max_notional_usd: float = Field(default=0.0, ge=0)
    robinhood_chain_max_gas_limit: int = Field(default=500_000, gt=0)
    robinhood_chain_max_gas_price_gwei: float = Field(default=5.0, gt=0)

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(x.strip().upper() for x in self.mvp_assets.split(",") if x.strip())
