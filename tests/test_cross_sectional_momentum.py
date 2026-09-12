from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.cross_sectional_momentum import (
    CONTROL_ID,
    CONTROL_IDS,
    CORE_IDS,
    CROSS_SECTIONAL_RULES,
    MULTI_ASSET_GATE_RULE,
    PAPER_PATH_READY,
    XS_IDS,
    XS_LOOKBACKS,
    aligned_triple_days,
    rank_xs_momentum_passers,
    render_cross_sectional_momentum_markdown,
    run_cross_sectional_momentum_search,
    skipped_xs_families,
    xs_momentum_candidates,
    xs_momentum_signals,
)
from traderstack.research.cross_sectional_momentum_cli import build_parser, run
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
)
from traderstack.research.second_print import DOCUMENTED_PRIMARY_FIRST_ISO, SECOND_PRINT_BARS
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
    step_days: int = 1,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=opened + timedelta(days=index * step_days),
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


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _rotating_histories(
    count: int = 80, *, start: datetime | None = None
) -> dict[str, tuple[Candle, ...]]:
    """BTC then ETH then SOL outperform in 21-day blocks so ranks rotate."""
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    btc = [100.0]
    eth = [100.0]
    sol = [100.0]
    for index in range(1, count):
        phase = (index // 21) % 3
        btc.append(btc[-1] * (1.012 if phase == 0 else 0.997))
        eth.append(eth[-1] * (1.012 if phase == 1 else 0.997))
        sol.append(sol[-1] * (1.012 if phase == 2 else 0.997))
    return {
        "BTC/USD@1d": make_candles(btc, symbol="BTC/USD", start=opened),
        "ETH/USD@1d": make_candles(eth, symbol="ETH/USD", start=opened),
        "SOL/USD@1d": make_candles(sol, symbol="SOL/USD", start=opened),
    }


def _tiny_catalog():
    return xs_momentum_candidates(_rotating_histories(80))


def _search(
    kraken: dict[str, tuple[Candle, ...]],
    binance: dict[str, tuple[Candle, ...]] | None = None,
    **overrides: object,
):
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "candidates": _tiny_catalog(),
    }
    kwargs.update(overrides)
    return run_cross_sectional_momentum_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


def _row(
    candidate_id: str,
    *,
    kraken_combined: bool,
    binance_combined: bool,
    kraken_ho: float | None,
    binance_ho: float | None = None,
) -> DualPrintRow:
    return DualPrintRow(
        candidate_id=candidate_id,
        family="xs_momentum",
        label=candidate_id,
        kraken_combined=kraken_combined,
        binance_combined=binance_combined,
        dual_print=kraken_combined and binance_combined,
        kraken_mean_holdout_excess=kraken_ho,
        binance_mean_holdout_excess=binance_ho,
    )


def test_promote_defaults_stay_false() -> None:
    cfg = settings()
    assert cfg.paper_promote_ema_9_21 is False
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.paper_promote_searched_strategies is False
    assert cfg.paper_garch_size is False
    assert not hasattr(cfg, "paper_promote_xs_mom_ls_21")
    assert not hasattr(cfg, "paper_promote_cross_sectional_momentum")


def test_catalog_and_bar_are_frozen_before_scoring() -> None:
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert PAPER_PATH_READY is True
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in CROSS_SECTIONAL_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in CROSS_SECTIONAL_RULES
    assert "CAN_AVERAGE_VENUES=false" in CROSS_SECTIONAL_RULES
    assert MULTI_ASSET_GATE_RULE == "btc_eth_signs_as_96_abc_sol_reported_not_required"
    assert MULTI_ASSET_GATE_RULE in CROSS_SECTIONAL_RULES
    assert XS_LOOKBACKS == (21, 63, 126)
    assert SECOND_PRINT_BARS == 720
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"
    catalog = xs_momentum_candidates(_rotating_histories(200))
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert ids[:3] == ["xs_mom_ls_21", "xs_mom_ls_63", "xs_mom_ls_126"]
    assert ids[3:6] == ["xs_mom_lo_21", "xs_mom_lo_63", "xs_mom_lo_126"]
    assert ids[6:9] == ["xs_mom_ls_vol_21", "xs_mom_ls_vol_63", "xs_mom_ls_vol_126"]
    assert ids[9:12] == ["xs_mom_lo_vol_21", "xs_mom_lo_vol_63", "xs_mom_lo_vol_126"]
    assert ids[-1] == CONTROL_ID
    assert set(XS_IDS) | CONTROL_IDS == set(CORE_IDS)
    assert "ema_9_21" not in ids
    assert "rv_fade_1_0" not in ids
    assert "equal-weight portfolio metrics are not used" in CROSS_SECTIONAL_RULES.lower()


def test_missing_sol_skips_xs_names() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(80, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(80, symbol="ETH/USD", start=start),
    }
    assert aligned_triple_days({"BTC/USD": {}, "ETH/USD": {}, "SOL/USD": {}}) == ()
    catalog = xs_momentum_candidates(histories)
    assert [item.candidate_id for item in catalog] == [CONTROL_ID]
    skipped = skipped_xs_families(histories)
    assert {item["candidate_id"] for item in skipped} == set(XS_IDS)
    assert all("invent" in item["reason"] for item in skipped)


def test_unpaired_day_is_skipped_not_invented() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    count = 40
    btc = make_candles([100.0 + index for index in range(count)], symbol="BTC/USD", start=start)
    eth = make_candles([100.0] * count, symbol="ETH/USD", start=start)
    sol = make_candles([100.0] * count, symbol="SOL/USD", start=start)
    # Drop one SOL bar so that day cannot enter the triple.
    sol = sol[:10] + sol[11:]
    mapping = xs_momentum_signals(
        {
            "BTC/USD@1d": btc,
            "ETH/USD@1d": eth,
            "SOL/USD@1d": sol,
        },
        lookback=21,
        long_short=True,
        vol_scaled=False,
    )
    dropped = start + timedelta(days=10)
    assert dropped not in {ts for ts, _ in mapping["BTC/USD"]}


def test_long_short_and_long_only_assignments() -> None:
    histories = _rotating_histories(50)
    ls = xs_momentum_signals(histories, lookback=21, long_short=True, vol_scaled=False)
    lo = xs_momentum_signals(histories, lookback=21, long_short=False, vol_scaled=False)
    catalog = xs_momentum_candidates(histories)
    ls_voter = next(item for item in catalog if item.candidate_id == "xs_mom_ls_21")
    lo_voter = next(item for item in catalog if item.candidate_id == "xs_mom_lo_21")
    last_ts = histories["BTC/USD@1d"][-1].opened_at
    ls_by_asset = {
        asset: dict(series)[last_ts]
        for asset, series in ls.items()
        if asset in {"BTC/USD", "ETH/USD", "SOL/USD"}
    }
    lo_by_asset = {
        asset: dict(series)[last_ts]
        for asset, series in lo.items()
        if asset in {"BTC/USD", "ETH/USD", "SOL/USD"}
    }
    assert sum(1 for value in ls_by_asset.values() if value > 0) == 1
    assert sum(1 for value in ls_by_asset.values() if value < 0) == 1
    assert sum(1 for value in lo_by_asset.values() if value > 0) == 1
    assert sum(1 for value in lo_by_asset.values() if value < 0) == 0
    btc_window = histories["BTC/USD@1d"]
    eth_window = histories["ETH/USD@1d"]
    sol_window = histories["SOL/USD@1d"]
    sides = {
        "BTC/USD": ls_voter.strategy.evaluate(btc_window, Regime.RANGE).side,
        "ETH/USD": ls_voter.strategy.evaluate(eth_window, Regime.RANGE).side,
        "SOL/USD": ls_voter.strategy.evaluate(sol_window, Regime.RANGE).side,
    }
    assert list(sides.values()).count(Side.BUY) == 1
    assert list(sides.values()).count(Side.SELL) == 1
    lo_sides = {
        "BTC/USD": lo_voter.strategy.evaluate(btc_window, Regime.RANGE).side,
        "ETH/USD": lo_voter.strategy.evaluate(eth_window, Regime.RANGE).side,
        "SOL/USD": lo_voter.strategy.evaluate(sol_window, Regime.RANGE).side,
    }
    assert list(lo_sides.values()).count(Side.BUY) == 1
    assert list(lo_sides.values()).count(Side.SELL) == 0


def test_same_bar_only_no_stale_hold() -> None:
    histories = _rotating_histories(50)
    catalog = xs_momentum_candidates(histories)
    voter = next(item for item in catalog if item.candidate_id == "xs_mom_ls_21")
    prefix = histories["BTC/USD@1d"][:10]
    signal = voter.strategy.evaluate(prefix, Regime.RANGE)
    assert signal.side is None
    assert "skipped" in signal.rationale


def test_control_cannot_enter_dual_print_ranking() -> None:
    rows = [
        _row(CONTROL_ID, kraken_combined=True, binance_combined=True, kraken_ho=0.50),
        _row("xs_mom_ls_21", kraken_combined=True, binance_combined=True, kraken_ho=0.08),
        _row("xs_mom_lo_63", kraken_combined=True, binance_combined=False, kraken_ho=0.40),
    ]
    passers = rank_xs_momentum_passers(rows)
    assert [row.candidate_id for row in passers] == ["xs_mom_ls_21"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False
    assert all(row.candidate_id != CONTROL_ID for row in passers)


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "xs_mom_ls_21",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.05,
            binance_ho=0.40,
        ),
        _row(
            "xs_mom_ls_63",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "xs_mom_lo_21",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.90,
        ),
    ]
    passers = rank_xs_momentum_passers(rows)
    assert [row.candidate_id for row in passers] == ["xs_mom_ls_63", "xs_mom_ls_21"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_ranking_tie_breaks_on_candidate_id() -> None:
    rows = [
        _row("xs_mom_lo_21", kraken_combined=True, binance_combined=True, kraken_ho=0.10),
        _row("xs_mom_ls_21", kraken_combined=True, binance_combined=True, kraken_ho=0.10),
    ]
    passers = rank_xs_momentum_passers(rows)
    assert [row.candidate_id for row in passers] == ["xs_mom_lo_21", "xs_mom_ls_21"]


def test_empty_binance_is_success_and_cannot_promote() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=start),
            "SOL/USD@1d": downtrend(240, symbol="SOL/USD", start=start),
        },
        {},
    )
    assert report.binance_slice.available is False
    assert report.any_dual_print_passer is False
    assert report.selected_candidate_id is None
    assert report.recommended_promote_flag is None
    assert report.keep_flag_false is True
    assert report.paper_path_ready is True
    assert report.multi_venue_bar_preregistered is True
    assert report.can_average_venues is False
    assert report.multi_asset_gate_rule == MULTI_ASSET_GATE_RULE
    rendered = render_cross_sectional_momentum_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "paper-executable on Kraken spot" in rendered
    assert "Cross-sectional momentum" in rendered
    assert "SOL reported" in rendered
    assert settings().paper_promote_ema_9_21_adx15 is False


def test_short_binance_slice_fails_closed() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2023, 1, 1, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=primary),
            "SOL/USD@1d": downtrend(240, symbol="SOL/USD", start=primary),
        },
        {
            "BTCUSDT@1d": downtrend(100, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(100, symbol="ETHUSDT", start=older),
            "SOLUSDT@1d": downtrend(100, symbol="SOLUSDT", start=older),
        },
    )
    assert report.binance_slice.available is False
    assert "shorter than 720" in (report.binance_slice.fail_closed_reason or "")
    assert report.any_dual_print_passer is False
    assert report.keep_flag_false is True


def test_binance_older_slice_is_scored_and_cannot_promote() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    kraken = {
        "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=primary),
        "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=primary),
        "SOL/USD@1d": downtrend(240, symbol="SOL/USD", start=primary),
    }
    report = _search(
        kraken,
        {
            "BTCUSDT@1d": downtrend(720, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(720, symbol="ETHUSDT", start=older),
            "SOLUSDT@1d": downtrend(720, symbol="SOLUSDT", start=older),
        },
        binance_source="binance_us_spot",
        candidates=None,
    )
    assert report.binance_slice.available is True
    assert report.binance_slice.overlaps_primary_window is False
    assert report.binance_slice.bars_btc == 720
    assert report.binance_slice.bars_sol == 720
    assert report.keep_flag_false is True
    assert all(row.can_promote is False for row in report.rows)
    assert CONTROL_ID not in report.dual_print_passer_ids
    rendered = render_cross_sectional_momentum_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert "Do not re-run dead EMA dual-prints" in rendered
    assert "equal-weight" in rendered.lower()


def test_committed_live_report_is_empty_success() -> None:
    text = Path("docs/artifacts/strategy-search/cross-sectional-momentum.md").read_text()
    assert "Dual-print passers: 0" in text
    assert "`keep_flag_false=true`" in text
    assert "Do not add a new promote flag" in text
    assert "PAPER_PROMOTE_*" in text
    assert "xs_mom_lo_vol_63" in text
    assert settings().paper_promote_ema_9_21 is False
    assert not hasattr(settings(), "paper_promote_xs_mom_ls_21")


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "cross-sectional-momentum.md"

    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    sol = tmp_path / "sol.json"
    btc_usdt = tmp_path / "btcusdt.json"
    eth_usdt = tmp_path / "ethusdt.json"
    sol_usdt = tmp_path / "solusdt.json"
    write_candles(btc, downtrend(240, symbol="BTC/USD", start=primary))
    write_candles(eth, downtrend(240, symbol="ETH/USD", start=primary))
    write_candles(sol, downtrend(240, symbol="SOL/USD", start=primary))
    write_candles(btc_usdt, downtrend(720, symbol="BTCUSDT", start=older))
    write_candles(eth_usdt, downtrend(720, symbol="ETHUSDT", start=older))
    write_candles(sol_usdt, downtrend(720, symbol="SOLUSDT", start=older))
    out_json = tmp_path / "ops" / "xs.json"
    out_md = tmp_path / "ops" / "xs.md"
    parsed = build_parser().parse_args(
        [
            "--candles",
            str(btc),
            "--candles",
            str(eth),
            "--candles",
            str(sol),
            "--binance-candles",
            str(btc_usdt),
            "--binance-candles",
            str(eth_usdt),
            "--binance-candles",
            str(sol_usdt),
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
    written_json, written_md = run(parsed, settings=settings(), candidates=_tiny_catalog())
    assert written_json.is_file()
    assert written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["ranking_key"] == RANKING_KEY
    assert payload["keep_flag_false"] is True
    assert payload["paper_path_ready"] is True
    assert payload["multi_venue_bar_preregistered"] is True
    assert payload["can_average_venues"] is False
    assert payload["any_dual_print_passer"] is False
    assert payload["selected_candidate_id"] is None
    assert payload["multi_asset_gate_rule"] == MULTI_ASSET_GATE_RULE
    text = written_md.read_text()
    assert "Cross-sectional momentum dual-print" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False
