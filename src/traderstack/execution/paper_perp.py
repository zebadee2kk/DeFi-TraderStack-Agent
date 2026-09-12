"""Paper-only perpetual / hedge book (stub).

Minimal cash-and-carry execution plane for research. Invariants:

* ``TRADING_MODE=paper`` only — live/shadow raise ``ExecutionSafetyError``;
* kill switch withholds new hedges (default-closed);
* a hedge requires an explicit perp mid — the Kraken spot mid is not a
  substitute and is never invented;
* funding credit/debit is applied only from caller-supplied settlement
  prints (never inferred from last-trade or from funding premium);
* client order id is recorded before the simulated hedge fill;
* perp PnL stays on this book and is **not** booked into the spot
  portfolio (that would invent NAV / net the spot leg).

``PAPER_PERP_PATH_READY`` is **true** only for the cycle-wired paper
hedge+funding soak (explicit venue mid + caller-supplied settlements).
That is not a promote path: historical PIT basis is still UNAVAILABLE
and ``can_promote`` stays false. No live. Does not flip ``PAPER_PROMOTE_*``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from traderstack.execution.hummingbot import ExecutionSafetyError
from traderstack.execution.ledger import (
    ExecutionFill,
    ExecutionLedger,
    ExecutionOrder,
    FeeSource,
    OrderLifecycleState,
)
from traderstack.execution.paper_fill import adverse_fill_price_usd
from traderstack.killswitch import KillSwitch
from traderstack.models import Side

# Paper hedge+funding path is cycle-wired (venue mid + same-venue
# funding tape). Not a promote unlock — PIT basis is still missing.
PAPER_PERP_PATH_READY = True

_PAPER_PERP_ID_PREFIX = "paper-perp:"


class PaperPerpStatus(StrEnum):
    HEDGED = "paper_perp_hedged"
    FUNDING_APPLIED = "paper_perp_funding_applied"
    SKIPPED = "paper_perp_skipped"
    WITHHELD = "paper_perp_withheld"
    REJECTED = "paper_perp_rejected"
    DUPLICATE = "paper_perp_duplicate"


@dataclass(frozen=True)
class PaperPerpPosition:
    asset: str
    side: Side
    quantity: float
    entry_price_usd: float
    funding_pnl_usd: float = 0.0
    client_order_id: str = ""


@dataclass(frozen=True)
class PaperPerpOutcome:
    status: PaperPerpStatus
    reason: str | None = None
    position: PaperPerpPosition | None = None
    fee_usd: float = 0.0
    funding_pnl_usd: float = 0.0

    @property
    def applied(self) -> bool:
        return self.status in {PaperPerpStatus.HEDGED, PaperPerpStatus.FUNDING_APPLIED}


def paper_perp_client_order_id(decision_id: str, asset: str) -> str:
    return f"{_PAPER_PERP_ID_PREFIX}{decision_id}:{asset.upper()}"


def paper_perp_fill_id(client_order_id: str) -> str:
    return f"{_PAPER_PERP_ID_PREFIX}fill:{client_order_id}"


def hedge_side(spot_side: Side) -> Side:
    """Opposite perp side: long spot → short perp (cash-and-carry)."""

    return Side.SELL if spot_side is Side.BUY else Side.BUY


@dataclass
class PaperPerpBook:
    """In-process paper perp book. Separate from the spot portfolio."""

    trading_mode: str = "paper"
    paper_fee_bps: float = 10.0
    paper_slippage_bps: float = 5.0
    kill_switch: KillSwitch | None = None
    _positions: dict[str, PaperPerpPosition] = field(default_factory=dict)
    _seen_ids: set[str] = field(default_factory=set)
    _funding_prints_applied: int = 0

    def __post_init__(self) -> None:
        if self.trading_mode != "paper":
            raise ExecutionSafetyError("paper perp book cannot operate outside paper mode")
        if self.paper_fee_bps < 0:
            raise ValueError("paper_fee_bps must not be negative")
        if self.paper_slippage_bps < 0:
            raise ValueError("paper_slippage_bps must not be negative")

    @property
    def path_ready(self) -> bool:
        return PAPER_PERP_PATH_READY

    @property
    def positions(self) -> dict[str, PaperPerpPosition]:
        return dict(self._positions)

    @property
    def funding_prints_applied(self) -> int:
        return self._funding_prints_applied

    def total_funding_pnl_usd(self) -> float:
        return sum(position.funding_pnl_usd for position in self._positions.values())

    def maybe_hedge_spot_fill(
        self,
        fill: ExecutionFill,
        *,
        perp_mid_usd: float | None,
        decision_id: str,
        ledger: ExecutionLedger | None = None,
    ) -> PaperPerpOutcome:
        """Open the opposite perp against a spot paper fill.

        Requires an explicit perp mid. Passing the Kraken spot mid as
        ``perp_mid_usd`` is the caller's lie — this method will not
        substitute ``fill.price_usd`` when mid is missing.
        """

        if self.trading_mode != "paper":
            raise ExecutionSafetyError("paper perp book cannot operate outside paper mode")
        if self.kill_switch is not None and self.kill_switch.engaged:
            return PaperPerpOutcome(
                status=PaperPerpStatus.WITHHELD,
                reason="kill switch engaged; paper perp hedge withheld",
            )
        if perp_mid_usd is None or perp_mid_usd <= 0:
            return PaperPerpOutcome(
                status=PaperPerpStatus.SKIPPED,
                reason=(
                    "perp mid missing; refuse to invent from the spot fill price or from last-trade"
                ),
            )

        asset = fill.asset.upper()
        client_order_id = paper_perp_client_order_id(decision_id, asset)
        if client_order_id in self._seen_ids:
            return PaperPerpOutcome(
                status=PaperPerpStatus.DUPLICATE,
                reason=f"paper perp hedge {client_order_id} already booked",
                position=self._positions.get(asset),
            )
        if asset in self._positions:
            return PaperPerpOutcome(
                status=PaperPerpStatus.REJECTED,
                reason=f"paper perp already open for {asset}; stub is one hedge per asset",
                position=self._positions[asset],
            )

        # Ledger-backed: write the client order id before the simulated fill.
        self._seen_ids.add(client_order_id)
        side = hedge_side(fill.side)
        fill_price = adverse_fill_price_usd(side, perp_mid_usd, self.paper_slippage_bps)
        fee_usd = fill.quantity * fill_price * self.paper_fee_bps / 10_000.0
        if ledger is not None:
            existing = [
                order
                for order in ledger.orders_for_decision(decision_id)
                if (order.client_order_id or order.order_id) == client_order_id
            ]
            if existing and existing[0].state is OrderLifecycleState.FILLED:
                return PaperPerpOutcome(
                    status=PaperPerpStatus.DUPLICATE,
                    reason=f"paper perp hedge {client_order_id} already booked",
                    position=self._positions.get(asset),
                )
            if not existing:
                ledger.register_order(
                    ExecutionOrder(
                        order_id=client_order_id,
                        decision_id=decision_id,
                        asset=asset,
                        side=side,
                        requested_quantity=fill.quantity,
                        state=OrderLifecycleState.PLANNED,
                        client_order_id=client_order_id,
                    )
                )
            fill_id = paper_perp_fill_id(client_order_id)
            ledger.record_fill(
                ExecutionFill(
                    fill_id=fill_id,
                    order_id=client_order_id,
                    asset=asset,
                    side=side,
                    quantity=fill.quantity,
                    price_usd=fill_price,
                    fee_usd=fee_usd,
                    fee_source=FeeSource.MODELLED,
                )
            )

        position = PaperPerpPosition(
            asset=asset,
            side=side,
            quantity=fill.quantity,
            entry_price_usd=fill_price,
            client_order_id=client_order_id,
        )
        self._positions[asset] = position
        return PaperPerpOutcome(
            status=PaperPerpStatus.HEDGED,
            position=position,
            fee_usd=fee_usd,
        )

    def apply_funding(
        self,
        settlements: tuple[tuple[datetime, float], ...],
        *,
        asset: str,
        mark_usd: float | None = None,
    ) -> PaperPerpOutcome:
        """Credit/debit funding from supplied settlement prints only.

        Positive rate: longs pay shorts. Cash-and-carry (short perp)
        therefore receives a positive rate. Notional uses ``mark_usd``
        when supplied; otherwise entry price (documented, not a PIT
        mark). Missing mark is not invented from last-trade.
        """

        if self.trading_mode != "paper":
            raise ExecutionSafetyError("paper perp book cannot operate outside paper mode")
        if self.kill_switch is not None and self.kill_switch.engaged:
            return PaperPerpOutcome(
                status=PaperPerpStatus.WITHHELD,
                reason="kill switch engaged; paper perp funding withheld",
            )
        key = asset.upper()
        position = self._positions.get(key)
        if position is None:
            return PaperPerpOutcome(
                status=PaperPerpStatus.SKIPPED,
                reason=f"no paper perp position for {key}",
            )
        if not settlements:
            return PaperPerpOutcome(
                status=PaperPerpStatus.SKIPPED,
                reason="no funding settlements supplied; refuse to invent a rate",
                position=position,
            )
        if mark_usd is not None and mark_usd > 0:
            notional_price = mark_usd
        else:
            notional_price = position.entry_price_usd
        signed = 1.0 if position.side is Side.SELL else -1.0
        pnl = 0.0
        applied = 0
        for _ts, rate in settlements:
            pnl += signed * float(rate) * position.quantity * notional_price
            applied += 1
        updated = PaperPerpPosition(
            asset=position.asset,
            side=position.side,
            quantity=position.quantity,
            entry_price_usd=position.entry_price_usd,
            funding_pnl_usd=position.funding_pnl_usd + pnl,
            client_order_id=position.client_order_id,
        )
        self._positions[key] = updated
        self._funding_prints_applied += applied
        return PaperPerpOutcome(
            status=PaperPerpStatus.FUNDING_APPLIED,
            position=updated,
            funding_pnl_usd=pnl,
        )
