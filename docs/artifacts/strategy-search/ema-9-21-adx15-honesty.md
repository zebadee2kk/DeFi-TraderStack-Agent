# `ema_9_21_adx15` honesty pack

Generated: 2026-09-12T15:31:24.983437+00:00
Candidate: `ema_9_21_adx15` (documented paper pin `PAPER_PROMOTE_EMA_9_21_ADX15`, default **false**)
Baseline costs: fee=10 bps + slippage=5 bps. Walk-forward: train=180 test=60 step=60; holdout_fraction=20%.
Catalog: expanded. Ranking key: `mean_holdout_excess_among_combined_passers`. Paper DD ceiling: 30% (`PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT`).

## Honesty

Honesty pack for `ema_9_21_adx15` only. No candidate is rewritten to look profitable. Combined ranking uses Kraken BTC+ETH only (`mean_holdout_excess_among_combined_passers`). Yahoo Finance daily is a longer non-Kraken A/B fetched with period1=1410912000 (2014-09-17T00:00:00+00:00) / period2=now so the series stays daily; `range=max` would downsample crypto to monthly. Yahoo cannot promote. Empty or negative Yahoo is a successful research outcome — it is not rewritten as a soft PASS. Walk-forward maxDD is compared to the paper ceiling 30% (`PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT`). This run does not flip `PAPER_PROMOTE_EMA_9_21_ADX15` (default false) and does not enable live. `ema_9_21_adx15` still clears combined and is still top-1 among combined-passers on this reprint.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- SOL/USD@1d: 720 committed Kraken bars 2024-09-22T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- BTC-USD@1d: 4378 Yahoo Finance (yfinance-compatible, non-Kraken) daily bars 2014-09-17T00:00:00+00:00 → 2026-09-11T00:00:00+00:00
- ETH-USD@1d: 3229 Yahoo Finance (yfinance-compatible, non-Kraken) daily bars 2017-11-09T00:00:00+00:00 → 2026-09-11T00:00:00+00:00

## 1. Kraken combined harder-gates reprint

Fresh pull of the same pre-registered A/B/C + #96 combined bar. Yahoo is stripped from this ranking. Confirm whether `ema_9_21_adx15` is still a combined-passer and still top-1 among passers.

| field | value |
| --- | --- |
| id | `ema_9_21_adx15` |
| #96 balanced-holdout | **PASS** |
| A Magnitude | **PASS** |
| B Multi-window | **PASS** |
| C Fee stress | **PASS** |
| Combined | **PASS** |
| combined rank | 1 |
| still top-1 | **yes** |
| mean HO excess | +26.07% |
| BTC holdout | +21.68% |
| ETH holdout | +30.45% |
| min/max ratio | 0.712 |
| BTC WF total | +1.37% |
| ETH WF total | +13.24% |
| mean WF total | +7.31% |
| WF rank (informational) | 4 |
| catalog top-1 | `ema_9_21_adx15` |

Combined-passers on this reprint (informational): `ema_9_21_adx15`, `ema_9_21_adx18`, `ema_12_26_adx18`, `ema_12_26_adx20`.

## 2. Yahoo Finance A/B (non-Kraken; cannot promote)

Yahoo `range=max` downsamples crypto to monthly (`dataGranularity=1mo`). This A/B uses `period1=1410912000` (2014-09-17T00:00:00+00:00) / `period2=1789084800` so the series stays daily. High/low are expanded to contain open/close when Yahoo's print is inconsistent. Closes are **not** Kraken Spot. These rows are for `ema_9_21_adx15` only — the older `ema_9_21` Yahoo BTC-USD holdout (−9.28% on the #97 window) is a different path and is not copied here.

| series | bars | first → last | WF total | WF excess | holdout excess | WF / HO signs |
| --- | ---: | --- | ---: | ---: | ---: | :---: |
| `BTC-USD` | 4378 | 2014-09-17T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 | +11.95% | -4.29% | -15.47% | + / − |
| `ETH-USD` | 3229 | 2017-11-09T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 | +10.69% | -1.31% | +150.33% | + / + |

**Cannot promote.** A negative or empty Yahoo print is success. Do not average these rows with Kraken, and do not wash a losing BTC-USD holdout out with a large ETH-USD tail.

## 3. Walk-forward maxDD vs paper DD ceiling

`PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT` default **30%** is the BTC+ETH research envelope (#98). SOL is in `mvp_assets` and is supporting-only for that ceiling. `ema_9_21` SOL WF maxDD was ~50% on the committed #95 window — the question here is whether `ema_9_21_adx15` still blows past.

| series | source | WF maxDD | vs ceiling | blows past? |
| --- | --- | ---: | --- | --- |
| `BTC/USD` | kraken | +17.93% | under | **no** |
| `ETH/USD` | kraken | +28.77% | under | **no** |
| `SOL/USD` | kraken | +50.01% | over | **yes** |

SOL still blows past the 30% ceiling: **yes**.

## 4. Multi-window (gate B) for this id

Three contiguous 240-bar Kraken daily slices; a window passes iff BTC **and** ETH WF total > 0. Gate B needs ≥ 2 of 3.

| window | bars | first → last | BTC WF | ETH WF | passed |
| --- | ---: | --- | ---: | ---: | --- |
| W1 oldest | 240 | 2024-09-22T00:00:00+00:00 → 2025-05-19T00:00:00+00:00 | +4.87% | +53.49% | yes |
| W2 middle | 240 | 2025-05-20T00:00:00+00:00 → 2026-01-14T00:00:00+00:00 | +10.44% | -16.88% | no |
| W3 newest | 240 | 2026-01-15T00:00:00+00:00 → 2026-09-11T00:00:00+00:00 | +4.68% | +10.55% | yes |

Windows passed: 2/3. Gate B: **PASS**.

## Operator recommendation

**Keep `PAPER_PROMOTE_EMA_9_21_ADX15=false`** until the remaining gaps below are closed or an operator explicitly accepts them as residual research risk. This is not a live-capital claim and not a YouTube / Yahoo PnL copy.

- Single 720-bar Kraken public Spot daily window (~2y; `since` cannot unlock older prints). One combined-passer top-1 is not a second independent venue or era.
- Yahoo Finance daily is labeled non-Kraken and cannot enter ranking, magnitude, multi-window, or fee-stress averages even if both signs are positive.
- Yahoo `BTC-USD` walk-forward excess is -4.29% (non-Kraken A/B; cannot promote).
- Yahoo `BTC-USD` holdout excess is -15.47% (non-Kraken A/B; cannot promote).
- Yahoo `ETH-USD` walk-forward excess is -1.31% (non-Kraken A/B; cannot promote).
- Kraken `SOL/USD` WF maxDD +50.01% exceeds paper DD ceiling 30%. SOL is in `mvp_assets` but the #98 paper DD envelope is BTC+ETH only; a SOL cycle on the promote path can hit `backtest_drawdown_above_maximum`.
- `PAPER_PROMOTE_EMA_9_21_ADX15` stays default **false**. This pack does not enable live and does not flip `PAPER_PROMOTE_EMA_9_21`.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live.
