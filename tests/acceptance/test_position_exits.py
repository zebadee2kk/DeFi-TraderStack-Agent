"""Acceptance drills: deterministic exits against ContinuousPaperService."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta  # --- protective exit sizing (#130) ---

import pytest

from traderstack.models import RiskDecision, Side

pytestmark = pytest.mark.asyncio

SYMBOL = "BTC/USD"


def _seed_losing_long(drill, *, premium: float = 0.10) -> float:
    """Open a long above the current synthetic mark so a 2% stop is already hit."""

    mark = drill.market.last(SYMBOL)
    entry = mark * (1.0 + premium)
    quantity = 0.05
    drill.portfolio.apply_fill("BTC", Side.BUY, quantity=quantity, price_usd=entry)
    drill.portfolio.mark("BTC", entry)
    return entry


async def test_stop_loss_reaches_the_ledger_and_the_risk_audit(harness) -> None:
    drill = await harness(
        settings_overrides={
            "exit_stop_loss_pct": 0.02,
            "exit_take_profit_pct": 0.0,
            "exit_trailing_stop_pct": 0.0,
            "exit_time_stop_bars": 0,
            "exit_on_thesis_invalidation": False,
        }
    )
    _seed_losing_long(drill)

    result = await drill.cycle()
    assert result is not None
    assert result.pipeline.exit_reason == "exit_stop_loss"
    assert result.pipeline.proposal is not None
    assert result.pipeline.proposal.strategy_id == "exit-stop_loss"
    assert result.pipeline.proposal.side is Side.SELL
    assert result.pipeline.proposal.signal_ids == ["exit_stop_loss"]
    assert result.pipeline.risk_result is not None
    assert result.pipeline.risk_result.decision in {RiskDecision.ALLOW, RiskDecision.REDUCE}
    assert result.pipeline.paper_order is not None
    assert result.pipeline.paper_order.side is Side.SELL
    assert result.pipeline.risk_result.approved_notional_usd == pytest.approx(
        result.pipeline.paper_order.notional_usd
    )
    assert (
        result.pipeline.risk_result.approved_notional_usd
        <= result.pipeline.proposal.requested_notional_usd + 1e-9
    )

    assert drill.ledger.has_order_for_decision(result.pipeline.paper_order.decision_id)
    records = [
        json.loads(line)
        for line in drill.risk_audit.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records
    latest = records[-1]
    proposal = latest.get("proposal") or {}
    assert proposal.get("strategy_id") == "exit-stop_loss"
    assert "exit_stop_loss" in (proposal.get("signal_ids") or [])


async def test_take_profit_emits_a_reducing_sell(harness) -> None:
    drill = await harness(
        settings_overrides={
            "exit_stop_loss_pct": 0.0,
            "exit_take_profit_pct": 0.03,
            "exit_trailing_stop_pct": 0.0,
            "exit_time_stop_bars": 0,
            "exit_on_thesis_invalidation": False,
        }
    )
    mark = drill.market.last(SYMBOL)
    entry = mark * 0.90
    drill.portfolio.apply_fill("BTC", Side.BUY, quantity=0.05, price_usd=entry)
    drill.portfolio.mark("BTC", mark)

    result = await drill.cycle()
    assert result is not None
    assert result.pipeline.exit_reason == "exit_take_profit"
    assert result.pipeline.paper_order is not None
    assert result.pipeline.paper_order.side is Side.SELL
    assert drill.ledger.has_order_for_decision(result.pipeline.paper_order.decision_id)


async def test_time_stop_fires_on_an_aged_position(harness) -> None:
    drill = await harness(
        settings_overrides={
            "exit_stop_loss_pct": 0.0,
            "exit_take_profit_pct": 0.50,
            "exit_trailing_stop_pct": 0.0,
            "exit_time_stop_bars": 1,
            "exit_on_thesis_invalidation": False,
        }
    )
    from datetime import UTC, datetime, timedelta

    opened = datetime.now(UTC) - timedelta(hours=2)
    mark = drill.market.last(SYMBOL)
    drill.portfolio.apply_fill("BTC", Side.BUY, quantity=0.05, price_usd=mark, now=opened)
    drill.portfolio.mark("BTC", mark)

    result = await drill.cycle()
    assert result is not None
    assert result.pipeline.exit_reason == "exit_time_stop"
    assert result.pipeline.paper_order is not None
    assert drill.ledger.has_order_for_decision(result.pipeline.paper_order.decision_id)


async def test_kill_switch_still_withholds_an_exit(harness) -> None:
    drill = await harness(
        settings_overrides={
            "exit_stop_loss_pct": 0.02,
            "exit_take_profit_pct": 0.0,
            "exit_time_stop_bars": 0,
            "exit_on_thesis_invalidation": False,
        }
    )
    _seed_losing_long(drill)
    drill.kill_sentinel.arm()

    result = await drill.cycle()
    assert result is not None
    assert result.pipeline.exit_reason == "exit_stop_loss"
    assert result.pipeline.risk_result is not None
    assert result.pipeline.risk_result.decision is RiskDecision.REJECT
    assert result.pipeline.risk_result.reasons == ["kill_switch_enabled"]
    assert result.pipeline.paper_order is None
    assert drill.venue_api.posts == 0


# --- protective exit sizing (#130) ---
# The harness submits via IdempotentSubmitter at tick.bid (below last), so the
# ledger order used to request more units than the seeded 0.05 BTC. The exit
# intent now carries the held quantity and the planner caps to it.

SEEDED_QUANTITY = 0.05


def _assert_ledger_never_exceeds_held(drill, result) -> None:
    assert result.pipeline.paper_order is not None
    assert result.pipeline.paper_order.max_quantity == pytest.approx(SEEDED_QUANTITY)
    order = drill.ledger.orders_for_decision(result.pipeline.paper_order.decision_id)[0]
    assert order.requested_quantity <= SEEDED_QUANTITY + 1e-12
    assert order.requested_quantity > 0


async def test_stop_loss_ledger_order_never_exceeds_the_held_quantity(harness) -> None:
    drill = await harness(
        settings_overrides={
            "exit_stop_loss_pct": 0.02,
            "exit_take_profit_pct": 0.0,
            "exit_trailing_stop_pct": 0.0,
            "exit_time_stop_bars": 0,
            "exit_on_thesis_invalidation": False,
        }
    )
    _seed_losing_long(drill)

    result = await drill.cycle()
    assert result is not None
    assert result.pipeline.exit_reason == "exit_stop_loss"
    _assert_ledger_never_exceeds_held(drill, result)


async def test_take_profit_ledger_order_never_exceeds_the_held_quantity(harness) -> None:
    drill = await harness(
        settings_overrides={
            "exit_stop_loss_pct": 0.0,
            "exit_take_profit_pct": 0.03,
            "exit_trailing_stop_pct": 0.0,
            "exit_time_stop_bars": 0,
            "exit_on_thesis_invalidation": False,
        }
    )
    mark = drill.market.last(SYMBOL)
    entry = mark * 0.90
    drill.portfolio.apply_fill("BTC", Side.BUY, quantity=SEEDED_QUANTITY, price_usd=entry)
    drill.portfolio.mark("BTC", mark)

    result = await drill.cycle()
    assert result is not None
    assert result.pipeline.exit_reason == "exit_take_profit"
    _assert_ledger_never_exceeds_held(drill, result)


async def test_time_stop_ledger_order_never_exceeds_the_held_quantity(harness) -> None:
    drill = await harness(
        settings_overrides={
            "exit_stop_loss_pct": 0.0,
            "exit_take_profit_pct": 0.50,
            "exit_trailing_stop_pct": 0.0,
            "exit_time_stop_bars": 1,
            "exit_on_thesis_invalidation": False,
        }
    )
    opened = datetime.now(UTC) - timedelta(hours=2)
    mark = drill.market.last(SYMBOL)
    drill.portfolio.apply_fill(
        "BTC", Side.BUY, quantity=SEEDED_QUANTITY, price_usd=mark, now=opened
    )
    drill.portfolio.mark("BTC", mark)

    result = await drill.cycle()
    assert result is not None
    assert result.pipeline.exit_reason == "exit_time_stop"
    _assert_ledger_never_exceeds_held(drill, result)


async def test_trailing_stop_reaches_the_ledger_and_never_exceeds_the_held_quantity(
    harness,
) -> None:
    drill = await harness(
        settings_overrides={
            "exit_stop_loss_pct": 0.0,
            "exit_take_profit_pct": 0.0,
            "exit_trailing_stop_pct": 0.015,
            "exit_time_stop_bars": 0,
            "exit_on_thesis_invalidation": False,
        }
    )
    # Long opened below the current mark, high-water pushed well above it so
    # the 1.5% trail is already breached at the current synthetic price.
    mark = drill.market.last(SYMBOL)
    entry = mark * 0.90
    drill.portfolio.apply_fill("BTC", Side.BUY, quantity=SEEDED_QUANTITY, price_usd=entry)
    drill.portfolio.mark("BTC", mark * 1.10)
    drill.portfolio.mark("BTC", mark)

    result = await drill.cycle()
    assert result is not None
    assert result.pipeline.exit_reason == "exit_trailing_stop"
    assert result.pipeline.proposal is not None
    assert result.pipeline.proposal.strategy_id == "exit-trailing_stop"
    assert result.pipeline.proposal.side is Side.SELL
    assert result.pipeline.risk_result is not None
    assert result.pipeline.risk_result.decision in {RiskDecision.ALLOW, RiskDecision.REDUCE}
    assert result.pipeline.paper_order is not None
    assert drill.ledger.has_order_for_decision(result.pipeline.paper_order.decision_id)
    _assert_ledger_never_exceeds_held(drill, result)
