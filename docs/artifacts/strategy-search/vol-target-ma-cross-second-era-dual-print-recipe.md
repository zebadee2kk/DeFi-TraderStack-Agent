# Vol-target ma_cross_10_30 — second-era dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · tip at authoring: `3aebcd9` (re-pin SHA in the run report).
**Never flips `PAPER_PROMOTE_*`.** Empty dual-print set is success.

## Why this exists

#169 scored the frozen vol-target overlay catalog on **concurrent venues**
(Kraken × Coinbase, same ~2024-09→2026-09 era) and returned
`dual_print_passers=0`. Edge-status 2026-09-18 rank #4 asks for a
**second-era / archive-era cell** for a family that already has
concurrent-venue plumbing. `traderstack-vol-target` already accepts
`--candles-dir VENUE DIR` cleanly (BTC/ETH only).

This recipe freezes a **non-overlapping older era** dual-print. It does
**not** retune the #169 catalog, targets, or lookbacks after seeing PnL.

## Frozen catalog (unchanged from #169)

| id | sizing | note |
| --- | --- | --- |
| `ma_cross_10_30` | unit ±1 | control; informational; **cannot promote** |
| `ma_cross_10_30_vt15` | min(0.15 / ann. realised vol, 1.0) | overlay |
| `ma_cross_10_30_vt25` | min(0.25 / ann. realised vol, 1.0) | overlay |
| `ma_cross_10_30_vt50` | min(0.50 / ann. realised vol, 1.0) | overlay |

Direction / vol scalar / lookback 20 / max leverage 1.0 — identical to
`vol-target-ma-cross-dual-print-recipe.md`. Do **not** grow or retune.

## Fee tier (frozen)

Pilot cost: Kraken Pro spot tier 1 taker **80 bps** + 5 bps slippage.

## Symbols (frozen)

`BTC/USD`, `ETH/USD` (gate pair; same as #169).

## Dual-print cells (frozen before any pull)

Second-era, **same venue** (Coinbase public archive — no local
`kraken_archive` drop required; `RESEARCH_KRAKEN_ARCHIVE_PATH` unset).
Non-overlapping windows, each ≥365 daily bars:

1. **Era recent** label `coinbase_era_2024_2026`:
   `2024-09-24T00:00:00Z` → `2026-09-17T00:00:00Z`
   (reuse `var/research/candles/coinbase/` if already covering this window).
2. **Era older** label `coinbase_era_2022_2024`:
   `2022-09-24T00:00:00Z` → `2024-09-23T23:59:59Z`
   via `traderstack-download-candles --venue coinbase --start/--end`
   into `var/research/candles/coinbase_era_2022_2024/`.

Fallback if Coinbase older-era download is blocked: attempt
`--venue kraken_archive` for the same older window into
`var/research/candles/kraken_archive_era_2022_2024/` and pair with
existing Kraken recent (`var/research/candles/kraken/`, ~2024-09-28→2026-09-17).
If **both** archive paths fail, commit this recipe + an honest skip report
and leave promote blocked — never invent bars or PnL.

Eras never overlap. Venues/eras never averaged. Skip-not-invent on short
or missing series.

## Passer rule (frozen)

A name is a dual-print passer only if it is eligible on **both** era prints
under the miles-style paper bar (mean WF total > 0, mean holdout excess > 0,
min trades) **and** it is **not** the control. Empty set is success.

## Exact command

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate

# A) older-era Coinbase candles (loop per symbol)
for SYM in BTC/USD ETH/USD; do
  STEM=$(echo "$SYM" | tr '/' '_')
  traderstack-download-candles "$SYM" \
    --venue coinbase --resolution 1d \
    --start 2022-09-24T00:00:00Z \
    --end 2024-09-23T23:59:59Z \
    --out "var/research/candles/coinbase_era_2022_2024/${STEM}_1d.json"
done

# B) score — two independent era prints
traderstack-vol-target \
  --candles-dir coinbase_era_2024_2026 var/research/candles/coinbase \
  --candles-dir coinbase_era_2022_2024 var/research/candles/coinbase_era_2022_2024 \
  --fee-bps 80 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/vol-target-ma-cross-second-era-dual-print.md \
  --output-json var/ops/vol_target_ma_cross_second_era_dual_print.json
```

## Promote

**Keep every `PAPER_PROMOTE_*=false`.** This CLI never adds or flips a promote
pin. `TRADING_MODE` stays paper. No live path.

## Related

- `docs/artifacts/strategy-search/vol-target-ma-cross-dual-print-recipe.md` — concurrent-venue cell (#169)
- `docs/artifacts/strategy-search/vol-target-ma-cross-dual-print.md` — #169 score (0 passers)
- `src/traderstack/research/vol_target_cli.py` — `--candles-dir`
