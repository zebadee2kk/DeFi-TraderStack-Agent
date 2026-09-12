from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.cli import build_pretrade_gate
from traderstack.config import (
    EMA_9_21_PAPER_CANDLE_INTERVAL,
    EMA_9_21_PAPER_KRAKEN_INTERVAL_MINUTES,
    EMA_9_21_PAPER_MAX_CANDLE_AGE_SECONDS,
    EMA_9_21_PAPER_MAX_DRAWDOWN_PCT,
    Settings,
)
from traderstack.indicators import average_directional_index
from traderstack.market.kraken_candles import INTERVAL_MINUTES
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot, Side
from traderstack.pipeline import VerticalSlicePipeline
from traderstack.research.miles_candidates import (
    EMA_9_21_STRATEGY_ID,
    EmaCrossoverStrategy,
    build_ema_9_21_paper_ensemble,
    default_miles_candidates,
    ema_9_21_paper_voter,
)
from traderstack.research.miles_cli import build_parser, run
from traderstack.research.miles_search import (
    render_miles_markdown,
    research_fee_bps,
    run_miles_search,
    split_holdout,
)
from traderstack.risk import RiskEngine, derive_policy_version
from traderstack.runtime import PaperRuntime
from traderstack.strategies import Regime


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def make_candles(
    prices: list[float],
    *,
    symbol: str = "BTC/USD",
    interval: str = "1d",
    start: datetime | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    delta = timedelta(days=1) if interval == "1d" else timedelta(hours=1)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=opened + delta * index,
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def downtrend(count: int = 400, *, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    return make_candles([200.0 - 0.25 * index for index in range(count)], symbol=symbol)


def noisy_uptrend(count: int = 400, *, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    prices: list[float] = []
    price = 100.0
    for index in range(count):
        price = price + 0.15 + 0.4 * ((index % 11) - 5) / 5
        prices.append(price)
    return make_candles(prices, symbol=symbol)


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def test_research_fee_is_the_conservative_of_pretrade_and_paper() -> None:
    assert research_fee_bps(10.0, 10.0) == 10.0
    assert research_fee_bps(10.0, 25.0) == 25.0
    assert research_fee_bps(15.0, 5.0) == 15.0


def test_holdout_split_is_a_strict_tail() -> None:
    candles = noisy_uptrend(100)
    research, holdout = split_holdout(candles, holdout_fraction=0.2)
    assert len(research) == 80
    assert len(holdout) == 20
    assert research[-1].opened_at < holdout[0].opened_at
    assert research + holdout == candles


def test_catalog_is_pre_registered_and_small() -> None:
    catalog = default_miles_candidates()
    assert len(catalog) == 12
    ids = [item.candidate_id for item in catalog]
    assert len(ids) == len(set(ids))
    assert "ema_9_21" in ids
    assert "ema_12_26" in ids
    assert "ema_9_21_adx20" in ids
    assert "ema_9_21_garch" in ids
    assert "ema_12_26_adx20_garch" in ids
    families = {item.family for item in catalog}
    assert families == {"ema_cross", "ema_cross_garch"}


def test_ema_crossover_goes_short_in_a_downtrend() -> None:
    signal = EmaCrossoverStrategy(strategy_id="ema_9_21", fast_span=9, slow_span=21).evaluate(
        downtrend(80), Regime.TRENDING_DOWN
    )
    assert signal.side is Side.SELL


def test_adx_gate_skips_when_adx_is_at_or_below_threshold() -> None:
    prices = [100.0 + (0.15 if index % 2 == 0 else -0.15) for index in range(80)]
    candles = make_candles(prices)
    measured = average_directional_index(candles, 14)
    gated = EmaCrossoverStrategy(
        strategy_id="ema_9_21_adx",
        fast_span=9,
        slow_span=21,
        adx_threshold=measured,
    ).evaluate(candles, Regime.RANGE)
    ungated = EmaCrossoverStrategy(strategy_id="ema_9_21", fast_span=9, slow_span=21).evaluate(
        candles, Regime.RANGE
    )
    assert gated.side is None
    assert "skip chop" in gated.rationale
    assert ungated.side is not None


def _search(histories: dict[str, tuple[Candle, ...]], **overrides: object):
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "garch_min_train": 50,
        "garch_refit_every": 20,
    }
    kwargs.update(overrides)
    return run_miles_search(histories, **kwargs)  # type: ignore[arg-type]


def test_downtrend_can_clear_total_return_for_always_on_ema() -> None:
    report = _search(
        {
            "BTC/USD@1d": downtrend(360, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(360, symbol="ETH/USD"),
        }
    )
    ema = next(row for row in report.candidates if row.candidate_id == "ema_9_21")
    assert ema.mean_wf_total_return is not None
    assert ema.mean_wf_total_return > 0
    assert ema.rankable
    if report.any_promoted:
        assert report.selected_candidate_id in report.promoted_candidate_ids


def test_holdout_tail_does_not_change_ranking() -> None:
    prefix = downtrend(280)
    holdout_a = make_candles(
        [prefix[-1].close - 0.2 * index for index in range(1, 81)],
        start=prefix[-1].opened_at + timedelta(days=1),
    )
    holdout_b = make_candles(
        [prefix[-1].close + 0.8 * index for index in range(1, 81)],
        start=prefix[-1].opened_at + timedelta(days=1),
    )
    a = _search({"BTC/USD@1d": prefix + holdout_a})
    b = _search({"BTC/USD@1d": prefix + holdout_b})
    ranks_a = {row.candidate_id: row.rank for row in a.candidates}
    ranks_b = {row.candidate_id: row.rank for row in b.candidates}
    assert ranks_a == ranks_b
    assert a.selected_candidate_id == b.selected_candidate_id
    a_sel = next(row for row in a.candidates if row.candidate_id == a.selected_candidate_id)
    b_sel = next(row for row in b.candidates if row.candidate_id == b.selected_candidate_id)
    assert a_sel.mean_holdout_excess_return != b_sel.mean_holdout_excess_return


def test_only_pre_registered_top1_is_promoted() -> None:
    report = _search({"BTC/USD@1d": downtrend(360)})
    selected = [row for row in report.candidates if row.selected]
    promoted = [row for row in report.candidates if row.promoted]
    assert len(selected) <= 1
    assert len(promoted) <= 1
    if promoted:
        assert promoted[0].selected
        assert promoted[0].rank == 1
        assert promoted[0].mean_wf_total_return is not None
        assert promoted[0].mean_wf_total_return > 0
        assert promoted[0].mean_holdout_excess_return is not None
        assert promoted[0].mean_holdout_excess_return > 0


def test_gate_rejects_positive_excess_with_negative_total() -> None:
    """The #89 honesty bar: beating BH while losing money is not promotion."""
    report = _search({"BTC/USD@1d": noisy_uptrend(360)}, min_trades=1)
    rendered = render_miles_markdown(report)
    for row in report.candidates:
        if (
            row.mean_wf_total_return is not None
            and row.mean_wf_total_return <= 0
            and row.mean_wf_excess_return is not None
            and row.mean_wf_excess_return > 0
        ):
            assert "walkforward_total_return_not_positive" in row.ineligible_reasons
            assert row.promoted is False
    if not report.any_promoted:
        assert "No candidate cleared the bar" in rendered
        assert "PAPER_GARCH_SIZE=false" in rendered


def test_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    candles_path = tmp_path / "btc.json"
    write_candles(candles_path, downtrend(280))
    out_json = tmp_path / "ops" / "report.json"
    out_md = tmp_path / "ops" / "report.md"
    args = build_parser().parse_args(
        [
            "--candles",
            str(candles_path),
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
            "--min-trades",
            "1",
            "--garch-min-train",
            "50",
            "--fee-bps",
            "10",
        ]
    )
    written_json, written_md = run(args, settings=settings())
    assert written_json.is_file()
    assert written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["selection_rule"] == "pre_registered_top1"
    assert "honesty" in payload
    ids = {row["candidate_id"] for row in payload["candidates"]}
    assert "ema_9_21" in ids
    assert "ema_9_21_garch" in ids
    text = written_md.read_text()
    assert "Miles-inspired strategy search report" in text
    assert "Multiple testing" in text


def test_paper_garch_flag_moves_risk_policy_version() -> None:
    off = settings(paper_garch_size=False)
    on = settings(paper_garch_size=True)
    assert derive_policy_version(off) != derive_policy_version(on)


def test_mixed_intervals_rank_on_daily_only() -> None:
    daily = downtrend(320, symbol="BTC/USD")
    hourly = make_candles(
        [100.0 + 0.4 * index for index in range(320)],
        symbol="BTC/USD",
        interval="1h",
    )
    mixed = _search({"BTC/USD@1d": daily, "BTC/USD@1h": hourly})
    daily_only = _search({"BTC/USD@1d": daily})
    assert mixed.promotion_interval == "1d"
    assert mixed.selected_candidate_id == daily_only.selected_candidate_id
    mixed_sel = next(
        row for row in mixed.candidates if row.candidate_id == mixed.selected_candidate_id
    )
    daily_sel = next(
        row for row in daily_only.candidates if row.candidate_id == daily_only.selected_candidate_id
    )
    assert mixed_sel.mean_wf_total_return == pytest.approx(daily_sel.mean_wf_total_return or 0.0)


def test_garch_candidates_are_scored_not_skipped() -> None:
    report = _search({"BTC/USD@1d": downtrend(320)})
    garch = next(row for row in report.candidates if row.candidate_id == "ema_9_21_garch")
    assert garch.mean_wf_total_return is not None
    assert garch.family == "ema_cross_garch"


def test_ema_9_21_paper_voter_is_only_the_pre_registered_winner() -> None:
    voter = ema_9_21_paper_voter()
    assert voter.strategy_id == EMA_9_21_STRATEGY_ID
    assert voter.fast_span == 9
    assert voter.slow_span == 21
    assert voter.adx_threshold is None
    ensemble = build_ema_9_21_paper_ensemble()
    assert ensemble.suppress_defaults is True
    assert ensemble.min_agreeing == 1
    assert ensemble.paper_research_strategy is None
    assert len(ensemble.extra_voters) == 1
    assert ensemble.extra_voters[0] == voter


def test_promote_ema_9_21_default_is_off_and_paper_only() -> None:
    off = settings()
    assert off.paper_promote_ema_9_21 is False
    assert off.paper_promote_ema_9_21_active is False
    live = settings(trading_mode="live", paper_promote_ema_9_21=True)
    shadow = settings(trading_mode="shadow", paper_promote_ema_9_21=True)
    paper = settings(trading_mode="paper", paper_promote_ema_9_21=True)
    assert live.paper_promote_ema_9_21_active is False
    assert shadow.paper_promote_ema_9_21_active is False
    assert paper.paper_promote_ema_9_21_active is True


def test_promote_ema_9_21_does_not_move_risk_policy_version() -> None:
    off = settings(paper_promote_ema_9_21=False, paper_fee_bps=10.0)
    on = settings(
        paper_promote_ema_9_21=True,
        paper_fee_bps=99.0,
        paper_promote_ema_9_21_max_drawdown_pct=0.30,
    )
    assert derive_policy_version(off) == derive_policy_version(on)


def test_build_pretrade_gate_registers_only_ema_9_21_when_flagged() -> None:
    cfg = settings(paper_promote_ema_9_21=True, pretrade_backtest_enabled=True)
    gate = build_pretrade_gate(cfg)
    ensemble = gate.backtester.ensemble
    assert ensemble.suppress_defaults is True
    assert ensemble.min_agreeing == 1
    assert [voter.strategy_id for voter in ensemble.extra_voters] == [EMA_9_21_STRATEGY_ID]


def test_build_pretrade_gate_ema_9_21_takes_precedence_over_search_flag() -> None:
    cfg = settings(
        paper_promote_ema_9_21=True,
        paper_promote_searched_strategies=True,
        paper_search_report_path="var/ops/does-not-exist.json",
        pretrade_backtest_enabled=True,
    )
    gate = build_pretrade_gate(cfg)
    ids = [voter.strategy_id for voter in gate.backtester.ensemble.extra_voters]
    assert ids == [EMA_9_21_STRATEGY_ID]


def test_build_pretrade_gate_ignores_ema_9_21_flag_outside_paper() -> None:
    live = settings(
        trading_mode="live",
        paper_promote_ema_9_21=True,
        paper_research_mode=False,
        pretrade_backtest_enabled=True,
    )
    gate = build_pretrade_gate(live)
    assert gate.backtester.ensemble.extra_voters == ()
    assert gate.backtester.ensemble.suppress_defaults is False
    assert gate.required_candle_interval is None


def test_promote_ema_forces_daily_interval_even_when_pretrade_is_hourly() -> None:
    hourly = settings(
        paper_promote_ema_9_21=True,
        pretrade_candle_interval="1h",
        pretrade_max_candle_age_seconds=7_200.0,
    )
    assert hourly.effective_pretrade_candle_interval == EMA_9_21_PAPER_CANDLE_INTERVAL
    assert hourly.effective_pretrade_candle_interval == "1d"
    assert hourly.effective_pretrade_max_candle_age_seconds == EMA_9_21_PAPER_MAX_CANDLE_AGE_SECONDS
    assert hourly.effective_pretrade_max_drawdown_pct == EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    assert INTERVAL_MINUTES[hourly.effective_pretrade_candle_interval] == (
        EMA_9_21_PAPER_KRAKEN_INTERVAL_MINUTES
    )
    off = settings(pretrade_candle_interval="1h")
    assert off.effective_pretrade_candle_interval == "1h"
    assert off.effective_pretrade_max_candle_age_seconds == pytest.approx(7_200.0)
    live = settings(
        trading_mode="live",
        paper_promote_ema_9_21=True,
        pretrade_candle_interval="1h",
        paper_promote_ema_9_21_max_drawdown_pct=0.30,
    )
    assert live.effective_pretrade_candle_interval == "1h"
    assert live.effective_pretrade_max_drawdown_pct == 0.15
    shadow = settings(
        trading_mode="shadow",
        paper_promote_ema_9_21=True,
        pretrade_candle_interval="4h",
        paper_promote_ema_9_21_max_drawdown_pct=0.30,
    )
    assert shadow.effective_pretrade_candle_interval == "4h"
    assert shadow.effective_pretrade_max_drawdown_pct == 0.15


def test_promote_pretrade_gate_cannot_silently_score_hourly_bars() -> None:
    cfg = settings(
        paper_promote_ema_9_21=True,
        pretrade_candle_interval="1h",
        pretrade_min_candles=20,
        pretrade_backtest_enabled=True,
    )
    gate = build_pretrade_gate(cfg)
    assert gate.required_candle_interval == "1d"
    assert gate.max_candle_age_seconds == EMA_9_21_PAPER_MAX_CANDLE_AGE_SECONDS
    assert gate.max_drawdown == EMA_9_21_PAPER_MAX_DRAWDOWN_PCT
    hourly = make_candles([100.0 + index for index in range(80)], interval="1h")
    check = gate.evaluate(hourly, now=hourly[-1].opened_at + timedelta(minutes=30))
    assert not check.passed
    assert check.reasons == ["candle_interval_mismatch"]
    assert check.metrics is None
    assert check.walkforward is None


def test_promote_pretrade_gate_accepts_daily_series_for_the_same_voter() -> None:
    cfg = settings(
        paper_promote_ema_9_21=True,
        pretrade_candle_interval="1h",
        pretrade_min_candles=20,
        pretrade_backtest_enabled=True,
    )
    gate = build_pretrade_gate(cfg)
    daily = make_candles([100.0 + index for index in range(80)], interval="1d")
    check = gate.evaluate(daily, now=daily[-1].opened_at + timedelta(hours=12))
    assert "candle_interval_mismatch" not in check.reasons
    assert check.candles_evaluated == 80


def test_promote_gate_off_does_not_require_daily_interval() -> None:
    cfg = settings(paper_promote_ema_9_21=False, pretrade_candle_interval="1h")
    gate = build_pretrade_gate(cfg)
    assert gate.required_candle_interval is None
    assert gate.max_candle_age_seconds == pytest.approx(cfg.pretrade_max_candle_age_seconds)


class _PromoteVenue:
    async def stream_ticks(self, symbols: tuple[str, ...]):
        yield MarketTick(
            source=MarketSource.KRAKEN,
            symbol=symbols[0],
            bid=99.95,
            ask=100.05,
            last=100.0,
        )


class _PromoteReference:
    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        return [ReferencePrice(source=MarketSource.COINGECKO, asset=assets[0], price=100.0)]


class _RecordingCandles:
    def __init__(self, candles: tuple[Candle, ...]) -> None:
        self.candles = candles
        self.resolutions: list[str] = []

    async def fetch(self, symbol: str, resolution: str = "1h", *, count: int = 400):
        self.resolutions.append(resolution)
        return self.candles


@pytest.mark.asyncio
async def test_promote_runtime_fetches_daily_even_if_pretrade_interval_is_hourly() -> None:
    cfg = settings(
        paper_promote_ema_9_21=True,
        pretrade_candle_interval="1h",
        pretrade_min_candles=20,
        kill_switch=False,
    )
    daily = make_candles(
        [100.0 + index for index in range(80)],
        interval="1d",
        start=datetime.now(UTC) - timedelta(days=80),
    )
    provider = _RecordingCandles(daily)
    runtime = PaperRuntime(
        venue=_PromoteVenue(),
        references=(_PromoteReference(),),
        pipeline=VerticalSlicePipeline(
            risk_engine=RiskEngine(cfg),
            pretrade_gate=build_pretrade_gate(cfg),
        ),
        candles=provider,
        candle_interval=cfg.effective_pretrade_candle_interval,
        candle_count=cfg.pretrade_candle_count,
    )
    result = await runtime.run_once(
        "BTC/USD",
        PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000),
    )
    assert provider.resolutions == ["1d"]
    assert result.candles_loaded == 80
    assert result.pipeline.pretrade_check is not None
    assert "candle_interval_mismatch" not in result.pipeline.pretrade_check.reasons


@pytest.mark.asyncio
async def test_promote_runtime_rejects_hourly_history_if_provider_returns_1h() -> None:
    cfg = settings(
        paper_promote_ema_9_21=True,
        pretrade_candle_interval="1h",
        pretrade_min_candles=20,
        kill_switch=False,
    )
    hourly = make_candles([100.0 + index for index in range(80)], interval="1h")
    provider = _RecordingCandles(hourly)
    runtime = PaperRuntime(
        venue=_PromoteVenue(),
        references=(_PromoteReference(),),
        pipeline=VerticalSlicePipeline(
            risk_engine=RiskEngine(cfg),
            pretrade_gate=build_pretrade_gate(cfg),
        ),
        candles=provider,
        candle_interval=cfg.effective_pretrade_candle_interval,
    )
    result = await runtime.run_once(
        "BTC/USD",
        PortfolioSnapshot(nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000),
    )
    assert provider.resolutions == ["1d"]
    assert result.pipeline.rejection_reasons == ["candle_interval_mismatch"]
    assert result.pipeline.proposal is None
    assert result.pipeline.paper_order is None
