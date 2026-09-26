# Edge-status memo — 2026-09-26

**Repo tip at score:** weekly hyp-C on `feat/weekly-lowturn-dual-print-2026-09-26` (recipe commit `dd527d1` before score; prior A+B on `feat/basis-residual-and-fund-harvest-2026-09-26`).

Paper / research only. Summarises the **post-#174 pivot** away from empty spot FeatureZ catalogs #160–#173 toward ALTERNATIVE strategies on EXISTING PIT basis + funding tapes. **Not a profitability claim.** All `PAPER_PROMOTE_*` defaults stay **false**. `TRADING_MODE` stays `paper`. No live path.

## Standing promote bar (unchanged)

A name cannot enter a paper pin unless **all** hold:

1. Dual independent prints (two venues **or** two non-overlapping eras).
2. Fee-aware walk-forward total return > 0 and holdout excess > 0 on **both** BTC and ETH.
3. Catalog + print policy frozen **before** the pull.
4. An operator-facing `PAPER_PROMOTE_*` flag is added only after a committed report names a passer, and that flag still defaults **false**.

Skip-not-invent. Pilot fees 80+5 when scoring **spot** legs. Paper only.

## Pivot choice

Prefer **A+B** — both data paths AVAILABLE on disk / live:

| hyp | family | data | result |
| --- | --- | --- | ---: |
| A | `basis_resid_*` | OKX + Binance Vision PIT mark−index (re-downloaded 2026-09-26) | **0** dual-print passers |
| B | `fund_z_harvest_*` | HL × HTX funding + required dual_basis OKX × Vision | **1** dual-print passer |
| C | `wk_trend_*` | Kraken × Coinbase daily→Friday-UTC weekly | **0** dual-print passers |

Skipped: D HL cross-sectional funding rank (not probed — A+B+C preferred).

Dead catalogs **not** retuned: xs-topk, xs_topk_lt, fund_div spot #162, ens_trend_v2, sess-gap, vol-target, oi_mom, candle families #104/#108/#116–#123, inventing DefiLlama history.

## A — Basis residual

Pre-registered recipe:
`docs/artifacts/strategy-search/basis-residual-dual-print-recipe.md`

Score:
`docs/artifacts/strategy-search/basis-residual-dual-print.md`

- Catalog: 6 `basis_resid_{mr_fade|mom_follow}_{1_0|1_5|2_0}` + control note
- Fees: **5+5 bps × 2 legs** (research paper-perp model; not spot 80+5)
- Dual-print: OKX × Binance Vision
- Executability: **research-only** residual PnL (basis change harvest); not Kraken-spot
- Result: **dual_print_passers=0**; `can_promote=false`; `keep_flag_false=true`

## B — Paper-perp funding-z harvest

Pre-registered recipe:
`docs/artifacts/strategy-search/fund-z-harvest-paper-perp-dual-print-recipe.md`

Score:
`docs/artifacts/strategy-search/fund-z-harvest-paper-perp-dual-print.md`

- Catalog: 5 NEW ids distinct from `CARRY_CATALOG` / spot fund_div
- Fees: **5+5 bps × 2 legs** with **required** dual_basis (NEW fee+basis stress vs funding-carry-daily)
- Dual-print: HL funding×OKX basis + HTX funding×Binance Vision basis
- Executability: **paper-perp** via `PAPER_PERP_HEDGE` path conceptually; CLI does **not** flip that flag
- Result: **dual_print_passers=1**; `can_promote=false`; `keep_flag_false=true`

### Named passer (informational; no Settings pin)

| field | value |
| --- | --- |
| id | `fund_z_harvest_sign_hold` |
| family | `fund_z_harvest` |
| fees | 5 bps + 5 bps slip × 2 legs |
| funding venues | Hyperliquid × HTX |
| basis venues | OKX × Binance Vision (modeled) |
| primary WF / holdout | +1.68% / +3.42% |
| second WF / holdout | +1.47% / +3.12% |
| hard gates | combined=true on both prints (#96/A/B/C) |
| paper-executable | conceptually via `PAPER_PERP_HEDGE` (defaults **false**; not flipped) |
| Kraken-spot | **no** |

Honesty: this is the always-harvest |rate| shape under a **new** recipe id + fee+basis freeze — not a silent retune of `carry_hedged_sign`. z-threshold and abs-2bp variants all failed. No `PAPER_PROMOTE_*` pin added.


## C — Weekly / low-turnover trend (this PR)

Pre-registered recipe (committed **before** score):
`docs/recipes/strategy-search/weekly-lowturn-trend-dual-print-recipe.md` (recipe commit `dd527d1`)

Score:
`docs/artifacts/strategy-search/weekly-lowturn-trend-dual-print.md`

- Catalog: 6 NEW `wk_trend_*` ids (weekly SMA 4/12 & 10/40, Donchian 20/40, TSMOM sign 12/26)
- Resample: **Friday UTC close** from existing Kraken × Coinbase `1d` archives → `1w` (102 / 103 weekly bars)
- Fees: **80 bps + 5 slip** (Kraken Pro tier-1 taker) for spot legs; Gate C 160+10
- Dual-print: concurrent Kraken × Coinbase (`concurrent_venue_harder_gates`)
- Executability: **Kraken-spot** path (unlike fund_z paper-perp)
- Result: **dual_print_passers=0**; `can_promote=false`; `keep_flag_false=true`

Honesty: not a retune of ens_trend_v2 / daily TSMOM / Donchian / xs-topk / sess-gap / vol-target / oi_mom / candle catalogs #104/#108/#116–#123. Empty dual-print set is success. No `PAPER_PROMOTE_*` pin.

## DefiLlama PIT tip (separate)

`traderstack-defillama-stable-snapshot --live` on 2026-09-26:

- as_of=`2026-09-26`; tip_day=`2026-09-25`
- **tip_days=2** (was 1)
- No Sep 19–25 backfill
- `enough_for_dual_print=false` (min=720)
- Note: `docs/artifacts/strategy-search/defillama-stable-pit-snapshot-2026-09-26.md`

## Operator recommendation

1. **Keep every `PAPER_PROMOTE_*=false`.** Do not enable `PAPER_PERP_HEDGE` from this memo alone.
2. Default-false pin added: `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD` (`paper_promote_fund_z_harvest_sign_hold`). Defaults **false**; paper-perp only via `PAPER_PERP_HEDGE`. See `docs/artifacts/ops/paper-promote-fund-z-harvest-sign-hold-2026-09-26.md`. Still not a live/profit claim.
3. Continue daily DefiLlama tips until ≥720.
4. Next pivot candidates (do not retune failed spot catalogs):
   - Fee-aware **paper** PnL accounting on open carry / harvest hedges under `PAPER_PERP_HEDGE` diagnostic (still default false)
   - Weekly / low-turnover trend (hyp C) — **scored 2026-09-26; 0 dual-print passers; do not retune**
   - Maker/rebate path — blocked until post-only fill-rate evidence
