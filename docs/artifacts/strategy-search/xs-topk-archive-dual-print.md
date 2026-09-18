# Long-only top-k cross-sectional momentum (wide Kraken USD universe)

Generated: 2026-09-18T09:14:24.955742+00:00

## Pre-registered header (frozen before any result below)

- Universe listing: `candles_dir_listing` fetched n/a; 45 candidate pairs after exclusions.
- Exclusion rule: status=online; quote in {ZUSD, USD}; wsname present; no `.d` dark-pool pairs; XBT->BTC and XDG->DOGE aliases; drop any base that starts or ends with `USD`; drop the frozen EXCLUDED_BASES list (stablecoins, fiat, tokenised commodities, wrapped / liquid-staked duplicates).
- Liquidity filter: `trailing_30d_median_dollar_volume_top_20_pit` (monthly, point-in-time).
- Frozen grid: N in [21, 63, 126] with a 7-day skip; k in [3, 5]; weights ['ew', 'iv']; rebalance `monday_utc_close_fill_next_open`; MIN_CROSS_SECTION=10; eligibility N+8 bars.
- Ranking key: `mean_era_excess_vs_ew_bh_among_dual_print_passers` (selection `top1_by_ranking_key_tiebreak_candidate_id`).
- Portfolio bar: `pilot_cost_net_return_pos_and_net_sharpe_pos_and_excess_vs_ew_bh_pos_in_every_covered_era_and_print_holdout_excess_pos`.
- Dual-print rule: `two_independent_covered_cells_pass_and_no_covered_cell_or_holdout_fails`.
- Eras (local constant pending #135): ['2016-2019', '2020-2022', '2022-2024', '2024-2026']; a cell is covered with >= 365 daily bars.
- Costs: research fee=10 bps + slippage=5 bps; pilot tier taker=80 bps + slippage=5 bps (Kraken Pro spot tier 1 ($0+ 30d volume) taker 0.80% per side). The bar and the ranking use the pilot print.
- Holdout: last 20% of each print (pilot cost).
- DSR / PBO: `not_computed_pending_135`.
- `multi_venue_bar_preregistered=true`; `can_average_venues=false`; `paper_path_ready=true`; `keep_flag_false=true`.

## Data sources reached

Print kind: committed daily spot OHLC bars per name; a skipped series is a skip, never a zero.

| print | source | status | names loaded | names skipped | window | bars (max) | snapshots | eras covered | fail-closed reason |
| --- | --- | :---: | ---: | ---: | --- | ---: | ---: | --- | --- |
| `kraken` | candles_dir:var/research/candles/kraken | **ok** | 43 | 0 | 2024-09-28T00:00:00+00:00 → 2026-09-17T00:00:00+00:00 | 720 | 23 | 2024-2026 | — |
| `coinbase` | candles_dir:var/research/candles/coinbase | **ok** | 45 | 0 | 2024-09-24T00:00:00+00:00 → 2026-09-17T00:00:00+00:00 | 724 | 23 | 2024-2026 | — |

## Honesty / pre-registered rules

Pre-registered long-only top-k cross-sectional momentum bar on the point-in-time Kraken USD spot universe (frozen before any score). Universe: `trailing_30d_median_dollar_volume_top_20_pit` on a frozen dated AssetPairs listing (status=online; quote in {ZUSD, USD}; wsname present; no `.d` dark-pool pairs; XBT->BTC and XDG->DOGE aliases; drop any base that starts or ends with `USD`; drop the frozen EXCLUDED_BASES list (stablecoins, fiat, tokenised commodities, wrapped / liquid-staked duplicates).). Score on each Monday UTC close t: close[t-7] / close[t-7-N] - 1 for N in [21, 63, 126] (one-week skip). A name missing either close or with fewer than N+8 bars through t is skipped for that rebalance, never zero-filled. Fewer than MIN_CROSS_SECTION=10 rankable names -> flat week (counted). Long the top k in [3, 5]; weights `ew` (1/k) or `iv` (inverse trailing 30-day sample vol, normalised to 1); long-only, no leverage, no shorts. Rebalance rule `monday_utc_close_fill_next_open`: decide on close t, fill at the next bar open, drift between rebalances. Turnover and fee drag are reported at research 10+5 bps and at the frozen pilot-tier cost (Kraken Pro spot tier 1 ($0+ 30d volume) taker 0.80% per side; 80 bps + 5 bps slippage). Control `ew_bh_universe` = equal weight of the same monthly snapshot names, refreshed at each snapshot, otherwise buy-and-hold; it cannot promote. Portfolio bar `pilot_cost_net_return_pos_and_net_sharpe_pos_and_excess_vs_ew_bh_pos_in_every_covered_era_and_print_holdout_excess_pos` at the pilot cost: every covered era needs net return > 0, net Sharpe > 0 and net excess over the control > 0, plus the print's last-20% holdout net excess > 0; a family that only works in one era fails. A cell (venue x era) is covered with >= 365 daily bars inside the era; eras ['2016-2019', '2020-2022', '2022-2024', '2024-2026'] are a local constant pending the #135 shared era policy. Dual print `two_independent_covered_cells_pass_and_no_covered_cell_or_holdout_fails`: two independent covered cells (distinct venues or non-overlapping eras) must pass and none may fail; one venue over one era cannot promote. Ranking key: mean_era_excess_vs_ew_bh_among_dual_print_passers (tie-break: candidate_id); CAN_AVERAGE_VENUES=false; MULTI_VENUE_BAR_PREREGISTERED=true. DSR / PBO: not_computed_pending_135 (Deflated Sharpe and PBO land with #135). Paper-executable on Kraken spot as candle-only long/flat signals (PAPER_PATH_READY=true); the runtime allowlist and RiskEngine limits are documented, not widened. PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not a #117 top-1 reprint. Frozen catalog (K=13): `xs_topk_{ew|iv}_{N}_k{3|5}` for N in [21, 63, 126] (12 baskets) plus the informational control `ew_bh_universe` (cannot promote). Do not grow this list after seeing PnL. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it (default false if ever added). This run scored K=13 (core ids frozen at 13) on 2 print(s). Single-print bar passers (ex-control): 0. Dual-print passers: 0. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

## Universe (point-in-time within a frozen listing)

Universe listing is Kraken public `GET /0/public/AssetPairs` at the fetch time recorded in the report header — a CURRENT listing. Delisted names are absent (survivorship), so membership is frozen from that dated listing and treated as a fixed candidate list, not a point-in-time listing history (that needs the Kraken OHLCVT archive, #133). Within the frozen list, monthly membership is point-in-time: `trailing_30d_median_dollar_volume_top_20_pit` uses only bars strictly before each snapshot date. Dollar volume is close × base volume from the OHLC print only. A name without a full trailing window, or with a zero median, is skipped for that month, never zero-filled.

## Pre-registered catalog

Frozen catalog (K=13): `xs_topk_{ew|iv}_{N}_k{3|5}` for N in [21, 63, 126] (12 baskets) plus the informational control `ew_bh_universe` (cannot promote). Do not grow this list after seeing PnL. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it (default false if ever added).

Frozen core ids: `xs_topk_ew_21_k3`, `xs_topk_ew_21_k5`, `xs_topk_ew_63_k3`, `xs_topk_ew_63_k5`, `xs_topk_ew_126_k3`, `xs_topk_ew_126_k5`, `xs_topk_iv_21_k3`, `xs_topk_iv_21_k5`, `xs_topk_iv_63_k3`, `xs_topk_iv_63_k5`, `xs_topk_iv_126_k3`, `xs_topk_iv_126_k5`, `ew_bh_universe`.

## Paper path and RiskEngine layering

This family is paper-executable on Kraken spot as candle-only long/flat signals per name: `CrossSectionalTopKVoter` emits Side.BUY on an assigned bar and no side otherwise (never Side.SELL); paper_simulate_fills already books that. No perp, no funding, no hedge book, no invented basis. `paper_path_ready` does NOT mean the runtime cycles twenty names: MVP_ASSETS and PAPER_PROMOTE_UNIVERSE are unchanged and would reject most universe names with `asset_not_allowlisted` — that is correct layering. A Settings pin is added only if a committed dual-print passer exists, and then default false.

RiskEngine layering (documented, not widened): max(TOPK_KS)=5 equals the MAX_OPEN_POSITIONS default (5); 5 x MAX_POSITION_PCT (0.10) = 0.50 fits under MAX_GROSS_EXPOSURE_PCT (0.60); `max_positions_reached` remains the binding control. This family reads no Settings and cannot raise any limit, side, asset list or size.

## Kraken public OHLC cap

Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.

## Data notes

- kraken: loaded 43 daily names from var/research/candles/kraken, skipped 0
- coinbase: loaded 45 daily names from var/research/candles/coinbase, skipped 0

## Dual-print passers (promotion ranking)

Frozen ranking key: `mean_era_excess_vs_ew_bh_among_dual_print_passers`. Only baskets that pass the portfolio bar on at least two independent covered cells with no failing cell appear here. `ew_bh_universe` is excluded. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | mean era excess vs ew_bh (pilot) | cells passed | selected | can flip flag |
| ---: | --- | ---: | ---: | :---: | :---: |
| — | — | n/a | 0 | no | no |

## Era table (every covered venue x era cell; turnover and fee drag at both costs)

Net returns are basket total returns over the era. Fee drag is total fees / starting equity over the era at each cost print. One-way turnover per year is half the traded fraction of equity, annualised. Weekly rebalancing of a five-name basket is where this family usually dies; the pilot column makes that visible.

| id | print | era | covered | bars | net ret (10+5) | net ret (pilot) | control (pilot) | excess vs ew_bh (pilot) | Sharpe (pilot) | maxDD (pilot) | one-way turnover/yr | fee drag (10+5) | fee drag (pilot) | bar |
| --- | --- | --- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| `xs_topk_ew_21_k3` | `kraken` | 2024-2026 | yes | 720 | -77.71% | -88.73% | -43.57% | -45.16% | -1.064 | +96.52% | 24.090 | +12.21% | +56.64% | FAIL |
| `xs_topk_ew_21_k5` | `kraken` | 2024-2026 | yes | 720 | -61.69% | -79.05% | -43.57% | -35.48% | -0.701 | +93.84% | 21.516 | +15.51% | +72.46% | FAIL |
| `xs_topk_ew_63_k3` | `kraken` | 2024-2026 | yes | 720 | -80.67% | -86.69% | -43.57% | -43.12% | -0.981 | +92.89% | 13.230 | +3.65% | +18.30% | FAIL |
| `xs_topk_ew_63_k5` | `kraken` | 2024-2026 | yes | 720 | -76.66% | -83.86% | -43.57% | -40.30% | -0.918 | +90.50% | 13.174 | +3.48% | +17.44% | FAIL |
| `xs_topk_ew_126_k3` | `kraken` | 2024-2026 | yes | 720 | -65.24% | -73.79% | -43.57% | -30.23% | -0.607 | +86.10% | 10.157 | +3.44% | +17.72% | FAIL |
| `xs_topk_ew_126_k5` | `kraken` | 2024-2026 | yes | 720 | -58.75% | -67.74% | -43.57% | -24.18% | -0.524 | +82.93% | 8.776 | +3.42% | +17.72% | FAIL |
| `xs_topk_iv_21_k3` | `kraken` | 2024-2026 | yes | 720 | -74.70% | -88.02% | -43.57% | -44.45% | -1.096 | +96.13% | 26.440 | +13.98% | +63.06% | FAIL |
| `xs_topk_iv_21_k5` | `kraken` | 2024-2026 | yes | 720 | -54.16% | -76.33% | -43.57% | -32.77% | -0.666 | +92.97% | 23.566 | +18.38% | +83.67% | FAIL |
| `xs_topk_iv_63_k3` | `kraken` | 2024-2026 | yes | 720 | -76.95% | -84.93% | -43.57% | -41.37% | -0.947 | +91.99% | 15.066 | +4.45% | +21.83% | FAIL |
| `xs_topk_iv_63_k5` | `kraken` | 2024-2026 | yes | 720 | -69.08% | -79.89% | -43.57% | -36.32% | -0.818 | +88.35% | 15.339 | +4.47% | +21.76% | FAIL |
| `xs_topk_iv_126_k3` | `kraken` | 2024-2026 | yes | 720 | -57.49% | -68.85% | -43.57% | -25.29% | -0.515 | +83.62% | 11.152 | +4.19% | +21.24% | FAIL |
| `xs_topk_iv_126_k5` | `kraken` | 2024-2026 | yes | 720 | -54.33% | -65.31% | -43.57% | -21.75% | -0.501 | +81.76% | 9.778 | +3.80% | +19.50% | FAIL |
| `ew_bh_universe` | `kraken` | 2024-2026 | yes | 720 | -40.21% | -43.57% | -43.57% | +0.00% | -0.039 | +81.52% | 2.094 | +1.27% | +7.05% | control |
| `xs_topk_ew_21_k3` | `coinbase` | 2024-2026 | yes | 724 | -71.58% | -85.59% | -35.70% | -49.89% | -0.849 | +96.32% | 24.100 | +17.22% | +79.60% | FAIL |
| `xs_topk_ew_21_k5` | `coinbase` | 2024-2026 | yes | 724 | -63.76% | -80.24% | -35.70% | -44.54% | -0.730 | +94.51% | 21.460 | +15.06% | +70.52% | FAIL |
| `xs_topk_ew_63_k3` | `coinbase` | 2024-2026 | yes | 724 | -77.59% | -84.47% | -35.70% | -48.77% | -0.892 | +92.43% | 12.947 | +4.09% | +20.55% | FAIL |
| `xs_topk_ew_63_k5` | `coinbase` | 2024-2026 | yes | 724 | -72.61% | -80.69% | -35.70% | -44.99% | -0.793 | +89.63% | 12.412 | +3.56% | +17.89% | FAIL |
| `xs_topk_ew_126_k3` | `coinbase` | 2024-2026 | yes | 724 | -73.15% | -80.69% | -35.70% | -44.99% | -0.959 | +89.29% | 11.574 | +3.71% | +18.87% | FAIL |
| `xs_topk_ew_126_k5` | `coinbase` | 2024-2026 | yes | 724 | -68.50% | -75.70% | -35.70% | -40.00% | -0.760 | +86.20% | 9.221 | +3.18% | +16.47% | FAIL |
| `xs_topk_iv_21_k3` | `coinbase` | 2024-2026 | yes | 724 | -73.11% | -87.21% | -35.70% | -51.51% | -1.008 | +96.29% | 26.277 | +17.36% | +78.51% | FAIL |
| `xs_topk_iv_21_k5` | `coinbase` | 2024-2026 | yes | 724 | -60.13% | -79.57% | -35.70% | -43.88% | -0.777 | +93.88% | 23.652 | +16.89% | +77.09% | FAIL |
| `xs_topk_iv_63_k3` | `coinbase` | 2024-2026 | yes | 724 | -73.29% | -82.54% | -35.70% | -46.84% | -0.855 | +91.62% | 15.008 | +5.13% | +25.14% | FAIL |
| `xs_topk_iv_63_k5` | `coinbase` | 2024-2026 | yes | 724 | -64.31% | -76.20% | -35.70% | -40.50% | -0.689 | +86.96% | 14.371 | +4.54% | +22.26% | FAIL |
| `xs_topk_iv_126_k3` | `coinbase` | 2024-2026 | yes | 724 | -65.61% | -75.74% | -35.70% | -40.04% | -0.811 | +86.77% | 12.251 | +4.34% | +21.79% | FAIL |
| `xs_topk_iv_126_k5` | `coinbase` | 2024-2026 | yes | 724 | -63.84% | -72.80% | -35.70% | -37.10% | -0.719 | +84.46% | 10.138 | +3.60% | +18.41% | FAIL |
| `ew_bh_universe` | `coinbase` | 2024-2026 | yes | 724 | -32.62% | -35.70% | -35.70% | +0.00% | 0.057 | +79.66% | 1.723 | +1.16% | +6.47% | control |

## Full catalog (informational)

| id | N | k | w | prints | covered | passed | failed | holdout fails | mean era excess (pilot) | dual-print | rank | selected | can promote |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | :---: | ---: | :---: | :---: |
| `xs_topk_ew_126_k3` | 126 | 3 | ew | kraken, coinbase | 2 | 0 | 2 | 2 | -37.61% | no | — | no | no |
| `xs_topk_ew_126_k5` | 126 | 5 | ew | kraken, coinbase | 2 | 0 | 2 | 0 | -32.09% | no | — | no | no |
| `xs_topk_ew_21_k3` | 21 | 3 | ew | kraken, coinbase | 2 | 0 | 2 | 2 | -47.53% | no | — | no | no |
| `xs_topk_ew_21_k5` | 21 | 5 | ew | kraken, coinbase | 2 | 0 | 2 | 2 | -40.01% | no | — | no | no |
| `xs_topk_ew_63_k3` | 63 | 3 | ew | kraken, coinbase | 2 | 0 | 2 | 2 | -45.95% | no | — | no | no |
| `xs_topk_ew_63_k5` | 63 | 5 | ew | kraken, coinbase | 2 | 0 | 2 | 2 | -42.64% | no | — | no | no |
| `xs_topk_iv_126_k3` | 126 | 3 | iv | kraken, coinbase | 2 | 0 | 2 | 2 | -32.66% | no | — | no | no |
| `xs_topk_iv_126_k5` | 126 | 5 | iv | kraken, coinbase | 2 | 0 | 2 | 1 | -29.42% | no | — | no | no |
| `xs_topk_iv_21_k3` | 21 | 3 | iv | kraken, coinbase | 2 | 0 | 2 | 2 | -47.98% | no | — | no | no |
| `xs_topk_iv_21_k5` | 21 | 5 | iv | kraken, coinbase | 2 | 0 | 2 | 2 | -38.32% | no | — | no | no |
| `xs_topk_iv_63_k3` | 63 | 3 | iv | kraken, coinbase | 2 | 0 | 2 | 2 | -44.11% | no | — | no | no |
| `xs_topk_iv_63_k5` | 63 | 5 | iv | kraken, coinbase | 2 | 0 | 2 | 2 | -38.41% | no | — | no | no |
| `ew_bh_universe` | — | — | — | kraken, coinbase | 2 | 0 | 2 | 2 | +0.00% | no | — | no | no |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Single-print bar passers (informational; cannot promote): 0.
- Print `kraken` (candles_dir:var/research/candles/kraken): **ok**; names loaded 43, skipped 0; eras covered ['2024-2026'].
- Print `coinbase` (candles_dir:var/research/candles/coinbase): **ok**; names loaded 45, skipped 0; eras covered ['2024-2026'].
- DSR / PBO: `not_computed_pending_135`.
- Paper path: candle-only long/flat on Kraken spot (PAPER_PATH_READY=true); runtime allowlist unchanged.
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not widen MAX_OPEN_POSITIONS, MVP_ASSETS or PAPER_PROMOTE_UNIVERSE for this family. Do not re-run the #117 top-1 catalog on the same window.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average venues. Do not widen MAX_OPEN_POSITIONS or the runtime allowlist for this family. Do not re-run the #117 top-1 catalog on the same window.
