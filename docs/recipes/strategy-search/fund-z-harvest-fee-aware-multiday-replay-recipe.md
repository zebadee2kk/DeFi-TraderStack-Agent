# fund_z_harvest_sign_hold fee-aware multi-day historical REPLAY recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26 Europe/London. Re-pin commit SHA in the run report.
**Never flips `PAPER_PROMOTE_*`.** `can_promote=false` / `keep_flag_false=true` unless numbers truly clear (still not a Settings pin flip without explicit clear evidence).

## Why this exists

Wall-clock soaks (#181 ~6h fee-negative; #183 48h soak still running PID 45859)
cannot deliver 3–7d fee-survival evidence quickly. This slice **replays** the
named passer `fund_z_harvest_sign_hold` on **existing on-disk** HL funding tapes
over tumbling N∈{3,5,7} day windows with paper open fees applied once per window.

Builds on:
- #175 dual-print passer `fund_z_harvest_sign_hold` (research 5+5; pin false)
- #176/#181 host fee-aware paper PnL soak tooling / fee assumptions
- #183 fee-amortization study (mean BE ~2.7d @ 10 bps×2 fees_usd; ~4.1d @ 10+5)
- #184 flip-cost hold-gate (structurally_fee_survivable_ge_3d=false)

**Honesty:** research dual-print passer ≠ short-horizon paper profit. Historical
replay is paper/research evidence only. Not live PnL. Not a promote claim.

## Probe gate (required before score)

- Primary tape: `var/ops/basis_cache/asilletto81/asset_ctxs/*.csv.lz4` (HL).
  Method (match #183): last `funding` print per UTC hour →
  `daily_sum_abs = sum(|hourly|)` for BTC and ETH under always-on sign-hold.
- HTX hourly funding tape: **skip-not-invent** if absent on disk (as in #183).
  Dual-print then uses **non-overlapping eras** on HL (not invented HTX).
- Do **not** invent funding, mids, fees, or PnL. Missing days omitted (never
  zero-filled into income).
- Freeze this recipe **before** any window score.

## Policy (frozen; same as named passer)

- Strategy id: `fund_z_harvest_sign_hold`
- Always-on sign-hold / hedged-carry: always harvest `|rate|` while in.
- Replay assumes position **open at window start**, held for N UTC days,
  no flips inside the window (amortization / fee-survival surface).
- Notional: **$100/asset × BTC+ETH = $200** (matches #181).
- MTM: **omitted** in primary metric (funding − fees). Live soak MTM is
  mark-noise; fee-survival question is whether funding covers open fees over N days.
  Document omission. Do not fabricate mids.

## Fee assumptions (frozen; match #176/#181 paper soak)

| Ladder | Open cost on $100×2 | Notes |
|---|---:|---|
| **Paper fees_usd only (PRIMARY)** | **$0.20** | `PAPER_FEE_BPS=10` × 2 legs; matches #181 `fees_usd≈0.1999` |
| Paper freeze text 10+5 × 2 | $0.30 | fee+slip as open drag (sensitivity) |
| Research dual-print 5+5 × 2 | $0.20 | #175 scoring fees (sensitivity) |

Maker/rebate **not** assumed. Spot 80+5 **not** charged (synthetic spot not booked).

## Windows (frozen)

- N ∈ **{3, 5, 7}** UTC days.
- Primary aggregation: **tumbling** (non-overlapping) windows for independent draws.
- Also report **sliding** (step=1) distribution for denser BE / percentile view.
- A window is valid only if **every** day in the window has BTC+ETH `daily_sum_abs`
  present (skip incomplete windows; never invent).

## Dual-print policy (dual era; HTX skip)

1. **Era A (primary):** 2024-01-01 → 2025-04-01 UTC (inclusive) — same freeze as #179.
2. **Era B (second):** 2025-04-02 → 2026-06-01 UTC (inclusive; asilletto tip).
3. Each era needs enough complete N-day tumbling windows to report (prefer ≥30 for N=3);
   else record gap and still publish available era.
4. Dual-print "fee-survival passer" (informational only): for a given N+ladder,
   **fraction_fee_positive ≥ 0.55** on **both** eras (tumbling). Still
   `can_promote=false` in this CLI — Settings pin is a separate PR.

## Metrics (frozen; report all)

Per era × N × fee ladder:
- `n_windows` (tumbling / sliding)
- `mean` / `median` / `p10` / `p90` of `fee_aware_paper_pnl_usd` (= funding_usd − fees_usd)
- `mean_funding_usd`, `fees_usd` (constant per ladder)
- `fraction_fee_positive` (= fee_aware > 0)
- Optional JSON detail: cumulative funding by day k≤N vs fees

## Explicit non-goals

- Do **not** kill / touch PID 45859 48h soak out dir (read-only if any).
- Do **not** flip `PAPER_PROMOTE_*` Field defaults or `.env`.
- Do **not** go live / invent PnL.
- Do **not** retune `HARVEST_CATALOG` / `CARRY_CATALOG` / flipcost / xs-rank.

## Exact command

```bash
traderstack-fund-z-fee-aware-replay \
  --asilletto-dir var/ops/basis_cache/asilletto81/asset_ctxs \
  --notional-per-asset-usd 100 \
  --output-md docs/artifacts/strategy-search/fund-z-harvest-fee-aware-multiday-replay.md \
  --output-json docs/artifacts/strategy-search/fund-z-harvest-fee-aware-multiday-replay.json
```

(Point `--asilletto-dir` at the host-home cache if the worktree has no var symlink.)

## Artifacts

- Recipe (this file) — freeze commit before score
- Results MD: `docs/artifacts/strategy-search/fund-z-harvest-fee-aware-multiday-replay.md`
- Results JSON: `docs/artifacts/strategy-search/fund-z-harvest-fee-aware-multiday-replay.json`
- Edge-status honesty blurb (append to `edge-status-2026-09-26.md`)

## Tip at freeze

`origin/main` @ f0c9391 (#184). Branch: `feat/fund-z-harvest-fee-aware-replay-2026-09-26`.
