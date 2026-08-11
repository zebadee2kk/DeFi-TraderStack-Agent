from dataclasses import dataclass

from traderstack.config import Settings
from traderstack.models import PortfolioSnapshot, RiskDecision, RiskResult, TradeProposal


@dataclass(frozen=True)
class RiskEngine:
    settings: Settings
    policy_version: str = "mvp-v1"

    def evaluate(self, proposal: TradeProposal, portfolio: PortfolioSnapshot) -> RiskResult:
        reasons: list[str] = []

        if self.settings.kill_switch:
            return self._result(proposal, RiskDecision.REJECT, 0, ["kill_switch_enabled"])

        if proposal.asset.upper() not in self.settings.assets:
            reasons.append("asset_not_allowlisted")

        daily_loss_limit = portfolio.nav_usd * self.settings.max_daily_loss_pct
        if portfolio.daily_pnl_usd <= -daily_loss_limit:
            reasons.append("daily_loss_limit_reached")

        drawdown = 1 - (portfolio.nav_usd / portfolio.peak_nav_usd)
        if drawdown >= self.settings.max_account_drawdown_pct:
            reasons.append("account_drawdown_limit_reached")

        max_notional = portfolio.nav_usd * self.settings.max_position_pct
        existing = portfolio.asset_exposure_usd.get(proposal.asset.upper(), 0.0)
        remaining = max(0.0, max_notional - existing)

        if reasons or remaining <= 0:
            if remaining <= 0:
                reasons.append("position_limit_reached")
            return self._result(proposal, RiskDecision.REJECT, 0, reasons)

        approved = min(proposal.requested_notional_usd, remaining)
        decision = RiskDecision.ALLOW if approved == proposal.requested_notional_usd else RiskDecision.REDUCE
        if decision is RiskDecision.REDUCE:
            reasons.append("position_size_reduced")
        return self._result(proposal, decision, approved, reasons)

    def _result(self, proposal, decision, approved, reasons):
        return RiskResult(
            decision_id=proposal.decision_id,
            decision=decision,
            approved_notional_usd=approved,
            reasons=reasons,
            policy_version=self.policy_version,
        )
