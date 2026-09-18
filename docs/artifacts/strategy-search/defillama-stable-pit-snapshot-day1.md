# DefiLlama stablecoin PIT snapshot archive — day-one status

Generated: 2026-09-18T16:01 UTC+1 (operator collect). Paper / research only.

## Verdict

**Collector landed. Historical dual-print still UNAVAILABLE.**

- Live `/stablecoincharts/*` remains **NOT_PIT_SAFE** for backtest (#166).
- Operator-dated snapshot path:
  `var/research/defillama/stablecoincharts/as_of=YYYY-MM-DD/` + `tips.jsonl`
  (gitignored under `var/`; layout frozen in recipe).
- First live collect: **as_of=2026-09-18**, tip_day=2026-09-18, chart points=3216,
  **tip_days=1**, `enough_for_dual_print=false` (min=720).
- Dual-print attempt with `--pit-archive var/research/defillama/stablecoincharts`:
  `print_kind=unavailable`, `dual_print_passers=0`, `can_promote=false`,
  `keep_flag_false=true`.
- **No** dual-print PnL was invented from the live chart.
- Every `PAPER_PROMOTE_*` default remains **false**.

Artifacts:
- Attempt MD: `docs/artifacts/strategy-search/defillama-stable-pit-archive-dual-print-attempt.md`
- Attempt JSON: `var/ops/defillama_stable_pit_archive_dual_print_attempt.json` (local)

## What this unblocks (forward)

Daily `traderstack-defillama-stable-snapshot --live` appends one immutable
`as_of` tip. After ≥720 distinct tip days, `traderstack-stable-net-issuance
--pit-archive var/research/defillama/stablecoincharts` may score the frozen
`stable_ni_*` catalog under LAG_DAYS=2 using **successive tip deltas only**.

## Link from #166

#166 unavailable report correctly refused live history. This slice does **not**
re-score that catalog with fabricated history. It installs the archive plumbing
named in the #166 recipe.

## Promotion decision

**No candidate is promoted.** Leave every `PAPER_PROMOTE_*` false. Do not enable live.
