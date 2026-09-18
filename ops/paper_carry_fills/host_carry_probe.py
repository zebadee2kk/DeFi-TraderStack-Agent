#!/usr/bin/env python3
"""Host probe: carry diagnostic path with public HL mid+funding (paper-only)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.paper_perp import (
    CARRY_DIAGNOSTIC_SIGNAL,
    PaperPerpBook,
)
from traderstack.execution.paper_perp_feed import PaperPerpVenueFeed
from traderstack.killswitch import KillSwitch
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.runtime import RuntimeResult
from traderstack.market.models import MarketSource, MarketTick
from traderstack.pipeline import PipelineResult
from traderstack.service import ContinuousPaperService

OUT = Path("/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_carry_fills_soak_20260918/host_carry_probe.json")


class FakeRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result

    async def run_once(self, symbol, portfolio, *, submit=False):
        return self.result


async def main() -> dict:
    settings = Settings().model_copy(
        update={"paper_perp_hedge": True, "paper_carry_hedge_diagnostic": True}
    )
    # Prove defaults remain false on a fresh Settings()
    defaults = Settings()
    feed = PaperPerpVenueFeed(trading_mode="paper", venue_preference="auto")
    book = PaperPerpBook(trading_mode="paper", kill_switch=KillSwitch(settings_flag=False))
    spot = InMemoryPortfolioBook(starting_nav_usd=10_000)
    nav_before = spot.snapshot().nav_usd
    result = RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=1.0,
            ask=1.0,
            last=1.0,
        ),
        references=[],
        pipeline=PipelineResult(accepted_market_data=True),
        trading_mode="paper",
    )
    service = ContinuousPaperService(
        runtime=FakeRuntime(result),  # type: ignore[arg-type]
        portfolio=spot,
        symbols=("BTC/USD", "ETH/USD"),
        execution_ledger=ExecutionLedger(),
        settings=settings,
        paper_perp_book=book,
        paper_perp_feed=feed,
    )
    errors = []
    for sym in ("BTC/USD", "ETH/USD"):
        try:
            await service._maybe_open_carry_diagnostic_hedge(sym)
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": sym, "error": repr(exc)})
    # funding apply if positions open
    for sym in ("BTC/USD", "ETH/USD"):
        try:
            await service._maybe_apply_paper_perp_funding(sym)
        except Exception as exc:  # noqa: BLE001
            errors.append({"op": "funding", "symbol": sym, "error": repr(exc)})

    out = {
        "started_utc": datetime.now(UTC).isoformat(),
        "signal": CARRY_DIAGNOSTIC_SIGNAL,
        "defaults_paper_carry_hedge_diagnostic": defaults.paper_carry_hedge_diagnostic,
        "defaults_paper_perp_hedge": defaults.paper_perp_hedge,
        "defaults_promote_ema": defaults.paper_promote_ema_9_21,
        "defaults_promote_adx": defaults.paper_promote_ema_9_21_adx15,
        "defaults_promote_searched": defaults.paper_promote_searched_strategies,
        "positions": {
            k: {
                "side": str(v.side),
                "qty": v.quantity,
                "entry": v.entry_price_usd,
                "funding_pnl_usd": v.funding_pnl_usd,
            }
            for k, v in book.positions.items()
        },
        "venues": dict(service._paper_perp_venue),
        "nav_before": nav_before,
        "nav_after": spot.snapshot().nav_usd,
        "hedge_count": len(book.positions),
        "errors": errors,
        "honesty": "PAPER_PROBE_ONLY_NOT_LIVE_PNL_NOT_PROMOTE",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    asyncio.run(main())
