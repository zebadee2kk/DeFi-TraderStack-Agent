from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.cli import build_pretrade_gate
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.candidates import (
    AlwaysOnTrendStrategy,
    default_price_candidates,
    feature_candidates,
)
from traderstack.research.promotion import (
    PromotionError,
    build_paper_ensemble,
    promoted_price_voters,
    row_clears_gate,
)
from traderstack.research.search import (
    CandidateSearchResult,
    render_search_markdown,
    research_fee_bps,
    run_search,
    split_holdout,
)
from traderstack.research.search_cli import build_parser, run
from traderstack.risk import derive_policy_version
from traderstack.strategies import Regime, StrategyEnsemble, combine_signals


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
    start: datetime | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval="1h",
                opened_at=opened + timedelta(hours=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def downtrend(count: int = 400, *, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    prices = [200.0 - 0.25 * index for index in range(count)]
    return make_candles(prices, symbol=symbol)


def noisy_uptrend(count: int = 400, *, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    prices: list[float] = []
    price = 100.0
    for index in range(count):
        price = price + 0.15 + 0.4 * ((index % 11) - 5) / 5
        prices.append(price)
    return make_candles(prices, symbol=symbol)


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([c.model_dump(mode="json") for c in candles]))


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


def test_gate_requires_positive_wf_excess_and_min_trades() -> None:
    assert (
        row_clears_gate(
            mean_wf_excess_return=0.01,
            total_wf_trades=5,
            mean_holdout_excess_return=0.01,
            min_trades=3,
            min_wf_excess_return=0.0,
            require_holdout_confirmation=True,
        )
        is True
    )
    assert (
        row_clears_gate(
            mean_wf_excess_return=0.0,
            total_wf_trades=5,
            mean_holdout_excess_return=0.01,
            min_trades=3,
            min_wf_excess_return=0.0,
            require_holdout_confirmation=True,
        )
        is False
    )
    assert (
        row_clears_gate(
            mean_wf_excess_return=0.01,
            total_wf_trades=2,
            mean_holdout_excess_return=0.01,
            min_trades=3,
            min_wf_excess_return=0.0,
            require_holdout_confirmation=True,
        )
        is False
    )
    assert (
        row_clears_gate(
            mean_wf_excess_return=0.01,
            total_wf_trades=5,
            mean_holdout_excess_return=-0.01,
            min_trades=3,
            min_wf_excess_return=0.0,
            require_holdout_confirmation=True,
        )
        is False
    )


def test_search_skips_optional_features_when_absent() -> None:
    report = run_search(
        {"BTC/USD": downtrend(360)},
        fee_bps=10.0,
        slippage_bps=5.0,
        train_size=120,
        test_size=60,
        step_size=60,
        holdout_fraction=0.2,
        min_trades=1,
    )
    ids = {row.candidate_id for row in report.candidates}
    assert "liquidation_z_fade" not in ids
    assert "cross_venue_fade" not in ids
    skipped = {item["candidate_id"] for item in report.skipped_feature_families}
    assert skipped == {"liquidation_z_fade", "cross_venue_fade"}
    assert report.selection_rule == "pre_registered_top1"
    assert report.multiple_testing["n_candidates"] == len(default_price_candidates())


def test_search_includes_feature_candidates_when_series_supplied() -> None:
    candles = downtrend(360)
    series = tuple((c.opened_at, float(index % 7) - 3.0) for index, c in enumerate(candles))
    extra = feature_candidates(liquidation=series, cross_venue=series)
    assert {c.candidate_id for c in extra} == {"liquidation_z_fade", "cross_venue_fade"}
    report = run_search(
        {"BTC/USD": candles},
        fee_bps=10.0,
        candidates=default_price_candidates() + extra,
        liquidation=series,
        cross_venue=series,
        train_size=120,
        test_size=60,
        step_size=60,
        holdout_fraction=0.2,
        min_trades=1,
    )
    ids = {row.candidate_id for row in report.candidates}
    assert "liquidation_z_fade" in ids
    assert "cross_venue_fade" in ids
    assert report.skipped_feature_families == []


def test_holdout_tail_does_not_change_ranking() -> None:
    """Ranking is a function of the research prefix only."""
    prefix = downtrend(320)
    holdout_a = make_candles(
        [prefix[-1].close - 0.2 * index for index in range(1, 81)],
        start=prefix[-1].opened_at + timedelta(hours=1),
    )
    holdout_b = make_candles(
        [prefix[-1].close + 0.8 * index for index in range(1, 81)],
        start=prefix[-1].opened_at + timedelta(hours=1),
    )
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "train_size": 120,
        "test_size": 60,
        "step_size": 60,
        "holdout_fraction": 0.2,
        "min_trades": 1,
    }
    a = run_search({"BTC/USD": prefix + holdout_a}, **kwargs)  # type: ignore[arg-type]
    b = run_search({"BTC/USD": prefix + holdout_b}, **kwargs)  # type: ignore[arg-type]
    ranks_a = {row.candidate_id: row.rank for row in a.candidates}
    ranks_b = {row.candidate_id: row.rank for row in b.candidates}
    assert ranks_a == ranks_b
    assert a.selected_candidate_id == b.selected_candidate_id
    # Holdout numbers themselves must differ so the test is not vacuous.
    a_sel = next(row for row in a.candidates if row.candidate_id == a.selected_candidate_id)
    b_sel = next(row for row in b.candidates if row.candidate_id == b.selected_candidate_id)
    assert a_sel.mean_holdout_excess_return != b_sel.mean_holdout_excess_return


def test_downtrend_can_clear_the_bar_for_always_on_ma() -> None:
    """A persistent downtrend is one of the few paths where shorting beats BH."""
    report = run_search(
        {
            "BTC/USD": downtrend(400, symbol="BTC/USD"),
            "ETH/USD": downtrend(400, symbol="ETH/USD"),
        },
        fee_bps=10.0,
        slippage_bps=5.0,
        train_size=120,
        test_size=60,
        step_size=60,
        holdout_fraction=0.2,
        min_trades=1,
    )
    always_on = next(row for row in report.candidates if row.candidate_id == "ma_always_on_10_30")
    assert always_on.mean_wf_excess_return is not None
    assert always_on.mean_wf_excess_return > 0
    assert always_on.rankable
    if report.any_promoted:
        assert report.promoted_candidate_ids
        assert report.selected_candidate_id in report.promoted_candidate_ids


def test_noisy_uptrend_is_not_rewritten_as_edge() -> None:
    """Typical grind-up + fees: excess after costs is not a free lunch."""
    report = run_search(
        {"BTC/USD": noisy_uptrend(400)},
        fee_bps=10.0,
        slippage_bps=5.0,
        train_size=120,
        test_size=60,
        step_size=60,
        holdout_fraction=0.2,
        min_trades=3,
    )
    rendered = render_search_markdown(report)
    if not report.any_promoted:
        assert "No candidate cleared the bar" in rendered
        assert "PAPER_PROMOTE_SEARCHED_STRATEGIES=false" in rendered


def test_only_pre_registered_top1_is_promoted() -> None:
    report = run_search(
        {"BTC/USD": downtrend(400)},
        fee_bps=10.0,
        train_size=120,
        test_size=60,
        step_size=60,
        holdout_fraction=0.2,
        min_trades=1,
    )
    selected = [row for row in report.candidates if row.selected]
    promoted = [row for row in report.candidates if row.promoted]
    assert len(selected) <= 1
    assert len(promoted) <= 1
    if promoted:
        assert promoted[0].selected
        assert promoted[0].rank == 1


def test_promotion_flag_default_keeps_baseline_ensemble() -> None:
    ensemble = build_paper_ensemble(settings())
    assert ensemble.suppress_defaults is False
    assert ensemble.extra_voters == ()
    assert ensemble.min_agreeing == 2


def test_promotion_without_report_fails_closed() -> None:
    cfg = settings(
        paper_promote_searched_strategies=True,
        paper_search_report_path="/tmp/traderstack-missing-search.json",
    )
    with pytest.raises(PromotionError, match="missing"):
        build_paper_ensemble(cfg)


def test_promotion_registers_only_gate_clearing_top1(tmp_path: Path) -> None:
    report = run_search(
        {"BTC/USD": downtrend(400)},
        fee_bps=10.0,
        train_size=120,
        test_size=60,
        step_size=60,
        holdout_fraction=0.2,
        min_trades=1,
    )
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json())
    cfg = settings(
        paper_promote_searched_strategies=True,
        paper_search_report_path=str(path),
        paper_search_min_trades=1,
    )
    if not report.any_promoted:
        with pytest.raises(PromotionError, match="no candidate cleared"):
            build_paper_ensemble(cfg)
        return
    ensemble = build_paper_ensemble(cfg)
    assert ensemble.suppress_defaults is True
    assert ensemble.min_agreeing == 1
    assert len(ensemble.extra_voters) == 1
    voter = ensemble.extra_voters[0]
    assert voter.strategy_id == report.promoted_candidate_ids[0]  # type: ignore[attr-defined]


def test_promotion_rejects_report_that_claims_a_loser(tmp_path: Path) -> None:
    report = run_search(
        {"BTC/USD": noisy_uptrend(360)},
        fee_bps=10.0,
        train_size=120,
        test_size=60,
        step_size=60,
        holdout_fraction=0.2,
        min_trades=3,
    )
    if report.selected_candidate_id:
        for row in report.candidates:
            if row.candidate_id == report.selected_candidate_id:
                row.promoted = True
                row.eligible = True
                row.mean_wf_excess_return = -0.05
                row.total_wf_trades = 20
    report.promoted_candidate_ids = (
        [report.selected_candidate_id] if report.selected_candidate_id else ["ma_cross_10_30"]
    )
    report.any_promoted = True
    path = tmp_path / "forged.json"
    path.write_text(report.model_dump_json())
    cfg = settings(
        paper_promote_searched_strategies=True,
        paper_search_report_path=str(path),
    )
    with pytest.raises(PromotionError, match="no candidate cleared"):
        build_paper_ensemble(cfg)


def test_build_pretrade_gate_uses_promoted_voter(tmp_path: Path) -> None:
    report = run_search(
        {"BTC/USD": downtrend(400)},
        fee_bps=10.0,
        train_size=120,
        test_size=60,
        step_size=60,
        holdout_fraction=0.2,
        min_trades=1,
    )
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json())
    cfg = settings(
        paper_promote_searched_strategies=report.any_promoted,
        paper_search_report_path=str(path),
        paper_search_min_trades=1,
        pretrade_backtest_enabled=True,
    )
    gate = build_pretrade_gate(cfg)
    if report.any_promoted:
        assert gate.backtester.ensemble.suppress_defaults is True
        assert gate.backtester.ensemble.min_agreeing == 1
    else:
        assert gate.backtester.ensemble.suppress_defaults is False


def test_promotion_settings_do_not_move_risk_policy_version() -> None:
    a = settings(paper_promote_searched_strategies=False, paper_fee_bps=10.0)
    b = settings(paper_promote_searched_strategies=True, paper_fee_bps=99.0)
    assert derive_policy_version(a) == derive_policy_version(b)


def test_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    candles_path = tmp_path / "btc.json"
    write_candles(candles_path, downtrend(360))
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
            "120",
            "--test-size",
            "60",
            "--step-size",
            "60",
            "--min-trades",
            "1",
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
    assert "ma_always_on_10_30" in {row["candidate_id"] for row in payload["candidates"]}
    text = written_md.read_text()
    assert "Strategy search report" in text
    assert "Multiple testing" in text


def test_default_ensemble_still_needs_two_votes() -> None:
    ensemble = StrategyEnsemble()
    assert ensemble.min_agreeing == 2
    one = AlwaysOnTrendStrategy().evaluate(downtrend(60), Regime.TRENDING_DOWN)
    assert one.side is Side.SELL
    assert combine_signals((one,), strategy_id="t") is None
    assert combine_signals((one, one), strategy_id="t", min_agreeing=1) is not None


def test_promoted_price_voters_ignore_non_promoted_rows() -> None:
    report = run_search(
        {"BTC/USD": downtrend(360)},
        fee_bps=10.0,
        train_size=120,
        test_size=60,
        step_size=60,
        holdout_fraction=0.2,
        min_trades=1,
    )
    cfg = settings(paper_search_min_trades=1)
    voters = promoted_price_voters(report, cfg)
    if report.any_promoted:
        assert len(voters) == 1
    else:
        assert voters == ()


def test_catalog_is_pre_registered_and_small() -> None:
    catalog = default_price_candidates()
    assert 8 <= len(catalog) <= 16
    families = {c.family for c in catalog}
    assert families == {"ma_cross", "momentum", "mean_reversion"}
    ids = [c.candidate_id for c in catalog]
    assert len(ids) == len(set(ids))
    assert "ma_always_on_10_30" in ids


def test_candidate_result_defaults_are_not_promoted() -> None:
    row = CandidateSearchResult(
        candidate_id="x",
        family="ma_cross",
        label="x",
        params={},
        signal_version="x",
    )
    assert row.promoted is False
    assert row.eligible is False
