from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.config import Settings
from traderstack.resource_audit import (
    BLOCKED_CREDENTIAL,
    DELIBERATELY_DISABLED,
    IMPLEMENTED_NOT_PROVEN,
    _evidence,
    build_rows,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def test_missing_keyed_resources_are_explicitly_blocked(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    rows = {row.provider: row for row in build_rows(_settings())}
    assert rows["Dune"].status == BLOCKED_CREDENTIAL
    assert rows["LunarCrush"].status == BLOCKED_CREDENTIAL
    assert rows["CryptoPanic"].status == BLOCKED_CREDENTIAL
    assert rows["Perplexity"].status == BLOCKED_CREDENTIAL
    assert rows["altFINS"].status == BLOCKED_CREDENTIAL


def test_configured_provider_reports_source_without_secret_value(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DUNE_API_KEY", "do-not-print-me")
    monkeypatch.setenv("DUNE_QUERY_IDS", "BTC:123")
    rows = {
        row.provider: row
        for row in build_rows(_settings(dune_api_key="do-not-print-me", dune_query_ids="BTC:123"))
    }
    dune = rows["Dune"]
    assert dune.status == IMPLEMENTED_NOT_PROVEN
    assert dune.credential_source == "env"
    assert "do-not-print-me" not in json.dumps(dune.__dict__)


def test_disabled_public_collectors_are_not_credential_failures(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    rows = {row.provider: row for row in build_rows(_settings())}
    assert rows["Coin Metrics"].status == DELIBERATELY_DISABLED
    assert rows["Polymarket crypto tape"].status == DELIBERATELY_DISABLED
    assert rows["Polymarket weather tape"].status == DELIBERATELY_DISABLED


def test_jsonl_evidence_counts_point_in_time_rows(tmp_path: Path) -> None:
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    path = tmp_path / "tape.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"observed_at": (now - timedelta(hours=1)).isoformat()}),
                json.dumps({"observed_at": (now - timedelta(days=2)).isoformat()}),
                json.dumps({"observed_at": (now - timedelta(days=9)).isoformat()}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    last, rows_24h, rows_7d, stale = _evidence(str(path), now=now)
    assert last == (now - timedelta(hours=1)).isoformat()
    assert rows_24h == 1
    assert rows_7d == 2
    assert stale == "no"


def test_dotenv_source_is_reported_without_secret_value(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "LUNARCRUSH_API_KEY=secret-from-file\n",
        encoding="utf-8",
    )
    rows = {
        row.provider: row
        for row in build_rows(_settings(lunarcrush_api_key="secret-from-file"))
    }
    lunar = rows["LunarCrush"]
    assert lunar.credential_source == ".env"
    assert "secret-from-file" not in json.dumps(lunar.__dict__)
