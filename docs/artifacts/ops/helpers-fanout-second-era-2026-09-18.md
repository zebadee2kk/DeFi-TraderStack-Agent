# Helpers fanout — vol-target second-era dual-print — 2026-09-18

Paper / research only. **Not a profitability claim.**

## Goal

Edge-status rank #4: second-era / archive-era cell for a family with
concurrent-venue plumbing. Prefer vol-target / sess-gap / ens_trend_v2.

## Choice

**vol-target** — `traderstack-vol-target` already accepts `--candles-dir VENUE DIR`
cleanly (BTC/ETH only). Catalog frozen from #169 (no retune).

## Pre-registration (committed first)

`docs/artifacts/strategy-search/vol-target-ma-cross-second-era-dual-print-recipe.md`
@ tip `a6a9165` (recipe-only commit before any pull).

Frozen eras (non-overlapping, ≥365 daily bars each):

| label | window | source |
| --- | --- | --- |
| `coinbase_era_2024_2026` | 2024-09-24 → 2026-09-17 | reuse `var/research/candles/coinbase/` |
| `coinbase_era_2022_2024` | 2022-09-24 → 2024-09-23 | Coinbase public download |

`RESEARCH_KRAKEN_ARCHIVE_PATH` unset → primary path used Coinbase historical
(not local `kraken_archive`). Download **succeeded** (731 bars BTC + ETH, gaps=0).

## Score

```
traderstack-vol-target \
  --candles-dir coinbase_era_2024_2026 var/research/candles/coinbase \
  --candles-dir coinbase_era_2022_2024 var/research/candles/coinbase_era_2022_2024 \
  --fee-bps 80 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/vol-target-ma-cross-second-era-dual-print.md
```

| field | value |
| --- | --- |
| dual_print_passers | **0** |
| print_kind | dual_print |
| can_promote | false |
| keep_flag_false | true |
| aligned bars | primary 724 / second 731 |
| PAPER_PROMOTE_* | unchanged (all defaults false) |

## Helpers

No Claude/Codex fanout required this slice — CLI path was already green from
#169 and the download completed on WSL without archive-path blockers.

## Next

1. Update/merge edge-status with #170 + this second-era 0-passer result.
2. Optional: sess-gap or ens_trend_v2 second-era using the same
   `coinbase_era_2022_2024` candle dir (recipe first).
3. Keep DefiLlama snapshot collect scheduled; do not invent tips.
