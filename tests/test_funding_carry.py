from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.funding_carry import (
    CARRY_IDS,
    CONTROL_IDS,
    CORE_IDS,
    FUNDING_CARRY_RULES,
    FUNDING_Z_IDS,
    OVERLAY_IDS,
    PAPER_CARRY_PATH_READY,
    PRINT_DUAL,
    PRINT_SINGLE,
    choose_walkforward,
    evaluate_carry_hard_gates,
    funding_usable,
    hard_gates_available,
    render_funding_carry_markdown,
    resample_funding_to_daily,
    run_funding_carry,
    score_hedged_carry,
    skipped_funding_families,
    slice_to_funding_overlap,
    spot_candidates,
)
from traderstack.research.funding_carry_cli import (
    _pick_venues,
    build_parser,
    fetch_basis_venues,
    run,
)


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


def aligned_funding(candles: tuple[Candle, ...], *, amplitude: float = 0.0004) -> tuple:
    return tuple(
        (candle.opened_at, amplitude * ((index % 7) - 3)) for index, candle in enumerate(candles)
    )


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def write_series(path: Path, series: tuple) -> None:
    rows = [{"opened_at": ts.isoformat(), "value": value} for ts, value in series]
    path.write_text(json.dumps(rows))


def _search(histories: dict[str, tuple[Candle, ...]], **overrides: object) -> object:
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "warmup": 8,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "interval": "1d",
    }
    kwargs.update(overrides)
    return run_funding_carry(histories, **kwargs)  # type: ignore[arg-type]


def test_core_catalog_is_frozen() -> None:
    assert set(FUNDING_Z_IDS) | set(OVERLAY_IDS) | set(CARRY_IDS) | CONTROL_IDS == set(CORE_IDS)
    assert "funding_z_fade_1_5" in FUNDING_Z_IDS
    assert "carry_hedged_sign" in CARRY_IDS
    assert "ema_9_21_funding_agree" in OVERLAY_IDS
    catalog = spot_candidates(
        funding=tuple((datetime(2024, 1, 1, tzinfo=UTC), 0.0001) for _ in range(30))
    )
    ids = {item.candidate_id for item in catalog}
    assert set(FUNDING_Z_IDS) <= ids
    assert set(OVERLAY_IDS) <= ids
    assert CONTROL_IDS <= ids
    assert spot_candidates() == ()


def test_funding_usable_requires_btc_and_eth() -> None:
    series = tuple(
        (datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i), 0.0002) for i in range(30)
    )
    assert funding_usable(series) is True
    assert funding_usable(funding_by_symbol={"BTC/USD": series}) is False
    assert funding_usable(funding_by_symbol={"BTC/USD": series, "ETH/USD": series}) is True
    assert funding_usable() is False


def test_hard_gates_need_daily_720() -> None:
    assert hard_gates_available(interval="1d", aligned_bars=720) is True
    assert hard_gates_available(interval="4h", aligned_bars=720) is False
    assert hard_gates_available(interval="1d", aligned_bars=90) is False
    assert hard_gates_available(interval="1d", aligned_bars=720, second_aligned_bars=90) is False
    assert hard_gates_available(interval="1d", aligned_bars=720, second_aligned_bars=720) is True


def test_resample_funding_sums_utc_days_and_skips_empty() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    series = (
        (start.replace(hour=0), 0.0001),
        (start.replace(hour=8), 0.0002),
        (start.replace(hour=16), -0.00005),
        (start + timedelta(days=2, hours=8), 0.0003),
    )
    daily = resample_funding_to_daily(series)
    assert len(daily) == 2
    assert daily[0] == (start, 0.00025)
    assert daily[1][0] == start + timedelta(days=2)
    assert daily[1][1] == 0.0003
    assert resample_funding_to_daily(None) == ()
    assert resample_funding_to_daily(()) == ()


def test_choose_walkforward_adapts_when_short() -> None:
    assert choose_walkforward(400, train_size=180, test_size=60, warmup=21) == (
        180,
        60,
        60,
        21,
    )
    adapted = choose_walkforward(130, train_size=180, test_size=60, warmup=31)
    assert adapted == (80, 40, 40, 31)
    assert choose_walkforward(20, train_size=180, test_size=60, warmup=31) is None


def test_slice_skips_unfunded_history() -> None:
    candles = downtrend(20)
    series = aligned_funding(candles[5:12])
    overlap = slice_to_funding_overlap(candles, series)
    assert overlap[0].opened_at == candles[5].opened_at
    assert overlap[-1].opened_at == candles[11].opened_at
    assert slice_to_funding_overlap(candles, None) == ()


def test_missing_funding_is_single_print_and_cannot_promote() -> None:
    report = _search(
        {
            "BTC/USD@1d": downtrend(360, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(360, symbol="ETH/USD"),
        }
    )
    assert report.print_kind == PRINT_SINGLE
    assert report.can_promote is False
    assert report.any_promoted is False
    assert report.promoted_candidate_ids == []
    assert report.recommended_promote_flag is None
    assert report.keep_flag_false is True
    assert report.hard_gates_available is False
    assert report.search is None
    assert report.carry == []
    skipped = {item["candidate_id"] for item in report.skipped_feature_families}
    assert set(FUNDING_Z_IDS) <= skipped
    assert set(CARRY_IDS) <= skipped
    assert set(OVERLAY_IDS) <= skipped
    text = render_funding_carry_markdown(report)
    assert "cannot promote" in text
    assert "PAPER_PROMOTE_*" in text
    assert "Leave every `PAPER_PROMOTE_*` false" in text
    assert "SINGLE-PRINT" in report.honesty or "single_print" in text


def test_funding_series_scores_catalog_but_stays_unpromoted() -> None:
    btc = downtrend(360, symbol="BTC/USD")
    eth = downtrend(360, symbol="ETH/USD")
    series = aligned_funding(btc)
    report = _search(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        funding_by_symbol={"BTC/USD": series, "ETH/USD": series},
        primary_venue="okx",
        interval="1d",
    )
    assert report.print_kind == PRINT_SINGLE
    assert report.can_promote is False
    assert report.primary_venue == "okx"
    assert report.hard_gates_available is False
    ids = {row.candidate_id for row in (report.search.candidates if report.search else [])}
    assert set(FUNDING_Z_IDS) <= ids
    assert set(OVERLAY_IDS) <= ids
    assert "ma_cross_10_30" in ids
    assert {row.candidate_id for row in report.carry} == set(CARRY_IDS)
    assert all(row.promoted is False for row in report.carry)
    skipped = {item["candidate_id"] for item in report.skipped_feature_families}
    assert "funding_z_fade_1_5" not in skipped
    text = render_funding_carry_markdown(report)
    assert "Hedged carry" in text
    assert "No candidate is promoted" in text


def test_one_funding_venue_is_not_dual_print() -> None:
    btc = downtrend(360, symbol="BTC/USD")
    series = aligned_funding(btc)
    report = _search({"BTC/USD@1d": btc}, funding=series, primary_venue="okx")
    assert report.print_kind == PRINT_SINGLE
    assert report.second_venue is None
    assert report.can_promote is False


def test_dual_print_without_passer_still_cannot_promote() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    other = datetime(2023, 1, 1, tzinfo=UTC)
    btc = downtrend(360, symbol="BTC/USD", start=start)
    eth = downtrend(360, symbol="ETH/USD", start=start)
    other_btc = downtrend(360, symbol="BTC/USD", start=other)
    other_eth = downtrend(360, symbol="ETH/USD", start=other)
    series = aligned_funding(btc)
    other_series = aligned_funding(other_btc)
    report = _search(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        funding_by_symbol={"BTC/USD": series, "ETH/USD": series},
        second_funding_by_symbol={"BTC/USD": other_series, "ETH/USD": other_series},
        second_histories={"BTC/USD@1d": other_btc, "ETH/USD@1d": other_eth},
        primary_venue="okx",
        second_venue="binance",
    )
    assert report.print_kind == PRINT_DUAL
    assert report.can_promote is False
    assert report.any_promoted is False
    assert report.recommended_promote_flag is None
    text = render_funding_carry_markdown(report)
    assert "dual_print" in text
    assert "No candidate is promoted" in text
    assert "Second funding print" in text
    assert report.second_venue == "binance"


def test_pick_venues_selects_two_usable_and_skips_empty() -> None:
    series = tuple(
        (datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=8 * i), 0.0001) for i in range(40)
    )
    long_series = series + tuple(
        (datetime(2024, 2, 15, tzinfo=UTC) + timedelta(hours=i), 0.0001) for i in range(80)
    )
    primary, primary_name, second, second_name = _pick_venues(
        {
            "binance": {},
            "bybit": {},
            "okx": {"BTC/USD": series, "ETH/USD": series},
            "hyperliquid": {"BTC/USD": long_series, "ETH/USD": long_series},
            "bitmex": {"BTC/USD": series + series, "ETH/USD": series + series},
        }
    )
    assert primary_name == "hyperliquid"
    assert second_name == "bitmex"
    assert primary is not None and second is not None
    none_primary, none_name, none_second, none_second_name = _pick_venues(
        {"binance": {}, "bybit": {}}
    )
    assert none_primary is None
    assert none_name is None
    assert none_second is None
    assert none_second_name is None


def test_dual_print_modeled_carry_passer_still_cannot_promote() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    other = datetime(2023, 1, 1, tzinfo=UTC)
    btc = downtrend(360, symbol="BTC/USD", start=start)
    eth = downtrend(360, symbol="ETH/USD", start=start)
    other_btc = downtrend(360, symbol="BTC/USD", start=other)
    other_eth = downtrend(360, symbol="ETH/USD", start=other)
    series = tuple((candle.opened_at, 0.001) for candle in btc)
    other_series = tuple((candle.opened_at, 0.001) for candle in other_btc)
    report = _search(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        funding_by_symbol={"BTC/USD": series, "ETH/USD": series},
        second_funding_by_symbol={"BTC/USD": other_series, "ETH/USD": other_series},
        second_histories={"BTC/USD@1d": other_btc, "ETH/USD@1d": other_eth},
        primary_venue="hyperliquid",
        second_venue="okx",
        min_trades=1,
    )
    assert report.print_kind == PRINT_DUAL
    assert "carry_hedged_sign" in report.dual_print_passer_ids
    assert report.can_promote is False
    assert report.any_promoted is False
    assert report.recommended_promote_flag is None
    assert report.keep_flag_false is True
    assert all(row.executable_on_paper_spot is False for row in report.carry)
    text = render_funding_carry_markdown(report)
    assert "carry_hedged_sign" in text
    assert "No candidate is promoted" in text
    assert "Do not add a new pin" in text


def test_hedged_carry_measures_constant_rate_after_fees() -> None:
    series = tuple(
        (datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=8 * index), 0.001)
        for index in range(80)
    )
    measured = score_hedged_carry(
        series,
        abs_threshold=None,
        z_threshold=None,
        fee_bps=10.0,
        slippage_bps=5.0,
        train_size=40,
        test_size=20,
        step_size=20,
    )
    assert measured["full_sample_total_return"] is not None
    assert float(measured["full_sample_total_return"]) > 0
    # One entry flip: 2 legs × 15 bps = 30 bps, then collect 0.001 × remaining.
    assert int(measured["flips"]) == 1


def test_skipped_families_when_no_funding() -> None:
    skipped = skipped_funding_families(funding=None, funding_by_symbol=None)
    ids = {item["candidate_id"] for item in skipped}
    assert set(FUNDING_Z_IDS) <= ids
    assert set(CARRY_IDS) <= ids
    assert (
        skipped_funding_families(funding=((datetime.now(UTC), 0.1),), funding_by_symbol=None) == []
    )


def test_cli_offline_writes_single_print_report(tmp_path: Path) -> None:
    btc = downtrend(360, symbol="BTC/USD")
    eth = downtrend(360, symbol="ETH/USD")
    btc_path = tmp_path / "btc.json"
    eth_path = tmp_path / "eth.json"
    write_candles(btc_path, btc)
    write_candles(eth_path, eth)
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    args = build_parser().parse_args(
        [
            "--candles",
            str(btc_path),
            "--candles",
            str(eth_path),
            "--interval",
            "1d",
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
            "--warmup",
            "8",
            "--min-trades",
            "1",
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
        ]
    )
    run(args, settings())
    payload = json.loads(out_json.read_text())
    assert payload["print_kind"] == "single_print"
    assert payload["can_promote"] is False
    assert payload["any_promoted"] is False
    assert payload["keep_flag_false"] is True
    assert payload["recommended_promote_flag"] is None
    text = out_md.read_text()
    assert "cannot promote" in text
    assert "PAPER_PROMOTE_*" in text
    defaults = settings()
    assert defaults.paper_promote_searched_strategies is False
    assert defaults.paper_promote_ema_9_21 is False
    assert defaults.paper_promote_ema_9_21_adx15 is False
    assert defaults.trading_mode == "paper"


def test_cli_with_funding_file_does_not_promote(tmp_path: Path) -> None:
    btc = downtrend(360, symbol="BTC/USD")
    path = tmp_path / "btc.json"
    series_path = tmp_path / "funding.json"
    write_candles(path, btc)
    write_series(series_path, aligned_funding(btc))
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    args = build_parser().parse_args(
        [
            "--candles",
            str(path),
            "--interval",
            "1d",
            "--funding-z",
            str(series_path),
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
            "--warmup",
            "8",
            "--min-trades",
            "1",
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
        ]
    )
    run(args, settings())
    payload = json.loads(out_json.read_text())
    ids = {row["candidate_id"] for row in (payload["search"] or {}).get("candidates", [])}
    assert "funding_z_fade_1_5" in ids
    assert payload["print_kind"] == "single_print"
    assert payload["can_promote"] is False
    assert payload["any_promoted"] is False
    assert {row["candidate_id"] for row in payload["carry"]} == set(CARRY_IDS)


def test_parser_defaults_keep_promote_paths_off() -> None:
    parser = build_parser()
    args = parser.parse_args(["--live"])
    assert args.interval == "4h"
    assert "funding-carry.md" in str(args.output_md)
    assert settings().trading_mode == "paper"
    assert FUNDING_CARRY_RULES.startswith("Pre-registered funding/carry")
    assert PAPER_CARRY_PATH_READY is False


def test_daily_resample_skips_basis_and_cannot_promote() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = downtrend(360, symbol="BTC/USD", start=start)
    eth = downtrend(360, symbol="ETH/USD", start=start)
    # Three 8h prints per day → resample should collapse to ~360 daily sums.
    eight_hour = tuple((start + timedelta(hours=8 * index), 0.0004) for index in range(360 * 3))
    report = _search(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        funding_by_symbol={"BTC/USD": eight_hour, "ETH/USD": eight_hour},
        primary_venue="hyperliquid",
        interval="1d",
    )
    assert report.funding_resampled_to == "1d"
    assert report.basis_status == "skipped"
    assert report.paper_path_ready is False
    assert report.can_promote is False
    assert report.hard_gates_available is False
    assert report.primary_carry_hard_gates is not None
    assert report.primary_carry_hard_gates.available is False
    assert "720" in report.primary_carry_hard_gates.note
    text = render_funding_carry_markdown(report)
    assert "Basis (skip-not-invent)" in text
    assert "skipped" in text
    assert "Paper-executable path" in text
    assert "PAPER_CARRY_PATH_READY" in text or "not promote-ready" in text
    assert "Do not add a Settings pin" in text


def test_short_second_venue_keeps_hard_gates_unavailable() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    other = datetime(2023, 1, 1, tzinfo=UTC)
    btc = downtrend(720, symbol="BTC/USD", start=start)
    eth = downtrend(720, symbol="ETH/USD", start=start)
    short_btc = downtrend(90, symbol="BTC/USD", start=other)
    short_eth = downtrend(90, symbol="ETH/USD", start=other)
    long_series = tuple((candle.opened_at, 0.001) for candle in btc)
    short_series = tuple((candle.opened_at, 0.001) for candle in short_btc)
    report = _search(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        funding_by_symbol={"BTC/USD": long_series, "ETH/USD": long_series},
        second_funding_by_symbol={"BTC/USD": short_series, "ETH/USD": short_series},
        second_histories={"BTC/USD@1d": short_btc, "ETH/USD@1d": short_eth},
        primary_venue="hyperliquid",
        second_venue="okx",
        interval="1d",
        min_trades=1,
    )
    assert report.print_kind == PRINT_DUAL
    assert report.primary_aligned_bars >= 720
    assert report.second_aligned_bars < 720
    assert report.hard_gates_available is False
    assert report.can_promote is False
    assert report.basis_status == "skipped"
    assert report.paper_path_ready is False
    assert report.recommended_promote_flag is None
    assert report.second_carry_hard_gates is not None
    assert report.second_carry_hard_gates.available is False
    text = render_funding_carry_markdown(report)
    assert "UNAVAILABLE" in text
    assert "No candidate is promoted" in text


def test_basis_file_is_modeled_but_still_cannot_promote_without_paper_path() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    series = tuple((start + timedelta(days=index), 0.001) for index in range(80))
    # Falling basis while harvesting is a cash-and-carry gain.
    basis = tuple((start + timedelta(days=index), 0.01 - 0.0001 * index) for index in range(80))
    without = score_hedged_carry(
        series,
        abs_threshold=None,
        z_threshold=None,
        fee_bps=10.0,
        slippage_bps=5.0,
        train_size=40,
        test_size=20,
        step_size=20,
    )
    with_basis = score_hedged_carry(
        series,
        abs_threshold=None,
        z_threshold=None,
        fee_bps=10.0,
        slippage_bps=5.0,
        train_size=40,
        test_size=20,
        step_size=20,
        basis=basis,
    )
    assert with_basis["basis_modeled"] is True
    assert int(with_basis["basis_days_applied"] or 0) > 0
    assert float(with_basis["full_sample_total_return"] or 0) > float(
        without["full_sample_total_return"] or 0
    )

    btc = downtrend(360, symbol="BTC/USD", start=start)
    eth = downtrend(360, symbol="ETH/USD", start=start)
    funding = aligned_funding(btc)
    report = _search(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        funding_by_symbol={"BTC/USD": funding, "ETH/USD": funding},
        primary_venue="file",
        interval="1d",
        basis=funding,
    )
    assert report.basis_status == "ok"
    assert report.can_promote is False
    assert report.paper_path_ready is False
    assert report.any_promoted is False


@pytest.mark.asyncio
async def test_fetch_basis_venues_records_skip_not_invent(monkeypatch: pytest.MonkeyPatch) -> None:
    from traderstack.research.edge_series import EdgeSeriesFetch

    async def fake_hl(symbol: str, *, client: object) -> EdgeSeriesFetch:
        return EdgeSeriesFetch(
            name=f"hyperliquid_basis:{symbol}",
            status="skipped",
            reason="UNAVAILABLE: current mark only",
            source="hyperliquid",
        )

    async def fake_bm(symbol: str, *, client: object) -> EdgeSeriesFetch:
        return EdgeSeriesFetch(
            name=f"bitmex_basis:{symbol}",
            status="skipped",
            reason="UNAVAILABLE: current mark only",
            source="bitmex",
        )

    monkeypatch.setattr(
        "traderstack.research.funding_carry_cli.fetch_hyperliquid_basis", fake_hl
    )
    monkeypatch.setattr("traderstack.research.funding_carry_cli.fetch_bitmex_basis", fake_bm)
    monkeypatch.setattr(
        "traderstack.research.funding_carry_cli.HYPERLIQUID_SYMBOL_PAUSE_SECONDS", 0
    )
    notes = await fetch_basis_venues(("BTC/USD", "ETH/USD"))
    names = {item["name"] for item in notes}
    assert names == {
        "hyperliquid_basis:BTC/USD",
        "hyperliquid_basis:ETH/USD",
        "bitmex_basis:BTC/USD",
        "bitmex_basis:ETH/USD",
    }
    assert all(item["status"] == "skipped" for item in notes)
    assert all(item["points"] == "0" for item in notes)


def test_evaluate_carry_hard_gates_unavailable_on_short_daily_tape() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    short = tuple((start + timedelta(days=index), 0.0002) for index in range(90))
    gates = evaluate_carry_hard_gates(
        {"BTC/USD": short, "ETH/USD": short},
        fee_bps=10.0,
        slippage_bps=5.0,
        holdout_fraction=0.2,
    )
    assert gates.available is False
    assert gates.combined is False
    assert "720" in gates.note
