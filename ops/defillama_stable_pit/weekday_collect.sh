#!/usr/bin/env bash
# Weekday (or daily) DefiLlama stablecoin PIT tip collector.
# Root cause of 2026-09-19..25 gap: no cron/automation was ever installed
# after day-one collect (docs said "Operator next: Schedule daily...").
# This helper is the scheduleable entry. Paper only. Never flips PAPER_PROMOTE_*.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export TRADING_MODE=paper
# Prefer venv entry point; fall back to python -m
if [[ -x "$ROOT/.venv/bin/traderstack-defillama-stable-snapshot" ]]; then
  BIN="$ROOT/.venv/bin/traderstack-defillama-stable-snapshot"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  BIN="$ROOT/.venv/bin/python -m traderstack.research.defillama_stable_snapshot_cli"
else
  BIN="python3 -m traderstack.research.defillama_stable_snapshot_cli"
fi
LOG_DIR="$ROOT/var/ops/defillama_stable_pit"
mkdir -p "$LOG_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
# --check-only first for status; then --live (refuses overwrite of same as_of)
set +e
$BIN --check-only | tee "$LOG_DIR/check_${TS}.log"
BEFORE="$(grep -o "tip_days=[0-9]*" "$LOG_DIR/check_${TS}.log" | head -1 || true)"
$BIN --live | tee "$LOG_DIR/collect_${TS}.log"
RC=$?
$BIN --check-only | tee "$LOG_DIR/check_after_${TS}.log"
AFTER="$(grep -o "tip_days=[0-9]*" "$LOG_DIR/check_after_${TS}.log" | head -1 || true)"
echo "tip_days_before=${BEFORE:-unknown} tip_days_after=${AFTER:-unknown} exit=$RC"
exit $RC
