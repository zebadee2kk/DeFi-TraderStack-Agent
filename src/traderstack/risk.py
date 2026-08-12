from dataclasses import dataclass

from traderstack.config import Settings
from traderstack.models import PortfolioSnapshot, RiskDecision, RiskResult, Side, TradeProposal


@dataclass(frozen=True)
class RiskEngine:
    settings: Settings
    policy_version: str = "mvp-v2"

    def evaluate(self, proposal: TradeProposal, portfolio: PortfolioSnapshot) -> RiskResult:
        if self.settings.kill_switch:
            return self._result(proposal, RiskDecision.REJECT, 0, ["kill_switch_enabled"])

        asset = proposal.asset.upper()
        if asset not in self.settings.assets:
            return self._result(proposal, RiskDecision.REJECT, 0, ["asset_not_allowlisted"])

        existing = portfolio.asset_exposure_usd.get(asset, 0.0)
        if proposal.side is Side.SELL:
            return self._evaluate_sell(proposal, existing)
        return self._evaluate_buy(proposal, portfolio, existing)

    def _evaluate_sell(self, proposal: TradeProposal, existing_exposure_usd: float) -> RiskResult:
        # Sells only reduce paper exposure (no shorts), so loss/drawdown breakers
        # never block an exit; only the kill switch and allowlist gate them.
        if existing_exposure_usd <= 0:
            return self._result(proposal, RiskDecision.REJECT, 0, ["no_position_to_reduce"])
        approved = min(proposal.requested_notional_usd, existing_exposure_usd)
        if approved < self.settings.min_order_notional_usd:
            return self._result(proposal, RiskDecision.REJECT, 0, ["below_minimum_notional"])
        if approved == proposal.requested_notional_usd:
            return self._result(proposal, RiskDecision.ALLOW, approved, [])
        return self._result(proposal, RiskDecision.REDUCE, approved, ["sell_capped_to_position"])

    def _evaluate_buy(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioSnapshot,
        existing_exposure_usd: float,
    ) -> RiskResult:
        reasons: list[str] = []

        daily_loss_limit = portfolio.nav_usd * self.settings.max_daily_loss_pct
        if portfolio.daily_pnl_usd <= -daily_loss_limit:
            reasons.append("daily_loss_limit_reached")

        drawdown = 1 - (portfolio.nav_usd / portfolio.peak_nav_usd)
        if drawdown >= self.settings.max_account_drawdown_pct:
            reasons.append("account_drawdown_limit_reached")

        max_notional = portfolio.nav_usd * self.settings.max_position_pct
        remaining = max(0.0, max_notional - existing_exposure_usd)

        if reasons or remaining <= 0:
            if remaining <= 0:
                reasons.append("position_limit_reached")
            return self._result(proposal, RiskDecision.REJECT, 0, reasons)

        approved = min(proposal.requested_notional_usd, remaining)
        if approved < self.settings.min_order_notional_usd:
            return self._result(proposal, RiskDecision.REJECT, 0, ["below_minimum_notional"])
        decision = RiskDecision.ALLOW if approved == proposal.requested_notional_usd else RiskDecision.REDUCE
        if decision is RiskDecision.REDUCE:
            reasons.append("position_size_reduced")
        return self._result(proposal, decision, approved, reasons)

    def _result(
        self,
        proposal: TradeProposal,
        decision: RiskDecision,
        approved: float,
        reasons: list[str],
    ) -> RiskResult:
        return RiskResult(
            decision_id=proposal.decision_id,
            decision=decision,
            approved_notional_usd=approved,
            reasons=reasons,
            policy_version=self.policy_version,
        )
