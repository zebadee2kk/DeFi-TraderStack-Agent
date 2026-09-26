# Interrupt note — fund_z multi-hour soak attempt 1 (2026-09-26)

**HONESTY: first attempt aborted by WSL reboot; no PnL claimed from it.**

| Item | Value |
|---|---|
| Started | 2026-09-26 ~02:42 BST |
| Worktree | `/tmp/fund-z-fee-aware-soak-wt` |
| Observed before loss | hedges opened BTC+ETH `fund_z_harvest_sign_hold` via promote pin; fees ~0.1999; funding prints 0 in first minutes |
| Cause | WSL reboot (`uptime` ~5 min at 03:12 BST); `/tmp` worktree wiped |
| Recovered PnL | **None** — raw JSON never written; do not invent |
| Restart plan | Persistent worktree under `/home/rham-admin/src/DeFi-TraderStack-Agent-fund-z-soak`; full 6h preferred again |

Smoke (pre-soak, 90s) is the only completed fee-aware print before interrupt and is
**not** the multi-hour result.
