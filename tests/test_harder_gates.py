from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.backtest import BacktestMetrics
from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.daily_candidates import (
    EXPANDED_HARDER_GATES_CORE_IDS,
    EXPANDED_HARDER_GATES_OVERLAY_IDS,
    default_balanced_holdout_candidates,
    default_expanded_harder_gates_candidates,
)
from traderstack.research.harder_gates import (
    HARDER_GATES_NOTE,
    MAGNITUDE_RATIO_MIN,
    MULTIWINDOW_BARS,
    MULTIWINDOW_COUNT,
    MULTIWINDOW_MIN_PASSES,
    PR96_ELIGIBLE_RECHECK,
    RANKING_KEY,
    SELECTION_RULE,
    CandidateHarderResult,
    apply_combined_promotion,
    evaluate_fee_stress_gate,
    evaluate_magnitude_gate,
    holdout_magnitude_ratio,
    paper_promote_flag_name,
    render_harder_gates_markdown,
    run_harder_gates,
    score_multiwindow,
    split_contiguous_windows,
)
from traderstack.research.harder_gates_cli import build_parser, run
from traderstack.research.miles_search import CandidateSearchResult, SeriesCandidateMetrics


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
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=opened + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def downtrend(
    count: int, *, symbol: str = "BTC/USD", start: datetime | None = None
) -> tuple[Candle, ...]:
    return make_candles(
        [200.0 - 0.25 * index for index in range(count)], symbol=symbol, start=start
    )


def gap_down_then_flat(
    count: int, *, symbol: str = "BTC/USD", start: datetime | None = None
) -> tuple[Candle, ...]:
    """Rise through the train window, then gap down and go flat.

    EMA 9/21 is long into the gap. A continuing crash would let it flip
    short and still print a positive walk-forward total; a flat print
    after the gap leaves the loss in place.
    """
    train = max(count - 60, 1)
    rise = [100.0 + 0.4 * index for index in range(train)]
    crashed = rise[-1] * 0.45
    rest = [crashed for _ in range(count - train)]
    return make_candles(rise + rest, symbol=symbol, start=start)


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _ema_catalog() -> tuple:
    return tuple(
        item
        for item in default_balanced_holdout_candidates()
        if item.candidate_id in {"ema_9_21", "ema_12_26"}
    )


def _search(histories: dict[str, tuple[Candle, ...]], **overrides: object):
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "candidates": _ema_catalog(),
    }
    kwargs.update(overrides)
    return run_harder_gates(histories, **kwargs)  # type: ignore[arg-type]


def test_promote_ema_9_21_default_stays_false() -> None:
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_active is False


def test_pre_registered_constants_are_frozen() -> None:
    assert MAGNITUDE_RATIO_MIN == 0.25
    assert MULTIWINDOW_COUNT == 3
    assert MULTIWINDOW_BARS == 240
    assert MULTIWINDOW_MIN_PASSES == 2
    assert PR96_ELIGIBLE_RECHECK == (
        "ema_12_26",
        "ema_12_26_adx25",
        "ema_12_26_adx20",
        "ema_9_21_adx25",
        "ema_9_21_ma200_riskoff",
        "ema_9_21_adx20",
    )
    assert "0.25" in HARDER_GATES_NOTE
    assert "2 of 3" in HARDER_GATES_NOTE or "2 of 3" in HARDER_GATES_NOTE.replace(" ", "")
    assert "20+10" in HARDER_GATES_NOTE
    assert RANKING_KEY == "mean_holdout_excess_among_combined_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_combined_passers"
    assert RANKING_KEY in HARDER_GATES_NOTE


def test_expanded_catalog_is_frozen_before_scoring() -> None:
    catalog = default_expanded_harder_gates_candidates()
    ids = [item.candidate_id for item in catalog]
    assert ids == list(EXPANDED_HARDER_GATES_CORE_IDS)
    assert len(ids) == len(set(ids))
    assert "ema_9_21" in ids
    assert "ema_12_26_adx20" in ids
    assert "ema_5_13" in ids
    assert "ema_21_55" in ids
    assert "ema_9_21_adx15" in ids
    assert "ema_12_26_adx30" in ids
    assert "ema_12_26_ma200_riskoff" in ids
    assert "dual_mom_10_50" in ids
    assert "dip_mr_20_1_5_vol2" in ids
    families = {item.family for item in catalog}
    assert {"ema_cross", "ema_cross_garch", "ema_cross_riskoff", "dual_momentum", "buy_the_dip"} <= (
        families
    )
    overlay = default_expanded_harder_gates_candidates(
        btc_overlay=downtrend(220, symbol="BTC/USD")
    )
    overlay_ids = [item.candidate_id for item in overlay]
    assert overlay_ids == list(EXPANDED_HARDER_GATES_CORE_IDS + EXPANDED_HARDER_GATES_OVERLAY_IDS)


def test_paper_promote_flag_name_is_deterministic() -> None:
    assert paper_promote_flag_name("ema_12_26_adx20") == "PAPER_PROMOTE_EMA_12_26_ADX20"
    assert paper_promote_flag_name("ema_9_21") == "PAPER_PROMOTE_EMA_9_21"


def test_magnitude_gate_fails_eth_only_magnitude() -> None:
    """#96-shaped print: both signs > 0 but ETH dominates."""
    passed, ratio, reasons = evaluate_magnitude_gate(0.0555, 0.5837)
    assert ratio == pytest.approx(0.0555 / 0.5837)
    assert ratio is not None and ratio < MAGNITUDE_RATIO_MIN
    assert passed is False
    assert "holdout_magnitude_ratio_below_minimum" in reasons


def test_magnitude_gate_passes_when_ratio_clears() -> None:
    passed, ratio, reasons = evaluate_magnitude_gate(0.0323, 0.0382)
    assert ratio == pytest.approx(0.0323 / 0.0382)
    assert ratio is not None and ratio >= MAGNITUDE_RATIO_MIN
    assert passed is True
    assert reasons == []


def test_magnitude_gate_fails_when_a_sign_is_not_positive() -> None:
    passed, ratio, reasons = evaluate_magnitude_gate(-0.01, 0.50)
    assert ratio is None
    assert passed is False
    assert "btc_holdout_excess_not_positive" in reasons
    assert holdout_magnitude_ratio(None, 0.1) is None


def test_split_windows_uses_latest_aligned_tail() -> None:
    extra = downtrend(800, symbol="BTC/USD")
    windows = split_contiguous_windows(extra)
    assert windows is not None
    assert len(windows) == 3
    assert all(len(window) == 240 for window in windows)
    assert windows[0][0].opened_at == extra[-720].opened_at
    assert windows[-1][-1].opened_at == extra[-1].opened_at


def test_split_windows_fail_closed_when_short() -> None:
    assert split_contiguous_windows(downtrend(719)) is None


def _stitch_windows(parts: list[tuple[Candle, ...]], *, symbol: str) -> tuple[Candle, ...]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    prices: list[float] = []
    for part in parts:
        prices.extend(candle.close for candle in part)
    return make_candles(prices, symbol=symbol, start=start)


def test_multiwindow_requires_two_of_three() -> None:
    catalog = _ema_catalog()
    ema = next(item for item in catalog if item.candidate_id == "ema_9_21")
    pass_w = downtrend(240)
    fail_w = gap_down_then_flat(240)
    btc_two = _stitch_windows([pass_w, pass_w, fail_w], symbol="BTC/USD")
    eth_two = _stitch_windows(
        [
            downtrend(240, symbol="ETH/USD"),
            downtrend(240, symbol="ETH/USD"),
            gap_down_then_flat(240, symbol="ETH/USD"),
        ],
        symbol="ETH/USD",
    )
    passed, scores, reasons = score_multiwindow(
        ema,
        {"BTC/USD@1d": btc_two, "ETH/USD@1d": eth_two},
        fee_bps=10.0,
        slippage_bps=5.0,
        starting_equity=10_000.0,
        train_size=180,
        test_size=60,
        step_size=60,
    )
    assert len(scores) == 3
    assert scores[0].passed is True
    assert scores[1].passed is True
    assert scores[2].passed is False
    assert passed is True
    assert reasons == []

    btc_one = _stitch_windows([pass_w, fail_w, fail_w], symbol="BTC/USD")
    eth_one = _stitch_windows(
        [
            downtrend(240, symbol="ETH/USD"),
            gap_down_then_flat(240, symbol="ETH/USD"),
            gap_down_then_flat(240, symbol="ETH/USD"),
        ],
        symbol="ETH/USD",
    )
    failed, one_scores, one_reasons = score_multiwindow(
        ema,
        {"BTC/USD@1d": btc_one, "ETH/USD@1d": eth_one},
        fee_bps=10.0,
        slippage_bps=5.0,
        starting_equity=10_000.0,
        train_size=180,
        test_size=60,
        step_size=60,
    )
    assert failed is False
    assert "multiwindow_fewer_than_min_passes" in one_reasons
    assert sum(1 for row in one_scores if row.passed) < MULTIWINDOW_MIN_PASSES


def test_multiwindow_fail_closed_without_kraken_daily() -> None:
    ema = next(item for item in _ema_catalog() if item.candidate_id == "ema_9_21")
    passed, scores, reasons = score_multiwindow(
        ema,
        {"BTC-USD@1d": downtrend(720, symbol="BTC-USD")},
        fee_bps=10.0,
        slippage_bps=5.0,
        starting_equity=10_000.0,
        train_size=180,
        test_size=60,
        step_size=60,
    )
    assert passed is False
    assert scores == []
    assert "btc_kraken_daily_missing" in reasons
    assert "eth_kraken_daily_missing" in reasons


def _metrics(*, excess: float, total: float) -> BacktestMetrics:
    return BacktestMetrics(
        starting_equity=10_000.0,
        ending_equity=10_000.0 * (1.0 + total),
        total_return=total,
        benchmark_return=total - excess,
        excess_return=excess,
        max_drawdown=0.01,
        sharpe=0.0,
        trades=4,
    )


def _series(asset: str, *, wf_total: float, ho_excess: float) -> SeriesCandidateMetrics:
    return SeriesCandidateMetrics(
        asset=asset,
        interval="1d",
        candle_count=720,
        research_bars=576,
        holdout_bars=144,
        walkforward_trades=10,
        walkforward_mean_total_return=wf_total,
        walkforward_mean_excess_return=wf_total - 0.01,
        holdout=_metrics(excess=ho_excess, total=ho_excess + 0.01),
    )


def test_fee_stress_gate_requires_balanced_signs() -> None:
    ok = CandidateSearchResult(
        candidate_id="ema_9_21",
        family="ema_cross",
        label="EMA 9/21",
        params={},
        signal_version="x",
        per_series=[
            _series("BTC/USD", wf_total=0.02, ho_excess=0.01),
            _series("ETH/USD", wf_total=0.03, ho_excess=0.02),
        ],
        mean_wf_total_return=0.025,
        mean_holdout_excess_return=0.015,
        total_wf_trades=20,
    )
    passed, reasons = evaluate_fee_stress_gate(ok)
    assert passed is True
    assert reasons == []

    lost_btc = CandidateSearchResult(
        candidate_id="ema_9_21",
        family="ema_cross",
        label="EMA 9/21",
        params={},
        signal_version="x",
        per_series=[
            _series("BTC/USD", wf_total=0.02, ho_excess=-0.01),
            _series("ETH/USD", wf_total=0.03, ho_excess=0.40),
        ],
        mean_wf_total_return=0.025,
        mean_holdout_excess_return=0.195,
        total_wf_trades=20,
    )
    failed, fail_reasons = evaluate_fee_stress_gate(lost_btc)
    assert failed is False
    assert "btc_holdout_excess_not_positive" in fail_reasons


def test_eth_dominated_holdout_fails_gate_a_and_does_not_promote() -> None:
    research_bars = 576
    holdout_bars = 144
    btc_research = downtrend(research_bars, symbol="BTC/USD")
    eth_research = downtrend(research_bars, symbol="ETH/USD")
    btc_start = btc_research[-1].close
    eth_start = eth_research[-1].close
    btc_holdout = make_candles(
        [btc_start * (1.0 - 0.00015 * index) for index in range(1, holdout_bars + 1)],
        symbol="BTC/USD",
        start=btc_research[-1].opened_at + timedelta(days=1),
    )
    eth_holdout = make_candles(
        [eth_start * (1.0 - 0.004 * index) for index in range(1, holdout_bars + 1)],
        symbol="ETH/USD",
        start=eth_research[-1].opened_at + timedelta(days=1),
    )
    report = _search(
        {
            "BTC/USD@1d": btc_research + btc_holdout,
            "ETH/USD@1d": eth_research + eth_holdout,
        }
    )
    ema = next(row for row in report.candidates if row.candidate_id == "ema_9_21")
    assert ema.eligible_96 is True
    assert ema.baseline_btc_holdout is not None and ema.baseline_btc_holdout > 0
    assert ema.baseline_eth_holdout is not None and ema.baseline_eth_holdout > 0
    assert ema.holdout_magnitude_ratio is not None
    assert ema.holdout_magnitude_ratio < MAGNITUDE_RATIO_MIN
    assert ema.gate_a_pass is False
    assert "holdout_magnitude_ratio_below_minimum" in ema.gate_a_reasons
    assert report.ema_9_21_gate_a is False
    assert report.ema_9_21_combined is False
    assert report.any_promoted is False
    rendered = render_harder_gates_markdown(report)
    assert "A Magnitude | **FAIL**" in rendered
    assert "PAPER_PROMOTE_EMA_9_21=false" in rendered


def _harder_row(
    candidate_id: str,
    *,
    combined: bool,
    mean_holdout_excess: float | None,
    wf_rank: int | None = None,
) -> CandidateHarderResult:
    return CandidateHarderResult(
        candidate_id=candidate_id,
        family="ema_cross",
        label=candidate_id,
        wf_rank=wf_rank,
        combined=combined,
        mean_holdout_excess=mean_holdout_excess,
    )


def test_ranking_selects_top_combined_passer_by_mean_holdout_excess() -> None:
    """WF #1 failing does not block a combined-passer; ranking is among passers."""
    rows = [
        _harder_row("ema_9_21", combined=False, mean_holdout_excess=0.32, wf_rank=1),
        _harder_row("ema_12_26_adx20", combined=True, mean_holdout_excess=0.098, wf_rank=4),
        _harder_row("ema_8_21_adx20", combined=True, mean_holdout_excess=0.141, wf_rank=9),
        _harder_row("dual_mom_10_50", combined=False, mean_holdout_excess=0.40, wf_rank=2),
    ]
    selected = apply_combined_promotion(rows)
    assert selected is not None
    assert selected.candidate_id == "ema_8_21_adx20"
    assert selected.promoted is True
    assert selected.combined_rank == 1
    adx20 = next(row for row in rows if row.candidate_id == "ema_12_26_adx20")
    assert adx20.combined_rank == 2
    assert adx20.promoted is False
    assert rows[0].promoted is False
    assert rows[0].selected is False


def test_empty_combined_passers_is_successful_empty_promotee() -> None:
    rows = [
        _harder_row("ema_9_21", combined=False, mean_holdout_excess=0.32, wf_rank=1),
        _harder_row("ema_12_26", combined=False, mean_holdout_excess=0.20, wf_rank=2),
    ]
    selected = apply_combined_promotion(rows)
    assert selected is None
    assert all(row.promoted is False and row.selected is False for row in rows)


def test_ranking_tie_breaks_on_candidate_id() -> None:
    rows = [
        _harder_row("ema_z", combined=True, mean_holdout_excess=0.10, wf_rank=2),
        _harder_row("ema_a", combined=True, mean_holdout_excess=0.10, wf_rank=1),
    ]
    selected = apply_combined_promotion(rows)
    assert selected is not None
    assert selected.candidate_id == "ema_a"


def test_non_passer_is_never_promoted_on_synthetic_window() -> None:
    report = _search(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD"),
        }
    )
    for row in report.candidates:
        if row.promoted:
            assert row.combined is True
            assert row.selected is True
            assert row.candidate_id == report.selected_candidate_id
        else:
            assert row.promoted is False
    if not any(row.combined for row in report.candidates):
        assert report.any_promoted is False
        assert report.selected_candidate_id is None


def test_yahoo_does_not_enter_magnitude_or_windows() -> None:
    kraken_btc = downtrend(720, symbol="BTC/USD")
    kraken_eth = downtrend(720, symbol="ETH/USD")
    yahoo = make_candles([10.0 + 3.0 * index for index in range(720)], symbol="BTC-USD")
    without = _search({"BTC/USD@1d": kraken_btc, "ETH/USD@1d": kraken_eth})
    with_yahoo = _search(
        {
            "BTC/USD@1d": kraken_btc,
            "ETH/USD@1d": kraken_eth,
            "BTC-USD@1d": yahoo,
        }
    )
    a = next(row for row in without.candidates if row.candidate_id == "ema_9_21")
    b = next(row for row in with_yahoo.candidates if row.candidate_id == "ema_9_21")
    assert a.baseline_wf_total == pytest.approx(b.baseline_wf_total or 0.0)
    assert a.holdout_magnitude_ratio == pytest.approx(b.holdout_magnitude_ratio or 0.0)
    assert a.windows_passed == b.windows_passed
    assert any("non-Kraken" in note for note in with_yahoo.yahoo_notes)


def test_markdown_table_covers_a_b_c_and_combined() -> None:
    report = _search(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD"),
        }
    )
    text = render_harder_gates_markdown(report)
    assert "## `ema_9_21` PASS / FAIL" in text
    assert "| A Magnitude |" in text
    assert "| B Multi-window |" in text
    assert "| C Fee stress |" in text
    assert "| Combined |" in text
    assert "Combined-passers (promotion ranking)" in text
    assert RANKING_KEY in text
    assert "Pre-registered gates" in text
    assert "Yahoo" in text
    assert report.ema_9_21_gate_a in {True, False}
    assert report.ema_9_21_gate_b in {True, False}
    assert report.ema_9_21_gate_c in {True, False}


def test_cli_default_catalog_is_expanded() -> None:
    args = build_parser().parse_args(
        ["--candles", "unused.json", "--no-yahoo"]
    )
    assert args.catalog == "expanded"
    assert args.output_md.name == "expanded-harder-gates-report.md"


def test_cli_writes_json_and_markdown(tmp_path: Path) -> None:
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    write_candles(btc, downtrend(720, symbol="BTC/USD"))
    write_candles(eth, downtrend(720, symbol="ETH/USD"))
    out_json = tmp_path / "ops" / "report.json"
    out_md = tmp_path / "ops" / "report.md"
    args = build_parser().parse_args(
        [
            "--candles",
            str(btc),
            "--candles",
            str(eth),
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
            "--fee-bps",
            "10",
            "--catalog",
            "legacy",
            "--no-yahoo",
        ]
    )
    written_json, written_md = run(args, settings=settings())
    assert written_json.is_file()
    assert written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["selection_rule"] == SELECTION_RULE
    assert payload["ranking_key"] == RANKING_KEY
    assert payload["magnitude_ratio_min"] == 0.25
    assert payload["multiwindow_count"] == 3
    assert payload["fee_stress_fee_bps"] == 20.0
    assert payload["fee_stress_slippage_bps"] == 10.0
    assert "ema_9_21_gate_a" in payload
    assert "ema_9_21_combined" in payload
    assert "combined_passer_ids" in payload
    ids = {row["candidate_id"] for row in payload["candidates"]}
    assert "ema_9_21" in ids
    text = written_md.read_text()
    assert "Expanded catalog harder-gates report" in text
    assert "PAPER_PROMOTE" in text
    assert RANKING_KEY in text
