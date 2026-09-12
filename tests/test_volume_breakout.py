from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
)
from traderstack.research.second_print import DOCUMENTED_PRIMARY_FIRST_ISO, SECOND_PRINT_BARS
from traderstack.research.volume_breakout import (
    CONTROL_ID,
    CONTROL_IDS,
    CORE_IDS,
    EXIT_RULE,
    FILL_RULE,
    MULTI_ASSET_GATE_RULE,
    PAPER_PATH_READY,
    QUOTE_VOLUME_OMITTED_REASON,
    VOL_LOOKBACK,
    VOLUME_BREAKOUT_IDS,
    VOLUME_BREAKOUT_RULES,
    VOLUME_SMA_RULE,
    btc_wf_fail_informational,
    eth_carried_informational,
    prior_volume_sma,
    rank_volume_breakout_passers,
    render_volume_breakout_markdown,
    run_volume_breakout_search,
    series_has_usable_volume,
    skipped_volume_breakout_families,
    volbrk_position_series,
    volsurge_position_series,
    volume_breakout_candidates,
    volume_breakout_signals,
    volume_confirmed,
)
from traderstack.research.volume_breakout_cli import build_parser, run
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
    volumes: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        high = highs[index] if highs is not None else max(previous, price) * 1.002
        low = lows[index] if lows is not None else min(previous, price) * 0.998
        high = max(high, previous, price)
        low = min(low, previous, price)
        volume = volumes[index] if volumes is not None else 1_000 + index
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=opened + timedelta(days=index),
                open=previous,
                high=high,
                low=low,
                close=price,
                volume=volume,
            )
        )
    return tuple(candles)


def downtrend(
    count: int, *, symbol: str = "BTC/USD", start: datetime | None = None
) -> tuple[Candle, ...]:
    return make_candles(
        [200.0 - 0.25 * index for index in range(count)], symbol=symbol, start=start
    )


def uptrend(
    count: int, *, symbol: str = "BTC/USD", start: datetime | None = None
) -> tuple[Candle, ...]:
    return make_candles(
        [100.0 + 0.25 * index for index in range(count)], symbol=symbol, start=start
    )


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _momentum_histories(
    count: int = 300, *, start: datetime | None = None
) -> dict[str, tuple[Candle, ...]]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return {
        "BTC/USD@1d": uptrend(count, symbol="BTC/USD", start=opened),
        "ETH/USD@1d": uptrend(count, symbol="ETH/USD", start=opened),
        "SOL/USD@1d": uptrend(count, symbol="SOL/USD", start=opened),
    }


def _tiny_catalog():
    return volume_breakout_candidates(_momentum_histories(80), include_control=True)


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
    return run_volume_breakout_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


def _row(
    candidate_id: str,
    *,
    kraken_combined: bool,
    binance_combined: bool,
    kraken_ho: float | None,
    binance_ho: float | None = None,
    kraken_btc_ho: float | None = None,
    kraken_eth_ho: float | None = None,
    kraken_btc_wf: float | None = None,
) -> DualPrintRow:
    return DualPrintRow(
        candidate_id=candidate_id,
        family="volume_breakout",
        label=candidate_id,
        kraken_combined=kraken_combined,
        binance_combined=binance_combined,
        dual_print=kraken_combined and binance_combined,
        kraken_mean_holdout_excess=kraken_ho,
        binance_mean_holdout_excess=binance_ho,
        kraken_btc_holdout=kraken_btc_ho,
        kraken_eth_holdout=kraken_eth_ho,
        kraken_btc_wf=kraken_btc_wf,
    )


def test_promote_defaults_stay_false() -> None:
    cfg = settings()
    assert cfg.paper_promote_ema_9_21 is False
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.paper_promote_searched_strategies is False
    assert cfg.paper_garch_size is False
    assert not hasattr(cfg, "paper_promote_volbrk_lo_20x1_5")
    assert not hasattr(cfg, "paper_promote_volume_breakout")


def test_catalog_and_bar_are_frozen_before_scoring() -> None:
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert PAPER_PATH_READY is True
    assert VOLUME_SMA_RULE == "volume_sma_through_t_minus_1"
    assert EXIT_RULE == "opposite_band_same_n"
    assert FILL_RULE == "next_bar_open"
    assert VOL_LOOKBACK == 20
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in VOLUME_BREAKOUT_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in VOLUME_BREAKOUT_RULES
    assert "CAN_AVERAGE_VENUES=false" in VOLUME_BREAKOUT_RULES
    assert MULTI_ASSET_GATE_RULE == "btc_eth_signs_as_96_abc_sol_reported_not_required"
    assert MULTI_ASSET_GATE_RULE in VOLUME_BREAKOUT_RULES
    assert VOLUME_SMA_RULE in VOLUME_BREAKOUT_RULES
    assert "not a Donchian N retune" in VOLUME_BREAKOUT_RULES
    assert QUOTE_VOLUME_OMITTED_REASON.split(";")[0] in VOLUME_BREAKOUT_RULES
    assert "equal-weight portfolio metrics are not used" in VOLUME_BREAKOUT_RULES.lower()
    assert SECOND_PRINT_BARS == 720
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"
    catalog = volume_breakout_candidates(_momentum_histories(80))
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert ids[:3] == ["volbrk_lo_20x1_5", "volbrk_lo_55x1_5", "volbrk_lo_20x2"]
    assert ids[3:5] == ["volbrk_ls_20x1_5", "volbrk_ls_55x1_5"]
    assert ids[5:7] == ["volsurge_lo_20x2", "volsurge_lo_20x2_5"]
    assert ids[-1] == CONTROL_ID
    assert set(VOLUME_BREAKOUT_IDS) | CONTROL_IDS == set(CORE_IDS)
    assert "ema_9_21" not in ids
    assert "rv_fade_1_0" not in ids
    assert "xs_mom_lo_21" not in ids
    assert "donchian_lo_20" not in ids
    assert "tsmom_lo_21" not in ids
    assert "bb_fade_20x2" not in ids
    assert "cal_dow_lo_mon" not in ids
    assert "leadlag_eth_follow_lo_1" not in ids
    freeze = Path("docs/artifacts/strategy-search/volume-breakout.md").read_text()
    assert "volbrk_lo_20x1_5" in freeze
    assert "volbrk_ls_55x1_5" in freeze
    assert "volsurge_lo_20x2_5" in freeze
    assert "ma_cross_10_30" in freeze
    assert "PAPER_PROMOTE_*" in freeze
    assert "volume_sma_through_t_minus_1" in freeze
    assert "Not yet run" in freeze or "Dual-print passers" in freeze


def test_missing_sol_does_not_skip_btc_eth_names() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(80, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(80, symbol="ETH/USD", start=start),
    }
    catalog = volume_breakout_candidates(histories)
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert skipped_volume_breakout_families(histories) == []


def test_short_history_skips_not_invented() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(10, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(10, symbol="ETH/USD", start=start),
    }
    catalog = volume_breakout_candidates(histories)
    assert [item.candidate_id for item in catalog] == [CONTROL_ID]
    skipped = skipped_volume_breakout_families(histories)
    assert {item["candidate_id"] for item in skipped} == set(VOLUME_BREAKOUT_IDS)
    assert all("invent" in item["reason"] for item in skipped)


def test_all_zero_volume_fails_closed() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    prices = [100.0 + index for index in range(80)]
    histories = {
        "BTC/USD@1d": make_candles(prices, symbol="BTC/USD", start=start, volumes=[0.0] * 80),
        "ETH/USD@1d": make_candles(prices, symbol="ETH/USD", start=start, volumes=[0.0] * 80),
    }
    assert series_has_usable_volume(histories["BTC/USD@1d"]) is False
    catalog = volume_breakout_candidates(histories)
    assert [item.candidate_id for item in catalog] == [CONTROL_ID]
    skipped = skipped_volume_breakout_families(histories)
    assert {item["candidate_id"] for item in skipped} == set(VOLUME_BREAKOUT_IDS)
    assert all("quote volume" in item["reason"].lower() for item in skipped)


def test_volume_sma_excludes_bar_t() -> None:
    volumes = [100.0] * 20 + [151.0]
    prices = [10.0] * 21
    candles = make_candles(prices, volumes=volumes)
    assert prior_volume_sma(candles, 20, 20) == pytest.approx(100.0)
    # Including t would raise the SMA and reject 151 vs 1.5×.
    through_t = (sum(volumes)) / 21
    assert 151.0 > 100.0 * 1.5
    assert 151.0 < through_t * 1.5
    assert volume_confirmed(candles, 20, vol_lookback=20, vol_mult=1.5) is True


def test_breakout_channel_excludes_bar_t_high() -> None:
    prices = [100.0] * 21
    highs = [100.0] * 20 + [200.0]
    lows = [99.0] * 21
    volumes = [100.0] * 20 + [200.0]
    candles = make_candles(prices, volumes=volumes, highs=highs, lows=lows)
    series = volbrk_position_series(
        candles, channel_n=20, vol_lookback=20, vol_mult=1.5, long_short=False
    )
    assert series
    assert series[-1][1] == 0.0


def test_price_breakout_without_volume_does_not_enter() -> None:
    prices = [100.0] * 20 + [120.0]
    highs = [100.0] * 20 + [120.0]
    lows = [99.0] * 21
    volumes = [100.0] * 20 + [101.0]
    candles = make_candles(prices, volumes=volumes, highs=highs, lows=lows)
    series = volbrk_position_series(
        candles, channel_n=20, vol_lookback=20, vol_mult=1.5, long_short=False
    )
    assert series[-1][1] == 0.0
    confirmed = volume_confirmed(candles, 20, vol_lookback=20, vol_mult=1.5)
    assert confirmed is False


def test_volume_confirmed_breakout_enters() -> None:
    prices = [100.0] * 20 + [120.0]
    highs = [100.0] * 20 + [120.0]
    lows = [99.0] * 21
    volumes = [100.0] * 20 + [200.0]
    candles = make_candles(prices, volumes=volumes, highs=highs, lows=lows)
    series = volbrk_position_series(
        candles, channel_n=20, vol_lookback=20, vol_mult=1.5, long_short=False
    )
    assert series[-1][1] == 1.0


def test_zero_volume_bar_holds_previous_breakout() -> None:
    prices = [100.0] * 20 + [120.0, 119.0]
    highs = [100.0] * 20 + [120.0, 119.0]
    lows = [99.0] * 22
    volumes = [100.0] * 20 + [200.0, 0.0]
    candles = make_candles(prices, volumes=volumes, highs=highs, lows=lows)
    series = volbrk_position_series(
        candles, channel_n=20, vol_lookback=20, vol_mult=1.5, long_short=False
    )
    by_ts = dict(series)
    entered = candles[20].opened_at
    skipped = candles[21].opened_at
    assert by_ts[entered] == 1.0
    assert by_ts[skipped] == 1.0
    assert volume_confirmed(candles, 21, vol_lookback=20, vol_mult=1.5) is None


def test_long_only_exits_without_volume_gate() -> None:
    # Enter on a confirmed upside break, then crash through the prior low
    # on quiet volume — long-only must flatten.
    prices = [100.0] * 20 + [120.0, 50.0]
    highs = [100.0] * 20 + [120.0, 50.0]
    lows = [99.0] * 20 + [99.0, 49.0]
    volumes = [100.0] * 20 + [200.0, 101.0]
    candles = make_candles(prices, volumes=volumes, highs=highs, lows=lows)
    series = volbrk_position_series(
        candles, channel_n=20, vol_lookback=20, vol_mult=1.5, long_short=False
    )
    assert series[-2][1] == 1.0
    assert series[-1][1] == 0.0


def test_long_short_requires_volume_to_flip() -> None:
    prices = [100.0] * 20 + [120.0, 50.0]
    highs = [100.0] * 20 + [120.0, 50.0]
    lows = [99.0] * 20 + [99.0, 49.0]
    volumes = [100.0] * 20 + [200.0, 101.0]
    candles = make_candles(prices, volumes=volumes, highs=highs, lows=lows)
    series = volbrk_position_series(
        candles, channel_n=20, vol_lookback=20, vol_mult=1.5, long_short=True
    )
    assert series[-2][1] == 1.0
    assert series[-1][1] == 1.0


def test_volume_surge_is_flat_without_up_close() -> None:
    prices = [100.0] * 20 + [90.0]
    volumes = [100.0] * 20 + [250.0]
    candles = make_candles(prices, volumes=volumes)
    series = volsurge_position_series(candles, vol_lookback=20, vol_mult=2.0)
    assert series[-1][1] == 0.0


def test_volume_surge_longs_on_up_close_and_skips_zero_volume() -> None:
    prices = [100.0] * 20 + [110.0, 111.0]
    volumes = [100.0] * 20 + [250.0, 0.0]
    candles = make_candles(prices, volumes=volumes)
    series = volsurge_position_series(candles, vol_lookback=20, vol_mult=2.0)
    by_ts = dict(series)
    assert by_ts[candles[20].opened_at] == 1.0
    assert candles[21].opened_at not in by_ts


def test_voter_maps_long_short_and_flat() -> None:
    histories = _momentum_histories(40)
    catalog = volume_breakout_candidates(histories)
    voter = next(item for item in catalog if item.candidate_id == "volsurge_lo_20x2")
    btc = histories["BTC/USD@1d"]
    signal = voter.strategy.evaluate(btc, Regime.RANGE)
    assert signal.side in {Side.BUY, None}
    warmup = voter.strategy.evaluate(btc[:1], Regime.RANGE)
    assert warmup.side is None
    assert "skipped" in warmup.rationale or "warmup" in warmup.rationale


def test_control_cannot_enter_dual_print_ranking() -> None:
    rows = [
        _row(CONTROL_ID, kraken_combined=True, binance_combined=True, kraken_ho=0.50),
        _row(
            "volbrk_lo_20x1_5",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.08,
        ),
        _row(
            "volbrk_ls_20x1_5",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.40,
        ),
    ]
    passers = rank_volume_breakout_passers(rows)
    assert [row.candidate_id for row in passers] == ["volbrk_lo_20x1_5"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False
    assert all(row.candidate_id != CONTROL_ID for row in passers)


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "volbrk_lo_20x1_5",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.05,
            binance_ho=0.40,
        ),
        _row(
            "volbrk_lo_20x2",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "volsurge_lo_20x2",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.90,
        ),
    ]
    passers = rank_volume_breakout_passers(rows)
    assert [row.candidate_id for row in passers] == [
        "volbrk_lo_20x2",
        "volbrk_lo_20x1_5",
    ]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_eth_carried_mean_is_flagged_96_fail() -> None:
    rows = [
        _row(
            "volbrk_lo_20x1_5",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.07,
            kraken_btc_ho=-0.16,
            kraken_eth_ho=0.30,
        ),
        _row(
            "volsurge_lo_20x2",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=-0.02,
            kraken_btc_ho=-0.01,
            kraken_eth_ho=-0.03,
        ),
    ]
    flagged = eth_carried_informational(rows)
    assert [row.candidate_id for row in flagged] == ["volbrk_lo_20x1_5"]


def test_positive_holdout_losing_btc_wf_is_flagged() -> None:
    rows = [
        _row(
            "volbrk_lo_20x1_5",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.15,
            kraken_btc_ho=0.14,
            kraken_eth_ho=0.16,
            kraken_btc_wf=-0.04,
        ),
        _row(
            "volbrk_lo_20x2",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.10,
            kraken_btc_ho=0.08,
            kraken_eth_ho=0.12,
            kraken_btc_wf=0.02,
        ),
    ]
    flagged = btc_wf_fail_informational(rows)
    assert [row.candidate_id for row in flagged] == ["volbrk_lo_20x1_5"]


def test_empty_binance_is_success_and_cannot_promote() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=start),
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
    rendered = render_volume_breakout_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "paper-executable on Kraken spot" in rendered
    assert "volume-confirmed" in rendered.lower()
    assert "not** a Donchian" in rendered.lower() or "not a Donchian" in rendered
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
        },
        {
            "BTCUSDT@1d": downtrend(720, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(720, symbol="ETHUSDT", start=older),
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
    rendered = render_volume_breakout_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert "Do not re-run dead EMA dual-prints" in rendered
    assert "#122" in rendered
    assert "equal-weight" in rendered.lower()
    assert "not a donchian" in rendered.lower()


def test_signals_alias_binance_symbols() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    mapping = volume_breakout_signals(
        {
            "BTCUSDT@1d": uptrend(80, symbol="BTCUSDT", start=start),
            "ETHUSDT@1d": uptrend(80, symbol="ETHUSDT", start=start),
        },
        kind="surge",
        channel_n=0,
        vol_lookback=20,
        vol_mult=2.0,
        long_short=False,
    )
    assert "BTC/USD" in mapping
    assert "BTCUSDT" in mapping


def test_committed_live_report_is_empty_success() -> None:
    text = Path("docs/artifacts/strategy-search/volume-breakout.md").read_text()
    assert "Dual-print passers: 0" in text
    assert "`keep_flag_false=true`" in text
    assert "Do not add a new promote flag" in text
    assert "PAPER_PROMOTE_*" in text
    assert "volbrk_lo_20x1_5" in text
    assert "volbrk_lo_20x2" in text
    assert "volsurge_lo_20x2_5" in text
    assert "volbrk_lo_20x1_5" in text
    assert settings().paper_promote_ema_9_21 is False
    assert not hasattr(settings(), "paper_promote_volbrk_lo_20x1_5")


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "volume-breakout.md"

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
    out_json = tmp_path / "ops" / "volume_breakout.json"
    out_md = tmp_path / "ops" / "volume_breakout.md"
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
    assert "Volume-confirmed breakout dual-print" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False
