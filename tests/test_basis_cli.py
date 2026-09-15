"""`traderstack-download-basis` (#134): file contract, probe table, empty-is-success."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.research.basis import (
    MAX_ABS_BASIS,
    align_basis_days,
    basis_from_closes,
    count_gaps,
    read_feature_series_json,
    write_feature_series_json,
)
from traderstack.research.basis_cli import (
    BASIS_VENUES,
    basis_series_path,
    build_parser,
    pairwise_alignment,
    run,
)
from traderstack.research.edge_series import EdgeSeriesFetch
from traderstack.research.search_cli import _parse_feature_series

START = datetime(2024, 1, 1, tzinfo=UTC)


def series(
    days: int, *, offset: int = 0, value: float = 0.001
) -> tuple[tuple[datetime, float], ...]:
    return tuple((START + timedelta(days=offset + i), value) for i in range(days))


def ok_fetch(name: str, points: tuple[tuple[datetime, float], ...], source: str) -> EdgeSeriesFetch:
    return EdgeSeriesFetch(
        name=name,
        status="ok",
        reason="fixture bounded_skips=0",
        source=source,
        points=points,
        first=points[0][0],
        last=points[-1][0],
    )


def skipped_fetch(name: str, source: str) -> EdgeSeriesFetch:
    return EdgeSeriesFetch(
        name=name, status="skipped", reason="HTTP 403 after 6 attempts", source=source
    )


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.venue is None
    assert args.symbol is None
    assert args.since is None and args.until is None
    assert str(args.out_dir) == "var/research/basis"
    assert "pit-basis-second-venue.md" in str(args.report_md)
    assert BASIS_VENUES == ("okx", "binance_vision")
    assert basis_series_path(Path("x"), "okx", "BTC/USD") == Path("x/okx/BTCUSD_basis_1d.json")


def test_align_basis_days_drops_non_overlapping_days_on_both_sides() -> None:
    left = series(10)  # days 0..9
    right = series(10, offset=5)  # days 5..14
    aligned_left, aligned_right, dropped_left, dropped_right = align_basis_days(left, right)
    assert [d for d, _ in aligned_left] == [START + timedelta(days=i) for i in range(5, 10)]
    assert [d for d, _ in aligned_right] == [d for d, _ in aligned_left]
    assert dropped_left == 5 and dropped_right == 5
    assert count_gaps(left[:3] + left[6:]) == 3
    assert count_gaps(()) == 0


def test_basis_from_closes_skips_one_sided_and_unbounded_days() -> None:
    day = START
    mark = {day: 101.0, day + timedelta(days=1): 101.0, day + timedelta(days=2): 200.0}
    index = {day: 100.0, day + timedelta(days=2): 100.0, day + timedelta(days=3): 100.0}
    points, bounded_skips = basis_from_closes(mark, index)
    assert points == [(day, pytest.approx(0.01))]
    assert bounded_skips == 1  # day 2: |basis| = 1.0 > MAX_ABS_BASIS
    assert MAX_ABS_BASIS == 0.10


def test_written_json_is_readable_by_search_cli_parser(tmp_path: Path) -> None:
    path = tmp_path / "okx" / "BTCUSD_basis_1d.json"
    write_feature_series_json(path, series(3, value=0.0005))
    parsed = _parse_feature_series(path)
    assert parsed == series(3, value=0.0005)
    assert read_feature_series_json(path) == parsed
    rows = json.loads(path.read_text())
    assert rows[0] == {"opened_at": "2024-01-01T00:00:00+00:00", "value": 0.0005}


def test_run_writes_series_and_probe_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_okx(
        symbol: str, *, client: object, since: datetime, until: datetime, **_: object
    ):
        return ok_fetch(
            f"okx_basis:{symbol}",
            series(730),
            "okx:history-mark-price-candles−history-index-candles",
        )

    async def fake_vision(
        symbol: str, *, client: object, since: datetime, until: datetime, **_: object
    ):
        # one gap day and a 5-day offset so alignment/gap columns are exercised
        points = series(730, offset=5)
        points = points[:100] + points[101:]
        return ok_fetch(
            f"binance_vision_basis:{symbol}",
            points,
            "binance_vision:markPriceKlines−indexPriceKlines",
        )

    monkeypatch.setattr("traderstack.research.basis_cli.fetch_okx_basis", fake_okx)
    monkeypatch.setattr("traderstack.research.basis_cli.fetch_binance_vision_basis", fake_vision)
    report = tmp_path / "probe.md"
    args = build_parser().parse_args(
        [
            "--out-dir",
            str(tmp_path / "basis"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--report-md",
            str(report),
            "--since",
            "2024-01-01",
            "--until",
            "2026-06-01",
        ]
    )
    assert run(args) == 0
    for venue in ("okx", "binance_vision"):
        for symbol in ("BTC/USD", "ETH/USD"):
            path = basis_series_path(tmp_path / "basis", venue, symbol)
            assert path.is_file()
            assert len(_parse_feature_series(path)) >= 720
    text = report.read_text()
    assert "| okx | BTC/USD | **ok** | 2024-01-01 | 2025-12-30 | 730 | 0 | 0 | no |" in text
    assert (
        "| binance_vision | BTC/USD | **ok** | 2024-01-06 | 2026-01-04 | 729 | 1 | 0 | no |" in text
    )
    assert (
        "| BTC/USD | okx×binance_vision | 724 | 6 | 5 | 2024-01-06 | 2025-12-30 | **yes** |" in text
    )
    assert "≥720 aligned daily bars on every symbol): **yes**" in text
    assert "Quote is **USDT**" in text
    assert "Refused in code" in text
    assert "PAPER_PROMOTE_*" in text


def test_all_skipped_run_exits_zero_and_reports_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_okx(symbol: str, **_: object) -> EdgeSeriesFetch:
        return skipped_fetch(f"okx_basis:{symbol}", "okx")

    async def fake_vision(symbol: str, **_: object) -> EdgeSeriesFetch:
        return skipped_fetch(f"binance_vision_basis:{symbol}", "binance_vision")

    monkeypatch.setattr("traderstack.research.basis_cli.fetch_okx_basis", fake_okx)
    monkeypatch.setattr("traderstack.research.basis_cli.fetch_binance_vision_basis", fake_vision)
    report = tmp_path / "probe.md"
    args = build_parser().parse_args(
        [
            "--out-dir",
            str(tmp_path / "basis"),
            "--cache-dir",
            str(tmp_path / "c"),
            "--report-md",
            str(report),
        ]
    )
    assert run(args) == 0
    assert not (tmp_path / "basis").exists()
    text = report.read_text()
    assert "**Result: UNAVAILABLE**" in text
    assert "every requested series was skipped; empty is success" in text
    assert "HTTP 403 after 6 attempts" in text
    assert "| BTC/USD | okx×binance_vision | 0 | 0 | 0 | — | — | **no** |" in text


def test_pairwise_alignment_skips_when_either_side_missing() -> None:
    results = {
        "okx": {"BTC/USD": ok_fetch("okx_basis:BTC/USD", series(800), "okx")},
        "binance_vision": {"BTC/USD": skipped_fetch("binance_vision_basis:BTC/USD", "vision")},
    }
    rows = pairwise_alignment(results)
    assert rows == [
        {
            "symbol": "BTC/USD",
            "pair": "okx×binance_vision",
            "aligned_days": "0",
            "dropped_first": "0",
            "dropped_second": "0",
            "first": "",
            "last": "",
            "dual_basis": "no",
            "note": "one or both series skipped — not aligned, not filled",
        }
    ]
