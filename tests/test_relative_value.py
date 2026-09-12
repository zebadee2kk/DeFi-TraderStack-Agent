from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from traderstack.research.relative_value import (
    CONTROL_ID,
    CONTROL_IDS,
    CORE_IDS,
    PAPER_PATH_READY,
    RELATIVE_VALUE_LOOKBACK,
    RELATIVE_VALUE_RULES,
    RELATIVE_VALUE_Z_THRESHOLDS,
    RV_IDS,
    btc_minus_eth_residual,
    rank_relative_value_passers,
    relative_value_candidates,
    render_relative_value_markdown,
    residual_by_symbol,
    run_relative_value_search,
    skipped_residual_families,
)
from traderstack.research.relative_value_cli import build_parser, run
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


def _tiny_catalog():
    residual = tuple(
        (datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index), 0.01 if index > 20 else 0.0)
        for index in range(40)
    )
    return relative_value_candidates(residual=residual)


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
    return run_relative_value_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


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
        family="relative_value",
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
    assert not hasattr(cfg, "paper_promote_rv_fade_1_5")
    assert not hasattr(cfg, "paper_promote_relative_value")


def test_catalog_and_bar_are_frozen_before_scoring() -> None:
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert PAPER_PATH_READY is True
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in RELATIVE_VALUE_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in RELATIVE_VALUE_RULES
    assert "CAN_AVERAGE_VENUES=false" in RELATIVE_VALUE_RULES
    assert RELATIVE_VALUE_LOOKBACK == 20
    assert RELATIVE_VALUE_Z_THRESHOLDS == (1.0, 1.5, 2.0)
    assert SECOND_PRINT_BARS == 720
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"
    catalog = relative_value_candidates(
        residual=((datetime(2024, 1, 1, tzinfo=UTC), 0.01),) * 25
    )
    ids = [item.candidate_id for item in catalog]
    assert ids == list(CORE_IDS)
    assert ids == [
        "rv_fade_1_0",
        "rv_fade_1_5",
        "rv_fade_2_0",
        "rv_follow_1_0",
        "rv_follow_1_5",
        "rv_follow_2_0",
        CONTROL_ID,
    ]
    assert set(RV_IDS) | CONTROL_IDS == set(CORE_IDS)
    assert "ema_9_21" not in ids
    assert "ema_9_21_adx15" not in ids


def test_missing_pair_skips_residual_names() -> None:
    assert btc_minus_eth_residual(None, downtrend(10, symbol="ETH/USD")) == ()
    assert relative_value_candidates(residual=())[0].candidate_id == CONTROL_ID
    assert len(relative_value_candidates(residual=())) == 1
    skipped = skipped_residual_families(())
    assert {item["candidate_id"] for item in skipped} == set(RV_IDS)
    assert all("invent" in item["reason"] for item in skipped)


def test_residual_skips_unpaired_days_and_does_not_invent() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    btc = make_candles([100.0, 110.0, 121.0, 133.1], symbol="BTC/USD", start=start)
    eth_prices = [100.0, 100.0, 100.0]
    eth = make_candles(eth_prices, symbol="ETH/USD", start=start)
    # Drop the middle ETH bar so 2024-01-02 is unpaired.
    eth = (eth[0], eth[2])
    residual = btc_minus_eth_residual(btc, eth)
    assert [ts.date().isoformat() for ts, _ in residual] == ["2024-01-03"]
    btc_r = 121.0 / 100.0 - 1.0
    eth_r = 100.0 / 100.0 - 1.0
    assert residual[0][1] == btc_r - eth_r


def test_fade_and_follow_are_opposite_legs() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    residual = tuple(
        (start + timedelta(days=index), 0.0 if index < 22 else 0.20) for index in range(30)
    )
    mapping = residual_by_symbol(residual)
    catalog = relative_value_candidates(residual_map=mapping)
    fade = next(item for item in catalog if item.candidate_id == "rv_fade_1_0")
    follow = next(item for item in catalog if item.candidate_id == "rv_follow_1_0")
    btc = make_candles([100.0 + index for index in range(30)], symbol="BTC/USD", start=start)
    eth = make_candles([100.0] * 30, symbol="ETH/USD", start=start)
    fade_btc = fade.strategy.evaluate(btc, Regime.RANGE)
    fade_eth = fade.strategy.evaluate(eth, Regime.RANGE)
    follow_btc = follow.strategy.evaluate(btc, Regime.RANGE)
    follow_eth = follow.strategy.evaluate(eth, Regime.RANGE)
    assert fade_btc.side is Side.SELL
    assert fade_eth.side is Side.BUY
    assert follow_btc.side is Side.BUY
    assert follow_eth.side is Side.SELL


def test_control_cannot_enter_dual_print_ranking() -> None:
    rows = [
        _row(
            CONTROL_ID,
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.50,
        ),
        _row(
            "rv_fade_1_5",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.08,
        ),
        _row(
            "rv_follow_2_0",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.40,
        ),
    ]
    passers = rank_relative_value_passers(rows)
    assert [row.candidate_id for row in passers] == ["rv_fade_1_5"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False
    assert all(row.candidate_id != CONTROL_ID for row in passers)


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "rv_fade_1_0",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.05,
            binance_ho=0.40,
        ),
        _row(
            "rv_fade_2_0",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "rv_follow_1_0",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.90,
        ),
    ]
    passers = rank_relative_value_passers(rows)
    assert [row.candidate_id for row in passers] == ["rv_fade_2_0", "rv_fade_1_0"]
    assert passers[0].selected is True
    assert passers[0].can_promote is False


def test_ranking_tie_breaks_on_candidate_id() -> None:
    rows = [
        _row("rv_follow_1_5", kraken_combined=True, binance_combined=True, kraken_ho=0.10),
        _row("rv_fade_1_5", kraken_combined=True, binance_combined=True, kraken_ho=0.10),
    ]
    passers = rank_relative_value_passers(rows)
    assert [row.candidate_id for row in passers] == ["rv_fade_1_5", "rv_follow_1_5"]


def test_empty_binance_is_success_and_cannot_promote() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=start),
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
    assert report.residual_points > 0
    rendered = render_relative_value_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert "paper-executable on Kraken spot" in rendered
    assert "BTC−ETH relative-value residual" in rendered
    assert settings().paper_promote_ema_9_21_adx15 is False


def test_short_binance_slice_fails_closed() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2023, 1, 1, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=primary),
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


def test_sol_is_not_scored() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(240, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(240, symbol="ETH/USD", start=start),
            "SOL/USD@1d": downtrend(240, symbol="SOL/USD", start=start),
        },
        {},
    )
    assert report.primary_bars == 240
    assert all("SOL" not in note for note in report.data_notes if "residual" in note)


def test_binance_older_slice_is_scored_and_cannot_promote() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=primary),
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
    assert report.catalog_ids == list(CORE_IDS)
    assert all(row.can_promote is False for row in report.rows)
    assert CONTROL_ID not in report.dual_print_passer_ids
    rendered = render_relative_value_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered
    assert "Do not re-run dead EMA dual-prints" in rendered


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "btc-eth-relative-value.md"

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
    out_json = tmp_path / "ops" / "rv.json"
    out_md = tmp_path / "ops" / "rv.md"
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
    text = written_md.read_text()
    assert "BTC−ETH relative-value residual dual-print" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False
