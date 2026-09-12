# Basis-aware dual-print window freeze (HL + HTX)

Frozen **before** any basis-aware score on branch \asis/hl-htx-aware\.
Paper / research only. No \PAPER_PROMOTE_*\ flip. No live trading.
BitMEX is forbidden (official sunset 23 September 2026 04:00 UTC).

## Why freeze (coverage-driven, not PnL-driven)

HuggingFace \siletto81/hyperliquid\ \sset_ctxs\ is the only free
Hyperliquid mark−index tape confirmed here:

| fact | value |
| --- | --- |
| archive | \siletto81/hyperliquid\ \sset_ctxs/YYYYMMDD.csv.lz4\ |
| columns | \mark_px\, \oracle_px\ (official asset_ctxs shape) |
| calendar | **2024-01-01 → 2026-06-01** |
| span | **883 contiguous days, 0 gaps** |
| construction | daily last \mark_px − oracle_px\ / \oracle_px\ (skip-not-invent) |

The default live Kraken 720 (**2024-09-22 → 2026-09-11**) overlaps that
HL tape on only **~617 days** (< 720). Extending HL mark past
2026-06-01 was **not** available without inventing AWS keys for
requester-pays S3 or stitching forbidden substitutes (premium,
last-trade, Tardis first-of-month).

HTX public daily \linear_swap_mark_price_kline\ − \index\ already
covers ≥720d (and funding ≥720d). Dual-print basis therefore needs a
**shared scored window inside both HL archive and HTX**, not a
retune after seeing carry PnL.

## Frozen policy (A)

| knob | frozen value |
| --- | --- |
| \BASIS_AWARE_WINDOW_END_UTC\ | **2026-06-01** (inclusive open-day; archive last day) |
| \BASIS_AWARE_MIN_ALIGNED_DAYS\ | **720** |
| implied start (720d ending end) | **2024-06-12** UTC day-open |
| primary funding venue | Hyperliquid |
| second funding venue | HTX |
| basis primary | HF asiletto81 mark−index |
| basis second | HTX mark−index |
| BitMEX | **excluded** |

Live \--interval 1d\ runs that request basis-aware scoring **must**
truncate candle histories, funding tapes, and basis series to
\opened_at.date() <= 2026-06-01\ **before** walk-forward / hard gates
/ dual-print eligibility. Missing days are skipped, never
zero-filled. If either venue cannot supply ≥720 aligned daily bars
inside the freeze, \asis_status=skipped\ / UNAVAILABLE — do not
invent rows and do not widen the end date past the archive.

## What this is not

- Not a retune of the candle dual-print Kraken720 after seeing the
  archive end date for non-basis catalogs (#104–#123 stay closed).
- Not permission to use HL \undingHistory.premium\, BitMEX
  \.XBTUSDPI\, last-trade candles, or circular mark≈index×(1+premium).
- Not a promote unlock by itself. \can_promote\ still needs
  dual-print + hard gates + PIT basis on **both** venues +
  paper-executable path + dual passers, and every
  \PAPER_PROMOTE_*=false\ until earned.

## Probe note (optional Vision)

Binance/Bybit Vision mark/index zips return 200 from WSL and remain
an optional later stitch for an HL gap past 2026-06-01. Prefer this
frozen HF+HTX window first.
