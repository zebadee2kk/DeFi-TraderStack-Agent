# fund_z 48h fee-aware soak — mid-run snapshot (2026-09-26 ~20:08 BST)

**HONESTY: PAPER ONLY. NOT A PROMOTE. NOT LIVE PnL. Soak still running — do not stop PID 45859.**

| Field | Value |
|---|---|
| PID | **45859** (alive at snapshot) |
| Started | 2026-09-26 10:02:33 BST |
| Elapsed | **~10.1 h** of 48 h target |
| Signal | `fund_z_harvest_sign_hold` (runtime `Settings.model_copy` promote pin) |
| Hedges | BTC + ETH open (`spot_side=buy`, $100 notional each, HL) |
| Funding prints | BTC 10 + ETH 10 hourly `paper_perp_funding_applied` |
| Funding sum (est.) | **$0.0237** (BTC 0.0112 + ETH 0.0125) |
| Open fees (est.) | **~$0.20** (#181/#183 paper fees_usd on $100×2) |
| Net vs open fees | **-$0.176** — still fee-negative mid-soak (expected) |
| Probe JSON | not flushed yet (`host_fee_aware_probe.json` written at end) |

Raw: `var/ops/_fund_z_fee_aware_48h_soak_20260926/mid_snapshot.json` + `soak.stdout.log`.

`PAPER_PROMOTE_*` Field defaults on `origin/main` @ f0c9391 remain **false**; soak uses process-local model_copy only.
