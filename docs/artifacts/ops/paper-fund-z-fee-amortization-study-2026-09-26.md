# fund_z_harvest_sign_hold fee-amortization study (2026-09-26)

**HONESTY: PAPER / RESEARCH ONLY. NOT A PROMOTE. NOT LIVE PnL.**

Pin stays false. `PAPER_PROMOTE_*` Field defaults stay false.

## Context

| Item | Value |
|---|---|
| Named passer | `fund_z_harvest_sign_hold` |
| #181 6h soak | `fee_aware_paper_pnl_usd=-0.064699` (fees 0.1999 ≫ funding 0.0132) |
| Dual-print (#175) | primary WF **+1.68%** / holdout **+3.42%**; second **+1.47%** / **+3.12%** |
| Research fees | **5+5 bps × 2 legs** |
| Paper soak fees (#176/#181) | **PAPER_FEE_BPS=10** + **PAPER_SLIPPAGE_BPS=5** (`fees_usd` = 10 bps only) |

## Funding tape (skip-not-invent)

| Field | Value |
|---|---|
| Source | `var/ops/basis_cache/asilletto81/asset_ctxs/*.csv.lz4` (HL) |
| Method | Last `funding` per UTC hour → daily `sum(|hourly|)` under sign-hold |
| Days | **760** (`20240101` → `20260601`, cut at study date) |
| Hours/day | mean **23.58**, median **24** |
| HTX | **SKIP** — no HTX hourly funding tape on disk (only dual-print result JSONs) |

### Mean / median `|funding|` per day (sign-hold)

| Asset | mean daily ∑\|rate\| | median daily ∑\|rate\| | mean as bps/day |
|---|---:|---:|---:|
| BTC | **0.00037211** | **0.00029836** | 3.72 |
| ETH | **0.00036576** | **0.00029007** | 3.66 |

Cross-check `daily_funding_last_core100.json` (end-of-day **last** rate, not sum): BTC mean |last| ≈ 1.66e-5 — ~22× smaller than daily sum, as expected for hourly settlements. **Do not use last-of-day alone for amortization.**

## Days-to-breakeven (open fee vs mean daily sign-hold income)

Notional: **$100/asset × BTC+ETH = $200** (matches #181).  
Mean combined daily funding income ≈ **$0.0738**/day. Median ≈ **$0.0588**/day.

| Ladder | Open cost USD | Days BE (mean) | Days BE (median) | Notes |
|---|---:|---:|---:|---|
| **Paper #176/#181 fees_usd only (10 bps × 2)** | **0.2000** | **2.7** | **3.4** | Matches observed #181 `fees_usd≈0.1999` |
| **Paper freeze text 10+5 × 2** | **0.3000** | **4.1** | **5.1** | fee+slip as open drag |
| **Research dual-print 5+5 × 2** | **0.2000** | **2.7** | **3.4** | #175 scoring fees |
| Sensitivity 2+2 × 2 | 0.0800 | 1.1 | 1.4 | sensitivity only |
| Maker 0+5 × 2 (if modeled) | 0.1000 | 1.4 | 1.7 | #176/#181: maker **not** assumed |

### Exact fee assumption matching #176/#181

- Freeze text: perp open = `PAPER_FEE_BPS=10` + `PAPER_SLIPPAGE_BPS=5`.
- Book `fees_usd` charges **10 bps** on fill notional; slippage moves fill price (affects MTM), not the fees line.
- #181: 2 hedges, `$100` notional/asset → `fees_usd=0.1999`.
- Spot 80+5 **not** charged (synthetic spot not booked).
- Maker/rebate **not** assumed.

## Dual-print WF vs amortization horizon

| Check | Result |
|---|---|
| Research open cost @ 5+5 on $100×2 | $0.20 |
| Days to amortize @ tape mean income | **~2.7 days** |
| Implied avg daily net from +1.68% WF / ~801 bars | ~0.0021%/day |
| Consistent? | **Yes** — multi-hundred-day WF can be positive after ~3d fee amortization; **does not** imply 3–6h paper profit under 10 bps open fees |

### Paper soak vs dual-print (honesty)

> **Research passer ≠ short-horizon paper profit under current open fees.**

- Dual-print scored **5+5** over ~800 daily bars and found `fund_z_harvest_sign_hold` eligible on both HL×OKX and HTX×Vision prints — with `can_promote=false` / `keep_flag_false=true`.
- Host paper soak (#181) uses **PAPER_FEE_BPS=10** and a **~6h** window: funding (~$0.013) ≪ open fees (~$0.20) → `fee_aware_paper_pnl_usd=-0.064699`.
- Tape-implied funding over 6h at mean rate ≈ $0.018 — same order as observed #181 funding; confirms short-horizon fee dominance.
- Keep `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD=false`. No live path.

## 48h soak status

See `docs/artifacts/ops/paper-fund-z-fee-aware-48h-soak-started-2026-09-26.md` (detached start; harvest follow-up).

## Raw

`docs/artifacts/ops/fund-z-fee-amortization-study-raw-2026-09-26.json`
