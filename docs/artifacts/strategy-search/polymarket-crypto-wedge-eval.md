# Polymarket crypto-threshold vs Deribit — fee-aware evaluation

Report-only. Not a live-capital claim. Not a reason to flip `PAPER_PROMOTE_*` or `TRADING_MODE`. An empty or negative result is success.

## What this does / does not claim

This CLI scores the pre-registered #142 wedge rule (`|wedge| >= 0.05` + Crucix clear) after conservative Polymarket taker fees. It is **not** a validated wedge edge, not an arbitrage (expiry_gap_hours), and not a CLOB/Deribit trading path. Hedged PnL is skipped unless option fill inputs exist.

## Honesty / pre-registered rules

Frozen in `crypto_models.CRYPTO_WEDGE_RULES` and `docs/artifacts/strategy-search/polymarket-crypto-wedge-eval-recipe.md` before scoring. Settlement is never a mid. `PAPER_PROMOTE_POLYMARKET_CRYPTO_WEDGE` is not a Settings field. Every existing `PAPER_PROMOTE_*` stays default false. No live. Empty / negative is success.

## Print policy (frozen before scoring)

| print | when | can promote? |
| --- | --- | --- |
| single-print | fewer than two independent packs | **no** |
| dual-print | BTC vs ETH or non-overlapping dates / disjoint resolution sources; each clears calculator floor | still **no** Settings flip |

This run: print_kind=`single_print`; independent=`false` (fewer_than_two_prints).

## Parameters

- wedge_threshold=0.05; model=bs_n_d2_markiv_interp_v1; holdout_fraction=20%; MIN_ROWS_PER_PRINT=20; MIN_TRADES_PER_PRINT=8.
- multi_print_bar_preregistered=true.

## Data

- TRADING_MODE=paper; report-only; venue_submitted=false
- Tape/settlement files are operator/fixture input. polymarket_crypto_wedge_tape n=66
- No --settlements supplied; rows that clear the wedge+Crucix mask are recorded as unsettled (skip-not-invent), not scored.
- Primary metric is unhedged Polymarket conservative PnL after frozen taker fee. Hedged Deribit path skipped_not_invented without option fills.
- PAPER_PROMOTE_POLYMARKET_CRYPTO_WEDGE is not a Settings field; can_promote stays false.

## Prints

### `polymarket_crypto_wedge_tape`

rows=47 decision=47 would_trade=0 stand_aside=47 below_threshold=0 unsettled=0 lookahead=0 non_ok=0.
Conservative treatment PnL (probability points, $1 notional): +0.0000 vs hold +0.0000 vs fade +0.0000. Mid-fill treatment (cannot promote): +0.0000.
Holdout: fail-closed (insufficient eligible rows).
Fail-closed reason: `no_eligible_trades`. Hedged: `skipped_not_invented`. clears_calculator=false.

## Promotion decision

**No candidate is promoted.** print_kind=`single_print`; can_promote=`false`; can_enter_promotion_average=`false`; keep_flag_false=`true`; recommended_promote_flag=`none`. `PAPER_PROMOTE_POLYMARKET_CRYPTO_WEDGE` is not a Settings field. Leave every `PAPER_PROMOTE_*` false. Do not enable live.

## Operator smoke (2026-09-18)

- `traderstack-polymarket-crypto-collect --once` reached Gamma + CLOB + Deribit (GET-only).
- Tape rows appended locally under `var/audit/` (not committed).
- Crucix `not_configured` in this environment: every decision row stood aside (gate can only remove).
- No `--settlements` pack: no scored trades (skip-not-invent). Hedged path `skipped_not_invented`.
- Recipe was pre-registered before this score: `polymarket-crypto-wedge-eval-recipe.md`.
- Weather path (#141/#157) unchanged; empty weather tape still cannot dual-print promote.

