# Polymarket weather fee-aware evaluation

Report-only. Not a live-capital claim. Not a reason to flip `PAPER_PROMOTE_*` or `TRADING_MODE`. An empty or negative result is success.

## What this does / does not claim

This CLI scores the #44 NWP-vs-CLOB weather rule against `always_hold` and `fade_the_mid` after conservative costs (mid ± half-spread − documented taker-fee haircut). It is **not** a validated weather-market edge, not a crypto signal, and not a CLOB trading path.

Crucix fail-closed-on-outage is **not** this change. Crucix already maps high-tier alerts to `adverse_event`; a dedicated opt-in outage veto remains a follow-up.

## Honesty / pre-registered rules

Pre-registered Polymarket weather evaluation (frozen before any resolved-row score). (1) Universe is the #44 warm/stable city allowlist (honolulu, san_diego, miami, phoenix, singapore, lisbon); unknown slugs are dropped, not researched. (2) Point-in-time only: forecast_issued_at must be strictly before close_at. (3) Station match: official_high_f + station_id required or the row is dropped (gate 4). (4) Treatment is the #44 NWP Normal(high, sigma_f) vs CLOB mid rule; trade only when net_edge >= min_edge after fee_haircut. (5) Controls: always_hold and fade_the_mid on the same trade mask. (6) Primary PnL is conservative (mid ± half-spread − documented taker-fee haircut). Mid-fill is reported and cannot promote (gate 5). (7) Dual independent prints required (MULTI_PRINT_BAR_PREREGISTERED=true). Independence = non-overlapping event_date sets or overlapping dates with disjoint resolution sources. (8) MIN_ELIGIBLE_PER_PRINT=20, MIN_TRADES_PER_PRINT=8. (9) CAN_ENTER_PROMOTION_AVERAGE=false. `PAPER_PROMOTE_POLYMARKET_WEATHER` is not a Settings field and is not added. Every existing PAPER_PROMOTE_* stays default false. No live. Empty / negative is success. (10) Crypto overlay `polymarket_weather_vs_btc_daily` is skipped unless an aligned BTC daily close series is supplied — never invented.

## Print policy (frozen before scoring)

| print | when | can promote? |
| --- | --- | --- |
| single-print | fewer than two independent resolved packs, or overlapping dates with the same resolution source | **no** |
| dual-print | two packs with non-overlapping `event_date` sets **or** overlapping dates with disjoint resolution sources; each pack must also clear the calculator floor | still **no** Settings flip |

This run: print_kind=`single_print`; independent=`false` (fewer_than_two_prints).

## Parameters

- min_edge=0.080; fee_haircut=0.020; sigma_f=2.50°F; default_half_spread=0.010; holdout_fraction=20%.
- allowlist: `honolulu`, `san_diego`, `miami`, `phoenix`, `singapore`, `lisbon`.
- calculator floor: n_eligible ≥ 20, would_trade ≥ 8, treatment excess vs hold **and** fade > 0 on the full eligible set **and** on the dated holdout tail.

## Data

- Live / historical tape: UNAVAILABLE. Gamma closed events without a stored decision-time mid and an official ASOS/NCEI station high are not scored (using the settlement price as the mid is look-ahead).
- This empty print is the successful outcome. Do not fabricate PnL.
- TRADING_MODE=paper; report-only; venue_submitted=false
- No resolved rows: there is no public point-in-time CLOB mid + official station-high tape in this repository. Empty print is success. Do not invent historical mids from settlement prices (look-ahead).

## Prints

### `live_historical`

rows=0 eligible=0 would_trade=0 below_edge=0; dropped city=0 lookahead=0 station=0 mid=0 unparsed=0.
Conservative treatment PnL (probability points, $1 notional): +0.0000 vs hold +0.0000 vs fade +0.0000. Mid-fill treatment (cannot promote): +0.0000.
Holdout: fail-closed (n_eligible=0 < 10).
Fail-closed reason: `empty_print`.

## Crypto overlay

`polymarket_weather_vs_btc_daily` **skipped**: no aligned BTC daily close series; overlay not invented (signal_days=0, aligned=0, pnl_after_fees=—, can_promote=`false`).

## Promotion decision

**No candidate is promoted.** print_kind=`single_print`; can_promote=`false`; can_enter_promotion_average=`false`; keep_flag_false=`true`; recommended_promote_flag=`none`. `PAPER_PROMOTE_POLYMARKET_WEATHER` is not a Settings field. Leave every `PAPER_PROMOTE_*` false. Do not enable live.
