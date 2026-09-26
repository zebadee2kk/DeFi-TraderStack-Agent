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
   - ~~Weekly / low-turnover trend (hyp C)~~ scored empty (#178)
   - ~~HL cross-sectional funding rank~~ scored this slice: dual_print_passers=0
   - ~~BTC–ETH relative funding / funding-spread on HL×HTX (option 2)~~ scored this slice: dual_print_passers=0
   - Weekly / low-turnover trend (hyp C) — **scored 2026-09-26; 0 dual-print passers; do not retune**
   - Maker/rebate path — blocked until post-only fill-rate evidence

## Appendix — fund_xs_rank dual-era (this slice)

**Choice:** option 1 — HL asilletto cross-sectional funding rank (dual era; paper-perp 5+5×2).

**Data probe:** asiletto81 `asset_ctxs` has 760 daily lz4 files with a `funding` column; 100 CORE_UNIVERSE coins (incl BTC+ETH) have long tapes. Compact cache written to `var/ops/basis_cache/asilletto81/daily_funding_last_core100.json` (gitignored).

**Blocked / skipped alternatives (this turn):**

| hyp | why blocked / skipped |
| --- | --- |
| 2. BTC–ETH funding spread / relative funding | **AVAILABLE** next (HL×HTX BTC+ETH funding already proven by #175); not scored this turn — option 1 preferred when multi-asset tape present |
| 3. Intraday 4h MR / overnight inventory | **BLOCKED** — no `*4h*` candles on disk under `var/research/candles/{kraken,coinbase}/`; #108 intraday already empty |
| 4. Maker/rebate paper fill probe | Not needed — option 1 had data |

**Recipe:** `docs/artifacts/strategy-search/fund-xs-rank-hl-dual-era-dual-print-recipe.md` (re-frozen era split 2025-04-01 after coverage-only miss: original mid left era A at 258&lt;300 due to 123 missing archive days; amendment before any candidate PnL).

**Score:** `docs/artifacts/strategy-search/fund-xs-rank-hl-dual-era-dual-print.md`

- Catalog: 5 `fund_xs_rank_*` + flat control
- Fees: 5+5 bps × 2 on gross turnover
- Dual-print: era A 2024-01-01→2025-04-01 (334d) × era B 2025-04-02→2026-06-01 (426d)
- Result: **dual_print_passers=0**; all L/S and single-sleeve names fee-aware negative on both eras; `can_promote=false`; `keep_flag_false=true`
- `PAPER_PROMOTE_*` untouched (false)

**Next recommendation (superseded by this slice):** ~~ship BTC–ETH relative funding / funding-spread~~ scored below.

## Appendix — fund_spread_btc_eth dual-print (this slice)

**Choice:** option 2 — BTC–ETH relative funding / funding-spread on concurrent HL×HTX (paper-perp 5+5×2).

**Data probe / coverage freeze (before PnL):** HL BTC+ETH daily funding 801d; HTX BTC+ETH daily funding 801d; pair-aligned intersection 801d each (2024-07-18 → 2026-09-26 UTC). Concurrent venues preferred and used.

**Blocked / skipped alternatives (this turn):** none required — concurrent HL×HTX tape sufficient (≥720).

**Recipe:** `docs/artifacts/strategy-search/fund-spread-btc-eth-hl-htx-dual-print-recipe.md` (committed before score).

**Score:** `docs/artifacts/strategy-search/fund-spread-btc-eth-hl-htx-dual-print.md`

- Catalog: 5 `fund_spread_btc_eth_*` + flat control (≤6; NEW ids)
- Fees: 5+5 bps × 2 legs on each position change
- Dual-print: concurrent Hyperliquid × HTX
- Result: **dual_print_passers=0**; all names fee-aware negative or flat on both venues; `can_promote=false`; `keep_flag_false=true`
- `PAPER_PROMOTE_*` untouched (false)

**Named passers:** none.

**Next recommendation (superseded by this slice):** ~~fee-aware paper PnL soak for fund_z~~ scored fee-negative in #181. This slice: maker fill-rate probe = **INVALID**/UNAVAILABLE; fund_mom dual-print = **0** passers. Keep every promote flag false. Prefer research-only basis-carry flip-cost amortization matching #181 fees, or wait DefiLlama PIT ?720. Do not retune empty catalogs. Maker/rebate remains blocked. Continue DefiLlama PIT tips.


## Appendix — maker fill-rate probe + fund_mom dual-print (this slice)

**A) Maker / post-only paper fill-rate probe**

Pre-registered recipe:
`docs/recipes/ops/paper-maker-post-only-fill-rate-probe-recipe-2026-09-26.md`

Measurement:
`docs/artifacts/ops/paper-maker-post-only-fill-rate-probe-2026-09-26.md`

- post_only_path_exists: **false** (#73 not implemented; no `post_only` defs in `src/`)
- PAPER_SIMULATE_FILLS / `PaperFillSimulator`: **20/20** sync fills; max time-to-fill ≈0.4ms; cancels=0
- **maker_evidence_status: INVALID**; **fill_rate: UNAVAILABLE**
- Honesty stop: immediate taker-style fills cannot evidence maker/rebate. No ≤2h soak (no resting queue).
- `PAPER_PROMOTE_*` untouched (false)

**B) Funding-momentum (rate-change) HL×HTX dual-print**

**Choice:** option 1 — same-asset funding momentum / Δfunding (NOT sign_hold retune, NOT spread #180, NOT xs-rank #179).

**Data probe / coverage freeze (before PnL):** HL BTC+ETH 801d; HTX BTC+ETH 801d (live public funding → UTC daily sums). Concurrent venues used. Dual basis not required.

**Blocked / skipped alternatives (this turn):**

| hyp | why blocked / skipped |
| --- | --- |
| 2. Basis-carry flip-cost amortization matching #181 fees | Research-only candidate; deferred — option 1 had AVAILABLE HL×HTX funding tape |
| 3. Edge-status blocked list only | Not needed — A measured INVALID; B scored |

**Recipe (committed before score):** `docs/recipes/strategy-search/fund-mom-delta-hl-htx-dual-print-recipe.md` (recipe commit before score)

**Score:** `docs/artifacts/strategy-search/fund-mom-delta-hl-htx-dual-print.md`

- Catalog: 5 `fund_mom_*` + flat control (NEW ids)
- Fees: 5+5 bps × 2 legs on each position change
- Dual-print: concurrent Hyperliquid × HTX
- Result: **dual_print_passers=0**; all names fee-aware negative on both venues (high flip count); `can_promote=false`; `keep_flag_false=true`
- `PAPER_PROMOTE_*` untouched (false)

**Named passers:** none.

**Next recommendation:** keep every promote flag false. Maker/rebate remains **blocked** (INVALID paper evidence). Prefer research-only basis-carry flip-cost amortization study matching #181 fee drag, or wait DefiLlama PIT ≥720 — do not retune empty fund_mom / fund_spread / fund_xs_rank / weekly / spot catalogs. Continue DefiLlama PIT tips.

## Paper soak vs dual-print honesty (fund_z fee amortization, 2026-09-26)

**HONESTY: research passer ≠ short-horizon paper profit under current open fees.**

| Surface | Fees | Horizon | Result |
|---|---|---|---|
| Dual-print #175 `fund_z_harvest_sign_hold` | research **5+5 bps × 2** | ~800 daily bars | WF +1.68% / +1.47%; holdout +3.42% / +3.12%; `can_promote=false` |
| Host paper soak #181 | **PAPER_FEE_BPS=10** (+5 slip in fill) | **~6h** | `fee_aware_paper_pnl_usd=-0.064699` (fees 0.20 ≫ funding 0.013) |
| On-disk HL amortization (asilletto81 hourly→daily ∑\|f\|) | open 10 bps×2 on $100×2 | mean income ~$0.074/day | **~2.7 days** to breakeven fees_usd; **~4.1 days** if counting 10+5 |

Pin / Field defaults: all `PAPER_PROMOTE_*=false`. Paper only. No live.

Full study: `docs/artifacts/ops/paper-fund-z-fee-amortization-study-2026-09-26.md`.
Recipe: `docs/recipes/ops/paper-fund-z-fee-amortization-and-48h-soak-recipe-2026-09-26.md`.

## Appendix — fund_z flip-cost / >=N-day hold-gate dual-print (this slice)

**Choice:** option 1 — re-score sign_hold under explicit flip-cost gate (N from #183 BE table). First AVAILABLE. Did **not** retune xs-topk / weekly wk_trend / fund_spread / fund_xs_rank / fund_mom / oi_mom / spot FeatureZ / basis_resid.

**Data probe / coverage freeze (before PnL):** HL BTC+ETH 801d; HTX BTC+ETH 801d (live public funding → UTC daily sums). Dual basis OKX×Vision on disk (>=720d). Recipe commit `eb60bcd` before score.

**Blocked / skipped alternatives (this turn):**

| hyp | why blocked / skipped |
| --- | --- |
| 2. Weekly funding harvest (1w resample) | Deferred — option 1 AVAILABLE (HL×HTX + known passer) |
| 3. Basis MR hold>=5d (NEW ids vs #175 empty) | Deferred — option 1 AVAILABLE |

**Recipe (committed before score):** `docs/recipes/strategy-search/fund-z-flipcost-hold-gate-dual-print-recipe.md`

**Score:** `docs/artifacts/strategy-search/fund-z-flipcost-hold-gate-dual-print.md`

- Catalog: 4 magnitude/sticky gates (N=3,5) + `fund_z_flipcost_sign_hold_ref` + flat control (NEW ids; <=6)
- Fees: 5+5 bps × 2 legs; dual_basis required
- Dual-print: Hyperliquid×OKX / HTX×Binance Vision
- Result: **dual_print_passers=1** (`fund_z_flipcost_sign_hold_ref` only)
- **Honesty:** ref clone = known `fund_z_harvest_sign_hold` / `carry_hedged_sign` shape under NEW id — **not a new edge**
- Magnitude/sticky gates: all dual-print **ineligible** (WF negative). Sticky mean holds 4–6.5d but fee-negative
- `structurally_fee_survivable_ge_3d=false` for NEW gated candidates
- `can_promote=false`; `keep_flag_false=true`; `PAPER_PROMOTE_*` untouched (false)
- 48h soak PID 45859 **untouched**

**Named passers:** `fund_z_flipcost_sign_hold_ref` (honesty: same always-on harvest family as #175).

**Fee-survivability conclusion:** No NEW gated family in existing data clears dual-print with structural >=3d amortized holds. Always-on sign_hold remains the only research passer; short-horizon paper still needs multi-day soak per #183 (~2.7–4.1d BE).

**Next recommendation:** keep every promote flag false. Await 48h fund_z soak harvest. Do not retune empty catalogs. Weekly funding harvest / basis MR hold>=5d remain unused alternatives if a distinct long-hold family is still required after soak.

## fund_z fee-aware multi-day historical REPLAY (2026-09-26)

**HONESTY: PAPER/RESEARCH ONLY. NOT A PROMOTE. NOT LIVE PnL. MTM omitted.**

Historical tumbling N∈{3,5,7} day windows of `fund_z_harvest_sign_hold` on HL
asilletto hourly→daily ∑|f| (skip-not-invent). Dual **era** (HTX hourly absent).
Primary ladder = paper `PAPER_FEE_BPS=10` fees_usd ×2 on $100×BTC+ETH.

See `docs/artifacts/strategy-search/fund-z-harvest-fee-aware-multiday-replay.md`.
Recipe frozen before score: `docs/recipes/strategy-search/fund-z-harvest-fee-aware-multiday-replay-recipe.md`.

`can_promote=false` / `keep_flag_false=true`. Every `PAPER_PROMOTE_*=false`.

## carry+basis fee-aware multi-day REPLAY (OKX x Vision, 2026-09-26)

**HONESTY: PAPER/RESEARCH ONLY. NOT A PROMOTE. NOT LIVE PnL. MTM omitted.**

Reuses #185 N in {3,5,7} fee-survival ladders on other archived tapes: HL
funding compact + dual PIT basis (OKX x Binance Vision). HTX hourly
still skip-not-invent. Always-on hedged-carry (funding + basis delta).

See docs/artifacts/strategy-search/carry-basis-fee-aware-multiday-replay.md.
Recipe frozen before score.

can_promote=false / keep_flag_false=true. Every PAPER_PROMOTE_*=false.

DefiLlama weekday cron installed (see
docs/artifacts/ops/defillama-stable-pit-weekday-cron-installed-2026-09-26.md);
tip_days=2; no tip backfill.

## Parallel 7d fund_z fee-aware paper soak + promote-gap memo (2026-09-26)

**HONESTY: PAPER ONLY. NOT A PROMOTE. model_copy only.**

- Started parallel 7d host soak PID **2638509** (604800s) out
  `var/ops/_fund_z_fee_aware_7d_soak_20260926/` — does not collide with 48h PID **45859**.
- Harvest note: `docs/artifacts/ops/paper-fund-z-fee-aware-7d-soak-harvest-note-2026-09-26.md` (expected ~2026-10-03).
- Promote-gap memo: `docs/artifacts/strategy-search/fund-z-promote-honesty-gap-2026-09-26.md`
  (why can_promote / PAPER_PROMOTE_FUND_Z still blocked despite #175 passer + #185/#186 N>=5 survival).
- Every `PAPER_PROMOTE_*=false`. Field defaults unchanged.

## fund_z high-|funding| selective ≤2d fee-survival REPLAY (2026-09-26)

**HONESTY: PAPER/RESEARCH ONLY. NOT A PROMOTE. NOT LIVE PnL. MTM omitted.**

The frozen completed-day high-|funding| gate produced a dual-era primary-ladder
event-mode N=2 fee-survival passer (era A 73.5%; era B 63.3%) on 760 HL
asilletto daily observations. N=1 failed both eras. The always-on tumbling
reference is contrast only and cannot enter the passers list.

See `docs/artifacts/strategy-search/fund-z-hiabs-2d-fee-survival.md`.
Recipe frozen at `7bb12d4` before score.

`le2d_path_exists=true`, but `can_promote=false` / `keep_flag_false=true`.
Every `PAPER_PROMOTE_*=false`; soak PIDs untouched.
