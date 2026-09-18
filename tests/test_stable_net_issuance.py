"""Tests for DefiLlama stablecoin net-issuance overlay (PIT refuse path)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from traderstack.market.defillama_stablecoins import (
    LAG_DAYS,
    PIT_SAFE_LIVE_HISTORY,
    apply_lag,
    net_issuance_from_chart,
    parse_stablecoin_chart_rows,
    refuse_live_history_for_backtest,
)
from traderstack.research.stable_net_issuance import (
    STABLE_NI_IDS,
    run_stable_net_issuance,
)


def _chart_rows(n: int = 5, start: date | None = None) -> list[dict]:
    day0 = start or date(2024, 1, 1)
    rows = []
    circ = 1000.0
    for i in range(n):
        d = day0 + timedelta(days=i)
        ts = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())
        circ += 10.0 * (i + 1)
        rows.append(
            {
                "date": str(ts),
                "totalCirculatingUSD": {"peggedUSD": circ},
            }
        )
    return rows


def test_pit_live_history_constant_false() -> None:
    assert PIT_SAFE_LIVE_HISTORY is False


def test_refuse_live_history_without_archive() -> None:
    ok, reason = refuse_live_history_for_backtest(pit_archive_present=False)
    assert ok is False
    assert "NOT_PIT_SAFE" in reason or "as_of" in reason


def test_refuse_archive_not_marked_safe() -> None:
    ok, reason = refuse_live_history_for_backtest(pit_archive_present=True, series_pit_safe=False)
    assert ok is False
    assert "refuse" in reason.lower() or "not marked" in reason.lower()


def test_allow_only_when_archive_pit_safe() -> None:
    ok, _ = refuse_live_history_for_backtest(pit_archive_present=True, series_pit_safe=True)
    assert ok is True


def test_parse_and_net_issuance_skips_gaps() -> None:
    rows = _chart_rows(3)
    # insert a gap by removing middle after parse via non-consecutive second batch
    series = parse_stablecoin_chart_rows(rows)
    assert series.pit_safe is False
    assert len(series.points) == 3
    points, notes = net_issuance_from_chart(series)
    assert len(points) == 2
    assert (
        points[0].net_issuance_usd == points[0].circulating_usd - series.points[0].circulating_usd
    )
    assert any(n["name"] == "net_issuance" for n in notes)

    # rebuild with explicit gap
    day0 = date(2024, 2, 1)
    gappy_rows = []
    circ = 100.0
    for i, offset in enumerate([0, 1, 3]):
        d = day0 + timedelta(days=offset)
        ts = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())
        circ += 5.0
        gappy_rows.append({"date": str(ts), "totalCirculatingUSD": {"peggedUSD": circ}})
    gappy_series = parse_stablecoin_chart_rows(gappy_rows)
    gappy_points, gappy_notes = net_issuance_from_chart(gappy_series)
    # only consecutive pair (day0->day1) yields a point; day1->day3 skipped
    assert len(gappy_points) == 1
    assert any("gap" in n["name"] for n in gappy_notes)


def test_apply_lag() -> None:
    series = parse_stablecoin_chart_rows(_chart_rows(6, start=date(2024, 3, 1)))
    points, _ = net_issuance_from_chart(series)
    as_of = date(2024, 3, 6)
    lagged = apply_lag(points, as_of=as_of, lag_days=LAG_DAYS)
    assert all(p.day <= as_of - timedelta(days=LAG_DAYS) for p in lagged)
    assert len(lagged) < len(points)


def test_run_refuses_without_pit_archive() -> None:
    series = parse_stablecoin_chart_rows(_chart_rows(10))
    report = run_stable_net_issuance(
        {},
        fee_bps=80.0,
        chart=series,
        pit_archive_present=False,
    )
    assert report.print_kind == "unavailable"
    assert report.can_promote is False
    assert report.keep_flag_false is True
    assert report.dual_print_passers == 0
    assert len(report.skipped) == len(STABLE_NI_IDS)


def test_catalog_frozen_ids() -> None:
    assert STABLE_NI_IDS == (
        "stable_ni_fade_1_0",
        "stable_ni_fade_1_5",
        "stable_ni_fade_2_0",
        "stable_ni_follow_1_0",
        "stable_ni_follow_1_5",
        "stable_ni_follow_2_0",
    )
