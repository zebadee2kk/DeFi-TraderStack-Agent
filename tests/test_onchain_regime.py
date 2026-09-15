"""On-chain regime overlay research (#139): frozen catalog, withhold-only
voter, point-in-time replay, skip-not-invent coverage, verdicts, CLI."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.market.coinmetrics import (
    OnChainDailyRow,
    OnChainRegimePoint,
    derive_regime_series,
    regime_point_before,
    save_regime_rows_json,
)
from traderstack.models import Side
from traderstack.research.leakage import (
    assert_no_lookahead,
    assert_no_lookahead_under_shuffled_future,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.onchain_regime import (
    CAN_PROMOTE,
    ONCHAIN_REGIME_RULES,
    OVERLAY_CATALOG,
    OVERLAY_IDS,
    OVERLAY_PASSER_RULE,
    OVERLAY_VERDICT_RULE,
    OnChainRegimeGateVoter,
    RegimeLookup,
    blocked_days,
    gated_candidate,
    gated_id,
    overlay_verdict,
    regime_coverage_usable,
    render_onchain_regime_markdown,
    run_onchain_regime_search,
)
from traderstack.research.onchain_regime_cli import build_parser, run
from traderstack.research.tsmom import CONTROL_ID, tsmom_candidates
from traderstack.strategies import Regime, StrategySignal

START = datetime(2024, 1, 1, tzinfo=UTC)


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
    opened = start or START
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


def uptrend(count: int, *, symbol: str = "BTC/USD", start: datetime | None = None):
    return make_candles([100.0 + 0.25 * i for i in range(count)], symbol=symbol, start=start)


def downtrend(count: int, *, symbol: str = "BTC/USD", start: datetime | None = None):
    return make_candles([200.0 - 0.25 * i for i in range(count)], symbol=symbol, start=start)


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _rows(count: int, *, start: date, hot: bool = False) -> tuple[OnChainDailyRow, ...]:
    out: list[OnChainDailyRow] = []
    for index in range(count):
        cap = 1e11 + 2e8 * index + 5e9 * math.sin(index / 37.0)
        mvrv = (3.5 if hot else 1.2) + 0.4 * math.sin(index / 53.0)
        out.append(
            OnChainDailyRow(
                asset="btc", day=start + timedelta(days=index), mvrv=mvrv, market_cap_usd=cap
            )
        )
    return tuple(out)


def _series(count: int, *, start: date, hot: bool = False) -> tuple[OnChainRegimePoint, ...]:
    return derive_regime_series(_rows(count, start=start, hot=hot), window_days=30, min_points=5)


def _point(day: date, *, pct: float | None, nupl: float = 0.2) -> OnChainRegimePoint:
    return OnChainRegimePoint(
        day=day,
        mvrv=1.25,
        market_cap_usd=1e12,
        realized_cap_usd=8e11,
        nupl=nupl,
        mvrv_z=1.0 if pct is not None else None,
        mvrv_z_percentile=pct,
        points=1460,
    )


class _AlwaysBuy:
    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        return StrategySignal(
            strategy_id="always_buy",
            symbol=candles[-1].symbol,
            side=Side.BUY,
            score=1.0,
            confidence=1.0,
            regime=regime,
            rationale="fixture",
        )


class _AlwaysSell:
    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        return StrategySignal(
            strategy_id="always_sell",
            symbol=candles[-1].symbol,
            side=Side.SELL,
            score=-1.0,
            confidence=1.0,
            regime=regime,
            rationale="fixture",
        )


def _voter(
    series: tuple[OnChainRegimePoint, ...],
    *,
    inner: object | None = None,
    field: str = "mvrv_z_percentile",
    threshold: float = 0.90,
) -> OnChainRegimeGateVoter:
    return OnChainRegimeGateVoter(
        inner=inner or _AlwaysBuy(),  # type: ignore[arg-type]
        strategy_id="always_buy__test",
        overlay_id="test",
        regime_field=field,
        threshold=threshold,
        lookup=RegimeLookup.from_series(series),
    )


# --- frozen catalog ---------------------------------------------------------------


def test_overlay_catalog_and_rules_are_frozen() -> None:
    assert OVERLAY_CATALOG == (
        ("mvrvz_p90", "mvrv_z_percentile", 0.90),
        ("mvrvz_p80", "mvrv_z_percentile", 0.80),
        ("nupl_075", "nupl", 0.75),
    )
    assert OVERLAY_IDS == ("mvrvz_p90", "mvrvz_p80", "nupl_075")
    assert CAN_PROMOTE is False
    assert "strictly before" in ONCHAIN_REGIME_RULES
    assert "never forward-filled" in ONCHAIN_REGIME_RULES
    assert "PAPER_PROMOTE_* stays default false" in ONCHAIN_REGIME_RULES
    assert "SOL has no community MVRV" in ONCHAIN_REGIME_RULES
    assert OVERLAY_PASSER_RULE in ONCHAIN_REGIME_RULES
    assert OVERLAY_VERDICT_RULE in ONCHAIN_REGIME_RULES
    assert gated_id("tsmom_lo_21", "mvrvz_p90") == "tsmom_lo_21__mvrvz_p90"


def test_promote_defaults_stay_false() -> None:
    cfg = settings()
    assert cfg.paper_promote_ema_9_21 is False
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.paper_promote_searched_strategies is False
    assert cfg.onchain_regime_gate_enabled is False
    assert not hasattr(cfg, "paper_promote_tsmom_lo_21__mvrvz_p90")


# --- withhold-only voter -------------------------------------------------------------


def test_gated_voter_blocks_buy_only_and_passes_sell_and_flat() -> None:
    hot = (_point(date(2024, 1, 1), pct=0.95),)
    cold = (_point(date(2024, 1, 1), pct=0.10),)
    candles = uptrend(3, start=datetime(2024, 1, 2, tzinfo=UTC))
    blocked = _voter(hot).evaluate(candles, Regime.TRENDING_UP)
    assert blocked.side is None and blocked.confidence == 0.0
    assert "BUY withheld" in blocked.rationale
    allowed = _voter(cold).evaluate(candles, Regime.TRENDING_UP)
    assert allowed.side is Side.BUY and allowed.strategy_id == "always_buy__test"
    sell = _voter(hot, inner=_AlwaysSell()).evaluate(candles, Regime.TRENDING_DOWN)
    assert sell.side is Side.SELL, "SELL is never gated"


def test_gated_voter_fails_closed_on_missing_or_stale_regime() -> None:
    candles = uptrend(3, start=datetime(2024, 3, 1, tzinfo=UTC))
    none_pct = (_point(date(2024, 2, 29), pct=None),)
    assert _voter(none_pct).evaluate(candles, Regime.TRENDING_UP).side is None
    stale = (_point(date(2024, 2, 1), pct=0.10),)
    assert _voter(stale).evaluate(candles, Regime.TRENDING_UP).side is None
    assert _voter(()).evaluate(candles, Regime.TRENDING_UP).side is None


def test_lookup_agrees_with_regime_point_before() -> None:
    series = _series(40, start=date(2024, 1, 1))
    lookup = RegimeLookup.from_series(series)
    for offset_hours in range(-48, 41 * 24, 7):
        decision = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=offset_hours)
        assert lookup.before(decision) == regime_point_before(series, decision)


# --- point-in-time replay -------------------------------------------------------------


def test_gated_voter_has_no_lookahead() -> None:
    series = _series(120, start=date(2023, 12, 1))
    voter = _voter(series, threshold=0.5)
    candles = uptrend(60, start=datetime(2024, 1, 10, tzinfo=UTC))

    def fn(window: tuple[Candle, ...]) -> tuple[Side | None, str]:
        signal = voter.evaluate(window, Regime.TRENDING_UP)
        return signal.side, signal.rationale

    assert_no_lookahead(fn, candles, min_index=5)
    assert_no_lookahead_under_shuffled_future(fn, candles, min_index=5)


def test_rows_dated_at_or_after_the_decision_bar_cannot_change_the_decision() -> None:
    rows = _rows(90, start=date(2023, 12, 1))
    decision_bar = datetime(2024, 2, 10, tzinfo=UTC)
    candles = uptrend(3, start=decision_bar - timedelta(days=2))
    window, min_points = 30, 5
    prior_day = decision_bar.date() - timedelta(days=1)

    def series_for(rows_variant: tuple[OnChainDailyRow, ...]) -> tuple[OnChainRegimePoint, ...]:
        return derive_regime_series(rows_variant, window_days=window, min_points=min_points)

    def decide(rows_variant: tuple[OnChainDailyRow, ...], threshold: float) -> Side | None:
        voter = _voter(series_for(rows_variant), threshold=threshold)
        return voter.evaluate(candles, Regime.TRENDING_UP).side

    used = regime_point_before(series_for(rows), decision_bar)
    assert used is not None and used.day == prior_day and used.mvrv_z_percentile is not None
    baseline_pct = used.mvrv_z_percentile
    # Pick a threshold and a strictly-earlier mutation that must flip the
    # decision, whichever side of the threshold the synthetic series sits on.
    if baseline_pct < 1.0:
        threshold = (baseline_pct + 1.0) / 2  # baseline allowed …
        past_scale, past_mvrv = 50.0, 9.0  # … a hot D-1 row blocks it
    else:
        threshold = 0.5  # baseline blocked …
        past_scale, past_mvrv = 0.01, 1.01  # … a cold D-1 row frees it
    baseline = decide(rows, threshold)

    # Mutate every row dated on/after the decision bar (including the future):
    # the decision at that bar cannot move.
    mutated_future = tuple(
        row.model_copy(update={"market_cap_usd": row.market_cap_usd * 50, "mvrv": 9.0})
        if row.day >= decision_bar.date()
        else row
        for row in rows
    )
    assert decide(mutated_future, threshold) == baseline
    # Mutating a strictly-earlier row (D-1) CAN change it — the series is
    # real input, not a constant.
    mutated_past = tuple(
        row.model_copy(
            update={"market_cap_usd": row.market_cap_usd * past_scale, "mvrv": past_mvrv}
        )
        if row.day == prior_day
        else row
        for row in rows
    )
    assert decide(mutated_past, threshold) != baseline


# --- coverage / verdict -----------------------------------------------------------------


def test_coverage_skips_when_series_does_not_cover_the_window() -> None:
    series = _series(40, start=date(2024, 1, 1))
    covered = uptrend(10, start=datetime(2024, 1, 20, tzinfo=UTC))
    assert regime_coverage_usable(series, covered, field_name="mvrv_z_percentile") == (True, None)
    uncovered = uptrend(10, start=datetime(2025, 1, 1, tzinfo=UTC))
    usable, reason = regime_coverage_usable(series, uncovered, field_name="mvrv_z_percentile")
    assert usable is False and reason is not None and "lack a committed" in reason
    assert regime_coverage_usable((), covered, field_name="nupl")[0] is False
    assert regime_coverage_usable(series, None, field_name="nupl")[0] is False


def test_blocked_days_counts_breaches_strictly_before_each_bar() -> None:
    series = (
        _point(date(2024, 1, 1), pct=0.95),
        _point(date(2024, 1, 2), pct=0.50),
        _point(date(2024, 1, 3), pct=0.99),
    )
    candles = uptrend(3, start=datetime(2024, 1, 2, tzinfo=UTC))  # bars 2, 3, 4 Jan
    assert blocked_days(series, candles, field_name="mvrv_z_percentile", threshold=0.9) == 2
    assert blocked_days((), candles, field_name="mvrv_z_percentile", threshold=0.9) is None


def test_overlay_verdict_rule_is_frozen_and_mixed_is_fail() -> None:
    common = {"kraken_scored": True, "binance_scored": True}
    assert overlay_verdict(kraken_delta=0.01, binance_delta=0.02, **common) == "helps"
    assert overlay_verdict(kraken_delta=-0.01, binance_delta=-0.02, **common) == "hurts"
    assert overlay_verdict(kraken_delta=0.01, binance_delta=-0.02, **common) == "mixed_fail"
    assert overlay_verdict(kraken_delta=0.0, binance_delta=0.0, **common) == "neutral"
    # A holdout lift with a walk-forward cut is a FAIL, not a help.
    assert (
        overlay_verdict(kraken_delta=0.0, binance_delta=0.03, kraken_delta_wf=-0.05, **common)
        == "mixed_fail"
    )
    assert overlay_verdict(kraken_delta=None, binance_delta=None, **common) == "skipped"
    assert (
        overlay_verdict(
            kraken_delta=None, binance_delta=None, kraken_scored=False, binance_scored=False
        )
        == "skipped"
    )
    assert (
        overlay_verdict(
            kraken_delta=0.01, binance_delta=None, kraken_scored=True, binance_scored=False
        )
        == "helps"
    )


# --- search -----------------------------------------------------------------------------


def _histories(count: int, start: datetime, trend: str = "up") -> dict[str, tuple[Candle, ...]]:
    maker = uptrend if trend == "up" else downtrend
    return {
        "BTC/USD@1d": maker(count, symbol="BTC/USD", start=start),
        "ETH/USD@1d": maker(count, symbol="ETH/USD", start=start),
    }


def _tiny_base(histories: dict[str, tuple[Candle, ...]]) -> tuple[SearchCandidate, ...]:
    return tuple(
        item
        for item in tsmom_candidates(histories, include_control=False)
        if item.candidate_id in {"tsmom_lo_21", "tsmom_ls_21"}
    )


def _search(kraken, binance=None, series=(), **overrides):
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "base_candidates": _tiny_base(kraken),
    }
    kwargs.update(overrides)
    return run_onchain_regime_search(kraken, binance, series, **kwargs)  # type: ignore[arg-type]


def test_search_without_series_skips_every_overlay_and_still_scores_base() -> None:
    kraken = _histories(240, datetime(2024, 9, 22, tzinfo=UTC))
    report = _search(kraken, regime_skip_reason="Coin Metrics unreachable: test")
    assert report.regime_status == "skipped"
    assert report.regime_skip_reason == "Coin Metrics unreachable: test"
    assert all(not item.usable for item in report.coverage)
    assert all(item.verdict == "skipped" for item in report.effects)
    assert {row.candidate_id for row in report.rows} == {"tsmom_lo_21", "tsmom_ls_21", CONTROL_ID}
    assert report.overlay_passer_ids == []
    assert report.any_overlay_passer is False
    assert report.keep_flag_false is True and report.can_promote is False
    assert all(row.can_promote is False for row in report.rows)
    assert all(item.can_promote is False for item in report.effects)
    text = render_onchain_regime_markdown(report)
    assert "skipped — Coin Metrics unreachable: test" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text


def test_search_with_series_scores_gated_names_and_never_promotes() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    kraken = _histories(240, primary)
    binance = {
        "BTCUSDT@1d": uptrend(720, symbol="BTCUSDT", start=older),
        "ETHUSDT@1d": uptrend(720, symbol="ETHUSDT", start=older),
    }
    series = _series(1200, start=date(2022, 6, 1))
    report = _search(kraken, binance, series, binance_source="binance_json")
    assert report.regime_status == "ok"
    assert report.binance_slice.available is True
    gated = [row for row in report.rows if "__" in row.candidate_id]
    assert len(gated) == len(OVERLAY_IDS) * 2
    assert all(item.usable for item in report.coverage)
    assert all(row.can_promote is False for row in report.rows)
    assert report.can_promote is False and report.keep_flag_false is True
    assert len(report.effects) == len(OVERLAY_IDS) * 2
    assert all(item.verdict != "skipped" for item in report.effects)
    for item in report.effects:
        # Passer requires dual-print AND non-negative deltas on both metrics.
        if item.overlay_passer:
            assert item.gated_dual_print
            assert item.kraken_delta_mean_ho is not None and item.kraken_delta_mean_ho >= 0
            assert item.binance_delta_mean_ho is not None and item.binance_delta_mean_ho >= 0
            assert item.kraken_delta_wf is not None and item.kraken_delta_wf >= 0
            assert item.binance_delta_wf is not None and item.binance_delta_wf >= 0
    text = render_onchain_regime_markdown(report)
    assert "## Overlay effect — Kraken primary 720" in text
    assert "## Overlay passers (promotion ranking)" in text
    assert "can flip flag" in text


def test_gated_candidate_wraps_without_touching_base_params() -> None:
    kraken = _histories(80, datetime(2024, 9, 22, tzinfo=UTC))
    base = _tiny_base(kraken)[0]
    series = _series(40, start=date(2024, 9, 1))
    wrapped = gated_candidate(base, OVERLAY_CATALOG[0], RegimeLookup.from_series(series))
    assert wrapped.candidate_id == f"{base.candidate_id}__mvrvz_p90"
    assert wrapped.family == "tsmom_onchain_regime"
    assert wrapped.params["base_id"] == base.candidate_id
    assert wrapped.params["regime_threshold"] == 0.90
    assert base.params.get("overlay_id") is None


# --- CLI ------------------------------------------------------------------------------


def test_cli_defaults_and_offline_run_write_outputs(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "onchain-regime.md"
    assert args.onchain_json is None

    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    btc_usdt = tmp_path / "btcusdt.json"
    eth_usdt = tmp_path / "ethusdt.json"
    write_candles(btc, downtrend(240, symbol="BTC/USD", start=primary))
    write_candles(eth, downtrend(240, symbol="ETH/USD", start=primary))
    write_candles(btc_usdt, downtrend(720, symbol="BTCUSDT", start=older))
    write_candles(eth_usdt, downtrend(720, symbol="ETHUSDT", start=older))
    rows_path = tmp_path / "cm.json"
    save_regime_rows_json(rows_path, _rows(1200, start=date(2022, 6, 1)))
    out_json = tmp_path / "ops" / "onchain-regime.json"
    out_md = tmp_path / "ops" / "onchain-regime.md"
    parsed = build_parser().parse_args(
        [
            "--candles",
            str(btc),
            "--candles",
            str(eth),
            "--binance-candles",
            str(btc_usdt),
            "--binance-candles",
            str(eth_usdt),
            "--onchain-json",
            str(rows_path),
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
        ]
    )
    kraken = {
        "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=primary),
        "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=primary),
    }
    written_json, written_md = run(parsed, settings=settings(), candidates=_tiny_base(kraken))
    assert written_json.is_file() and written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["regime_status"] == "ok"
    assert payload["can_promote"] is False
    assert payload["keep_flag_false"] is True
    assert payload["any_overlay_passer"] in (True, False)
    assert payload["overlay_passer_rule"] == OVERLAY_PASSER_RULE
    text = written_md.read_text()
    assert "On-chain regime overlay" in text
    assert "Coin Metrics rows loaded offline" in text
    assert settings().onchain_regime_gate_enabled is False
    assert settings().paper_promote_ema_9_21 is False


def test_cli_offline_without_rows_skips_overlays(tmp_path: Path) -> None:
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    write_candles(btc, uptrend(200, symbol="BTC/USD", start=primary))
    write_candles(eth, uptrend(200, symbol="ETH/USD", start=primary))
    parsed = build_parser().parse_args(
        [
            "--candles",
            str(btc),
            "--candles",
            str(eth),
            "--no-binance",
            "--output-json",
            str(tmp_path / "o.json"),
            "--output-md",
            str(tmp_path / "o.md"),
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
            "--min-trades",
            "1",
        ]
    )
    kraken = {
        "BTC/USD@1d": uptrend(200, symbol="BTC/USD", start=primary),
        "ETH/USD@1d": uptrend(200, symbol="ETH/USD", start=primary),
    }
    written_json, _ = run(parsed, settings=settings(), candidates=_tiny_base(kraken))
    payload = json.loads(written_json.read_text())
    assert payload["regime_status"] == "skipped"
    assert "without --onchain-json" in payload["regime_skip_reason"]
    assert payload["overlay_passer_ids"] == []


def test_cli_live_coinmetrics_failure_skips_overlays_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import traderstack.research.onchain_regime_cli as cli

    primary = datetime(2024, 9, 22, tzinfo=UTC)
    kraken = {
        "BTC/USD@1d": uptrend(200, symbol="BTC/USD", start=primary),
        "ETH/USD@1d": uptrend(200, symbol="ETH/USD", start=primary),
    }

    def fake_histories(args):
        return dict(kraken), ["fixture Kraken histories"]

    def broken(base_url: str, asset: str):
        raise httpx.ConnectError("community-api down")

    monkeypatch.setattr(cli, "_load_histories", fake_histories)
    monkeypatch.setattr(cli, "fetch_live_regime_rows", broken)
    parsed = build_parser().parse_args(
        [
            "--live",
            "--no-binance",
            "--output-json",
            str(tmp_path / "o.json"),
            "--output-md",
            str(tmp_path / "o.md"),
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
            "--min-trades",
            "1",
        ]
    )
    written_json, _ = cli.run(parsed, settings=settings(), candidates=_tiny_base(kraken))
    payload = json.loads(written_json.read_text())
    assert payload["regime_status"] == "skipped"
    assert "ConnectError" in payload["regime_skip_reason"]
    assert payload["any_overlay_passer"] is False
    out = capsys.readouterr().out
    assert "NO OVERLAY PASSER" in out
    assert "PAPER_PROMOTE_* flags are unchanged" in out


def test_committed_live_report_is_empty_success() -> None:
    text = Path("docs/artifacts/strategy-search/onchain-regime.md").read_text()
    assert "Overlay passers: 0" in text
    assert "`keep_flag_false=true`" in text
    assert "`can_promote=false`" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert "coinmetrics:community:v4:CapMVRVCur+CapMrktCurUSD" in text
    assert "HTTP 403 on the community plan" in text
    assert "tsmom_lo_21__mvrvz_p90" in text
    assert "tsmom_ls_252__nupl_075" in text
    assert settings().onchain_regime_gate_enabled is False
