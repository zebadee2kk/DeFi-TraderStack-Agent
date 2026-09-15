"""Collector CLI (#141): observations only, named skips, paper-only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from traderstack.config import Settings
from traderstack.polymarket.collect_cli import (
    PolymarketWeatherTapeCollector,
    _run,
    build_parser,
    load_fixtures,
)
from traderstack.polymarket.tape import PolymarketWeatherTape

FIXTURES = Path(__file__).parent / "fixtures" / "polymarket" / "tape"
# The committed Gamma capture is the 2026-09-17 Miami / Toronto event set.
NOW = datetime(2026, 9, 17, 14, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "trading_mode": "paper",
        "polymarket_weather_cities": "miami,toronto,honolulu",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _collector(tape_path: Path, **overrides: object) -> PolymarketWeatherTapeCollector:
    return PolymarketWeatherTapeCollector(
        settings=_settings(),
        tape=PolymarketWeatherTape(tape_path),
        fixtures=load_fixtures(FIXTURES),
        clock=lambda: NOW,
        **overrides,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_fixture_run_writes_paper_observations(tmp_path: Path) -> None:
    tape_path = tmp_path / "tape.jsonl"
    report = await _collector(tape_path).run_once()

    assert report.observed > 0
    rows = [json.loads(line) for line in tape_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == report.observed
    for row in rows:
        assert row["venue_submitted"] is False
        assert row["trading_mode"] == "paper"
        assert row["tape_kind"] == "live"
        assert row["city_slug"] == "miami"
        assert 0.0 <= row["clob_mid"] <= 1.0
        assert row["best_bid"] <= row["clob_mid"] <= row["best_ask"]
        # Point-in-time by construction.
        assert row["observed_at"] < row["close_at"]
        assert row["forecast_issued_at"] < row["close_at"]
        assert row["lead_hours"] > 0


@pytest.mark.asyncio
async def test_lowest_temperature_and_celsius_cities_are_named_skips(tmp_path: Path) -> None:
    report = await _collector(tmp_path / "tape.jsonl").run_once()

    # "Lowest temperature in Miami" is a different contract family.
    assert report.skipped["unparsed"] >= 2
    # Toronto resolves in whole °C; the bucket model is Fahrenheit-only.
    assert report.skipped["unit_unsupported"] >= 3
    assert report.observed + sum(report.skipped.values()) == report.markets_seen
    assert "observations" in report.render().lower()


@pytest.mark.asyncio
async def test_one_sided_and_empty_books_are_skipped(tmp_path: Path) -> None:
    report = await _collector(tmp_path / "tape.jsonl").run_once()
    # The committed book fixtures include one no-bid book and one empty book.
    assert report.skipped["book_one_sided"] == 2


@pytest.mark.asyncio
async def test_city_outside_the_allowlist_is_blocked_not_researched(tmp_path: Path) -> None:
    collector = PolymarketWeatherTapeCollector(
        settings=_settings(polymarket_weather_cities="honolulu"),
        tape=PolymarketWeatherTape(tmp_path / "tape.jsonl"),
        fixtures=load_fixtures(FIXTURES),
        clock=lambda: NOW,
    )
    report = await collector.run_once()
    assert report.observed == 0
    assert report.skipped["city_blocked"] > 0
    assert not (tmp_path / "tape.jsonl").exists()


@pytest.mark.asyncio
async def test_markets_past_their_local_close_are_skipped(tmp_path: Path) -> None:
    collector = _collector(tmp_path / "tape.jsonl")
    collector.clock = lambda: datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    report = await collector.run_once()
    assert report.observed == 0
    assert report.skipped["closed"] > 0


@pytest.mark.asyncio
async def test_live_trading_mode_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "live")
    args = build_parser().parse_args(
        ["--fixtures-dir", str(FIXTURES), "--tape-path", str(tmp_path / "tape.jsonl")]
    )
    with pytest.raises(RuntimeError, match="TRADING_MODE=paper"):
        await _run(args)
    assert not (tmp_path / "tape.jsonl").exists()
