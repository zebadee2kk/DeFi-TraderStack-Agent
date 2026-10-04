#!/usr/bin/env python3
"""Safely populate intelligence-provider credentials in a local .env file.

Designed for interactive use on WSL/Linux. Secret values are read with
getpass(), never accepted as command-line values, and never printed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    secret: bool = True
    required_for_strict: bool = True


FIELDS = (
    CredentialField("DUNE_API_KEY", "Dune API key"),
    CredentialField(
        "DUNE_QUERY_IDS",
        'Dune query IDs (for example "BTC:123456,ETH:234567")',
        secret=False,
    ),
    CredentialField("LUNARCRUSH_API_KEY", "LunarCrush API key"),
    CredentialField("CRYPTOPANIC_API_KEY", "CryptoPanic API key"),
    CredentialField("PERPLEXITY_API_KEY", "Perplexity API key"),
    CredentialField("ALTFINS_API_KEY", "altFINS API key"),
    CredentialField("COINGECKO_API_KEY", "CoinGecko API key"),
    CredentialField("COINMARKETCAP_API_KEY", "CoinMarketCap API key"),
)


def parse_env(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.exists():
        return [], {}

    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def redact_status(values: dict[str, str]) -> list[str]:
    output: list[str] = []
    for field in FIELDS:
        value = values.get(field.name, "").strip()
        state = "SET" if value else "MISSING"
        output.append(f"{field.name}={state}")
    return output


def prompt_value(field: CredentialField, current: str, *, ask_all: bool) -> str | None:
    if current and not ask_all:
        return None

    if current:
        choice = input(f"{field.label} is already set. Replace it? [y/N]: ").strip().lower()
        if choice not in {"y", "yes"}:
            return None
    else:
        choice = input(f"Configure {field.label}? [Y/n]: ").strip().lower()
        if choice in {"n", "no"}:
            return None

    if field.secret:
        first = getpass.getpass(f"{field.label}: ").strip()
        if not first:
            return None
        second = getpass.getpass("Confirm value: ").strip()
        if first != second:
            raise ValueError(f"{field.name}: values did not match")
        return first

    value = input(f"{field.label}: ").strip()
    return value or None


def render_env(original_lines: list[str], updates: dict[str, str]) -> str:
    remaining = dict(updates)
    rendered: list[str] = []

    for raw in original_lines:
        if "=" not in raw or raw.lstrip().startswith("#"):
            rendered.append(raw)
            continue
        key, _ = raw.split("=", 1)
        normalized = key.strip()
        if normalized in remaining:
            rendered.append(f"{normalized}={remaining.pop(normalized)}")
        else:
            rendered.append(raw)

    if remaining:
        if rendered and rendered[-1] != "":
            rendered.append("")
        rendered.append("# Intelligence credentials populated by ops/configure-intelligence-credentials.py")
        for field in FIELDS:
            if field.name in remaining:
                rendered.append(f"{field.name}={remaining.pop(field.name)}")

    return "\n".join(rendered).rstrip() + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def backup_env(path: Path, repo_root: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = repo_root / "var" / "backups" / "credentials"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"env.{stamp}.bak"
    shutil.copy2(path, backup_path)
    os.chmod(backup_path, stat.S_IRUSR | stat.S_IWUSR)
    return backup_path


def run_checks(repo_root: Path, env_file: Path) -> int:
    commands = [
        [str(repo_root / ".venv/bin/traderstack-check-config")],
        [
            str(repo_root / ".venv/bin/traderstack-resource-audit"),
            "--probe-public",
        ],
        [
            str(repo_root / ".venv/bin/traderstack-redeploy-preflight"),
            "--strict-resources",
            "--host-published-services",
        ],
    ]
    env = os.environ.copy()

    final_rc = 0
    for command in commands:
        executable = Path(command[0])
        if not executable.exists():
            print(f"SKIP: {executable} not found; run 'make setup' first.", file=sys.stderr)
            final_rc = max(final_rc, 1)
            continue
        print(f"\n==> Running {executable.name}")
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            final_rc = max(final_rc, completed.returncode)
    return final_rc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Interactively populate missing intelligence credentials in .env "
            "without exposing secret values on the command line."
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="local env file to update (default: .env)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="offer to replace already-populated values as well as missing ones",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="print SET/MISSING status only; never print values",
    )
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="skip config/resource/preflight checks after updating",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    env_file = args.env_file
    if not env_file.is_absolute():
        env_file = repo_root / env_file

    original_lines, values = parse_env(env_file)
    if not env_file.exists():
        template = repo_root / ".env.example"
        if not template.is_file():
            print("ERROR: .env is missing and .env.example was not found.", file=sys.stderr)
            return 2
        original_lines, values = parse_env(template)
        print(f"{env_file} does not exist; it will be created from .env.example.")

    if args.status:
        print("\n".join(redact_status(values)))
        return 0

    print("This helper only updates intelligence credential fields.")
    print("Secret values are hidden while typing and are never printed.")
    print("Press Ctrl+C to abort without writing changes.\n")

    updates: dict[str, str] = {}
    try:
        for field in FIELDS:
            current = values.get(field.name, "").strip()
            new_value = prompt_value(field, current, ask_all=args.all)
            if new_value is not None:
                updates[field.name] = new_value
    except (KeyboardInterrupt, EOFError):
        print("\nAborted. No changes written.", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(f"ERROR: {exc}. No changes written.", file=sys.stderr)
        return 2

    if not updates:
        print("No credential changes requested.")
        print("\n".join(redact_status(values)))
        return 0

    backup = backup_env(env_file, repo_root)
    merged = dict(values)
    merged.update(updates)
    atomic_write(env_file, render_env(original_lines, updates))

    print(f"Updated {env_file}")
    if backup is not None:
        print(f"Backup written to {backup}")
    print("Permissions set to owner read/write only.")
    print("\nCredential status:")
    print("\n".join(redact_status(merged)))

    if args.no_check:
        return 0

    canonical_env = repo_root / ".env"
    if env_file != canonical_env:
        print(
            "SKIP: post-write checks read the repository .env; "
            "rerun without --env-file to validate runtime configuration.",
            file=sys.stderr,
        )
        return 0

    return run_checks(repo_root, env_file)


if __name__ == "__main__":
    raise SystemExit(main())
