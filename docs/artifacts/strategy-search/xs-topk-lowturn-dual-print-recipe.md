# xs-topk lower-turnover dual-print recipe (pre-registration only)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · repo tip at authoring: `0183d2f` (re-pin commit in any run report).
**Never flips `PAPER_PROMOTE_*`.** Empty dual-print set is success.

## Why this exists

Committed `docs/artifacts/strategy-search/xs-topk-archive-dual-print.md` (PR #160)
scored the frozen K=13 catalog (`xs_topk_{ew|iv}_{N}_k{3|5}` for N in {21, 63, 126})
on Kraken×Coinbase at pilot 80+5 bps and recorded **dual_print_passers=0**.
That catalog is **not** retuned after seeing PnL.

This note freezes a **fresh** lower-turnover catalog (new ids) intended to cut
fee drag via longer momentum windows — still monday rebalance, still pilot fees,
still dual-print on the same archive candle dirs. Distinct family label so the
failed K=13 stays untouched.

## Frozen lower-turnover catalog (new ids; freeze before any score)

- Prefix: `xs_topk_lt_`
- Ids: `xs_topk_lt_{ew|iv}_{N}_k{3|5}` for **N in {126, 252, 378}**, **k in {3, 5}**
  → 12 baskets + informational control `ew_bh_universe` (cannot promote).
- Weights: `ew` | `iv` (same rules as default catalog).
- Skip: `TOPK_SKIP_DAYS=7` (unchanged).
- Rebalance: `monday_utc_close_fill_next_open` (unchanged cadence; longer N is
  the turnover lever — no every-Nth-monday code in this slice).
- Do **not** mutate `TOPK_LOOKBACKS` / `TOPK_CATALOG` / `CORE_IDS`.
- CLI: `traderstack-xs-topk --catalog lowturn ...` (default catalog remains
  the K=13 set).

## Fee tier (frozen)

Pilot cost: Kraken Pro spot tier 1 taker **80 bps** + 5 bps slippage
(`--pilot-fee-bps` / Settings `PAPER_FEE_TIER`). Same as #160.

## Dual-print cells (reuse existing dirs; no new pull required)

1. Kraken: `var/research/candles/kraken/` (from #160 rebuild; 43 names).
2. Coinbase: `var/research/candles/coinbase/` (from #160; 45 names; skip `*.report.json`).

Universe membership and trailing volume stay **per venue tape** — never reuse
Kraken ranks for Coinbase.

## Exact command skeleton (operator-run; skip-not-invent)

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate

traderstack-xs-topk   --catalog lowturn   --candles-dir kraken var/research/candles/kraken   --candles-dir coinbase var/research/candles/coinbase   --output-md docs/artifacts/strategy-search/xs-topk-lowturn-dual-print.md   --output-json var/ops/xs_topk_lowturn_dual_print.json
```

An unreachable venue or short history is a **skip** with a data note — never a
zero-filled series. If fewer than two covered cells result, the report must say
so and leave every `PAPER_PROMOTE_*` false.

## Honesty traps

- Do not retune the failed K=13 N/k/weights after seeing either cell PnL.
- Do not grow `LOWTURN_*` after seeing this run PnL.
- Do not average venues; dual-print means both cells pass the frozen portfolio bar.
- This recipe is **not** a Settings pin and does not widen `MVP_ASSETS` /
  `PAPER_PROMOTE_UNIVERSE` / RiskEngine limits.

## Related

- `docs/artifacts/strategy-search/xs-topk-archive-dual-print.md` — prior K=13 dual-print (0 passers)
- `docs/artifacts/strategy-search/xs-topk-archive-dual-print-recipe.md` — archive recipe
- `src/traderstack/research/xs_topk.py` — `LOWTURN_*` + `CATALOGS`
- `src/traderstack/research/xs_topk_cli.py` — `--catalog`
