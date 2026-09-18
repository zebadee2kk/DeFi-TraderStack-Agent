# DefiLlama stablecoin net-issuance SPOT overlay dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · repo tip at authoring: `f3659a7` (re-pin commit in any run report).
**Never flips `PAPER_PROMOTE_*`.** Empty / UNAVAILABLE dual-print is success.

## Why this exists

Prior slices (#160–#164) printed empty dual-prints / no poly edge; #165 landed
paper-perp-hedge soak plumbing with **0 hedges** while every `PAPER_PROMOTE_*=false`.
This note freezes a **fresh** exogenous feature: DefiLlama aggregate stablecoin
**net issuance** (Δ circulating mcap) as a FeatureZ fade/follow overlay on Kraken
spot BTC/ETH with a Coinbase second candle print — paper-executable long/flat only.

## Endpoint catalog (frozen; public; no key)

Base URL (working host): `https://stablecoins.llama.fi`
(docs also list `https://api.llama.fi` paths under `/stablecoins/...`; the
peggedassets host above is what returns 200 for charts).

| Endpoint | Use |
|---|---|
| `GET /stablecoins` | catalog of pegged assets + ids (USDT=`1`, USDC=`2`, …) |
| `GET /stablecoincharts/all` | aggregate historical circulating / USD mcap |
| `GET /stablecoincharts/all?stablecoin={id}` | single-asset chart |
| `GET /stablecoin/{id}` | per-asset history + chain distribution |
| `GET /stablecoinchains` | current chain totals (not a history series) |

**Metric (frozen):** `totalCirculatingUSD.peggedUSD` on `/stablecoincharts/all`.
Net issuance at UTC day `t`:
`net_iss[t] = circ_usd[t] - circ_usd[t-1]` when both days exist; **skip** the day
if either side is missing (never zero-fill, never interpolate).

## PIT integrity verdict (blocks historical dual-print)

**NOT PIT-SAFE for historical backtest from a live pull.**

Evidence frozen into this recipe before any score:

1. No `as_of` / revision-history / immutable snapshot parameter on any stablecoin
   chart endpoint (OpenAPI + docs checked 2026-09-18).
2. `/stablecoincharts/all` returns the **current view** of history; DefiLlama
   peggedassets cron recomputes circulating and can **overwrite** past days when
   methodology or source balances change.
3. Therefore a live pull today of day `2024-01-15` is not guaranteed to equal what
   an operator would have observed on `2024-01-16`. Scoring Kraken/Coinbase
   holdouts against that series would be look-ahead / revision leakage.

**Lag rule (forward paper only, if/when local snapshots exist):** at candle open
`T`, only use net-issuance points with `feature_day <= T.date() - LAG_DAYS`
where `LAG_DAYS=2` (day close + one buffer day for DefiLlama publish). Missing
days → flat / skip-not-invent.

**Allowed inputs for a future dual-print score (not this run):**

- Operator-supplied **dated snapshot archive** (JSONL of `{fetched_at, chart_as_of_day, rows}`)
  where each chart was frozen **before** the decision bars it gates; or
- Forward-only paper path that appends daily snapshots going forward (no rewrite).

Live API history without a PIT archive → **`print_kind=unavailable`**, refuse score.

## Frozen catalog (new ids; freeze before any score)

- Family label: `stable_net_iss`
- Prefix: `stable_ni_`
- Ids: `stable_ni_{fade|follow}_{1_0|1_5|2_0}` → 6 voters + informational control
  `ma_cross_10_30` (cannot promote).
- Lookback: `Z_LOOKBACK=20` (same as funding-div / funding-z).
- Thresholds: `|z| >= 1.0 / 1.5 / 2.0` (frozen grid; do not grow after seeing PnL).
- Feature applies the **same** aggregate series to BTC and ETH (market-regime
  assumption, frozen). Do **not** invent per-asset crypto betas.

## Dual-print cells (candle venues)

1. Kraken: `var/research/candles/kraken/` — BTC_USD_1d + ETH_USD_1d.
2. Coinbase: `var/research/candles/coinbase/` — BTC_USD_1d + ETH_USD_1d.

A name must clear the fee-aware eligible bar on **both** cells to be a dual-print
passer. Control cannot promote.

## Fee tier / WF (frozen)

- Pilot cost: Kraken Pro spot tier 1 taker **80 bps** + 5 bps slippage.
- Interval: `1d`; symbols: `BTC/USD`, `ETH/USD`.
- Default WF: train=180 test=60 step=60 warmup=31; holdout_fraction=0.20.
- Hard-gate / promote: still blocked. `keep_flag_false=true`. No Settings pin.

## Exact command skeleton (operator-run; skip-not-invent)

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate

# Live DefiLlama pull is fetch-only; dual-print score stays UNAVAILABLE without PIT archive:
TRADING_MODE=paper traderstack-stable-net-issuance \
  --live \
  --interval 1d \
  --fee-bps 80 --slippage-bps 5 \
  --candles-dir kraken var/research/candles/kraken \
  --candles-dir coinbase var/research/candles/coinbase \
  --output-md docs/artifacts/strategy-search/defillama-stable-net-issuance-dual-print.md \
  --output-json var/ops/defillama_stable_net_issuance_dual_print.json

# When a PIT snapshot archive exists (never invent one from live history):
TRADING_MODE=paper traderstack-stable-net-issuance \
  --pit-archive var/research/defillama/stable_net_iss_snapshots.jsonl \
  --candles-dir kraken var/research/candles/kraken \
  --candles-dir coinbase var/research/candles/coinbase \
  --output-md docs/artifacts/strategy-search/defillama-stable-net-issuance-dual-print.md
```

## Out of scope / cannot-promote reasons

- Live API historical chart without PIT archive → UNAVAILABLE (this run).
- Single candle venue / missing BTC or ETH candles → skip-not-invent.
- Empty dual-print passer set → success; leave every `PAPER_PROMOTE_*` false.
- Weather (#141/#157) remains the documented pivot if this overlay stays blocked
  on PIT grounds (collectors already on main; eval empty-print is success).

## Paper-fill gap note (soak #165; diagnostic only)

#165 paper-perp-hedge soak observed **0** `paper_perp_hedged` events with all
`PAPER_PROMOTE_*=false`. The hedge path is wired to fire only after a spot paper
fill; with promote voters off, the paper loop produces no promote-driven entries,
so the soak correctly shows a zero-hedge funnel (plumbing PASS, fills absent).
Options **without** flipping defaults: (1) diagnostic funnel counters for
`plan_rejected` / dust-exit / no-voter-flat stages; (2) a fixtures-driven paper
fill injector marked `can_promote=false` that only proves hedge apply/withhold;
(3) longer soak once an independent paper path has non-promote research fills.
Do **not** set any `PAPER_PROMOTE_*` to true to manufacture hedges.
