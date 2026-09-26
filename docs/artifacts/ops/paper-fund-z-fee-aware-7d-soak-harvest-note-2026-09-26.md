# Grok-Bot harvest note — fund_z 7d fee-aware paper soak (2026-09-26)

**HONESTY: PAPER ONLY. Do not invent PnL. Do not flip PAPER_PROMOTE_*. Do not kill PID 45859.**

Parent agent owns Grok Bot routines; this note is the operator checklist with exact paths.
Expected completion: **~2026-10-03 21:08 BST** (started 2026-09-26 21:08:05 BST; duration 604800s).

## Paths (exact)

| Item | Path |
|---|---|
| Out dir | `/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_7d_soak_20260926/` |
| Harvest JSON | `.../host_fee_aware_probe.json` |
| Stdout | `.../soak.stdout.log` |
| Stderr | `.../soak.stderr.log` |
| PID file | `.../soak.pid` (start PID **2638509**) |
| Worktree | `/tmp/dt-fund-z-7d-soak-20260926` |
| Repo | `/home/rham-admin/src/DeFi-TraderStack-Agent` |
| machineId | `561916e9-51c2-474e-b6d6-31f9dac5b5aa` (WSL) |

## Pre-flight (read-only)

1. `ps -p $(cat .../soak.pid) -o pid,etime,cmd` — confirm still running or exited cleanly.
2. Do **not** touch 48h out dir except read-only:
   `var/ops/_fund_z_fee_aware_48h_soak_20260926/` (PID **45859** if still alive).
3. Confirm Field defaults still false:
   `Settings().paper_promote_fund_z_harvest_sign_hold is False` and `.env` unset/false.
4. If process died early: document interrupt; **do not fabricate** fee_aware PnL.

## Harvest steps

1. Read final `host_fee_aware_probe.json` (keys: samples, fee_aware_paper_pnl_usd, fees_usd, funding_pnl_usd, funding_prints_applied, flag snapshots).
2. Write summary artifact under `docs/artifacts/ops/` e.g.
   `paper-fund-z-fee-aware-7d-soak-harvest-2026-10-03.md` with:
   - wall-clock start/end (Europe/London)
   - n_samples, funding_prints_applied
   - fees_usd / funding_pnl_usd / fee_aware_paper_pnl_usd (**as recorded**; no invention)
   - marks_incomplete / skipped_assets if any
   - confirmation that Field defaults + `.env` remain false after exit
3. Optionally mid-compare vs 48h harvest if that completed earlier (same honesty rules).
4. Open analysis PR; keep `can_promote=false`; never set `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD=true` from harvest alone.
5. Cross-check promote-gap memo still stands:
   `docs/artifacts/strategy-search/fund-z-promote-honesty-gap-2026-09-26.md`

## Suggested routine schedule (parent owns Grok Bot)

| When (Europe/London) | Action |
|---|---|
| Daily ~09:00 BST while running | Optional mid-snapshot (read-only JSON/log tail); do not restart |
| **2026-10-03 ~21:30 BST** | Primary harvest window (soak should have exited) |
| 2026-10-04 ~09:00 BST | Backup harvest if primary missed |

Cron example (operator / parent to install — **not** installed by this note):

```cron
# example only — parent agent owns Grok Bot routines
30 21 3 10 *  # 2026-10-03 21:30 BST — trigger harvest agent for 7d fund_z soak
```

## Non-goals

- Do not invent mids, funding, or PnL.
- Do not flip promote Field defaults or `.env`.
- Do not kill 45859 / collide out dirs.
- Do not go live.
