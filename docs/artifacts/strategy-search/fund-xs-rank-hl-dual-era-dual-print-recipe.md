# HL asilletto cross-sectional funding-rank dual-era dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26. Re-pin commit SHA in the run report.
**Never flips `PAPER_PROMOTE_*`.** Empty dual-print set is success.

## Why this exists

Post-#174/#175 pivot: spot FeatureZ catalogs and weekly hyp C (#178) are empty.
Paper-perp `fund_z_harvest_sign_hold` is the only research passer so far. This
slice scores a **NEW** family — cross-sectional funding rank on the on-disk
Hyperliquid multi-asset asiletto81 `asset_ctxs` funding column — dual **era**
(not a retune of `CARRY_CATALOG` / `fund_z_harvest_*` / spot `fund_div` / xs-topk).

Preferring available data over invention. HTX multi-asset funding is **not**
required for this recipe (dual era on one venue). Distinct from BTC−ETH price
RV and from HL−HTX same-asset funding-div spot #162.

## Probe gate (required before score)

- asiletto81 cache `var/ops/basis_cache/asilletto81/asset_ctxs/*.csv.lz4` with
  a `funding` column and **≥8** coins with long tapes across the archive.
- Archive window frozen at asiletto bounds: 2024-01-01 → 2026-06-01 UTC.
- If cache missing / fewer than 8 coins / eras too short: record skip; do not invent.

## Frozen catalog (new ids; freeze before any score)

- Family label: `fund_xs_rank`
- Prefix: `fund_xs_rank_`
- Ids (5 + informational control; no mutate of prior catalogs):
  - `fund_xs_rank_ls_k3` — dollar-neutral long bottom-3 / short top-3 by daily last funding
  - `fund_xs_rank_ls_k5` — long bottom-5 / short top-5
  - `fund_xs_rank_ls_k8` — long bottom-8 / short top-8
  - `fund_xs_rank_short_top_k5` — short-only top-5 (high funding)
  - `fund_xs_rank_long_bottom_k5` — long-only bottom-5 (low funding)
  - `fund_xs_rank_ew_flat` — always-flat control (cannot promote)
- Universe: frozen CORE_UNIVERSE (100 coins present across archive samples;
  always includes BTC+ETH). Daily eligibility = coins with a finite funding
  print that day ∩ CORE_UNIVERSE. `MIN_CROSS_SECTION=8` → flat day if fewer.
- Signal: last `funding` print per UTC day per coin (skip-not-invent missing).
- Rebalance: daily; weights equal within each sleeve; dollar-neutral for `ls_*`.
- Do **not** mutate `CARRY_CATALOG` / `HARVEST_CATALOG` / `FUND_DIV_CATALOG` /
  `TOPK_CATALOG` / `LOWTURN` after seeing PnL.

## Fee stress (frozen)

- Paper-perp model: **5 bps + 5 bps slippage × `CARRY_LEGS=2`** applied to
  gross turnover `0.5 * Σ|Δw_i|` on each rebalance.
- Not pilot spot 80+5. Gate-C analog: 2× fees still required for hard-gate
  combined when hard gates are computed.

## Dual-print policy (dual era)

1. Primary era A: 2024-01-01 → 2025-01-15 UTC (inclusive).
2. Second era B: 2025-01-16 → 2026-06-01 UTC (inclusive).
3. Each era needs ≥300 daily panel days with ≥8 eligible coins; else skip.
4. Passer: fee-aware walk-forward mean total return > 0 **and** holdout excess > 0
   on **both** eras. BTC+ETH must remain in CORE_UNIVERSE (membership gate).
5. Ranking key (informational): mean holdout excess among dual-era passers.
6. Paper-executable conceptually via multi-asset `PAPER_PERP_HEDGE` path; this
   CLI does **not** flip `PAPER_PERP_HEDGE` or any `PAPER_PROMOTE_*`. Not Kraken-spot.

## Walk-forward (frozen)

- holdout_fraction=0.20 within each era
- train=80 test=40 step=40 (short tape; eras ~380d)
- Compound daily net returns; no price path invented — funding income only
  under dollar-neutral (or single-sleeve) weights.

## Exact command

```bash
traderstack-fund-xs-rank \
  --asilletto-dir var/ops/basis_cache/asilletto81/asset_ctxs \
  --fee-bps 5 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/fund-xs-rank-hl-dual-era-dual-print.md \
  --output-json var/ops/fund_xs_rank_hl_dual_era_dual_print.json
```

## Promote

Keep every `PAPER_PROMOTE_*=false`. Even if a dual-print passer appears, a
Settings pin is a separate default-false PR. No live path.
