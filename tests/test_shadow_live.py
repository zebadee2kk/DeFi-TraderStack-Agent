"""Roadmap Phase 7: shadow-live records would-have-been orders and never submits."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from prometheus_client import REGISTRY

from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.cli import build_service
from traderstack.config import Settings, require_runtime_trading_mode
from traderstack.execution.hummingbot import HummingbotPaperExecutor
from traderstack.execution.shadow import (
    SHADOW_DUPLICATE,
    SHADOW_PLAN_REJECTED,
    SHADOW_RECORDED,
    ShadowLedger,
    ShadowRecorder,
)
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot, Side
from traderstack.pipeline import PaperOrderIntent, VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime, RuntimeResult


class FakeVenue:
    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        yield MarketTick(
            source=MarketSource.KRAKEN,
            symbol=symbols[0],
            observed_at=datetime.now(UTC),
            bid=99.95,
            ask=100.05,
            last=100,
        )


class MismatchedVenue:
    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        yield MarketTick(
            source=MarketSource.KRAKEN,
            symbol="ETH/USD",
            observed_at=datetime.now(UTC),
            bid=99.95,
            ask=100.05,
            last=100,
        )


class GoodReference:
    def __init__(self, source: MarketSource = MarketSource.COINGECKO, price: float = 100) -> None:
        self.source = source
        self.price = price

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=self.source, asset=assets[0], price=self.price)]


def portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=10_000,
        daily_pnl_usd=0,
        peak_nav_usd=10_000,
    )


def pipeline() -> VerticalSlicePipeline:
    return VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False)))


async def _noop(result: RuntimeResult) -> None:
    return None


def _intent() -> PaperOrderIntent:
    return PaperOrderIntent(decision_id="dec-1", asset="BTC", side=Side.BUY, notional_usd=100)


def test_require_runtime_trading_mode_rejects_live() -> None:
    with pytest.raises(RuntimeError, match="live capital is out of scope"):
        require_runtime_trading_mode("live")
    assert require_runtime_trading_mode("paper") == "paper"
    assert require_runtime_trading_mode("shadow") == "shadow"


@pytest.mark.asyncio
async def test_shadow_recorder_persists_a_planned_intent(tmp_path: Path) -> None:
    ledger = ShadowLedger(tmp_path / "shadow.jsonl")
    recorder = ShadowRecorder(ledger=ledger)
    recorded = await recorder.record(
        _intent(), execution_price_usd=100.0, reference_price_usd=100.0
    )

    assert recorded.status == SHADOW_RECORDED
    assert recorded.trading_mode == "shadow"
    assert recorded.quantity == pytest.approx(1.0)
    assert recorded.client_order_id
    assert ledger.has_decision("dec-1")
    lines = (tmp_path / "shadow.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert '"status":"shadow_recorded"' in lines[0]


@pytest.mark.asyncio
async def test_shadow_recorder_is_idempotent_per_decision(tmp_path: Path) -> None:
    ledger = ShadowLedger(tmp_path / "shadow.jsonl")
    recorder = ShadowRecorder(ledger=ledger)
    first = await recorder.record(_intent(), execution_price_usd=100.0, reference_price_usd=100.0)
    second = await recorder.record(_intent(), execution_price_usd=100.0, reference_price_usd=100.0)

    assert first.status == SHADOW_RECORDED
    assert second.status == SHADOW_DUPLICATE
    assert len(ledger.records) == 1


@pytest.mark.asyncio
async def test_shadow_recorder_records_planner_rejection(tmp_path: Path) -> None:
    ledger = ShadowLedger(tmp_path / "shadow.jsonl")
    recorder = ShadowRecorder(ledger=ledger)
    recorded = await recorder.record(
        _intent(), execution_price_usd=100.0, reference_price_usd=200.0
    )

    assert recorded.status == SHADOW_PLAN_REJECTED
    assert recorded.reason is not None
    assert "bps" in recorded.reason


@pytest.mark.asyncio
async def test_shadow_runtime_records_without_calling_the_venue(tmp_path: Path) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"detail": "should never be called"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="http://hummingbot", transport=transport) as client:
        executor = HummingbotPaperExecutor("http://hummingbot", "user", "pass", client=client)
        recorder = ShadowRecorder(ledger=ShadowLedger(tmp_path / "shadow.jsonl"))
        runtime = PaperRuntime(
            venue=FakeVenue(),
            references=(GoodReference(),),
            pipeline=pipeline(),
            executor=executor,
            trading_mode="shadow",
            shadow_recorder=recorder,
        )
        before = (
            REGISTRY.get_sample_value(
                "traderstack_shadow_intents_recorded_total",
                {"symbol": "BTC/USD", "side": "buy", "status": SHADOW_RECORDED},
            )
            or 0.0
        )
        result = await runtime.run_once("BTC/USD", portfolio(), submit=True)

    assert calls == 0
    assert result.execution_receipt is None
    assert result.trading_mode == "shadow"
    assert result.shadow_intent is not None
    assert result.shadow_intent.status == SHADOW_RECORDED
    assert result.execution_status == SHADOW_RECORDED
    assert result.pipeline.paper_order is not None
    assert recorder.ledger.has_decision(result.pipeline.paper_order.decision_id)
    after = (
        REGISTRY.get_sample_value(
            "traderstack_shadow_intents_recorded_total",
            {"symbol": "BTC/USD", "side": "buy", "status": SHADOW_RECORDED},
        )
        or 0.0
    )
    assert after == before + 1


@pytest.mark.asyncio
async def test_runtime_rejects_a_tick_for_the_wrong_symbol() -> None:
    runtime = PaperRuntime(
        venue=MismatchedVenue(),
        references=(GoodReference(),),
        pipeline=pipeline(),
    )
    with pytest.raises(RuntimeError, match="does not match requested"):
        await runtime.run_once("BTC/USD", portfolio())


def test_build_service_accepts_shadow_and_never_wires_hummingbot(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        trading_mode="shadow",
        hummingbot_api_username="user",
        hummingbot_api_password="secret",  # type: ignore[arg-type]
        pretrade_backtest_enabled=False,
    )
    ledger = ShadowLedger(tmp_path / "shadow.jsonl")
    service = build_service(
        settings,
        submit=True,
        cycle_seconds=1.0,
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        on_result=_noop,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
        shadow_ledger=ledger,
    )

    assert service.runtime.trading_mode == "shadow"
    assert service.runtime.shadow_recorder is not None
    assert service.runtime.shadow_recorder.ledger is ledger
    assert service.runtime.submitter is None
    assert service.runtime.executor is None
    assert service.execution_reconciler is None
    assert service.portfolio_reconciler is None
    assert service.submit is False
    assert service.submission_enabled is False


def test_build_service_still_rejects_live(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        trading_mode="live",
        pretrade_backtest_enabled=False,
    )
    with pytest.raises(RuntimeError, match="live capital is out of scope"):
        build_service(
            settings,
            submit=False,
            cycle_seconds=1.0,
            portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
            on_result=_noop,
            checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
        )
