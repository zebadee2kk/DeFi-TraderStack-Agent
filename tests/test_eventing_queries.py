from datetime import UTC, datetime
from typing import Self

import pytest

from traderstack.eventing import PostgresRuntimeEventStore
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.runtime import RuntimeResult


def runtime_result(symbol: str = "BTC/USD", *, with_proposal: bool = False) -> RuntimeResult:
    pipeline = PipelineResult(accepted_market_data=with_proposal)
    if with_proposal:
        proposal = TradeProposal(
            strategy_id="s",
            asset="BTC",
            side=Side.BUY,
            confidence=0.6,
            requested_notional_usd=100,
            thesis="t",
            source_freshness_seconds=0,
        )
        risk_result = RiskResult(
            decision_id=proposal.decision_id,
            decision=RiskDecision.ALLOW,
            approved_notional_usd=100,
            policy_version="v1",
        )
        order = PaperOrderIntent(
            decision_id=str(proposal.decision_id), asset="BTC", side=Side.BUY, notional_usd=100
        )
        pipeline = PipelineResult(
            accepted_market_data=True, proposal=proposal, risk_result=risk_result, paper_order=order
        )
    return RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol=symbol,
            observed_at=datetime.now(UTC),
            bid=99,
            ask=101,
            last=100,
        ),
        references=[],
        pipeline=pipeline,
    )


class FakeCursorResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "FakeCursorResult":
        return self

    def all(self) -> list[dict]:
        return self._rows


class FakeConnection:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.executed_statements: list[object] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: object) -> FakeCursorResult:
        self.executed_statements.append(statement)
        return FakeCursorResult(self.rows)


class FakeEngine:
    def __init__(self, rows: list[dict]) -> None:
        self._connection = FakeConnection(rows)

    def connect(self) -> FakeConnection:
        return self._connection

    def begin(self) -> FakeConnection:
        return self._connection


def _row(result: RuntimeResult, decision_id: str | None) -> dict:
    return {
        "id": 1,
        "observed_at": datetime.now(UTC),
        "symbol": result.tick.symbol,
        "accepted_market_data": int(result.pipeline.accepted_market_data),
        "decision_id": decision_id,
        "payload": result.model_dump(mode="json"),
    }


@pytest.mark.asyncio
async def test_recent_selects_by_symbol_and_parses_rows_back_into_runtime_results() -> None:
    result = runtime_result("BTC/USD")
    engine = FakeEngine([_row(result, None)])
    store = PostgresRuntimeEventStore("postgresql+asyncpg://unused", engine=engine)  # type: ignore[arg-type]

    events = await store.recent("BTC/USD", limit=10)

    assert len(events) == 1
    assert events[0].tick.symbol == "BTC/USD"
    statement = engine._connection.executed_statements[0]
    sql = str(statement.compile())
    assert "runtime_events.symbol" in sql
    assert "ORDER BY" in sql
    assert "LIMIT" in sql


@pytest.mark.asyncio
async def test_recent_rejects_non_positive_limit() -> None:
    store = PostgresRuntimeEventStore("postgresql+asyncpg://unused", engine=FakeEngine([]))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="limit must be positive"):
        await store.recent("BTC/USD", limit=0)


@pytest.mark.asyncio
async def test_decision_trace_selects_by_decision_id_in_chronological_order() -> None:
    result = runtime_result("BTC/USD", with_proposal=True)
    decision_id = str(result.pipeline.proposal.decision_id)  # type: ignore[union-attr]
    engine = FakeEngine([_row(result, decision_id)])
    store = PostgresRuntimeEventStore("postgresql+asyncpg://unused", engine=engine)  # type: ignore[arg-type]

    events = await store.decision_trace(decision_id)

    assert len(events) == 1
    assert events[0].pipeline.proposal is not None
    assert str(events[0].pipeline.proposal.decision_id) == decision_id
    statement = engine._connection.executed_statements[0]
    sql = str(statement.compile())
    assert "runtime_events.decision_id" in sql
    assert "ASC" in sql.upper() or "ORDER BY" in sql


@pytest.mark.asyncio
async def test_call_persists_decision_id_from_proposal() -> None:
    result = runtime_result("BTC/USD", with_proposal=True)
    engine = FakeEngine([])
    store = PostgresRuntimeEventStore("postgresql+asyncpg://unused", engine=engine)  # type: ignore[arg-type]

    await store(result)

    statement = engine._connection.executed_statements[0]
    compiled = statement.compile()
    assert compiled.params["decision_id"] == str(result.pipeline.proposal.decision_id)  # type: ignore[union-attr]
