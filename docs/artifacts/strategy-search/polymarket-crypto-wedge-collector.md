# Polymarket crypto-threshold vs Deribit — wedge tape collector shakedown (#142)

Generated: 2026-09-15T15:59:31.217550+00:00 by `traderstack-polymarket-crypto-collect` (paper / research only). **Not a print, not a result.** This artifact records that the collector reaches the venues it claims to reach and what the first rows look like; it scores nothing and claims no PnL.

## Header

- **Window**: 2 live cycle(s), 2026-09-15T15:55:35.734536Z → 2026-09-15T15:59:09.916685Z (UTC). A wedge tape needs weeks; this is the first day-zero sample.
- **Data sources actually reached** (status per series):

| Source | Endpoint | Status |
| --- | --- | --- |
| Polymarket Gamma | `/events?slug=<asset>-above-on-<month>-<day>-<year>` | **ok** — every requested slug returned an event (`events_missing=0`, `events_error=0`) |
| Polymarket CLOB | `/book?token_id=<yes token>` | **ok** — two-sided for 91 of 132 markets |
| Deribit | `public/get_instruments`, `public/get_book_summary_by_currency` (BTC, ETH) | **ok** |
| Crucix | operator-hosted `CRUCIX_*` | **skipped — not configured in this environment**; every row records `crucix_status=not_configured`, which is a stand-aside, so a gated mask built from this sample would be empty |
| Binance Vision 1m (slice-2 settlement) | not called in this slice | **skipped by design** |

- **Fee tier / bps**: none applied. This slice computes no PnL, so no fee is charged anywhere. The frozen formulas the evaluator will use are Polymarket taker `shares × 0.07 × p × (1 − p)` (cap 1.75 USD / 100 shares), Deribit option taker 0.0003 of the underlying per contract (cap 12.5% of premium) and 5 bps taker on a delta-hedge perp leg.
- **Print kind**: none. This is a collector shakedown. No trade, no mask, no control, no promotion; `PAPER_PROMOTE_POLYMARKET_CRYPTO_WEDGE` does not exist as a setting.
- **Model**: `bs_n_d2_markiv_interp_v1`, frozen before the first row.

## What the cycles did

| Cycle | Started (UTC) | Rows | ok | Non-ok |
| ---: | --- | ---: | ---: | --- |
| 1 | 2026-09-15T15:55:35.734536Z | 66 | 43 | no_option_probability=3, no_two_sided_book=20 |
| 2 | 2026-09-15T15:58:28.865406Z | 66 | 42 | no_option_probability=3, no_two_sided_book=21 |

Row status over all cycles: `no_option_probability`=6, `no_two_sided_book`=41, `ok`=85.

Recorded reasons for the non-`ok` rows:

- `book is one-sided: no mid` — 41
- `option probability skipped: sparse_chain` — 6

Nothing was substituted for any of these: a one-sided book has no mid, and a strike outside the listed chain has no probability. They are recorded as evidence and are not scoreable.

## First wedge sample (evidence only)

| Asset | ok rows | mean wedge | sd | mean \|wedge\| | p95 \|wedge\| | max \|wedge\| | rows ≥ 0.05 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC | 45 | -0.0016 | 0.0150 | 0.0128 | 0.0247 | 0.0277 | 0 |
| ETH | 40 | +0.0008 | 0.0216 | 0.0179 | 0.0394 | 0.0414 | 0 |

`wedge = poly_mid − deribit_prob`. The pre-registered decision threshold is `|wedge| >= 0.05`, frozen before any of these rows existed.

42 market(s) were observed in more than one cycle; the mean absolute change in the wedge between consecutive observations was 0.0025. One sample spacing is not a half-life estimate and none is claimed here.

Expiry gaps used (hours between the Polymarket 16:00 UTC resolution and the nearest Deribit expiry actually used): 8h × 74, 16h × 11.

## What this does not claim

- No PnL, no win rate, no edge. A wedge is a price difference between two venues pricing *similar but not identical* payoffs; the recorded `expiry_gap_hours` is exactly why it is not an arbitrage.
- No promotion path. There is no `PAPER_PROMOTE_*` field for this strategy and no `PAPER_PROMOTE_*` default changed.
- No resolution. Settlement and scoring are slice 2 (Binance Vision 1-minute closes and Gamma's settled `outcomePrices` as two disjoint sources).
- Crucix was not reachable in this environment, so every row here stands aside by construction. That is the intended direction: unknown is not clear.

Reproduce offline, with no network, from the committed fixture pack: `traderstack-polymarket-crypto-collect --fixtures-dir tests/fixtures/polymarket_crypto --json`.
