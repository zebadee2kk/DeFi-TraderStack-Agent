"""The meta-agent's place in the live loop and in `build_service` (Epic 6)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from traderstack.agents.claude import AnthropicMetaAgentClient
from traderstack.agents.meta import EvidencePacket, MetaAgentDecision
from traderstack.agents.review import (
    UNAVAILABLE_REASON,
    VETO_REASON,
    EvidenceCache,
    MetaAgentMode,
    MetaAgentReviewer,
)
from traderstack.cli import build_meta_reviewer, build_service
from traderstack.config import Settings
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk import RiskEngine
from traderstack.runtime import PaperRuntime


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


class GoodReference:
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=MarketSource.COINGECKO, asset=assets[0], price=100)]


def portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000
    )


def runtime(reviewer: MetaAgentReviewer | None) -> PaperRuntime:
    return PaperRuntime(
        venue=FakeVenue(),
        references=(GoodReference(),),
        pipeline=VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False))),
        meta_reviewer=reviewer,
    )


def reviewer(mode: MetaAgentMode, client) -> MetaAgentReviewer:
    return MetaAgentReviewer(
        client=client, mode=mode, model="test-model", cache=EvidenceCache(ttl_seconds=0)
    )


async def vetoing(_: EvidencePacket) -> MetaAgentDecision:
    return MetaAgentDecision(approve=False, confidence_delta=0.0, rationale="no")


async def approving(_: EvidencePacket) -> MetaAgentDecision:
    return MetaAgentDecision(approve=True, confidence_delta=0.1, rationale="yes")


async def exploding(_: EvidencePacket) -> MetaAgentDecision:
    raise RuntimeError("provider down")


@pytest.mark.asyncio
async def test_runtime_records_a_review_without_a_reviewer_configured() -> None:
    result = await runtime(None).run_once("BTC/USD", portfolio())

    assert result.meta_review is None
    assert result.pipeline.paper_order is not None


@pytest.mark.asyncio
async def test_runtime_records_an_advisory_review_without_changing_execution() -> None:
    result = await runtime(reviewer(MetaAgentMode.ADVISORY, vetoing)).run_once(
        "BTC/USD", portfolio()
    )

    assert result.meta_review is not None
    assert result.meta_review.called is True
    assert result.meta_review.approved is False
    assert result.meta_review.model == "test-model"
    assert result.meta_review.prompt_hash.startswith("sha256:")
    assert result.pipeline.paper_order is not None


@pytest.mark.asyncio
async def test_runtime_suppresses_the_order_on_a_veto() -> None:
    result = await runtime(reviewer(MetaAgentMode.VETO, vetoing)).run_once(
        "BTC/USD", portfolio()
    )

    assert result.pipeline.paper_order is None
    assert VETO_REASON in result.pipeline.rejection_reasons
    assert result.execution_receipt is None


@pytest.mark.asyncio
async def test_runtime_fails_closed_when_the_reviewer_errors() -> None:
    result = await runtime(reviewer(MetaAgentMode.VETO, exploding)).run_once(
        "BTC/USD", portfolio()
    )

    assert result.pipeline.paper_order is None
    assert UNAVAILABLE_REASON in result.pipeline.rejection_reasons


@pytest.mark.asyncio
async def test_runtime_keeps_the_order_on_approval_and_applies_the_delta() -> None:
    result = await runtime(reviewer(MetaAgentMode.VETO, approving)).run_once(
        "BTC/USD", portfolio()
    )

    assert result.pipeline.paper_order is not None
    assert result.pipeline.proposal is not None
    # Pipeline baseline confidence is 0.5 without a pre-trade gate.
    assert result.pipeline.proposal.confidence == pytest.approx(0.6)
    assert result.meta_review is not None
    assert result.meta_review.applied_confidence == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_runtime_result_serialises_the_review_for_the_audit_trail() -> None:
    result = await runtime(reviewer(MetaAgentMode.ADVISORY, approving)).run_once(
        "BTC/USD", portfolio()
    )
    dumped = result.model_dump(mode="json")

    assert dumped["meta_review"]["prompt_version"]
    assert dumped["meta_review"]["evidence_digest"].startswith("sha256:")
    assert dumped["meta_review"]["mode"] == "advisory"


# --- CLI wiring -----------------------------------------------------------


def test_no_client_is_built_when_the_mode_is_off() -> None:
    settings = Settings(
        meta_agent_mode="off", anthropic_api_key=SecretStr("sk-test"), kill_switch=False
    )

    assert build_meta_reviewer(settings) is None


def test_no_client_is_built_in_advisory_mode_without_a_key() -> None:
    settings = Settings(meta_agent_mode="advisory", anthropic_api_key=None, kill_switch=False)

    assert build_meta_reviewer(settings) is None


def test_veto_mode_without_a_key_fails_at_startup() -> None:
    settings = Settings(meta_agent_mode="veto", anthropic_api_key=None, kill_switch=False)

    with pytest.raises(RuntimeError, match="requires ANTHROPIC_API_KEY"):
        build_meta_reviewer(settings)


def test_reviewer_is_built_from_settings() -> None:
    settings = Settings(
        meta_agent_mode="veto",
        anthropic_api_key=SecretStr("sk-test"),
        meta_agent_model="claude-haiku-4-5",
        meta_agent_max_calls_per_day=7,
        meta_agent_max_tokens_per_day=1_234,
        meta_agent_cache_seconds=42.0,
        meta_agent_timeout_seconds=3.0,
        kill_switch=False,
    )

    built = build_meta_reviewer(settings)

    assert built is not None
    assert built.mode is MetaAgentMode.VETO
    assert built.model == "claude-haiku-4-5"
    assert built.timeout_seconds == 3.0
    assert built.budget.max_calls == 7
    assert built.budget.max_tokens == 1_234
    assert built.cache.ttl_seconds == 42.0
    assert isinstance(built.client, AnthropicMetaAgentClient)
    assert built.client.model == "claude-haiku-4-5"
    assert built.committee is not None


def test_build_service_attaches_the_reviewer_to_the_runtime(tmp_path) -> None:
    from traderstack.checkpoint import JsonPortfolioCheckpointStore

    async def sink(_: object) -> None:
        return None

    settings = Settings(
        meta_agent_mode="advisory",
        anthropic_api_key=SecretStr("sk-test"),
        pretrade_backtest_enabled=False,
        kill_switch=False,
    )
    service = build_service(
        settings,
        submit=False,
        cycle_seconds=1.0,
        portfolio=InMemoryPortfolioBook(10_000),
        on_result=sink,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
    )

    assert service.runtime.meta_reviewer is not None
    assert service.runtime.meta_reviewer.mode is MetaAgentMode.ADVISORY
