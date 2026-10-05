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
LIMIT="${POLYMARKET_WALLET_LIMIT:-25}"
MAX_PAGES="${POLYMARKET_WALLET_MAX_PAGES:-2}"

if [[ ! -x "$VENV/bin/traderstack-polymarket-wallet-snapshot" ]]; then
  echo "missing $VENV/bin/traderstack-polymarket-wallet-snapshot; run make setup" >&2
  exit 2
fi

export TRADING_MODE=paper
mkdir -p var/research

run_ts "$VENV/bin/traderstack-polymarket-wallet-snapshot"   --category CRYPTO --time-period MONTH --limit "$LIMIT" --max-pages "$MAX_PAGES"

run_ts "$VENV/bin/traderstack-polymarket-wallet-snapshot"   --category OVERALL --time-period MONTH --limit "$LIMIT" --max-pages "$MAX_PAGES"

run_ts "$VENV/bin/traderstack-polymarket-research-health"

run_ts "$VENV/bin/traderstack-signal-health-import"

tmp="$(mktemp var/research/polymarket-wallet-cohorts.XXXXXX)"
run_ts "$VENV/bin/traderstack-polymarket-wallet-cohorts"   --time-period MONTH --top 100 > "$tmp"
mv "$tmp" var/research/polymarket-wallet-cohorts-latest.json

echo "polymarket intelligence collection complete"
