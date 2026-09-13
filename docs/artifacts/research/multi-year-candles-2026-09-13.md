# Multi-year candle pull — first run (#133, 2026-09-13)

**Print kind:** research data pull only (no strategy scored, no PnL, no
fees applied — candles are inputs; fee tier / bps: n/a). Nothing here is a
passer and nothing here changes a gate or a `PAPER_PROMOTE_*` default.

**Command family:** `traderstack-download-candles --venue
coinbase|binance_vision|kraken_archive` (this PR), run unauthenticated from
the session environment between 15:55:01Z and 15:58:52Z on 2026-09-13.
Candle JSON files (~0.7–0.8 MB each) are **not** committed; only the
sidecar headers are reproduced below. Re-run the commands in
`docs/RUNBOOK.md`, "Multi-year candle history (#133)", to regenerate them.

## Data sources reached (status per series)

| Series | Venue / source label | Status | Window (first → last, UTC) | Bars | Gaps (entries / missing bars) | Quote | Notes |
|---|---|---|---|---|---|---|---|
| BTC/USD@1d | `coinbase_exchange_candles` | **ok** | 2016-01-01 → 2026-09-12 | 3908 | 0 / 0 | USD | 14 pages of ≤300 bars, 0 empty windows, paced ≤4 rps; uncommitted 2026-09-13 bar dropped |
| ETH/USD@1d | `coinbase_exchange_candles` | **ok** | 2016-05-18 → 2026-09-12 | 3768 | 1 / 2 | USD | 14 pages; 2 daily bars missing after 2016-05-20 (listing week; reported, not filled) |
| BTCUSDT@1d | `binance_vision_spot_monthly` | **ok** | 2017-08-17 → 2026-08-31 | 3302 | 0 / 0 | USDT | 109 monthly zips, all 109 sha256-verified against `.CHECKSUM`; current month (2026-09) not requested (end = last completed month) |
| ETHUSDT@1d | `binance_vision_spot_monthly` | **ok** | 2017-08-17 → 2026-08-31 | 3302 | 0 / 0 | USDT | 109 monthly zips, all verified |
| BTC/USD@1d | `kraken_ohlcvt_archive` | **skipped** | — | 0 | — | USD | `RESEARCH_KRAKEN_ARCHIVE_DIR / --archive-dir is unset; download the archive manually (support article 360047124832) and unzip it there` — the archive is a manual Google Drive download and no drop exists in this environment. Skipped, not zero. |
| BTC/USD@1d (reference) | Kraken public OHLC (`--venue kraken`, legacy path) | ok | 720 most-recent daily bars ending 2026-09-12 | 720 | — | USD | cross-check reference only |
| ETH/USD@1d (reference) | Kraken public OHLC (legacy path) | ok | 720 most-recent daily bars ending 2026-09-12 | 720 | — | USD | cross-check reference only |

`fetched_at` (sidecar): Coinbase BTC 15:55:03Z, Coinbase ETH 15:55:09Z,
Binance Vision BTC 15:55:15Z, Binance Vision ETH 15:57:05Z, Kraken archive
15:58:52Z.

## Cross-venue divergence (flagged, never dropped or blended)

Threshold: `MAX_REFERENCE_DIVERGENCE_BPS` = 50 (Settings default, read
only). Same-bar daily closes, `|a − b| / a × 1e4`.

| Fetched series | Reference | Shared bars | Flags > 50 bps | Max | Median |
|---|---|---|---|---|---|
| Coinbase BTC-USD | Kraken BTC/USD 720 | 720 | **0** | 10.7 bps (2026-02-05) | 1.5 bps |
| Coinbase ETH-USD | Kraken ETH/USD 720 | 720 | **0** | 16.3 bps (2025-06-16) | 1.5 bps |
| Binance Vision BTCUSDT | Kraken BTC/USD 720 | 708 | **0** | 22.3 bps (2025-01-01) | 4.2 bps |
| Binance Vision ETHUSDT | Kraken ETH/USD 720 | 708 | **0** | 25.2 bps (2026-02-04) | 4.3 bps |

Informational only (computed offline from the same files, not a CLI
flag): Coinbase BTC-USD vs Binance Vision BTCUSDT over all 3302 shared bars
has 294 bars above 50 bps, max 1178 bps on 2017-12-23; ETH 307 bars, max
1262 bps on the same day. That is the 2017 USDT/USD dislocation plus early
Binance liquidity, not a data error — and it is exactly why a USDT series
must never be averaged into a USD print. Over the Kraken-overlapping window
(2024-09 → 2026-08) USDT and USD closes agree within 25 bps.

## What this proves and what it does not

- The acceptance criteria's loads are real: BTC/USD and ETH/USD daily from
  2016 (Coinbase) and 2017 (Binance) land in the existing bare-list candle
  JSON that every `--candles` consumer already reads, with the header
  (venue, first/last bar, bar count, gaps, fetched_at, divergence flags) in
  the `<out>.meta.json` sidecar.
- The Kraken OHLCVT archive path is wired and tested on fixtures but was
  **not exercised on a real drop** here (manual download). Its column
  layout is [S]; confirm on the first drop.
- No strategy was re-scored on this history (#136), no era policy applied
  (#135), no 4h series pulled (Binance Vision ships 4h natively; Coinbase
  has none), no hourly series pulled in this run (Coinbase ETH-USD hourly
  from 2020 is reachable and paged the same way, ~200 pages).
- Survivorship: Binance Vision retains some delisted symbols and drops
  others; the Kraken archive is active pairs only. A multi-asset universe
  built from these sources needs a listing-date file before any
  cross-sectional print (#137/#140).
