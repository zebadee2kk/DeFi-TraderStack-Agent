from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.calendar_seasonality import (
    CALENDAR_CATALOG_NOTE,
    CALENDAR_IDS,
    CALENDAR_RULES,
    CONTROL_ID,
    CONTROL_IDS,
    CORE_IDS,
    DECISION_RULE,
    DOW_IDS,
    DOW_SETS,
    FILL_RULE,
    MOY_IDS,
    MOY_SETS,
    MULTI_ASSET_GATE_RULE,
    PAPER_PATH_READY,
    PRICE_PATH_OMITTED_REASON,
    TIMEZONE_RULE,
    TOM_FIRST_M,
    TOM_IDS,
    TOM_LAST_N,
    TOM_RULE,
    UTC_WEEKDAY_FRI,
    UTC_WEEKDAY_MON,
    UTC_WEEKDAYS,
    UTC_WEEKEND,
    btc_wf_fail_informational,
    calendar_candidates,
    calendar_position,
    calendar_position_series,
    calendar_signals,
    eth_carried_informational,
    is_turn_of_month,
    rank_calendar_passers,
    render_calendar_seasonality_markdown,
    run_calendar_seasonality_search,
    skipped_calendar_families,
    utc_calendar_date,
)
from traderstack.research.calendar_seasonality_cli import build_parser, run
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


def uptrend(
    count: int, *, symbol: str = "BTC/USD", start: datetime | None = None
) -> tuple[Candle, ...]:
    return make_candles(
        [100.0 + 0.25 * index for index in range(count)], symbol=symbol, start=start
    )


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _histories(count: int = 300, *, start: datetime | None = None) -> dict[str, tuple[Candle, ...]]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    return {
        "BTC/USD@1d": uptrend(count, symbol="BTC/USD", start=opened),
        "ETH/USD@1d": uptrend(count, symbol="ETH/USD", start=opened),
        "SOL/USD@1d": uptrend(count, symbol="SOL/USD", start=opened),
    }


def _tiny_catalog():
    return calendar_candidates(_histories(80), include_control=True)


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
    return run_calendar_seasonality_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


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
        family="cal_dow",
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
    assert not hasattr(cfg, "paper_promote_cal_dow_lo_mon")
    assert not hasattr(cfg, "paper_promote_calendar")


def test_catalog_and_bar_are_frozen_before_scoring() -> None:
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert PAPER_PATH_READY is True
    assert TIMEZONE_RULE == "utc"
    assert DECISION_RULE == "utc_calendar_date_of_bar_t"
    assert FILL_RULE == "next_bar_open"
    assert TOM_RULE == "utc_calendar_last_n_first_m_days_of_month"
    assert TOM_LAST_N == 3
    assert TOM_FIRST_M == 3
    assert DOW_SETS["cal_dow_lo_mon"] == frozenset({UTC_WEEKDAY_MON})
    assert DOW_SETS["cal_dow_lo_fri"] == frozenset({UTC_WEEKDAY_FRI})
    assert DOW_SETS["cal_dow_lo_mon_fri"] == frozenset({UTC_WEEKDAY_MON, UTC_WEEKDAY_FRI})
    assert DOW_SETS["cal_dow_skip_weekend"] == UTC_WEEKDAYS
    assert UTC_WEEKEND.isdisjoint(UTC_WEEKDAYS)
    assert MOY_SETS["cal_moy_lo_q4"] == frozenset({10, 11, 12})
    assert MOY_SETS["cal_moy_lo_jan"] == frozenset({1})
    assert MOY_SETS["cal_moy_lo_nov_dec"] == frozenset({11, 12})
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in CALENDAR_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in CALENDAR_RULES
    assert "CAN_AVERAGE_VENUES=false" in CALENDAR_RULES
    assert MULTI_ASSET_GATE_RULE == "btc_eth_signs_as_96_abc_sol_reported_not_required"
    assert MULTI_ASSET_GATE_RULE in CALENDAR_RULES
    assert SECOND_PRINT_BARS == 720
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"
    catalog = calendar_candidates(_histories(80))
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert ids[:3] == ["cal_dow_lo_mon", "cal_dow_lo_fri", "cal_dow_lo_mon_fri"]
    assert ids[3] == "cal_dow_skip_weekend"
    assert ids[4:7] == ["cal_moy_lo_q4", "cal_moy_lo_jan", "cal_moy_lo_nov_dec"]
    assert ids[7] == "cal_tom_lo_3_3"
    assert ids[-1] == CONTROL_ID
    assert set(CALENDAR_IDS) | CONTROL_IDS == set(CORE_IDS)
    assert set(DOW_IDS) | set(MOY_IDS) | set(TOM_IDS) == set(CALENDAR_IDS)
    assert "ema_9_21" not in ids
    assert "rv_fade_1_0" not in ids
    assert "xs_mom_lo_21" not in ids
    assert "donchian_lo_20" not in ids
    assert "tsmom_lo_21" not in ids
    assert "bb_fade_20x2" not in ids
    assert PRICE_PATH_OMITTED_REASON in CALENDAR_RULES
    assert "equal-weight portfolio metrics are not used" in CALENDAR_RULES.lower()
    assert "not Bollinger fade" in CALENDAR_RULES
    freeze = Path("docs/artifacts/strategy-search/calendar-seasonality.md").read_text()
    assert "cal_dow_lo_mon" in freeze
    assert "cal_dow_lo_fri" in freeze
    assert "cal_dow_lo_mon_fri" in freeze
    assert "cal_dow_skip_weekend" in freeze
    assert "cal_moy_lo_q4" in freeze
    assert "cal_moy_lo_jan" in freeze
    assert "cal_moy_lo_nov_dec" in freeze
    assert "cal_tom_lo_3_3" in freeze
    assert "ma_cross_10_30" in freeze
    assert "PAPER_PROMOTE_*" in freeze
    assert "utc_calendar_date_of_bar_t" in freeze
    assert "Not yet run" in freeze or "Dual-print passers" in freeze


def test_missing_sol_does_not_skip_btc_eth_names() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": downtrend(80, symbol="BTC/USD", start=start),
        "ETH/USD@1d": downtrend(80, symbol="ETH/USD", start=start),
    }
    catalog = calendar_candidates(histories)
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert skipped_calendar_families(histories) == []


def test_empty_history_skips_not_invented() -> None:
    catalog = calendar_candidates({})
    assert [item.candidate_id for item in catalog] == [CONTROL_ID]
    skipped = skipped_calendar_families({})
    assert {item["candidate_id"] for item in skipped} == set(CALENDAR_IDS)
    assert all("invent" in item["reason"] for item in skipped)


def test_utc_date_uses_timezone_not_local() -> None:
    monday = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    friday_late = datetime(2024, 1, 5, 23, 0, tzinfo=UTC)
    saturday = datetime(2024, 1, 6, 0, 0, tzinfo=UTC)
    naive_monday = datetime(2024, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    assert utc_calendar_date(monday).weekday() == UTC_WEEKDAY_MON
    assert utc_calendar_date(friday_late).weekday() == UTC_WEEKDAY_FRI
    assert utc_calendar_date(saturday).weekday() == 5
    assert utc_calendar_date(naive_monday).weekday() == UTC_WEEKDAY_MON
    assert calendar_position(monday, "cal_dow_lo_mon", "dow_lo") == 1.0
    assert calendar_position(friday_late, "cal_dow_lo_mon", "dow_lo") == 0.0
    assert calendar_position(friday_late, "cal_dow_lo_fri", "dow_lo") == 1.0
    assert calendar_position(friday_late, "cal_dow_lo_mon_fri", "dow_lo") == 1.0
    assert calendar_position(saturday, "cal_dow_skip_weekend", "dow_skip_weekend") == 0.0
    assert calendar_position(monday, "cal_dow_skip_weekend", "dow_skip_weekend") == 1.0


def test_month_and_turn_of_month_use_civil_calendar() -> None:
    jan = datetime(2024, 1, 15, tzinfo=UTC)
    oct_day = datetime(2024, 10, 2, tzinfo=UTC)
    nov = datetime(2024, 11, 10, tzinfo=UTC)
    assert calendar_position(jan, "cal_moy_lo_jan", "moy_lo") == 1.0
    assert calendar_position(oct_day, "cal_moy_lo_q4", "moy_lo") == 1.0
    assert calendar_position(jan, "cal_moy_lo_q4", "moy_lo") == 0.0
    assert calendar_position(nov, "cal_moy_lo_nov_dec", "moy_lo") == 1.0
    assert calendar_position(oct_day, "cal_moy_lo_nov_dec", "moy_lo") == 0.0
    assert is_turn_of_month(datetime(2024, 1, 1, tzinfo=UTC).date()) is True
    assert is_turn_of_month(datetime(2024, 1, 3, tzinfo=UTC).date()) is True
    assert is_turn_of_month(datetime(2024, 1, 4, tzinfo=UTC).date()) is False
    assert is_turn_of_month(datetime(2024, 1, 29, tzinfo=UTC).date()) is True
    assert is_turn_of_month(datetime(2024, 1, 31, tzinfo=UTC).date()) is True
    assert is_turn_of_month(datetime(2024, 1, 15, tzinfo=UTC).date()) is False
    # Leap February 2024 has 29 days: last 3 are 27/28/29, not 26.
    assert is_turn_of_month(datetime(2024, 2, 26, tzinfo=UTC).date()) is False
    assert is_turn_of_month(datetime(2024, 2, 27, tzinfo=UTC).date()) is True
    assert is_turn_of_month(datetime(2024, 2, 29, tzinfo=UTC).date()) is True
    assert calendar_position(datetime(2024, 1, 31, tzinfo=UTC), "cal_tom_lo_3_3", "tom_lo") == 1.0
    assert calendar_position(datetime(2024, 1, 15, tzinfo=UTC), "cal_tom_lo_3_3", "tom_lo") == 0.0


def test_positions_ignore_price_path() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)  # Monday
    rising = make_candles([100.0 + index for index in range(10)], symbol="BTC/USD", start=start)
    falling = make_candles([200.0 - index for index in range(10)], symbol="ETH/USD", start=start)
    mapping = calendar_signals(
        {"BTC/USD@1d": rising, "ETH/USD@1d": falling},
        candidate_id="cal_dow_lo_mon",
        kind="dow_lo",
    )
    btc = dict(mapping["BTC/USD"])
    eth = dict(mapping["ETH/USD"])
    assert [btc[c.opened_at] for c in rising] == [eth[c.opened_at] for c in falling]
    assert btc[rising[0].opened_at] == 1.0
    assert btc[rising[1].opened_at] == 0.0
    series = dict(
        calendar_position_series(
            rising, candidate_id="cal_dow_skip_weekend", kind="dow_skip_weekend"
        )
    )
    assert series[rising[0].opened_at] == 1.0  # Mon
    assert series[rising[4].opened_at] == 1.0  # Fri
    assert series[rising[5].opened_at] == 0.0  # Sat
    assert series[rising[6].opened_at] == 0.0  # Sun


def test_voter_maps_long_and_flat() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    monday = make_candles([100.0], symbol="BTC/USD", start=start)
    tuesday = make_candles([100.0], symbol="BTC/USD", start=start + timedelta(days=1))
    histories = {"BTC/USD@1d": monday + tuesday}
    catalog = calendar_candidates(histories)
    voter = next(item for item in catalog if item.candidate_id == "cal_dow_lo_mon")
    long = voter.strategy.evaluate(monday, Regime.RANGE)
    flat = voter.strategy.evaluate(tuesday, Regime.RANGE)
    missing = voter.strategy.evaluate(
        make_candles([100.0], symbol="SOL/USD", start=start),
        Regime.RANGE,
    )
    assert long.side is Side.BUY
    assert flat.side is None
    assert missing.side is None
    assert "skipped" in missing.rationale


def test_control_cannot_enter_dual_print_ranking() -> None:
    rows = [
        _row(CONTROL_ID, kraken_combined=True, binance_combined=True, kraken_ho=0.50),
        _row("cal_dow_lo_mon", kraken_combined=True, binance_combined=True, kraken_ho=0.08),
        _row("cal_moy_lo_jan", kraken_combined=True, binance_combined=False, kraken_ho=0.40),
    ]
    passers = rank_calendar_passers(rows)
    assert [row.candidate_id for row in passers] == ["cal_dow_lo_mon"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False
    assert all(row.candidate_id != CONTROL_ID for row in passers)


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "cal_dow_lo_mon",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.05,
            binance_ho=0.40,
        ),
        _row(
            "cal_moy_lo_q4",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "cal_tom_lo_3_3",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.90,
        ),
    ]
    passers = rank_calendar_passers(rows)
    assert [row.candidate_id for row in passers] == ["cal_moy_lo_q4", "cal_dow_lo_mon"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_eth_carried_mean_is_flagged_96_fail() -> None:
    rows = [
        _row(
            "cal_dow_lo_mon",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.07,
            kraken_btc_ho=-0.16,
            kraken_eth_ho=0.30,
        ),
        _row(
            "cal_moy_lo_jan",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=-0.02,
            kraken_btc_ho=-0.01,
            kraken_eth_ho=-0.03,
        ),
    ]
    flagged = eth_carried_informational(rows)
    assert [row.candidate_id for row in flagged] == ["cal_dow_lo_mon"]


def test_positive_holdout_losing_btc_wf_is_flagged() -> None:
    rows = [
        _row(
            "cal_dow_lo_mon",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.15,
            kraken_btc_ho=0.14,
            kraken_eth_ho=0.16,
            kraken_btc_wf=-0.04,
        ),
        _row(
            "cal_moy_lo_jan",
            kraken_combined=False,
            binance_combined=False,
            kraken_ho=0.10,
            kraken_btc_ho=0.08,
            kraken_eth_ho=0.12,
            kraken_btc_wf=0.02,
        ),
    ]
    flagged = btc_wf_fail_informational(rows)
    assert [row.candidate_id for row in flagged] == ["cal_dow_lo_mon"]


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
    rendered = render_calendar_seasonality_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "paper-executable on Kraken spot" in rendered
    assert "Calendar seasonality" in rendered
    assert "SOL reported" in rendered
    assert "not Bollinger fade" in rendered
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
    rendered = render_calendar_seasonality_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert "Do not re-run dead EMA dual-prints" in rendered
    assert "#120" in rendered
    assert "equal-weight" in rendered.lower()
    assert CALENDAR_CATALOG_NOTE.split("(")[0] in rendered or "Frozen catalog" in rendered


def test_signals_do_not_require_paired_days() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = make_candles([100.0 + index for index in range(10)], symbol="BTC/USD", start=start)
    eth = make_candles([100.0] * 10, symbol="ETH/USD", start=start)[:6]
    mapping = calendar_signals(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        candidate_id="cal_dow_lo_mon",
        kind="dow_lo",
    )
    assert mapping["BTC/USD"]
    assert mapping["ETH/USD"]
    assert len(mapping["BTC/USD"]) != len(mapping["ETH/USD"])


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "calendar-seasonality.md"

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
    out_json = tmp_path / "ops" / "calendar_seasonality.json"
    out_md = tmp_path / "ops" / "calendar_seasonality.md"
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
    assert "Calendar seasonality" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False
