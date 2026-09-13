"""ContinuousPaperService keeps the opportunity funnel and honours diagnostic mode (#131)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from traderstack.execution.ledger import ExecutionLedger, OrderLifecycleState
from traderstack.execution.paper_fill import PaperFillSimulator
from traderstack.killswitch import KillSwitch
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.opportunity_funnel import (
    DIAGNOSTIC_WITHHELD_STATUS,
    BlockingGate,
    FunnelStage,
    OpportunityFunnelReport,
)
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService


class FakeRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result
        self.calls: list[tuple[str, bool]] = []

    async def run_once(self, symbol, portfolio, *, submit=False):
        self.calls.append((symbol, submit))
        return self.result


def _tick() -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC),
        bid=19_990,
        ask=20_010,
        last=20_000,
    )


def _allowed_result() -> RuntimeResult:
    proposal = TradeProposal(
        strategy_id="vertical-slice-v1",
        asset="BTC",
        side=Side.BUY,
        confidence=0.6,
        requested_notional_usd=1_000,
        thesis="fixture",
        source_freshness_seconds=0.5,
    )
    return RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            proposal=proposal,
            risk_result=RiskResult(
                decision_id=proposal.decision_id,
                decision=RiskDecision.ALLOW,
                approved_notional_usd=1_000,
                policy_version="mvp-v1+fixture",
            ),
            paper_order=PaperOrderIntent(
                decision_id=str(proposal.decision_id),
                asset="BTC",
                side=Side.BUY,
                notional_usd=1_000,
            ),
        ),
        trading_mode="paper",
    )


def _rejected_result() -> RuntimeResult:
    return RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=False, rejection_reasons=["stale_primary_tick"]
        ),
    )


@pytest.mark.asyncio
async def test_service_observes_every_cycle_into_the_funnel(tmp_path: Path) -> None:
    ledger = ExecutionLedger()
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        symbols=("BTC/USD",),
        execution_ledger=ledger,
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0),
        opportunity_funnel_path=tmp_path / "ops" / "opportunity_funnel.json",
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")
    service.runtime.result = _rejected_result()  # type: ignore[attr-defined]
    await service._run_symbol_safely("BTC/USD")

    report = service.opportunity_funnel.snapshot()
    assert report.totals.stage_count(FunnelStage.CYCLE) == 2
    assert report.totals.stage_count(FunnelStage.FILLED) == 1
    assert report.totals.blocked_by_gate == {"market_data": 1}
    assert report.paper_fills_enabled is True
    assert report.submission_enabled is False
    assert report.diagnostic_mode is False
    assert report.tick_age_seconds.samples == 2
    persisted = OpportunityFunnelReport.model_validate_json(
        (tmp_path / "ops" / "opportunity_funnel.json").read_text(encoding="utf-8")
    )
    assert persisted.totals == report.totals


@pytest.mark.asyncio
async def test_diagnostic_mode_withholds_the_paper_fill_and_explains_it() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    ledger = ExecutionLedger()
    seen: list[RuntimeResult] = []

    async def on_result(result: RuntimeResult) -> None:
        seen.append(result)

    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=True,
        execution_ledger=ledger,
        paper_fill_simulator=PaperFillSimulator(paper_fee_bps=10.0, paper_slippage_bps=5.0),
        on_result=on_result,
        diagnostic_mode=True,
        error_backoff_seconds=0,
    )

    await service._run_symbol_safely("BTC/USD")

    # No venue submit, no paper fill, no ledger row, NAV untouched.
    assert service.runtime.calls == [("BTC/USD", False)]  # type: ignore[attr-defined]
    assert service.submission_enabled is False
    assert service.paper_fill_enabled is False
    assert ledger.orders == {}
    assert book.nav_usd == pytest.approx(10_000)
    assert not any(order.state is OrderLifecycleState.FILLED for order in ledger.orders.values())
    assert seen[0].execution_status == DIAGNOSTIC_WITHHELD_STATUS
    assert "diagnostic mode" in (seen[0].execution_reason or "")

    report = service.opportunity_funnel.snapshot()
    assert report.diagnostic_mode is True
    assert report.totals.stage_count(FunnelStage.META_AGENT_RETAINED) == 1
    assert report.totals.stage_count(FunnelStage.FILLED) == 0
    assert report.totals.blocked_by_gate == {BlockingGate.FILL.value: 1}
    assert report.reasons_by_gate["fill"] == {DIAGNOSTIC_WITHHELD_STATUS: 1}
    assert report.diagnosis.category == "fill_unavailable"
    assert "by design" in report.diagnosis.verdict


@pytest.mark.asyncio
async def test_diagnostic_mode_keeps_the_kill_switch_as_the_first_explanation() -> None:
    service = ContinuousPaperService(
        runtime=FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(),
        kill_switch=KillSwitch(settings_flag=True),
        diagnostic_mode=True,
        error_backoff_seconds=0,
    )
    seen: list[RuntimeResult] = []

    async def on_result(result: RuntimeResult) -> None:
        seen.append(result)

    service.on_result = on_result
    await service._run_symbol_safely("BTC/USD")
    assert seen[0].execution_status == DIAGNOSTIC_WITHHELD_STATUS
    assert "kill switch engaged" in (seen[0].execution_reason or "")


@pytest.mark.asyncio
async def test_a_funnel_write_failure_never_fails_the_cycle(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    service = ContinuousPaperService(
        runtime=FakeRuntime(_rejected_result()),  # type: ignore[arg-type]
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        symbols=("BTC/USD",),
        opportunity_funnel_path=blocker / "opportunity_funnel.json",
        error_backoff_seconds=0,
    )
    await service._run_symbol_safely("BTC/USD")
    assert service.health.consecutive_errors == 0
    assert service.opportunity_funnel.snapshot().totals.stage_count(FunnelStage.CYCLE) == 1
