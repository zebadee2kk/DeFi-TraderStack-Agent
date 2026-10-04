"""Interactively populate TraderStack API credentials in .env.

Designed for a trusted WSL/operator shell. Secret values are read with getpass,
never accepted as command-line arguments, and never printed back to the terminal.
The file is rewritten atomically with mode 0600 while preserving unrelated lines.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

SECRET_KEYS = (
    "DUNE_API_KEY",
    "LUNARCRUSH_API_KEY",
    "CRYPTOPANIC_API_KEY",
    "PERPLEXITY_API_KEY",
    "ALTFINS_API_KEY",
    "COINGECKO_API_KEY",
    "COINMARKETCAP_API_KEY",
)
VISIBLE_KEYS = ("DUNE_QUERY_IDS",)
ALL_KEYS = SECRET_KEYS + VISIBLE_KEYS

_KEY_RE = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=.*$"
)


@dataclass(frozen=True)
class EditResult:
    updated: tuple[str, ...]
    skipped: tuple[str, ...]


def _strip_matching_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
        match = _KEY_RE.match(raw)
        if match is None:
            continue
        key = match.group("key")
        _, value = raw.split("=", 1)
        values[key] = _strip_matching_quotes(value)
    return values


def _dotenv_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("credential values must be single-line")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def update_env(path: Path, replacements: dict[str, str]) -> EditResult:
    original_lines = (
        path.read_text(encoding="utf-8", errors="strict").splitlines()
        if path.exists()
        else []
    )
    remaining = dict(replacements)
    output: list[str] = []
    updated: list[str] = []

    for line in original_lines:
        match = _KEY_RE.match(line)
        if match is None:
            output.append(line)
            continue
        key = match.group("key")
        if key not in remaining:
            output.append(line)
            continue
        prefix = match.group("prefix")
        output.append(f"{prefix}{key}={_dotenv_value(remaining.pop(key))}")
        updated.append(key)

    if remaining:
        if output and output[-1] != "":
            output.append("")
        output.append("# API credentials managed by ops/configure-api-credentials.py")
        for key in ALL_KEYS:
            if key not in remaining:
                continue
            output.append(f"{key}={_dotenv_value(remaining.pop(key))}")
            updated.append(key)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    finally:
        temp_path.unlink(missing_ok=True)

    return EditResult(updated=tuple(updated), skipped=())


def prompt_values(
    current: dict[str, str],
    *,
    only_missing: bool,
) -> tuple[dict[str, str], tuple[str, ...]]:
    replacements: dict[str, str] = {}
    skipped: list[str] = []

    for key in SECRET_KEYS:
        present = bool(current.get(key, "").strip())
        if only_missing and present:
            skipped.append(key)
            continue
        status = "currently set" if present else "missing"
        value = getpass.getpass(
            f"{key} [{status}] — enter new value, or press Enter to keep unchanged: "
        )
        if value:
            replacements[key] = value
        else:
            skipped.append(key)

    key = "DUNE_QUERY_IDS"
    present = bool(current.get(key, "").strip())
    if not (only_missing and present):
        status = "currently set" if present else "missing"
        value = input(
            f"{key} [{status}] — enter the configured query mapping/value, "
            "or press Enter to keep unchanged: "
        ).strip()
        if value:
            replacements[key] = value
        else:
            skipped.append(key)
    else:
        skipped.append(key)

    return replacements, tuple(skipped)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Safely prompt for TraderStack external API credentials and update .env."
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="dotenv file to update (default: .env)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="prompt for already-populated keys too; default prompts only for missing keys",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="show only set/missing status; never print values",
    )
    return parser


def _print_status(values: dict[str, str]) -> None:
    for key in ALL_KEYS:
        state = "SET" if values.get(key, "").strip() else "MISSING"
        print(f"{state:7} {key}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path: Path = args.env_file
    if not path.exists():
        example = path.parent / ".env.example"
        if not example.is_file():
            raise FileNotFoundError(
                f"{path} does not exist and no {example} template is available"
            )
        path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print(f"Initialized {path} from {example} with mode 0600.")
    current = read_env_values(path)

    if args.status:
        _print_status(current)
        return 0

    print(f"Updating {path} (secret values will not be echoed).")
    print("Press Enter at any prompt to leave the existing value unchanged.")
    replacements, _skipped = prompt_values(current, only_missing=not args.all)

    if not replacements:
        print("No credential values changed.")
        _print_status(current)
        return 0

    result = update_env(path, replacements)
    final = read_env_values(path)
    print(f"Updated {len(result.updated)} field(s); {path} permissions set to 0600.")
    _print_status(final)

    missing = [key for key in ALL_KEYS if not final.get(key, "").strip()]
    if missing:
        print("Still missing: " + ", ".join(missing))
        return 2

    print("All managed credential fields are populated.")
    print(
        "Next: run .venv/bin/traderstack-resource-audit --probe-public "
        "and .venv/bin/traderstack-redeploy-preflight "
        "--strict-resources --host-published-services"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
