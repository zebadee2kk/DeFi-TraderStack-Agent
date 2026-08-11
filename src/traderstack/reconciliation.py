from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field

from traderstack.portfolio import InMemoryPortfolioBook


class ReconciliationResult(BaseModel):
    matched: bool
    internal_nav_usd: float = Field(ge=0)
    external_nav_usd: float = Field(ge=0)
    nav_difference_usd: float = Field(ge=0)
    nav_difference_bps: float = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)


@dataclass
class HummingbotPortfolioReconciler:
    base_url: str
    username: str
    password: str
    account_name: str = "paper_account"
    connector_name: str = "kraken_paper_trade"
    max_nav_difference_bps: float = 25.0
    client: httpx.AsyncClient | None = None

    async def reconcile(self, portfolio: InMemoryPortfolioBook) -> ReconciliationResult:
        payload = {
            "account_names": [self.account_name],
            "connector_names": [self.connector_name],
            "refresh": True,
        }
        if self.client is not None:
            response = await self.client.post("/portfolio/state", json=payload)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                auth=(self.username, self.password),
                timeout=10,
            ) as client:
                response = await client.post("/portfolio/state", json=payload)
        response.raise_for_status()
        external_nav = self._extract_nav(response.json())
        internal_nav = portfolio.nav_usd
        difference = abs(external_nav - internal_nav)
        difference_bps = difference / internal_nav * 10_000 if internal_nav else 10_000.0
        reasons: list[str] = []
        if difference_bps > self.max_nav_difference_bps:
            reasons.append(
                f"portfolio NAV drift {difference_bps:.2f} bps exceeds "
                f"{self.max_nav_difference_bps:.2f} bps"
            )
        return ReconciliationResult(
            matched=not reasons,
            internal_nav_usd=internal_nav,
            external_nav_usd=external_nav,
            nav_difference_usd=difference,
            nav_difference_bps=difference_bps,
            reasons=reasons,
        )

    def _extract_nav(self, payload: object) -> float:
        if not isinstance(payload, dict):
            raise TypeError("unexpected Hummingbot portfolio response")
        account = payload.get(self.account_name)
        if not isinstance(account, dict):
            raise TypeError("Hummingbot response missing configured account")
        connector = account.get(self.connector_name)
        if connector is None:
            raise ValueError("Hummingbot response missing configured connector")

        if isinstance(connector, dict):
            balances = connector.values()
        elif isinstance(connector, list):
            balances = connector
        else:
            raise TypeError("unexpected Hummingbot connector balance response")

        total = 0.0
        for balance in balances:
            if not isinstance(balance, dict):
                raise TypeError("unexpected Hummingbot balance item")
            value = balance.get("value")
            if not isinstance(value, int | float):
                raise TypeError("Hummingbot balance item missing numeric value")
            total += float(value)
        if total < 0:
            raise ValueError("Hummingbot portfolio NAV cannot be negative")
        return total
