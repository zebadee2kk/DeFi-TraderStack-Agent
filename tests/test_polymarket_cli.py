import json
from pathlib import Path

import pytest

from traderstack.cli_check import build_report
from traderstack.config import Settings
from traderstack.polymarket.cli import build_parser, main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "polymarket"


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **extra: str) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("KILL_SWITCH", "false")
    monkeypatch.setenv("KILL_SWITCH_REDIS_ENABLED", "false")
    monkeypatch.setenv("POLYMARKET_WEATHER_LEDGER_PATH", str(tmp_path / "paper.jsonl"))
    for key, value in extra.items():
        monkeypatch.setenv(key, value)


def test_parser_defaults_are_once_and_offline_capable() -> None:
    args = build_parser().parse_args(["--fixtures-dir", str(FIXTURES), "--json"])
    assert args.once is True
    assert args.fixtures_dir == FIXTURES
    assert args.json is True


def test_cli_fixture_run_writes_paper_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _env(monkeypatch, tmp_path)
    main(["--fixtures-dir", str(FIXTURES), "--ledger-path", str(tmp_path / "out.jsonl")])
    out = capsys.readouterr().out
    assert "no CLOB orders" in out
    assert "WOULD_TRADE" in out
    assert "unproven" in out
    lines = (tmp_path / "out.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert any(json.loads(line)["status"] == "would_trade" for line in lines)
    assert all(json.loads(line)["venue_submitted"] is False for line in lines)


def test_cli_json_marks_execution_paper_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _env(monkeypatch, tmp_path)
    main(["--fixtures-dir", str(FIXTURES), "--json", "--ledger-path", str(tmp_path / "out.jsonl")])
    payload = json.loads(capsys.readouterr().out)
    assert payload["venue_submitted"] is False
    assert payload["execution"] == "paper_intent_only"
    assert payload["would_trade"] >= 1


def test_cli_rejects_live_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _env(monkeypatch, tmp_path, TRADING_MODE="live")
    with pytest.raises(RuntimeError, match="TRADING_MODE=paper"):
        main(["--fixtures-dir", str(FIXTURES), "--ledger-path", str(tmp_path / "out.jsonl")])


def test_check_config_reports_disabled_by_default() -> None:
    report = build_report(settings())
    item = next(i for i in report.items if i.label == "Polymarket weather research")
    assert item.value.startswith("disabled")
    paper_only = next(i for i in report.items if "no CLOB" in i.label)
    assert paper_only.value == "yes"


def test_check_config_warns_when_enabled_with_non_paper_mode() -> None:
    report = build_report(settings(polymarket_weather_enabled=True, trading_mode="live"))
    assert not report.safe
    assert any("POLYMARKET_WEATHER_ENABLED" in warning for warning in report.warnings)
    assert any("Live Polymarket" in warning for warning in report.warnings)


# --- polymarket weather PIT tape (#141) ---


def test_check_config_reports_the_pit_tape_collector_and_resolver() -> None:
    report = build_report(settings())
    item = next(i for i in report.items if "PIT tape collector" in i.label)
    assert "no intents" in item.value
    assert "traderstack-polymarket-weather-collect" in item.detail
    assert "traderstack-polymarket-weather-resolve" in item.detail
    assert "PAPER_PROMOTE_POLYMARKET_WEATHER" in item.detail
    lag = next(i for i in report.items if "PIT tape settle lag" in i.label)
    assert lag.value == "24 h"
