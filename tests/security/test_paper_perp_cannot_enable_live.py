"""Paper perp/hedge stub cannot enable live, invent basis, or relax risk."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from traderstack.config import Settings
from traderstack.execution.hummingbot import ExecutionSafetyError
from traderstack.execution.ledger import ExecutionFill, ExecutionLedger, FeeSource
from traderstack.execution.paper_fill import PaperFillSimulator
from traderstack.execution.paper_perp import PAPER_PERP_PATH_READY, PaperPerpBook, PaperPerpStatus
from traderstack.killswitch import KillSwitch
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.research.funding_carry import PAPER_CARRY_PATH_READY
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService


def test_settings_paper_perp_hedge_cannot_be_rewritten() -> None:
    settings = Settings(paper_perp_hedge=True)
    with pytest.raises(ValidationError):
        settings.paper_perp_hedge = False  # type: ignore[misc]
    assert settings.paper_perp_hedge is True
    assert settings.trading_mode == "paper"
    assert PAPER_PERP_PATH_READY is True
    assert PAPER_CARRY_PATH_READY is True
    assert settings.paper_promote_searched_strategies is False


def test_constructor_cannot_be_used_for_live() -> None:
    with pytest.raises(ExecutionSafetyError, match="outside paper mode"):
        PaperPerpBook(trading_mode="live")


@pytest.mark.asyncio
async def test_service_does_not_invent_perp_mid_from_kraken_spot() -> None:
    result = RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=19_990,
            ask=20_010,
            last=20_000,
        ),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            paper_order=PaperOrderIntent(
                decision_id="stale-allow",
                asset="BTC",
                side=Side.BUY,
                notional_usd=1_000,
            ),
        ),
        trading_mode="paper",
    )

    class FakeRuntime:
        async def run_once(self, symbol, portfolio, *, submit=False):
            return result

    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    perp = PaperPerpBook()
    service = ContinuousPaperService(
        runtime=FakeRuntime(),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(),
        paper_perp_book=perp,
        error_backoff_seconds=0,
    )
    await service._run_symbol_safely("BTC/USD")
    assert book.positions["BTC"].quantity > 0
    assert perp.positions == {}
    assert PAPER_CARRY_PATH_READY is True
    # Path-ready does not authorize inventing a mid from the Kraken tick.


@pytest.mark.asyncio
async def test_service_uses_venue_mid_not_kraken_spot_when_feed_returns_one() -> None:
    from datetime import UTC, datetime

    from traderstack.execution.paper_perp_feed import PaperPerpQuote

    class MidFeed:
        async def fetch_mid(self, symbol: str) -> PaperPerpQuote:
            return PaperPerpQuote(
                venue="bitmex",
                asset="BTC",
                symbol=symbol,
                mid_usd=21_000.0,
                observed_at=datetime.now(UTC),
                source="bitmex:/api/v1/instrument midPrice",
            )

        async def fetch_funding_since(self, symbol: str, *, venue: str, since):
            from traderstack.execution.paper_perp_feed import PaperPerpFundingTape

            return PaperPerpFundingTape(venue="bitmex", asset="BTC", settlements=(), source="")

    result = RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=19_990,
            ask=20_010,
            last=20_000,
        ),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            paper_order=PaperOrderIntent(
                decision_id="venue-mid",
                asset="BTC",
                side=Side.BUY,
                notional_usd=1_000,
            ),
        ),
        trading_mode="paper",
    )

    class FakeRuntime:
        async def run_once(self, symbol, portfolio, *, submit=False):
            return result

    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    perp = PaperPerpBook(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    service = ContinuousPaperService(
        runtime=FakeRuntime(),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=0.0, paper_slippage_bps=0.0),
        paper_perp_book=perp,
        paper_perp_feed=MidFeed(),
        error_backoff_seconds=0,
    )
    await service._run_symbol_safely("BTC/USD")
    assert perp.positions["BTC"].entry_price_usd == pytest.approx(21_000.0)
    assert perp.positions["BTC"].entry_price_usd != pytest.approx(20_000.0)


@pytest.mark.asyncio
async def test_engaged_kill_switch_blocks_hedge_even_with_perp_mid() -> None:
    perp = PaperPerpBook(kill_switch=KillSwitch(settings_flag=True))
    outcome = perp.maybe_hedge_spot_fill(
        ExecutionFill(
            fill_id="paper-fill:x",
            order_id="x",
            asset="BTC",
            side=Side.BUY,
            quantity=0.01,
            price_usd=20_000.0,
            fee_source=FeeSource.MODELLED,
        ),
        perp_mid_usd=20_000.0,
        decision_id="x",
    )
    assert outcome.status is PaperPerpStatus.WITHHELD
    assert perp.positions == {}
