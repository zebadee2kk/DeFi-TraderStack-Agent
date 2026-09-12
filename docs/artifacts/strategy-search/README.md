# Strategy search artifacts

This directory holds committed offline search reports. Two catalogs share it.

## Catalog search (`traderstack-strategy-search`)

Committed output of `traderstack-strategy-search` on **Kraken charts-spot
`PI_*`** (research-only; not the 720-bar public Spot OHLC). BTC/USD, ETH/USD,
SOL/USD. Costs: `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)=10` +
`PRETRADE_SLIPPAGE_BPS=5`.

This is **not** a profitability claim.

## Windows

| file | interval | source | bars / asset | span |
| --- | --- | --- | ---: | --- |
| `report.md` / `report.json` | 1h | `kraken_charts_spot` | 4320 | 2026-03-16 13:00 → 2026-09-12 12:00 UTC (180.0d) |
| `report-4h.md` / `report-4h.json` | 4h | `kraken_charts_spot` | 1080 | 2026-03-16 12:00 → 2026-09-12 08:00 UTC (179.8d) |

Public `GET /0/public/OHLC` cannot reach this history: a `since` of 180 days
ago still returns the same most-recent **720** 1h bars. Charts-spot closes can
differ a few bps from that print; volume is zero on this path.

## Result

**No catalog member cleared the promotion gate on either window.**

Promotion requires WF mean **total** return > 0 after fees, min trades, and
holdout mean excess > 0. Ranking is pre-registered top-1 by WF excess (K=23;
Bonferroni analogue 0.05/23 ≈ 0.0022). Top-1 failing holdout does **not**
unlock #2.

### 1h (primary, paper-aligned timeframe)

Every rankable candidate had **negative** walk-forward total return *and*
negative excess after fees.

| top-1 / notable | WF excess | WF total | holdout excess | promoted |
| --- | ---: | ---: | ---: | --- |
| `funding_z_follow` (top-1) | **−0.11%** | **−0.09%** | **−20.12%** | no |
| `oi_z_follow` | −0.43% | −0.41% | −28.92% | no |
| `ma_always_on_10_30` | −0.86% | −0.84% | −16.03% | no |
| `momentum_6` (PR #89 30d top-1) | −1.11% | −1.09% | −18.56% | no |

### 4h (supporting mix)

Three names posted positive WF total after fees. All three **failed holdout**.

| top-1 / notable | WF excess | WF total | holdout excess | promoted |
| --- | ---: | ---: | ---: | --- |
| `momentum_12_strict` (top-1) | +0.44% | **+0.45%** | **−13.06%** | no (holdout failed) |
| `momentum_6_vol` | +0.19% | +0.19% | −13.89% | no (not top-1; holdout failed) |
| `ma_cross_5_20` | +0.06% | +0.06% | −13.96% | no (not top-1; holdout failed) |

## Edge series

| series | status |
| --- | --- |
| Binance USDT-M funding / OI / `allForceOrders` | **skipped** — HTTP 451 from this environment |
| Binance historical liquidations | **skipped** — no public USDT-M historical REST; live WS is `!forceOrder@arr`; Vision `um/liquidationSnapshot` removed |
| OKX funding-rate-history | **ok** — 289 prints (~90d of 8h) per BTC/ETH/SOL |
| OKX 1h open-interest-history | **ok** — 1440 points (~60d) per symbol |
| OKX liquidation-orders | **skipped** — ~5–19h of recent fills, not a historical aggregate |
| Cross-venue divergence | **skipped** — no aligned two-venue series supplied |

**Leave `PAPER_PROMOTE_SEARCHED_STRATEGIES=false`.**
`PAPER_PROMOTE_SEARCHED_STRATEGY_ID` stays empty — there is no id to pin.

Offline unit tests use the smaller synthetic files in
`tests/fixtures/strategy_search/` (not this live window). Runtime default
writes the same JSON/MD pair to `var/ops/` (gitignored).

## Miles-inspired catalog (`traderstack-miles-search`)

Committed output of `traderstack-miles-search --live-kraken` on Kraken public
Spot OHLC (`GET https://api.kraken.com/0/public/OHLC`) for BTC/USD, ETH/USD,
SOL/USD.

Kraken returns at most 720 of the most recent committed bars per pair and
interval. Daily (2024-09-22 → 2026-09-11) is the promotion window. 1h
(2026-08-13 → 2026-09-12) is robustness only — 1h percent returns are not
averaged with daily.

Costs: `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)=10` + `PRETRADE_SLIPPAGE_BPS=5`.

### Result on this window

`ema_9_21` cleared the daily bar (WF mean total return +7.92%, holdout mean
excess +22.20% after fees). That holdout is one ~144-day tail and is ETH-heavy.
Every GARCH-sized candidate lost money after fees (more turnover). 1h lost
money for the same EMA.

**Leave `PAPER_GARCH_SIZE=false`.** This is not a live-capital claim and not
a YouTube PnL copy. Register `ema_9_21` as a paper voter only via the
documented `PAPER_PROMOTE_EMA_9_21` flag (default false). That flag forces
paper candles to daily (`1d` / 1440m) and uses
`PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT` (default 0.30) so the ~23%
daily WF maxDD is not rejected by the 1h 15% bar. Do not claim this
daily edge on a 1h runtime.

See `miles-inspired-report.md`.

## Daily robustness (`traderstack-daily-robustness`)

Stress-test of the #93 daily winner plus dual-momentum and buy-the-dip
mean-reversion on the longest **Kraken public Spot daily** window the API
allows (720 committed bars, ~2 years). `since` cannot unlock older Kraken
prints. Optional Yahoo Finance `BTC-USD` / `ETH-USD` daily is a longer
**non-Kraken** A/B and never enters the promotion average.

Promotion is stricter than #93: **BTC and ETH** must both have fee-aware
walk-forward mean total return > 0, plus holdout mean excess > 0. The
three-asset mean that let ETH dominate #93's holdout is not enough.

On the 2026-09-12 Kraken window, `ema_9_21` still cleared BTC WF +4.57%
and ETH WF +14.61% (holdout remains ETH-heavy: +5.55% vs +58.37%). Dual-
momentum and buy-the-dip did not. Documented pin is
`PAPER_PROMOTE_EMA_9_21` (default false). Yahoo daily is supporting only.

See `daily-robustness-report.md`.

## Balanced holdout (`traderstack-daily-robustness`, default bar)

The #95 bar still lets an ETH holdout tail carry a **mean** that is
positive while BTC holdout is not. The default promotion bar now also
requires **BTC holdout excess > 0 and ETH holdout excess > 0**. SOL is
reported and is not a gate. Yahoo remains A/B only.

The catalog is pre-registered (frozen before the window is scored): the
#95 EMA/ADX names, slower EMA 20/50 and 50/200, a dual-mom lookback
grid, a dip z grid, asset-local and BTC-overlay SMA200 risk-off, and
two GARCH size overlays. `PAPER_GARCH_SIZE` and
`PAPER_PROMOTE_EMA_9_21` stay false unless a committed report names a
paper-only pin and an operator flips the flag.

On the 2026-09-12 Kraken 720-bar daily window (2024-09-22 → 2026-09-11),
`ema_9_21` **PASS**ed both bars: BTC WF +4.57% / ETH WF +14.61%, BTC
holdout excess +5.55% / ETH +58.37%. The ETH tail is still large; the
new bar only requires both **signs** > 0. Slower EMAs, dual-mom, dip,
and both GARCH overlays failed. Yahoo BTC-USD holdout excess stayed
negative and did not enter the average. Leave
`PAPER_PROMOTE_EMA_9_21=false` (documented paper-only pin only).

See `balanced-holdout-report.md`.

## Harder honesty gates (`traderstack-harder-gates`)

Pre-registered before scoring (do not retune after seeing the print):

| gate | rule |
| --- | --- |
| A Magnitude | BTC and ETH holdout excess > 0 **and** min/max ≥ 0.25 |
| B Multi-window | 3 contiguous 240-bar Kraken daily slices; BTC and ETH WF total > 0 in ≥ 2 of 3 |
| C Fee stress | 2× fees (20+10 bps) still clear #96 balanced signs |
| Combined | #96 **and** A **and** B **and** C **and** pre-registered top-1 |

Yahoo / non-Kraken stays A/B only. #96-eligible ADX/SMA names are
re-scored and cannot skip a failing `ema_9_21` top-1. This command
never flips `PAPER_PROMOTE_EMA_9_21`. An honest FAIL is success.

On the 2026-09-12 Kraken 720-bar daily window (2024-09-22 → 2026-09-11),
`ema_9_21` **FAIL**ed the combined bar:

| gate | `ema_9_21` | evidence |
| --- | --- | --- |
| A Magnitude | **FAIL** | BTC HO +5.55% / ETH +58.37%, ratio 0.095 < 0.25 |
| B Multi-window | **FAIL** | 1 of 3 windows (W2 ETH WF −16.88%, W3 BTC WF −8.99%) |
| C Fee stress | **PASS** | 2× fees still BTC/ETH WF and holdout signs > 0 |
| Combined | **FAIL** | A and B failed. Leave `PAPER_PROMOTE_EMA_9_21=false`. |

`ema_12_26_adx20` cleared A+B+C+#96 but is rank 4, not top-1 — it is
**not** promoted. Yahoo BTC-USD holdout excess stayed −9.28% and did
not enter the average.

See `magnitude-multiwindow-report.md`.

## Expanded harder-gates catalog (`traderstack-harder-gates`, default)

Same A/B/C gates and Kraken 720-bar daily window as #97, with a
**larger catalog frozen before the live pull**: more ADX thresholds,
faster/slower EMAs, SMA200 risk-off variants, dual-mom lookbacks, and
dip+vol grids. Yahoo remains A/B only.

Ranking key (frozen before scoring): **mean holdout excess among
combined-passers** (`#96` + A + B + C). Walk-forward rank of the full
catalog is informational. #97 required the WF-total #1 to also clear
A+B+C and therefore did not promote `ema_12_26_adx20` (combined PASS,
rank 4). This key selects among names that already cleared the bar.

`PAPER_PROMOTE_EMA_9_21` stays false. On the 2026-09-12 Kraken 720-bar
daily window (2024-09-22 → 2026-09-11) four names cleared combined:

| combined rank | id | mean HO excess | BTC HO | ETH HO | ratio | promoted |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `ema_9_21_adx15` | +26.07% | +21.68% | +30.45% | 0.712 | research only |
| 2 | `ema_9_21_adx18` | +24.41% | +22.90% | +25.93% | 0.883 | no |
| 3 | `ema_12_26_adx18` | +18.11% | +17.37% | +18.85% | 0.921 | no |
| 4 | `ema_12_26_adx20` | +9.87% | +4.53% | +15.20% | 0.298 | no (#97 rank-4) |

Documented paper-only pin: `PAPER_PROMOTE_EMA_9_21_ADX15` (default
**false**). This report does not flip it and does not enable live.
`ema_9_21` still fails A and B.

See `expanded-harder-gates-report.md`.

## Honesty pack (`traderstack-honesty-pack`)

Focused reprint for the `#99` promotee `ema_9_21_adx15` only. Re-scores
the Kraken combined row (still top-1?), Yahoo Finance daily A/B for
**this** candidate (`period1`/`period2`; labeled non-Kraken; cannot
promote), WF maxDD on BTC/ETH/SOL vs the paper DD ceiling 0.30, and
the gate-B multi-window table. Empty or negative Yahoo is success.
The pin stays default **false**.

On the 2026-09-12 reprint (same 720-bar Kraken daily window as #99):

- Still combined **PASS** and still top-1 (mean HO +26.07%, ratio 0.712).
- Yahoo BTC-USD holdout excess **−15.47%** (WF total +; cannot promote).
  The older `ema_9_21` Yahoo BTC holdout was −9.28% — this path is worse.
- Yahoo ETH-USD holdout excess +150.33% (WF total +; cannot promote).
- SOL WF maxDD **+50.01%** still blows past the 0.30 paper ceiling.
  BTC +17.93% and ETH +28.77% stay under.
- Gate B 2/3 (W2 ETH WF −16.88%).

Leave `PAPER_PROMOTE_EMA_9_21_ADX15=false`. When an operator does
flip a daily paper pin, `PAPER_PROMOTE_UNIVERSE` (default
`BTC/USD,ETH/USD`) keeps SOL off that cycle list
(`promote_universe_excluded`) so the 0.30 ceiling is not applied to
a name outside the envelope. Universe alignment, not a claim of edge.

See `ema-9-21-adx15-honesty.md`.

## Second print (`traderstack-second-print`)

Closes the #100 gap: one Kraken 720-bar window is not a second
independent venue or era. Slice rules are frozen before scoring.

| path | rule | can promote? |
| --- | --- | --- |
| Kraken second 720 | public OHLC cannot page backward | n/a (UNAVAILABLE) |
| Kraken holdout-blind prefix | drop last 20% of the public 720 | no (same venue) |
| Binance Spot daily BTCUSDT+ETHUSDT | 720 committed bars ending before the primary Kraken first bar | no (report-only; multi-venue bar not pre-registered) |

`api.binance.com` is HTTP 451 here; `api.binance.us` is labeled
Binance.US. Yahoo is not re-averaged. Same #96+A+B+C gates and 10+5
bps (gate C 20+10). An honest FAIL is success.
`PAPER_PROMOTE_EMA_9_21_ADX15` stays false.

On the 2026-09-12 run (primary Kraken first bar 2024-09-22, last
2026-09-11):

- Kraken second 720: **UNAVAILABLE**.
- Kraken prefix 576 bars (2024-09-22 → 2026-04-20): `ema_9_21_adx15`
  combined **FAIL** (#96 FAIL on BTC WF −4.58%; B FAIL insufficient
  bars; C FAIL). Same venue; not independent.
- Binance.US Spot 720 (2022-10-03 → 2024-09-21, no overlap):
  `ema_9_21_adx15` #96/A/B/C/combined all **FAIL**. Mean HO excess
  **−15.80%** (BTC HO −29.21%, ETH −2.39%). WF totals were positive
  (BTC +14.95% / ETH +3.03%) — beating a falling holdout while
  losing the holdout is not an edge. The other three #99/#100
  passers also combined-FAIL.

See `ema-9-21-adx15-second-print.md`.

## Dual-print search (`traderstack-dual-print-search`)

#102 failed the Binance.US older-720 for every #99 combined-passer, and
that print could not enter a promotion average because a multi-venue
bar had not been pre-registered. This command freezes the dual-print
bar **before** the pull:

| print | rule | enters ranking average? |
| --- | --- | --- |
| Kraken primary 720 | #96+A+B+C; rank dual-print passers by Kraken mean HO | Kraken mean HO only |
| Binance.US older 720 | same #102 slice; must combined-PASS | no (gate only) |

Catalog is a frozen superset of the #99 grid (K=65 core / 70 with BTC
overlay): more EMA/ADX, SMA100/200 risk-off, dual-mom, dip+vol, and
candle-only vol-regime wrappers. Liquidation / funding / OI stay
skipped on public Spot OHLC. A Kraken-only combined-passer cannot
promote. Empty dual-print set is success.
`PAPER_PROMOTE_*` stays false. No new pin unless a committed report
names a passer (default false if added).

On the 2026-09-12 live run (catalog committed first):

- Kraken primary still 2024-09-22 → 2026-09-11 (720).
- Binance.US older-720 still 2022-10-03 → 2024-09-21 (720; no overlap).
- Kraken combined-passers: 5. Top-1 remains `ema_9_21_adx15`
  (mean HO +26.07%). New name `ema_8_21_adx15` is Kraken #2
  (+25.08%) — still Kraken-only.
- Binance.US combined-passers: **0**. All five Kraken passers
  combined-FAIL on Binance (mean HO −7.67% to −15.80%).
- Dual-print passers: **0**. No new `PAPER_PROMOTE_*` pin.

See `dual-print-search.md`.

## Liquidation / regime-conditioned search (`traderstack-liq-regime-search`)

#104's dual-print EMA catalog had zero passers. This command pivots to
features already scaffolded in-repo: liquidation-z, funding-z, OI-z,
cross-venue, and candle-only vol-regime wrappers.

| print | when | can promote? |
| --- | --- | --- |
| single-print | no usable historical liquidation series on BTC+ETH | **no** |
| dual-print | historical liq on BTC+ETH **and** a second venue print | still no Settings flip |

Public USDT-M liquidation REST is typically unusable and is skipped,
not zero-filled. Live paper `!forceOrder@arr` / bookTicker snapshots
are not a historical series. Crucix → `adverse_event` was already
wired as a news veto and is unchanged.

`PAPER_PROMOTE_*` stays false. Empty search is success.

On the 2026-09-12 live Kraken daily 720 (2024-09-22 → 2026-09-11):

- Historical liquidation: **unavailable** (Binance HTTP 451 / no public
  REST; OKX liquidation-orders span hours). Single-print.
- OKX funding (~90d) and 1h OI (~60d) scored; no #89-eligible row.
- Informational WF-excess top-1 `ma_always_on_10_30_vol` is not
  eligible (WF excess −4.40%). No promotee.

See `liq-regime-search.md`.

## Polymarket weather eval (`traderstack-polymarket-weather-eval`)

#44 records would-trade intents. This command is the fee-aware
calculator for EVALUATION-FRAMEWORK gates 1 / 4 / 5 (point-in-time
treatment vs `always_hold` / `fade_the_mid`, station match, conservative
costs). A pre-registered crypto overlay
(`polymarket_weather_vs_btc_daily`) is skipped unless an aligned BTC
daily close series is supplied.

| print | when | can promote? |
| --- | --- | --- |
| single-print | fewer than two independent resolved packs | **no** |
| dual-print | non-overlapping `event_date` sets **or** overlapping dates with disjoint resolution sources; each pack must also clear the calculator floor | still **no** Settings flip |

This repository has no public point-in-time CLOB mid + official
ASOS/NCEI high tape. Using a settlement price as the decision mid is
look-ahead. The committed 2026-09-12 run is `--empty-live`: **0**
eligible rows, single-print, cannot promote. Empty is success.
`PAPER_PROMOTE_*` stays false. No `PAPER_PROMOTE_POLYMARKET_WEATHER`
Settings field is added.

Fixture packs under `tests/fixtures/polymarket/resolved_print_*.json`
prove the calculator (tiny n; cannot promote). They are not a live
season.

See `polymarket-weather-eval.md`.

## Intraday dual-print (`traderstack-intraday-dual-print`)

#104 daily EMA dual-print, #105 historical liquidation, and #106
Polymarket PIT tape were all empty. This command is a **different
family**: fee-aware #96+A+B+C on Kraken public Spot **4h** (default;
`1h` alternate) BTC+ETH, plus the #102-style Binance.US older-720 of
the same interval.

| print | rule | can enter ranking average? |
| --- | --- | --- |
| Kraken primary 720 | 4h or 1h public Spot; #96+A+B+C; rank dual-print passers by Kraken mean HO | Kraken mean HO only |
| Binance.US older 720 | same interval; 720 bars ending before the primary Kraken first bar | no (gate only) |

Catalog is frozen non-EMA (MA / momentum / mean-reversion / vol-regime;
two EMA names as controls). Funding/OI instantiate only when an
aligned series is fetched. Liquidation-z and cross-venue stay skipped.
A Kraken-only combined-passer cannot promote. Empty dual-print set is
success. `PAPER_PROMOTE_*` stays false. No new pin unless a committed
report names a passer (default false if added).

On the 2026-09-12 live run (catalog committed first):

- Kraken 4h primary: 2026-05-15 16:00 → 2026-09-12 12:00 UTC (720).
- Binance.US older-720 4h: 2026-01-15 16:00 → 2026-05-15 12:00 UTC
  (720; no overlap). `api.binance.com` HTTP 451; labeled Binance.US.
- OKX funding (~90d of 8h) and 1h OI scored; liquidation skipped.
- Kraken combined-passers: **0**. Every Kraken mean HO was negative.
- Binance.US combined-passers: **0**.
- Dual-print passers: **0**. No new `PAPER_PROMOTE_*` pin.

See `intraday-dual-print.md`.

## Funding / carry (`traderstack-funding-carry`)

#104–#106 and #108 were empty. This command is a **different family**:
fee-aware funding-z thresholds, funding-agree spot overlays, and a
modeled hedged cash-and-carry on BTC+ETH.

| print | when | can promote? |
| --- | --- | --- |
| single-print | only one usable funding venue on BTC+ETH | **no** |
| dual-print | two independent funding venues (e.g. OKX **and** Hyperliquid) | still no Settings flip |

OKX public funding-rate-history is typically ~90d of 8h prints.
Hyperliquid `fundingHistory` is hourly and typically reachable here.
Binance USDT-M is often HTTP 451; Bybit linear is often HTTP 403.
Hard gates (#96+A+B+C) stay UNAVAILABLE unless 720 aligned daily bars
exist on two venues. Hedged carry does not invent basis.
`PAPER_PROMOTE_*` stays false. Empty dual-print is success.

On the 2026-09-12 live run (catalog committed first):

- Kraken 4h 720 (2026-05-15 16:00 → 2026-09-12 12:00 UTC); funding
  overlap 578 bars (OKX 290 8h prints from 2026-06-08).
- Binance funding: **skipped** (HTTP 451). Single-print.
- Hard gates: **UNAVAILABLE**.
- Spot-signal top-1 `funding_z_follow_2_0` WF excess **−0.46%**
  (ineligible). Every overlay and the MA control also lost after fees.
- Modeled `carry_hedged_sign` WF +0.16% / holdout +0.33% on this one
  tape — not dual-print, basis not modeled, cannot promote.

Follow-up the same day: Hyperliquid public `fundingHistory` is
reachable here and is the wired second tape. Bybit is HTTP 403
(CloudFront). Same frozen catalog. Dual-print numbers overwrite
`funding-carry.md`. Empty dual-print is still success. No new pin.

See `funding-carry.md` and the 2026-09-12 status memo
`edge-status-2026-09-12.md`.

