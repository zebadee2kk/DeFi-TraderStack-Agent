# Weekly / low-turnover trend dual-print recipe (pre-registration only)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-26 · repo tip at authoring: `b1a0403` (re-pin commit SHA in the score report).
**Never flips `PAPER_PROMOTE_*`.** Empty dual-print set is success.
**Hypothesis:** C from the 2026-09-26 pivot (spot-executable path; unlike fund_z paper-perp).

## Why this exists

Post-#174 / #175 pivot: daily spot FeatureZ catalogs (ens_trend_v2, sess-gap,
vol-target, xs-topk, oi_mom, candle families #104/#108/#116-#123) are **dead —
not retuned**. fund_z_harvest yielded a paper-perp dual-print passer that is
**not** Kraken-spot. This recipe freezes a **NEW** weekly-interval, low-turnover
trend catalog on existing Kraken x Coinbase **daily** archives, resampled to
weekly bars, to hunt a spot-executable dual-print passer.

## Resample rule (frozen before score)

**Friday UTC close week.**

- Source: existing `1d` JSON under `var/research/candles/{kraken,coinbase}/`
  (skip `*.report.json`). No new archive pull required for the score.
- Group daily bars into weeks whose **Friday** (UTC weekday=4) is the week stamp.
- For each week that has a Friday bar: O = Monday-or-first open in Mon-Fri,
  H = max high, L = min low, C = Friday close, V = sum volume.
- Week `opened_at` = Friday 00:00:00 UTC of that week.
- Interval label on resampled bars: `1w`.
- If Friday is missing for a calendar week then **skip that week** (skip-not-invent;
  never forward-fill Friday from Thursday/Saturday).
- Weekend-only daily bars do not open a week by themselves.

## Frozen catalog (NEW ids; K<=6; freeze before any score)

Prefix: `wk_trend_`. Do **not** mutate `ENSEMBLE_*`, `V2_*`, `TSMOM_*`,
`DONCHIAN_*`, `xs_topk_*`, `sess_gap_*`, `vol_target_*`, or `oi_mom_*`.

| id | rule (weekly bars only) |
| --- | --- |
| `wk_trend_ma_4_12` | long-only SMA(4) > SMA(12); else flat |
| `wk_trend_ma_10_40` | long-only SMA(10) > SMA(40); else flat |
| `wk_trend_donch_20` | long when close > prior 20-week max close; exit when close < channel midpoint; else flat |
| `wk_trend_donch_40` | same with N=40 |
| `wk_trend_tsmom_12` | long-only when close[t]/close[t-12]-1 > 0; else flat |
| `wk_trend_tsmom_26` | long-only when close[t]/close[t-26]-1 > 0; else flat |

Decision at week t (closes through t). Fill at **next week open** (no look-ahead
into the fill bar). Long-only spot (no short inventory). Missing/short series
skipped, never zero-filled.

## Fee tier (frozen)

Pilot cost: Kraken Pro spot tier-1 taker **80 bps** + **5 bps** slippage per side
(`--kraken-tier 1` / `--fee-bps 80` + `--slippage-bps 5`). Gate C doubles
to 160+10.

## Walk-forward + weekly-scaled #96+A+B+C (frozen)

Daily #96 bar counts do **not** apply to `1w` bars. Weekly-scaled params
(documented before score; do not retune after PnL):

| knob | weekly value | rationale |
| --- | ---: | --- |
| train_size | 40 | ~9 months |
| test_size | 10 | ~1 quarter |
| step_size | 10 | non-overlapping tests |
| holdout_fraction | 0.20 | same fraction as #96 |
| min_trades | 2 | low-turnover weekly |
| Gate A ratio | 0.25 | unchanged |
| Gate B windows | 3 x 34 weeks | ~2y tape split; need >=102 weekly bars |
| Gate B in-window WF | train=24, test=10 | one fold per window |
| Gate B min passes | 2 of 3 | unchanged rule |
| Gate C multiplier | 2x fee+slip | unchanged |

Combined passer on a venue: BTC **and** ETH clear #96-style signs (WF total > 0
and holdout excess > 0 and min trades) **and** A **and** B **and** C.
SOL reported when present; not a gate.

## Dual-print cells (prefer concurrent)

1. **Primary:** Kraken weekly from `var/research/candles/kraken/`
2. **Second:** Coinbase weekly from `var/research/candles/coinbase/`

Rule: `concurrent_venue_harder_gates` — same combined bar on each venue
window (overlap allowed; venues never averaged). If a venue is missing/short
(< 102 weekly bars after resample), that print is a **skip** with a data note.
If concurrent second print is unavailable, fall back to non-overlapping
`coinbase_era_2022_2024` only when that era yields >=102 weekly bars and ends
before primary first week — else leave dual-print empty (success).

A **dual-print passer** must combined-PASS **both** prints. Ranking key
(informational): Kraken BTC+ETH mean holdout excess among dual-print passers.
No `PAPER_PROMOTE_*` pin in this PR.

## Exact command skeleton (operator-run; skip-not-invent)

    traderstack-weekly-trend --candles-dir kraken var/research/candles/kraken --candles-dir coinbase var/research/candles/coinbase --kraken-tier 1 --slippage-bps 5 --output-md docs/artifacts/strategy-search/weekly-lowturn-trend-dual-print.md --output-json var/ops/weekly_lowturn_trend_dual_print.json

## Honesty traps

- Do **not** retune lookbacks / WF / Gate B after seeing either cell PnL.
- Do **not** grow `wk_trend_*` after seeing this run PnL.
- Do **not** average venues; do **not** invent Friday closes.
- Do **not** flip any `PAPER_PROMOTE_*` default.
- Not a retune of ens_trend_v2, daily TSMOM, Donchian #118, xs-topk, sess-gap,
  vol-target, oi_mom, or candle catalogs #104/#108/#116-#123.
- Paper only. `TRADING_MODE` stays `paper`.

## Related

- `docs/artifacts/strategy-search/edge-status-2026-09-26.md` — pivot memo (hyp C)
- `docs/artifacts/strategy-search/ensemble-trend-v2-dual-print-recipe.md` — daily concurrent pattern
- `src/traderstack/research/weekly_trend.py` — catalog + resample + score (this slice)
- `src/traderstack/research/weekly_trend_cli.py` — `traderstack-weekly-trend`
