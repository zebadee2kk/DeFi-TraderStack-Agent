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
