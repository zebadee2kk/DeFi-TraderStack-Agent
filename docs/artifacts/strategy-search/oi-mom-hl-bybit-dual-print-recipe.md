# HL open-interest momentum SPOT overlay dual-print recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18. Re-pin commit SHA in the run report.
**Never flips PAPER_PROMOTE_*.** Empty dual-print set is success.

## Why this exists

Empty streak continues through #171 (vol-target second-era 0 passers). Claude2
backlog pre-registered HL open-interest momentum contingent on a second-venue
OI probe. This note freezes the catalog before any score.

## Probe gate (required before score)

- Hyperliquid: HuggingFace asiletto81/hyperliquid asset_ctxs daily last open_interest; need BTC+ETH each >=720 UTC days.
- Second venue: Bybit linear /v5/market/open-interest intervalTime=1d (HTX/Binance/OKX probed); need BTC+ETH each >=720 UTC days.
- If either venue UNAVAILABLE at >=720d for BTC or ETH: commit probe report + this recipe stub; refuse single-venue promote; do not invent a second tape.

## Frozen catalog (new ids; freeze before any score)

- Family label: oi_mom
- Prefix: oi_mom_
- Ids: oi_mom_{fade|follow}_{7|14|30} -> 6 voters + informational control ma_cross_10_30 (cannot promote).
- Feature: daily OI momentum oi_ret[t]=OI[t]/OI[t-N]-1 for frozen N in {7,14,30}; FeatureZVoter lookback=Z_LOOKBACK=20; entry |z|>=2.0 only (fade threshold frozen at z=2.0; do not grow after seeing PnL).
- Do not mutate prior catalogs (fund_div_*, sess_gap_*, stable_ni_*, vol-target, xs-topk).

## Dual OI + candle dual-print policy

1. Dual OI gate: both HL asiletto and Bybit must clear >=720d BTC+ETH.
2. Live candle dual-print: Kraken x Coinbase spot BTC/ETH at pilot 80+5 bps.
3. Feature tape for live candles: Bybit daily OI (covers live Kraken/Coinbase ~720 ending 2026-09). HL asiletto archive ends 2026-06-01; overlap with live Kraken public 720 is <720 — skip-not-invent (do not stitch post-archive HL tail). HL remains second independent OI venue for the gate.
4. Same oi_ret FeatureZ series on both candle venues (missing days omitted, never zero-filled).

## Fee tier (frozen)

Pilot cost: Kraken Pro spot tier 1 taker 80 bps + 5 bps slippage.

## Passer rule (frozen)

A name is a dual-print passer only if eligible on both Kraken and Coinbase under the fee-aware paper bar and it is not the control. Empty set is success. can_promote=false; keep_flag_false=true. No Settings pin.

## Exact command

traderstack-oi-mom --hl-oi-json var/ops/oi_cache/asilletto81_oi.json --bybit-oi-json var/ops/oi_cache/bybit_oi.json --fee-bps 80 --slippage-bps 5 --candles-dir kraken var/research/candles/kraken --candles-dir coinbase var/research/candles/coinbase --output-md docs/artifacts/strategy-search/oi-mom-hl-bybit-dual-print.md


## Promote

Keep every PAPER_PROMOTE_*=false. This CLI never adds or flips a promote pin. TRADING_MODE stays paper. No live path.
