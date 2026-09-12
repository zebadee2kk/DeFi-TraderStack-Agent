from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.candidates import FEATURE_CATALOG
from traderstack.research.intraday_candidates import (
    ALLOWED_INTERVALS,
    DEFAULT_INTERVAL,
    INTRADAY_DUAL_PRINT_CORE_IDS,
    INTRADAY_DUAL_PRINT_GRID_NOTE,
    OPTIONAL_FEATURE_IDS,
    default_intraday_dual_print_candidates,
    skipped_optional_families,
)
from traderstack.research.intraday_dual_print import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    INTRADAY_DUAL_PRINT_RULES,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    IntradayDualPrintRow,
    rank_dual_print_passers,
    render_intraday_dual_print_markdown,
    run_intraday_dual_print,
)
from traderstack.research.intraday_dual_print_cli import build_parser, run
from traderstack.research.second_print import SECOND_PRINT_BARS


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def _step(interval: str) -> timedelta:
    if interval == "1h":
        return timedelta(hours=1)
    if interval == "4h":
        return timedelta(hours=4)
    return timedelta(days=1)


def make_candles(
    prices: list[float],
    *,
    symbol: str = "BTC/USD",
    interval: str = "4h",
    start: datetime | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2026, 5, 15, tzinfo=UTC)
    delta = _step(interval)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=opened + delta * index,
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def downtrend(
    count: int,
    *,
    symbol: str = "BTC/USD",
    interval: str = "4h",
    start: datetime | None = None,
) -> tuple[Candle, ...]:
    return make_candles(
        [200.0 - 0.25 * index for index in range(count)],
        symbol=symbol,
        interval=interval,
        start=start,
    )


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _tiny_catalog():
    return tuple(
        item
        for item in default_intraday_dual_print_candidates()
        if item.candidate_id in {"ma_cross_10_30", "momentum_12"}
    )


def _search(
    kraken: dict[str, tuple[Candle, ...]],
    binance: dict[str, tuple[Candle, ...]] | None = None,
    **overrides: object,
):
    kwargs: dict[str, object] = {
        "interval": "4h",
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
    return run_intraday_dual_print(kraken, binance, **kwargs)  # type: ignore[arg-type]


def _row(
    candidate_id: str,
    *,
    kraken_combined: bool,
    binance_combined: bool,
    kraken_ho: float | None,
    binance_ho: float | None = None,
    family: str = "momentum",
) -> IntradayDualPrintRow:
    return IntradayDualPrintRow(
        candidate_id=candidate_id,
        family=family,
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
    assert not hasattr(cfg, "paper_promote_intraday")
    assert not any("intraday" in name and "promote" in name for name in Settings.model_fields)


def test_bar_and_interval_are_frozen_before_scoring() -> None:
    assert DEFAULT_INTERVAL == "4h"
    assert ALLOWED_INTERVALS == ("4h", "1h")
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in INTRADAY_DUAL_PRINT_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in INTRADAY_DUAL_PRINT_RULES
    assert "CAN_AVERAGE_VENUES=false" in INTRADAY_DUAL_PRINT_RULES
    assert SECOND_PRINT_BARS == 720
    assert "4h/1h" in INTRADAY_DUAL_PRINT_GRID_NOTE
    assert "Not a daily-EMA hunt" in INTRADAY_DUAL_PRINT_GRID_NOTE


def test_catalog_is_frozen_non_ema_core() -> None:
    catalog = default_intraday_dual_print_candidates()
    ids = [item.candidate_id for item in catalog]
    assert ids == list(INTRADAY_DUAL_PRINT_CORE_IDS)
    assert len(ids) == len(set(ids))
    assert len(ids) == 32
    for required in (
        "ma_cross_10_30",
        "momentum_12",
        "mean_reversion_20_1_5",
        "ma_cross_10_30_vol",
        "momentum_18",
        "mean_reversion_30_1_5_vol",
    ):
        assert required in ids
    families = {item.family for item in catalog}
    assert "ma_cross" in families
    assert "momentum" in families
    assert "mean_reversion" in families
    ema_ids = [item.candidate_id for item in catalog if item.family == "ema_cross"]
    assert ema_ids == ["ema_9_21", "ema_12_26"]
    assert "funding_z_fade" not in ids
    assert "oi_z_follow" not in ids
    assert "liquidation_z_fade" not in ids


def test_funding_oi_instantiate_only_when_series_present() -> None:
    start = datetime(2026, 5, 1, tzinfo=UTC)
    series = tuple(
        (start + timedelta(hours=8 * index), 0.01 * (index % 5 - 2)) for index in range(40)
    )
    catalog = default_intraday_dual_print_candidates(
        funding_by_symbol={"BTC/USD": series, "ETH/USD": series},
        open_interest_by_symbol={"BTC/USD": series, "ETH/USD": series},
    )
    ids = [item.candidate_id for item in catalog]
    assert ids[:32] == list(INTRADAY_DUAL_PRINT_CORE_IDS)
    assert ids[32:] == list(OPTIONAL_FEATURE_IDS)
    assert "liquidation_z_fade" not in ids
    feature_ids = {item[1] for item in FEATURE_CATALOG}
    assert "funding_z_fade" in feature_ids


def test_skipped_optional_families_are_honest() -> None:
    notes = skipped_optional_families(funding_present=False, open_interest_present=False)
    joined = " ".join(notes)
    assert "liquidation_z" in joined
    assert "Not invented" in joined
    assert "funding_z" in joined
    assert "open_interest_z" in joined
    present = skipped_optional_families(funding_present=True, open_interest_present=True)
    joined_present = " ".join(present)
    assert "funding_z: skipped" not in joined_present
    assert "liquidation_z" in joined_present


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "kraken_only",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.40,
            binance_ho=-0.10,
        ),
        _row(
            "dual_low_kraken_high_binance",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.08,
            binance_ho=0.50,
        ),
        _row(
            "dual_high_kraken",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "binance_only",
            kraken_combined=False,
            binance_combined=True,
            kraken_ho=0.30,
            binance_ho=0.40,
        ),
    ]
    passers = rank_dual_print_passers(rows)
    assert [row.candidate_id for row in passers] == [
        "dual_high_kraken",
        "dual_low_kraken_high_binance",
    ]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_ranking_tie_breaks_on_candidate_id() -> None:
    rows = [
        _row("zeta", kraken_combined=True, binance_combined=True, kraken_ho=0.10),
        _row("alpha", kraken_combined=True, binance_combined=True, kraken_ho=0.10),
    ]
    passers = rank_dual_print_passers(rows)
    assert [row.candidate_id for row in passers] == ["alpha", "zeta"]


def test_empty_binance_is_success_and_cannot_promote() -> None:
    start = datetime(2026, 5, 15, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@4h": downtrend(720, symbol="BTC/USD", start=start),
            "ETH/USD@4h": downtrend(720, symbol="ETH/USD", start=start),
        },
        {},
    )
    assert report.interval == "4h"
    assert report.binance_slice.available is False
    assert report.any_dual_print_passer is False
    assert report.selected_candidate_id is None
    assert report.recommended_promote_flag is None
    assert report.keep_flag_false is True
    assert report.multi_venue_bar_preregistered is True
    assert report.can_average_venues is False
    rendered = render_intraday_dual_print_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "4h" in rendered
    assert settings().paper_promote_ema_9_21 is False


def test_short_binance_slice_fails_closed() -> None:
    primary = datetime(2026, 5, 15, tzinfo=UTC)
    older = datetime(2026, 1, 1, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@4h": downtrend(720, symbol="BTC/USD", start=primary),
            "ETH/USD@4h": downtrend(720, symbol="ETH/USD", start=primary),
        },
        {
            "BTCUSDT@4h": downtrend(100, symbol="BTCUSDT", start=older),
            "ETHUSDT@4h": downtrend(100, symbol="ETHUSDT", start=older),
        },
    )
    assert report.binance_slice.available is False
    assert "shorter than 720" in (report.binance_slice.fail_closed_reason or "")
    assert report.any_dual_print_passer is False


def test_overlapping_binance_fails_closed() -> None:
    start = datetime(2026, 5, 15, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@4h": downtrend(720, symbol="BTC/USD", start=start),
            "ETH/USD@4h": downtrend(720, symbol="ETH/USD", start=start),
        },
        {
            "BTCUSDT@4h": downtrend(720, symbol="BTCUSDT", start=start),
            "ETHUSDT@4h": downtrend(720, symbol="ETHUSDT", start=start),
        },
    )
    assert report.binance_slice.available is False
    reason = report.binance_slice.fail_closed_reason or ""
    assert "shorter than 720" in reason or "overlaps" in reason
    assert report.any_dual_print_passer is False


def test_binance_older_slice_is_scored_and_gate_holds() -> None:
    primary = datetime(2026, 5, 15, tzinfo=UTC)
    older = datetime(2026, 1, 15, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@4h": downtrend(720, symbol="BTC/USD", start=primary),
            "ETH/USD@4h": downtrend(720, symbol="ETH/USD", start=primary),
        },
        {
            "BTCUSDT@4h": downtrend(720, symbol="BTCUSDT", start=older),
            "ETHUSDT@4h": downtrend(720, symbol="ETHUSDT", start=older),
        },
        binance_source="binance_us_spot",
    )
    assert report.binance_slice.available is True
    assert report.binance_slice.overlaps_primary_window is False
    assert report.binance_slice.bars_btc == 720
    assert report.keep_flag_false is True
    assert all(row.can_promote is False for row in report.rows)
    for row in report.rows:
        expected = row.kraken_combined and row.binance_combined
        assert row.dual_print is expected
    rendered = render_intraday_dual_print_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert (
        "Not a daily-EMA hunt" in rendered
        or "not just EMA" in rendered.lower()
        or "non-EMA" in rendered
        or "not the hunt family" in rendered
    )


def test_daily_histories_are_rejected_for_4h_search() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    try:
        run_intraday_dual_print(
            {
                "BTC/USD@1d": downtrend(720, symbol="BTC/USD", interval="1d", start=start),
                "ETH/USD@1d": downtrend(720, symbol="ETH/USD", interval="1d", start=start),
            },
            interval="4h",
            fee_bps=10.0,
            candidates=_tiny_catalog(),
        )
    except ValueError as exc:
        assert "4h" in str(exc)
    else:
        raise AssertionError("1d histories must not score as a 4h hunt")


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "intraday-dual-print.md"
    assert args.interval == "4h"

    primary = datetime(2026, 5, 15, tzinfo=UTC)
    older = datetime(2026, 1, 15, tzinfo=UTC)
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    btc_usdt = tmp_path / "btcusdt.json"
    eth_usdt = tmp_path / "ethusdt.json"
    write_candles(btc, downtrend(240, symbol="BTC/USD", start=primary))
    write_candles(eth, downtrend(240, symbol="ETH/USD", start=primary))
    write_candles(btc_usdt, downtrend(720, symbol="BTCUSDT", start=older))
    write_candles(eth_usdt, downtrend(720, symbol="ETHUSDT", start=older))
    out_json = tmp_path / "ops" / "intra.json"
    out_md = tmp_path / "ops" / "intra.md"
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
            "--interval",
            "4h",
            "--no-fetch-edge-series",
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
    assert payload["interval"] == "4h"
    assert payload["ranking_key"] == RANKING_KEY
    assert payload["keep_flag_false"] is True
    assert payload["multi_venue_bar_preregistered"] is True
    assert payload["can_average_venues"] is False
    assert payload["any_dual_print_passer"] is False
    assert payload["selected_candidate_id"] is None
    text = written_md.read_text()
    assert "Intraday (4h) dual-print" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False
    assert settings().trading_mode == "paper"
