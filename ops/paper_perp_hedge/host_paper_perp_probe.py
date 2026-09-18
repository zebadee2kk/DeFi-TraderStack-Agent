#!/usr/bin/env python3
"""Bounded host-side paper perp feed+book probe (paper-only)."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.execution.ledger import ExecutionFill, ExecutionLedger, FeeSource
from traderstack.execution.paper_perp import PaperPerpBook, PaperPerpStatus
from traderstack.execution.paper_perp_feed import PaperPerpVenueFeed
from traderstack.killswitch import KillSwitch
from traderstack.models import Side

OUT = Path("/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_perp_hedge_soak_20260918/host_probe.json")
REPORT_SNIP = Path("/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_perp_hedge_soak_20260918/host_probe.md")


def _out(o):
    if o is None:
        return None
    return {
        "status": str(o.status),
        "reason": o.reason,
        "applied": o.applied,
        "fee_usd": o.fee_usd,
        "funding_pnl_usd": o.funding_pnl_usd,
    }


async def main() -> dict:
    started = datetime.now(UTC).isoformat()
    feed = PaperPerpVenueFeed(trading_mode="paper", venue_preference="auto")
    book = PaperPerpBook(trading_mode="paper", kill_switch=KillSwitch(settings_flag=False))
    ledger = ExecutionLedger()
    symbols = ["BTC/USD", "ETH/USD", "SOL/USD"]
    mids: dict = {}
    funding: dict = {}
    errors: list = []
    for sym in symbols:
        try:
            q = await feed.fetch_mid(sym)
            mids[sym] = None if q is None else {
                "venue": q.venue,
                "mid_usd": q.mid_usd,
                "source": q.source,
                "observed_at": q.observed_at.isoformat(),
            }
        except Exception as exc:  # noqa: BLE001
            errors.append({"op": "fetch_mid", "symbol": sym, "error": repr(exc)})
            mids[sym] = None

    hedge_outcome = None
    funding_outcome = None
    withhold_outcome = None
    pick = next((s for s, m in mids.items() if m), None)
    if pick and mids[pick]:
        asset = pick.split("/")[0]
        fill = ExecutionFill(
            fill_id="probe-fill-1",
            order_id="probe-decision-1",
            asset=asset,
            side=Side.BUY,
            quantity=0.001,
            price_usd=float(mids[pick]["mid_usd"]),
            fee_usd=0.0,
            fee_source=FeeSource.MODELLED,
        )
        hedge_outcome = book.maybe_hedge_spot_fill(
            fill,
            perp_mid_usd=float(mids[pick]["mid_usd"]),
            decision_id="probe-decision-1",
            ledger=ledger,
        )
        venue = mids[pick]["venue"]
        since = datetime.now(UTC) - timedelta(hours=24)
        try:
            tape = await feed.fetch_funding_since(pick, venue=venue, since=since)
            funding[pick] = {
                "venue": tape.venue,
                "n_settlements": len(tape.settlements),
                "source": tape.source,
                "sample": [
                    {"ts": ts.isoformat(), "rate": rate}
                    for ts, rate in tape.settlements[:3]
                ],
            }
            if tape.settlements:
                funding_outcome = book.apply_funding(
                    tape.settlements,
                    asset=asset,
                    mark_usd=float(mids[pick]["mid_usd"]),
                )
        except Exception as exc:  # noqa: BLE001
            errors.append({"op": "fetch_funding", "symbol": pick, "error": repr(exc)})

        withheld_book = PaperPerpBook(
            trading_mode="paper", kill_switch=KillSwitch(settings_flag=True)
        )
        other = "ETH" if asset != "ETH" else "BTC"
        mid2 = mids.get(f"{other}/USD") or mids[pick]
        fill2 = ExecutionFill(
            fill_id="probe-fill-2",
            order_id="probe-decision-2",
            asset=other,
            side=Side.BUY,
            quantity=0.001,
            price_usd=float(mid2["mid_usd"]),
            fee_usd=0.0,
            fee_source=FeeSource.MODELLED,
        )
        withhold_outcome = withheld_book.maybe_hedge_spot_fill(
            fill2,
            perp_mid_usd=float(mid2["mid_usd"]),
            decision_id="probe-decision-2",
        )

    result = {
        "started_utc": started,
        "ended_utc": datetime.now(UTC).isoformat(),
        "trading_mode": "paper",
        "paper_promote_flipped": False,
        "mids": mids,
        "funding": funding,
        "hedge_outcome": _out(hedge_outcome),
        "funding_outcome": _out(funding_outcome),
        "withhold_outcome": _out(withhold_outcome),
        "withhold_expected": str(PaperPerpStatus.WITHHELD),
        "positions": {
            k: {
                "side": str(v.side),
                "qty": v.quantity,
                "entry": v.entry_price_usd,
                "funding_pnl_usd": v.funding_pnl_usd,
            }
            for k, v in book.positions.items()
        },
        "errors": errors,
        "honesty": "PAPER_PROBE_ONLY_NOT_LIVE_PNL_NOT_PROMOTE",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# Host paper-perp probe (complement to docker soak)",
        "",
        "**PAPER ONLY. Not live PnL. Not a promote claim.**",
        "",
        f"- started: `{result['started_utc']}`",
        f"- ended: `{result['ended_utc']}`",
        f"- hedge: `{result['hedge_outcome']}`",
        f"- funding_apply: `{result['funding_outcome']}`",
        f"- kill_withhold: `{result['withhold_outcome']}`",
        "- mid venues: "
        + ", ".join(f"{s}-> {(m or {}).get('venue')}" for s, m in mids.items()),
        f"- errors: {len(errors)}",
        "",
        "Raw: `var/ops/_perp_hedge_soak_20260918/host_probe.json`",
        "",
    ]
    REPORT_SNIP.write_text("\n".join(lines) + "\n")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    asyncio.run(main())
