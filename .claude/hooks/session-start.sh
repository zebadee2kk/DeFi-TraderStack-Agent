#!/bin/bash
# SessionStart hook (Claude Code on the web): install the dev environment so
# `ruff`, `mypy` and `pytest` all work immediately in a fresh session.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "session-start: python3.12 not found on PATH, skipping venv setup" >&2
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  python3.12 -m venv .venv
fi

.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -e '.[dev]'

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\""
  } >> "$CLAUDE_ENV_FILE"
fi
