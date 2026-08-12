import pytest
from pydantic import SecretStr

from traderstack.cli import build_intelligence, build_runtime, build_service
from traderstack.config import Settings
from traderstack.runtime import PaperRuntime, SignalPaperRuntime


def settings(**overrides) -> Settings:
    values = {"kill_switch": False}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_dune_queries_parse_valid_mapping() -> None:
    parsed = settings(dune_query_ids="BTC:123, eth:456 ,").dune_queries
    assert parsed == {"BTC": 123, "ETH": 456}


def test_dune_queries_empty_by_default() -> None:
    assert settings().dune_queries == {}


def test_dune_queries_reject_malformed_mapping() -> None:
    with pytest.raises(ValueError, match="invalid Dune query mapping"):
        _ = settings(dune_query_ids="BTC=123").dune_queries


def test_intelligence_disabled_without_credentials() -> None:
    assert build_intelligence(settings()) is None


def test_intelligence_enables_configured_providers() -> None:
    configured = settings(
        cryptopanic_api_key=SecretStr("news"),
        lunarcrush_api_key=SecretStr("social"),
        dune_api_key=SecretStr("dune"),
        dune_query_ids="BTC:123",
    )
    orchestrator = build_intelligence(configured)
    assert orchestrator is not None
    assert orchestrator.onchain is not None
    assert orchestrator.social is not None
    assert len(orchestrator.news) == 1


def test_dune_requires_query_ids() -> None:
    orchestrator = build_intelligence(settings(dune_api_key=SecretStr("dune")))
    assert orchestrator is None


def test_build_runtime_modes() -> None:
    assert isinstance(
        build_runtime(settings(), pipeline_mode="signal", submit=False, use_meta_agent=False),
        SignalPaperRuntime,
    )
    assert isinstance(
        build_runtime(settings(), pipeline_mode="demo", submit=False, use_meta_agent=False),
        PaperRuntime,
    )


def test_submit_requires_hummingbot_credentials() -> None:
    with pytest.raises(RuntimeError, match="Hummingbot API credentials"):
        build_runtime(settings(), pipeline_mode="signal", submit=True, use_meta_agent=False)


def test_meta_agent_requires_api_key() -> None:
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_runtime(settings(), pipeline_mode="signal", submit=False, use_meta_agent=True)


async def test_build_service_wires_reconciliation_for_submit_runs(tmp_path) -> None:
    from traderstack.checkpoint import JsonPortfolioCheckpointStore
    from traderstack.portfolio import InMemoryPortfolioBook
    from traderstack.runtime import RuntimeResult

    async def sink(result: RuntimeResult) -> None:
        return None

    configured = settings(
        hummingbot_api_username="user",
        hummingbot_api_password=SecretStr("pass"),
    )
    service = build_service(
        configured,
        submit=True,
        cycle_seconds=1.0,
        portfolio=InMemoryPortfolioBook(10_000),
        on_result=sink,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
    )
    assert service.execution_ledger is not None
    assert service.reconciler is not None
    assert service.reconcile_interval_seconds == pytest.approx(30.0)

    paper_only = build_service(
        configured,
        submit=False,
        cycle_seconds=1.0,
        portfolio=InMemoryPortfolioBook(10_000),
        on_result=sink,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio2.json"),
    )
    assert paper_only.execution_ledger is None
    assert paper_only.reconciler is None


async def test_ledger_checkpoint_round_trip(tmp_path) -> None:
    from traderstack.checkpoint import JsonLedgerCheckpointStore
    from traderstack.execution.ledger import ExecutionLedger, ExecutionOrder
    from traderstack.models import Side

    store = JsonLedgerCheckpointStore(tmp_path / "ledger.json")
    assert await store.load() is None

    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="o1", decision_id="d1", asset="BTC", side=Side.BUY, requested_quantity=1.0
        )
    )
    await store.save(ledger)

    restored = await store.load()
    assert restored is not None
    assert "o1" in restored.orders
