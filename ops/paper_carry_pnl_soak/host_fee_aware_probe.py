#!/usr/bin/env python3
"""Host fee-aware paper PnL soak for carry diagnostic (paper-only).

Opens carry_hedged_sign diagnostic hedges, samples explicit HL/HTX mids
over a wall-clock window, applies any new same-venue funding prints, and
harvests fee-aware paper PnL components. Never invents mids, funding, or
PnL. Does not flip PAPER_PROMOTE_*. .env diagnostic flags stay false;
probe uses Settings.model_copy only.
"""

from __future__ import annotations

import argparse
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
from traderstack.market.models import MarketSource, MarketTick
from traderstack.pipeline import PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService

DEFAULT_OUT = Path("var/ops/_carry_fee_aware_pnl_soak_20260926/host_fee_aware_probe.json")


class FakeRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result

    async def run_once(self, symbol, portfolio, *, submit=False):
        return self.result


def _promote_defaults(settings: Settings) -> dict[str, bool]:
    return {
        "paper_perp_hedge": settings.paper_perp_hedge,
        "paper_carry_hedge_diagnostic": settings.paper_carry_hedge_diagnostic,
        "paper_promote_ema_9_21": settings.paper_promote_ema_9_21,
        "paper_promote_ema_9_21_adx15": settings.paper_promote_ema_9_21_adx15,
        "paper_promote_searched_strategies": settings.paper_promote_searched_strategies,
        "paper_garch_size": settings.paper_garch_size,
    }


async def _collect_marks(
    feed: PaperPerpVenueFeed,
    symbols: tuple[str, ...],
    venues: dict[str, str],
) -> dict[str, float]:
    marks: dict[str, float] = {}
    for symbol in symbols:
        asset = symbol.split("/", 1)[0].upper()
        try:
            quote = await feed.fetch_mid(symbol)
        except Exception as exc:  # noqa: BLE001 - skip, never invent
            # Skip-not-invent: missing mid excludes the asset from fee-aware PnL.
            print(f"mark_fetch_skipped symbol={symbol} error={type(exc).__name__}")
            continue
        if quote is None or quote.mid_usd <= 0:
            continue
        expected = venues.get(asset)
        if expected is not None and quote.venue != expected:
            continue
        marks[asset] = float(quote.mid_usd)
    return marks


async def run_soak(
    *,
    duration_seconds: int,
    sample_every_seconds: int,
    out_path: Path,
) -> dict:
    defaults = Settings()
    defaults_snapshot = _promote_defaults(defaults)
    settings = defaults.model_copy(
        update={"paper_perp_hedge": True, "paper_carry_hedge_diagnostic": True}
    )
    book = PaperPerpBook(
        trading_mode="paper",
        paper_fee_bps=defaults.paper_fee_bps,
        paper_slippage_bps=defaults.paper_slippage_bps,
        kill_switch=KillSwitch(settings_flag=False),
    )
    feed = PaperPerpVenueFeed(trading_mode="paper", venue_preference="auto")
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

    errors: list[dict] = []
    started = datetime.now(UTC)
    for sym in ("BTC/USD", "ETH/USD"):
        try:
            await service._maybe_open_carry_diagnostic_hedge(sym)
        except Exception as exc:  # noqa: BLE001
            errors.append({"op": "open", "symbol": sym, "error": repr(exc)})

    samples: list[dict] = []
    while True:
        elapsed = int((datetime.now(UTC) - started).total_seconds())
        for sym in ("BTC/USD", "ETH/USD"):
            try:
                await service._maybe_apply_paper_perp_funding(sym)
            except Exception as exc:  # noqa: BLE001
                errors.append({"op": "funding", "symbol": sym, "error": repr(exc)})
        marks = await _collect_marks(
            feed, ("BTC/USD", "ETH/USD"), dict(service._paper_perp_venue)
        )
        snap = book.harvest_fee_aware_paper_pnl(marks)
        samples.append(
            {
                "utc": datetime.now(UTC).isoformat(),
                "elapsed_s": elapsed,
                "marks": marks,
                "funding_pnl_usd": snap.funding_pnl_usd,
                "unrealized_mtm_usd": snap.unrealized_mtm_usd,
                "fees_usd": snap.fees_usd,
                "fee_aware_paper_pnl_usd": snap.fee_aware_paper_pnl_usd,
                "marks_incomplete": snap.marks_incomplete,
                "marked_assets": list(snap.marked_assets),
                "skipped_assets": list(snap.skipped_assets),
                "funding_prints_applied": book.funding_prints_applied,
                "hedge_count": len(book.positions),
            }
        )
        if elapsed >= duration_seconds:
            break
        await asyncio.sleep(sample_every_seconds)

    ended = datetime.now(UTC)
    final_marks = samples[-1]["marks"] if samples else {}
    final_snap = book.harvest_fee_aware_paper_pnl(final_marks)
    nav_after = spot.snapshot().nav_usd
    post_defaults = _promote_defaults(Settings())

    if final_snap.fee_aware_paper_pnl_usd is None:
        fee_aware_status: float | str = "UNAVAILABLE"
    else:
        fee_aware_status = final_snap.fee_aware_paper_pnl_usd

    out = {
        "started_utc": started.isoformat(),
        "ended_utc": ended.isoformat(),
        "duration_seconds_requested": duration_seconds,
        "duration_seconds_observed": int((ended - started).total_seconds()),
        "sample_every_seconds": sample_every_seconds,
        "sample_count": len(samples),
        "signal": CARRY_DIAGNOSTIC_SIGNAL,
        "defaults_before": defaults_snapshot,
        "defaults_after": post_defaults,
        "paper_fee_bps": defaults.paper_fee_bps,
        "paper_slippage_bps": defaults.paper_slippage_bps,
        "paper_fee_tier": defaults.paper_fee_tier,
        "fee_assumptions": {
            "spot_if_booked": (
                "kraken_pro_spot_t1 taker 80 bps + 5 slip "
                "(NOT charged; diagnostic spot not booked)"
            ),
            "perp_open": (
                f"PAPER_FEE_BPS={defaults.paper_fee_bps} + "
                f"PAPER_SLIPPAGE_BPS={defaults.paper_slippage_bps}"
            ),
            "maker_rebate": "not assumed",
        },
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
        "hedge_count": len(book.positions),
        "funding_prints_applied": book.funding_prints_applied,
        "total_fees_usd": book.total_fees_usd,
        "final_marks": final_marks,
        "final_funding_pnl_usd": final_snap.funding_pnl_usd,
        "final_unrealized_mtm_usd": final_snap.unrealized_mtm_usd,
        "final_fee_aware_paper_pnl_usd": fee_aware_status,
        "final_marks_incomplete": final_snap.marks_incomplete,
        "nav_before": nav_before,
        "nav_after": nav_after,
        "samples": samples,
        "errors": errors,
        "honesty": "PAPER_PROBE_ONLY_NOT_LIVE_PNL_NOT_PROMOTE",
        "docker_note": (
            "compose app was restarting (postgres DNS); host probe is the soak surface"
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2) + "\n")
    summary = {k: v for k, v in out.items() if k != "samples"}
    print(json.dumps(summary, indent=2))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--sample-every-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    asyncio.run(
        run_soak(
            duration_seconds=args.duration_seconds,
            sample_every_seconds=args.sample_every_seconds,
            out_path=args.out,
        )
    )


if __name__ == "__main__":
    main()
