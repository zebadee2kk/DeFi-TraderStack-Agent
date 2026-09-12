from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from traderstack.config import Settings
from traderstack.polymarket.cities import DEFAULT_CITY_SLUGS
from traderstack.polymarket.eval import (
    CAN_ENTER_PROMOTION_AVERAGE,
    CRYPTO_OVERLAY_ID,
    DEFAULT_PROMOTE_FLAG,
    MIN_ELIGIBLE_PER_PRINT,
    MIN_TRADES_PER_PRINT,
    MULTI_PRINT_BAR_PREREGISTERED,
    PRINT_DUAL,
    PRINT_SINGLE,
    DailyClose,
    ResolvedWeatherRow,
    WeatherEvalReport,
    conservative_entry,
    empty_live_report,
    print_clears_calculator,
    prints_independent,
    realized_pnl,
    render_weather_eval_markdown,
    run_weather_eval,
    yes_won,
)
from traderstack.polymarket.eval_cli import build_parser, run
from traderstack.polymarket.models import ContractSide, TemperatureContract

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "polymarket"


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "trading_mode": "paper",
    }
    values.update(overrides)
    return Settings(**values)


def _row(**overrides: object) -> ResolvedWeatherRow:
    values: dict[str, object] = {
        "market_id": "mkt-1",
        "city_slug": "miami",
        "event_date": date(2024, 6, 1),
        "contract": TemperatureContract.THRESHOLD_OR_HIGHER,
        "threshold_f": 90.0,
        "forecast_high_f": 94.0,
        "forecast_source": "open_meteo",
        "forecast_issued_at": datetime(2024, 6, 1, 12, tzinfo=UTC),
        "market_mid": 0.55,
        "half_spread": 0.02,
        "official_high_f": 95.0,
        "station_id": "KMIA",
        "resolution_source": "fixture_ncei_asos",
        "close_at": datetime(2024, 6, 2, 10, tzinfo=UTC),
        "print_id": "print_a",
    }
    values.update(overrides)
    return ResolvedWeatherRow.model_validate(values)


def _eval(
    prints: dict[str, tuple[ResolvedWeatherRow, ...]], **overrides: object
) -> WeatherEvalReport:
    kwargs: dict[str, object] = {
        "min_edge": 0.08,
        "fee_haircut": 0.02,
        "sigma_f": 2.5,
    }
    kwargs.update(overrides)
    return run_weather_eval(prints, **kwargs)  # type: ignore[arg-type]


def test_rules_are_frozen_and_honest() -> None:
    assert MULTI_PRINT_BAR_PREREGISTERED is True
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert DEFAULT_PROMOTE_FLAG == "PAPER_PROMOTE_POLYMARKET_WEATHER"
    assert DEFAULT_PROMOTE_FLAG not in Settings.model_fields
    assert MIN_ELIGIBLE_PER_PRINT == 20
    assert MIN_TRADES_PER_PRINT == 8
    assert CRYPTO_OVERLAY_ID == "polymarket_weather_vs_btc_daily"
    assert set(DEFAULT_CITY_SLUGS) == {
        "honolulu",
        "san_diego",
        "miami",
        "phoenix",
        "singapore",
        "lisbon",
    }


def test_yes_won_from_official_high() -> None:
    assert yes_won(_row(official_high_f=90.0)) is True
    assert yes_won(_row(official_high_f=89.0)) is False
    bucket = _row(
        contract=TemperatureContract.BUCKET,
        threshold_f=None,
        bucket_low_f=86.0,
        bucket_high_f=87.0,
        official_high_f=86.0,
    )
    assert yes_won(bucket) is True
    assert yes_won(bucket.model_copy(update={"official_high_f": 88.0})) is False


def test_conservative_entry_is_worse_than_mid() -> None:
    yes = conservative_entry(ContractSide.YES, 0.50, 0.02)
    no = conservative_entry(ContractSide.NO, 0.50, 0.02)
    assert yes == pytest.approx(0.52)
    assert no == pytest.approx(0.52)
    assert realized_pnl(0.52, won=True, fee_haircut=0.02) < realized_pnl(
        0.50, won=True, fee_haircut=0.02
    )


def test_station_lookahead_and_city_filters() -> None:
    report = _eval(
        {
            "print_a": (
                _row(station_id="", market_id="no-station"),
                _row(
                    market_id="lookahead",
                    forecast_issued_at=datetime(2024, 6, 3, tzinfo=UTC),
                ),
                _row(market_id="nyc", city_slug="new_york"),
                _row(market_id="ok"),
            )
        }
    )
    metrics = report.prints[0]
    assert metrics.n_station_dropped == 1
    assert metrics.n_lookahead_dropped == 1
    assert metrics.n_city_blocked == 1
    assert metrics.n_eligible == 1
    assert report.can_promote is False
    assert report.print_kind == PRINT_SINGLE


def test_single_print_cannot_promote_even_with_positive_excess() -> None:
    winner = _row(market_mid=0.20, forecast_high_f=98.0, official_high_f=99.0)
    report = _eval({"only": (winner,)})
    assert report.prints[0].treatment_excess_vs_hold > 0
    assert report.print_kind == PRINT_SINGLE
    assert report.independent is False
    assert print_clears_calculator(report.prints[0]) is False
    assert report.can_promote is False
    assert report.keep_flag_false is True


def test_dual_print_small_n_cannot_promote() -> None:
    a = tuple(
        _row(
            market_id=f"a-{index}",
            event_date=date(2024, 6, index + 1),
            forecast_issued_at=datetime(2024, 6, index + 1, 12, tzinfo=UTC),
            close_at=datetime(2024, 6, index + 2, 10, tzinfo=UTC),
        )
        for index in range(3)
    )
    b = tuple(
        _row(
            market_id=f"b-{index}",
            event_date=date(2025, 1, index + 1),
            forecast_issued_at=datetime(2025, 1, index + 1, 12, tzinfo=UTC),
            close_at=datetime(2025, 1, index + 2, 10, tzinfo=UTC),
            resolution_source="fixture_second_season",
            print_id="print_b",
        )
        for index in range(3)
    )
    report = _eval({"print_a": a, "print_b": b})
    assert report.print_kind == PRINT_DUAL
    assert report.independent is True
    assert report.independence_reason == "non_overlapping_event_dates"
    assert all(
        item.fail_closed_reason in {"below_min_eligible", "below_min_trades"}
        for item in report.prints
    )
    assert all(not print_clears_calculator(item) for item in report.prints)
    assert report.can_promote is False


def test_overlapping_same_source_is_not_independent() -> None:
    row_a = _row()
    row_b = _row(market_id="copy", print_id="print_b")
    assert prints_independent((row_a,), (row_b,)) == (
        False,
        "overlapping_dates_same_or_missing_resolution_source",
    )
    other = row_b.model_copy(update={"resolution_source": "ncei_second"})
    assert prints_independent((row_a,), (other,))[0] is True


def test_midfill_is_reported_and_cannot_be_primary() -> None:
    winner = _row(market_mid=0.20, forecast_high_f=98.0, official_high_f=99.0)
    report = _eval({"only": (winner,)})
    metrics = report.prints[0]
    assert metrics.used_mid_fill_as_primary is False
    assert metrics.midfill_treatment_pnl > metrics.treatment_pnl
    assert "cannot promote" in render_weather_eval_markdown(report)


def test_committed_artifact_matches_empty_live_renderer() -> None:
    report = empty_live_report(
        min_edge=0.08,
        fee_haircut=0.02,
        sigma_f=2.5,
        extra_notes=["TRADING_MODE=paper; report-only; venue_submitted=false"],
    )
    committed = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "artifacts"
        / "strategy-search"
        / "polymarket-weather-eval.md"
    )
    assert render_weather_eval_markdown(report) == committed.read_text(encoding="utf-8")


def test_empty_live_cannot_promote() -> None:
    report = empty_live_report(min_edge=0.08, fee_haircut=0.02, sigma_f=2.5)
    assert report.print_kind == PRINT_SINGLE
    assert report.prints[0].n_eligible == 0
    assert report.prints[0].fail_closed_reason == "empty_print"
    assert report.can_promote is False
    assert report.crypto_overlay.status == "skipped"
    text = render_weather_eval_markdown(report)
    assert "No candidate is promoted" in text
    assert "PAPER_PROMOTE_*` false" in text
    assert "UNAVAILABLE" in text


def test_crypto_overlay_skipped_without_btc() -> None:
    report = _eval({"only": (_row(),)})
    assert report.crypto_overlay.status == "skipped"
    assert report.crypto_overlay.can_promote is False
    assert "not invented" in report.crypto_overlay.reason


def test_crypto_overlay_scores_but_cannot_promote() -> None:
    rows = (_row(event_date=date(2024, 6, 1), market_mid=0.20, forecast_high_f=98.0),)
    btc = (
        DailyClose(opened_at=datetime(2024, 6, 1, tzinfo=UTC), close=100.0),
        DailyClose(opened_at=datetime(2024, 6, 2, tzinfo=UTC), close=101.0),
    )
    report = _eval({"only": rows}, btc_daily=btc, crypto_fee_bps=10.0)
    assert report.crypto_overlay.status == "scored"
    assert report.crypto_overlay.n_aligned == 1
    assert report.crypto_overlay.pnl_after_fees is not None
    assert report.crypto_overlay.can_promote is False
    assert report.can_promote is False


def test_fixture_files_are_honest_and_non_promoting() -> None:
    print_a = json.loads((FIXTURES / "resolved_print_a.json").read_text())
    print_b = json.loads((FIXTURES / "resolved_print_b.json").read_text())
    from traderstack.polymarket.eval import load_resolved_rows

    report = _eval(
        {
            "resolved_print_a": load_resolved_rows(print_a, default_print_id="a"),
            "resolved_print_b": load_resolved_rows(print_b, default_print_id="b"),
        }
    )
    assert report.print_kind == PRINT_DUAL
    assert report.prints[0].n_city_blocked == 1
    assert report.prints[0].n_station_dropped == 1
    assert report.prints[0].n_lookahead_dropped == 1
    assert report.prints[0].n_eligible == 3
    assert report.prints[1].n_eligible == 3
    assert report.can_promote is False
    assert all(not print_clears_calculator(item) for item in report.prints)


def test_cli_empty_live_leaves_promote_flags_false(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_json = tmp_path / "eval.json"
    out_md = tmp_path / "eval.md"
    args = build_parser().parse_args(
        [
            "--empty-live",
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
        ]
    )
    cfg = settings()
    run(args, settings=cfg)
    out = capsys.readouterr().out
    assert "report-only" in out
    assert "can_promote=false" in out
    payload = json.loads(out_json.read_text())
    assert payload["can_promote"] is False
    assert payload["keep_flag_false"] is True
    assert payload["print_kind"] == PRINT_SINGLE
    assert cfg.paper_promote_searched_strategies is False
    assert cfg.paper_promote_ema_9_21 is False
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.trading_mode == "paper"
    assert "PAPER_PROMOTE_POLYMARKET_WEATHER" not in Settings.model_fields


def test_cli_resolved_fixtures(tmp_path: Path) -> None:
    out_json = tmp_path / "eval.json"
    out_md = tmp_path / "eval.md"
    args = build_parser().parse_args(
        [
            "--resolved",
            str(FIXTURES / "resolved_print_a.json"),
            "--resolved",
            str(FIXTURES / "resolved_print_b.json"),
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
        ]
    )
    run(args, settings=settings())
    payload = json.loads(out_json.read_text())
    assert payload["print_kind"] == PRINT_DUAL
    assert payload["can_promote"] is False
    assert payload["crypto_overlay"]["status"] == "skipped"
    text = out_md.read_text()
    assert "No candidate is promoted" in text
    assert "Crucix fail-closed-on-outage is **not** this change" in text


def test_cli_rejects_live_mode(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "--empty-live",
            "--output-json",
            str(tmp_path / "a.json"),
            "--output-md",
            str(tmp_path / "a.md"),
        ]
    )
    with pytest.raises(RuntimeError, match="TRADING_MODE=paper"):
        run(args, settings=settings(trading_mode="live"))


def test_check_config_mentions_eval_cli() -> None:
    from traderstack.cli_check import build_report

    report = build_report(settings())
    labels = [item.label for item in report.items]
    assert any("weather eval" in label.lower() for label in labels)
    item = next(item for item in report.items if "weather eval" in item.label.lower())
    assert "report-only" in item.value
    assert "dual" in (item.detail or "").lower() or "dual" in item.value.lower()
