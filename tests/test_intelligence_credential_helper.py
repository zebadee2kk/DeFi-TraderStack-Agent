from __future__ import annotations

import importlib.util
import stat
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "ops" / "configure-intelligence-credentials.py"
SPEC = importlib.util.spec_from_file_location("credential_helper", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
credential_helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(credential_helper)


def test_redact_status_never_returns_secret_values() -> None:
    secret = "super-secret-value"
    rows = credential_helper.redact_status(
        {
            "DUNE_API_KEY": secret,
            "DUNE_QUERY_IDS": "BTC:123",
        }
    )
    rendered = "\n".join(rows)
    assert secret not in rendered
    assert "DUNE_API_KEY=SET" in rows
    assert "DUNE_QUERY_IDS=SET" in rows
    assert "LUNARCRUSH_API_KEY=MISSING" in rows


def test_render_env_updates_only_selected_fields() -> None:
    original = [
        "TRADING_MODE=paper",
        "DUNE_API_KEY=old",
        "KILL_SWITCH=true",
        "PERPLEXITY_API_KEY=",
    ]
    rendered = credential_helper.render_env(
        original,
        {
            "DUNE_API_KEY": "new-value",
            "PERPLEXITY_API_KEY": "p-value",
        },
    )
    assert "TRADING_MODE=paper" in rendered
    assert "KILL_SWITCH=true" in rendered
    assert "DUNE_API_KEY=new-value" in rendered
    assert "PERPLEXITY_API_KEY=p-value" in rendered
    assert "DUNE_API_KEY=old" not in rendered


def test_render_env_appends_missing_fields_without_reordering_existing_config() -> None:
    rendered = credential_helper.render_env(
        ["TRADING_MODE=paper", "KILL_SWITCH=true"],
        {"COINGECKO_API_KEY": "cg-value"},
    )
    lines = rendered.splitlines()
    assert lines[0] == "TRADING_MODE=paper"
    assert lines[1] == "KILL_SWITCH=true"
    assert "COINGECKO_API_KEY=cg-value" in lines


def test_atomic_write_sets_owner_only_permissions(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    credential_helper.atomic_write(path, "DUNE_API_KEY=x\n")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_backup_is_written_under_gitignored_var_tree(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("DUNE_API_KEY=x\n", encoding="utf-8")
    backup = credential_helper.backup_env(env, tmp_path)
    assert backup is not None
    assert backup.parent == tmp_path / "var" / "backups" / "credentials"
    assert backup.read_text(encoding="utf-8") == "DUNE_API_KEY=x\n"
    assert stat.S_IMODE(backup.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR


def test_no_secret_command_line_arguments_are_supported() -> None:
    parser = credential_helper.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    for field in credential_helper.FIELDS:
        assert f"--{field.name.lower()}" not in option_strings
