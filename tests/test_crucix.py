import httpx
import pytest

from traderstack.cli import build_intelligence
from traderstack.config import Settings
from traderstack.features import NewsFeatures
from traderstack.intelligence import merge_external_intelligence
from traderstack.intelligence_orchestrator import ExternalIntelligence, IntelligenceOrchestrator
from traderstack.market.crucix import (
    DEFAULT_CRUCIX_BASE_URL,
    CrucixIntelProvider,
    crucix_effective_base_url,
    crucix_should_register,
    parse_crucix_alerts,
)
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.risk import RiskEngine


def test_crucix_registers_only_when_enabled_or_url_or_key() -> None:
    assert crucix_should_register(enabled=False, base_url="", api_key=None) is False
    assert crucix_should_register(enabled=False, base_url="  ", api_key="") is False
    assert crucix_should_register(enabled=True, base_url="", api_key=None) is True
    assert (
        crucix_should_register(enabled=False, base_url="http://127.0.0.1:9", api_key=None) is True
    )
    assert crucix_should_register(enabled=False, base_url="", api_key="secret") is True


def test_crucix_default_url_is_host_docker_internal() -> None:
    assert crucix_effective_base_url("") == DEFAULT_CRUCIX_BASE_URL
    assert DEFAULT_CRUCIX_BASE_URL.startswith("http://host.docker.internal:")
    assert crucix_effective_base_url("http://localhost:9000") == "http://localhost:9000"


def test_parse_crucix_high_tier_sets_adverse_and_event_score() -> None:
    snapshot = parse_crucix_alerts(
        {
            "alerts": [
                {"asset": "BTC", "tier": "high", "score": 0.9, "sentiment": -0.4},
                {"asset": "BTC", "tier": "low", "score": 0.1},
            ]
        },
        asset="BTC",
    )
    assert snapshot.adverse_event is True
    assert snapshot.event_score == pytest.approx(0.9)
    assert snapshot.item_count == 2
    assert snapshot.source_id == "crucix:alerts"


def test_parse_crucix_numeric_tier_and_critical_label() -> None:
    high = parse_crucix_alerts({"data": [{"symbol": "ETH", "tier": 5}]}, asset="ETH")
    assert high.adverse_event is True
    assert high.event_score >= 0.8
    critical = parse_crucix_alerts({"items": [{"level": "critical"}]}, asset="ETH")
    assert critical.adverse_event is True


def test_parse_crucix_low_tier_does_not_set_adverse() -> None:
    snapshot = parse_crucix_alerts(
        [{"tier": "low", "narrative": 0.3, "sentiment": 0.2}],
        asset="BTC",
    )
    assert snapshot.adverse_event is False
    assert snapshot.event_score == pytest.approx(0.3)


def test_parse_crucix_rejects_unknown_shape() -> None:
    with pytest.raises(TypeError):
        parse_crucix_alerts("nope", asset="BTC")
    with pytest.raises(TypeError):
        parse_crucix_alerts({"ok": True}, asset="BTC")


@pytest.mark.asyncio
async def test_crucix_provider_fetches_alerts_path() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/alerts"
        assert request.url.params["asset"] == "BTC"
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(200, json={"alerts": [{"tier": "medium", "score": 0.4}]})

    async with httpx.AsyncClient(
        base_url="http://crucix.test", transport=httpx.MockTransport(handler)
    ) as client:
        snapshot = await CrucixIntelProvider(
            base_url="http://crucix.test", api_key="k", client=client
        ).fetch("btc")

    assert snapshot.adverse_event is False
    assert snapshot.event_score == pytest.approx(0.4)


def test_build_intelligence_skips_crucix_by_default() -> None:
    orchestrator = build_intelligence(Settings())
    assert orchestrator is None


def test_build_intelligence_registers_crucix_when_enabled() -> None:
    orchestrator = build_intelligence(Settings(crucix_enabled=True))
    assert orchestrator is not None
    assert orchestrator.news == ()
    assert len(orchestrator.fail_closed_news) == 1


def test_build_intelligence_registers_crucix_when_url_set() -> None:
    orchestrator = build_intelligence(Settings(crucix_base_url="http://127.0.0.1:8787"))
    assert orchestrator is not None
    assert orchestrator.news == ()
    assert len(orchestrator.fail_closed_news) == 1


def test_build_intelligence_skips_blank_crucix_key_without_flag() -> None:
    assert build_intelligence(Settings(crucix_api_key="")) is None
    assert build_intelligence(Settings(crucix_api_key="   ")) is None


def test_crucix_adverse_event_only_adds_rejection() -> None:
    """High-tier Crucix news can only withhold risk, never raise notional."""
    pipeline = VerticalSlicePipeline(risk_engine=RiskEngine(Settings(kill_switch=False)))
    tick = MarketTick(
        source=MarketSource.KRAKEN, symbol="BTC/USD", bid=999.5, ask=1000.5, last=1000
    )
    refs = [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=1000)]
    portfolio = PortfolioSnapshot(
        nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000
    )
    news = parse_crucix_alerts({"alerts": [{"tier": "high", "score": 1.0}]}, asset="BTC")
    result = pipeline.process(
        tick,
        refs,
        portfolio,
        intelligence=ExternalIntelligence(asset="BTC", news=news),
    )
    assert result.rejection_reasons == ["adverse_news_event"]
    assert result.paper_order is None
    assert result.proposal is None
    assert result.feature_vector is not None
    assert result.feature_vector.news == NewsFeatures(event_score=1.0, adverse_event=True)


def test_crucix_merge_cannot_relax_news_features() -> None:
    from traderstack.features import MarketFeatures

    market = MarketFeatures(
        trend_4h=0.1, trend_1d=0.1, volatility_z=0.0, relative_volume=1.0, spread_bps=1.0
    )
    news = parse_crucix_alerts({"alerts": [{"tier": "low"}]}, asset="BTC")
    vector = merge_external_intelligence("BTC", market, news=news)
    assert vector.news.adverse_event is False
    assert vector.news.event_score == 0.0


@pytest.mark.asyncio
async def test_orchestrator_wraps_crucix_like_other_news() -> None:
    async def fetch(asset: str):
        return parse_crucix_alerts({"alerts": [{"tier": "high"}]}, asset=asset)

    bundle = await IntelligenceOrchestrator(fail_closed_news=(fetch,)).gather("BTC")
    assert bundle.news is not None
    assert bundle.news.adverse_event is True
    assert bundle.provider_unavailable is False


@pytest.mark.asyncio
async def test_orchestrator_crucix_outage_is_fail_closed() -> None:
    async def broken(asset: str):
        raise TimeoutError("crucix unreachable")

    bundle = await IntelligenceOrchestrator(fail_closed_news=(broken,)).gather("BTC")
    assert bundle.provider_unavailable is True
    assert bundle.news is None
