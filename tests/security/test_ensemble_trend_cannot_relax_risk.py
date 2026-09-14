"""The #137 ensemble-trend voter cannot relax Zone C controls.

It is long-only with a score in [0, 1]; the pipeline's requested notional
is fixed before RiskEngine.evaluate, so a larger score cannot size a trade
upward; the kill switch still withholds after consensus; no promote flag
was added; and TRADING_MODE=live is still rejected by cli.build_service.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.backtest import BaselineBacktester
from traderstack.candles import Candle
from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.cli import build_service, paper_research_ensemble
from traderstack.config import Settings
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.market_features import CandleMarketFeatureBuilder
from traderstack.models import PortfolioSnapshot, RiskDecision, Side
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.pretrade import PreTradeBacktestGate
from traderstack.research.ensemble_trend import (
    MAX_LEVERAGE,
    EnsembleTrendVoter,
    build_ensemble_trend_paper_ensemble,
    ensemble_trend_series,
)
from traderstack.risk import RiskEngine, derive_policy_version
from traderstack.strategies import Regime, StrategyEnsemble


async def _noop(_result: object) -> None:
    return None


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def daily_uptrend(count: int = 420, *, sigma: float = 0.02, seed: int = 9) -> tuple[Candle, ...]:
    """Daily bars ending now, with a fresh breakout on the final bar."""
    rng = random.Random(seed)
    prices = [100.0]
    for _ in range(count - 2):
        prices.append(max(1.0, prices[-1] * (1.0 + rng.gauss(0.003, sigma))))
    prices.append(max(prices) * 1.05)  # close[t] > every prior max close
    now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    candles: list[Candle] = []
    previous = prices[0]
    for index, close in enumerate(prices):
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1d",
                opened_at=now - timedelta(days=count - index),
                open=previous,
                high=max(previous, close) * 1.002,
                low=min(previous, close) * 0.998,
                close=close,
                volume=5_000_000.0,
            )
        )
        previous = close
    return tuple(candles)


def _lenient_gate(settings: Settings, ensemble: StrategyEnsemble) -> PreTradeBacktestGate:
    return PreTradeBacktestGate(
        backtester=BaselineBacktester(
            starting_equity=settings.paper_starting_nav_usd,
            ensemble=ensemble,
        ),
        min_candles=250,
        max_candle_age_seconds=7 * 86_400.0,  # daily bars; last bar closed yesterday
        min_excess_return=-10.0,
        max_drawdown=0.99,
        min_sharpe=-100.0,
        min_trades=0,
        require_walkforward=False,
        min_walkforward_excess_return=-10.0,
    )


def _process(settings: Settings, ensemble: StrategyEnsemble, candles: tuple[Candle, ...]):
    last = candles[-1].close
    pipeline = VerticalSlicePipeline(
        risk_engine=RiskEngine(settings),
        pretrade_gate=_lenient_gate(settings, ensemble),
        feature_builder=CandleMarketFeatureBuilder(),
        max_tick_age_seconds=30.0,
    )
    return pipeline.process(
        MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            bid=last * 0.9995,
            ask=last * 1.0005,
            last=last,
        ),
        [ReferencePrice(source=MarketSource.COINGECKO, asset="BTC", price=last)],
        PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000),
        candles=candles,
    )


def test_voter_weight_cannot_exceed_one_under_tiny_vol() -> None:
    # Near-zero realised vol would imply a huge vol-target multiplier; the
    # book is capped at MAX_LEVERAGE=1.0 and never invents leverage.
    calm = tuple(
        Candle(
            symbol="BTC/USD",
            interval="1d",
            opened_at=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
            open=100.0 * (1.0001 ** max(index - 1, 0)),
            high=100.0 * (1.0001**index) * 1.001,
            low=100.0 * (1.0001 ** max(index - 1, 0)) * 0.999,
            close=100.0 * (1.0001**index),
            volume=5_000_000.0,
        )
        for index in range(400)
    )
    series = ensemble_trend_series(calm)
    assert series
    assert max(weight for _ts, weight, _n in series) <= MAX_LEVERAGE == 1.0
    signal = EnsembleTrendVoter(strategy_id="ens_trend_9lb_vt25").evaluate(calm, Regime.RANGE)
    assert signal.side is Side.BUY
    assert signal.score <= 1.0
    assert signal.confidence <= 1.0
    # Explicit near-zero vol path: scalar caps at 1.0.
    assert min(0.25 / 1e-9, MAX_LEVERAGE) == 1.0


def test_paper_ensemble_cannot_increase_approved_notional() -> None:
    settings = _settings(trading_mode="paper", paper_research_mode=True, kill_switch=False)
    candles = daily_uptrend()
    ensemble = build_ensemble_trend_paper_ensemble()
    assert ensemble.suppress_defaults is True
    assert ensemble.min_agreeing == 1
    assert [voter.strategy_id for voter in ensemble.extra_voters] == ["ens_trend_9lb_vt25"]
    voted = ensemble.extra_voters[0].evaluate(candles, Regime.TRENDING_UP)  # type: ignore[attr-defined]
    assert voted.side is Side.BUY and 0.0 < voted.score <= 1.0

    research = _process(settings, ensemble, candles)
    baseline = _process(settings, paper_research_ensemble(settings), candles)
    assert research.pretrade_check is not None and research.pretrade_check.passed
    assert research.proposal is not None and research.risk_result is not None
    assert baseline.proposal is not None and baseline.risk_result is not None
    assert research.proposal.side is Side.BUY
    # Sizing is fixed by the pipeline (1% of NAV) before RiskEngine.evaluate;
    # the ensemble's score cannot lift it, and the engine can only reduce.
    assert research.proposal.requested_notional_usd == baseline.proposal.requested_notional_usd
    assert research.risk_result.approved_notional_usd <= research.proposal.requested_notional_usd
    assert research.risk_result.approved_notional_usd == baseline.risk_result.approved_notional_usd
    assert research.risk_result.policy_version == baseline.risk_result.policy_version
    assert research.risk_result.policy_version == derive_policy_version(settings)


def test_kill_switch_still_withholds_after_ensemble_consensus() -> None:
    settings = _settings(trading_mode="paper", paper_research_mode=True, kill_switch=True)
    result = _process(settings, build_ensemble_trend_paper_ensemble(), daily_uptrend())
    assert result.pretrade_check is not None and result.pretrade_check.passed
    assert result.proposal is not None
    assert result.risk_result is not None
    assert result.risk_result.decision is RiskDecision.REJECT
    assert "kill_switch_enabled" in result.risk_result.reasons
    assert result.paper_order is None


def test_no_new_promote_flag_and_live_mode_ignores_builder(tmp_path: Path) -> None:
    assert not any(name.startswith("paper_promote_ens") for name in Settings.model_fields)
    for name, field in Settings.model_fields.items():
        if name.startswith("paper_promote_") and field.annotation is bool:
            assert field.default is False, name
    cli_source = Path("src/traderstack/cli.py").read_text()
    assert "build_ensemble_trend_paper_ensemble" not in cli_source
    assert "ensemble_trend" not in cli_source
    live = Settings(
        _env_file=None,  # type: ignore[call-arg]
        trading_mode="live",
        pretrade_backtest_enabled=False,
    )
    with pytest.raises(RuntimeError, match="live capital is out of scope"):
        build_service(
            live,
            submit=False,
            cycle_seconds=1.0,
            portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
            on_result=_noop,  # type: ignore[arg-type]
            checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
        )
