"""Regression: archive report sidecars must not be loaded as candle series."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.research.xs_topk_cli import load_candles_dir


def test_load_candles_dir_skips_archive_report_sidecars(tmp_path: Path) -> None:
    """Archive downloads (#147) write <out>.report.json next to candle arrays."""
    day0 = datetime(2024, 9, 24, tzinfo=UTC)
    rows = []
    for i in range(400):
        opened = day0 + timedelta(days=i)
        rows.append(
            {
                "symbol": "BTC/USD",
                "interval": "1d",
                "opened_at": opened.isoformat(),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 1000.0 + i,
            }
        )
    candle_path = tmp_path / "BTC_USD_1d.json"
    report_path = tmp_path / "BTC_USD_1d.json.report.json"
    candle_path.write_text(json.dumps(rows) + "\n")
    report_path.write_text(json.dumps({"venue": "coinbase_exchange", "bar_count": 400}) + "\n")

    histories, skip_reasons, skipped = load_candles_dir(tmp_path, universe=None)

    assert "BTC/USD@1d" in histories
    assert skipped == 0
    assert skip_reasons == []
