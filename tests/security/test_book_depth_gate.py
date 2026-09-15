"""Order-book depth as a risk gate (#61).

A spread check bounds the *price* at the top of book. It says nothing about
the size behind it, so a clip sized off NAV can fill well through that spread
in a thin book. #61 makes depth a pre-trade gate.

Making market data gate a trade is exactly where it could go wrong, so these
pin the direction of that power: depth may withhold a trade and may never
authorise, enlarge, or unblock one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from traderstack.config import Settings
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.market.models import BookLevel, BookSnapshot, MarketSource
from traderstack.models import (
    PortfolioSnapshot,
    RiskDecision,
    Side,
    TradeProposal,
)
from traderstack.risk import RiskEngine


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"kill_switch": False}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def portfolio(**overrides: object) -> PortfolioSnapshot:
    base: dict[str, object] = {
        "nav_usd": 100_000.0,
        "cash_usd": 100_000.0,
        "daily_pnl_usd": 0.0,
        "peak_nav_usd": 100_000.0,
        "asset_exposure_usd": {},
        "observed_at": datetime.now(UTC),
    }
    base.update(overrides)
    return PortfolioSnapshot(**base)  # type: ignore[arg-type]


def proposal(side: Side = Side.BUY, notional: float = 1_000.0) -> TradeProposal:
    return TradeProposal(
        decision_id=uuid4(),
        asset="BTC",
        side=side,
        requested_notional_usd=notional,
        confidence=0.6,
        strategy_id="momentum",
        thesis="t",
        source_freshness_seconds=1.0,
    )


def features(spread_bps: float = 5.0) -> AssetFeatureVector:
    return AssetFeatureVector(
        asset="BTC",
        market=MarketFeatures(
            trend_4h=0.0,
            trend_1d=0.0,
            volatility_z=0.0,
            relative_volume=1.0,
            spread_bps=spread_bps,
        ),
    )


def book(*, bid_qty: float, ask_qty: float, mid: float = 100.0) -> BookSnapshot:
    """A two-sided book with all size inside 10 bps of ``mid``."""

    return BookSnapshot(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        bids=(BookLevel(price=mid * 0.9999, qty=bid_qty),),
        asks=(BookLevel(price=mid * 1.0001, qty=ask_qty),),
    )


# --- the gate ----------------------------------------------------------------


def test_a_thin_book_rejects_a_taking_buy() -> None:
    """$1000 buy needs 2x depth in asks; 5 units at ~$100 is only ~$500."""

    engine = RiskEngine(settings())
    result = engine.evaluate(
        proposal(Side.BUY),
        portfolio(),
        features(),
        book_snapshot=book(bid_qty=1_000.0, ask_qty=5.0),
    )
    assert result.decision is RiskDecision.REJECT
    assert "insufficient_book_depth" in result.reasons


def test_a_deep_book_leaves_the_decision_unchanged() -> None:
    engine = RiskEngine(settings())
    deep = engine.evaluate(
        proposal(Side.BUY),
        portfolio(),
        features(),
        book_snapshot=book(bid_qty=500.0, ask_qty=500.0),
    )
    without = engine.evaluate(proposal(Side.BUY), portfolio(), features())
    assert deep.decision is without.decision
    assert deep.approved_notional_usd == without.approved_notional_usd
    assert "insufficient_book_depth" not in deep.reasons


def test_the_taking_side_is_the_one_checked() -> None:
    """A BUY consumes asks, a SELL consumes bids.

    Checking the wrong side would clear a trade against liquidity it cannot
    reach, which is the whole failure this gate exists to prevent.
    """

    engine = RiskEngine(settings())
    thin_asks = book(bid_qty=1_000.0, ask_qty=1.0)

    buy = engine.evaluate(proposal(Side.BUY), portfolio(), features(), book_snapshot=thin_asks)
    assert "insufficient_book_depth" in buy.reasons

    # The same book is deep on the bid side. A SELL with no existing exposure
    # is still risk-adding, so it passes the gate on its own (bid) side.
    sell = engine.evaluate(proposal(Side.SELL), portfolio(), features(), book_snapshot=thin_asks)
    assert "insufficient_book_depth" not in sell.reasons


# --- direction of power ------------------------------------------------------


def test_depth_can_never_increase_the_approved_notional() -> None:
    """A gate, not a sizer: no book makes an order larger than no book at all."""

    engine = RiskEngine(settings())
    baseline = engine.evaluate(proposal(Side.BUY), portfolio(), features())
    enormous = engine.evaluate(
        proposal(Side.BUY),
        portfolio(),
        features(),
        book_snapshot=book(bid_qty=10_000_000.0, ask_qty=10_000_000.0),
    )
    assert enormous.approved_notional_usd <= baseline.approved_notional_usd


def test_depth_cannot_unblock_a_trade_another_gate_rejected() -> None:
    """A deep book must not rescue a proposal the spread gate already refused."""

    engine = RiskEngine(settings(risk_max_spread_bps=10.0))
    result = engine.evaluate(
        proposal(Side.BUY),
        portfolio(),
        features(spread_bps=500.0),
        book_snapshot=book(bid_qty=10_000.0, ask_qty=10_000.0),
    )
    assert result.decision is RiskDecision.REJECT
    assert "spread_too_wide" in result.reasons


def test_a_risk_reducing_exit_is_exempt() -> None:
    """Refusing to let a stop-loss out of a thin book is the #130 failure mode.

    A thin book is exactly when flattening matters most, so the gate applies
    to risk-adding proposals only.
    """

    engine = RiskEngine(settings())
    result = engine.evaluate(
        proposal(Side.SELL),
        portfolio(asset_exposure_usd={"BTC": 5_000.0}),
        features(),
        book_snapshot=book(bid_qty=0.01, ask_qty=0.01),
    )
    assert "insufficient_book_depth" not in result.reasons
    assert result.decision is not RiskDecision.REJECT


# --- absent and hostile books ------------------------------------------------


def test_an_absent_book_is_no_information_and_off_by_default() -> None:
    """Default off so the Robinhood Chain path, which has no book, still runs."""

    engine = RiskEngine(settings())
    result = engine.evaluate(proposal(Side.BUY), portfolio(), features(), book_snapshot=None)
    assert "book_depth_unavailable" not in result.reasons
    assert result.decision is not RiskDecision.REJECT


def test_an_absent_book_fails_closed_when_required() -> None:
    engine = RiskEngine(settings(risk_require_book_depth=True))
    result = engine.evaluate(proposal(Side.BUY), portfolio(), features(), book_snapshot=None)
    assert result.decision is RiskDecision.REJECT
    assert "book_depth_unavailable" in result.reasons


def test_an_empty_book_is_thin_not_deep() -> None:
    """No levels means no depth, which must reject rather than divide by zero."""

    engine = RiskEngine(settings())
    empty = BookSnapshot(source=MarketSource.KRAKEN, symbol="BTC/USD")
    result = engine.evaluate(proposal(Side.BUY), portfolio(), features(), book_snapshot=empty)
    assert result.decision is RiskDecision.REJECT
    assert "insufficient_book_depth" in result.reasons


@pytest.mark.parametrize(
    "level",
    [
        {"price": 100.0, "qty": float("inf")},
        {"price": float("inf"), "qty": 1.0},
        {"price": float("nan"), "qty": 1.0},
        {"price": -100.0, "qty": 1.0},
        {"price": 100.0, "qty": -1.0},
    ],
)
def test_a_hostile_level_fails_validation_before_the_engine(level: dict[str, float]) -> None:
    """Non-finite size is the dangerous direction, not the obviously-broken one.

    An infinite qty yields infinite depth, which satisfies *any* minimum — so
    a hostile or malformed venue payload could have talked its way past the
    gate. `allow_inf_nan=False` stops it at the model boundary.
    """

    with pytest.raises(ValidationError):
        BookLevel(**level)  # type: ignore[arg-type]


def test_disabling_the_multiple_disables_the_gate() -> None:
    """A zero multiple is off, not 'reject everything'."""

    engine = RiskEngine(settings(risk_min_depth_multiple=0.0))
    result = engine.evaluate(
        proposal(Side.BUY), portfolio(), features(), book_snapshot=book(bid_qty=0.0, ask_qty=0.0)
    )
    assert "insufficient_book_depth" not in result.reasons
