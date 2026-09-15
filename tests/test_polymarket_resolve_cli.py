"""Resolver CLI (#141): settle lag, look-ahead, prints, honest empty report."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from traderstack.config import Settings
from traderstack.polymarket import eval_cli
from traderstack.polymarket.cities import CITY_CATALOG
from traderstack.polymarket.models import TemperatureContract
from traderstack.polymarket.resolve_cli import (
    COMMITTED_ARTIFACT,
    DEFAULT_OUTPUT_MD,
    build_parser,
    resolve_tape,
)
from traderstack.polymarket.stations import GhcnDailyClient, IemAsosClient
from traderstack.polymarket.tape import (
    PolymarketWeatherResolvedTape,
    PolymarketWeatherTape,
    TapeObservation,
    TapeStatus,
    lead_hours,
    local_close_at,
    render_tape_status_markdown,
    split_prints_by_month,
)

REPO = Path(__file__).resolve().parents[1]
MIAMI = CITY_CATALOG["miami"]


def _settings() -> Settings:
    return Settings(trading_mode="paper")  # type: ignore[arg-type]


def _observation(event_date: date, market_id: str, **overrides: object) -> TapeObservation:
    close_at = local_close_at(MIAMI, event_date)
    observed_at = overrides.pop("observed_at", close_at - timedelta(hours=5))
    assert isinstance(observed_at, datetime)
    payload: dict[str, object] = {
        "event_id": "evt",
        "market_id": market_id,
        "city_slug": "miami",
        "station_icao": "KMIA",
        "event_date": event_date,
        "contract": TemperatureContract.THRESHOLD_OR_LOWER,
        "threshold_f": 88.0,
        "yes_token_id": f"{market_id}-yes",
        "no_token_id": f"{market_id}-no",
        "observed_at": observed_at,
        "clob_mid": 0.40,
        "best_bid": 0.38,
        "best_ask": 0.42,
        "half_spread": 0.02,
        "forecast_high_f": 87.5,
        "forecast_issued_at": observed_at,
        "close_at": close_at,
        "lead_hours": lead_hours(observed_at, close_at),
        "question": f"Will the highest temperature in Miami be 88°F or below on {event_date}?",
    }
    payload.update(overrides)
    return TapeObservation(**payload)  # type: ignore[arg-type]


def _station_transport(iem_value: float, ghcn_value: float) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        day = request.url.params.get("day1")
        if request.url.path == "/cgi-bin/request/daily.py":
            stamp = (
                f"{request.url.params['year1']}-"
                f"{int(request.url.params['month1']):02d}-{int(day):02d}"
            )
            return httpx.Response(200, text=f"station,day,max_temp_f\nMIA,{stamp},{iem_value}\n")
        stamp = str(request.url.params["startDate"])
        return httpx.Response(
            200,
            json=[{"DATE": stamp, "STATION": "USW00012839", "TMAX": str(ghcn_value)}],
        )

    return httpx.MockTransport(handler)


async def _resolve(
    tmp_path: Path,
    observations: list[TapeObservation],
    *,
    now: datetime,
    iem_value: float = 87.0,
    ghcn_value: float = 87.0,
    settle_lag_hours: float = 24.0,
) -> tuple[TapeStatus, tuple]:
    tape = PolymarketWeatherTape(tmp_path / "tape.jsonl")
    for observation in observations:
        tape.append_sync(observation)
    resolved = PolymarketWeatherResolvedTape(tmp_path / "resolved.jsonl")
    transport = _station_transport(iem_value, ghcn_value)
    async with httpx.AsyncClient(base_url="https://example.invalid", transport=transport) as client:
        return await resolve_tape(
            _settings(),
            tape=tape,
            resolved_tape=resolved,
            iem=IemAsosClient(client=client),
            ghcn=GhcnDailyClient(client=client),
            settle_lag_hours=settle_lag_hours,
            min_lead_hours=0.0,
            station_tolerance_f=1.0,
            now=now,
        )


@pytest.mark.asyncio
async def test_only_markets_past_close_plus_settle_lag_resolve(tmp_path: Path) -> None:
    done = _observation(date(2026, 9, 10), "mkt-done")
    fresh = _observation(date(2026, 9, 14), "mkt-fresh")
    status, rows = await _resolve(
        tmp_path, [done, fresh], now=datetime(2026, 9, 14, 12, tzinfo=UTC)
    )
    assert [row.market_id for row in rows] == ["mkt-done"]
    assert status.per_stage["newly_resolved"] == 1
    assert status.per_stage["awaiting_close"] == 1
    assert status.decision_rows == 2
    assert status.per_city == {"miami": 2}


@pytest.mark.asyncio
async def test_resolution_is_idempotent_across_runs(tmp_path: Path) -> None:
    done = _observation(date(2026, 9, 10), "mkt-done")
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    await _resolve(tmp_path, [done], now=now)
    status, rows = await _resolve(tmp_path, [], now=now)
    # The tape is rewritten by the helper, but the resolved store is not.
    assert len(rows) == 1
    assert status.per_stage["newly_resolved"] == 0


@pytest.mark.asyncio
async def test_station_disagreement_drops_the_row(tmp_path: Path) -> None:
    done = _observation(date(2026, 9, 10), "mkt-done")
    status, rows = await _resolve(
        tmp_path,
        [done],
        now=datetime(2026, 9, 14, 12, tzinfo=UTC),
        iem_value=87.0,
        ghcn_value=92.0,
    )
    assert rows == ()
    assert any(key.startswith("station_unmatched") for key in status.drop_reasons)
    assert status.eligible_rows == 0


@pytest.mark.asyncio
async def test_emitted_prints_are_consumed_by_the_evaluator(tmp_path: Path) -> None:
    september = [_observation(date(2026, 9, 10), "mkt-sep")]
    october = [_observation(date(2026, 10, 10), "mkt-oct")]
    tape = PolymarketWeatherTape(tmp_path / "tape.jsonl")
    for observation in september + october:
        tape.append_sync(observation)
    resolved = PolymarketWeatherResolvedTape(tmp_path / "resolved.jsonl")
    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=_station_transport(87.0, 87.0)
    ) as client:
        status, rows = await resolve_tape(
            _settings(),
            tape=tape,
            resolved_tape=resolved,
            iem=IemAsosClient(client=client),
            ghcn=GhcnDailyClient(client=client),
            settle_lag_hours=24.0,
            min_lead_hours=0.0,
            station_tolerance_f=1.0,
            now=datetime(2026, 11, 1, tzinfo=UTC),
        )
    assert sorted(status.prints) == ["2026-09", "2026-10"]
    prints = split_prints_by_month(rows)
    print_path = tmp_path / "2026-09.json"
    print_path.write_text(
        json.dumps([row.model_dump(mode="json") for row in prints["2026-09"]], default=str),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        resolved=[print_path],
        empty_live=False,
        btc_daily=None,
        min_edge=None,
        fee_haircut=None,
        sigma_f=None,
        half_spread=None,
        holdout_fraction=0.20,
        cities="miami",
        output_json=tmp_path / "eval.json",
        output_md=tmp_path / "eval.md",
        stdout_md=False,
    )
    eval_cli.run(args, _settings())
    report = json.loads((tmp_path / "eval.json").read_text(encoding="utf-8"))
    assert report["print_kind"] == "single_print"
    assert report["can_promote"] is False
    assert report["prints"][0]["n_eligible"] == 1


@pytest.mark.asyncio
async def test_post_close_observation_is_never_resolved(tmp_path: Path) -> None:
    close_at = local_close_at(MIAMI, date(2026, 9, 10))
    tape_path = tmp_path / "tape.jsonl"
    tape = PolymarketWeatherTape(tape_path)
    # The tape writer itself refuses a post-close observation: a row that
    # would be look-ahead cannot even be recorded.
    with pytest.raises(RuntimeError):
        tape.append_sync(
            _observation(date(2026, 9, 10), "mkt-late", observed_at=close_at + timedelta(minutes=1))
        )
    assert not tape_path.exists()


def test_committed_artifact_matches_the_empty_tape_renderer() -> None:
    committed = (REPO / COMMITTED_ARTIFACT).read_text(encoding="utf-8")
    generated_at = datetime.fromisoformat(
        committed.split("Generated: ", 1)[1].split("\n", 1)[0].strip()
    )
    status = TapeStatus(
        generated_at=generated_at,
        tape_path="var/audit/polymarket_weather_tape.jsonl",
        resolved_path="var/audit/polymarket_weather_resolved.jsonl",
        fee_haircut=0.02,
        min_lead_hours=0.0,
        settle_lag_hours=24.0,
        station_tolerance_f=1.0,
        sources=[],
        notes=[],
    )
    rendered = render_tape_status_markdown(status)
    # The committed artifact is the renderer's output for an empty tape plus
    # the operator notes appended below it; the counts must match exactly.
    for line in rendered.splitlines():
        if line.startswith("|"):
            assert line in committed


def test_parser_defaults_are_report_only() -> None:
    args = build_parser().parse_args([])
    # A routine run must not overwrite the committed artifact.
    assert args.output_md == DEFAULT_OUTPUT_MD
    assert not str(args.output_md).startswith("docs/")
    assert args.settle_lag_hours is None
    assert args.station_tolerance_f == 1.0
    assert not hasattr(args, "promote")
