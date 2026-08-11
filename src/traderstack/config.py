from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str
    redis_url: str
    trading_mode: Literal["paper", "shadow", "live"] = "paper"
    paper_starting_nav_usd: float = 10_000
    mvp_assets: str = "BTC,ETH,SOL"
    max_position_pct: float = Field(default=0.10, gt=0, le=1)
    max_daily_loss_pct: float = Field(default=0.02, gt=0, le=1)
    max_account_drawdown_pct: float = Field(default=0.10, gt=0, le=1)
    kill_switch: bool = True

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(x.strip().upper() for x in self.mvp_assets.split(",") if x.strip())
