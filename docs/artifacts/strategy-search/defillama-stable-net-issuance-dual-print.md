# DefiLlama stablecoin net-issuance SPOT overlay dual-print

Generated: 2026-09-18T12:55:56.291374+00:00
Print kind: **unavailable**. interval=`1d`; primary_candle=`kraken`; second_candle=`coinbase`; feature=`defillama_stablecoins`; pit_safe=`false`; paper_path_ready=`true`; can_promote=`false`; `keep_flag_false=true`.
Core ids=7; dual_print_passers=`0`.
Costs: fee=80 bps + slippage=5 bps (pilot spot).
Aligned bars: primary=0, second=0.

## What this does / does not claim

Paper-research catalog of DefiLlama stablecoin net-issuance FeatureZ voters on spot BTC/ETH. **Not** a live-capital claim, **not** a reason to flip `PAPER_PROMOTE_*`. UNAVAILABLE / empty dual-print is success.

## PIT verdict

NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.

Live history PIT-safe constant: `False`. LAG_DAYS=`2`.

## Honesty / pre-registered rules

Pre-registered DefiLlama stablecoin net-issuance SPOT overlay (frozen before any pull/score). Feature = UTC-daily Δ totalCirculatingUSD.peggedUSD on /stablecoincharts/all; non-consecutive days skipped; LAG_DAYS=2. FeatureZVoter lookback=20; fade/follow at |z|>=1.0/1.5/2.0. Dual-print = Kraken x Coinbase spot BTC/ETH with the SAME aggregate series. Live API history is NOT PIT-safe (no as_of; revisions overwrite) — refuse historical dual-print unless an operator PIT archive is marked pit_safe. Pilot fee 80+5 bps. PAPER_PROMOTE_* stays default false. UNAVAILABLE / empty dual-print is success.

## Pre-registered catalog

Frozen ids: `stable_ni_fade_1_0`, `stable_ni_fade_1_5`, `stable_ni_fade_2_0`, `stable_ni_follow_1_0`, `stable_ni_follow_1_5`, `stable_ni_follow_2_0`; control `ma_cross_10_30`.

## Edge / PIT notes

- `stable_net_issuance` **unavailable**: NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.

## Candle notes

- `rules`: Pre-registered DefiLlama stablecoin net-issuance SPOT overlay (frozen before any pull/score). Feature = UTC-daily Δ totalCirculatingUSD.peggedUSD on /stablecoin…
- `pit`: NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.
- `live_fetch`: fetched 3216 days from https://stablecoins.llama.fi; score refused without PIT archive
- `candles:kraken`: var/research/candles/kraken: symbols=['BTC/USD', 'ETH/USD']
- `candles:coinbase`: var/research/candles/coinbase: symbols=['BTC/USD', 'ETH/USD']
- `parse_stablecoin_chart_rows`: parsed 3216 circulating days; skipped=0; pit_safe=false (NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history …)
- `pit_gate`: NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.

## Skipped families

- `stable_ni_fade_1_0`: fade stable-net-iss z |z|>=1: skipped — NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.
- `stable_ni_fade_1_5`: fade stable-net-iss z |z|>=1.5: skipped — NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.
- `stable_ni_fade_2_0`: fade stable-net-iss z |z|>=2: skipped — NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.
- `stable_ni_follow_1_0`: follow stable-net-iss z |z|>=1: skipped — NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.
- `stable_ni_follow_1_5`: follow stable-net-iss z |z|>=1.5: skipped — NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.
- `stable_ni_follow_2_0`: follow stable-net-iss z |z|>=2: skipped — NOT_PIT_SAFE: DefiLlama /stablecoincharts/* returns the current view of history with no as_of/revision feed; past circulating values may be rewritten. Live pulls must not score historical dual-prints. Forward paper use requires operator-dated snapshot archives + LAG_DAYS=2.

## Promotion decision

**No candidate is promoted.** print_kind=`unavailable`; can_promote=`false`; keep_flag_false=`true`; recommended_promote_flag=`none`. Leave every `PAPER_PROMOTE_*` false. Do not enable live.

## Weather pivot

Because live DefiLlama history is not PIT-safe, the documented parallel paper path remains Polymarket weather (`traderstack-polymarket-weather-collect` / `traderstack-polymarket-weather-eval` on main). Empty weather print is success; do not invent mids from settlement.

## Forward unblocker (post-#166)

Operator-dated snapshot collector recipe:
`docs/artifacts/strategy-search/defillama-stable-pit-snapshot-recipe.md`

Day-one status (no invented PnL):
`docs/artifacts/strategy-search/defillama-stable-pit-snapshot-day1.md`

CLI: `traderstack-defillama-stable-snapshot`. Dual-print remains unavailable until
≥720 distinct `as_of` tip days exist. Do not backfill tips from one live chart.

