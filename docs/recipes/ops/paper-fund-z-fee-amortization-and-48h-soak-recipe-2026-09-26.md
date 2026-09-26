# Paper fund_z fee-amortization study + ≥24h soak — PRE-REGISTRATION (2026-09-26)

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PnL. NOT EDGE PROVEN.**

Frozen **before** enabling soak flags and before scoring the amortization study.
Builds on:

- #181 ~6h fund_z fee-aware soak (`fee_aware_paper_pnl_usd=-0.064699`)
- #176 host fee-aware harvest tooling (`ops/paper_carry_pnl_soak/host_fee_aware_probe.py`)
- #177 / #175 named passer `fund_z_harvest_sign_hold` (dual-print research; pin stays false)

## Goal

1. **Honest fee-amortization study** on EXISTING on-disk HL funding tapes (asilletto81
   `asset_ctxs` hourly-last → daily sum of `|funding|` under sign-hold). HTX hourly
   tape: skip-not-invent if absent on disk.
2. Optionally start a **background ≥24h** (prefer **48h**) host fee-aware paper soak
   using #181 tooling. Flags only via `Settings.model_copy` / process env — restore false.
   If unsupervised harvest cannot finish in one agent turn: detach soak, commit recipe +
   started note (PID/out path), open analysis PR now; leave harvest for follow-up.

## Fee assumptions (frozen; match #176/#181)

| Leg | Assumption | Notes |
|---|---|---|
| Spot (if booked) | Pilot Kraken Pro Tier-1 **taker 80 bps** + **5 bps** slip | Synthetic spot **not** booked — spot fee **not** charged |
| Perp open (paper soak) | `PAPER_FEE_BPS=10` + `PAPER_SLIPPAGE_BPS=5` | `fees_usd` charges **fee_bps only**; slip in adverse fill. #181 observed `fees_usd≈0.1999` on $100×2 |
| Research dual-print (#175) | **5+5 bps × 2 legs** | Different from paper soak 10+5 — document both |
| Maker / rebate | **Not assumed** | Sensitivity ladder may model 0+5; not a claim |

Sensitivity ladders (amortization only): **10+5**, **5+5**, **2+2**, maker **0+5** — each × 2 legs (BTC+ETH), $100 notional/asset.

## Funding tape rules

- Use EXISTING HL (+ HTX if useful) tapes already on disk.
- **Do NOT invent funding series.** Skip-not-invent.
- Primary tape: `var/ops/basis_cache/asilletto81/asset_ctxs/*.csv.lz4` (`funding` col).
  Method: last funding print per UTC hour → `daily_sum_abs = sum(|hourly|)` for sign-hold.
- Cross-check only: `daily_funding_last_core100.json` (end-of-day last rate — **not** daily sum).

## Opt-in flags (defaults stay false; Field definitions never flipped)

| Setting | Default | Soak window only |
|---|---|---|
| TRADING_MODE | paper | paper |
| PAPER_PERP_HEDGE | false | true via Settings.model_copy |
| PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD | false | true via Settings.model_copy |
| Every other PAPER_PROMOTE_* | false | unchanged false |
| PAPER_CARRY_HEDGE_DIAGNOSTIC | false | leave false |

Restore **all** soak flags to **false** after the window. Do **not** flip Settings Field defaults. Do **not** set TRADING_MODE=live.

## Pre-registered soak duration

| Surface | Target | Partial |
|---|---|---|
| Host fee-aware probe `--mode fund_z` | **≥24h**; prefer **48h** if machine stable | Detach + started note if unsupervised |

## Explicit non-goals

- Do **not** invent PnL, funding, basis, or mids.
- Do **not** treat dual-print WF passer as short-horizon paper profit.
- Do **not** leave promote/perp flags true after soak.
- Do **not** go live.

## Artifacts

- Recipe (this file)
- Study report: `docs/artifacts/ops/paper-fund-z-fee-amortization-study-2026-09-26.md`
- Raw JSON: `docs/artifacts/ops/fund-z-fee-amortization-study-raw-2026-09-26.json`
- Soak started note: `docs/artifacts/ops/paper-fund-z-fee-aware-48h-soak-started-2026-09-26.md`
- Raw soak out: durable under `var/ops/_fund_z_fee_aware_48h_soak_20260926/` (host home repo var)

## Tip at freeze

`origin/main` @ fc30e5b (#181). Branch: `research/fund-z-fee-amortization-2026-09-26`.
