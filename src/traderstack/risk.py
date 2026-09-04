"""Deterministic risk engine (Epic 7).

Everything here is Zone C: no LLM, agent message, tool result or retrieved text
can modify, disable, bypass or authorise an exception to any limit below. Limits
come from ``Settings`` -- version-controlled configuration -- and nowhere else.

Checks are ordered by the control hierarchy in docs/RISK-PRINCIPLES.md, and a
higher layer's rejection always survives whatever a lower layer would have
allowed:

1. global halt / operator kill switch  -> kill_switch_enabled
2. account and portfolio limits        -> stale_portfolio_state,
                                          daily_loss_limit_reached,
                                          account_drawdown_limit_reached,
                                          gross_exposure_limit,
                                          cash_reserve_breached,
                                          max_positions_reached
3. strategy limits                     -> strategy_circuit_breaker
4. asset / venue limits                -> asset_not_allowlisted, spread_too_wide
5. trade-level validation              -> position_limit_reached,
                                          position_size_reduced, volatility_scaled

The default response to uncertainty is no new risk. Existing positions are never
touched by this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.config import Settings
from traderstack.features import AssetFeatureVector
from traderstack.killswitch import KillSwitch
from traderstack.models import PortfolioSnapshot, RiskDecision, RiskResult, TradeProposal

# Settings fields that constitute risk policy. Any change to one of these
# changes the derived policy version, so every audit record shows exactly which
# limits were in force when a decision was made.
RISK_LIMIT_FIELDS: tuple[str, ...] = (
    "mvp_assets",
    "max_position_pct",
    "max_daily_loss_pct",
    "max_account_drawdown_pct",
    "max_open_positions",
    "min_cash_reserve_pct",
    "max_gross_exposure_pct",
    "max_portfolio_state_age_seconds",
    "risk_max_spread_bps",
    "volatility_sizing_enabled",
    "target_volatility",
    "strategy_max_consecutive_losses",
    "strategy_drawdown_window",
    "strategy_max_rolling_drawdown_pct",
    "strategy_breaker_cooldown_seconds",
    "kill_switch",
    "kill_switch_file",
    "kill_switch_redis_key",
    "kill_switch_redis_enabled",
)


def risk_limits(settings: Settings) -> dict[str, Any]:
    """The risk-relevant settings in force, as a plain serialisable mapping."""

    return {name: getattr(settings, name) for name in RISK_LIMIT_FIELDS}


def risk_limits_hash(settings: Settings) -> str:
    payload = json.dumps(risk_limits(settings), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_policy_version(settings: Settings, label: str | None = None) -> str:
    """Manual label plus a digest of every risk limit in force."""

    resolved = label or settings.risk_policy_label
    return f"{resolved}+{risk_limits_hash(settings)[:12]}"


@dataclass(frozen=True)
class RiskEngine:
    settings: Settings
    # Manual policy label. Defaults to Settings.risk_policy_label; the numeric
    # limits are folded into policy_version automatically.
    policy_label: str | None = None
    # --- risk plane (Epic 7) ---
    # Live operator halt. When absent the engine falls back to the static
    # settings flag, so an un-wired engine is no less safe.
    kill_switch: KillSwitch | None = None
    # Per-strategy suspension on realized underperformance.
    circuit_breaker: StrategyCircuitBreaker | None = None

    @property
    def policy_version(self) -> str:
        return derive_policy_version(self.settings, self.policy_label)

    @property
    def risk_limits(self) -> dict[str, Any]:
        return risk_limits(self.settings)

    def evaluate(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioSnapshot,
        features: AssetFeatureVector | None = None,
        *,
        now: datetime | None = None,
    ) -> RiskResult:
        reasons: list[str] = []
        moment = now or datetime.now(UTC)

        # --- 1. global halt ------------------------------------------------
        if self._halted():
            return self._result(proposal, RiskDecision.REJECT, 0, ["kill_switch_enabled"])

        # --- 2. account and portfolio limits ------------------------------
        # Stale-state shutdown: an old view of the book is inconsistent state.
        state_age = (moment - portfolio.observed_at).total_seconds()
        if state_age > self.settings.max_portfolio_state_age_seconds:
            reasons.append("stale_portfolio_state")

        daily_loss_limit = portfolio.nav_usd * self.settings.max_daily_loss_pct
        if portfolio.daily_pnl_usd <= -daily_loss_limit:
            reasons.append("daily_loss_limit_reached")

        drawdown = 1 - (portfolio.nav_usd / portfolio.peak_nav_usd)
        if drawdown >= self.settings.max_account_drawdown_pct:
            reasons.append("account_drawdown_limit_reached")

        gross_exposure = sum(portfolio.asset_exposure_usd.values())
        gross_limit = portfolio.nav_usd * self.settings.max_gross_exposure_pct
        gross_room = gross_limit - gross_exposure
        if gross_room <= 0:
            reasons.append("gross_exposure_limit")

        cash_floor = portfolio.nav_usd * self.settings.min_cash_reserve_pct
        cash_room = portfolio.cash_usd - cash_floor
        if cash_room <= 0:
            reasons.append("cash_reserve_breached")

        asset = proposal.asset.upper()
        open_positions = {
            name for name, exposure in portfolio.asset_exposure_usd.items() if exposure > 0
        }
        if asset not in open_positions and len(open_positions) >= self.settings.max_open_positions:
            reasons.append("max_positions_reached")

        # --- 3. strategy limits -------------------------------------------
        if self.circuit_breaker is not None and self.circuit_breaker.is_tripped(
            proposal.strategy_id, moment
        ):
            reasons.append("strategy_circuit_breaker")

        # --- 4. asset / venue limits --------------------------------------
        if asset not in self.settings.assets:
            reasons.append("asset_not_allowlisted")

        if features is not None and features.market.spread_bps > self.settings.risk_max_spread_bps:
            reasons.append("spread_too_wide")

        # --- 5. trade-level validation ------------------------------------
        max_notional = portfolio.nav_usd * self.settings.max_position_pct
        existing = portfolio.asset_exposure_usd.get(asset, 0.0)
        remaining = max(0.0, max_notional - existing)

        if reasons or remaining <= 0:
            if remaining <= 0:
                reasons.append("position_limit_reached")
            return self._result(proposal, RiskDecision.REJECT, 0, reasons)

        requested = proposal.requested_notional_usd
        volatility_scaled = False
        if features is not None and self.settings.volatility_sizing_enabled:
            factor = self._volatility_factor(features)
            if factor < 1.0:
                requested = requested * factor
                volatility_scaled = True

        # The position limit caps volatility sizing, and portfolio-level room
        # caps everything: the tightest constraint wins.
        approved = min(requested, remaining, gross_room, cash_room)
        if volatility_scaled:
            reasons.append("volatility_scaled")
        decision = (
            RiskDecision.ALLOW
            if approved == proposal.requested_notional_usd
            else RiskDecision.REDUCE
        )
        if decision is RiskDecision.REDUCE:
            reasons.append("position_size_reduced")
        return self._result(proposal, decision, approved, reasons)

    # --- helpers -----------------------------------------------------------

    def _halted(self) -> bool:
        if self.kill_switch is not None:
            return self.kill_switch.engaged
        return self.settings.kill_switch

    def _volatility_factor(self, features: AssetFeatureVector) -> float:
        """target / observed realized volatility, never above 1.0.

        Volatility targeting only ever *reduces* size here. Scaling a proposal up
        because volatility looks low would have the risk engine inventing risk
        nobody proposed, which the control hierarchy does not permit. An absent
        or non-positive observation carries no information, so it earns no
        scale-up either.
        """

        observed = features.market.volatility_z
        if observed <= 0:
            return 1.0
        return min(1.0, self.settings.target_volatility / observed)

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
