"""A torn trailing tape line is skipped, never a resolver crash (#141)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from traderstack.polymarket.tape import _read_jsonl


def test_read_jsonl_skips_a_torn_trailing_line(tmp_path: Path) -> None:
    path = tmp_path / "tape.jsonl"
    good = {"market_id": "m1", "observed_at": "2026-09-15T00:00:00+00:00"}
    path.write_text(
        json.dumps(good) + "\n" + '{"market_id": "m2", "observed_at": "2026-09-1', encoding="utf-8"
    )
    assert _read_jsonl(path) == [good]


def test_read_jsonl_still_rejects_a_non_object_line(tmp_path: Path) -> None:
    path = tmp_path / "tape.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(TypeError):
        _read_jsonl(path)


def test_read_jsonl_missing_file_is_empty(tmp_path: Path) -> None:
    assert _read_jsonl(tmp_path / "absent.jsonl") == []
