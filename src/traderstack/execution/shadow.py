"""Shadow-live recorder (Roadmap Phase 7).

Plans and persists the order the paper path *would* have submitted, using the
same ``ExecutionPlanner`` constraints, without calling Hummingbot, broadcasting
an on-chain swap, or applying a fill to the portfolio.

The ledger is a separate append-only JSONL from the venue ``ExecutionLedger``
so a shadow run can never be mistaken for paper fills at the persistence layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from traderstack.execution.planner import ExecutionPlanner, ExecutionPlanRejected
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent

SHADOW_RECORDED = "shadow_recorded"
SHADOW_PLAN_REJECTED = "shadow_plan_rejected"
SHADOW_DUPLICATE = "shadow_duplicate"


class ShadowIntent(BaseModel):
    """One would-have-been submission, durable and distinguishable from paper."""

    recorded_at: datetime
    decision_id: str
    asset: str
    side: Side
    execution_price_usd: float = Field(gt=0)
    reference_price_usd: float = Field(gt=0)
    status: str
    trading_mode: str = "shadow"
    client_order_id: str | None = None
    correlation_id: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    notional_usd: float | None = Field(default=None, gt=0)
    reason: str | None = None


class ShadowLedger:
    """Append-only JSONL of shadow intents, keyed by decision id."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.records: list[ShadowIntent] = []
        self._decision_ids: set[str] = set()
        self._resumed = False

    def _resume(self) -> None:
        if self._resumed:
            return
        self._resumed = True
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                intent = ShadowIntent.model_validate_json(line)
                self.records.append(intent)
                self._decision_ids.add(intent.decision_id)

    def has_decision(self, decision_id: str) -> bool:
        self._resume()
        return decision_id in self._decision_ids

    def append(self, intent: ShadowIntent) -> ShadowIntent:
        self._resume()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(intent.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        self.records.append(intent)
        self._decision_ids.add(intent.decision_id)
        return intent


@dataclass
class ShadowRecorder:
    """Plan a paper intent and persist it as a shadow record. Never talks to a venue."""

    ledger: ShadowLedger
    planner: ExecutionPlanner = field(default_factory=ExecutionPlanner)

    async def record(
        self,
        intent: PaperOrderIntent,
        *,
        execution_price_usd: float,
        reference_price_usd: float,
        now: datetime | None = None,
    ) -> ShadowIntent:
        recorded_at = now or datetime.now(UTC)
        if self.ledger.has_decision(intent.decision_id):
            return ShadowIntent(
                recorded_at=recorded_at,
                decision_id=intent.decision_id,
                asset=intent.asset.upper(),
                side=intent.side,
                execution_price_usd=execution_price_usd,
                reference_price_usd=reference_price_usd,
                status=SHADOW_DUPLICATE,
                reason=f"decision {intent.decision_id} already has a shadow record",
            )

        try:
            plan = self.planner.plan(
                intent,
                execution_price_usd=execution_price_usd,
                reference_price_usd=reference_price_usd,
            )
        except ExecutionPlanRejected as exc:
            return self.ledger.append(
                ShadowIntent(
                    recorded_at=recorded_at,
                    decision_id=intent.decision_id,
                    asset=intent.asset.upper(),
                    side=intent.side,
                    execution_price_usd=execution_price_usd,
                    reference_price_usd=reference_price_usd,
                    status=SHADOW_PLAN_REJECTED,
                    reason=exc.reason,
                )
            )

        return self.ledger.append(
            ShadowIntent(
                recorded_at=recorded_at,
                decision_id=plan.decision_id,
                asset=plan.asset,
                side=plan.side,
                execution_price_usd=plan.execution_price_usd,
                reference_price_usd=plan.reference_price_usd,
                status=SHADOW_RECORDED,
                client_order_id=plan.client_order_id,
                correlation_id=plan.correlation_id,
                quantity=plan.quantity,
                notional_usd=plan.notional_usd,
            )
        )
