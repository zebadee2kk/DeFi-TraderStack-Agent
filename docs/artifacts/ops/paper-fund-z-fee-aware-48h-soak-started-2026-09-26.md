# fund_z 48h fee-aware paper soak — STARTED (2026-09-26)

**HONESTY: PAPER ONLY. NOT A PROMOTE. NOT LIVE PnL. Harvest pending follow-up.**

Detached host soak started after fee-amortization recipe pre-registration.
Flags enabled **only** in-process via `Settings.model_copy` inside
`ops/paper_carry_pnl_soak/host_fee_aware_probe.py --mode fund_z`.
Field defaults and `.env` remain false. `TRADING_MODE=paper`.

## Process

| Field | Value |
|---|---|
| Started (Europe/London) | 2026-09-26 ~10:02 BST |
| PID | **45859** |
| Duration requested | **172800 s (48h)** |
| Sample every | 300 s |
| Mode / signal | `fund_z` / `fund_z_harvest_sign_hold` |
| Out JSON | `/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_48h_soak_20260926/host_fee_aware_probe.json` |
| Stdout log | `/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_48h_soak_20260926/soak.stdout.log` |
| Stderr log | `/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_48h_soak_20260926/soak.stderr.log` |
| PID file | `/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_48h_soak_20260926/soak.pid` |
| Worktree cwd | `/tmp/dt-fee-amort-study-20260926` (tip fc30e5b / #181) |
| PYTHONPATH | worktree `src` |
| Interpreter | `/home/rham-admin/src/DeFi-TraderStack-Agent/.venv/bin/python` |

## Hygiene (at start)

- `PAPER_PROMOTE_*` Field defaults: **false** (unchanged)
- Probe enables `paper_perp_hedge` + `paper_promote_fund_z_harvest_sign_hold` via model_copy only
- Observed at t≈0: BTC+ETH hedges opened with `signal=fund_z_harvest_sign_hold`, `promote_pin=True` (in-process)

## Follow-up

Harvest when wall clock ≥24–48h: read out JSON, write summary artifact, confirm flags restored false.
Do **not** invent PnL if process dies early — document interrupt instead.

## Related

- Recipe: `docs/recipes/ops/paper-fund-z-fee-amortization-and-48h-soak-recipe-2026-09-26.md`
- Amortization study: `docs/artifacts/ops/paper-fund-z-fee-amortization-study-2026-09-26.md`
- Prior 6h soak: #181
