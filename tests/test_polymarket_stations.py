"""Official station highs (#141): reduce, skip-not-invent, fail closed."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from traderstack.polymarket.cities import CITY_CATALOG
from traderstack.polymarket.stations import (
    GHCN_SOURCE,
    IEM_SOURCE,
    GhcnDailyClient,
    IemAsosClient,
    StationFetch,
    parse_ghcn_tmax_f,
    parse_iem_daily_max_f,
    resolve_official_high,
)

FIXTURES = Path(__file__).parent / "fixtures" / "polymarket" / "tape"
STATIONS: dict[str, Any] = json.loads((FIXTURES / "stations.json").read_text(encoding="utf-8"))
HONOLULU = CITY_CATALOG["honolulu"]
MIAMI = CITY_CATALOG["miami"]


def test_iem_csv_reduces_to_the_verified_phnl_series() -> None:
    body = STATIONS["iem_phnl_csv"]
    assert parse_iem_daily_max_f(body, date(2025, 6, 1), "PHNL") == 83.0
    assert parse_iem_daily_max_f(body, date(2025, 6, 2), "PHNL") == 86.0
    assert parse_iem_daily_max_f(body, date(2025, 6, 3), "PHNL") == 87.0


def test_iem_blank_and_error_bodies_are_skips_never_zero() -> None:
    with pytest.raises(ValueError, match="blank"):
        parse_iem_daily_max_f(STATIONS["iem_phnl_blank_csv"], date(2025, 6, 1), "PHNL")
    with pytest.raises(ValueError, match="not found"):
        parse_iem_daily_max_f(STATIONS["iem_station_not_found"], date(2025, 6, 1), "HNL")
    with pytest.raises(KeyError):
        parse_iem_daily_max_f(STATIONS["iem_phnl_csv"], date(2025, 6, 9), "PHNL")


def test_ghcn_json_reduces_and_missing_tmax_is_a_skip() -> None:
    assert parse_ghcn_tmax_f(STATIONS["ghcn_phnl"], date(2025, 6, 2), "USW00022521") == 86.0
    # A row present but without TMAX is a skip, never a 0.0.
    with pytest.raises(ValueError, match="blank"):
        parse_ghcn_tmax_f(STATIONS["ghcn_missing_tmax"], date(2025, 6, 2), "USW00012839")
    with pytest.raises(KeyError):
        parse_ghcn_tmax_f(STATIONS["ghcn_phnl"], date(2025, 6, 9), "USW00022521")


def test_station_fetch_note_never_prints_a_value_for_a_skip() -> None:
    skipped = StationFetch(name="miami MIA", source=IEM_SOURCE, status="skipped", reason="404")
    assert "skipped (404)" in skipped.as_note()
    assert "0.0" not in skipped.as_note()
    ok = StationFetch(name="miami MIA", source=IEM_SOURCE, status="ok", value=89.0)
    assert "ok (89.0 °F)" in ok.as_note()


@pytest.mark.asyncio
async def test_clients_issue_get_only_and_resolve_matching_sources() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/cgi-bin/request/daily.py":
            assert request.url.params["network"] == "HI_ASOS"
            assert request.url.params["stations"] == "PHNL"
            assert request.url.params["var"] == "max_temp_f"
            return httpx.Response(200, text=STATIONS["iem_phnl_csv"])
        assert request.url.path == "/access/services/data/v1"
        assert request.url.params["stations"] == "USW00022521"
        return httpx.Response(200, json=STATIONS["ghcn_phnl"])

    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        official = await resolve_official_high(
            HONOLULU,
            date(2025, 6, 2),
            iem=IemAsosClient(client=client),
            ghcn=GhcnDailyClient(client=client),
        )

    assert [request.method for request in seen] == ["GET", "GET"]
    assert official.status == "ok"
    assert official.high_f == 86.0
    assert official.resolution_source == IEM_SOURCE
    assert official.crosscheck_source == GHCN_SOURCE
    assert official.mismatch_f == 0.0
    assert official.station_id == "PHNL"


@pytest.mark.asyncio
async def test_disagreement_beyond_tolerance_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/request/daily.py":
            return httpx.Response(200, text=STATIONS["iem_mia_csv"])
        return httpx.Response(200, json=STATIONS["ghcn_mia_mismatch"])

    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        official = await resolve_official_high(
            MIAMI,
            date(2025, 6, 2),
            iem=IemAsosClient(client=client),
            ghcn=GhcnDailyClient(client=client),
        )

    # IEM 89 vs GHCN 92 for the same day: no value is returned at all.
    assert official.status == "unmatched"
    assert official.high_f is None
    assert official.reason.startswith("crosscheck_mismatch")
    assert official.mismatch_f == 3.0


@pytest.mark.asyncio
async def test_missing_primary_or_crosscheck_is_unmatched_not_zero() -> None:
    async def only_ghcn(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/request/daily.py":
            return httpx.Response(200, text=STATIONS["iem_station_not_found"])
        return httpx.Response(200, json=STATIONS["ghcn_phnl"])

    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(only_ghcn)
    ) as client:
        official = await resolve_official_high(
            HONOLULU,
            date(2025, 6, 2),
            iem=IemAsosClient(client=client),
            ghcn=GhcnDailyClient(client=client),
        )
    assert official.status == "unmatched"
    assert official.reason == "primary_station_missing"
    assert official.high_f is None
    assert any(fetch.status == "skipped" for fetch in official.fetches)

    async def only_iem(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/request/daily.py":
            return httpx.Response(200, text=STATIONS["iem_phnl_csv"])
        return httpx.Response(404, text="not found")

    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(only_iem)
    ) as client:
        official = await resolve_official_high(
            HONOLULU,
            date(2025, 6, 2),
            iem=IemAsosClient(client=client),
            ghcn=GhcnDailyClient(client=client),
        )
    assert official.status == "unmatched"
    assert official.reason == "crosscheck_station_missing"
    assert official.high_f is None


@pytest.mark.asyncio
async def test_city_without_a_verified_station_is_skipped() -> None:
    denver = CITY_CATALOG["denver"]
    assert denver.ghcn_id == ""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="station,day,max_temp_f\nBKF,2025-06-02,77.0\n")

    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        official = await resolve_official_high(
            denver,
            date(2025, 6, 2),
            iem=IemAsosClient(client=client),
            ghcn=GhcnDailyClient(client=client),
        )
    assert official.status == "unmatched"
    assert official.reason == "crosscheck_station_missing"
