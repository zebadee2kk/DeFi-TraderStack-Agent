"""Diagnostic mode (#131) can only withhold. It is not a risk-plane input.

``OPPORTUNITY_DIAGNOSTIC_MODE`` explains where cycles stop. It must never
move a limit, change a risk decision, alter ``policy_version``, enable a
submission the reconciliation/durability gates would refuse, or let an
approved order fill when the kill switch is engaged.
"""

from __future__ import annotations

from datetime import UTC, datetime

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.paper_fill import PaperFillSimulator
from traderstack.features import AssetFeatureVector, MarketFeatures
from traderstack.killswitch import KillSwitch
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import PortfolioSnapshot, RiskDecision, RiskResult, Side, TradeProposal
from traderstack.opportunity_funnel import DIAGNOSTIC_WITHHELD_STATUS
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk import RISK_LIMIT_FIELDS, RiskEngine, risk_limits
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _proposal() -> TradeProposal:
    return TradeProposal(
        strategy_id="vertical-slice-v1",
        asset="BTC",
        side=Side.BUY,
        confidence=0.6,
        requested_notional_usd=500,
        thesis="fixture",
        source_freshness_seconds=1.0,
    )


def _snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000)


def _features() -> AssetFeatureVector:
    return AssetFeatureVector(
        asset="BTC",
        market=MarketFeatures(
            trend_4h=0.0, trend_1d=0.0, volatility_z=0.0, relative_volume=1.0, spread_bps=5.0
        ),
    )


def test_diagnostic_mode_is_not_a_risk_limit_and_does_not_move_policy_version() -> None:
    assert "opportunity_diagnostic_mode" not in RISK_LIMIT_FIELDS
    off = _settings(opportunity_diagnostic_mode=False)
    on = _settings(opportunity_diagnostic_mode=True)
    assert risk_limits(off) == risk_limits(on)
    assert RiskEngine(off).policy_version == RiskEngine(on).policy_version


def test_diagnostic_mode_does_not_change_the_risk_decision_or_notional() -> None:
    proposal = _proposal()
    off = RiskEngine(_settings(opportunity_diagnostic_mode=False, kill_switch=False)).evaluate(
        proposal, _snapshot(), _features()
    )
    on = RiskEngine(_settings(opportunity_diagnostic_mode=True, kill_switch=False)).evaluate(
        proposal, _snapshot(), _features()
    )
    assert on.decision is off.decision
    assert on.approved_notional_usd == off.approved_notional_usd
    assert on.reasons == off.reasons


class _FakeRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result
        self.calls: list[tuple[str, bool]] = []

    async def run_once(self, symbol, portfolio, *, submit=False):
        self.calls.append((symbol, submit))
        return self.result


def _allowed_result() -> RuntimeResult:
    proposal = _proposal()
    return RuntimeResult(
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
            proposal=proposal,
            risk_result=RiskResult(
                decision_id=proposal.decision_id,
                decision=RiskDecision.ALLOW,
                approved_notional_usd=500,
                policy_version="mvp-v1+fixture",
            ),
            paper_order=PaperOrderIntent(
                decision_id=str(proposal.decision_id), asset="BTC", side=Side.BUY, notional_usd=500
            ),
        ),
    )


async def test_diagnostic_mode_never_submits_or_fills_even_with_submit_requested() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    ledger = ExecutionLedger()
    runtime = _FakeRuntime(_allowed_result())
    service = ContinuousPaperService(
        runtime=runtime,  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        submit=True,
        execution_ledger=ledger,
        paper_fill_simulator=PaperFillSimulator(),
        diagnostic_mode=True,
        error_backoff_seconds=0,
    )
    for _ in range(3):
        await service._run_symbol_safely("BTC/USD")
    assert runtime.calls == [("BTC/USD", False)] * 3
    assert ledger.orders == {}
    assert ledger.processed_fill_ids == set()
    assert book.nav_usd == 10_000
    assert book.positions.get("BTC") is None


async def test_diagnostic_mode_cannot_reopen_a_reconciliation_or_durability_block() -> None:
    service = ContinuousPaperService(
        runtime=_FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        symbols=("BTC/USD",),
        submit=True,
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(),
        diagnostic_mode=True,
    )
    service.health.record_reconciliation_failure("venue unanswered")
    assert service.submission_enabled is False
    assert service.paper_fill_enabled is False
    service.health.record_durable_state_failure("torn ledger")
    assert service.submission_enabled is False
    assert service.paper_fill_enabled is False
    # Turning diagnostic mode off again does not lift those blocks either.
    service.diagnostic_mode = False
    assert service.submission_enabled is False
    assert service.paper_fill_enabled is False


async def test_kill_switch_still_withholds_under_diagnostic_mode() -> None:
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    seen: list[RuntimeResult] = []

    async def on_result(result: RuntimeResult) -> None:
        seen.append(result)

    service = ContinuousPaperService(
        runtime=_FakeRuntime(_allowed_result()),  # type: ignore[arg-type]
        portfolio=book,
        symbols=("BTC/USD",),
        execution_ledger=ExecutionLedger(),
        paper_fill_simulator=PaperFillSimulator(),
        kill_switch=KillSwitch(settings_flag=True),
        diagnostic_mode=True,
        on_result=on_result,
        error_backoff_seconds=0,
    )
    await service._run_symbol_safely("BTC/USD")
    assert book.nav_usd == 10_000
    assert seen[0].execution_status == DIAGNOSTIC_WITHHELD_STATUS
    assert "kill switch engaged" in (seen[0].execution_reason or "")


def test_diagnostic_mode_cannot_enable_live() -> None:
    settings = _settings(trading_mode="live", opportunity_diagnostic_mode=True)
    from traderstack.cli import build_service

    try:
        build_service(
            settings,
            submit=False,
            cycle_seconds=0,
            portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
            on_result=None,
            checkpoint_store=None,  # type: ignore[arg-type]
        )
    except (RuntimeError, ValueError) as exc:
        assert "live" in str(exc).lower()
    else:  # pragma: no cover - the assertion above is the test
        raise AssertionError("live trading mode must be refused regardless of diagnostic mode")
