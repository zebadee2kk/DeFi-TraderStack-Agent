"""Point-in-time tape guards (#141): close_at, look-ahead, prints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.polymarket.cities import CITY_CATALOG
from traderstack.polymarket.eval import DEFAULT_CITY_SLUGS, prints_independent, run_weather_eval
from traderstack.polymarket.models import TemperatureContract
from traderstack.polymarket.tape import (
    PolymarketWeatherResolvedTape,
    PolymarketWeatherTape,
    ResolvedTapeRow,
    TapeObservation,
    TapeStatus,
    lead_hours,
    local_close_at,
    render_tape_status_markdown,
    select_decision_rows,
    split_prints_by_month,
    to_resolved_weather_rows,
)

MIAMI = CITY_CATALOG["miami"]
HONOLULU = CITY_CATALOG["honolulu"]


def _observation(**overrides: object) -> TapeObservation:
    event_date = overrides.pop("event_date", date(2026, 9, 14))
    assert isinstance(event_date, date)
    close_at = local_close_at(MIAMI, event_date)
    observed_at = overrides.pop("observed_at", close_at - timedelta(hours=6))
    assert isinstance(observed_at, datetime)
    payload: dict[str, object] = {
        "event_id": "evt-1",
        "market_id": "mkt-1",
        "condition_id": "0xabc",
        "city_slug": "miami",
        "station_icao": "KMIA",
        "event_date": event_date,
        "contract": TemperatureContract.BUCKET,
        "bucket_low_f": 88.0,
        "bucket_high_f": 89.0,
        "yes_token_id": "tok-yes",
        "no_token_id": "tok-no",
        "observed_at": observed_at,
        "clob_mid": 0.32,
        "best_bid": 0.30,
        "best_ask": 0.34,
        "half_spread": 0.02,
        "forecast_high_f": 88.6,
        "forecast_issued_at": observed_at,
        "close_at": close_at,
        "lead_hours": lead_hours(observed_at, close_at),
        "question": "Will the highest temperature in Miami be between 88-89°F on September 14?",
    }
    payload.update(overrides)
    return TapeObservation(**payload)  # type: ignore[arg-type]


def _resolved(observation: TapeObservation, **overrides: object) -> ResolvedTapeRow:
    payload: dict[str, object] = {
        **observation.model_dump(),
        "official_high_f": 89.0,
        "station_id": "KMIA",
        "resolution_source": "iem_asos",
        "crosscheck_high_f": 89.0,
        "crosscheck_source": "ncei_ghcn_daily",
        "resolution_mismatch": 0.0,
        "resolved_at": observation.close_at + timedelta(hours=24),
    }
    payload.update(overrides)
    return ResolvedTapeRow(**payload)  # type: ignore[arg-type]


def test_local_close_at_is_end_of_local_day_not_gamma_end_date() -> None:
    # Gamma's nominal endDate for the 2026-09-14 event is 2026-09-14T12:00Z,
    # while the market keeps accepting orders through the local day.
    assert local_close_at(MIAMI, date(2026, 9, 14)) == datetime(2026, 9, 15, 4, tzinfo=UTC)
    assert local_close_at(HONOLULU, date(2026, 9, 14)) == datetime(2026, 9, 15, 10, tzinfo=UTC)
    assert local_close_at(MIAMI, date(2026, 9, 14)) > datetime(2026, 9, 14, 12, tzinfo=UTC)


def test_tape_round_trip_keeps_rows_paper_only(tmp_path: Path) -> None:
    tape = PolymarketWeatherTape(tmp_path / "tape.jsonl")
    observation = _observation()
    tape.append_sync(observation)
    tape.append_sync(observation.model_copy(update={"market_id": "mkt-2"}))
    rows = tape.read()
    assert [row.market_id for row in rows] == ["mkt-1", "mkt-2"]
    assert all(row.venue_submitted is False for row in rows)
    assert all(row.trading_mode == "paper" for row in rows)
    assert all(row.tape_kind == "live" for row in rows)


def test_tape_refuses_observations_at_or_after_close(tmp_path: Path) -> None:
    tape = PolymarketWeatherTape(tmp_path / "tape.jsonl")
    close_at = local_close_at(MIAMI, date(2026, 9, 14))
    with pytest.raises(RuntimeError, match="at or after close_at"):
        tape.append_sync(_observation(observed_at=close_at))
    with pytest.raises(RuntimeError, match="forecast issued at or after close_at"):
        tape.append_sync(_observation(forecast_issued_at=close_at + timedelta(minutes=1)))
    assert not (tmp_path / "tape.jsonl").exists()


def test_select_decision_rows_takes_latest_with_enough_lead() -> None:
    close_at = local_close_at(MIAMI, date(2026, 9, 14))
    early = _observation(observed_at=close_at - timedelta(hours=10))
    late = _observation(observed_at=close_at - timedelta(hours=2))
    early = early.model_copy(update={"lead_hours": lead_hours(early.observed_at, close_at)})
    late = late.model_copy(update={"lead_hours": lead_hours(late.observed_at, close_at)})
    assert select_decision_rows([early, late])[0].observed_at == late.observed_at
    chosen = select_decision_rows([early, late], min_lead_hours=6.0)
    assert [row.observed_at for row in chosen] == [early.observed_at]
    assert select_decision_rows([early, late], min_lead_hours=48.0) == ()


def test_lookahead_rows_are_dropped_not_scored() -> None:
    good = _resolved(_observation())
    late_observation = _resolved(
        _observation(),
        market_id="mkt-late-obs",
        observed_at=good.close_at + timedelta(minutes=1),
    )
    late_forecast = _resolved(
        _observation(),
        market_id="mkt-late-fc",
        forecast_issued_at=good.close_at,
    )
    unmatched = _resolved(_observation(), market_id="mkt-unmatched", station_id=" ")
    rows, drops = to_resolved_weather_rows(
        [good, late_observation, late_forecast, unmatched], print_id="2026-09"
    )
    assert [row.market_id for row in rows] == ["mkt-1"]
    assert drops == {
        "lookahead_observation": 1,
        "lookahead_forecast": 1,
        "station_unmatched": 1,
    }


def test_monthly_prints_are_non_overlapping_and_cannot_promote() -> None:
    september = _resolved(_observation(event_date=date(2026, 9, 14)))
    october = _resolved(
        _observation(event_date=date(2026, 10, 14)),
        market_id="mkt-oct",
    )
    prints = split_prints_by_month([september, october])
    assert sorted(prints) == ["2026-09", "2026-10"]
    independent, reason = prints_independent(prints["2026-09"], prints["2026-10"])
    assert independent is True
    assert reason == "non_overlapping_event_dates"

    report = run_weather_eval(
        prints,
        min_edge=0.08,
        fee_haircut=0.02,
        sigma_f=2.5,
        allowlist=DEFAULT_CITY_SLUGS,
    )
    # Two one-row prints cannot clear MIN_ELIGIBLE_PER_PRINT, and the CLI can
    # never promote regardless.
    assert report.can_promote is False
    assert sum(item.n_rows for item in report.prints) == 2


def test_resolved_rows_reach_the_evaluator_as_eligible_rows() -> None:
    rows, drops = to_resolved_weather_rows([_resolved(_observation())], print_id="2026-09")
    assert drops == {}
    report = run_weather_eval(
        {"2026-09": rows},
        min_edge=0.08,
        fee_haircut=0.02,
        sigma_f=2.5,
        allowlist=DEFAULT_CITY_SLUGS,
    )
    assert report.prints[0].n_rows == 1
    assert report.prints[0].n_eligible == 1
    assert report.print_kind == "single_print"


def test_resolved_tape_is_idempotent_on_market_id(tmp_path: Path) -> None:
    store = PolymarketWeatherResolvedTape(tmp_path / "resolved.jsonl")
    assert store.read() == ()
    assert store.resolved_market_ids() == set()
    store.append_sync(_resolved(_observation()))
    assert store.resolved_market_ids() == {"mkt-1"}


def test_empty_tape_status_renders_zero_rows_and_no_pnl() -> None:
    status = TapeStatus(
        generated_at=datetime(2026, 9, 15, tzinfo=UTC),
        tape_path="var/audit/polymarket_weather_tape.jsonl",
        resolved_path="var/audit/polymarket_weather_resolved.jsonl",
        fee_haircut=0.02,
        min_lead_hours=0.0,
        settle_lag_hours=24.0,
        station_tolerance_f=1.0,
    )
    markdown = render_tape_status_markdown(status)
    assert "| observations on tape | 0 |" in markdown
    # The only mention of PnL is the disclaimer that none is computed.
    assert "never computes PnL" in markdown
    assert markdown.lower().count("pnl") == 1
    assert "$" not in markdown
    assert "PAPER_PROMOTE_POLYMARKET_WEATHER" in markdown
