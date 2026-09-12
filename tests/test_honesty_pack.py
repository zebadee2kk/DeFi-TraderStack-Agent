from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.daily_candidates import default_expanded_harder_gates_candidates
from traderstack.research.honesty_pack import (
    DEFAULT_CANDIDATE_ID,
    DEFAULT_PROMOTE_FLAG,
    PAPER_DD_CEILING,
    SeriesHonestyRow,
    honesty_md_name,
    remaining_gaps,
    render_honesty_pack_markdown,
    run_honesty_pack,
)
from traderstack.research.honesty_pack_cli import build_parser, run
from traderstack.research.yahoo_daily import YAHOO_PERIOD1_ISO, YAHOO_PERIOD1_UNIX


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


def _adx15_catalog() -> tuple:
    return tuple(
        item
        for item in default_expanded_harder_gates_candidates()
        if item.candidate_id in {"ema_9_21", "ema_9_21_adx15"}
    )


def _pack(histories: dict[str, tuple[Candle, ...]], **overrides: object):
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "candidate_id": DEFAULT_CANDIDATE_ID,
        "candidates": _adx15_catalog(),
    }
    kwargs.update(overrides)
    return run_honesty_pack(histories, **kwargs)  # type: ignore[arg-type]


def _yahoo_row(**overrides: object) -> SeriesHonestyRow:
    values: dict[str, object] = {
        "asset": "BTC-USD",
        "source": "yahoo (non-Kraken)",
        "bars": 100,
        "wf_total": 0.05,
        "holdout_excess": -0.09,
        "wf_total_sign": "+",
        "holdout_excess_sign": "−",
    }
    values.update(overrides)
    return SeriesHonestyRow(**values)  # type: ignore[arg-type]


def _kraken_dd(**overrides: object) -> SeriesHonestyRow:
    values: dict[str, object] = {
        "asset": "BTC/USD",
        "source": "kraken",
        "bars": 720,
        "wf_max_drawdown": 0.20,
        "blows_past_dd_ceiling": False,
    }
    values.update(overrides)
    return SeriesHonestyRow(**values)  # type: ignore[arg-type]


def test_promote_defaults_stay_false() -> None:
    cfg = settings()
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.paper_promote_ema_9_21_adx15_active is False
    assert cfg.paper_promote_ema_9_21 is False
    assert PAPER_DD_CEILING == 0.30
    assert DEFAULT_PROMOTE_FLAG == "PAPER_PROMOTE_EMA_9_21_ADX15"
    assert honesty_md_name(DEFAULT_CANDIDATE_ID) == "ema-9-21-adx15-honesty.md"


def test_remaining_gaps_include_negative_yahoo_and_sol_dd() -> None:
    gaps = remaining_gaps(
        candidate_id=DEFAULT_CANDIDATE_ID,
        promote_flag=DEFAULT_PROMOTE_FLAG,
        still_combined_pass=True,
        still_combined_top1=True,
        yahoo_rows=[
            _yahoo_row(asset="BTC-USD", holdout_excess=-0.0928, wf_total=0.10),
            _yahoo_row(asset="ETH-USD", holdout_excess=0.5, wf_total=-0.01),
        ],
        kraken_dd_rows=[
            _kraken_dd(asset="BTC/USD", wf_max_drawdown=0.18, blows_past_dd_ceiling=False),
            _kraken_dd(asset="ETH/USD", wf_max_drawdown=0.22, blows_past_dd_ceiling=False),
            _kraken_dd(asset="SOL/USD", wf_max_drawdown=0.51, blows_past_dd_ceiling=True),
        ],
        paper_dd_ceiling=0.30,
        yahoo_fetch_failed=False,
    )
    text = " ".join(gaps)
    assert "Yahoo `BTC-USD` holdout excess is -9.28%" in text
    assert "Yahoo `ETH-USD` walk-forward total is -1.00%" in text
    assert "SOL/USD" in text and "51.00%" in text
    assert "mvp_assets" in text
    assert "`PAPER_PROMOTE_EMA_9_21_ADX15` stays default **false**" in text
    assert "Single 720-bar" in text


def test_remaining_gaps_empty_yahoo_is_a_gap_and_success() -> None:
    gaps = remaining_gaps(
        candidate_id=DEFAULT_CANDIDATE_ID,
        promote_flag=DEFAULT_PROMOTE_FLAG,
        still_combined_pass=False,
        still_combined_top1=False,
        yahoo_rows=[],
        kraken_dd_rows=[],
        paper_dd_ceiling=0.30,
        yahoo_fetch_failed=True,
    )
    text = " ".join(gaps)
    assert "Yahoo Finance A/B missing" in text
    assert "no longer clears combined" in text


def test_honesty_pack_on_synthetic_keeps_flag_false() -> None:
    report = _pack(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD"),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD"),
            "SOL/USD@1d": downtrend(720, symbol="SOL/USD"),
        }
    )
    assert report.candidate_id == DEFAULT_CANDIDATE_ID
    assert report.promote_flag == DEFAULT_PROMOTE_FLAG
    assert report.keep_flag_false is True
    assert report.paper_dd_ceiling == 0.30
    assert report.yahoo_period1_unix == YAHOO_PERIOD1_UNIX
    assert report.yahoo_period1_iso == YAHOO_PERIOD1_ISO
    rendered = render_honesty_pack_markdown(report)
    assert "## 1. Kraken combined harder-gates reprint" in rendered
    assert "## 2. Yahoo Finance A/B (non-Kraken; cannot promote)" in rendered
    assert "## 3. Walk-forward maxDD vs paper DD ceiling" in rendered
    assert "## 4. Multi-window (gate B) for this id" in rendered
    assert "## Operator recommendation" in rendered
    assert "Keep `PAPER_PROMOTE_EMA_9_21_ADX15=false`" in rendered
    assert "Cannot promote" in rendered
    assert settings().paper_promote_ema_9_21_adx15 is False


def test_yahoo_rows_are_labeled_and_do_not_enter_ranking() -> None:
    kraken_btc = downtrend(720, symbol="BTC/USD")
    kraken_eth = downtrend(720, symbol="ETH/USD")
    kraken_sol = downtrend(720, symbol="SOL/USD")
    yahoo_btc = make_candles([10.0 + 0.4 * index for index in range(400)], symbol="BTC-USD")
    yahoo_eth = make_candles([8.0 + 0.3 * index for index in range(400)], symbol="ETH-USD")
    without = _pack(
        {
            "BTC/USD@1d": kraken_btc,
            "ETH/USD@1d": kraken_eth,
            "SOL/USD@1d": kraken_sol,
        }
    )
    with_yahoo = _pack(
        {
            "BTC/USD@1d": kraken_btc,
            "ETH/USD@1d": kraken_eth,
            "SOL/USD@1d": kraken_sol,
            "BTC-USD@1d": yahoo_btc,
            "ETH-USD@1d": yahoo_eth,
        }
    )
    assert without.still_combined_pass == with_yahoo.still_combined_pass
    assert without.still_combined_top1 == with_yahoo.still_combined_top1
    assert without.mean_holdout_excess == pytest.approx(with_yahoo.mean_holdout_excess or 0.0)
    assert without.yahoo_rows == []
    assert {row.asset for row in with_yahoo.yahoo_rows} == {"BTC-USD", "ETH-USD"}
    assert all(row.source == "yahoo (non-Kraken)" for row in with_yahoo.yahoo_rows)
    assert all(row.wf_total_sign in {"+", "−", "0", "n/a"} for row in with_yahoo.yahoo_rows)
    assert all(row.wf_excess_sign in {"+", "−", "0", "n/a"} for row in with_yahoo.yahoo_rows)
    assert all(row.holdout_excess_sign in {"+", "−", "0", "n/a"} for row in with_yahoo.yahoo_rows)
    rendered = render_honesty_pack_markdown(with_yahoo)
    assert "period1=1410912000" in rendered
    assert "Cannot promote" in rendered
    assert "BTC-USD" in rendered
    assert "ETH-USD" in rendered


def test_unknown_candidate_fails_closed() -> None:
    with pytest.raises(ValueError, match="not in the"):
        _pack(
            {
                "BTC/USD@1d": downtrend(240, symbol="BTC/USD"),
                "ETH/USD@1d": downtrend(240, symbol="ETH/USD"),
            },
            candidate_id="not_a_real_strategy",
        )


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-yahoo"])
    assert args.candidate == DEFAULT_CANDIDATE_ID
    assert args.output_md.name == "ema-9-21-adx15-honesty.md"
    assert args.catalog == "expanded"

    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    write_candles(btc, downtrend(720, symbol="BTC/USD"))
    write_candles(eth, downtrend(720, symbol="ETH/USD"))
    out_json = tmp_path / "ops" / "honesty.json"
    out_md = tmp_path / "ops" / "honesty.md"
    parsed = build_parser().parse_args(
        [
            "--candles",
            str(btc),
            "--candles",
            str(eth),
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
            "--catalog",
            "expanded",
            "--candidate",
            DEFAULT_CANDIDATE_ID,
            "--no-yahoo",
        ]
    )
    written_json, written_md = run(parsed, settings=settings(), candidates=_adx15_catalog())
    assert written_json.is_file()
    assert written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["candidate_id"] == DEFAULT_CANDIDATE_ID
    assert payload["keep_flag_false"] is True
    assert payload["promote_flag"] == DEFAULT_PROMOTE_FLAG
    assert payload["paper_dd_ceiling"] == 0.30
    assert "honesty" in payload
    assert "remaining_gaps" in payload
    text = written_md.read_text()
    assert "Keep `PAPER_PROMOTE_EMA_9_21_ADX15=false`" in text
    assert settings().paper_promote_ema_9_21_adx15 is False
