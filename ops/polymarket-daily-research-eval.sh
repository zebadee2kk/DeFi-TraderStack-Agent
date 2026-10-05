#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

bash ops/polymarket-wallet-signal-eval.sh
bash ops/polymarket-world-context-eval.sh

echo "polymarket daily research evaluation complete"
