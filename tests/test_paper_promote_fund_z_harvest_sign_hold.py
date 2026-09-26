"""Tests for PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD (default false)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from traderstack.cli_check import build_report
from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.paper_perp import (
    CARRY_DIAGNOSTIC_NOTIONAL_USD,
    FUND_Z_HARVEST_SIGN_HOLD_SIGNAL,
    PaperPerpBook,
)
from traderstack.execution.paper_perp_feed import PaperPerpFundingTape, PaperPerpQuote
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import Side
from traderstack.pipeline import PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.research.harder_gates import paper_promote_flag_name
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService


def test_promote_flag_name_convention() -> None:
    assert (
        paper_promote_flag_name("fund_z_harvest_sign_hold")
        == "PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD"
    )


def test_fund_z_harvest_promote_defaults_false() -> None:
    settings = Settings()
    assert settings.paper_promote_fund_z_harvest_sign_hold is False
    assert settings.paper_promote_fund_z_harvest_sign_hold_active is False
    assert settings.trading_mode == "paper"
    assert settings.paper_perp_hedge is False


def test_check_config_reports_cannot_promote_by_default() -> None:
    report = build_report(Settings())
    item = next(i for i in report.items if i.label == "Paper promote fund_z_harvest_sign_hold")
    assert "cannot promote" in item.value
    assert "default false" in item.value


def test_check_config_requires_explicit_env_and_paper_perp() -> None:
    report = build_report(
        Settings().model_copy(update={"paper_promote_fund_z_harvest_sign_hold": True})
    )
    assert any("PAPER_PERP_HEDGE" in w for w in report.warnings)
    item = next(i for i in report.items if i.label == "Paper promote fund_z_harvest_sign_hold")
    assert "off" in item.value or "cannot promote" in item.value


def test_check_config_active_warns_paper_perp_only() -> None:
    report = build_report(
        Settings().model_copy(
            update={
                "paper_perp_hedge": True,
                "paper_promote_fund_z_harvest_sign_hold": True,
            }
        )
    )
    item = next(i for i in report.items if i.label == "Paper promote fund_z_harvest_sign_hold")
    assert "active" in item.value
    assert any("fund_z_harvest_sign_hold" in w for w in report.warnings)
    assert any("Not live" in w for w in report.warnings)


def test_explicit_env_required_to_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD", "true")
    settings = Settings()
    assert settings.paper_promote_fund_z_harvest_sign_hold is True
    assert settings.paper_promote_fund_z_harvest_sign_hold_active is True


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
async def test_promote_pin_opens_harvest_with_paper_perp() -> None:
    settings = Settings().model_copy(
        update={
            "paper_perp_hedge": True,
            "paper_promote_fund_z_harvest_sign_hold": True,
        }
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
    assert perp.positions["BTC"].side is Side.SELL
    assert spot.snapshot().nav_usd == pytest.approx(nav_before)
    assert FUND_Z_HARVEST_SIGN_HOLD_SIGNAL == "fund_z_harvest_sign_hold"
    assert CARRY_DIAGNOSTIC_NOTIONAL_USD == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_promote_pin_false_skips_even_with_paper_perp() -> None:
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
