# Polymarket weather fee-aware eval recipe (2026-09-18 live-tape slice)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · repo tip at authoring: `58a43ca` (#166).
**Never flips `PAPER_PROMOTE_*`.** Empty / cannot-promote is success.

## Why this exists

Collectors / resolver / eval for Polymarket weather already landed on `main`
(#44 research module, #106 fee-aware eval, #141/#157 PIT tape). Prior
committed prints are empty because the tape can only grow while markets are
open (`docs/artifacts/strategy-search/polymarket-weather-tape.md`,
`polymarket-weather-eval.md`). #166 noted weather as the parallel paper path
after DefiLlama live history was refused as NOT_PIT_SAFE.

This recipe freezes the **live collect → resolve → score** path for today's
operator run **before** any new observation is scored. It does **not** retune
gates after seeing empty or negative prints from #160–#166 catalogs.

## Frozen decision rule (already in code; do not retune after PnL)

1. **Universe:** #44 warm/stable allowlist only —
   `honolulu`, `san_diego`, `miami`, `phoenix` (Fahrenheit primary score set).
   `singapore` / `lisbon` remain catalogued but `unit_unsupported` for °C
   buckets unless a unit-aware model lands separately. Unknown slugs dropped.
2. **Point-in-time only:** every observation stores decision-time CLOB top of
   book + as-issued Open-Meteo NWP high while the market is open.
   `forecast_issued_at` / `observed_at` must be strictly before `close_at`.
   Settlement `outcomePrices` are never read back as a mid (look-ahead refuse).
3. **Forecast lag:** decision row = latest observation with
   `lead_hours >= min_lead_hours` (default **0**). Settle lag = **24 h** after
   `close_at` before station resolution is attempted.
4. **Station match:** IEM ASOS daily max cross-checked vs NCEI GHCN-Daily;
   disagreement beyond `station_tolerance_f=1.0` °F (or either missing) drops
   as `station_unmatched` (fail closed).
5. **Treatment:** #44 NWP `Normal(high, sigma_f)` vs CLOB mid; trade only when
   `net_edge >= min_edge` after fee haircut. Controls on the **same** mask:
   `always_hold`, `fade_the_mid`.
6. **Fees / slip (frozen):** flat taker haircut
   `POLYMARKET_WEATHER_FEE_HAIRCUT=0.02` (Fee Structure V2 formula deferred);
   default half-spread `0.010`. Conservative PnL = mid ± half-spread − haircut.
   Mid-fill is reported and **cannot** promote.
7. **Eval knobs (frozen before score):** `min_edge=0.080`, `sigma_f=2.50` °F,
   `holdout_fraction=0.20`. Calculator floor: `n_eligible ≥ 20`,
   `would_trade ≥ 8`, treatment excess vs hold **and** fade > 0 on full set
   and dated holdout tail.
8. **Print bar:** `MULTI_PRINT_BAR_PREREGISTERED=true`. Independence = one
   print per calendar month of event dates (non-overlapping event_date sets)
   **or** overlapping dates with disjoint resolution sources.
   `MIN_ELIGIBLE_PER_PRINT=20`, `MIN_TRADES_PER_PRINT=8`.
   `CAN_ENTER_PROMOTION_AVERAGE=false`.
9. **Crucix:** weather path has no crypto Crucix gate today. Document
   `stand_aside` / `not_configured` if an operator env lacks Crucix; do not
   invent clears. (Crypto wedge uses Crucix; weather does not share that mask.)
10. **Promote:** `PAPER_PROMOTE_POLYMARKET_WEATHER` is **not** a Settings field
    and is **not** added. Every existing `PAPER_PROMOTE_*` stays default false.
    Single print can never promote. Empty / negative is success.

## What this run may score

- Live `traderstack-polymarket-weather-collect --once` append to
  `var/audit/polymarket_weather_tape.jsonl` (GET-only; paper mode).
- `traderstack-polymarket-weather-resolve` → per-month packs under an emit dir
  when settle lag has elapsed and stations agree.
- `traderstack-polymarket-weather-eval --resolved …` when ≥1 resolved pack exists;
  otherwise `--empty-live` for the honest empty historical-tape report.
- Fixture packs under `tests/fixtures/polymarket/` prove the calculator
  offline; fixtures cannot promote.

## Exact command skeleton

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate

# Collect (allowlist F cities; skip-not-invent):
TRADING_MODE=paper traderstack-polymarket-weather-collect --once \
  --cities honolulu,san_diego,miami,phoenix \
  --tape-path var/audit/polymarket_weather_tape.jsonl \
  --max-pages 6

# Resolve (no PnL):
TRADING_MODE=paper traderstack-polymarket-weather-resolve \
  --tape-path var/audit/polymarket_weather_tape.jsonl \
  --resolved-path var/audit/polymarket_weather_resolved.jsonl \
  --emit-resolved-dir var/ops/polymarket_weather_prints \
  --output-md var/ops/polymarket_weather_tape.md \
  --stdout-md

# Eval — resolved packs if any (repeat --resolved per print file;
# argparse action=append — a bare multi-file glob is NOT valid):
TRADING_MODE=paper traderstack-polymarket-weather-eval \
  --resolved var/ops/polymarket_weather_prints/print_2026-08.json \
  --resolved var/ops/polymarket_weather_prints/print_2026-09.json \
  --output-md docs/artifacts/strategy-search/polymarket-weather-eval.md \
  --output-json var/ops/polymarket_weather_eval.json

# Honest empty when no PIT+station resolved rows:
TRADING_MODE=paper traderstack-polymarket-weather-eval --empty-live \
  --output-md docs/artifacts/strategy-search/polymarket-weather-eval.md \
  --output-json var/ops/polymarket_weather_eval.json
```

## Paper-executable path (forward)

1. Cron collect every 15–30m while weather markets are open (GET-only).
2. After event day + 24h settle lag, resolve with IEM+GHCN cross-check.
3. Re-run eval when ≥2 independent monthly prints exist; promote remains
   blocked until dual prints clear the calculator **and** a separate
   Settings pin lands default false (out of scope here).

## Out of scope / cannot-promote reasons

- Fresh tape / markets still open → `awaiting_close` / empty resolved.
- One-sided CLOB books → `book_one_sided` skips (not invented fills).
- Celsius cities → `unit_unsupported`.
- Fewer than two monthly prints → `print_kind=single_print`, can_promote=false.
- No BTC overlay series → crypto overlay skipped_not_invented.
