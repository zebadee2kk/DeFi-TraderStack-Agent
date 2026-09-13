"""``traderstack-verify-audit``: verify the risk-audit chain against its anchors (#68).

`verify_chain` alone proves a trail is internally consistent — no edited,
removed or reordered line. It cannot prove the file was never regenerated from
genesis, because the file is its own only root of trust. This command adds that
second half: it cross-checks the trail against the chain heads published
outside it, and reports the sequence number where they disagree.

Offline and read-only. Nothing here can change a decision, a limit, or the
trail itself. Exit codes are meant for an operator's cron:

* ``0`` — chain intact *and* every anchor matches;
* ``1`` — verification failed (edited, truncated, or rewritten);
* ``2`` — could not run (no trail at the given path).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from traderstack.audit_anchor import (
    AnchorVerification,
    AuditAnchor,
    JsonlAuditAnchorStore,
    verify_with_anchors,
)
from traderstack.risk_audit import verify_chain


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a risk-audit JSONL chain and cross-check it against the "
            "chain heads anchored outside the file, so a whole-file rewrite "
            "is detectable rather than self-consistent."
        )
    )
    parser.add_argument("--audit-path", type=Path, default=Path("var/audit/risk.jsonl"))
    parser.add_argument(
        "--anchor-path",
        type=Path,
        default=Path("var/audit/anchors.jsonl"),
        help="local anchor log to check against",
    )
    parser.add_argument(
        "--allow-unanchored",
        action="store_true",
        help=(
            "treat an intact chain with no anchors as a pass. Off by default: "
            "an attacker who can rewrite the trail can usually delete a local "
            "anchor log too, so 'no anchors' is not evidence of integrity."
        ),
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of a summary")
    return parser


def _load_anchors(path: Path) -> list[AuditAnchor]:
    store = JsonlAuditAnchorStore(path)
    return asyncio.run(store.anchors())


def _render(verification: AnchorVerification) -> str:
    lines = [
        (
            f"chain:   {'intact' if verification.chain.valid else 'BROKEN'} "
            f"({verification.chain.records} record(s))"
        ),
        f"anchors: {verification.anchors_checked} checked",
        f"result:  {'OK' if verification.valid else 'FAILED'}",
    ]
    if verification.error:
        lines.append(f"error:   {verification.error}")
    if verification.diverged_at_sequence is not None:
        lines.append(f"diverged at sequence: {verification.diverged_at_sequence}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.audit_path.exists():
        print(f"{args.audit_path}: no risk audit trail found")
        return 2

    anchors = _load_anchors(args.anchor_path)
    if not anchors and args.allow_unanchored:
        chain = verify_chain(args.audit_path)
        verification = AnchorVerification(
            valid=chain.valid,
            chain=chain,
            anchors_checked=0,
            error=chain.error,
            diverged_at_sequence=chain.first_invalid_sequence,
        )
    else:
        verification = verify_with_anchors(args.audit_path, anchors)

    if args.json:
        print(json.dumps(verification.model_dump(mode="json"), indent=2, default=str))
    else:
        print(_render(verification))
    return 0 if verification.valid else 1


if __name__ == "__main__":  # pragma: no cover - console script entry point
    raise SystemExit(main())
