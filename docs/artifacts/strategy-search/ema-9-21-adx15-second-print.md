# `ema_9_21_adx15` second print

Generated: 2026-09-12T16:03:07.469684+00:00
Candidate: `ema_9_21_adx15` (documented paper pin `PAPER_PROMOTE_EMA_9_21_ADX15`, default **false**)
Also re-scored (informational): `ema_9_21_adx15`, `ema_9_21_adx18`, `ema_12_26_adx18`, `ema_12_26_adx20`.
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Primary Kraken window first bar: 2024-09-22T00:00:00+00:00 (source=`this_run_kraken_btc_first_bar`; last=2026-09-11T00:00:00+00:00; bars=720).
`can_enter_promotion_average=false`; `multi_venue_bar_preregistered=false`; `keep_flag_false=true`.

## Honesty / pre-registered rules

Second print for `ema_9_21_adx15` and the #99/#100 combined-passers (`ema_9_21_adx15`, `ema_9_21_adx18`, `ema_12_26_adx18`, `ema_12_26_adx20`). Pre-registered before any second-print score (do not retune after seeing PnL). (1) Kraken public OHLC cannot unlock a second 720-bar era (`since` pages forward only). (2) Kraken-compatible path that exists: `holdout_blind_prefix` — drop the last holdout_fraction of the public 720 and score the prefix. Same venue; overlapping WF; not an independent era. Gate B still needs 3×240 bars and fails closed if short. (3) A Kraken older-720 is scored only if a supplied series has 720 committed daily bars whose last open is before the primary first bar. Public OHLC cannot produce that. (4) Binance Spot daily BTCUSDT+ETHUSDT slice `older_720_ending_before_primary_first_bar`: 720 committed bars ending strictly before the primary Kraken first bar. Labeled non-Kraken. (5) Same strategy definition and #96+A+B+C gates. (6) Fees are paper-research 10+5 (gate C 20+10). (7) CAN_ENTER_PROMOTION_AVERAGE=false; MULTI_VENUE_BAR_PREREGISTERED=false. Report-only. (8) `PAPER_PROMOTE_EMA_9_21_ADX15` stays default false. No live. Yahoo remains a longer non-Kraken A/B from the honesty pack and is not re-averaged here. Empty or failed Binance is success. This run does not flip `PAPER_PROMOTE_EMA_9_21_ADX15` (default false) and does not enable live. `ema_9_21_adx15` combined-FAILS on the Binance slice. An honest FAIL is the successful outcome.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- primary first bar 2024-09-22T00:00:00+00:00 (source=this_run_kraken_btc_first_bar)
- BTCUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- BTCUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- BTCUSDT@1d: 720 committed binance_us_spot daily bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)
- ETHUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- ETHUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- ETHUSDT@1d: 720 committed binance_us_spot daily bars 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00 (non-Kraken; report-only)

## 1. Kraken-compatible path

### 1a. Second 720-bar Kraken era

- Rule: `older_720_ending_before_primary_first_bar`
- Venue label: `kraken_public_ohlc`
- Status: **UNAVAILABLE / fail-closed**
- Bars: BTC 0 / ETH 0
- Span: n/a → n/a
- Overlaps primary window: no
- Overlaps primary holdout: no
- Fail-closed reason: Kraken public OHLC cannot retrieve bars older than the most recent 720; no non-overlapping second 720 exists

This is **not** invented from Yahoo, charts-spot, or a shuffled offset inside the same 720. Public OHLC cannot page backward.

### 1b. Holdout-blind prefix (same venue; not independent)

- Rule: `holdout_blind_prefix`
- Venue label: `kraken_public_ohlc_holdout_blind_prefix`
- Status: **available**
- Bars: BTC 576 / ETH 576
- Span: 2024-09-22T00:00:00+00:00 → 2026-04-20T00:00:00+00:00
- Overlaps primary window: yes
- Overlaps primary holdout: no
- Fail-closed reason: —

Same Kraken public print as #99/#100 with the primary holdout tail removed. Walk-forward still overlaps the primary research prefix. Gate B needs 720 bars and fails closed on a shorter prefix — that is not retuned to 2×240 after seeing the length.

#### `ema_9_21_adx15` on the prefix

| field | value |
| --- | --- |
| id | `ema_9_21_adx15` |
| venue | kraken_public_ohlc_holdout_blind_prefix |
| #96 balanced-holdout | **FAIL** |
| A Magnitude | **PASS** |
| B Multi-window | **FAIL** |
| C Fee stress | **FAIL** |
| Combined | **FAIL** |
| can promote | **no** |
| combined rank (in this print) | — |
| mean HO excess | +25.45% |
| BTC holdout | +28.15% |
| ETH holdout | +22.75% |
| min/max ratio | 0.808 |
| BTC WF total | -4.58% |
| ETH WF total | +19.01% |
| mean WF total | +7.22% |
| gate B windows | 0/3 |

Gate B reasons: `btc_insufficient_bars_for_multiwindow`, `eth_insufficient_bars_for_multiwindow`.

Other #99/#100 combined-passers on the prefix (informational):

| id | #96 | A | B | C | combined | mean HO | BTC HO | ETH HO | can promote |
| --- | :---: | :---: | :---: | :---: | :---: | ---: | ---: | ---: | :---: |
| `ema_9_21_adx15` | FAIL | PASS | FAIL | FAIL | **FAIL** | +25.45% | +28.15% | +22.75% | no |
| `ema_9_21_adx18` | FAIL | PASS | FAIL | FAIL | **FAIL** | +28.67% | +29.55% | +27.79% | no |
| `ema_12_26_adx18` | PASS | PASS | FAIL | FAIL | **FAIL** | +6.33% | +5.70% | +6.97% | no |
| `ema_12_26_adx20` | FAIL | PASS | FAIL | FAIL | **FAIL** | +11.63% | +11.46% | +11.79% | no |

## 2. Binance Spot daily (non-Kraken; report-only)

### 2a. Venue and fees

Source this run: `binance_us_spot`. `api.binance.com` is HTTP 451 from this environment; `api.binance.us` is the reachable public Spot kline host and is labeled **Binance.US**, not Binance.com. Pairs are BTCUSDT and ETHUSDT. Do not average with Kraken.

Binance.US Spot published taker is typically 10 bps at the lowest listed tier. This print uses the paper-research defaults `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` + `PRETRADE_SLIPPAGE_BPS` (10+5; gate C at 20+10) so costs stay comparable to the Kraken print. Not a maker-rebate or VIP study. Quote is USDT, not USD.

### 2b. Slice

- Rule: `older_720_ending_before_primary_first_bar`
- Venue label: `binance_us_spot`
- Status: **available**
- Bars: BTC 720 / ETH 720
- Span: 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00
- Overlaps primary window: no
- Overlaps primary holdout: no
- Fail-closed reason: —

Pre-registered: 720 committed daily bars ending strictly before the primary Kraken first bar. This window does not overlap the primary holdout. A short or overlapping series fails closed and is not rewritten as a soft PASS.

### 2c. `ema_9_21_adx15` vs harder gates

| field | value |
| --- | --- |
| id | `ema_9_21_adx15` |
| venue | binance_us_spot |
| #96 balanced-holdout | **FAIL** |
| A Magnitude | **FAIL** |
| B Multi-window | **FAIL** |
| C Fee stress | **FAIL** |
| Combined | **FAIL** |
| can promote | **no** |
| combined rank (in this print) | — |
| mean HO excess | -15.80% |
| BTC holdout | -29.21% |
| ETH holdout | -2.39% |
| min/max ratio | n/a |
| BTC WF total | +14.95% |
| ETH WF total | +3.03% |
| mean WF total | +8.99% |
| gate B windows | 0/3 |

Fail reasons: A: `btc_holdout_excess_not_positive`, `eth_holdout_excess_not_positive`; B: `multiwindow_fewer_than_min_passes`; C: `holdout_excess_return_not_positive`, `btc_holdout_excess_not_positive`, `eth_holdout_excess_not_positive`.

Binance combined for `ema_9_21_adx15`: **FAIL**. Cannot enter the promotion average. Cannot flip `PAPER_PROMOTE_EMA_9_21_ADX15`.

### 2d. Other #99/#100 combined-passers (informational)

| id | #96 | A | B | C | combined | mean HO | BTC HO | ETH HO | can promote |
| --- | :---: | :---: | :---: | :---: | :---: | ---: | ---: | ---: | :---: |
| `ema_9_21_adx15` | FAIL | FAIL | FAIL | FAIL | **FAIL** | -15.80% | -29.21% | -2.39% | no |
| `ema_9_21_adx18` | FAIL | FAIL | FAIL | FAIL | **FAIL** | -7.67% | -32.77% | +17.44% | no |
| `ema_12_26_adx18` | FAIL | FAIL | FAIL | FAIL | **FAIL** | -14.58% | -40.62% | +11.47% | no |
| `ema_12_26_adx20` | FAIL | FAIL | FAIL | FAIL | **FAIL** | -14.78% | -43.64% | +14.07% | no |

## Operator recommendation

**Keep `PAPER_PROMOTE_EMA_9_21_ADX15=false`.** This second print is report-only. A multi-venue bar was not pre-registered, so a Binance combined-pass cannot enter the promotion average and cannot flip the pin. An honest FAIL is success.

- Kraken second 720-bar era: UNAVAILABLE (Kraken public OHLC cannot retrieve bars older than the most recent 720; no non-overlapping second 720 exists).
- Kraken `holdout_blind_prefix`: 576 BTC / 576 ETH bars (2024-09-22T00:00:00+00:00 → 2026-04-20T00:00:00+00:00). Same venue; not independent.
- Binance `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH; 2022-10-03T00:00:00+00:00 → 2024-09-21T00:00:00+00:00).
- `ema_9_21_adx15` Binance #96=FAIL A=FAIL B=FAIL C=FAIL combined=**FAIL** (cannot promote).
- `PAPER_PROMOTE_EMA_9_21_ADX15` stays default **false**. Do not enable live.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average this print with the #99/#100 Kraken window.
