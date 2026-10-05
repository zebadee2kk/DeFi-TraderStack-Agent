#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV="${VENV:-.venv}"
HOST_PUBLISHED="${TRADERSTACK_HOST_PUBLISHED_SERVICES:-0}"

run_ts() {
  if [[ "$HOST_PUBLISHED" == "1" ]]; then
    "$VENV/bin/python" ops/run-with-host-published-services.py -- "$@"
  else
    "$@"
  fi
}

if [[ ! -x "$VENV/bin/traderstack-polymarket-world-context-eval" ]]; then
  echo "missing world-context evaluator; run make setup from current main" >&2
  exit 2
fi

export TRADING_MODE=paper
mkdir -p var/research
tmp="$(mktemp var/research/polymarket-world-context-eval.XXXXXX)"
run_ts "$VENV/bin/traderstack-polymarket-world-context-eval" > "$tmp"
mv "$tmp" var/research/polymarket-world-context-eval-latest.json
echo "world-context research evaluation complete"
