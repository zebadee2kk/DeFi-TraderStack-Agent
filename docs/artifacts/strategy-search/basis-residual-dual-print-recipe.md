# Basis residual / cash-and-carry residual dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26. Re-pin commit SHA in the run report.
**Never flips PAPER_PROMOTE_*.** Empty dual-print set is success.

## Why this exists

Spot FeatureZ catalogs #160-#173 emptied. This slice pivots to an ALTERNATIVE
family that uses EXISTING PIT dual_basis files (OKX + Binance Vision
mark-index) already proven in funding-carry-daily.md. It does **not**
retune xs-topk, fund_div, ens_trend_v2, sess-gap, vol-target, oi_mom, or
candle families from #104/#108/#116-#123.

## Probe gate (required before score)

- OKX daily mark-index JSON under var/research/basis/okx/*_basis_1d.json
  (from traderstack-download-basis): BTC+ETH each >=720 UTC days.
- Binance Vision daily mark-index JSON under
  var/research/basis/binance_vision/*_basis_1d.json: BTC+ETH each >=720 UTC days.
- Dual basis = both venues clear >=720d on BTC and ETH.
- If either venue UNAVAILABLE: commit probe report + this recipe; refuse
  single-venue promote; do not invent basis.

## Frozen catalog (new ids; freeze before any score)

- Family label: basis_resid
- Prefix: basis_resid_
- Ids (6 + informational control ma_cross_10_30 which cannot promote):
  - basis_resid_mr_fade_1_0 / _1_5 / _2_0 - mean-reversion (fade) on basis z
  - basis_resid_mom_follow_1_0 / _1_5 / _2_0 - momentum (follow) on basis z
- Lookback: Z_LOOKBACK=20
- Thresholds: |z| >= 1.0 / 1.5 / 2.0 (frozen; do not grow after seeing PnL)
- Do **not** mutate CARRY_CATALOG / FUNDING_Z_CATALOG / FUND_DIV_CATALOG.

## Feature + residual PnL (frozen)

1. Load PIT mark-index series from disk (OKX, Binance Vision). Never invent.
2. At day t, FeatureZ uses only basis points with ts <= t and trailing
   lookback=20; missing days omitted (never zero-filled).
3. Fade (mr): when z >= +entry -> short the basis (expect compression);
   when z <= -entry -> long the basis. Flat otherwise.
4. Follow (mom): opposite of fade.
5. Residual PnL while short-basis: prev_basis - current_basis; while
   long-basis: current_basis - prev_basis. Applied only when both current
   and previous day have a PIT value.
6. Two-leg fee on each flip: frozen research paper-perp model
   5 bps fee + 5 bps slippage x 2 legs (not Kraken spot 80+5).

## Dual-print policy

1. Primary print: OKX basis residual catalog (BTC+ETH).
2. Second print: Binance Vision basis residual catalog (BTC+ETH).
3. A name is a dual-print passer only if eligible (WF total > 0 and holdout
   excess > 0 on both BTC and ETH) on both venues.
4. Control cannot promote. Empty set is success.

## Executability (honest)

- Research-only for residual PnL scored here (basis change harvest).
- Paper-perp path exists via PAPER_PERP_HEDGE for related hedged carry,
  but this catalog does not auto-enable it and does not flip any promote.
- Not Kraken-spot executable as a pure basis residual.

## Exact command

traderstack-basis-residual --basis-dir var/research/basis --fee-bps 5 --slippage-bps 5 --output-md docs/artifacts/strategy-search/basis-residual-dual-print.md --output-json var/ops/basis_residual_dual_print.json

## Promote

Keep every PAPER_PROMOTE_*=false. This CLI never adds or flips a promote pin.
TRADING_MODE stays paper. No live path.
