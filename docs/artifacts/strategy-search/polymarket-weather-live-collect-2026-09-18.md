# Polymarket weather live collect/resolve note (2026-09-18)

Report-only. **Not a scored edge.** No PnL invented. `PAPER_PROMOTE_*` untouched.

Generated from operator run after pre-registering
`docs/artifacts/strategy-search/polymarket-weather-eval-recipe.md`
(tip `58a43ca` / #166). Scoring remains the separate
`traderstack-polymarket-weather-eval` path; this note only records what
public APIs returned today.

## Collect (`traderstack-polymarket-weather-collect --once`)

| Field | Value |
|---|---|
| TRADING_MODE | paper |
| cities | honolulu, san_diego, miami, phoenix |
| pages | 4 |
| events_seen | 378 |
| markets_seen | 3788 |
| parsed | 33 |
| observed | **20** |
| venue_submitted | false |
| emits | observations_only |

Skipped: city_blocked=1064, unparsed=2691, book_one_sided=13,
book_unavailable=0, forecast_missing=0, closed=0, unit_unsupported=0,
station_unverified=0.

Tape path (gitignored under `var/`): `var/audit/polymarket_weather_tape.jsonl`
— 20 JSONL rows. Decision-time CLOB tops + Open-Meteo as-issued highs only.
Settlement prices were not read back as mids.

## Resolve (`traderstack-polymarket-weather-resolve`)

| Stage | Rows |
|---|---|
| observations on tape | 20 |
| distinct markets | 20 |
| decision rows | 20 (all miami — only miami cleared two-sided books in this cycle) |
| resolved rows | **0** |
| awaiting_close | **20** |
| newly_resolved | 0 |

Event-date window: 2026-09-18 .. 2026-09-20. Settle lag 24 h after
`close_at` has not elapsed, so IEM ASOS / NCEI GHCN were **not probed**
(skip-not-invent). `print_kind=single_print`; no monthly print packs emitted.

## Eval

`traderstack-polymarket-weather-eval --empty-live` → committed
`docs/artifacts/strategy-search/polymarket-weather-eval.md`:
`print_kind=single_print`, `independent=false`, `can_promote=false`,
`keep_flag_false=true`, fail-closed reason `empty_print`. Crypto overlay
skipped (no BTC series). Conservative PnL fields are +0.0000 because
n_eligible=0 — not an invented edge.

## Crucix

Weather NWP-vs-mid path does **not** share the crypto-wedge Crucix trade
mask. Documented as N/A / stand_aside for this slice (no invent clears).

## Promotion

**Blocked.** `PAPER_PROMOTE_POLYMARKET_WEATHER` is not a Settings field and
was not added. Every existing `PAPER_PROMOTE_*` stays default false.
Forward path: cron collect while open → resolve after settle lag → dual
monthly prints before anyone may discuss promotion.
