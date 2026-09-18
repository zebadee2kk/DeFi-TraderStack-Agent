# DefiLlama stablecoin PIT snapshot archive recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · unblocks historical scoring for #166 once enough dated tips exist.
**Never flips `PAPER_PROMOTE_*`.** Day-one dual-print UNAVAILABLE is success.

## Why this exists

#166 refused live `/stablecoincharts/*` for historical dual-print: DefiLlama
returns the **current view** of circulating history with **no `as_of`** and
revisions may overwrite past days. This recipe freezes an **operator-dated
snapshot collector** so future dual-prints can use `LAG_DAYS` without
look-ahead.

A **single live chart pull is not a 720-day PIT archive.** Storing today's
revised history under one `as_of` only freezes what was visible **today**.
True PIT net-issuance for backtest is built from **successive daily tip**
observations across many `as_of` days.

## Snapshot dating (frozen)

- `as_of` = **UTC calendar day of the fetch** (`fetched_at.astimezone(UTC).date()`).
- One snapshot directory per `as_of`. **Immutable:** if `as_of=YYYY-MM-DD/`
  already exists, the collector **refuses overwrite** (skip / exit non-zero
  unless `--force` is explicitly passed for operator recovery — default off).
- Tip row appended once per `as_of` to append-only `tips.jsonl`.

## Storage layout under `var/research/`

```
var/research/defillama/stablecoincharts/
  as_of=YYYY-MM-DD/
    meta.json      # fetched_at, as_of, endpoint, tip_day, tip_circulating_usd,
                   # point_count, pit_safe_for_historical_score=false,
                   # schema_version
    chart.json     # raw DefiLlama list payload (audit / revision diff)
  tips.jsonl       # append-only {as_of, tip_day, circulating_usd, fetched_at,
                   #              endpoint, source_date_unix}
  STATUS.md        # human summary of archive coverage (regenerated ok)
```

Also accepted by `traderstack-stable-net-issuance --pit-archive`:
a consolidated object with `pit_safe=true` **only** when built from
≥ `MIN_SNAPSHOT_DAYS` tip rows via the archive loader (never from a bare
live chart array).

## LAG_DAYS

`LAG_DAYS=2` (same as #166): at candle open `T`, only use tip / net-issuance
points with `feature_day <= T.date() - LAG_DAYS`. Missing days → skip-not-invent
(never zero-fill).

## PIT series construction (frozen)

1. Load `tips.jsonl`, sort by `as_of`, drop duplicate `as_of` (keep first).
2. Net issuance at tip day `t` from consecutive tips only:
   `net_iss[t] = circ[t] - circ[t-1]` when `as_of` days are consecutive
   calendar days **and** tip_days are consecutive; else **skip** that step.
3. Do **not** use revised historical rows inside `chart.json` for dual-print
   scoring — those rows are the fetch-day view of the past, not PIT.

## Dual-print gate

| Condition | Outcome |
|---|---|
| Live `/stablecoincharts/*` without dated tip archive | `print_kind=unavailable`; refuse score |
| Tip archive present but `< MIN_SNAPSHOT_DAYS` (720) | `print_kind=unavailable`; honest skip |
| Tip archive ≥720 distinct `as_of` days, `pit_safe` series built from tips | may score Kraken×Coinbase dual-print |
| Dual-print passers = 0 | success; promote blocked |

`MIN_SNAPSHOT_DAYS = 720`. Day one will not clear this bar.

## CLI (frozen name)

```bash
TRADING_MODE=paper traderstack-defillama-stable-snapshot \
  --live \
  --archive-dir var/research/defillama/stablecoincharts \
  --status-md var/research/defillama/stablecoincharts/STATUS.md

# Optional: after archive clears 720d, score via existing #166 CLI:
TRADING_MODE=paper traderstack-stable-net-issuance \
  --pit-archive var/research/defillama/stablecoincharts \
  --candles-dir kraken var/research/candles/kraken \
  --candles-dir coinbase var/research/candles/coinbase \
  --output-md docs/artifacts/strategy-search/defillama-stable-net-issuance-dual-print.md
```

## Refusal rules (non-negotiable)

1. Never invent historical dual-print PnL from a live chart.
2. Never mark `pit_safe=true` on a bare live / offline chart array.
3. Never flip any `PAPER_PROMOTE_*` default.
4. Empty / UNAVAILABLE dual-print is success.
5. Weather / second-era pivots remain documented alternatives if archive growth
   is too slow — do not retune `stable_ni_*` thresholds after seeing PnL.

## Out of scope

- Backfilling fake tip days from one chart pull.
- Per-stablecoin betas / inventing USDT-only overlays in this slice.
- Live capital / promote pins.
