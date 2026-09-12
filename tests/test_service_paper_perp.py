"""Service paper cycles hedge with an explicit venue mid and apply funding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.paper_fill import PaperFillSimulator
from traderstack.execution.paper_perp import PaperPerpBook, PaperPerpStatus
from traderstack.execution.paper_perp_feed import PaperPerpFundingTape, PaperPerpQuote
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.research.funding_carry import PAPER_CARRY_PATH_READY
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService


class FakeRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result

    async def run_once(self, symbol, portfolio, *, submit=False):
        return self.result


class FakePaperPerpFeed:
    def __init__(
        self,
        quote: PaperPerpQuote | None,
        tape: PaperPerpFundingTape | None = None,
    ) -> None:
        self.quote = quote
        self.tape = tape
        self.mid_calls: list[str] = []
        self.funding_calls: list[tuple[str, str]] = []

    async def fetch_mid(self, symbol: str) -> PaperPerpQuote | None:
        self.mid_calls.append(symbol)
        return self.quote

    async def fetch_funding_since(self, symbol: str, *, venue: str, since: datetime):
        self.funding_calls.append((symbol, venue))
        if self.tape is None:
            return PaperPerpFundingTape(venue=venue, asset="BTC", settlements=(), source="")
        return self.tape


def _tick(*, last: float = 20_000.0) -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC),
        bid=last - 10,
        ask=last + 10,
        last=last,
    )


def _allowed() -> RuntimeResult:
    return RuntimeResult(
        tick=_tick(last=20_000.0),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            paper_order=PaperOrderIntent(
                decision_id="decision-allow",
                asset="BTC",
                side=Side.BUY,
                notional_usd=1_000,
            ),
        ),
        trading_mode="paper",
    )


def _quote(*, mid: float = 20_100.0) -> PaperPerpQuote:
    return PaperPerpQuote(
        venue="hyperliquid",
        asset="BTC",
        symbol="BTC/USD",
        mid_usd=mid,
        observed_at=datetime(2026, 9, 12, 16, 0, tzinfo=UTC),
        source="hyperliquid:/info metaAndAssetCtxs midPx",
    )


@pytest.mark.asyncio
async def test_service_hedges_with_venue_mid_not_kraken_spot() -> None:
    spot = InMemoryPortfolioBook(starting_nav_usd=10_000)
    perp = PaperPerpBook(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    feed = FakePaperPerpFeed(_quote(mid=20_100.0))
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed()),  # type: ignore[arg-type]
        portfolio=spot,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=0.0, paper_slippage_bps=0.0),
        paper_perp_book=perp,
        paper_perp_feed=feed,
        error_backoff_seconds=0,
    )
    await service._run_symbol_safely("BTC/USD")
    assert feed.mid_calls == ["BTC/USD"]
    assert "BTC" in perp.positions
    position = perp.positions["BTC"]
    assert position.side is Side.SELL
    assert position.entry_price_usd == pytest.approx(20_100.0)
    assert PAPER_CARRY_PATH_READY is True


@pytest.mark.asyncio
async def test_service_skips_hedge_when_feed_has_no_mid() -> None:
    spot = InMemoryPortfolioBook(starting_nav_usd=10_000)
    perp = PaperPerpBook()
    feed = FakePaperPerpFeed(None)
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed()),  # type: ignore[arg-type]
        portfolio=spot,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(),
        paper_perp_book=perp,
        paper_perp_feed=feed,
        error_backoff_seconds=0,
    )
    await service._run_symbol_safely("BTC/USD")
    assert spot.positions["BTC"].quantity > 0
    assert perp.positions == {}
    assert feed.mid_calls == ["BTC/USD"]


@pytest.mark.asyncio
async def test_service_applies_same_venue_funding_after_hedge() -> None:
    opened = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
    later = opened + timedelta(hours=1)
    quote = PaperPerpQuote(
        venue="hyperliquid",
        asset="BTC",
        symbol="BTC/USD",
        mid_usd=20_000.0,
        observed_at=opened,
        source="hyperliquid:/info metaAndAssetCtxs midPx",
    )
    tape = PaperPerpFundingTape(
        venue="hyperliquid",
        asset="BTC",
        settlements=((later, 0.001),),
        source="hyperliquid:/info fundingHistory",
    )
    spot = InMemoryPortfolioBook(starting_nav_usd=10_000)
    perp = PaperPerpBook(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    feed = FakePaperPerpFeed(quote, tape)
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed()),  # type: ignore[arg-type]
        portfolio=spot,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=0.0, paper_slippage_bps=0.0),
        paper_perp_book=perp,
        paper_perp_feed=feed,
        error_backoff_seconds=0,
    )
    await service._run_symbol_safely("BTC/USD")
    assert perp.positions["BTC"].side is Side.SELL
    assert feed.funding_calls == [("BTC/USD", "hyperliquid")]
    assert perp.funding_prints_applied == 1
    qty = perp.positions["BTC"].quantity
    assert perp.total_funding_pnl_usd() == pytest.approx(qty * 20_000.0 * 0.001)
    assert PAPER_CARRY_PATH_READY is True


@pytest.mark.asyncio
async def test_service_does_not_invent_funding_when_tape_empty() -> None:
    perp = PaperPerpBook(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    feed = FakePaperPerpFeed(_quote(mid=20_000.0))
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed()),  # type: ignore[arg-type]
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=0.0, paper_slippage_bps=0.0),
        paper_perp_book=perp,
        paper_perp_feed=feed,
        error_backoff_seconds=0,
    )
    await service._run_symbol_safely("BTC/USD")
    assert perp.positions
    assert perp.funding_prints_applied == 0
    assert perp.total_funding_pnl_usd() == pytest.approx(0.0)


def test_hedge_with_explicit_mid_and_funding_is_the_ready_path() -> None:
    book = PaperPerpBook(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    from traderstack.execution.ledger import ExecutionFill, FeeSource

    fill = ExecutionFill(
        fill_id="paper-fill:x",
        order_id="x",
        asset="BTC",
        side=Side.BUY,
        quantity=1.0,
        price_usd=19_000.0,
        fee_source=FeeSource.MODELLED,
    )
    hedge = book.maybe_hedge_spot_fill(fill, perp_mid_usd=20_000.0, decision_id="x")
    assert hedge.status is PaperPerpStatus.HEDGED
    funding = book.apply_funding(
        ((datetime(2026, 9, 12, tzinfo=UTC), 0.0001),),
        asset="BTC",
        mark_usd=20_000.0,
    )
    assert funding.status is PaperPerpStatus.FUNDING_APPLIED
    assert book.funding_prints_applied == 1
    assert PAPER_CARRY_PATH_READY is True
    assert book.path_ready is True
