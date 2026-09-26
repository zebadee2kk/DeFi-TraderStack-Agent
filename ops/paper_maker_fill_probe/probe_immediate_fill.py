#!/usr/bin/env python3
"""Minimal paper maker / post-only fill-rate probe.

Places post-only-*style* paper intents through PaperFillSimulator and records
whether fills are immediate. Honesty: if every apply() returns FILLED in the
same call (no resting/cancel path), maker evidence is INVALID / UNAVAILABLE.

Never flips PAPER_PROMOTE_*. Paper only.
"""

from __future__ import annotations

import ast
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.paper_fill import PaperFillSimulator, PaperFillStatus
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent
from traderstack.portfolio import InMemoryPortfolioBook

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def _post_only_symbols_in_src() -> list[str]:
    """Return source paths under src/ that mention post-only order plumbing."""
    hits: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "post_only" in text or "PostOnly" in text or "post-only" in text.lower():
            # fee_tiers / config comments mention post-only as ABSENT — exclude
            # pure documentation comments by requiring an assignment/def/class.
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and (
                    "post_only" in node.name.lower() or "postonly" in node.name.lower()
                ):
                    hits.append(str(path.relative_to(REPO_ROOT)))
                    break
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        name = getattr(target, "id", None) or getattr(target, "attr", None)
                        if name and "post_only" in name.lower():
                            hits.append(str(path.relative_to(REPO_ROOT)))
                            break
    return sorted(set(hits))


def run_probe(*, n_orders: int = 20, mid_usd: float = 20_000.0) -> dict:
    post_only_hits = _post_only_symbols_in_src()
    simulator = PaperFillSimulator(paper_fee_bps=80.0, paper_slippage_bps=5.0, trading_mode="paper")
    book = InMemoryPortfolioBook(starting_nav_usd=100_000.0)
    ledger = ExecutionLedger()

    fills = 0
    cancels = 0
    rejected = 0
    latencies_ms: list[float] = []

    # BUY-only: isolate fill timing. SELL short-rejects are not maker cancels.
    for i in range(n_orders):
        intent = PaperOrderIntent(
            decision_id=f"maker-probe-{i}",
            asset="BTC",
            side=Side.BUY,
            notional_usd=500.0,
        )
        t0 = time.perf_counter()
        outcome = simulator.apply(intent, mid_usd=mid_usd, ledger=ledger, portfolio=book)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if outcome.status is PaperFillStatus.FILLED:
            fills += 1
            latencies_ms.append(dt_ms)
        elif outcome.status in {PaperFillStatus.REJECTED, PaperFillStatus.PLAN_REJECTED}:
            rejected += 1
        else:
            # No CANCELLED status exists on PaperFillSimulator.
            rejected += 1

    max_ttf = max(latencies_ms) if latencies_ms else None
    # Immediate = every FILLED outcome completed inside synchronous apply().
    # A real maker queue would leave orders open across cycles / wall time.
    always_immediate = (
        fills > 0 and fills == n_orders and cancels == 0 and max_ttf is not None and max_ttf < 50.0
    )
    post_only_exists = bool(post_only_hits)
    has_cancel_api = hasattr(PaperFillSimulator, "cancel") or hasattr(
        PaperFillSimulator, "place_post_only"
    )

    if not post_only_exists and not has_cancel_api and always_immediate:
        status = "INVALID"
        fill_rate: float | str = "UNAVAILABLE"
        honesty = (
            "PaperFillSimulator fills every intent synchronously at mid ± adverse "
            "slippage (taker-style). No post-only / resting / cancel path exists "
            "(#73 not implemented). Immediate 100% fill is INVALID for maker "
            "fill-rate evidence. Do not assume maker fees. Stop."
        )
    elif post_only_exists and not always_immediate:
        status = "VALID"
        fill_rate = fills / n_orders if n_orders else "UNAVAILABLE"
        honesty = "post-only path present; record measured fill_rate"
    else:
        status = "UNAVAILABLE"
        fill_rate = "UNAVAILABLE"
        honesty = "Cannot produce honest maker fill-rate evidence from this paper path."

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "post_only_path_exists": post_only_exists,
        "post_only_code_hits": post_only_hits,
        "orders_attempted": n_orders,
        "fills": fills,
        "cancels": cancels,
        "rejected": rejected,
        "time_to_fill_ms_max": max_ttf,
        "time_to_fill_ms_mean": (sum(latencies_ms) / len(latencies_ms) if latencies_ms else None),
        "always_immediate_sync_fills": always_immediate,
        "maker_evidence_status": status,
        "fill_rate": fill_rate,
        "paper_promote_flipped": False,
        "honesty": honesty,
        "bounded_window_note": (
            "≤2h soak not required: simulator has no resting queue, so wall-clock "
            "cannot create maker fill vs cancel observations."
        ),
    }


def render_markdown(result: dict) -> str:
    lines = [
        "# Paper maker / post-only fill-rate probe (2026-09-26)",
        "",
        f"Generated: `{result['generated_at']}`",
        "",
        f"**maker_evidence_status: `{result['maker_evidence_status']}`**",
        f"**fill_rate: `{result['fill_rate']}`**",
        "",
        "## Measurement",
        "",
        f"- post_only_path_exists: `{result['post_only_path_exists']}`",
        f"- post_only_code_hits: `{result['post_only_code_hits']}`",
        f"- orders_attempted: `{result['orders_attempted']}`",
        f"- fills: `{result['fills']}`",
        f"- cancels: `{result['cancels']}`",
        f"- rejected: `{result['rejected']}`",
        f"- time_to_fill_ms_max: `{result['time_to_fill_ms_max']}`",
        f"- time_to_fill_ms_mean: `{result['time_to_fill_ms_mean']}`",
        f"- always_immediate_sync_fills: `{result['always_immediate_sync_fills']}`",
        f"- PAPER_PROMOTE_* flipped: `{result['paper_promote_flipped']}`",
        "",
        "## Honesty",
        "",
        result["honesty"],
        "",
        result["bounded_window_note"],
        "",
        "## Decision",
        "",
        (
            "Maker/rebate path remains **blocked**. Do not score dual-prints at "
            "maker bps. No `PAPER_PROMOTE_*` changes."
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    result = run_probe()
    out_json = REPO_ROOT / "var/ops/paper_maker_fill_probe_20260926.json"
    out_md = REPO_ROOT / "docs/artifacts/ops/paper-maker-post-only-fill-rate-probe-2026-09-26.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(result), encoding="utf-8")
    print(
        f"maker_evidence_status={result['maker_evidence_status']} "
        f"fill_rate={result['fill_rate']} wrote {out_md}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
