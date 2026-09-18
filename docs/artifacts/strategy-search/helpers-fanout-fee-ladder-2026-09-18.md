# Helpers fanout — fee-ladder autopsy 2026-09-18

Paper/research only. Synthesis for operators continuing DeFi-TraderStack-Agent
after empty streak #160–#172. **No invented PnL.** `PAPER_PROMOTE_*` untouched.

## Done this slice

1. **#172 merged** — HL+Bybit OI-momentum dual-print; lint fixed (ruff);
   `dual_print_passers=0` at pilot 80+5; promote blocked.
2. **Fee-ladder autopsy** on frozen **oi_mom** catalog (chosen before re-score):
   pilot 80+5 vs intermediate `kraken_pro_spot_t3` 38+5 vs modelled 10+5.
   Result: **0 passers at every rung** — not a fee-blocker for oi_mom.
   Memo: `docs/artifacts/strategy-search/fee-ladder-autopsy-2026-09-18.md`.

## Standing rules (repeat)

- Never invent PnL; quote machine JSON only.
- Never flip `PAPER_PROMOTE_*` defaults; pilot bar is the promote bar.
- Freeze catalog + fee ladder **before** any re-score; do not retune ids
  after seeing PnL.
- Skip-not-invent missing tapes.

## Next hypotheses (ranked; pre-register before pull)

1. **Maker / rebate path** — `fee_tiers` already stamps maker bps as
   informational only. A maker-assumed score is **out of scope** until
   post-only paper fill-rate evidence exists (#73). Do not score maker
   fees as if filled.
2. **Paper-perp fills for carry** — funding/basis families need an
   executable paper-perp fill path (not spot long/flat). Soak #165 had
   0 fills; continue harness honesty, do not claim edge.
3. **Second-era cell for sess-gap or ens_trend_v2** — freeze recipe first;
   Coinbase older era may already be on disk.
4. **DefiLlama PIT** — wait for ≥720 tip days before re-scoring `stable_ni_*`.

## Operator recommendation

Keep promote blocked. Empty dual-print at research fees on oi_mom means the
next dollar of research should buy a **new family / new executable path**,
not another fee retune of oi_mom / vol-target / sess-gap catalogs already
scored at pilot.
