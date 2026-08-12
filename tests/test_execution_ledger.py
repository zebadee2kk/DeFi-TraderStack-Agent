import pytest
from pydantic import ValidationError

from traderstack.execution.ledger import (
    ExecutionFill,
    ExecutionLedger,
    ExecutionOrder,
    OrderLifecycleState,
)
from traderstack.models import Side


def test_ledger_applies_partial_then_complete_fill_idempotently() -> None:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o1",
            decision_id="d1",
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.1,
        )
    )

    assert ledger.record_fill(
        ExecutionFill(
            fill_id="f1",
            order_id="o1",
            asset="BTC",
            side=Side.BUY,
            quantity=0.04,
            price_usd=20_000,
        )
    )
    assert ledger.orders["o1"].state is OrderLifecycleState.PARTIALLY_FILLED
    assert ledger.orders["o1"].filled_quantity == pytest.approx(0.04)

    assert not ledger.record_fill(
        ExecutionFill(
            fill_id="f1",
            order_id="o1",
            asset="BTC",
            side=Side.BUY,
            quantity=0.04,
            price_usd=20_000,
        )
    )

    assert ledger.record_fill(
        ExecutionFill(
            fill_id="f2",
            order_id="o1",
            asset="BTC",
            side=Side.BUY,
            quantity=0.06,
            price_usd=21_000,
        )
    )
    order = ledger.orders["o1"]
    assert order.state is OrderLifecycleState.FILLED
    assert order.filled_quantity == pytest.approx(0.1)
    assert order.average_fill_price_usd == pytest.approx(20_600)


def test_ledger_rejects_orphan_and_overfill() -> None:
    ledger = ExecutionLedger()
    with pytest.raises(KeyError):
        ledger.record_fill(
            ExecutionFill(
                fill_id="orphan",
                order_id="missing",
                asset="ETH",
                side=Side.BUY,
                quantity=1,
                price_usd=1_000,
            )
        )

    ledger.register_order(
        ExecutionOrder(
            order_id="o2",
            decision_id="d2",
            asset="ETH",
            side=Side.BUY,
            requested_quantity=1,
        )
    )
    with pytest.raises(ValueError, match="overfills"):
        ledger.record_fill(
            ExecutionFill(
                fill_id="too-much",
                order_id="o2",
                asset="ETH",
                side=Side.BUY,
                quantity=1.1,
                price_usd=1_000,
            )
        )


def test_execution_fill_rejects_non_finite_values() -> None:
    base = {
        "fill_id": "f-1",
        "order_id": "o-1",
        "asset": "BTC",
        "side": Side.BUY,
        "quantity": 1.0,
        "price_usd": 100.0,
    }
    with pytest.raises(ValidationError):
        ExecutionFill(**{**base, "price_usd": float("inf")})
    with pytest.raises(ValidationError):
        ExecutionFill(**{**base, "quantity": float("nan")})
    with pytest.raises(ValidationError):
        ExecutionFill(**{**base, "fee_usd": float("inf")})


def test_large_quantity_partial_fills_within_float_noise() -> None:
    requested = 1_000_000.0 / 6.396708  # notional / price, not exactly representable
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o-big",
            decision_id="d1",
            asset="SOL",
            side=Side.BUY,
            requested_quantity=requested,
        )
    )
    first = round(requested * 0.6, 8)
    second = requested - first + 2.9e-11  # exchange-rounded remainder, one ULP over
    assert ledger.record_fill(
        ExecutionFill(
            fill_id="f1", order_id="o-big", asset="SOL", side=Side.BUY, quantity=first, price_usd=6.4
        )
    )
    assert ledger.record_fill(
        ExecutionFill(
            fill_id="f2", order_id="o-big", asset="SOL", side=Side.BUY, quantity=second, price_usd=6.4
        )
    )
    assert ledger.orders["o-big"].state is OrderLifecycleState.FILLED


def test_ledger_state_round_trip() -> None:
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o1", decision_id="d1", asset="BTC", side=Side.BUY, requested_quantity=1.0
        )
    )
    ledger.record_fill(
        ExecutionFill(
            fill_id="f1", order_id="o1", asset="BTC", side=Side.BUY, quantity=0.4, price_usd=100.0
        )
    )

    restored = ExecutionLedger.from_state(ledger.state())
    assert restored.orders["o1"].filled_quantity == pytest.approx(0.4)
    assert restored.processed_fill_ids == {"f1"}
    assert restored.record_fill(
        ExecutionFill(
            fill_id="f1", order_id="o1", asset="BTC", side=Side.BUY, quantity=0.4, price_usd=100.0
        )
    ) is False
