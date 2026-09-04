"""``traderstack-trace`` — print the decision-to-fill trace for one decision.

A thin, read-only console entrypoint over
``PostgresRuntimeEventStore.decision_trace`` (Epic 9's "decision-to-fill trace
view" backlog item, expressed as a query rather than a UI): every persisted
runtime event whose proposal or paper order carried the given decision_id,
printed in chronological order.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from traderstack.config import Settings
from traderstack.eventing import PostgresRuntimeEventStore
from traderstack.runtime import RuntimeResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print the ordered runtime-event trace for one decision_id"
    )
    parser.add_argument("decision_id", help="the TradeProposal.decision_id (UUID) to trace")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="also print the N most recent events for the decision's symbol, for context",
    )
    return parser


def render_event(index: int, result: RuntimeResult) -> str:
    outcome = "accepted" if result.pipeline.accepted_market_data else "rejected"
    risk_decision = (
        result.pipeline.risk_result.decision.value if result.pipeline.risk_result else None
    )
    lines = [
        f"[{index}] {result.tick.observed_at.isoformat()}  {result.tick.symbol}  outcome={outcome}",
    ]
    if result.pipeline.rejection_reasons:
        lines.append(f"      rejection_reasons={result.pipeline.rejection_reasons}")
    if result.pipeline.proposal is not None:
        proposal = result.pipeline.proposal
        lines.append(
            f"      proposal: side={proposal.side.value} "
            f"notional_usd={proposal.requested_notional_usd:.2f} confidence={proposal.confidence:.2f}"
        )
    if risk_decision is not None:
        assert result.pipeline.risk_result is not None
        lines.append(
            f"      risk: decision={risk_decision} "
            f"approved_usd={result.pipeline.risk_result.approved_notional_usd:.2f} "
            f"reasons={result.pipeline.risk_result.reasons}"
        )
    if result.pipeline.paper_order is not None:
        lines.append(f"      paper_order: {result.pipeline.paper_order.model_dump()}")
    if result.execution_receipt is not None:
        lines.append(f"      execution_receipt: {result.execution_receipt.model_dump()}")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    store = PostgresRuntimeEventStore(settings.database_url)
    try:
        events = await store.decision_trace(args.decision_id)
        if not events:
            print(f"no runtime events found for decision_id={args.decision_id}", file=sys.stderr)
            return 1
        for index, event in enumerate(events, start=1):
            print(render_event(index, event))
        if args.limit:
            symbol = events[-1].tick.symbol
            recent = await store.recent(symbol, limit=args.limit)
            print(f"\n--- {len(recent)} most recent events for {symbol} ---")
            for event in recent:
                print(
                    json.dumps(
                        {
                            "observed_at": event.tick.observed_at.isoformat(),
                            "accepted": event.pipeline.accepted_market_data,
                            "decision_id": (
                                str(event.pipeline.proposal.decision_id)
                                if event.pipeline.proposal is not None
                                else None
                            ),
                        }
                    )
                )
        return 0
    finally:
        await store.close()


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
