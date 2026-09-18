# HL-HTX funding-divergence SPOT overlay dual-print recipe (pre-registration only)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · repo tip at authoring: `1a73cc6` (re-pin commit in any run report).
**Never flips `PAPER_PROMOTE_*`.** Empty dual-print set is success.

## Why this exists

Committed funding/carry dual-print reports (`funding-carry.md`, `funding-carry-daily.md`)
score **single-venue** funding-z fade/follow and funding-agree overlays independently on
Hyperliquid and HTX, plus a modeled hedged cash-and-carry that is **not** paper-spot
executable. Those spot overlays did not clear the fee-aware bar. Hedged
`carry_hedged_sign` is out of scope for a Kraken paper-spot promote path.

This note freezes a **fresh** catalog that uses the **divergence between HL and HTX
funding** as an exogenous spot feature (long/flat or fade via `FeatureZVoter`) on
Kraken spot BTC/ETH — paper-executable on the existing spot path. It does **not**
model a hedged perp leg and does **not** retune `funding_z_*` / `carry_hedged_*`.

## Frozen catalog (new ids; freeze before any score)

- Family label: `funding_div`
- Prefix: `fund_div_hl_htx_`
- Ids: `fund_div_hl_htx_{fade|follow}_{1_0|1_5|2_0}`
  → 6 voters + informational control `ma_cross_10_30` (cannot promote).
- Lookback: `Z_LOOKBACK=20` (same as funding-z).
- Thresholds: `|z| >= 1.0 / 1.5 / 2.0` (frozen grid; do not grow after seeing PnL).
- Do **not** mutate `FUNDING_Z_CATALOG` / `CARRY_CATALOG` / `CORE_IDS`.
- Hedged carry ids are **excluded** from this catalog.

## Feature definition (frozen)

1. Fetch public Hyperliquid `fundingHistory` and HTX `swap_historical_funding_rate`
   for BTC and ETH (reuse `edge_series.fetch_hyperliquid_funding` /
   `fetch_htx_funding`). BitMEX is not used.
2. Resample each tape to UTC **daily sums**; omit empty days (never zero-fill).
3. Per symbol, align on the **intersection** of HL and HTX UTC days.
4. `raw_div[t] = hl_daily_sum[t] - htx_daily_sum[t]` (sign convention frozen: HL minus HTX).
5. At candle open `t`, `FeatureZVoter` computes z of `raw_div` using only points with
   `ts <= candle.opened_at` and the trailing `lookback=20` aligned values.
6. Fade: BUY when z <= -entry_z, SELL when z >= +entry_z (same convention as
   existing funding-z FeatureZ voters). Follow: opposite. Missing history → flat.

## Fee tier (frozen)

Pilot cost: Kraken Pro spot tier 1 taker **80 bps** + 5 bps slippage
(`--fee-bps 80` / `--slippage-bps 5`). Same pilot tier as xs-topk archive dual-prints.

## Dual-print cells (candle venues; funding feature needs BOTH HL and HTX)

1. Kraken: `var/research/candles/kraken/` — BTC_USD_1d + ETH_USD_1d.
2. Coinbase: `var/research/candles/coinbase/` — BTC_USD_1d + ETH_USD_1d.

The **same** HL−HTX divergence series is applied on both candle venues (skip-not-invent
extra unfunded / unaligned days per venue tape). A name must clear the fee-aware
eligible bar on **both** cells to be a dual-print passer. Control cannot promote.

This is **not** the funding-carry dual-print pattern (HL-only catalog × HTX-only
catalog). Divergence by construction requires both funding tapes for the feature.

## Interval / walk-forward (frozen)

- Interval: `1d`
- Symbols: `BTC/USD`, `ETH/USD`
- Default WF: train=180 test=60 step=60 warmup=31; holdout_fraction=0.20
- Hard-gate / promote: still blocked. `keep_flag_false=true`. No Settings pin.

## Exact command skeleton (operator-run; skip-not-invent)

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate

traderstack-funding-div \
  --live \
  --interval 1d \
  --fee-bps 80 --slippage-bps 5 \
  --candles-dir kraken var/research/candles/kraken \
  --candles-dir coinbase var/research/candles/coinbase \
  --output-md docs/artifacts/strategy-search/hl-htx-funding-div-spot-dual-print.md \
  --output-json var/ops/hl_htx_funding_div_spot_dual_print.json
```

An unreachable funding venue, short intersection, or missing candle cell is a
**skip** with a data note — never a zero-filled series. If fewer than two covered
candle cells result, the report must say so and leave every `PAPER_PROMOTE_*` false.

## Honesty traps

- Do not retune `funding_z_*` / `carry_hedged_*` / thresholds after seeing PnL.
- Do not grow `FUND_DIV_CATALOG` after seeing this run PnL.
- Do not average candle venues; dual-print means both cells pass.
- Do not treat hedged carry as paper-spot executable.
- Do not use BitMEX.
- This recipe is **not** a Settings pin and does not widen `MVP_ASSETS` /
  `PAPER_PROMOTE_UNIVERSE` / RiskEngine limits.
- Never flip `PAPER_PROMOTE_*`.

## Related

- `docs/artifacts/strategy-search/funding-carry-daily.md` — prior HL×HTX funding dual-print (spot overlays failed; carry modeled-only)
- `src/traderstack/research/edge_series.py` — HL + HTX funding fetchers (divergence not built there)
- `src/traderstack/research/candidates.py` — `FeatureZVoter`
- `src/traderstack/research/funding_div.py` — divergence align + catalog (this slice)
