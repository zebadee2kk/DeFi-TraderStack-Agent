# Helpers fanout — fund_z fee-aware replay + next hypothesis (2026-09-26)

Paper only. `PAPER_PROMOTE_*` stay false.

## Helper status

| Helper | Result |
|---|---|
| claude ×3 | **blocked** — Claude Code monthly spend limit (resets ~23:50 Europe/London) |
| codex | **blocked** — not a trusted directory / skip-git-repo-check still aborted |

Operator continued autonomously (Cursor cloud agents also usage-exhausted).

## Replay QA (operator)

1. Compact tape schema matches loader (`days[YYYYMMDD][BTC|ETH]`); n_days=760.
2. Primary ladder = paper fees_usd $0.20 (#181); research 5+5 also $0.20; sensitivity $0.30.
3. `can_promote=false`; Field defaults untouched; HTX skip-not-invent → dual_era on HL.

## Fabrication risk avoided

Do not treat dual-era fee-survival passers (N=5/7 @ $0.20) as a Settings pin flip or short-horizon soak profit — mid-soak ~10h still fee-negative vs $0.20 open.

## High-EV next hypotheses (1–3; not dead catalog)

1. **DefiLlama PIT tip hardening** — weekday_collect.sh + cron; grow tip_days from 2 toward 720; refuse live historical score until archive clears min days.
2. **Historical fee-aware replay tooling reuse** — apply the same N∈{3,5,7} compact-tape helper to other archived funding/basis series that have not been dual-printed as fee-survival windows (e.g. OKX×Vision basis residual carry path if tapes exist; no empty dual-print).
3. **48h soak harvest honesty pack** — after PID 45859 finishes, publish fee_aware_paper_pnl vs $0.20 open without inventing mids; compare to N=2 empiric BE (~3.9d mean) — expect still fee-negative at 48h if funding stays ~$0.02/10h.

Dead catalog (do not relaunch): FeatureZ spot overlays, fund_mom, BTC-ETH funding-spread, flip-cost gates, weekly trend @80+5.
