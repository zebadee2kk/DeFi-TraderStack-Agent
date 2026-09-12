from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.candidates import FEATURE_CATALOG
from traderstack.research.liq_regime_search import (
    CONTROL_IDS,
    LIQ_REGIME_CORE_IDS,
    LIQ_REGIME_RULES,
    PRINT_DUAL,
    PRINT_SINGLE,
    ema_liq_agree_candidates,
    historical_liquidation_usable,
    liq_regime_core_candidates,
    render_liq_regime_markdown,
    run_liq_regime_search,
    second_venue_usable,
    skipped_optional_families,
)
from traderstack.research.liq_regime_search_cli import build_parser, run


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


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def write_series(path: Path, candles: tuple[Candle, ...]) -> None:
    rows = [
        {"opened_at": candle.opened_at.isoformat(), "value": float(index % 7) - 3.0}
        for index, candle in enumerate(candles)
    ]
    path.write_text(json.dumps(rows))


def _search(
    histories: dict[str, tuple[Candle, ...]],
    **overrides: object,
) -> object:
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "min_second_venue_bars": 200,
    }
    kwargs.update(overrides)
    return run_liq_regime_search(histories, **kwargs)  # type: ignore[arg-type]


def test_core_catalog_is_frozen() -> None:
    catalog = liq_regime_core_candidates()
    assert tuple(item.candidate_id for item in catalog) == LIQ_REGIME_CORE_IDS
    assert CONTROL_IDS < set(LIQ_REGIME_CORE_IDS)
    assert all(item.requires_feature is None for item in catalog)


def test_historical_liq_requires_btc_and_eth() -> None:
    series = tuple((datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i), 0.1) for i in range(30))
    assert historical_liquidation_usable(series) is True
    assert historical_liquidation_usable(liquidation_by_symbol={"BTC/USD": series}) is False
    assert (
        historical_liquidation_usable(liquidation_by_symbol={"BTC/USD": series, "ETH/USD": series})
        is True
    )
    assert historical_liquidation_usable() is False


def test_second_venue_requires_both_assets() -> None:
    btc = downtrend(240, symbol="BTC/USD")
    eth = downtrend(240, symbol="ETH/USD")
    assert second_venue_usable({"a": btc}, min_bars=200) is False
    assert second_venue_usable({"a": btc, "b": eth}, min_bars=200) is True
    assert second_venue_usable({"a": btc, "b": eth}, min_bars=400) is False


def test_ema_liq_agree_skipped_without_series() -> None:
    assert ema_liq_agree_candidates() == ()
    series = tuple((datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i), 1.0) for i in range(25))
    ids = {item.candidate_id for item in ema_liq_agree_candidates(liquidation=series)}
    assert ids == {"ema_9_21_liq_agree", "ema_9_21_adx15_liq_agree", "ema_12_26_liq_agree"}


def test_skipped_families_include_ema_liq_agree() -> None:
    skipped = skipped_optional_families(
        liquidation=None,
        liquidation_by_symbol=None,
        funding=None,
        funding_by_symbol=None,
        open_interest=None,
        open_interest_by_symbol=None,
        cross_venue=None,
    )
    ids = {item["candidate_id"] for item in skipped}
    assert "liquidation_z_fade" in ids
    assert "ema_9_21_liq_agree" in ids
    assert "funding_z_fade" in ids
    assert {item[1] for item in FEATURE_CATALOG} < ids


def test_missing_liq_is_single_print_and_cannot_promote() -> None:
    report = _search(
        {
            "BTC/USD@1d": downtrend(360, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(360, symbol="ETH/USD"),
        }
    )
    assert report.print_kind == PRINT_SINGLE
    assert report.historical_liquidation is False
    assert report.second_venue is False
    assert report.can_promote is False
    assert report.any_promoted is False
    assert report.promoted_candidate_ids == []
    assert report.recommended_promote_flag is None
    assert report.keep_flag_false is True
    ids = {row.candidate_id for row in report.search.candidates}
    assert set(LIQ_REGIME_CORE_IDS) <= ids
    assert "liquidation_z_fade" not in ids
    assert "ema_9_21_liq_agree" not in ids
    assert all(row.promoted is False for row in report.search.candidates)
    skipped = {item["candidate_id"] for item in report.skipped_feature_families}
    assert "liquidation_z_fade" in skipped
    assert "ema_9_21_adx15_liq_agree" in skipped
    text = render_liq_regime_markdown(report)
    assert "SINGLE-PRINT" in text or "single_print" in text
    assert "cannot promote" in text
    assert "PAPER_PROMOTE_*" in text
    assert "Leave every `PAPER_PROMOTE_*` false" in text
    assert LIQ_REGIME_RULES.split("Dual-print")[0].strip() in report.honesty or "SINGLE-PRINT" in (
        report.honesty
    )


def test_liq_series_instantiates_feature_voters_but_stays_unpromoted() -> None:
    btc = downtrend(360, symbol="BTC/USD")
    eth = downtrend(360, symbol="ETH/USD")
    series = tuple((c.opened_at, float(index % 7) - 3.0) for index, c in enumerate(btc))
    report = _search(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        liquidation_by_symbol={"BTC/USD": series, "ETH/USD": series},
    )
    assert report.historical_liquidation is True
    assert report.print_kind == PRINT_SINGLE
    assert report.can_promote is False
    ids = {row.candidate_id for row in report.search.candidates}
    assert "liquidation_z_fade" in ids
    assert "liquidation_z_follow" in ids
    assert "ema_9_21_liq_agree" in ids
    assert "momentum_12_liq_agree" in ids
    skipped = {item["candidate_id"] for item in report.skipped_feature_families}
    assert "liquidation_z_fade" not in skipped
    assert "funding_z_fade" in skipped


def test_dual_print_without_passer_still_cannot_promote() -> None:
    start = datetime(2023, 1, 1, tzinfo=UTC)
    btc = downtrend(360, symbol="BTC/USD", start=start)
    eth = downtrend(360, symbol="ETH/USD", start=start)
    other_start = datetime(2022, 1, 1, tzinfo=UTC)
    other_btc = downtrend(360, symbol="BTC/USD", start=other_start)
    other_eth = downtrend(360, symbol="ETH/USD", start=other_start)
    series = tuple((c.opened_at, float(index % 7) - 3.0) for index, c in enumerate(btc))
    report = _search(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        liquidation_by_symbol={"BTC/USD": series, "ETH/USD": series},
        second_venue_histories={"BTC/USD@1d": other_btc, "ETH/USD@1d": other_eth},
    )
    assert report.print_kind == PRINT_DUAL
    assert report.historical_liquidation is True
    assert report.second_venue is True
    assert report.can_promote is False
    assert report.any_promoted is False
    assert report.recommended_promote_flag is None
    assert report.second_print_search is not None
    text = render_liq_regime_markdown(report)
    assert "dual_print" in text
    assert "No candidate is promoted" in text


def test_funding_series_is_scored_when_supplied() -> None:
    btc = downtrend(360, symbol="BTC/USD")
    series = tuple((c.opened_at, 0.01 * ((index % 5) - 2)) for index, c in enumerate(btc))
    report = _search(
        {"BTC/USD@1d": btc},
        funding=series,
    )
    ids = {row.candidate_id for row in report.search.candidates}
    assert "funding_z_fade" in ids
    assert "funding_z_follow" in ids
    assert report.print_kind == PRINT_SINGLE
    assert report.can_promote is False


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
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
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


def test_cli_with_liq_file_does_not_promote(tmp_path: Path) -> None:
    btc = downtrend(360, symbol="BTC/USD")
    path = tmp_path / "btc.json"
    series_path = tmp_path / "liq.json"
    write_candles(path, btc)
    write_series(series_path, btc)
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    args = build_parser().parse_args(
        [
            "--candles",
            str(path),
            "--liquidation-z",
            str(series_path),
            "--no-binance",
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
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
    ids = {row["candidate_id"] for row in payload["search"]["candidates"]}
    assert "liquidation_z_fade" in ids
    assert payload["print_kind"] == "single_print"
    assert payload["can_promote"] is False
    assert payload["any_promoted"] is False


def test_parser_defaults_keep_promote_paths_off() -> None:
    parser = build_parser()
    args = parser.parse_args(["--live-kraken"])
    assert args.binance is True
    assert "liq-regime-search.md" in str(args.output_md)
    assert settings().trading_mode == "paper"
