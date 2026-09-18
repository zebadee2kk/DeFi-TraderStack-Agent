"""Unit tests for carry_hedged_sign diagnostic helpers and defaults."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.paper_perp import (
    CARRY_DIAGNOSTIC_NOTIONAL_USD,
    CARRY_DIAGNOSTIC_SIGNAL,
    PaperPerpBook,
    carry_hedged_sign_spot_side,
)
from traderstack.execution.paper_perp_feed import PaperPerpFundingTape, PaperPerpQuote
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import Side
from traderstack.pipeline import PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService


def test_carry_diagnostic_defaults_false() -> None:
    settings = Settings()
    assert settings.paper_carry_hedge_diagnostic is False
    assert settings.paper_perp_hedge is False
    assert settings.paper_promote_ema_9_21 is False
    assert settings.paper_promote_ema_9_21_adx15 is False
    assert settings.paper_promote_searched_strategies is False


def test_carry_hedged_sign_spot_side_mapping() -> None:
    assert carry_hedged_sign_spot_side(0.0001) is Side.BUY
    assert carry_hedged_sign_spot_side(-0.0001) is Side.SELL
    assert carry_hedged_sign_spot_side(0.0) is None


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

    async def fetch_mid(self, symbol: str) -> PaperPerpQuote | None:
        return self.quote

    async def fetch_funding_since(self, symbol: str, *, venue: str, since: datetime):
        if self.tape is None:
            return PaperPerpFundingTape(venue=venue, asset="BTC", settlements=(), source="")
        return self.tape


def _flat_result() -> RuntimeResult:
    return RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=19_990.0,
            ask=20_010.0,
            last=20_000.0,
        ),
        references=[],
        pipeline=PipelineResult(accepted_market_data=True),
        trading_mode="paper",
    )


@pytest.mark.asyncio
async def test_carry_diagnostic_opens_hedge_without_spot_fill() -> None:
    settings = Settings().model_copy(
        update={"paper_perp_hedge": True, "paper_carry_hedge_diagnostic": True}
    )
    quote = PaperPerpQuote(
        venue="hyperliquid",
        asset="BTC",
        symbol="BTC/USD",
        mid_usd=20_100.0,
        observed_at=datetime(2026, 9, 18, 16, 0, tzinfo=UTC),
        source="hyperliquid:/info metaAndAssetCtxs midPx",
    )
    tape = PaperPerpFundingTape(
        venue="hyperliquid",
        asset="BTC",
        settlements=((datetime(2026, 9, 18, 12, 0, tzinfo=UTC), 0.0001),),
        source="hyperliquid:/info fundingHistory",
    )
    spot = InMemoryPortfolioBook(starting_nav_usd=10_000)
    nav_before = spot.snapshot().nav_usd
    perp = PaperPerpBook(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    feed = FakePaperPerpFeed(quote, tape)
    service = ContinuousPaperService(
        runtime=FakeRuntime(_flat_result()),  # type: ignore[arg-type]
        portfolio=spot,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        settings=settings,
        paper_perp_book=perp,
        paper_perp_feed=feed,
    )
    await service._maybe_open_carry_diagnostic_hedge("BTC/USD")
    assert "BTC" in perp.positions
    assert perp.positions["BTC"].side is Side.SELL  # positive rate -> short perp
    assert spot.snapshot().nav_usd == pytest.approx(nav_before)
    assert CARRY_DIAGNOSTIC_SIGNAL == "carry_hedged_sign"
    assert CARRY_DIAGNOSTIC_NOTIONAL_USD == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_carry_diagnostic_off_by_default_skips() -> None:
    settings = Settings().model_copy(update={"paper_perp_hedge": True})
    quote = PaperPerpQuote(
        venue="hyperliquid",
        asset="BTC",
        symbol="BTC/USD",
        mid_usd=20_100.0,
        observed_at=datetime(2026, 9, 18, 16, 0, tzinfo=UTC),
        source="test",
    )
    tape = PaperPerpFundingTape(
        venue="hyperliquid",
        asset="BTC",
        settlements=((datetime(2026, 9, 18, 12, 0, tzinfo=UTC), 0.0001),),
        source="test",
    )
    perp = PaperPerpBook(paper_fee_bps=0.0, paper_slippage_bps=0.0)
    service = ContinuousPaperService(
        runtime=FakeRuntime(_flat_result()),  # type: ignore[arg-type]
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        settings=settings,
        paper_perp_book=perp,
        paper_perp_feed=FakePaperPerpFeed(quote, tape),
    )
    await service._maybe_open_carry_diagnostic_hedge("BTC/USD")
    assert perp.positions == {}
