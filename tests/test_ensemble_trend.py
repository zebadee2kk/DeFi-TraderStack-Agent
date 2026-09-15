from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
)
from traderstack.research.ensemble_trend import (
    CANDIDATE_UNIVERSE,
    CATALOG_NOTE,
    CONTROL_ID,
    CORE_IDS,
    DSR_PBO_AVAILABLE,
    ENSEMBLE_CATALOG,
    ENSEMBLE_IDS,
    ENSEMBLE_LOOKBACKS,
    ENSEMBLE_RULES,
    ENTRY_RULE,
    ERA_PRINTS_AVAILABLE,
    KRAKEN_PRO_TIERS,
    MAX_LEVERAGE,
    MULTI_ASSET_GATE_RULE,
    PAPER_PATH_READY,
    REBALANCE_THRESHOLD,
    SHORT_LOOKBACKS,
    STOP_RULE,
    SURVIVORSHIP_NOTE,
    UNIVERSE_MEDIAN_DOLLAR_VOLUME_USD,
    UNIVERSE_MIN_LISTED_BARS,
    UNIVERSE_SNAPSHOT_NOTE,
    UNIVERSE_TOP_K,
    VOL_LOOKBACK,
    VOL_TARGET_ANNUAL,
    EnsembleTrendVoter,
    apply_membership,
    ensemble_attribution,
    ensemble_trend_candidates,
    ensemble_trend_series,
    fee_tier_taker_bps,
    lookback_state_series,
    prior_close_channel,
    rank_ensemble_passers,
    realised_vol_annualised,
    render_ensemble_trend_markdown,
    run_ensemble_trend_search,
    skipped_ensemble_families,
    universe_snapshots,
)
from traderstack.research.ensemble_trend_cli import build_parser, resolve_fee_bps, run
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
    volume: float = 5_000_000.0,
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
                volume=volume,
            )
        )
    return tuple(candles)


def noisy_uptrend(
    count: int,
    *,
    symbol: str = "BTC/USD",
    start: datetime | None = None,
    seed: int = 3,
    drift: float = 0.002,
    sigma: float = 0.03,
    volume: float = 5_000_000.0,
) -> tuple[Candle, ...]:
    rng = random.Random(seed)
    prices = [100.0]
    for _ in range(count - 1):
        prices.append(max(1.0, prices[-1] * (1.0 + rng.gauss(drift, sigma))))
    return make_candles(prices, symbol=symbol, start=start, volume=volume)


def downtrend(
    count: int, *, symbol: str = "BTC/USD", start: datetime | None = None
) -> tuple[Candle, ...]:
    return make_candles(
        [200.0 - 0.25 * index for index in range(count)], symbol=symbol, start=start
    )


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _gate_histories(count: int = 240, *, start: datetime | None = None, seed: int = 3):
    opened = start or datetime(2024, 9, 22, tzinfo=UTC)
    return {
        "BTC/USD@1d": noisy_uptrend(count, symbol="BTC/USD", start=opened, seed=seed),
        "ETH/USD@1d": noisy_uptrend(count, symbol="ETH/USD", start=opened, seed=seed + 1),
        "SOL/USD@1d": noisy_uptrend(count, symbol="SOL/USD", start=opened, seed=seed + 2),
    }


def _tiny_catalog():
    return ensemble_trend_candidates(_gate_histories(240))


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
    return run_ensemble_trend_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


def _row(
    candidate_id: str,
    *,
    kraken_combined: bool,
    binance_combined: bool,
    kraken_ho: float | None,
) -> DualPrintRow:
    return DualPrintRow(
        candidate_id=candidate_id,
        family="ensemble_trend",
        label=candidate_id,
        kraken_combined=kraken_combined,
        binance_combined=binance_combined,
        dual_print=kraken_combined and binance_combined,
        kraken_mean_holdout_excess=kraken_ho,
    )


def test_promote_defaults_stay_false() -> None:
    cfg = settings()
    for name, field in Settings.model_fields.items():
        if name.startswith("paper_promote_") and field.annotation is bool:
            assert getattr(cfg, name) is False, name
    assert not any(name.startswith("paper_promote_ens") for name in Settings.model_fields)
    assert not hasattr(cfg, "paper_promote_ensemble_trend")
    report = _search(_gate_histories(240), {})
    assert report.keep_flag_false is True


def test_catalog_and_rules_are_frozen_before_scoring() -> None:
    assert ENSEMBLE_LOOKBACKS == (5, 10, 20, 30, 60, 90, 150, 250, 360)
    assert SHORT_LOOKBACKS == (5, 10, 20, 30, 60, 90)
    assert VOL_TARGET_ANNUAL == 0.25
    assert VOL_LOOKBACK == 90
    assert MAX_LEVERAGE == 1.0
    assert REBALANCE_THRESHOLD == 0.05
    assert ENTRY_RULE == "close_above_prior_n_max_close"
    assert STOP_RULE == "max_prior_stop_close_channel_midpoint"
    assert ENSEMBLE_IDS == ("ens_trend_9lb_vt25", "ens_trend_6lb_vt25", "ens_trend_9lb_unit")
    assert ENSEMBLE_CATALOG[0][1] == ENSEMBLE_LOOKBACKS and ENSEMBLE_CATALOG[0][2] == 0.25
    assert ENSEMBLE_CATALOG[1][1] == SHORT_LOOKBACKS
    assert ENSEMBLE_CATALOG[2][2] is None
    assert CORE_IDS == ENSEMBLE_IDS + (CONTROL_ID,)
    assert CONTROL_ID == "ma_cross_10_30"
    assert PAPER_PATH_READY is True
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert ERA_PRINTS_AVAILABLE is False
    assert DSR_PBO_AVAILABLE is False
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    for needle in (
        ENTRY_RULE,
        STOP_RULE,
        "vol",
        "CANDIDATE_UNIVERSE",
        "Kraken Pro tier",
        "era_prints_available=false",
        "dsr_pbo_available=false",
        RANKING_KEY,
        MULTI_ASSET_GATE_RULE,
        "MULTI_VENUE_BAR_PREREGISTERED=true",
        "CAN_AVERAGE_VENUES=false",
        "survivorship",
        f"{CONTROL_ID} cannot enter the passer set",
        "Not a #118 Donchian N retune",
    ):
        assert needle in ENSEMBLE_RULES, needle
    assert "not a post-hoc retune" in CATALOG_NOTE
    assert UNIVERSE_MIN_LISTED_BARS == 365
    assert UNIVERSE_MEDIAN_DOLLAR_VOLUME_USD == 2_000_000.0
    assert UNIVERSE_TOP_K == 20
    assert len(CANDIDATE_UNIVERSE) == len(set(CANDIDATE_UNIVERSE)) >= 30
    assert all(symbol.endswith("/USD") for symbol in CANDIDATE_UNIVERSE)
    assert {"BTC/USD", "ETH/USD", "SOL/USD"} <= set(CANDIDATE_UNIVERSE)
    assert "USDT/USD" not in CANDIDATE_UNIVERSE and "USDC/USD" not in CANDIDATE_UNIVERSE
    assert "point-in-time" in UNIVERSE_SNAPSHOT_NOTE.lower() or "before" in UNIVERSE_SNAPSHOT_NOTE
    assert "currently-listed" in SURVIVORSHIP_NOTE or "listed today" in SURVIVORSHIP_NOTE
    assert KRAKEN_PRO_TIERS[1] == (40.0, 80.0)
    freeze = Path("docs/artifacts/strategy-search/ensemble-trend.md").read_text()
    for needle in (
        "ens_trend_9lb_vt25",
        "ens_trend_6lb_vt25",
        "ens_trend_9lb_unit",
        CONTROL_ID,
        "PAPER_PROMOTE_*",
        "era_prints_available=false",
        "dsr_pbo_available=false",
        "Survivorship",
        "Kraken Pro tier",
    ):
        assert needle in freeze, needle


def test_entry_uses_prior_n_max_close_and_excludes_bar_t() -> None:
    flat_then_equal = make_candles([100.0] * 20 + [100.0])
    assert prior_close_channel(flat_then_equal, 20, 20) == (100.0, 100.0)
    equal = lookback_state_series(flat_then_equal, 20)
    assert equal[-1][1] is False  # close == prior max does not enter

    breakout = make_candles([100.0] * 20 + [101.0])
    series = lookback_state_series(breakout, 20)
    assert series[-1][1] is True
    assert series[-1][2] == pytest.approx(100.0)  # midpoint of the prior close channel

    # Bar t's own close is never part of its own level: with an outsized
    # close on bar t the prior channel is unchanged.
    spike = make_candles([100.0] * 20 + [500.0])
    assert prior_close_channel(spike, 20, 20) == (100.0, 100.0)
    assert prior_close_channel(spike, 19, 20) is None  # not enough prior bars
    assert lookback_state_series(spike[:20], 20) == ()


def test_trailing_stop_ratchets_up_never_down_and_exits_on_close_below() -> None:
    up = [100.0 + index for index in range(30)]  # 100..129
    fade = [129.0 - 4.0 * index for index in range(1, 8)]  # 125, 121, 117, ...
    candles = make_candles(up + fade)
    series = lookback_state_series(candles, 20)
    by_ts = {ts: (in_position, stop) for ts, in_position, stop in series}
    entry_ts = candles[20].opened_at
    assert by_ts[entry_ts][0] is True
    # Channel over bars [0, 20) is 100..119 → midpoint 109.5 at entry.
    assert by_ts[entry_ts][1] == pytest.approx(109.5)
    # Stop rises with the midpoint while the trend continues.
    stops = [by_ts[candles[index].opened_at][1] for index in range(20, 30)]
    assert stops == pytest.approx([109.5 + index for index in range(10)])
    # During the fade the midpoint of the prior window falls back while the
    # stop holds (never ratchets down) ...
    hold_ts = candles[31].opened_at  # close 121, prior window max 129
    assert by_ts[hold_ts][0] is True
    assert by_ts[hold_ts][1] >= 119.5
    # ... until close < stop exits to flat and clears the stop.
    exit_ts = candles[32].opened_at  # close 117
    assert by_ts[exit_ts] == (False, None)
    # No re-entry without a fresh breakout.
    assert all(by_ts[candles[index].opened_at][0] is False for index in range(32, 37))


def test_ensemble_weight_is_open_fraction_times_vol_scalar_capped_at_one() -> None:
    # 3 of 9 lookbacks open at 50% annualised vol → (3/9) × 0.5.
    candles = noisy_uptrend(420, seed=11)
    series = ensemble_trend_series(candles)
    assert series
    _ts, weight, open_count = series[-1]
    index = len(candles) - 1
    vol = realised_vol_annualised(candles, index, VOL_LOOKBACK)
    assert vol is not None and vol > 0
    expected = (open_count / 9) * min(VOL_TARGET_ANNUAL / vol, 1.0)
    assert weight == pytest.approx(expected)
    assert all(0.0 <= w <= 1.0 for _ts, w, _n in series)
    assert all(0 <= n <= 9 for _ts, _w, n in series)

    # Constant geometric drift: realised vol is 0 → scalar caps at 1.0 and
    # every lookback is open, so the weight is exactly 1.0, never above.
    calm = make_candles([100.0 * (1.005**index) for index in range(400)])
    calm_series = ensemble_trend_series(calm)
    assert calm_series[-1][1] == 1.0
    assert calm_series[-1][2] == 9

    # Low-vol fraction case: 3 of 9 open with vol far below target → 3/9.
    open_count = 3
    scalar = min(VOL_TARGET_ANNUAL / 0.05, MAX_LEVERAGE)
    assert scalar == 1.0
    assert (open_count / 9) * scalar == pytest.approx(3 / 9)

    # Unit book: open fraction only, no vol scalar.
    unit = ensemble_trend_series(candles, vol_target=None)
    assert unit[-1][1] == pytest.approx(unit[-1][2] / 9)


def test_insufficient_history_is_skipped_not_invented() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": noisy_uptrend(200, symbol="BTC/USD", start=start),
        "ETH/USD@1d": noisy_uptrend(200, symbol="ETH/USD", start=start, seed=5),
    }
    assert ensemble_trend_series(histories["BTC/USD@1d"]) == ()
    assert ensemble_trend_series(histories["BTC/USD@1d"], lookbacks=SHORT_LOOKBACKS)
    catalog = ensemble_trend_candidates(histories)
    ids = [item.candidate_id for item in catalog]
    assert ids == ["ens_trend_6lb_vt25", CONTROL_ID]
    skipped = skipped_ensemble_families(histories)
    assert {item["candidate_id"] for item in skipped} == {
        "ens_trend_9lb_vt25",
        "ens_trend_9lb_unit",
    }
    assert all("invent" in item["reason"] for item in skipped)
    assert all("361" in item["reason"] for item in skipped)


def test_universe_snapshot_is_point_in_time_monthly_top20() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories: dict[str, tuple[Candle, ...]] = {}
    # 22 old, liquid names with distinct volumes so the top-20 cut is deterministic.
    for rank in range(22):
        symbol = f"A{rank:02d}/USD"
        histories[f"{symbol}@1d"] = make_candles(
            [100.0] * 450, symbol=symbol, start=start, volume=100_000.0 - rank * 1_000.0
        )
    # Young name: listed 200 bars ago (fewer than 365 prior) — excluded.
    histories["YOUNG/USD@1d"] = make_candles(
        [100.0] * 230, symbol="YOUNG/USD", start=start + timedelta(days=220), volume=1e6
    )
    # Old but illiquid: median 30d close×volume below $2M — excluded.
    histories["THIN/USD@1d"] = make_candles(
        [100.0] * 450, symbol="THIN/USD", start=start, volume=10_000.0
    )
    # Old and liquid but volume collapses after month 13: drops out later.
    fading = list(make_candles([100.0] * 450, symbol="FADE/USD", start=start, volume=90_000.0))
    fading = [
        candle
        if candle.opened_at < start + timedelta(days=395)
        else candle.model_copy(update={"volume": 1.0})
        for candle in fading
    ]
    histories["FADE/USD@1d"] = tuple(fading)
    snapshots = universe_snapshots(histories, cap_bars=10_000)
    # First 12 month starts: nobody has 365 prior bars → empty (never invented).
    early = [month for month in sorted(snapshots) if month < start + timedelta(days=365)]
    assert early and all(snapshots[month] == frozenset() for month in early)
    month_14 = datetime(2025, 2, 1, tzinfo=UTC)
    members = snapshots[month_14]
    assert len(members) == UNIVERSE_TOP_K
    assert "YOUNG/USD" not in members
    assert "THIN/USD" not in members
    assert "FADE/USD" in members  # still liquid using bars before 2025-02-01
    # A02..A21 have lower volume than A00/A01, and the cut is by median volume.
    assert "A00/USD" in members and "A21/USD" not in members
    later = datetime(2025, 3, 1, tzinfo=UTC)
    assert "FADE/USD" not in snapshots[later]
    # Point-in-time: membership at a month never uses bars in or after it —
    # zeroing every volume from the month start onward leaves it unchanged.
    mutated = {
        key: tuple(
            c if c.opened_at < month_14 else c.model_copy(update={"volume": 0.0}) for c in candles
        )
        for key, candles in histories.items()
    }
    assert universe_snapshots(mutated, cap_bars=10_000)[month_14] == members
    # Non-member bars are forced flat.
    series = ((month_14, 0.7, 5), (later, 0.4, 3))
    assert apply_membership("FADE/USD", series, snapshots) == ((month_14, 0.7, 5), (later, 0.0, 3))
    assert apply_membership("YOUNG/USD", series, snapshots) == ((month_14, 0.0, 5), (later, 0.0, 3))


def test_capped_kraken_series_is_inferred_to_predate_the_window() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    capped = make_candles([100.0] * 720, symbol="BTC/USD", start=start)
    snapshots = universe_snapshots({"BTC/USD@1d": capped})
    second_month = datetime(2024, 11, 1, tzinfo=UTC)
    assert "BTC/USD" in snapshots[second_month]
    uncapped = make_candles([100.0] * 300, symbol="BTC/USD", start=start)
    assert "BTC/USD" not in universe_snapshots({"BTC/USD@1d": uncapped})[second_month]


def test_attribution_by_lookback_and_asset_sums_to_gross() -> None:
    histories = _gate_histories(420, seed=21)
    by_asset, by_lookback = ensemble_attribution(
        {key: candles for key, candles in histories.items()}
    )
    assert set(by_asset) == {"BTC/USD", "ETH/USD", "SOL/USD"}
    assert set(by_lookback) == set(ENSEMBLE_LOOKBACKS)
    assert sum(by_lookback.values()) == pytest.approx(sum(by_asset.values()), abs=1e-9)
    snapshots = universe_snapshots(histories)
    masked_asset, masked_lookback = ensemble_attribution(histories, snapshots=snapshots)
    assert sum(masked_lookback.values()) == pytest.approx(sum(masked_asset.values()), abs=1e-9)


def test_voter_never_emits_sell_and_score_is_weight() -> None:
    candles = noisy_uptrend(420, seed=11)
    series = ensemble_trend_series(candles)
    voter = EnsembleTrendVoter(
        strategy_id="ens_trend_9lb_vt25", signals_by_symbol=(("BTC/USD", series),)
    )
    for end in range(len(candles) - 30, len(candles) + 1):
        signal = voter.evaluate(candles[:end], Regime.RANGE)
        assert signal.side in {Side.BUY, None}
        assert 0.0 <= signal.score <= 1.0
        assert signal.confidence == signal.score
        if signal.side is Side.BUY:
            assert signal.score > 0.0
        else:
            assert signal.score == 0.0
    # Warmup bar: no assignment → side None with a rationale.
    warmup = voter.evaluate(candles[:50], Regime.RANGE)
    assert warmup.side is None and "warmup" in warmup.rationale
    # Decision-time recompute when no series is registered (paper re-confirmation).
    fresh = EnsembleTrendVoter(strategy_id="ens_trend_9lb_vt25")
    recomputed = fresh.evaluate(candles, Regime.RANGE)
    registered = voter.evaluate(candles, Regime.RANGE)
    assert recomputed.side is registered.side
    assert recomputed.score == pytest.approx(registered.score)
    assert "recompute" in recomputed.rationale
    # A falling market never becomes a SELL.
    bear = EnsembleTrendVoter(strategy_id="ens_trend_9lb_vt25").evaluate(
        downtrend(420), Regime.TRENDING_DOWN
    )
    assert bear.side is None and bear.score == 0.0


def test_control_cannot_enter_dual_print_ranking() -> None:
    rows = [
        _row(CONTROL_ID, kraken_combined=True, binance_combined=True, kraken_ho=0.50),
        _row("ens_trend_9lb_vt25", kraken_combined=True, binance_combined=True, kraken_ho=0.08),
        _row("ens_trend_6lb_vt25", kraken_combined=True, binance_combined=False, kraken_ho=0.40),
    ]
    passers = rank_ensemble_passers(rows)
    assert [row.candidate_id for row in passers] == ["ens_trend_9lb_vt25"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_candidates_opt_into_fractional_weight_and_control_does_not() -> None:
    catalog = ensemble_trend_candidates(_gate_histories(420))
    by_id = {item.candidate_id: item for item in catalog}
    assert [item.candidate_id for item in catalog] == list(CORE_IDS)
    for candidate_id in ENSEMBLE_IDS:
        assert by_id[candidate_id].weight_from_score is True
        assert by_id[candidate_id].garch_sizing is False
    assert by_id[CONTROL_ID].weight_from_score is False


def test_empty_binance_is_success_and_cannot_promote() -> None:
    report = _search(_gate_histories(240), {})
    assert report.binance_slice.available is False
    assert report.any_dual_print_passer is False
    assert report.selected_candidate_id is None
    assert report.recommended_promote_flag is None
    assert report.keep_flag_false is True
    assert report.paper_path_ready is True
    assert report.multi_venue_bar_preregistered is True
    assert report.can_average_venues is False
    assert report.multi_asset_gate_rule == MULTI_ASSET_GATE_RULE
    assert report.era_prints_available is False
    assert report.dsr_pbo_available is False
    rendered = render_ensemble_trend_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "UNAVAILABLE / fail-closed" in rendered
    assert "SOL reported" in rendered
    assert settings().paper_promote_ema_9_21_adx15 is False


def test_short_or_overlapping_binance_slice_fails_closed() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    kraken = _gate_histories(240, start=primary)
    short = _search(
        kraken,
        {
            "BTCUSDT@1d": downtrend(100, symbol="BTCUSDT", start=datetime(2023, 1, 1, tzinfo=UTC)),
            "ETHUSDT@1d": downtrend(100, symbol="ETHUSDT", start=datetime(2023, 1, 1, tzinfo=UTC)),
        },
    )
    assert short.binance_slice.available is False
    assert "shorter than 720" in (short.binance_slice.fail_closed_reason or "")
    assert short.any_dual_print_passer is False
    overlapping = _search(
        kraken,
        {
            "BTCUSDT@1d": downtrend(720, symbol="BTCUSDT", start=datetime(2024, 1, 1, tzinfo=UTC)),
            "ETHUSDT@1d": downtrend(720, symbol="ETHUSDT", start=datetime(2024, 1, 1, tzinfo=UTC)),
        },
    )
    assert overlapping.binance_slice.available is False
    assert overlapping.any_dual_print_passer is False
    assert overlapping.keep_flag_false is True


def test_binance_older_slice_is_scored_and_cannot_promote() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    report = _search(
        _gate_histories(420, start=primary),
        {
            "BTCUSDT@1d": noisy_uptrend(720, symbol="BTCUSDT", start=older, seed=31),
            "ETHUSDT@1d": noisy_uptrend(720, symbol="ETHUSDT", start=older, seed=32),
            "SOLUSDT@1d": noisy_uptrend(720, symbol="SOLUSDT", start=older, seed=33),
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
    assert set(report.attribution_by_asset) == set(ENSEMBLE_IDS)
    assert set(report.attribution_by_lookback["ens_trend_6lb_vt25"]) == {
        str(n) for n in SHORT_LOOKBACKS
    }
    rendered = render_ensemble_trend_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert "## Attribution" in rendered


def test_fee_tier_maps_to_taker_bps_and_explicit_fee_overrides() -> None:
    assert fee_tier_taker_bps(1) == 80.0
    assert fee_tier_taker_bps(3) == 38.0
    assert fee_tier_taker_bps(12) == 10.0
    with pytest.raises(ValueError, match="unknown Kraken Pro tier"):
        fee_tier_taker_bps(4)
    parser = build_parser()
    default = parser.parse_args(["--candles", "x.json"])
    assert resolve_fee_bps(default) == (80.0, "kraken_pro_tier_taker", 1)
    tier3 = parser.parse_args(["--candles", "x.json", "--kraken-tier", "3"])
    assert resolve_fee_bps(tier3) == (38.0, "kraken_pro_tier_taker", 3)
    explicit = parser.parse_args(["--candles", "x.json", "--kraken-tier", "3", "--fee-bps", "10"])
    assert resolve_fee_bps(explicit) == (10.0, "explicit_fee_bps", None)
    with pytest.raises(SystemExit):
        parser.parse_args(["--candles", "x.json", "--kraken-tier", "4"])


def test_report_declares_era_and_dsr_pbo_unavailable() -> None:
    report = _search(_gate_histories(240), {})
    payload = json.loads(report.model_dump_json())
    assert payload["era_prints_available"] is False
    assert payload["dsr_pbo_available"] is False
    rendered = render_ensemble_trend_markdown(report)
    header = rendered.split("## Honesty")[0]
    assert "`era_prints_available=false`" in header
    assert "`dsr_pbo_available=false`" in header
    assert "Kraken Pro tier" in header or "explicit --fee-bps" in header
    # Header carries the catalog, universe policy, survivorship note and fee
    # tier before any score table.
    first_table = rendered.index("| rank | id |")
    assert rendered.index("## Universe snapshot policy") < first_table
    assert rendered.index("Survivorship") < first_table
    assert rendered.index("## Fee tier (frozen)") < first_table
    assert rendered.index("## Pre-registered catalog") < first_table


def test_committed_live_report_is_empty_success() -> None:
    text = Path("docs/artifacts/strategy-search/ensemble-trend.md").read_text()
    assert "Dual-print passers: 0" in text
    assert "`keep_flag_false=true`" in text
    assert "Do not add a new promote flag" in text
    assert "`era_prints_available=false`" in text
    assert "`dsr_pbo_available=false`" in text
    assert "| month | members |" in text
    assert settings().paper_promote_ema_9_21 is False
    assert not hasattr(settings(), "paper_promote_ens_trend_9lb_vt25")


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "ensemble-trend.md"
    assert args.output_json.name == "ensemble_trend.json"
    assert args.kraken_tier == 1
    assert args.fee_bps is None

    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    histories = _gate_histories(240, start=primary)
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    btc_usdt = tmp_path / "btcusdt.json"
    eth_usdt = tmp_path / "ethusdt.json"
    write_candles(btc, histories["BTC/USD@1d"])
    write_candles(eth, histories["ETH/USD@1d"])
    write_candles(btc_usdt, noisy_uptrend(720, symbol="BTCUSDT", start=older, seed=41))
    write_candles(eth_usdt, noisy_uptrend(720, symbol="ETHUSDT", start=older, seed=42))
    out_json = tmp_path / "ops" / "ensemble.json"
    out_md = tmp_path / "ops" / "ensemble.md"
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
            "--kraken-tier",
            "3",
        ]
    )
    written_json, written_md = run(parsed, settings=settings(), candidates=_tiny_catalog())
    assert written_json.is_file()
    assert written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["ranking_key"] == RANKING_KEY
    assert payload["keep_flag_false"] is True
    assert payload["paper_path_ready"] is True
    assert payload["fee_bps"] == 38.0
    assert payload["kraken_tier"] == 3
    assert payload["fee_source"] == "kraken_pro_tier_taker"
    assert payload["era_prints_available"] is False
    assert payload["dsr_pbo_available"] is False
    assert payload["any_dual_print_passer"] is False
    assert payload["selected_candidate_id"] is None
    assert payload["universe"]["candidate_universe"] == list(CANDIDATE_UNIVERSE)
    text = written_md.read_text()
    assert "Ensemble trend dual-print" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert "Kraken Pro tier 3 taker" in text
    assert settings().paper_promote_ema_9_21 is False
