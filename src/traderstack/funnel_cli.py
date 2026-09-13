"""``traderstack-opportunity-funnel``: zero-trade diagnosis for a finished run (#131).

Rebuilds the opportunity funnel from the runtime audit JSONL a paper run
wrote (``JsonlAuditSink``) and, optionally, the execution ledger, so a
24-hour ``traderstack-paper`` window can be diagnosed after the fact: which
gate stopped most cycles, with exact reason counts, and whether the answer
is "no opportunity", "opportunity rejected" or "fill unavailable".

Offline and read-only. Nothing here can change a decision or a limit.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from traderstack.execution.ledger import ExecutionLedger, ExecutionLedgerState
from traderstack.opportunity_funnel import funnel_from_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild the zero-trade opportunity funnel from a run's audit/runtime.jsonl: "
            "cycles -> valid market data -> signal -> pre-trade -> risk -> meta-agent "
            "-> planner -> fill, with the nearest blocking gate and reason counts."
        )
    )
    parser.add_argument("--audit-path", type=Path, default=Path("var/audit/runtime.jsonl"))
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=Path("var/state/execution_ledger.json"),
        help="execution ledger to join venue fills from (skipped when missing)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="also write the JSON funnel report to this path",
    )
    return parser


def load_ledger(path: Path) -> ExecutionLedger | None:
    if not path.exists():
        return None
    payload = path.read_text(encoding="utf-8")
    if not payload.strip():
        return None
    return ExecutionLedger.from_state(ExecutionLedgerState.model_validate_json(payload))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.audit_path.exists():
        print(f"{args.audit_path}: no runtime audit trail found")
        return 2
    funnel = funnel_from_audit(args.audit_path, ledger=load_ledger(args.ledger_path))
    report = funnel.snapshot()
    payload = json.dumps(report.model_dump(mode="json"), indent=2, default=str)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    if args.json:
        print(payload)
    else:
        print(report.render())
        if funnel.skipped_lines:
            print(f"\n({funnel.skipped_lines} unreadable audit line(s) skipped)")
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
