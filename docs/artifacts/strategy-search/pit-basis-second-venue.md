# PIT basis — second venue probe (OKX + Binance Vision mark−index)

Generated: 2026-09-13T23:17:26.904075+00:00 by `traderstack-download-basis`. Paper / research only.

Window requested: **2020-01-01 → 2026-09-12** (UTC day opens; today's bar is never included).

Construction: daily **mark close − index close, over index close**, labelled by the UTC day open of that bar. OKX `history-mark-price-candles` − `history-index-candles` (USDT-margined swap vs USDT index; `confirm==1` rows only). Binance Vision USDT-M `markPriceKlines` − `indexPriceKlines` (sha256 `.CHECKSUM` verified per zip). Quote is **USDT** on both venues, not USD.

Refused in code: `premium` / `premiumIndexKlines` (funding-formula premium), `klines` / `market/candles` (last-trade), `fundingRate` (funding-implied). A day missing on either side of a venue is a **skip**, never a zero. An unreachable venue is a **skip** and this report says so.

## Probe table

| venue | symbol | status | first | last | days | gaps | bounded skips | truncated | source |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | :---: | --- |
| binance_vision | BTC/USD | **ok** | 2020-01-01 | 2026-09-12 | 2429 | 18 | 0 | no | `binance_vision:markPriceKlines−indexPriceKlines (USDT-M; quote USDT)` |
| binance_vision | ETH/USD | **ok** | 2020-01-01 | 2026-09-12 | 2443 | 4 | 0 | no | `binance_vision:markPriceKlines−indexPriceKlines (USDT-M; quote USDT)` |
| okx | BTC/USD | **ok** | 2020-01-01 | 2026-09-12 | 2447 | 0 | 0 | no | `okx:history-mark-price-candles−history-index-candles (USDT quote)` |
| okx | ETH/USD | **ok** | 2020-01-01 | 2026-09-12 | 2447 | 0 | 0 | no | `okx:history-mark-price-candles−history-index-candles (USDT quote)` |

## OKX × Binance Vision alignment (per symbol)

| symbol | pair | aligned days | dropped OKX-only | dropped Vision-only | first | last | ≥720 aligned |
| --- | --- | ---: | ---: | ---: | --- | --- | :---: |
| BTC/USD | okx×binance_vision | 2429 | 18 | 0 | 2020-01-01 | 2026-09-12 | **yes** |
| ETH/USD | okx×binance_vision | 2443 | 4 | 0 | 2020-01-01 | 2026-09-12 | **yes** |

Dual basis (two independent venues, ≥720 aligned daily bars on every symbol): **yes**.

## Notes per series

- `binance_vision:BTC/USD` **ok** — Binance Vision USDT-M BTCUSDT daily markPriceKlines close minus indexPriceKlines close over index (sha256 .CHECKSUM verified per zip; monthly zips + daily zips for the trailing month; today's bar dropped) — not premiumIndexKlines, not last-trade klines, not funding-implied. mark months_ok=80 months_missing=0 days_ok=12 days_missing=0 checksum_failures=0; index months_ok=80 months_missing=0 days_ok=12 days_missing=0 checksum_failures=0; one_sided_days_skipped=14 bounded_skips=0.
- `binance_vision:ETH/USD` **ok** — Binance Vision USDT-M ETHUSDT daily markPriceKlines close minus indexPriceKlines close over index (sha256 .CHECKSUM verified per zip; monthly zips + daily zips for the trailing month; today's bar dropped) — not premiumIndexKlines, not last-trade klines, not funding-implied. mark months_ok=80 months_missing=0 days_ok=12 days_missing=0 checksum_failures=0; index months_ok=80 months_missing=0 days_ok=12 days_missing=0 checksum_failures=0; one_sided_days_skipped=1 bounded_skips=0.
- `okx:BTC/USD` **ok** — OKX public daily history-mark-price-candles (BTC-USDT-SWAP) close minus history-index-candles (BTC-USDT) close over index; bar=1Dutc (UTC day open); confirm==1 rows only (uncommitted day dropped); USDT-margined swap vs USDT index — not premium, not last-trade, not funding-implied. mark_pages=25 index_pages=25 misaligned_rows_skipped=0 one_sided_days_skipped=0 bounded_skips=0.
- `okx:ETH/USD` **ok** — OKX public daily history-mark-price-candles (ETH-USDT-SWAP) close minus history-index-candles (ETH-USDT) close over index; bar=1Dutc (UTC day open); confirm==1 rows only (uncommitted day dropped); USDT-margined swap vs USDT index — not premium, not last-trade, not funding-implied. mark_pages=25 index_pages=25 misaligned_rows_skipped=0 one_sided_days_skipped=0 bounded_skips=0.

## Files written

- `binance_vision:BTC/USD` → `var/research/basis/binance_vision/BTCUSD_basis_1d.json`
- `binance_vision:ETH/USD` → `var/research/basis/binance_vision/ETHUSD_basis_1d.json`
- `okx:BTC/USD` → `var/research/basis/okx/BTCUSD_basis_1d.json`
- `okx:ETH/USD` → `var/research/basis/okx/ETHUSD_basis_1d.json`

## Honesty

- These are USDT-perp vs USDT-index prints on OKX and Binance; they are not a Kraken USD series and are labelled as such wherever they are scored.
- Basis for day D is the day-D close and is applied only to the day-D hedged-carry PnL (close D−1 → close D); it never enters the harvest decision.
- No `PAPER_PROMOTE_*` default changes. No Settings field. No live path.
