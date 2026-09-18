# Ensemble-trend v2 consensus dual-print recipe (pre-registration only)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · repo tip at authoring: `694aeff` (re-pin commit in any run report).
**Never flips `PAPER_PROMOTE_*`.** Empty dual-print set is success.

## Why this exists

Committed `docs/artifacts/strategy-search/ensemble-trend.md` (#137) scored the
frozen K=4 catalog (`ens_trend_9lb_vt25`, `ens_trend_6lb_vt25`,
`ens_trend_9lb_unit` + control) on Kraken x Binance.US older-720 at pilot
tier-1 taker fees and recorded **dual_print_passers=0**. That catalog is
**not** retuned after seeing PnL.

This note freezes a **fresh** ensemble-trend **v2** catalog (new ids) aimed at
cutting fee drag via a **consensus floor** on mid/long lookbacks plus a lower
vol target — still Donchian-on-close + trailing midpoint stop, still pilot
80+5 bps, still dual-print. Distinct family label / CLI switch so the failed
#137 catalog stays untouched.

### New hypothesis (structural; not a post-hoc N retune)

#137 weights every bar by open_lookbacks/total even when a single short
lookback is the only open member. Under 80 bps/side that fractional churn is
a plausible fee killer independent of directional skill. v2 requires a
**minimum open-count consensus** before any long exposure, drops the
ultra-short {5,10} lookbacks from the v2 member sets, and uses a **15%**
vol target (vs 25%). Concurrent **Kraken x Coinbase** harder-gate cells
replace the #137 Binance.US older-720 second print (archive candles already
on disk; skip-not-invent).

## Frozen v2 catalog (new ids; freeze before any score)

- Prefix: `ens_trend_v2_`
- Ids (K=3 books + control):
  - `ens_trend_v2_maj_mid_vt15` — lookbacks {30, 60, 90, 150}, `min_open=2`
    (majority of 4), `vol_target=0.15`
  - `ens_trend_v2_maj_long_vt15` — lookbacks {60, 90, 150, 250}, `min_open=2`,
    `vol_target=0.15`
  - `ens_trend_v2_strict_mid_vt15` — lookbacks {20, 30, 60, 90, 150},
    `min_open=3` (strict consensus of 5), `vol_target=0.15`
  - informational control `ma_cross_10_30` (cannot promote)
- Entry / stop rules unchanged: `close_above_prior_n_max_close` /
  `max_prior_stop_close_channel_midpoint`.
- When `open_count < min_open`, weight is forced to **0** (flat). When
  consensus holds, weight = (open_count / total) * min(0.15 / vol_90d, 1.0).
- Do **not** mutate `ENSEMBLE_CATALOG` / `ENSEMBLE_IDS` / `CORE_IDS` (#137).
- CLI: `traderstack-ensemble-trend --catalog v2 ...` (default catalog remains
  the #137 K=4 set).

## Fee tier (frozen)

Pilot cost: Kraken Pro spot tier 1 taker **80 bps** + 5 bps slippage
(`--kraken-tier 1` / `--fee-bps 80` + `--slippage-bps 5`). Gate C still doubles.

## Dual-print cells (reuse existing dirs; no new pull required)

1. Kraken: `var/research/candles/kraken/` (full archive listing feeds PIT
   universe; BTC/ETH gate, SOL reported).
2. Coinbase: `var/research/candles/coinbase/` (BTC/ETH[/SOL] gate cells;
   skip `*.report.json`).

Second-print rule for v2: **`concurrent_venue_harder_gates`** — same #96+A+B+C
combined bar on the Coinbase daily window (overlap with Kraken allowed;
venues never averaged). This is **not** the #137 / #102
`older_720_ending_before_primary_first_bar` Binance.US slice.

Universe membership stays **per primary (Kraken) tape** for the Kraken cell;
Coinbase gate symbols are scored venue-local (skip-not-invent short series).

## Exact command skeleton (operator-run; skip-not-invent)

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate

traderstack-ensemble-trend \
  --catalog v2 \
  --candles-dir kraken var/research/candles/kraken \
  --candles-dir coinbase var/research/candles/coinbase \
  --kraken-tier 1 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/ensemble-trend-v2-dual-print.md \
  --output-json var/ops/ensemble_trend_v2_dual_print.json
```

An unreachable venue or short history is a **skip** with a data note — never a
zero-filled series. If fewer than two covered cells result, the report must say
so and leave every `PAPER_PROMOTE_*` false.

## Honesty traps

- Do not retune the failed #137 lookbacks / vol targets after seeing either cell PnL.
- Do not grow `V2_*` / `ens_trend_v2_*` after seeing this run PnL.
- Do not average venues; dual-print means both cells combined-pass #96+A+B+C.
- Do not flip any `PAPER_PROMOTE_*` default.
- This recipe is **not** a Settings pin and does not widen `MVP_ASSETS` /
  `PAPER_PROMOTE_UNIVERSE` / RiskEngine limits.
- Not a #118 Donchian N retune, not an EMA reprint, not xs-topk, not carry.

## Related

- `docs/artifacts/strategy-search/ensemble-trend.md` — prior #137 dual-print (0 passers)
- `src/traderstack/research/ensemble_trend.py` — `V2_*` + `CATALOGS` (this slice)
- `src/traderstack/research/ensemble_trend_cli.py` — `--catalog v2` / `--candles-dir`
