# Helpers fan-out — HL OI momentum — 2026-09-18

Paper-only. No PnL invented. `PAPER_PROMOTE_*` defaults remain **false**.

## Probe

| venue | source | BTC days | ETH days | verdict |
| --- | --- | --- | --- | --- |
| Hyperliquid | HuggingFace asiletto81/hyperliquid asset_ctxs daily last open_interest | 760 | 760 | **AVAILABLE** (>=720) |
| Bybit | linear open-interest API intervalTime=1d | 2236 | 2158 | **AVAILABLE** (>=720) |
| HTX | swap_his_open_interest | ~185 | ~185 | UNAVAILABLE |
| Binance | openInterestHist | ~31 | ~31 | UNAVAILABLE |
| OKX | rubik open-interest-history 1D | ~100 | ~100 | UNAVAILABLE |

Dual OI gate: **PASSED** (HL + Bybit).

## Score

- Recipe: `docs/artifacts/strategy-search/oi-mom-hl-bybit-dual-print-recipe.md`
- Report: `docs/artifacts/strategy-search/oi-mom-hl-bybit-dual-print.md`
- Catalog: `oi_mom_{fade|follow}_{7|14|30}` + control `ma_cross_10_30`
- Feature tape: Bybit OI momentum (HL archive ends 2026-06-01; live Kraken720 overlap less than 720 — skip-not-invent)
- Dual-print: Kraken x Coinbase at pilot 80+5 bps
- **dual_print_passers=0**
- `can_promote=false`; `keep_flag_false=true`

## Promote

Every `PAPER_PROMOTE_*=false`. No Settings pin. Empty dual-print set is success.
