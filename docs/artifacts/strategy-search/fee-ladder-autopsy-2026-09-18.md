# Fee-ladder autopsy — oi_mom dual-print (2026-09-18)

**Status:** scored result memo. Numbers below are copied from machine-written
JSON under `docs/artifacts/strategy-search/fee-ladder-oi-mom-*.md` /
`fee-ladder-oi-mom-summary.json`. **No PnL is invented.**
**Repo tip at score:** `ae2f8ed`.
**Never flips `PAPER_PROMOTE_*`.** Promote bar remains pilot 80+5.

## Pre-registration (frozen before re-score)

Recipe:
`docs/artifacts/strategy-search/fee-ladder-autopsy-recipe-2026-09-18.md`

| freeze | choice |
| --- | --- |
| catalog | **oi_mom** (#172 HL+Bybit OI-momentum; dual-print plumbing already present) |
| ids | unchanged `oi_mom_{fade,follow}_{7,14,30}` + control `ma_cross_10_30` |
| pilot | `kraken_pro_spot_t1` taker **80** + slip **5** |
| intermediate | `kraken_pro_spot_t3` taker **38** + slip **5** (already in `fee_tiers`; not invented) |
| research | `modelled` / PAPER_FEE_BPS **10** + slip **5** |
| not scored | t2/t8/t12 (one intermediate only — no post-hoc ladder fishing) |

## Results (honest)

| rung | tier_id | fee+slip | dual_print_passers | eligible core (Kraken) | eligible core (Coinbase) | dual eligible | median WF trades (core) | median fold turnover (core) | best primary WF excess (core) |
| --- | --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: |
| pilot | `kraken_pro_spot_t1` | 80+5 | **0** | none | none | none | 17 | 2.80 | -6.06% (`oi_mom_follow_30`) |
| intermediate | `kraken_pro_spot_t3` | 38+5 | **0** | none | none | none | 17 | 2.82 | -4.88% (`oi_mom_follow_30`) |
| research | `modelled` | 10+5 | **0** | none | none | none | 17 | 2.83 | -4.09% (`oi_mom_follow_30`) |

`can_promote=false` and `keep_flag_false=true` on every rung.
`--fee-bps` already existed on `traderstack-oi-mom`; no new override flag required.

## Fee-blocker finding?

**No — not for this frozen catalog.** A fee-blocker would be: some name
clears at research 10+5 (or intermediate 38+5) but fails only at pilot 80+5.
Here **zero** names are dual-print eligible at any rung, including 10+5.
Best primary walk-forward excess stays **negative** at all three fee levels
(improves slightly as fees fall, still below the bar). Typical turnover is
essentially fee-invariant (~2.8 fold turnover; ~17 WF trades), so this is
not a “high-turnover name killed only by 80 bps” story for oi_mom.

Pilot 80+5 remains the **promote** bar. Even if a future catalog clears at
10+5 only, `PAPER_PROMOTE_*` stays false until it also clears pilot.

## Artifacts

- `fee-ladder-autopsy-recipe-2026-09-18.md` (pre-reg)
- `fee-ladder-oi-mom-pilot-80.md` / `t3-38` / `modelled-10`
- `fee-ladder-oi-mom-summary.json` (machine counts only)

## Promote

Keep every `PAPER_PROMOTE_*=false`. No Settings pin. No live path.
