# Honesty gap memo — what STILL blocks can_promote / PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD=true

**Date:** 2026-09-26 (Europe/London)  
**Tip context:** origin/main @ **d67da27** (#186). Paper / research only.  
**HONESTY: NOT A PROMOTE. Do not flip Field defaults or `.env`. No fabricated PnL.**

Standing promote bar (edge-status 2026-09-26): dual independent prints; fee-aware WF total > 0 **and** holdout excess > 0 on **both** BTC and ETH; catalog + print policy frozen before pull; operator pin only after a committed passer report — and that pin still defaults **false**.

## What we have (committed; informational)

| Surface | Result | Promote? |
|---|---|---|
| #175 dual-print `fund_z_harvest_sign_hold` | dual_print_passers=**1**; WF +1.68%/+1.47%; holdout +3.42%/+3.12%; hard gates combined=true both prints | `can_promote=false`; `keep_flag_false=true` |
| Default-false pin | `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD` / Field `paper_promote_fund_z_harvest_sign_hold=False` | Pin exists; **stays false** |
| #181 ~6h host soak | `fee_aware_paper_pnl_usd=-0.064699` (fees much greater than funding) | Not promote evidence |
| #183 amortization | BE ~2.7–4.1d at open $0.20 on HL tape | Research calendar only |
| #185 fund_z hist replay | BE mean **3.89d** / median **4.0d**; dual-era fee-survival informational at N=5,7 | `can_promote=false` |
| #186 OKX×Vision hedged-carry | dual-basis survival informational at N=5,7 | `can_promote=false` |
| Live paper soaks | 48h PID **45859**; 7d PID **2638509** (model_copy only) | Harvest pending |

## Top blockers (concrete)

### 1. Research can_promote is intentionally false even with a named dual-print passer

#175 scored `fund_z_harvest_sign_hold` as the **only** dual-print passer and still set `can_promote=false` / `keep_flag_false=true`. Reasons baked into that honesty path:

- Executability is **paper-perp conceptual** (`PAPER_PERP_HEDGE`), **not** Kraken-spot. Score used research **5+5 bps × 2 legs**, not pilot spot **80+5**.
- Passer report itself forbids Settings promotion: pin may exist default-false after naming, but flipping env to true is a separate operator act that the score explicitly rejects.
- Always-on `|rate|` harvest is the same family as diagnostic carry shapes — not a distinct frozen edge recipe beyond the fee+basis dual-print freeze.

**Gap:** dual_print_passers=1 is **necessary but not sufficient** under repo policy. Holdout excess on both assets was positive in #175 — the bar that still fails is "operator may promote," not "holdout missing."

### 2. Paper runtime fees / horizon mismatch vs research dual-print

| Layer | Fee model | Horizon evidence |
|---|---|---|
| Research #175 | 5+5 bps × 2 | ~800 daily bars WF/holdout |
| Host paper soak | `PAPER_FEE_BPS=10` (+ slip in fill); fees_usd charges fee_bps | #181 ~6h fee-negative; #183/#185 imply **multi-day** BE (~3.9d mean) |
| #185/#186 ladders | Informational fee-survival at N≥5 (MTM **omitted**) | Historical replay is not live paper mark-to-market |

Until a completed multi-day **host** harvest shows fee-aware paper PnL that is not fabricated and is consistent with the open-fee drag, short-horizon paper cannot underwrite the research passer. Parallel 7d soak (PID 2638509) is the intended evidence path; it is **not yet done**.

**Gap:** research fee ladder ≠ paper soak fee ledger; hist replay omits MTM; no finished ≥BE-horizon host harvest yet.

### 3. Fee-survival replays (#185/#186) are informational — not a Settings flip

Both reports label dual-era / dual-basis survival at N=5,7 as **informational**, keep `can_promote=false`, and state explicitly that historical fee-survival is not a pin flip and not live PnL. Additional honesty limits:

- #185 dual-era on HL only (HTX hourly **skip-not-invent**).
- #186 dual-basis OKX×Vision on funding+|basis|; HTX hourly still absent; MTM omitted.
- N=3 generally fails survival; promotion bar is not "some N passes a ladder."

**Gap:** N≥5 survival on archived tapes does not satisfy the standing promote bar's live/paper executability + frozen promote decision; both assets' research holdout excess (#175) still sits behind an explicit keep_flag_false.

## Secondary blockers (still material)

- **Frozen recipe discipline:** any new gated family (#184 flip-cost) that is not a silent retune still failed dual-print except the honesty-clone ref of sign_hold — "not a new edge."
- **Kraken-spot:** fund_z is **not** Kraken-spot executable; spot FeatureZ / weekly spot catalogs remain empty dual-print. Promoting a paper-perp pin does not create spot edge.
- **Maker/rebate path:** fill-rate probe **INVALID** (#182) — cannot claim lower fee ladder as evidence.
- **Both-assets paper soak:** host probe opens BTC+ETH, but promote still requires both-asset research gates **and** non-fabricated paper harvest; one-leg or marks_incomplete harvests do not clear.

## What would still be required before even considering env=true (not doing it now)

1. Finished ≥BE-horizon host fee-aware harvest (7d preferred) with recorded `fee_aware_paper_pnl_usd`, fees, funding prints — no invention.
2. Explicit operator decision **after** that harvest + reaffirmation that research `can_promote` policy still allows a pin (today's committed reports say no).
3. Keep Field default **false**; any env true would be temporary/soak-scoped — current soaks already use model_copy only and must restore false.
4. Never TRADING_MODE=live from this memo.

## Operator recommendation

1. Leave every `PAPER_PROMOTE_*=false` (including `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD`).
2. Let 48h (45859) and 7d (2638509) soaks finish; harvest per ops notes.
3. Do not treat #185/#186 survival passers as promote authority.
4. Re-read this memo after 7d harvest before any pin discussion.

## Related artifacts

- `docs/artifacts/strategy-search/fund-z-harvest-paper-perp-dual-print.md` (#175)
- `docs/artifacts/strategy-search/fund-z-harvest-fee-aware-multiday-replay.md` (#185)
- `docs/artifacts/strategy-search/carry-basis-fee-aware-multiday-replay.md` (#186)
- `docs/artifacts/ops/paper-fund-z-fee-aware-7d-soak-started-2026-09-26.md`
- `docs/artifacts/ops/paper-fund-z-fee-aware-7d-soak-harvest-note-2026-09-26.md`
- `docs/artifacts/ops/paper-promote-fund-z-harvest-sign-hold-2026-09-26.md`
