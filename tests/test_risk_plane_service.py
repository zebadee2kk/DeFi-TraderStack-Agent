"""Service-level wiring for the Epic 7 risk plane.

Covers the two hooks in ``service.py``: the kill switch is re-evaluated at the
start of every cycle, and every risk decision the cycle produced is appended to
the immutable audit trail.
"""

import json
from datetime import UTC, datetime

import pytest

from traderstack.agents.review import MetaAgentMode, MetaAgentReview
from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.config import Settings
from traderstack.killswitch import KillSwitch
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.pipeline import PipelineResult
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk_audit import JsonlRiskAuditTrail, verify_chain
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


class FakeRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self.result = result
        self.calls: list[tuple[str, bool]] = []

    async def run_once(self, symbol, portfolio, *, submit=False):
        self.calls.append((symbol, submit))
        return self.result


def tick() -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol="BTC/USD",
        observed_at=datetime.now(UTC),
        bid=19_990,
        ask=20_010,
        last=20_000,
    )


def proposal() -> TradeProposal:
    return TradeProposal(
        strategy_id="vertical-slice-v1",
        asset="BTC",
        side=Side.BUY,
        confidence=0.5,
        requested_notional_usd=100,
        thesis="deterministic test proposal",
        source_freshness_seconds=1,
    )


def runtime_result_with_decision() -> tuple[RuntimeResult, TradeProposal, RiskResult]:
    item = proposal()
    result = RiskResult(
        decision_id=item.decision_id,
        decision=RiskDecision.ALLOW,
        approved_notional_usd=100,
        reasons=[],
        policy_version="mvp-v1+abc123abc123",
    )
    return (
        RuntimeResult(
            tick=tick(),
            references=[],
            pipeline=PipelineResult(accepted_market_data=True, proposal=item, risk_result=result),
        ),
        item,
        result,
    )


def service(runtime, **overrides) -> ContinuousPaperService:
    values = {
        "runtime": runtime,
        "portfolio": InMemoryPortfolioBook(starting_nav_usd=10_000),
        "symbols": ("BTC/USD",),
        "error_backoff_seconds": 0,
    }
    values.update(overrides)
    return ContinuousPaperService(**values)  # type: ignore[arg-type]


# --- kill switch is evaluated every cycle ---------------------------------


class CountingKillSwitch(KillSwitch):
    refreshes: int = 0

    async def refresh(self) -> bool:
        type(self).refreshes += 1
        return await super().refresh()


@pytest.mark.asyncio
async def test_kill_switch_is_refreshed_at_the_start_of_every_cycle(tmp_path) -> None:
    result, _, _ = runtime_result_with_decision()
    runtime = FakeRuntime(result)
    CountingKillSwitch.refreshes = 0
    switch = CountingKillSwitch(sentinel_path=tmp_path / "KILL")
    svc = service(runtime, kill_switch=switch)

    await svc._run_symbol_safely("BTC/USD")
    await svc._run_symbol_safely("BTC/USD")

    assert CountingKillSwitch.refreshes == 2


@pytest.mark.asyncio
async def test_a_sentinel_created_mid_run_is_seen_on_the_next_cycle(tmp_path) -> None:
    """The switch is live: no restart is needed for an operator halt to bite."""

    sentinel = tmp_path / "KILL"
    result, _, _ = runtime_result_with_decision()
    switch = KillSwitch(sentinel_path=sentinel)
    svc = service(FakeRuntime(result), kill_switch=switch)

    await svc._run_symbol_safely("BTC/USD")
    assert switch.engaged is False

    sentinel.write_text("halt", encoding="utf-8")
    await svc._run_symbol_safely("BTC/USD")
    assert switch.engaged is True


# --- risk decisions reach the audit trail ---------------------------------


@pytest.mark.asyncio
async def test_every_risk_decision_is_recorded(tmp_path) -> None:
    path = tmp_path / "risk.jsonl"
    result, _, _ = runtime_result_with_decision()
    svc = service(
        FakeRuntime(result),
        risk_audit=JsonlRiskAuditTrail(path),
        settings=Settings(kill_switch=False),
    )

    await svc._run_symbol_safely("BTC/USD")
    await svc._run_symbol_safely("BTC/USD")

    verification = verify_chain(path)
    assert verification.valid is True
    assert verification.records == 2

    trail = JsonlRiskAuditTrail(path)
    trail._resume()
    assert trail._sequence == 1


@pytest.mark.asyncio
async def test_a_cycle_with_no_proposal_records_nothing(tmp_path) -> None:
    path = tmp_path / "risk.jsonl"
    result = RuntimeResult(
        tick=tick(), references=[], pipeline=PipelineResult(accepted_market_data=False)
    )
    svc = service(
        FakeRuntime(result),
        risk_audit=JsonlRiskAuditTrail(path),
        settings=Settings(kill_switch=False),
    )

    await svc._run_symbol_safely("BTC/USD")

    assert not path.exists()


@pytest.mark.asyncio
async def test_service_without_an_audit_trail_still_runs(tmp_path) -> None:
    result, _, _ = runtime_result_with_decision()
    svc = service(FakeRuntime(result))
    await svc._run_symbol_safely("BTC/USD")
    assert svc.health.healthy


@pytest.mark.asyncio
async def test_a_meta_agent_veto_is_visible_on_the_recorded_audit_line(tmp_path) -> None:
    """The service must carry RuntimeResult.meta_review/execution_status into
    the audit record, not only the risk engine's own (pre-veto) decision.
    """

    path = tmp_path / "risk.jsonl"
    result, _, risk_result = runtime_result_with_decision()
    assert risk_result.decision is RiskDecision.ALLOW
    vetoed = result.model_copy(
        update={
            "meta_review": MetaAgentReview(
                mode=MetaAgentMode.VETO,
                called=True,
                approved=False,
                prompt_version="v1",
                prompt_hash="sha256:deadbeef",
                suppressed_order=True,
                suppression_reason="meta_agent_veto",
            ),
            "execution_status": None,
            "execution_reason": "meta_agent_veto",
        }
    )
    svc = service(
        FakeRuntime(vetoed),
        risk_audit=JsonlRiskAuditTrail(path),
        settings=Settings(kill_switch=False),
    )

    await svc._run_symbol_safely("BTC/USD")

    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["result"]["decision"] == "allow"
    assert line["meta_review"]["suppressed_order"] is True
    assert line["meta_review"]["suppression_reason"] == "meta_agent_veto"
    assert line["execution_status"] is None
    assert line["execution_reason"] == "meta_agent_veto"


# --- breaker state is persisted in the checkpoint -------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_state_round_trips_through_the_checkpoint(tmp_path) -> None:
    path = tmp_path / "state" / "portfolio.json"
    breaker = StrategyCircuitBreaker(max_consecutive_losses=2, cooldown_seconds=3_600)
    for _ in range(2):
        breaker.record_closed_trade("momentum-v1", pnl_usd=-50, nav_usd=10_000, at=NOW)
    assert breaker.is_tripped("momentum-v1", NOW)

    store = JsonPortfolioCheckpointStore(path, circuit_breaker=breaker)
    await store.save(InMemoryPortfolioBook(starting_nav_usd=10_000))

    restarted = StrategyCircuitBreaker(max_consecutive_losses=2, cooldown_seconds=3_600)
    reloaded = JsonPortfolioCheckpointStore(path, circuit_breaker=restarted)
    book = await reloaded.load()

    assert book is not None
    # A restart does not clear a tripped strategy.
    assert restarted.is_tripped("momentum-v1", NOW)
    assert restarted.state_for("momentum-v1").trip_reason == "consecutive_losses"


@pytest.mark.asyncio
async def test_checkpoint_without_a_breaker_is_unchanged(tmp_path) -> None:
    path = tmp_path / "portfolio.json"
    store = JsonPortfolioCheckpointStore(path)
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    book.apply_fill("BTC", Side.BUY, quantity=0.1, price_usd=20_000)
    await store.save(book)

    reloaded = await store.load()
    assert reloaded is not None
    assert reloaded.positions["BTC"].quantity == pytest.approx(0.1)
