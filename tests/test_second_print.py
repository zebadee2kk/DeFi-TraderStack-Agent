from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.binance_spot import (
    BINANCE_COM_BASE,
    BINANCE_SOURCE_RESTRICTED,
    BINANCE_SOURCE_US,
    download_binance_spot_daily,
    parse_binance_kline,
    parse_binance_klines,
)
from traderstack.research.second_print import (
    CAN_ENTER_PROMOTION_AVERAGE,
    DEFAULT_CANDIDATE_ID,
    DEFAULT_PROMOTE_FLAG,
    DOCUMENTED_PRIMARY_FIRST_ISO,
    MULTI_VENUE_BAR_PREREGISTERED,
    SECOND_PRINT_BARS,
    SECOND_PRINT_CANDIDATE_IDS,
    holdout_blind_prefix,
    primary_first_opened_at,
    remap_binance_for_scoring,
    render_second_print_markdown,
    run_second_print,
    slice_ending_before,
)
from traderstack.research.second_print_cli import build_parser, run


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


def _print(
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
        "candidate_id": DEFAULT_CANDIDATE_ID,
        "candidate_ids": SECOND_PRINT_CANDIDATE_IDS,
    }
    kwargs.update(overrides)
    return run_second_print(kraken, binance, **kwargs)  # type: ignore[arg-type]


def test_promote_defaults_and_frozen_rules_stay_closed() -> None:
    cfg = settings()
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.paper_promote_ema_9_21 is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert MULTI_VENUE_BAR_PREREGISTERED is False
    assert DEFAULT_PROMOTE_FLAG == "PAPER_PROMOTE_EMA_9_21_ADX15"
    assert DEFAULT_CANDIDATE_ID in SECOND_PRINT_CANDIDATE_IDS
    assert SECOND_PRINT_CANDIDATE_IDS == (
        "ema_9_21_adx15",
        "ema_9_21_adx18",
        "ema_12_26_adx18",
        "ema_12_26_adx20",
    )
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"


def test_holdout_blind_prefix_drops_last_20_percent() -> None:
    candles = downtrend(720, symbol="BTC/USD")
    prefix = holdout_blind_prefix(candles, holdout_fraction=0.20)
    assert len(prefix) == 576
    assert prefix[0].opened_at == candles[0].opened_at
    assert prefix[-1].opened_at == candles[575].opened_at
    assert prefix[-1].opened_at < candles[576].opened_at


def test_slice_ending_before_has_no_overlap() -> None:
    start = datetime(2022, 10, 2, tzinfo=UTC)
    candles = downtrend(800, symbol="BTCUSDT", start=start)
    cutoff = datetime(2024, 9, 22, tzinfo=UTC)
    sliced = slice_ending_before(candles, before=cutoff, bars=720)
    assert sliced
    assert sliced[-1].opened_at < cutoff
    assert len(sliced) == 720
    assert all(item.opened_at < cutoff for item in sliced)


def test_remap_binance_symbols_for_scoring_only() -> None:
    btc = downtrend(10, symbol="BTCUSDT")
    eth = downtrend(10, symbol="ETHUSDT")
    remapped = remap_binance_for_scoring({"BTCUSDT@1d": btc, "ETHUSDT@1d": eth})
    assert set(remapped) == {"BTC/USD@1d", "ETH/USD@1d"}
    assert remapped["BTC/USD@1d"][0].symbol == "BTC/USD"
    assert remapped["ETH/USD@1d"][0].symbol == "ETH/USD"
    assert btc[0].symbol == "BTCUSDT"


def test_primary_first_prefers_this_run_kraken() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    first, source = primary_first_opened_at(
        {"BTC/USD@1d": downtrend(20, symbol="BTC/USD", start=start)}
    )
    assert first == start
    assert source == "this_run_kraken_btc_first_bar"
    fallback, fallback_source = primary_first_opened_at({})
    assert fallback.isoformat() == DOCUMENTED_PRIMARY_FIRST_ISO
    assert fallback_source == "documented_primary_first_iso"


def test_kraken_second_720_unavailable_on_public_window() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _print(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=start),
        },
        {},
    )
    assert report.kraken_second_720.available is False
    assert report.kraken_second_720.fail_closed_reason is not None
    assert "cannot retrieve" in report.kraken_second_720.fail_closed_reason
    assert report.kraken_prefix.available is True
    assert report.kraken_prefix.bars_btc == 576
    assert report.kraken_prefix.overlaps_primary_window is True
    assert report.kraken_prefix.overlaps_primary_holdout is False
    assert report.keep_flag_false is True
    assert report.can_enter_promotion_average is False


def test_empty_binance_is_success_and_cannot_promote() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _print(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=start),
        },
        {},
    )
    assert report.binance_print_fail_closed is True
    assert report.binance_combined_pass is False
    assert report.target_binance is None
    assert report.keep_flag_false is True
    assert report.can_enter_promotion_average is False
    rendered = render_second_print_markdown(report)
    assert "Keep `PAPER_PROMOTE_EMA_9_21_ADX15=false`" in rendered
    assert "cannot enter the promotion average" in rendered.lower() or "Cannot enter" in rendered
    assert "UNAVAILABLE" in rendered
    assert settings().paper_promote_ema_9_21_adx15 is False


def test_binance_older_slice_is_scored_and_still_cannot_promote() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    report = _print(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=primary),
        },
        {
            "BTCUSDT@1d": downtrend(720, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(720, symbol="ETHUSDT", start=older),
        },
        binance_source="binance_us_spot",
    )
    assert report.binance_slice.available is True
    assert report.binance_slice.overlaps_primary_window is False
    assert report.binance_slice.overlaps_primary_holdout is False
    assert report.binance_slice.bars_btc == 720
    assert report.target_binance is not None
    assert report.target_binance.can_promote is False
    assert report.keep_flag_false is True
    assert report.can_enter_promotion_average is False
    assert report.multi_venue_bar_preregistered is False
    # A short-capable EMA can combined-pass a synthetic downtrend. That
    # still cannot promote — the point of this test.
    assert report.target_binance.can_promote is False
    rendered = render_second_print_markdown(report)
    assert "### 2c. `ema_9_21_adx15` vs harder gates" in rendered
    assert "can promote | **no**" in rendered
    assert "Binance.US" in rendered
    assert "cannot enter the promotion average" in rendered.lower() or "Cannot enter" in rendered
    assert all(row.can_promote is False for row in report.binance_rows)
    assert {row.candidate_id for row in report.binance_rows} == set(SECOND_PRINT_CANDIDATE_IDS)
    if report.binance_combined_pass:
        assert "report-only" in report.honesty
        assert report.keep_flag_false is True


def test_short_binance_slice_fails_closed() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2023, 1, 1, tzinfo=UTC)
    report = _print(
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
    assert report.binance_print_fail_closed is True
    assert "shorter than 720" in (report.binance_slice.fail_closed_reason or "")
    assert report.target_binance is None
    assert report.keep_flag_false is True


def test_prefix_gate_b_fails_closed_on_short_series() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    report = _print(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=primary),
        }
    )
    assert report.target_prefix is not None
    assert report.target_prefix.gate_b_pass is False
    assert any("insufficient_bars" in reason for reason in report.target_prefix.gate_b_reasons)
    assert report.target_prefix.combined is False
    assert report.target_prefix.can_promote is False


def test_unknown_candidate_fails_closed() -> None:
    with pytest.raises(ValueError, match="not in the second-print"):
        _print(
            {
                "BTC/USD@1d": downtrend(240, symbol="BTC/USD"),
                "ETH/USD@1d": downtrend(240, symbol="ETH/USD"),
            },
            candidate_id="not_a_real_strategy",
        )


def test_parse_binance_kline_and_drop_today() -> None:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    rows = [
        [
            int(yesterday.timestamp() * 1000),
            "100",
            "101",
            "99",
            "100.5",
            "12",
        ],
        [
            int(today.timestamp() * 1000),
            "100.5",
            "102",
            "100",
            "101",
            "8",
        ],
    ]
    candles = parse_binance_klines(rows, symbol="BTCUSDT")
    assert len(candles) == 1
    assert candles[0].symbol == "BTCUSDT"
    assert candles[0].opened_at == yesterday
    parsed = parse_binance_kline(rows[0], symbol="ethusdt")
    assert parsed.symbol == "ETHUSDT"


@pytest.mark.asyncio
async def test_binance_com_451_is_not_confirmation() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(451, json={"msg": "restricted"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url=BINANCE_COM_BASE, transport=transport) as client:
        candles, source, notes = await download_binance_spot_daily(
            "BTCUSDT", client=client, bases=(BINANCE_COM_BASE,)
        )
    assert candles == ()
    assert source == BINANCE_SOURCE_RESTRICTED
    assert any("451" in note for note in notes)


@pytest.mark.asyncio
async def test_binance_us_klines_parse() -> None:
    start = datetime(2022, 10, 3, tzinfo=UTC)
    rows = [
        [
            int((start + timedelta(days=index)).timestamp() * 1000),
            "100",
            "101",
            "99",
            "100.5",
            "1",
        ]
        for index in range(5)
    ]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(base_url="https://api.binance.us", transport=transport) as client:
        candles, source, notes = await download_binance_spot_daily(
            "BTCUSDT",
            client=client,
            max_candles=720,
            end_before=datetime(2024, 9, 22, tzinfo=UTC),
        )
    assert source == BINANCE_SOURCE_US
    assert len(candles) == 5
    assert candles[0].symbol == "BTCUSDT"
    assert not notes or all("skipped" not in note for note in notes)


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.candidate == DEFAULT_CANDIDATE_ID
    assert args.output_md.name == "ema-9-21-adx15-second-print.md"

    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    btc_usdt = tmp_path / "btcusdt.json"
    eth_usdt = tmp_path / "ethusdt.json"
    write_candles(btc, downtrend(720, symbol="BTC/USD", start=primary))
    write_candles(eth, downtrend(720, symbol="ETH/USD", start=primary))
    write_candles(btc_usdt, downtrend(720, symbol="BTCUSDT", start=older))
    write_candles(eth_usdt, downtrend(720, symbol="ETHUSDT", start=older))
    out_json = tmp_path / "ops" / "second.json"
    out_md = tmp_path / "ops" / "second.md"
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
    written_json, written_md = run(parsed, settings=settings())
    assert written_json.is_file()
    assert written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["candidate_id"] == DEFAULT_CANDIDATE_ID
    assert payload["keep_flag_false"] is True
    assert payload["can_enter_promotion_average"] is False
    assert payload["multi_venue_bar_preregistered"] is False
    assert payload["promote_flag"] == DEFAULT_PROMOTE_FLAG
    assert payload["keep_flag_false"] is True
    assert payload["can_enter_promotion_average"] is False
    text = written_md.read_text()
    assert "Keep `PAPER_PROMOTE_EMA_9_21_ADX15=false`" in text
    assert "second print" in text.lower()
    assert "can promote | **no**" in text
    assert settings().paper_promote_ema_9_21_adx15 is False
    assert SECOND_PRINT_BARS == 720


def test_second_print_surfaces_the_selection_evidence_block() -> None:
    """#135 reached this CLI: the evidence was computed but discarded.

    `_score_histories` already ran it through `run_harder_gates`; it just
    dropped the report and returned rows. These assertions pin that the
    catalog block and the per-row scalars now reach `SecondPrintReport` and
    its markdown, so the gap cannot silently reopen.
    """

    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    report = _print(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=primary),
        },
        {
            "BTCUSDT@1d": downtrend(720, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(720, symbol="ETHUSDT", start=older),
        },
        binance_source="binance_us_spot",
    )

    evidence = report.selection_evidence
    assert evidence is not None, "the Kraken prefix slice must carry the evidence block"
    assert evidence.trial_count == len(SECOND_PRINT_CANDIDATE_IDS)
    assert evidence.print_kind is not None

    # Every prefix row carries the denormalised scalars, same spelling as
    # DualPrintRow so the two reports read as one vocabulary.
    assert report.kraken_prefix_rows
    for row in report.kraken_prefix_rows:
        assert row.print_kind == evidence.print_kind.value
        assert row.trial_count == evidence.trial_count
        assert isinstance(row.evidence_gate_pass, bool)

    # The evidence gate is additive: it never promotes anything here.
    assert all(row.can_promote is False for row in report.kraken_prefix_rows)

    rendered = render_second_print_markdown(report)
    assert "## Selection evidence (#135)" in rendered
    assert "**Print kind:**" in rendered
    assert "**PBO (CSCV):**" in rendered
    assert "**Trials scored (K):**" in rendered
