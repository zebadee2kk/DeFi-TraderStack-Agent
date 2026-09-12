from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.indicators import average_directional_index
from traderstack.models import Side
from traderstack.research.miles_candidates import (
    EmaCrossoverStrategy,
    default_miles_candidates,
)
from traderstack.research.miles_cli import build_parser, run
from traderstack.research.miles_search import (
    render_miles_markdown,
    research_fee_bps,
    run_miles_search,
    split_holdout,
)
from traderstack.risk import derive_policy_version
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
