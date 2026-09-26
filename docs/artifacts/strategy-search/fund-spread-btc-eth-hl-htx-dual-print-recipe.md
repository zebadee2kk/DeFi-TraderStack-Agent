# BTC-ETH relative funding / funding-spread HL x HTX dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26. Re-pin commit SHA in the run report.
**Never flips PAPER_PROMOTE_*.** Empty dual-print set is success.

## Why this exists

Post-#179: fund_xs_rank dual-era empty; fund_z_harvest_sign_hold remains the only
research passer. This slice scores a NEW family — BTC funding vs ETH
funding differential (and/or residual after demeaning) — dual print on
Hyperliquid x HTX. Distinct from:

- BTC-ETH price RV (rv_fade_* / rv_follow_*; already empty)
- HL-HTX same-asset funding-div SPOT overlay #162 (fund_div_hl_htx_*; empty)
- fund_z_harvest_sign_hold (same-asset carry harvest)
- fund-xs-rank #179 (cross-sectional across coins)

Prefer concurrent HL x HTX when both venues have BTC+ETH funding coverage.
Fall back to dual non-overlapping eras on one venue only if concurrent tape
is insufficient (skip-not-invent).

## Probe gate (required before score)

- Hyperliquid + HTX public funding covering BTC and ETH (live fetch;
  resample to UTC daily sums; empty days omitted, never zero-filled).
- Per venue: intersection of BTC and ETH UTC days must be long enough for
  walk-forward (>= HARD_GATE_MIN_DAILY_BARS = 720 preferred; short tape uses
  SHORT walk-forward sizes and may still score if >= MIN_RESEARCH_BARS + holdout).
- Freeze coverage / dual-print cells before any candidate PnL.
- If funding UNAVAILABLE on a venue or pair intersection too short: record
  skip; do not invent. Empty dual-print set is success.

## Frozen catalog (new ids; freeze before any score)

- Family label: fund_spread_btc_eth
- Prefix: fund_spread_btc_eth_
- Ids (5 + informational flat control; <=6; no mutate of prior catalogs):
  - fund_spread_btc_eth_sign_hold — always dollar-neutral short higher-funding /
    long lower-funding of {BTC, ETH} by sign of daily spread f_BTC - f_ETH
  - fund_spread_btc_eth_z_1_0 — same harvest when |z(spread)| >= 1.0
  - fund_spread_btc_eth_z_1_5 — |z| >= 1.5
  - fund_spread_btc_eth_z_2_0 — |z| >= 2.0
  - fund_spread_btc_eth_demean_sign — demean spread (subtract trailing lookback
    mean), then sign-harvest the residual
  - fund_spread_btc_eth_flat — always-flat control (cannot promote)
- Lookback for z / demean: Z_LOOKBACK=20
- Signal: UTC-daily funding sum per asset; align on intersection of BTC and
  ETH days per venue (skip-not-invent missing pair days).
- Position: dollar-neutral |w_BTC|=|w_ETH|=1, opposite signs. Income under
  perp convention (long pays funding): -w_BTC*f_BTC - w_ETH*f_ETH.
- Rebalance: daily; fee on each position change (enter / exit / flip).
- Do not mutate CARRY_CATALOG / HARVEST_CATALOG / FUND_DIV_CATALOG /
  RANK_CATALOG / rv_* / weekly catalogs after seeing PnL.

## Fee stress (frozen)

- Paper-perp model: 5 bps + 5 bps slippage x CARRY_LEGS=2 on each
  position change (both legs).
- Not pilot spot 80+5. Gate-C analog: 2x fees still required when hard gates
  are computed.

## Dual-print policy (prefer concurrent venues)

1. Primary print: Hyperliquid BTC+ETH funding (pair-aligned).
2. Second print: HTX BTC+ETH funding (pair-aligned).
3. Concurrent preferred when both venues clear the coverage probe.
4. Fallback (only if concurrent insufficient): two non-overlapping eras on the
   longer single venue — freeze era bounds from coverage before PnL; else skip.
5. Passer: fee-aware walk-forward mean total return > 0 and holdout excess
   > 0 on both prints. Control cannot promote.
6. Ranking key (informational): mean holdout excess among dual-print passers.
7. Paper-executable conceptually via PAPER_PERP_HEDGE; this CLI does not
   flip PAPER_PERP_HEDGE or any PAPER_PROMOTE_*. Not Kraken-spot.

## Walk-forward (frozen)

- holdout_fraction=0.20
- Default train=180 test=60 step=60; short tape falls back to 80/40/40 via
  choose_walkforward
- Compound daily net returns (funding income - fees). No price path invented.

## Exact command

```bash
traderstack-fund-spread-btc-eth \
  --live \
  --fee-bps 5 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/fund-spread-btc-eth-hl-htx-dual-print.md \
  --output-json var/ops/fund_spread_btc_eth_hl_htx_dual_print.json
```

## Promote

Keep every PAPER_PROMOTE_*=false. Even if a dual-print passer appears, a
Settings pin is a separate default-false PR. No live path.
