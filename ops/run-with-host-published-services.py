"""Run a TraderStack command from the Docker host with published service URLs.

Loads the normal Settings (including .env), rewrites only compose service DNS
names for Postgres/Redis to loopback, and execs the requested command with those
two values in the child environment. Secret-bearing URLs are never printed.
"""

from __future__ import annotations

import argparse
import os
import shutil

from traderstack.config import Settings


def host_published_urls(settings: Settings) -> tuple[str, str]:
    database_url = settings.database_url.replace("@postgres:", "@127.0.0.1:")
    redis_url = settings.redis_url.replace("://redis:", "://127.0.0.1:")
    return database_url, redis_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Exec a command with host-published Postgres/Redis URLs."
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("command required after --")

    settings = Settings()
    database_url, redis_url = host_published_urls(settings)
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["REDIS_URL"] = redis_url
    env["TRADING_MODE"] = "paper"

    executable = command[0]
    if "/" not in executable:
        resolved = shutil.which(executable)
        if resolved is None:
            raise SystemExit(f"command not found: {executable}")
        executable = resolved

    os.execvpe(executable, command, env)
    return 127  # pragma: no cover - os.execvpe replaces the process on success.


if __name__ == "__main__":
    raise SystemExit(main())
