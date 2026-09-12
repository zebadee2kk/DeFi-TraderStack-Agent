"""Paper daily promote path: cycle only the BTC+ETH research envelope.

#100 honesty pack: ``ema_9_21_adx15`` (and ``ema_9_21``) cleared harder
gates on Kraken daily BTC+ETH. SOL WF maxDD ~50% is outside
``PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT=0.30``. SOL stays in
``MVP_ASSETS`` so the flag-off paper path and RiskEngine allowlist are
unchanged; the promote path must not trade that name under the envelope.

This is universe alignment, not a claim of edge. Pins stay default false.
Live/shadow ignore the pins and keep the full mvp list.
"""

from __future__ import annotations

from datetime import UTC, datetime

from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.cli import build_service
from traderstack.cli_check import build_report
from traderstack.config import PAPER_PROMOTE_UNIVERSE_SYMBOLS, Settings
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import HeldPosition, PortfolioSnapshot, RiskDecision, Side, TradeProposal
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk import RiskEngine, derive_policy_version
from traderstack.runtime import RuntimeResult

NOW = datetime(2026, 9, 12, 15, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "kill_switch": False,
        "pretrade_backtest_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _tick(symbol: str, last: float = 1_000.0) -> MarketTick:
    half = last * 0.0005  # ~10 bps, inside MAX_SPREAD_BPS=30
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol=symbol,
        observed_at=NOW,
        bid=last - half,
        ask=last + half,
        last=last,
    )


def _refs(asset: str, price: float = 1_000.0) -> list[ReferencePrice]:
    return [ReferencePrice(source=MarketSource.COINGECKO, asset=asset, price=price)]


def _flat_book() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=10_000,
        daily_pnl_usd=0,
        peak_nav_usd=10_000,
    )


async def _noop(result: RuntimeResult) -> None:
    return None


def test_promote_universe_default_is_btc_eth_and_pins_stay_off() -> None:
    settings = _settings()
    assert settings.paper_promote_ema_9_21 is False
    assert settings.paper_promote_ema_9_21_adx15 is False
    assert settings.paper_daily_promote_active is False
    assert settings.paper_promote_universe == "BTC/USD,ETH/USD"
    assert settings.configured_promote_universe_symbols == PAPER_PROMOTE_UNIVERSE_SYMBOLS
    assert settings.effective_cycle_symbols == ("BTC/USD", "ETH/USD", "SOL/USD")
    assert settings.assets == ("BTC", "ETH", "SOL")


def test_promote_paper_cycles_only_btc_eth() -> None:
    ema = _settings(paper_promote_ema_9_21=True)
    adx = _settings(paper_promote_ema_9_21_adx15=True)
    for settings in (ema, adx):
        assert settings.paper_daily_promote_active is True
        assert settings.effective_cycle_symbols == ("BTC/USD", "ETH/USD")
        assert settings.promote_universe_allows("BTC/USD") is True
        assert settings.promote_universe_allows("ETH/USD") is True
        assert settings.promote_universe_allows("SOL/USD") is False
        assert settings.assets == ("BTC", "ETH", "SOL")


def test_non_promote_paper_still_cycles_sol() -> None:
    settings = _settings(trading_mode="paper")
    assert "SOL/USD" in settings.effective_cycle_symbols
    assert settings.promote_universe_allows("SOL/USD") is True


def test_live_and_shadow_ignore_promote_universe() -> None:
    for mode in ("live", "shadow"):
        for pin in (
            {"paper_promote_ema_9_21": True},
            {"paper_promote_ema_9_21_adx15": True},
        ):
            settings = _settings(trading_mode=mode, **pin)
            assert settings.paper_daily_promote_active is False
            assert settings.effective_cycle_symbols == ("BTC/USD", "ETH/USD", "SOL/USD")
            assert settings.promote_universe_allows("SOL/USD") is True


def test_extra_universe_names_cannot_expand_past_btc_eth() -> None:
    settings = _settings(
        paper_promote_ema_9_21=True,
        paper_promote_universe="BTC/USD,ETH/USD,SOL/USD,DOGE/USD",
    )
    assert settings.configured_promote_universe_symbols == (
        "BTC/USD",
        "ETH/USD",
        "SOL/USD",
        "DOGE/USD",
    )
    assert settings.effective_promote_universe_symbols == ("BTC/USD", "ETH/USD")
    assert settings.effective_cycle_symbols == ("BTC/USD", "ETH/USD")
    assert settings.promote_universe_allows("SOL/USD") is False


def test_asset_tokens_in_universe_are_normalized_to_usd_symbols() -> None:
    settings = _settings(paper_promote_ema_9_21=True, paper_promote_universe="BTC,ETH")
    assert settings.configured_promote_universe_symbols == ("BTC/USD", "ETH/USD")
    assert settings.effective_cycle_symbols == ("BTC/USD", "ETH/USD")


def test_universe_can_narrow_but_not_below_mvp_intersection() -> None:
    btc_only = _settings(paper_promote_ema_9_21=True, paper_promote_universe="BTC/USD")
    assert btc_only.effective_cycle_symbols == ("BTC/USD",)
    eth_missing = _settings(
        paper_promote_ema_9_21=True,
        mvp_assets="BTC,SOL",
        paper_promote_universe="BTC/USD,ETH/USD",
    )
    assert eth_missing.effective_cycle_symbols == ("BTC/USD",)


def test_pipeline_rejects_sol_on_promote_paper() -> None:
    settings = _settings(paper_promote_ema_9_21=True)
    pipe = VerticalSlicePipeline(risk_engine=RiskEngine(settings))
    result = pipe.process(_tick("SOL/USD"), _refs("SOL"), _flat_book(), now=NOW)
    assert result.accepted_market_data is True
    assert result.rejection_reasons == ["promote_universe_excluded"]
    assert result.proposal is None
    assert result.paper_order is None
    assert result.risk_result is None


def test_pipeline_rejects_sol_on_adx15_promote_paper() -> None:
    settings = _settings(paper_promote_ema_9_21_adx15=True)
    pipe = VerticalSlicePipeline(risk_engine=RiskEngine(settings))
    result = pipe.process(_tick("SOL/USD"), _refs("SOL"), _flat_book(), now=NOW)
    assert result.rejection_reasons == ["promote_universe_excluded"]
    assert result.paper_order is None


def test_pipeline_still_proposes_btc_and_eth_on_promote_paper() -> None:
    settings = _settings(paper_promote_ema_9_21=True)
    pipe = VerticalSlicePipeline(risk_engine=RiskEngine(settings))
    for symbol, asset in (("BTC/USD", "BTC"), ("ETH/USD", "ETH")):
        result = pipe.process(_tick(symbol), _refs(asset), _flat_book(), now=NOW)
        assert "promote_universe_excluded" not in result.rejection_reasons
        assert result.paper_order is not None
        assert result.paper_order.asset == asset


def test_pipeline_still_cycles_sol_when_promote_is_off() -> None:
    settings = _settings()
    pipe = VerticalSlicePipeline(risk_engine=RiskEngine(settings))
    result = pipe.process(_tick("SOL/USD"), _refs("SOL"), _flat_book(), now=NOW)
    assert "promote_universe_excluded" not in result.rejection_reasons
    assert result.paper_order is not None
    assert result.paper_order.asset == "SOL"


def test_live_pipeline_does_not_emit_promote_universe_excluded() -> None:
    settings = _settings(trading_mode="live", paper_promote_ema_9_21=True)
    pipe = VerticalSlicePipeline(risk_engine=RiskEngine(settings))
    result = pipe.process(_tick("SOL/USD"), _refs("SOL"), _flat_book(), now=NOW)
    assert "promote_universe_excluded" not in result.rejection_reasons
    assert result.paper_order is not None


def test_promote_universe_does_not_block_a_leftover_sol_exit() -> None:
    settings = _settings(
        paper_promote_ema_9_21=True,
        exit_stop_loss_pct=0.02,
        exit_take_profit_pct=0.0,
        exit_trailing_stop_pct=0.0,
        exit_time_stop_bars=0,
        exit_on_thesis_invalidation=False,
    )
    held = HeldPosition(
        quantity=10.0,
        average_cost_usd=100.0,
        exposure_usd=900.0,
        opened_at=NOW,
        high_water_price_usd=100.0,
        entry_strategy_id="ema_9_21",
    )
    book = PortfolioSnapshot(
        nav_usd=10_000,
        cash_usd=9_100,
        daily_pnl_usd=0,
        peak_nav_usd=10_000,
        asset_exposure_usd={"SOL": 900.0},
        held_positions={"SOL": held},
    )
    pipe = VerticalSlicePipeline(risk_engine=RiskEngine(settings))
    result = pipe.process(_tick("SOL/USD", last=90.0), _refs("SOL", 90.0), book, now=NOW)
    assert result.exit_reason == "exit_stop_loss"
    assert result.proposal is not None
    assert result.proposal.side is Side.SELL
    assert result.proposal.asset == "SOL"
    assert "promote_universe_excluded" not in result.rejection_reasons
    assert result.paper_order is not None


def test_build_service_promote_paper_cycles_only_btc_eth(tmp_path) -> None:
    settings = _settings(paper_promote_ema_9_21=True, mvp_assets="BTC,ETH,SOL")
    service = build_service(
        settings,
        submit=False,
        cycle_seconds=1.0,
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        on_result=_noop,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
    )
    assert service.symbols == ("BTC/USD", "ETH/USD")


def test_build_service_non_promote_paper_still_cycles_sol(tmp_path) -> None:
    settings = _settings(mvp_assets="BTC,ETH,SOL")
    service = build_service(
        settings,
        submit=False,
        cycle_seconds=1.0,
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        on_result=_noop,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
    )
    assert service.symbols == ("BTC/USD", "ETH/USD", "SOL/USD")


def test_check_config_prints_promote_universe_on_daily_pin() -> None:
    report = build_report(_settings(paper_promote_ema_9_21=True))
    item = next(i for i in report.items if i.label == "Paper promote universe")
    assert item.value == "BTC/USD, ETH/USD"
    assert "#100" in item.detail
    assert "promote_universe_excluded" in item.detail


def test_check_config_warns_when_universe_tries_to_add_sol() -> None:
    report = build_report(
        _settings(
            paper_promote_ema_9_21=True,
            paper_promote_universe="BTC/USD,ETH/USD,SOL/USD",
        )
    )
    assert not report.safe
    assert any("SOL/USD" in warning and "#100" in warning for warning in report.warnings)


def test_check_config_warns_when_promote_universe_is_empty() -> None:
    report = build_report(_settings(paper_promote_ema_9_21=True, paper_promote_universe="SOL/USD"))
    assert not report.safe
    assert any("empty" in warning for warning in report.warnings)


def test_promote_universe_is_not_risk_engine_policy() -> None:
    baseline = _settings()
    pinned = _settings(
        paper_promote_ema_9_21=True,
        paper_promote_universe="BTC/USD",
    )
    assert derive_policy_version(baseline) == derive_policy_version(pinned)
    engine = RiskEngine(pinned)
    proposal_ok = engine.evaluate(
        TradeProposal(
            strategy_id="vertical-slice-v1",
            asset="SOL",
            side=Side.BUY,
            confidence=0.5,
            requested_notional_usd=100.0,
            thesis="universe is not Zone C",
            source_freshness_seconds=0.0,
        ),
        _flat_book(),
        now=NOW,
    )
    assert proposal_ok.decision is RiskDecision.ALLOW
    assert "asset_not_allowlisted" not in proposal_ok.reasons
