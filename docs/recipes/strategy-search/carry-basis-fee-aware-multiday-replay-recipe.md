# Hedged-carry + dual-basis fee-aware multi-day REPLAY recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26 Europe/London. Re-pin commit SHA in the run report.
**Never flips `PAPER_PROMOTE_*`.** `can_promote=false` / `keep_flag_false=true`.

## Why this exists

#185 scored `fund_z_harvest_sign_hold` fee-survival on **HL asilletto funding alone**
(dual era; HTX hourly absent). This slice reuses the same N∈{3,5,7} fee-survival
helper / fee ladders on **OTHER archived tapes** that have not yet been dual-printed
for this lens: **OKX** and **Binance Vision** PIT basis, paired with the same HL
funding compact, under always-on hedged-carry (funding |rate| + basis Δ).

Distinct from #185 (no basis) and from #175 long WF dual-print. Not a retune of
`HARVEST_CATALOG` / flipcost / xs-rank.

## Probe gate (required before score)

- HL funding compact: `var/ops/basis_cache/asilletto81/daily_sum_abs_btc_eth.json`
  (or rebuild from asset_ctxs; skip-not-invent). BTC+ETH required.
- OKX basis: `var/research/basis/okx/{BTC,ETH}USD_basis_1d.json` on disk.
- Binance Vision basis: `var/research/basis/binance_vision/{BTC,ETH}USD_basis_1d.json`.
- HTX hourly funding: **skip-not-invent** if still absent (as in #183/#185).
- Freeze this recipe **before** any window score.

## Policy (frozen)

- Strategy shape: always-on sign-hold / hedged-carry (same income shape as
  `fund_z_harvest_sign_hold` / `carry_hedged_sign`), **plus** dual_basis PnL.
- Open once at window start; hold N UTC days; no flips inside window.
- Notional: **$100/asset × BTC+ETH = $200**.
- Funding income/day/asset: `notional * daily_sum_abs`.
- Basis income (while in): `notional * (prev_basis - current_basis)` on days with
  both previous and current PIT values; missing days omit basis that day (never invent).
- MTM mid moves: **omitted** (same honesty as #185).
- Primary fee ladder: paper `PAPER_FEE_BPS=10` fees_usd ×2 (= $0.20). Sensitivities:
  10+5 ($0.30), research 5+5 ($0.20).

## Dual-print policy (dual basis venues)

1. **Primary:** HL funding + **OKX** basis.
2. **Second:** HL funding + **Binance Vision** basis.
3. Window validity: every day in the window has BTC+ETH funding `daily_sum_abs`.
4. Informational dual-print fee-survival passer: tumbling `frac_fee_positive ≥ 0.55`
   on **both** prints for same N + primary ladder. Still `can_promote=false`.

## Windows / metrics

Same as #185: N∈{3,5,7}; tumbling primary + sliding denser; report mean/median/p10/p90
fee_aware (= funding + basis − fees), fraction_fee_positive, mean_funding, mean_basis.

## Exact command

```bash
traderstack-carry-basis-fee-aware-replay \
  --asilletto-compact var/ops/basis_cache/asilletto81/daily_sum_abs_btc_eth.json \
  --basis-dir var/research/basis \
  --output-md docs/artifacts/strategy-search/carry-basis-fee-aware-multiday-replay.md \
  --output-json docs/artifacts/strategy-search/carry-basis-fee-aware-multiday-replay.json
```

## Explicit non-goals

- Do not kill PID 45859 / touch soak out except read-only.
- Do not flip PAPER_PROMOTE_* / go live / invent tips or PnL.
- Do not backfill DefiLlama tip days.
- Do not re-score #185 HL-only fund_z dual-era as a new claim.

## Tip at freeze

`origin/main` @ 7b3f18a (#185). Branch: `feat/fee-survival-other-tapes-2026-09-26`.
