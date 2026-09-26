# Paper-perp funding-z threshold harvest dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26. Re-pin commit SHA in the run report.
**Never flips PAPER_PROMOTE_*.** Empty dual-print set is success.

## Why this exists

NOT the rejected HL-HTX funding-div spot overlay (#162). This slice scores
a paper-perp-only funding-z harvest catalog on dual HL x HTX funding tapes,
with explicit dual_basis PnL required (OKX x Binance Vision). Distinct ids
from carry_hedged_sign / existing CARRY_CATALOG. New fee-stress freeze:
paper-perp 5+5 bps x 2 legs with dual_basis mandatory (skip if basis
missing — never score basis-unaware under this recipe).

## Probe gate (required before score)

- Hyperliquid + HTX public funding covering BTC+ETH (live fetch; resample to
  UTC daily sums; empty days omitted).
- OKX + Binance Vision PIT basis files on disk (>=720d BTC+ETH each) via
  --basis-dir. Dual basis required.
- If funding or basis UNAVAILABLE: record skip; do not invent.

## Frozen catalog (new ids; freeze before any score)

- Family label: fund_z_harvest
- Prefix: fund_z_harvest_
- Ids (5; no spot control — this is paper-perp harvest, not spot FeatureZ):
  - fund_z_harvest_z_1_0 — harvest when |funding z| >= 1.0
  - fund_z_harvest_z_1_5 — harvest when |funding z| >= 1.5
  - fund_z_harvest_z_2_0 — harvest when |funding z| >= 2.0
  - fund_z_harvest_abs_2bp — harvest when |rate| >= 2bp (not in CARRY_CATALOG)
  - fund_z_harvest_sign_hold — always harvest |rate| under this recipe fee+basis stress (honest re-score shape; NEW id + NEW fee freeze; not a silent retune of carry_hedged_sign)
- Lookback for z: 20 (same as funding-carry).
- Do not mutate CARRY_CATALOG / FUNDING_Z_CATALOG / FUND_DIV_CATALOG.

## Fee + basis stress (frozen; NEW vs funding-carry-daily)

- Fee: 5 bps + slippage 5 bps, x CARRY_LEGS=2 on each flip.
- Basis: required dual_basis pairing primary x OKX, second x Binance Vision.
  Basis PnL enters only on days with both current and previous PIT values.
- Gate C fee stress: 2x fees still clear #96 analog (unchanged multiplier).
- This is not pilot spot 80+5.

## Dual-print policy

1. Primary: Hyperliquid funding + OKX basis.
2. Second: HTX funding + Binance Vision basis.
3. Passer: eligible on both prints (BTC and ETH WF total > 0 and holdout > 0).
4. Paper-executable via PAPER_PERP_HEDGE path conceptually; this CLI does
   not flip PAPER_PERP_HEDGE or any PAPER_PROMOTE_*.

## Exact command

traderstack-fund-z-harvest --live --interval 1d --basis-dir var/research/basis --fee-bps 5 --slippage-bps 5 --output-md docs/artifacts/strategy-search/fund-z-harvest-paper-perp-dual-print.md --output-json var/ops/fund_z_harvest_paper_perp_dual_print.json

## Promote

Keep every PAPER_PROMOTE_*=false. Even if a dual-print passer appears, a
Settings pin is a separate default-false PR. No live path.
