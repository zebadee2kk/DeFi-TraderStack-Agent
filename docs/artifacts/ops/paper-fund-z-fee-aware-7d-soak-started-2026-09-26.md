# fund_z 7d fee-aware paper soak — STARTED (2026-09-26)

**HONESTY: PAPER ONLY. NOT A PROMOTE. NOT LIVE PnL. Harvest pending ~2026-10-03.**

Parallel host soak started alongside the still-running 48h soak (PID **45859**).
Flags enabled **only** in-process via `Settings.model_copy` inside
`ops/paper_carry_pnl_soak/host_fee_aware_probe.py --mode fund_z`.
Field defaults and `.env` remain false. `TRADING_MODE=paper`.

## Process

| Field | Value |
|---|---|
| Started (Europe/London) | **2026-09-26 21:08:05 BST** |
| PID | **2638509** |
| Duration requested | **604800 s (~7 days)** |
| Sample every | 300 s |
| Mode / signal | `fund_z` / `fund_z_harvest_sign_hold` |
| Out JSON | `/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_7d_soak_20260926/host_fee_aware_probe.json` |
| Stdout log | `/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_7d_soak_20260926/soak.stdout.log` |
| Stderr log | `/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_7d_soak_20260926/soak.stderr.log` |
| PID file | `/home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_7d_soak_20260926/soak.pid` |
| Worktree cwd | `/tmp/dt-fund-z-7d-soak-20260926` (tip **d67da27** / #186) |
| PYTHONPATH | worktree `src` |
| Interpreter | `/home/rham-admin/src/DeFi-TraderStack-Agent/.venv/bin/python` |
| Expected end (Europe/London) | **~2026-10-03 21:08 BST** |

## Command (exact)

```bash
cd /tmp/dt-fund-z-7d-soak-20260926
PYTHONPATH=/tmp/dt-fund-z-7d-soak-20260926/src \
  nohup /home/rham-admin/src/DeFi-TraderStack-Agent/.venv/bin/python -u \
  ops/paper_carry_pnl_soak/host_fee_aware_probe.py \
  --mode fund_z \
  --duration-seconds 604800 \
  --sample-every-seconds 300 \
  --out /home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/_fund_z_fee_aware_7d_soak_20260926/host_fee_aware_probe.json \
  > .../soak.stdout.log 2> .../soak.stderr.log &
```

## Hygiene (at start)

- `PAPER_PROMOTE_*` Field defaults: **false** (unchanged; verified via fresh `Settings()`)
- `.env` `PAPER_PERP_HEDGE=false`; no `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD=true`
- Probe enables `paper_perp_hedge` + `paper_promote_fund_z_harvest_sign_hold` via **model_copy only**
- Observed at t≈0: BTC+ETH hedges opened with `signal=fund_z_harvest_sign_hold`, `promote_pin=True` (in-process)
- Parallel 48h soak PID **45859** left running; **different** out dir (no collision)

## Related

- Harvest note (Grok-Bot-facing): `docs/artifacts/ops/paper-fund-z-fee-aware-7d-soak-harvest-note-2026-09-26.md`
- Promote-gap memo: `docs/artifacts/strategy-search/fund-z-promote-honesty-gap-2026-09-26.md`
- Prior 48h started note: `docs/artifacts/ops/paper-fund-z-fee-aware-48h-soak-started-2026-09-26.md`
- #185 hist replay / #186 carry+basis replay (both `can_promote=false`)
