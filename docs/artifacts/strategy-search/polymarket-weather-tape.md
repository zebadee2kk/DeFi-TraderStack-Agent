# Polymarket weather point-in-time tape (collector / resolver)

Evidence only. This report counts observations; it does not score them and never computes PnL. Scoring happens in `traderstack-polymarket-weather-eval`, which cannot promote on a single print. `PAPER_PROMOTE_POLYMARKET_WEATHER` is not a `Settings` field and is not added here.

Generated: 2026-09-15T15:44:59.435021+00:00

## Header

| Field | Value |
|---|---|
| Tape | `var/audit/polymarket_weather_tape.jsonl` |
| Resolved tape | `var/audit/polymarket_weather_resolved.jsonl` |
| Window (event dates) | — (empty tape) |
| Print kind | single_print |
| Fee model | flat taker haircut 0.0200 (Polymarket Fee Structure V2 formula is deferred) |
| Decision rule | latest observation with lead_hours >= 0 |
| Settle lag | 24 h after close_at |
| Station match | IEM ASOS primary, NCEI GHCN-Daily cross-check, tolerance 1 °F (fail closed) |
| Print kind source | one print per calendar month of event dates |

## Sources reached

| Source | Status | Detail |
|---|---|---|
| iem_asos | skipped | not probed in this run (no row was due for resolution) |
| ncei_ghcn_daily | skipped | not probed in this run (no row was due for resolution) |

## Counts

| Stage | Rows |
|---|---|
| observations on tape | 0 |
| distinct markets | 0 |
| decision rows | 0 |
| resolved rows | 0 |
| rows emitted to prints | 0 |
| already_resolved | 0 |
| awaiting_close | 0 |
| newly_resolved | 0 |

## Per city (decision rows)

| City | Rows |
|---|---|
| — | 0 |

## Drop reasons

| Reason | Rows |
|---|---|
| — | 0 |

## Prints

| Print (event month) | Rows |
|---|---|
| — | 0 |

## Notes

- Point-in-time by construction: every row's CLOB mid and NWP high were read while the market was open. Settlement prices are never read back as a mid (that would be look-ahead).
- Resolution is the IEM ASOS daily maximum with an NCEI GHCN-Daily cross-check. Polymarket itself resolves on the NOAA hourly 'Temp' maximum at the same airport, which can differ by a degree; rows where the two free sources disagree beyond the tolerance are dropped rather than scored on the flattering one.
- Celsius-resolved cities (London, Seoul, Toronto, Zhengzhou, Singapore, ...) are catalogued but skipped as unit_unsupported: single-degree °C buckets need a unit-aware bucket model.
- `PAPER_PROMOTE_POLYMARKET_WEATHER` is not a `Settings` field and is not added by this CLI. No PAPER_PROMOTE_* default changes.
- rows=0. The tape has to be collected while markets are open, so a freshly built tape is legitimately empty. An empty print is the successful outcome; nothing is back-filled from settlement.
- Fewer than two monthly prints: the dual-print bar cannot be attempted, and a single print can never promote.

## Sources probed while building this slice (2026-09-15, unauthenticated GET)

Every row below was actually requested from this environment. A source that
was not reached is marked `skipped` with the reason; nothing is inferred.

| Source | Request | Status |
|---|---|---|
| Polymarket Gamma | `/events?tag_slug=weather&closed=false&limit=100&order=id&ascending=false&offset=0` | ok — 100 events; response carries `deprecation: true`, `sunset`, `warning: 299 - "use /events/keyset"` and still returns 200 |
| Polymarket Gamma (keyset) | `/events/keyset?tag_slug=weather&closed=false&limit=2` | ok — `{"events": [...], "next_cursor": "..."}` |
| Polymarket CLOB | `/book?token_id=<Miami 77°F-or-below yes token>` | ok — `bids`/`asks` arrays of `{price,size}` strings, **not** sorted ascending; the sampled book was one-sided (no bids) and is therefore a `book_one_sided` skip |
| IEM ASOS | `cgi-bin/request/daily.py?network=HI_ASOS&stations=PHNL&…&var=max_temp_f` | ok — PHNL 2025-06-01..03 = 83/86/87 °F |
| IEM ASOS | 15 further station/network pairs (MIA, LGA, ORD, PHX, SAN, LAX, SFO, SEA, HOU, DAL, AUS, ATL, BKF, TJSJ, LPPT) | ok — each verified with one GET before being written into `CITY_CATALOG`; `SJU` is **not** a valid id (`PR_ASOS` wants `TJSJ`) |
| NCEI GHCN-Daily | `access/services/data/v1?dataset=daily-summaries&stations=…&dataTypes=TMAX&units=standard` | ok — 12 of 13 ids returned TMAX; Buckley (Denver) and San Juan have no verified id and are left empty, which fails closed |
| Open-Meteo forecast | `/v1/forecast` (`models=` parameter) | ok — used as the as-issued forecast at observation time |
| Open-Meteo historical-forecast / previous-runs | archived as-issued runs | skipped — daily free quota exhausted from this IP; needed only for the deferred coarse backfill |

Header for this report: **window** — none (the tape is empty); **fee tier /
bps** — flat taker haircut `POLYMARKET_WEATHER_FEE_HAIRCUT=0.02` (the Fee
Structure V2 formula is deferred); **print kind** — `single_print`.

### Why rows = 0 is the honest result

The tape can only be written while a market is open, and this slice is the
first commit of the collector. Nothing is back-filled: Gamma's
`outcomePrices` on a closed market are the settlement, and reading them back
as a decision-time mid would be look-ahead. The acceptance criterion "a
committed report with rows > 0" therefore needs weeks of operator-host
collection and is explicitly deferred.

### Pre-registered rules (fixed before any row is scored)

1. `close_at` is the end of the event's local calendar day in the city's
   timezone — **not** Gamma's `endDate` (12:00Z while the market keeps
   accepting orders all day).
2. The decision row is the latest observation with
   `lead_hours >= --min-lead-hours` (default 0).
3. The official high is the IEM ASOS daily maximum, cross-checked against
   NCEI GHCN-Daily. Disagreement beyond `--station-tolerance-f` (default
   1 °F), or either source missing, drops the row as `station_unmatched`.
   Verified example of why: Miami 2025-06-01..03 read 85/89/78 °F at IEM and
   86/92/78 °F at GHCN, so a 3 °F day exists in the very first sample.
4. One print per calendar month of event dates, so independence comes from
   disjoint dates rather than from re-scoring the same rows against a second
   resolution source.
5. Fahrenheit-resolved cities only. Celsius cities are catalogued and skipped
   as `unit_unsupported`.

### Live smoke run of the collector (2026-09-15, Miami only)

The collector was run once against the live endpoints to prove the path
end to end. It is **not** committed as data — the tape below lived in a
scratch file and the committed status above is still the empty tape.

```
cities: miami
pages=1 events=100 markets=1118 parsed=11 observed=4
skipped: book_one_sided=7, book_unavailable=0, city_blocked=324,
         closed=0, forecast_missing=0, station_unverified=0,
         unit_unsupported=0, unparsed=783
```

The four recorded observations (Miami, event date 2026-09-17, Open-Meteo
`best_match` high 86.6 °F, `close_at` 2026-09-18T04:00Z, lead 60.1 h) were
the 84-85, 86-87, 88-89 and 90-91 °F buckets at mids 0.095 / 0.245 / 0.320 /
0.175. `unparsed=783` is the rest of the weather tag (every "lowest
temperature" event and every non-allowlisted city's markets), `city_blocked`
counts markets whose city is catalogued but not on this run's allowlist.

Two operational findings from that run, both now handled in code:

* A YES token's `/book` is frequently **ask-only**. Resting bids sit as asks
  on the complementary NO token, verified on the 82-83 °F market (YES asks
  best 0.07, NO bids best 0.93) — so a missing YES bid is a genuinely absent
  bid, not a paging artefact, and the row is skipped as `book_one_sided`.
* A one-sided book must not be reported to the `ProviderRegistry` as a
  provider failure. It was, at first: three out-of-the-money buckets tripped
  the circuit breaker and the remaining eight markets were skipped for a
  reason that had nothing to do with their books. The HTTP read now goes
  through the registry and the reduction to a top of book happens outside it,
  and the collector paces CLOB reads at `60 /
  POLYMARKET_WEATHER_CALLS_PER_MINUTE` because that quota raises rather than
  throttling.
