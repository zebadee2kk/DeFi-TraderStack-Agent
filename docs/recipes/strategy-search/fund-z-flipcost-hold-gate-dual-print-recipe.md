# fund_z flip-cost / ≥N-day hold gate dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26. Re-pin commit SHA in the run report.
**Never flips PAPER_PROMOTE_*.** Empty dual-print set is success.

## Why this exists

#183 BE table: research 5+5×2 open fees need **~2.7d** mean daily ∑|f|
to amortize; paper 10+5×2 need **~4.1d**. #181 6h soak was fee-negative.
Named dual-print passer \und_z_harvest_sign_hold\ (#175) has research
edge over ~800d but is **not** short-horizon paper profit under open fees.

This slice re-scores the **sign_hold / always-harvest** shape under an
**explicit flip-cost gate**: only harvest when funding magnitude can
amortize open fees over an N-day hold (N from #183), optionally sticky
for ≥N days. NEW ids. Dual HL×HTX + required dual_basis.

**Honesty:** if the only dual-print passer is the unfiltered sign_hold
reference clone, that is **not a new edge** — same sign_hold under a
hold/filter wrapper. Report passer retention honestly.

Distinct from / do not retune: xs-topk, weekly \wk_trend_*\, fund_spread,
fund_xs_rank, fund_mom, oi_mom, spot FeatureZ, basis_resid #175 empty.

## Probe gate (required before score)

- Hyperliquid + HTX public funding covering BTC+ETH (live fetch; UTC daily
  sums; empty days omitted, never zero-filled). Each venue ≥720 daily.
- OKX + Binance Vision PIT basis on disk (≥720d BTC+ETH) via \--basis-dir\.
  Dual basis **required** (same as #175 fund_z_harvest).
- Freeze coverage before any candidate PnL. Skip-not-invent.

## N from #183 BE table (frozen)

| Ladder | Days BE (mean) | N used |
|---|---:|---:|
| Research dual-print 5+5 × 2 | 2.7 | **3** |
| Paper freeze text 10+5 × 2 | 4.1 | **5** |

## Flip-cost gate (frozen)

- \open_cost = CARRY_LEGS * (fee_bps + slippage_bps) / 10_000- Decision at print *i* uses only \series[:i]\ (no look-ahead).
- **Magnitude enter:** \want = (N * |last_rate| >= open_cost)\ — funding
  magnitude must cover one open over an N-day hold.
- **Sticky min-hold (optional ids):** once in, stay ≥ N daily bars before
  exit even if magnitude drops.
- Income while in: \bs(rate)\ (+ dual_basis PnL when both days present).
- Fee on each flip. Flat otherwise.

## Frozen catalog (new ids; freeze before any score)

- Family label: \und_z_flipcost- Prefix: \und_z_flipcost_- Ids (5 + flat control; ≤6; do **not** mutate HARVEST_CATALOG / CARRY_CATALOG):
  - \und_z_flipcost_be3d\ — magnitude gate N=3; exit when gate fails
  - \und_z_flipcost_be5d\ — magnitude gate N=5; exit when gate fails
  - \und_z_flipcost_be3d_sticky\ — N=3 magnitude enter + min_hold=3
  - \und_z_flipcost_be5d_sticky\ — N=5 magnitude enter + min_hold=5
  - \und_z_flipcost_sign_hold_ref\ — unfiltered always-harvest reference
    (NEW id; same shape as \und_z_harvest_sign_hold\ / \carry_hedged_sign    under this recipe fee+basis freeze — honesty baseline)
  - \und_z_flipcost_flat\ — always-flat control (cannot promote)

## Fee + basis stress (frozen)

- Fee: **5 + 5 bps × CARRY_LEGS=2** on each flip (research dual-print ladder).
- Basis: required dual_basis — primary HL×OKX, second HTX×Binance Vision.
  Skip if basis missing. Never score basis-unaware under this recipe.

## Dual-print policy

1. Primary: Hyperliquid funding + OKX basis.
2. Second: HTX funding + Binance Vision basis.
3. Passer: eligible on both prints (BTC and ETH WF total > 0 and holdout > 0).
   Control cannot promote. \can_promote=false\ always in this CLI.
4. Paper-perp conceptually via \PAPER_PERP_HEDGE\; CLI does not flip that
   flag or any \PAPER_PROMOTE_*\.

## Exact command

\\ash
traderstack-fund-z-flipcost \
  --live \
  --basis-dir var/research/basis \
  --fee-bps 5 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/fund-z-flipcost-hold-gate-dual-print.md \
  --output-json var/ops/fund_z_flipcost_hold_gate_dual_print.json
\
## Promote

Keep every \PAPER_PROMOTE_*=false\. No live path. Empty set success.
