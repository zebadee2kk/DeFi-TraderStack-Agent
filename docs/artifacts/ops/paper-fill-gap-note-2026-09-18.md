# Paper-fill gap note (soak #165) — diagnostic only

#165 paper-perp-hedge soak observed **0** `paper_perp_hedged` events with every
`PAPER_PROMOTE_*=false`. The hedge path only fires after a spot paper fill; with
promote voters off, the loop yields no promote-driven entries, so the soak
correctly shows a zero-hedge funnel (plumbing PASS, fills absent). Options
**without** flipping defaults: (1) diagnostic funnel counters for
`plan_rejected` / dust-exit / no-voter-flat stages; (2) a fixtures-driven paper
fill injector marked `can_promote=false` that only proves hedge apply/withhold;
(3) longer soak once an independent paper path has non-promote research fills.
Do **not** set any `PAPER_PROMOTE_*` to true to manufacture hedges.
