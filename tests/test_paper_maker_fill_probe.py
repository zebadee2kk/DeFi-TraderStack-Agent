"""Maker fill-rate probe honesty: simulator fills immediately => INVALID."""

from __future__ import annotations

import time

from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.paper_fill import PaperFillSimulator, PaperFillStatus
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent
from traderstack.portfolio import InMemoryPortfolioBook


def test_paper_simulator_always_fills_immediately_invalid_for_maker() -> None:
    """Honesty gate: sync taker fills cannot evidence maker fill-rate."""
    simulator = PaperFillSimulator(paper_fee_bps=80.0, paper_slippage_bps=5.0)
    book = InMemoryPortfolioBook(starting_nav_usd=100_000.0)
    ledger = ExecutionLedger()
    latencies: list[float] = []
    for i in range(8):
        intent = PaperOrderIntent(
            decision_id=f"maker-honesty-{i}",
            asset="BTC",
            side=Side.BUY,
            notional_usd=500.0,
        )
        t0 = time.perf_counter()
        outcome = simulator.apply(intent, mid_usd=20_000.0, ledger=ledger, portfolio=book)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        assert outcome.status is PaperFillStatus.FILLED
    assert max(latencies) < 50.0
    # No cancel / resting API on PaperFillSimulator — maker evidence INVALID.
    assert not hasattr(PaperFillSimulator, "place_post_only")
    assert not hasattr(PaperFillSimulator, "cancel")
