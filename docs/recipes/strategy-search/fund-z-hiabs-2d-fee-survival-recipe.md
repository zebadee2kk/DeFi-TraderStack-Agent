# fund_z high-|funding| selective entry ? ?2d fee-survival ladder (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26. Re-pin commit SHA in the run report.
**Never flips PAPER_PROMOTE_*.** Empty / failing ?2d set is success.

## Why this exists

#183/#185/#186: always-on `fund_z_harvest_sign_hold` amortizes paper open
fees (~$0.20 on $100?BTC+ETH) in **~2.7?4d** mean/median. N=3 fee-survival
fails dual-era; N?5 informational survivors. Live paper still fee-negative
until multi-day soak (#181/#187).

**Question this slice answers:** does a **selective high-|funding| regime
entry** (freeze BEFORE score) create a paper-fee fee-survival path at
**N?{1,2,3}** ? especially **?2d** ? on the EXISTING HL asilletto
daily_sum_abs tape?

Distinct from / do **not** retune:
- always-on #185 fund_z fee-aware replay
- #184 flipcost magnitude/sticky dual-print (WF; N=3,5; continuous flips)
- fund_mom / fund_spread / fund_xs_rank / weekly / oi_mom / spot FeatureZ
- basis_resid / carry+basis #186 always-on

## Probe gate (required before score)

- Compact `var/ops/basis_cache/asilletto81/daily_sum_abs_btc_eth.json`
  (or rebuild from `asset_ctxs/*.csv.lz4`) covering BTC+ETH ?720d.
- Dual **era** print (HTX hourly absent ? skip-not-invent; same eras as #185).
- Freeze coverage + threshold math before any candidate window PnL.

## Frozen threshold (BEFORE score; from #183 BE math ? not fitted)

Target hold for ?2d question: **TARGET_N = 2**.

| Ladder | open_cost_usd ($100?2) | thr_usd = open_cost / TARGET_N |
|---|---:|---:|
| **Primary** `paper_fees_usd_10bps_x2` | **0.20** | **0.10** |
| `paper_fee_plus_slip_15bps_x2` | 0.30 | 0.15 |
| `research_5plus5_x2` | 0.20 | 0.10 |

Per-ladder thr: enter only when **trailing completed day** combined
funding_usd (= notional ? (BTC+ETH) daily_sum_abs) **? thr_usd** for that
ladder. Same thr used for all window lengths N?{1,2,3} on that ladder
(gate answers "is regime hot enough for 2d amortization?"; windows then
measure 1d/2d/3d survival under that gate).

## Entry / hold (frozen; no lookahead)

1. Ordered present-day list (gaps dropped; never zero-fill).
2. Signal on day `i` if `funding_usd(i) ? thr_usd` (completed day only).
3. Hold window = next **N** present days starting at `i+1` (NOT including
   signal day). Skip if fewer than N days remain.
4. Primary mode = **event** (one window per qualifying signal).
5. Secondary denser mode = **event** only (no always-on tumbling retune).
6. `fee_aware = sum(funding_usd over hold) ? open_cost` (MTM omitted).
7. Survival pass per era?N?ladder: `fraction_fee_positive ? 0.55` and
   `n_windows ? 1` (match #185). Dual-era passer = primary ladder +
   event mode + both eras pass.

## Honesty

- This is **not** a dual-print WF edge and **not** a promote.
- Thin n_windows in a quiet funding era is reported honestly.
- If N=1 and N=2 fail dual-era: document **no ?2d path** clearly.
- If N=2 passes dual-era on primary only: informational ?2d fee-survival
  under selective entry ? still `can_promote=false`.
- Always-on reference at same N?{1,2,3} may be shown for contrast but is
  **not** a new catalog (already #185).

## Explicit non-goals

- Do **not** kill / touch soak PIDs **45859** (48h) or **2638509** (7d).
- Do **not** flip any `PAPER_PROMOTE_*` (incl. FUND_Z_HARVEST_SIGN_HOLD).
- Do **not** invent HTX hourly / PnL / edge.
- Do **not** retune dead catalogs listed above.

## Exact command

```bash
traderstack-fund-z-hiabs-fee-aware-replay \
  --asilletto-dir var/ops/basis_cache/asilletto81/asset_ctxs \
  --notional-per-asset-usd 100 \
  --target-hold-days 2 \
  --output-md docs/artifacts/strategy-search/fund-z-hiabs-2d-fee-survival.md \
  --output-json docs/artifacts/strategy-search/fund-z-hiabs-2d-fee-survival.json
```

## Artifacts

- Recipe (this file) ? freeze commit **before** score
- Results MD / JSON under `docs/artifacts/strategy-search/`
- Edge-status honesty blurb append to `edge-status-2026-09-26.md`

## Tip at freeze

`origin/main` @ 7ac9f31 (#187). Branch: `feat/fund-z-hiabs-2d-fee-survival-2026-09-26`.
