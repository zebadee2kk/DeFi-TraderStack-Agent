from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).resolve().parents[1] / "ops" / "configure-api-credentials.py"
    spec = importlib.util.spec_from_file_location("credential_helper", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


helper = _module()


def test_update_env_preserves_unrelated_lines_and_sets_mode_0600(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "TRADING_MODE=paper\nKILL_SWITCH=true\nDUNE_API_KEY=old\n# keep this comment\n",
        encoding="utf-8",
    )
    env.chmod(0o644)

    result = helper.update_env(
        env,
        {
            "DUNE_API_KEY": "new=value",
            "PERPLEXITY_API_KEY": "p-key",
        },
    )

    text = env.read_text(encoding="utf-8")
    assert "TRADING_MODE=paper" in text
    assert "KILL_SWITCH=true" in text
    assert "# keep this comment" in text
    assert 'DUNE_API_KEY="new=value"' in text
    assert 'PERPLEXITY_API_KEY="p-key"' in text
    assert result.updated == ("DUNE_API_KEY", "PERPLEXITY_API_KEY")
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_read_env_values_handles_quoted_values_and_equals(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "DUNE_API_KEY=\"abc=123\"\nDUNE_QUERY_IDS='BTC:100,ETH:200'\n",
        encoding="utf-8",
    )
    values = helper.read_env_values(env)
    assert values["DUNE_API_KEY"] == "abc=123"
    assert values["DUNE_QUERY_IDS"] == "BTC:100,ETH:200"


def test_dotenv_value_rejects_multiline_secret() -> None:
    with pytest.raises(ValueError, match="single-line"):
        helper._dotenv_value("first\nsecond")


def test_status_never_prints_values(capsys: pytest.CaptureFixture[str]) -> None:
    values = {
        "DUNE_API_KEY": "super-secret-value",
        "DUNE_QUERY_IDS": "BTC:123",
    }
    helper._print_status(values)
    output = capsys.readouterr().out
    assert "super-secret-value" not in output
    assert "BTC:123" not in output
    assert "SET      DUNE_API_KEY" in output
    assert "SET      DUNE_QUERY_IDS" in output
    assert "MISSING  LUNARCRUSH_API_KEY" in output
    assert "OPTIONAL COINGECKO_API_KEY" in output
    assert "OPTIONAL COINMARKETCAP_API_KEY" in output


def test_prompt_values_skips_existing_keys_in_missing_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = {key: "already-set" for key in helper.REQUIRED_KEYS}
    monkeypatch.setattr(
        helper.getpass,
        "getpass",
        lambda prompt: pytest.fail(f"unexpected secret prompt: {prompt}"),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: pytest.fail(f"unexpected visible prompt: {prompt}"),
    )

    replacements, skipped = helper.prompt_values(
        current,
        only_missing=True,
        include_optional=False,
    )

    assert replacements == {}
    assert set(skipped) == set(helper.REQUIRED_KEYS)


def test_main_initializes_missing_env_from_example(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = tmp_path / ".env"
    example = tmp_path / ".env.example"
    example.write_text("TRADING_MODE=paper\nKILL_SWITCH=true\n", encoding="utf-8")
    monkeypatch.setattr(
        helper,
        "prompt_values",
        lambda current, only_missing, include_optional=False: ({}, tuple(helper.ALL_KEYS)),
    )

    assert helper.main(["--env-file", str(env)]) == 2
    text = env.read_text(encoding="utf-8")
    assert "TRADING_MODE=paper" in text
    assert "KILL_SWITCH=true" in text
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_optional_reference_keys_do_not_count_as_missing() -> None:
    values = {key: "set" for key in helper.REQUIRED_KEYS}
    assert helper._missing_keys(values) == []


def test_optional_keys_are_only_prompted_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = {key: "set" for key in helper.REQUIRED_KEYS}
    prompts: list[str] = []

    def fake_getpass(prompt: str) -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr(helper.getpass, "getpass", fake_getpass)
    monkeypatch.setattr("builtins.input", lambda _: "")

    helper.prompt_values(current, only_missing=True, include_optional=False)
    assert all("COINGECKO_API_KEY" not in prompt for prompt in prompts)
    assert all("COINMARKETCAP_API_KEY" not in prompt for prompt in prompts)

    helper.prompt_values(current, only_missing=True, include_optional=True)
    assert any("COINGECKO_API_KEY" in prompt for prompt in prompts)
    assert any("COINMARKETCAP_API_KEY" in prompt for prompt in prompts)


def test_guide_never_prints_secret_values(capsys: pytest.CaptureFixture[str]) -> None:
    helper._print_guide()
    output = capsys.readouterr().out
    assert "DUNE_API_KEY [required]" in output
    assert "COINGECKO_API_KEY [optional]" in output
    assert "DUNE_QUERY_IDS [required]" in output


def test_main_guide_does_not_prompt_or_touch_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = tmp_path / ".env"
    env.write_text("TRADING_MODE=paper\nKILL_SWITCH=true\n", encoding="utf-8")
    before = env.read_text(encoding="utf-8")
    monkeypatch.setattr(
        helper.getpass,
        "getpass",
        lambda prompt: pytest.fail(f"unexpected prompt: {prompt}"),
    )

    assert helper.main(["--env-file", str(env), "--guide"]) == 0
    assert env.read_text(encoding="utf-8") == before
    output = capsys.readouterr().out
    assert "PERPLEXITY_API_KEY [required]" in output
