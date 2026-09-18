#!/usr/bin/env bash
set -euo pipefail
REPO=/home/rham-admin/src/DeFi-TraderStack-Agent
cd "$REPO"
RAW=var/ops/_carry_fills_soak_20260918
mkdir -p "$RAW"
SECONDS_SOAK="${1:-480}"

capture() {
  local PHASE="$1"
  local UTC LON SHA
  UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  LON=$(TZ=Europe/London date +%Y-%m-%dT%H:%M:%S%z)
  SHA=$(git rev-parse --short HEAD)
  echo "phase=$PHASE utc=$UTC london=$LON commit=$SHA" | tee -a "$RAW/meta.txt"
  curl -sS http://127.0.0.1:9108/metrics > "$RAW/metrics_${PHASE}.txt" || true
  grep -E 'traderstack_portfolio_nav_usd|traderstack_paper_fills_total|paper_perp|perp_hedge|funding|cycles_total' "$RAW/metrics_${PHASE}.txt" > "$RAW/metrics_${PHASE}_snippet.txt" || true
  sg docker -c "docker compose logs --tail=1200 app" > "$RAW/app_logs_${PHASE}.txt" 2>&1 || true
  sg docker -c "docker compose exec -T app cat /app/var/state/portfolio.json" > "$RAW/portfolio_${PHASE}.json" 2>/dev/null || true
  grep -E 'paper_perp|paper_carry_diag|perp_hedge|funding_applied|mid_fetch|hedge_skipped|paper_fill|withheld|KILL|carry-diag' "$RAW/app_logs_${PHASE}.txt" > "$RAW/app_logs_${PHASE}_perp.txt" || true
  echo "CAPTURE_OK_$PHASE"
}

capture start
echo "Soaking ${SECONDS_SOAK}s ..."
sleep "$SECONDS_SOAK"
capture mid1
capture end
sg docker -c "docker compose logs --since 25m app" > "$RAW/docker_logs_window.txt" 2>&1 || true
grep -E 'paper_perp|paper_carry_diag|perp_hedge|funding_applied|mid_fetch|hedge_skipped|runtime_cycle_completed|withheld|kill|carry-diag|carry_hedged' "$RAW/docker_logs_window.txt" > "$RAW/docker_logs_perp.txt" || true
echo SOAK_DONE
