import pytest

from traderstack.execution.planner import (
    ExecutionPlanner,
    ExecutionPlanRejected,
    client_order_id_for,
    correlation_id_for,
)
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent


def intent(**overrides: object) -> PaperOrderIntent:
    payload: dict[str, object] = {
        "decision_id": "decision-1",
        "asset": "BTC",
        "side": Side.BUY,
        "notional_usd": 1_000.0,
        "venue": "kraken_paper_trade",
    }
    payload.update(overrides)
    return PaperOrderIntent.model_validate(payload)


def test_plan_rounds_quantity_down_to_lot_step() -> None:
    planner = ExecutionPlanner(lot_step=0.001, min_notional_usd=10)
    plan = planner.plan(intent(), execution_price_usd=19_999, reference_price_usd=20_000)

    # 1000 / 19999 = 0.050002... -> floored to the 0.001 lot step.
    assert plan.quantity == pytest.approx(0.050)
    assert plan.notional_usd == pytest.approx(0.050 * 19_999)
    assert plan.notional_usd <= plan.requested_notional_usd
    assert plan.trading_pair == "BTC-USD"


def test_plan_rejects_below_minimum_notional() -> None:
    planner = ExecutionPlanner(lot_step=1e-8, min_notional_usd=25)
    with pytest.raises(ExecutionPlanRejected, match="below minimum"):
        planner.plan(
            intent(notional_usd=20.0), execution_price_usd=20_000, reference_price_usd=20_000
        )


def test_plan_rejects_when_lot_step_rounds_quantity_to_zero() -> None:
    planner = ExecutionPlanner(lot_step=1.0, min_notional_usd=1)
    with pytest.raises(ExecutionPlanRejected, match="rounds to zero"):
        planner.plan(
            intent(notional_usd=1_000.0), execution_price_usd=20_000, reference_price_usd=20_000
        )


def test_plan_rejects_adverse_slippage_beyond_limit() -> None:
    planner = ExecutionPlanner(lot_step=1e-8, max_slippage_bps=25)
    with pytest.raises(ExecutionPlanRejected, match="deviates"):
        # 20_100 vs 20_000 is 50 bps.
        planner.plan(intent(), execution_price_usd=20_100, reference_price_usd=20_000)


def test_plan_rejects_favourable_slippage_beyond_limit() -> None:
    """A suspiciously good price is a data-integrity signal, not a gift."""

    planner = ExecutionPlanner(lot_step=1e-8, max_slippage_bps=25)
    with pytest.raises(ExecutionPlanRejected, match="deviates"):
        planner.plan(intent(), execution_price_usd=19_900, reference_price_usd=20_000)


def test_plan_accepts_slippage_at_the_limit() -> None:
    planner = ExecutionPlanner(lot_step=1e-8, max_slippage_bps=50)
    plan = planner.plan(intent(), execution_price_usd=20_100, reference_price_usd=20_000)
    assert plan.slippage_bps == pytest.approx(50.0)


def test_plan_rejects_non_positive_prices() -> None:
    planner = ExecutionPlanner()
    with pytest.raises(ExecutionPlanRejected, match="execution price"):
        planner.plan(intent(), execution_price_usd=0.0, reference_price_usd=20_000)
    with pytest.raises(ExecutionPlanRejected, match="reference price"):
        planner.plan(intent(), execution_price_usd=20_000, reference_price_usd=0.0)


def test_client_order_id_is_deterministic_and_decision_scoped() -> None:
    assert client_order_id_for("decision-1") == client_order_id_for("decision-1")
    assert client_order_id_for("decision-1") != client_order_id_for("decision-2")
    assert len(client_order_id_for("decision-1")) <= 32
    assert correlation_id_for("decision-1") == correlation_id_for("decision-1")
    assert correlation_id_for("decision-1") != client_order_id_for("decision-1")


def test_planner_is_pure_across_instances() -> None:
    """Two processes planning the same decision must agree on the idempotency key."""

    first = ExecutionPlanner(lot_step=0.001).plan(
        intent(), execution_price_usd=20_000, reference_price_usd=20_000
    )
    second = ExecutionPlanner(lot_step=0.001).plan(
        intent(), execution_price_usd=20_000, reference_price_usd=20_000
    )
    assert first.client_order_id == second.client_order_id
    assert first.correlation_id == second.correlation_id
    assert first.model_dump() == second.model_dump()


def test_planner_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="lot_step"):
        ExecutionPlanner(lot_step=0)
    with pytest.raises(ValueError, match="min_notional_usd"):
        ExecutionPlanner(min_notional_usd=0)
    with pytest.raises(ValueError, match="max_slippage_bps"):
        ExecutionPlanner(max_slippage_bps=-1)


# --- protective exit sizing (#130) ---


def test_max_quantity_caps_quantity_and_lowers_notional_never_raises() -> None:
    planner = ExecutionPlanner(lot_step=1e-8, min_notional_usd=10)
    # 1.0 BTC held at a $100 mark; adverse sell price $99.95 would convert
    # $100 back into 1.00050025 units without the cap.
    exit_intent = intent(side=Side.SELL, notional_usd=100.0, max_quantity=1.0)
    plan = planner.plan(exit_intent, execution_price_usd=99.95, reference_price_usd=100.0)

    assert plan.quantity == pytest.approx(1.0)
    assert plan.quantity_capped_to_position is True
    assert plan.notional_usd == pytest.approx(99.95)
    assert plan.notional_usd < plan.requested_notional_usd


def test_max_quantity_above_notional_over_price_is_a_no_op() -> None:
    planner = ExecutionPlanner(lot_step=1e-8, min_notional_usd=10)
    uncapped = planner.plan(
        intent(side=Side.SELL, notional_usd=100.0),
        execution_price_usd=99.95,
        reference_price_usd=100.0,
    )
    capped = planner.plan(
        intent(side=Side.SELL, notional_usd=100.0, max_quantity=5.0),
        execution_price_usd=99.95,
        reference_price_usd=100.0,
    )
    assert capped.quantity == pytest.approx(uncapped.quantity)
    assert capped.notional_usd == pytest.approx(uncapped.notional_usd)
    assert capped.quantity_capped_to_position is False


def test_max_quantity_is_floored_to_the_lot_step() -> None:
    planner = ExecutionPlanner(lot_step=0.001, min_notional_usd=10)
    plan = planner.plan(
        intent(side=Side.SELL, notional_usd=100.0, max_quantity=0.9999),
        execution_price_usd=99.95,
        reference_price_usd=100.0,
    )
    assert plan.quantity == pytest.approx(0.999)
    assert plan.quantity <= 0.9999


def test_max_quantity_that_floors_to_zero_is_rejected() -> None:
    planner = ExecutionPlanner(lot_step=1.0, min_notional_usd=1)
    with pytest.raises(ExecutionPlanRejected, match="held quantity .* rounds to zero"):
        planner.plan(
            intent(side=Side.SELL, notional_usd=100.0, max_quantity=0.5),
            execution_price_usd=100.0,
            reference_price_usd=100.0,
        )


def test_capped_quantity_is_still_subject_to_minimum_notional() -> None:
    planner = ExecutionPlanner(lot_step=1e-8, min_notional_usd=25)
    with pytest.raises(ExecutionPlanRejected, match="below minimum"):
        planner.plan(
            intent(side=Side.SELL, notional_usd=100.0, max_quantity=0.1),
            execution_price_usd=100.0,
            reference_price_usd=100.0,
        )


def test_max_quantity_on_a_buy_intent_only_lowers() -> None:
    planner = ExecutionPlanner(lot_step=1e-8, min_notional_usd=10)
    base = planner.plan(
        intent(side=Side.BUY, notional_usd=1_000.0),
        execution_price_usd=20_000,
        reference_price_usd=20_000,
    )
    smaller = planner.plan(
        intent(side=Side.BUY, notional_usd=1_000.0, max_quantity=0.01),
        execution_price_usd=20_000,
        reference_price_usd=20_000,
    )
    larger = planner.plan(
        intent(side=Side.BUY, notional_usd=1_000.0, max_quantity=10.0),
        execution_price_usd=20_000,
        reference_price_usd=20_000,
    )
    assert smaller.quantity == pytest.approx(0.01)
    assert smaller.quantity < base.quantity
    assert larger.quantity == pytest.approx(base.quantity)
    assert larger.notional_usd <= larger.requested_notional_usd


def test_max_quantity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        intent(max_quantity=0.0)
    with pytest.raises(ValueError):
        intent(max_quantity=-1.0)
