# Funding-momentum (rate-change) HL×HTX dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26. Re-pin commit SHA in the run report.
**Never flips PAPER_PROMOTE_*.** Empty dual-print set is success.

## Why this exists

Post-#180/#181: funding-spread empty; fund_z_harvest_sign_hold paper soak
~6h was **fee-negative**. Spot catalogs #160–#173 / weekly #178 empty.
This slice scores a **NEW** family — same-asset **funding momentum / rate
change** (Δfunding), dual print on Hyperliquid × HTX — distinct from:

- `fund_z_harvest_sign_hold` / level |rate| harvest (#175; NOT a retune)
- BTC–ETH funding-spread #180 (`fund_spread_btc_eth_*`)
- HL asilletto fund-xs-rank #179 (`fund_xs_rank_*`)
- HL−HTX funding-div spot overlay #162

## Probe gate (required before score)

- Hyperliquid + HTX public funding covering BTC+ETH (live fetch; resample
  to UTC daily sums; empty days omitted, never zero-filled).
- Per venue: BTC and ETH each need usable daily tape for walk-forward
  (≥ HARD_GATE_MIN_DAILY_BARS = 720 preferred).
- Freeze coverage / dual-print cells **before** any candidate PnL.
- If funding UNAVAILABLE: record skip; do not invent. Empty set success.
- Dual basis **not** required for this recipe (funding-only momentum).

## Frozen catalog (new ids; freeze before any score)

- Family label: `fund_mom`
- Prefix: `fund_mom_`
- Ids (5 + flat control; ≤6; do not mutate prior catalogs):
  - `fund_mom_delta_sign` — position = −sign(Δf); Δf = last − prior daily funding
  - `fund_mom_delta_z_1_0` — same when |z(Δf)| ≥ 1.0 over lookback
  - `fund_mom_delta_z_1_5` — |z(Δf)| ≥ 1.5
  - `fund_mom_delta_z_2_0` — |z(Δf)| ≥ 2.0
  - `fund_mom_confirm_sign` — harvest −sign(rate) only when sign(Δf)==sign(rate)
  - `fund_mom_flat` — always-flat control (cannot promote)
- Lookback for z: Z_LOOKBACK=20
- Income (perp convention, long pays): `−position * rate`
- Rebalance: daily; fee on each position change
- Do not mutate CARRY_CATALOG / HARVEST_CATALOG / FUND_DIV / RANK / SPREAD

## Fee stress (frozen)

- Paper-perp model: **5 bps + 5 bps slip × CARRY_LEGS=2** on each flip.
- Not pilot spot 80+5.

## Dual-print policy

1. Primary: Hyperliquid BTC+ETH funding (per-asset scores).
2. Second: HTX BTC+ETH funding.
3. Passer: fee-aware WF total > 0 **and** holdout excess > 0 on **both**
   BTC and ETH on **both** prints. Control cannot promote.
4. Paper-executable conceptually via `PAPER_PERP_HEDGE`; CLI does not flip
   that flag or any `PAPER_PROMOTE_*`. Not Kraken-spot.

## Exact command

```bash
traderstack-fund-mom-delta \
  --live \
  --fee-bps 5 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/fund-mom-delta-hl-htx-dual-print.md \
  --output-json var/ops/fund_mom_delta_hl_htx_dual_print.json
```

## Promote

Keep every `PAPER_PROMOTE_*=false`. Even if a dual-print passer appears, a
Settings pin is a separate default-false PR. No live path.
