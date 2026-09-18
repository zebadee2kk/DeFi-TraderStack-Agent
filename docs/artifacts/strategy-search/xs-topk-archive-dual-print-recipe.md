# xs-topk archive dual-print recipe (pre-registration only)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · repo tip at authoring: `d54ca0b` (re-pin commit in any run report).
**Never flips `PAPER_PROMOTE_*`.** Empty dual-print set is success.

## Why this exists

Committed `docs/artifacts/strategy-search/xs-topk.md` scored **one** covered cell
(Kraken public OHLC 720 x era 2024-2026). The frozen dual-print rule needs two
independent covered cells (distinct venue **or** non-overlapping era, >=365 daily
bars). PR #147 landed multi-year candle archives (`traderstack-download-candles`
venues `coinbase` / `binance_vision` / `kraken_archive`) and `traderstack-xs-topk`
already accepts `--candles-dir VENUE DIR`. This note freezes the **recipe** that
uses those pieces for a second cell — it does not retune the K=13 catalog after
seeing the Kraken-only PnL.

## Frozen catalog (unchanged)

Same ids as `xs-topk.md`: `xs_topk_{ew|iv}_{N}_k{3|5}` for N in {21, 63, 126},
k in {3, 5}, plus informational `ew_bh_universe` (cannot promote). Do not add or
drop ids because the first cell failed.

## Frozen second-cell options (pick one before any pull; record which)

1. **Second venue, same era:** Coinbase or Binance Vision daily spot JSON under
   `var/research/candles/<venue>/`, scored via `--candles-dir <venue> <dir>`
   alongside a Kraken `--candles-dir` (or `--live` for Kraken only if the second
   print is archive-only). Universe membership and trailing-30d dollar volume
   must be derived **on that venue's own tape** — never reuse Kraken volume ranks
   for a Coinbase/Binance universe.
2. **Second era, same venue:** Kraken OHLCVT archive (`--venue kraken_archive`)
   covering a non-overlapping older era (>=365 daily bars), scored as its own
   `--candles-dir kraken_archive <dir>` print. Eras follow the local constants in
   `xs-topk.md` pending #135.

## Fee tier (frozen)

Pilot cost: Kraken Pro spot tier 1 taker **80 bps** + 5 bps slippage
(`--fee-tier` / Settings `PAPER_FEE_TIER`). Do not score the second cell at the
legacy 10+5 research fee.

## Exact command skeleton (operator-run; skip-not-invent)

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate

# A) pull archive candles for a pre-declared symbol list / window
#    (replace SYMBOLS, START, END after freezing them in the run notes)
traderstack-download-candles \
  --venue coinbase \
  --symbols BTC/USD,ETH/USD,SOL/USD \
  --start START_ISO --end END_ISO \
  --out-dir var/research/candles/coinbase

# B) score — two independent --candles-dir prints (example)
traderstack-xs-topk \
  --candles-dir kraken var/research/candles/kraken \
  --candles-dir coinbase var/research/candles/coinbase \
  --output-md docs/artifacts/strategy-search/xs-topk-archive-dual-print.md
```

An unreachable venue or short history is a **skip** with a data note — never a
zero-filled series. If fewer than two covered cells result, the report must say
so and leave every `PAPER_PROMOTE_*` false.

## Honesty traps

- Do not retune N / k / weights / rebalance after seeing either cell's PnL.
- Do not average venues; dual-print means both cells pass the frozen portfolio bar.
- Survivorship: archive listings still omit delisted names unless the OHLCVT drop
  includes them — state that in the run report.
- This recipe is **not** a Settings pin and does not widen `MVP_ASSETS` /
  `PAPER_PROMOTE_UNIVERSE` / RiskEngine limits.

## Related

- `docs/artifacts/strategy-search/xs-topk.md` — first (single-cell) committed print
- `src/traderstack/research/xs_topk_cli.py` — `--candles-dir` / `--live`
- `src/traderstack/research/download_candles.py` / `candle_archives.py` — #147
- Helpers fanout 2026-09-18: prefer this executable dual-print path over modeled
  hedged-carry promotion.


## Operator execution record (2026-09-18)

Executed on WSL against tip `3302ac4` / branch `feat/xs-topk-archive-dual-print`.
Pre-registration run notes (scratch):
`/home/rham-admin/claude-scratch/defi-helpers/xs-topk-dual-print-run-notes-2026-09-18.md`.

- **Second cell picked before pull:** option 1 Coinbase same era (download succeeded from WSL).
- **START/END:** `2024-09-24T00:00:00+00:00` → `2026-09-18T00:00:00+00:00`.
- **SYMBOLS:** 45 pre-declared Coinbase USD pairs (see run notes). Coinbase pull: 45/45 ok.
  Kraken first-cell dir rebuilt for the same list via public OHLC: 43/45 ok
  (skipped `MATIC/USD`, `MKR/USD` — fail-closed, not invented).
- **Score:** two `--candles-dir` prints at pilot 80+5 bps →
  `docs/artifacts/strategy-search/xs-topk-archive-dual-print.md`.
- **Result:** dual-print passers = **0** (success). `keep_flag_false=true`.
  `PAPER_PROMOTE_*` unchanged (still default false). Catalog K=13 not retuned.

### CLI corrections vs skeleton above

- `traderstack-download-candles` takes one positional `symbol` and `--out FILE`
  (not `--symbols` / `--out-dir`). Loop per symbol into `var/research/candles/<venue>/`.
- Archive venues also write `<out>.report.json` sidecars; `load_candles_dir` skips
  `*.report.json` so they are not counted as unreadable candle series.
