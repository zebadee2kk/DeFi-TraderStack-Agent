# Frozen Polymarket weather paper recipe (Open-Meteo signal) — 2026-10-03

**Status:** frozen BEFORE resolve/score. Not a result. No PnL claimed here.
**Signal tool:** Open-Meteo NWP daily high (`forecast_source=open_meteo`) via
`traderstack.polymarket.forecast.OpenMeteoClient` — public URL, no API key.
**Settlement sources (post-freeze):** IEM ASOS + NCEI GHCN-Daily (public, no key).
**Crucix:** STOPPED / not used (weather path has no Crucix gate; `CRUCIX_ENABLED`
absent/false, `CRUCIX_BASE_URL` blank, `CRUCIX_API_KEY` missing).
**Promote:** every `PAPER_PROMOTE_*` stays false. No live flags flipped.

## Why this tool

Inventory found only public, no-secret signal sources can emit today.
Secret-gated intel (Dune, LunarCrush, CryptoPanic, Perplexity, altFINS, Crucix)
has missing keys in operator `.env`. Crypto wedge requires Crucix clear and
stands aside when `not_configured` — that is not this test.
Open-Meteo already emitted on the 2026-09-18 PIT tape (20 miami rows).

## Frozen one-trade recipe (pre-score)

| Field | Value |
|---|---|
| market_id | `4608557` |
| question | Will the highest temperature in Miami be between 90-91°F on September 18? |
| city | `miami` |
| event_date | `2026-09-18` |
| close_at | `2026-09-19T04:00:00Z` |
| contract | `bucket` bounds `90.0-91.0` thr=None |
| signal | Open-Meteo high_f=86.0 sigma_f=2.5 model=best_match issued=2026-09-18T13:30:33.627431Z |
| CLOB mid (PIT) | 0.465000 |
| best_bid / best_ask | 0.46 / 0.47 |
| half_spread | 0.005000 |
| model_probability | 0.046602 |
| side | **no** |
| ask you would pay | **0.540000** (YES→best_ask; NO→1−best_bid) |
| min_edge / net_edge (legacy haircut 0.02) | 0.08 / 0.398398 |
| would_trade under min_edge | True |
| paper notional | $10.00 USDC |
| shares | 18.518519 (= notional / ask) |
| fee formula | Polymarket Fee Structure V2: `shares * 0.07 * p * (1-p)`, cap `1.75` USD per 100 shares (`polymarket_taker_fee`) |
| fee at ask (V2) | 0.322000 USDC |
| spread | pay touch ask; half_spread=0.005000 recorded from book |
| hold | hold to resolution (station high IEM+GHCN agree; no early exit) |

## Scoring plan (after this file is on the branch tip)

1. Resolve official high for this `event_date`/`city` via IEM ASOS + GHCN.
2. Outcome YES if station high falls in contract; else NO.
3. Net USDC at stated notional: if side wins `(1-ask)*shares - fee_v2`; else `-ask*shares - fee_v2`.
4. If station unmatched / missing → no score (skip-not-invent).

## Tape provenance

- Source tape: `var/audit/polymarket_weather_tape.jsonl` (n=20, city=miami,
  event_dates=['2026-09-18', '2026-09-19', '2026-09-20']).
- Observation is PIT: forecast_issued_at / observed_at before close_at.
- No settlement `outcomePrices` used as mid.
