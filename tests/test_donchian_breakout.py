from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.donchian_breakout import (
    CONTROL_ID,
    CONTROL_IDS,
    CORE_IDS,
    DONCHIAN_ATR_LOOKBACKS,
    DONCHIAN_ATR_PERIOD,
    DONCHIAN_IDS,
    DONCHIAN_LOOKBACKS,
    DONCHIAN_RULES,
    EXIT_RULE,
    MULTI_ASSET_GATE_RULE,
    PAPER_PATH_READY,
    donchian_candidates,
    donchian_position_series,
    donchian_signals,
    eth_carried_informational,
    prior_channel,
    rank_donchian_passers,
    render_donchian_breakout_markdown,
    run_donchian_breakout_search,
    skipped_donchian_families,
    wilder_atr,
)
from traderstack.research.donchian_breakout_cli import build_parser, run
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
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        high = highs[index] if highs is not None else max(previous, price) * 1.002
        low = lows[index] if lows is not None else min(previous, price) * 0.998
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=opened + timedelta(days=index),
                open=previous,
                high=high,
                low=low,
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


def _breakout_histories(
    count: int = 160, *, start: datetime | None = None
) -> dict[str, tuple[Candle, ...]]:
    """Uptrend then fade so a 20-day channel can enter and later exit."""
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    prices = [100.0]
    for index in range(1, count):
        if index < 80:
            prices.append(prices[-1] * 1.008)
        else:
            prices.append(prices[-1] * 0.995)
    return {
        "BTC/USD@1d": make_candles(prices, symbol="BTC/USD", start=opened),
        "ETH/USD@1d": make_candles(prices, symbol="ETH/USD", start=opened),
        "SOL/USD@1d": make_candles(prices, symbol="SOL/USD", start=opened),
    }


def _tiny_catalog():
    return donchian_candidates(_breakout_histories(160))


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
    return run_donchian_breakout_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


def _row(
    candidate_id: str,
    *,
    kraken_combined: bool,
    binance_combined: bool,
    kraken_ho: float | None,
    binance_ho: float | None = None,
    kraken_btc_ho: float | None = None,
    kraken_eth_ho: float | None = None,
) -> DualPrintRow:
    return DualPrintRow(
        candidate_id=candidate_id,
        family="donchian",
        label=candidate_id,
        kraken_combined=kraken_combined,
        binance_combined=binance_combined,
        dual_print=kraken_combined and binance_combined,
        kraken_mean_holdout_excess=kraken_ho,
        binance_mean_holdout_excess=binance_ho,
        kraken_btc_holdout=kraken_btc_ho,
        kraken_eth_holdout=kraken_eth_ho,
    )


def test_promote_defaults_stay_false() -> None:
    cfg = settings()
    assert cfg.paper_promote_ema_9_21 is False
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.paper_promote_searched_strategies is False
    assert cfg.paper_garch_size is False
    assert not hasattr(cfg, "paper_promote_donchian_lo_20")
    assert not hasattr(cfg, "paper_promote_donchian_breakout")


def test_catalog_and_bar_are_frozen_before_scoring() -> None:
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert PAPER_PATH_READY is True
    assert EXIT_RULE == "opposite_band_same_n"
    assert DONCHIAN_ATR_PERIOD == 14
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in DONCHIAN_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in DONCHIAN_RULES
    assert "CAN_AVERAGE_VENUES=false" in DONCHIAN_RULES
    assert MULTI_ASSET_GATE_RULE == "btc_eth_signs_as_96_abc_sol_reported_not_required"
    assert MULTI_ASSET_GATE_RULE in DONCHIAN_RULES
    assert DONCHIAN_LOOKBACKS == (20, 55, 100)
    assert DONCHIAN_ATR_LOOKBACKS == (20, 55)
    assert SECOND_PRINT_BARS == 720
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"
    catalog = donchian_candidates(_breakout_histories(200))
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert ids[:3] == ["donchian_lo_20", "donchian_lo_55", "donchian_lo_100"]
    assert ids[3:6] == ["donchian_ls_20", "donchian_ls_55", "donchian_ls_100"]
    assert ids[6:8] == ["donchian_lo_atr_20", "donchian_lo_atr_55"]
    assert ids[-1] == CONTROL_ID
    assert set(DONCHIAN_IDS) | CONTROL_IDS == set(CORE_IDS)
    assert "ema_9_21" not in ids
    assert "rv_fade_1_0" not in ids
    assert "xs_mom_lo_21" not in ids
    assert "equal-weight portfolio metrics are not used" in DONCHIAN_RULES.lower()
    freeze = Path("docs/artifacts/strategy-search/donchian-breakout.md").read_text()
    assert "donchian_lo_20" in freeze
    assert "donchian_lo_atr_55" in freeze
    assert "ma_cross_10_30" in freeze
    assert "PAPER_PROMOTE_*" in freeze


def test_missing_sol_does_not_skip_btc_eth_names() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(160, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(160, symbol="ETH/USD", start=start),
    }
    catalog = donchian_candidates(histories)
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert skipped_donchian_families(histories) == []


def test_short_history_skips_not_invented() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(10, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(10, symbol="ETH/USD", start=start),
    }
    catalog = donchian_candidates(histories)
    assert [item.candidate_id for item in catalog] == [CONTROL_ID]
    skipped = skipped_donchian_families(histories)
    assert {item["candidate_id"] for item in skipped} == set(DONCHIAN_IDS)
    assert all("invent" in item["reason"] for item in skipped)


def test_channel_excludes_bar_t_high_and_uses_close() -> None:
    # 20 flat bars, then a spike high with a close that still clears the prior high.
    prices = [100.0] * 20 + [105.0]
    highs = [100.0] * 20 + [200.0]
    lows = [99.0] * 21
    candles = make_candles(prices, highs=highs, lows=lows)
    assert prior_channel(candles, 20, 20) == (100.0, 99.0)
    series = donchian_position_series(candles, channel_n=20, long_short=False, use_atr=False)
    assert series[-1][1] == 1.0

    # Spike high with close still inside the prior channel must stay flat.
    inside = make_candles([100.0] * 20 + [99.5], highs=[100.0] * 20 + [200.0], lows=[99.0] * 21)
    inside_series = donchian_position_series(inside, channel_n=20, long_short=False, use_atr=False)
    assert inside_series[-1][1] == 0.0


def test_long_only_exits_flat_long_short_goes_short() -> None:
    up = [100.0 + index for index in range(25)]
    down = [124.0 - 3.0 * index for index in range(1, 15)]
    prices = up + down
    candles = make_candles(prices)
    lo = dict(donchian_position_series(candles, channel_n=20, long_short=False, use_atr=False))
    ls = dict(donchian_position_series(candles, channel_n=20, long_short=True, use_atr=False))
    last = candles[-1].opened_at
    assert lo[last] == 0.0
    assert ls[last] == -1.0


def test_atr_buffer_requires_a_wider_close() -> None:
    prices = [100.0] * 30 + [100.4]
    highs = [100.2] * 30 + [100.5]
    lows = [99.8] * 31
    candles = make_candles(prices, highs=highs, lows=lows)
    unbuffered = donchian_position_series(candles, channel_n=20, long_short=False, use_atr=False)
    buffered = donchian_position_series(candles, channel_n=20, long_short=False, use_atr=True)
    assert unbuffered[-1][1] == 1.0
    assert buffered[-1][1] == 0.0
    atr = wilder_atr(candles[:-1], DONCHIAN_ATR_PERIOD)
    assert atr is not None and atr > 0.2


def test_voter_maps_long_short_and_flat() -> None:
    histories = _breakout_histories(60)
    catalog = donchian_candidates(histories)
    voter = next(item for item in catalog if item.candidate_id == "donchian_ls_20")
    btc = histories["BTC/USD@1d"]
    signal = voter.strategy.evaluate(btc, Regime.RANGE)
    assert signal.side in {Side.BUY, Side.SELL, None}
    warmup = voter.strategy.evaluate(btc[:10], Regime.RANGE)
    assert warmup.side is None
    assert "warmup" in warmup.rationale


def test_control_cannot_enter_dual_print_ranking() -> None:
    rows = [
        _row(CONTROL_ID, kraken_combined=True, binance_combined=True, kraken_ho=0.50),
        _row("donchian_lo_20", kraken_combined=True, binance_combined=True, kraken_ho=0.08),
        _row("donchian_ls_55", kraken_combined=True, binance_combined=False, kraken_ho=0.40),
    ]
    passers = rank_donchian_passers(rows)
    assert [row.candidate_id for row in passers] == ["donchian_lo_20"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False
    assert all(row.candidate_id != CONTROL_ID for row in passers)


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "donchian_lo_20",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.05,
            binance_ho=0.40,
        ),
        _row(
            "donchian_lo_55",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "donchian_ls_20",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.90,
        ),
    ]
    passers = rank_donchian_passers(rows)
    assert [row.candidate_id for row in passers] == ["donchian_lo_55", "donchian_lo_20"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_eth_carried_mean_is_flagged_96_fail() -> None:
    rows = [
        _row(
            "donchian_lo_20",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.07,
            kraken_btc_ho=-0.16,
            kraken_eth_ho=0.30,
        ),
        _row(
            "donchian_ls_20",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=-0.02,
            kraken_btc_ho=-0.01,
            kraken_eth_ho=-0.03,
        ),
    ]
    flagged = eth_carried_informational(rows)
    assert [row.candidate_id for row in flagged] == ["donchian_lo_20"]


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
    rendered = render_donchian_breakout_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "paper-executable on Kraken spot" in rendered
    assert "Donchian / channel-breakout" in rendered
    assert "SOL reported" in rendered
    assert settings().paper_promote_ema_9_21_adx15 is False


def test_short_binance_slice_fails_closed() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2023, 1, 1, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=primary),
        },
        {
            "BTCUSDT@1d": downtrend(100, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(100, symbol="ETHUSDT", start=older),
        },
    )
    assert report.binance_slice.available is False
    assert "shorter than 720" in (report.binance_slice.fail_closed_reason or "")
    assert report.any_dual_print_passer is False
    assert report.keep_flag_false is True


def test_binance_older_slice_is_scored_and_cannot_promote() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=primary),
            "SOL/USD@1d": downtrend(240, symbol="SOL/USD", start=primary),
        },
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
    assert report.keep_flag_false is True
    assert all(row.can_promote is False for row in report.rows)
    assert CONTROL_ID not in report.dual_print_passer_ids
    rendered = render_donchian_breakout_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert "Do not re-run dead EMA dual-prints" in rendered
    assert "#117" in rendered
    assert "equal-weight" in rendered.lower()


def test_signals_do_not_require_paired_days() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = make_candles([100.0 + index for index in range(40)], symbol="BTC/USD", start=start)
    eth = make_candles([100.0] * 40, symbol="ETH/USD", start=start)[:30]
    mapping = donchian_signals(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        channel_n=20,
        long_short=False,
        use_atr=False,
    )
    assert mapping["BTC/USD"]
    assert mapping["ETH/USD"]
    assert len(mapping["BTC/USD"]) != len(mapping["ETH/USD"])


def test_committed_live_report_is_empty_success() -> None:
    text = Path("docs/artifacts/strategy-search/donchian-breakout.md").read_text()
    assert "Dual-print passers: 0" in text
    assert "`keep_flag_false=true`" in text
    assert "Do not add a new promote flag" in text
    assert "PAPER_PROMOTE_*" in text
    assert "donchian_ls_20" in text
    assert "donchian_lo_atr_55" in text
    assert settings().paper_promote_ema_9_21 is False
    assert not hasattr(settings(), "paper_promote_donchian_lo_20")


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "donchian-breakout.md"

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
    out_json = tmp_path / "ops" / "donchian.json"
    out_md = tmp_path / "ops" / "donchian.md"
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
    assert "Donchian / channel-breakout dual-print" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False
