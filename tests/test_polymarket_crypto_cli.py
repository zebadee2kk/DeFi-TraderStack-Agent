"""``traderstack-polymarket-crypto-collect`` and its check-config block (#142)."""

import json
from pathlib import Path

import pytest

from traderstack.cli_check import build_report
from traderstack.config import Settings
from traderstack.polymarket.crypto_cli import build_parser, load_crypto_fixtures, main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "polymarket_crypto"


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
    monkeypatch.setenv("POLYMARKET_CRYPTO_TAPE_PATH", str(tmp_path / "tape.jsonl"))
    for key, value in extra.items():
        monkeypatch.setenv(key, value)


def test_parser_defaults_are_once_and_offline_capable() -> None:
    args = build_parser().parse_args(["--fixtures-dir", str(FIXTURES), "--json"])
    assert args.once is True
    assert args.fixtures_dir == FIXTURES
    assert args.json is True
    assert args.tape_path is None
    assert args.print_rules is False


def test_fixture_run_writes_the_tape_and_prints_the_paper_banner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, tmp_path)
    main(["--fixtures-dir", str(FIXTURES)])
    out = capsys.readouterr().out
    assert "no CLOB orders" in out
    assert "paper_tape_only" in out
    assert "no Deribit private endpoints" in out
    rows = [
        json.loads(line)
        for line in (tmp_path / "tape.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows
    assert all(row["venue_submitted"] is False for row in rows)


def test_json_marks_execution_paper_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, tmp_path)
    main(["--fixtures-dir", str(FIXTURES), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["venue_submitted"] is False
    assert payload["execution"] == "paper_tape_only"
    assert payload["model_version"] == "bs_n_d2_markiv_interp_v1"
    assert payload["rows_ok"] == 2


def test_print_rules_does_not_touch_the_network_or_the_tape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--print-rules"])
    out = capsys.readouterr().out
    assert "pre-registered" in out
    assert "Empty is success" in out
    assert not (tmp_path / "tape.jsonl").exists()


def test_live_trading_mode_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _env(monkeypatch, tmp_path, TRADING_MODE="live")
    with pytest.raises(RuntimeError, match="TRADING_MODE=paper"):
        main(["--fixtures-dir", str(FIXTURES)])


def test_fixture_loader_rejects_wrong_shapes(tmp_path: Path) -> None:
    (tmp_path / "events.json").write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError):
        load_crypto_fixtures(tmp_path)


def test_check_config_shows_the_block_disabled_by_default() -> None:
    report = build_report(settings())
    labels = {item.label: item.value for item in report.items}
    assert labels["Polymarket crypto wedge tape"] == "disabled (opt-in)"
    assert labels["  Deribit read-only (no private endpoints)"] == "yes"
    assert "slice 2" in labels["  evaluator"]
    assert report.safe


def test_check_config_warns_on_live_mode_and_empty_assets() -> None:
    live = build_report(settings(trading_mode="live", polymarket_crypto_tape_enabled=True))
    assert any("POLYMARKET_CRYPTO_TAPE_ENABLED=true with TRADING_MODE" in w for w in live.warnings)
    assert live.safe is False

    empty = build_report(
        settings(polymarket_crypto_tape_enabled=True, polymarket_crypto_assets=" ")
    )
    assert any("empty POLYMARKET_CRYPTO_ASSETS" in w for w in empty.warnings)


def test_check_config_warns_on_unknown_asset() -> None:
    report = build_report(
        settings(polymarket_crypto_tape_enabled=True, polymarket_crypto_assets="BTC,DOGE")
    )
    assert any("DOGE" in warning for warning in report.warnings)
