# Long-only top-k cross-sectional momentum (wide Kraken USD universe)

Generated: 2026-09-15T11:35:21.616350+00:00

## Pre-registered header (frozen before any result below)

- Universe listing: `kraken_asset_pairs` fetched 2026-09-15T11:29:37.971104+00:00; 581 candidate pairs after exclusions.
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
| `kraken` | kraken_public_ohlc_1d | **ok** | 568 | 13 | 2024-09-24T00:00:00+00:00 → 2026-09-14T00:00:00+00:00 | 720 | 23 | 2024-2026 | — |

## Honesty / pre-registered rules

Pre-registered long-only top-k cross-sectional momentum bar on the point-in-time Kraken USD spot universe (frozen before any score). Universe: `trailing_30d_median_dollar_volume_top_20_pit` on a frozen dated AssetPairs listing (status=online; quote in {ZUSD, USD}; wsname present; no `.d` dark-pool pairs; XBT->BTC and XDG->DOGE aliases; drop any base that starts or ends with `USD`; drop the frozen EXCLUDED_BASES list (stablecoins, fiat, tokenised commodities, wrapped / liquid-staked duplicates).). Score on each Monday UTC close t: close[t-7] / close[t-7-N] - 1 for N in [21, 63, 126] (one-week skip). A name missing either close or with fewer than N+8 bars through t is skipped for that rebalance, never zero-filled. Fewer than MIN_CROSS_SECTION=10 rankable names -> flat week (counted). Long the top k in [3, 5]; weights `ew` (1/k) or `iv` (inverse trailing 30-day sample vol, normalised to 1); long-only, no leverage, no shorts. Rebalance rule `monday_utc_close_fill_next_open`: decide on close t, fill at the next bar open, drift between rebalances. Turnover and fee drag are reported at research 10+5 bps and at the frozen pilot-tier cost (Kraken Pro spot tier 1 ($0+ 30d volume) taker 0.80% per side; 80 bps + 5 bps slippage). Control `ew_bh_universe` = equal weight of the same monthly snapshot names, refreshed at each snapshot, otherwise buy-and-hold; it cannot promote. Portfolio bar `pilot_cost_net_return_pos_and_net_sharpe_pos_and_excess_vs_ew_bh_pos_in_every_covered_era_and_print_holdout_excess_pos` at the pilot cost: every covered era needs net return > 0, net Sharpe > 0 and net excess over the control > 0, plus the print's last-20% holdout net excess > 0; a family that only works in one era fails. A cell (venue x era) is covered with >= 365 daily bars inside the era; eras ['2016-2019', '2020-2022', '2022-2024', '2024-2026'] are a local constant pending the #135 shared era policy. Dual print `two_independent_covered_cells_pass_and_no_covered_cell_or_holdout_fails`: two independent covered cells (distinct venues or non-overlapping eras) must pass and none may fail; one venue over one era cannot promote. Ranking key: mean_era_excess_vs_ew_bh_among_dual_print_passers (tie-break: candidate_id); CAN_AVERAGE_VENUES=false; MULTI_VENUE_BAR_PREREGISTERED=true. DSR / PBO: not_computed_pending_135 (Deflated Sharpe and PBO land with #135). Paper-executable on Kraken spot as candle-only long/flat signals (PAPER_PATH_READY=true); the runtime allowlist and RiskEngine limits are documented, not widened. PAPER_PROMOTE_* stays default false. No live. An empty dual-print set is success. Not a #117 top-1 reprint. Frozen catalog (K=13): `xs_topk_{ew|iv}_{N}_k{3|5}` for N in [21, 63, 126] (12 baskets) plus the informational control `ew_bh_universe` (cannot promote). Do not grow this list after seeing PnL. PAPER_PROMOTE_* stays false unless a committed dual-print report names a paper-only pin and an operator flips it (default false if ever added). This run scored K=13 (core ids frozen at 13) on 1 print(s). Single-print bar passers (ex-control): 0. Dual-print passers: 0. No dual-print passer. Leave every PAPER_PROMOTE_* false. Do not add a new promote flag.

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

- kraken_asset_pairs: ok; 581 online USD pairs after exclusions
- kraken_public_ohlc_1d: 568 names loaded, 13 skipped; 247 pairs fetched now (sleep 1s between pairs; 720-bar public cap), 332 pairs reused from --cache-dir /tmp/claude-0/-home-user-DeFi-TraderStack-Agent/5fb3a889-cb36-501f-9295-6c06b0cc41b3/scratchpad/kraken_1d

## Skipped on `kraken` (not invented)

- ALIGN/USD: 25 daily bars < 29 (short history)
- AVL/USD: 18 daily bars < 29 (short history)
- CORN/USD: fetch skipped (4 validation errors for Candle
open
  Input should be greater than 0 [type=greater_than, input_value=0.0, input_type=float]
    For further information visit https://errors.pydantic.dev/2.13/v/greater_than
high
  Input should be greater than 0 [type=greater_than, input_value=0.0, input_type=float]
    For further information visit https://errors.pydantic.dev/2.13/v/greater_than
low
  Input should be greater than 0 [type=greater_than, input_value=0.0, input_type=float]
    For further information visit https://errors.pydantic.dev/2.13/v/greater_than
close
  Input should be greater than 0 [type=greater_than, input_value=0.0, input_type=float]
    For further information visit https://errors.pydantic.dev/2.13/v/greater_than)
- DGAI/USD: 21 daily bars < 29 (short history)
- FOLD/USD: 20 daily bars < 29 (short history)
- LAPTOP/USD: 5 daily bars < 29 (short history)
- LIGHTER/USD: 28 daily bars < 29 (short history)
- ONE/USD: 6 daily bars < 29 (short history)
- PIPE/USD: fetch skipped (4 validation errors for Candle
open
  Input should be greater than 0 [type=greater_than, input_value=0.0, input_type=float]
    For further information visit https://errors.pydantic.dev/2.13/v/greater_than
high
  Input should be greater than 0 [type=greater_than, input_value=0.0, input_type=float]
    For further information visit https://errors.pydantic.dev/2.13/v/greater_than
low
  Input should be greater than 0 [type=greater_than, input_value=0.0, input_type=float]
    For further information visit https://errors.pydantic.dev/2.13/v/greater_than
close
  Input should be greater than 0 [type=greater_than, input_value=0.0, input_type=float]
    For further information visit https://errors.pydantic.dev/2.13/v/greater_than)
- PWT/USD: 22 daily bars < 29 (short history)
- SOFID/USD: 11 daily bars < 29 (short history)
- TCS/USD: 6 daily bars < 29 (short history)
- TMX/USD: 21 daily bars < 29 (short history)

## Dual-print passers (promotion ranking)

Frozen ranking key: `mean_era_excess_vs_ew_bh_among_dual_print_passers`. Only baskets that pass the portfolio bar on at least two independent covered cells with no failing cell appear here. `ew_bh_universe` is excluded. Empty table = no promotee (success). A new Settings pin is added only if this table is non-empty, and then default **false**.

| dual rank | id | mean era excess vs ew_bh (pilot) | cells passed | selected | can flip flag |
| ---: | --- | ---: | ---: | :---: | :---: |
| — | — | n/a | 0 | no | no |

## Era table (every covered venue x era cell; turnover and fee drag at both costs)

Net returns are basket total returns over the era. Fee drag is total fees / starting equity over the era at each cost print. One-way turnover per year is half the traded fraction of equity, annualised. Weekly rebalancing of a five-name basket is where this family usually dies; the pilot column makes that visible.

| id | print | era | covered | bars | net ret (10+5) | net ret (pilot) | control (pilot) | excess vs ew_bh (pilot) | Sharpe (pilot) | maxDD (pilot) | one-way turnover/yr | fee drag (10+5) | fee drag (pilot) | bar |
| --- | --- | --- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| `xs_topk_ew_21_k3` | `kraken` | 2024-2026 | yes | 721 | -68.26% | -84.95% | -53.04% | -31.92% | -0.625 | +94.14% | 26.435 | +14.72% | +64.85% | FAIL |
| `xs_topk_ew_21_k5` | `kraken` | 2024-2026 | yes | 721 | -46.51% | -71.94% | -53.04% | -18.91% | -0.414 | +89.48% | 23.052 | +15.51% | +69.90% | FAIL |
| `xs_topk_ew_63_k3` | `kraken` | 2024-2026 | yes | 721 | -70.76% | -80.77% | -53.04% | -27.73% | -0.493 | +88.13% | 14.917 | +4.78% | +23.19% | FAIL |
| `xs_topk_ew_63_k5` | `kraken` | 2024-2026 | yes | 721 | -79.66% | -86.32% | -53.04% | -33.28% | -0.843 | +90.54% | 14.119 | +3.57% | +17.73% | FAIL |
| `xs_topk_ew_126_k3` | `kraken` | 2024-2026 | yes | 721 | -80.48% | -85.54% | -53.04% | -32.50% | -0.687 | +93.01% | 10.644 | +3.61% | +18.60% | FAIL |
| `xs_topk_ew_126_k5` | `kraken` | 2024-2026 | yes | 721 | -79.61% | -84.72% | -53.04% | -31.69% | -0.876 | +90.32% | 10.240 | +3.02% | +15.61% | FAIL |
| `xs_topk_iv_21_k3` | `kraken` | 2024-2026 | yes | 721 | -57.23% | -81.37% | -53.04% | -28.33% | -0.586 | +93.57% | 29.526 | +17.74% | +75.94% | FAIL |
| `xs_topk_iv_21_k5` | `kraken` | 2024-2026 | yes | 721 | -43.86% | -72.38% | -53.04% | -19.34% | -0.548 | +89.95% | 25.345 | +16.01% | +70.88% | FAIL |
| `xs_topk_iv_63_k3` | `kraken` | 2024-2026 | yes | 721 | -65.88% | -79.30% | -53.04% | -26.27% | -0.535 | +88.12% | 17.720 | +5.92% | +27.68% | FAIL |
| `xs_topk_iv_63_k5` | `kraken` | 2024-2026 | yes | 721 | -73.48% | -83.36% | -53.04% | -30.33% | -0.830 | +89.16% | 16.586 | +4.57% | +21.98% | FAIL |
| `xs_topk_iv_126_k3` | `kraken` | 2024-2026 | yes | 721 | -61.02% | -71.95% | -53.04% | -18.91% | -0.368 | +87.74% | 11.747 | +4.60% | +23.16% | FAIL |
| `xs_topk_iv_126_k5` | `kraken` | 2024-2026 | yes | 721 | -71.82% | -79.49% | -53.04% | -26.45% | -0.785 | +87.81% | 11.229 | +3.35% | +17.08% | FAIL |
| `ew_bh_universe` | `kraken` | 2024-2026 | yes | 721 | -48.97% | -53.04% | -53.04% | +0.00% | -0.118 | +80.70% | 2.878 | +1.49% | +8.22% | control |

## Full catalog (informational)

| id | N | k | w | prints | covered | passed | failed | holdout fails | mean era excess (pilot) | dual-print | rank | selected | can promote |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | :---: | ---: | :---: | :---: |
| `xs_topk_ew_126_k3` | 126 | 3 | ew | kraken | 1 | 0 | 1 | 1 | -32.50% | no | — | no | no |
| `xs_topk_ew_126_k5` | 126 | 5 | ew | kraken | 1 | 0 | 1 | 1 | -31.69% | no | — | no | no |
| `xs_topk_ew_21_k3` | 21 | 3 | ew | kraken | 1 | 0 | 1 | 1 | -31.92% | no | — | no | no |
| `xs_topk_ew_21_k5` | 21 | 5 | ew | kraken | 1 | 0 | 1 | 1 | -18.91% | no | — | no | no |
| `xs_topk_ew_63_k3` | 63 | 3 | ew | kraken | 1 | 0 | 1 | 1 | -27.73% | no | — | no | no |
| `xs_topk_ew_63_k5` | 63 | 5 | ew | kraken | 1 | 0 | 1 | 1 | -33.28% | no | — | no | no |
| `xs_topk_iv_126_k3` | 126 | 3 | iv | kraken | 1 | 0 | 1 | 1 | -18.91% | no | — | no | no |
| `xs_topk_iv_126_k5` | 126 | 5 | iv | kraken | 1 | 0 | 1 | 1 | -26.45% | no | — | no | no |
| `xs_topk_iv_21_k3` | 21 | 3 | iv | kraken | 1 | 0 | 1 | 1 | -28.33% | no | — | no | no |
| `xs_topk_iv_21_k5` | 21 | 5 | iv | kraken | 1 | 0 | 1 | 1 | -19.34% | no | — | no | no |
| `xs_topk_iv_63_k3` | 63 | 3 | iv | kraken | 1 | 0 | 1 | 1 | -26.27% | no | — | no | no |
| `xs_topk_iv_63_k5` | 63 | 5 | iv | kraken | 1 | 0 | 1 | 1 | -30.33% | no | — | no | no |
| `ew_bh_universe` | — | — | — | kraken | 1 | 0 | 1 | 1 | +0.00% | no | — | no | no |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This search does not flip a pin and does not enable live. An empty dual-print set is the successful outcome.

- Dual-print passers: 0 (none).
- Single-print bar passers (informational; cannot promote): 0.
- Print `kraken` (kraken_public_ohlc_1d): **ok**; names loaded 568, skipped 13; eras covered ['2024-2026'].
- Independent prints available: 1 venue(s) x 1 covered era(s) — fewer than two independent cells, so **no name can dual-print on this data** (empty is success; a second venue or an older era from #133 is required).
- DSR / PBO: `not_computed_pending_135`.
- Paper path: candle-only long/flat on Kraken spot (PAPER_PATH_READY=true); runtime allowlist unchanged.
- Dual-print top-1: **none**. Do not add a new promote flag. Leave every existing `PAPER_PROMOTE_*` false.
- Do not enable live. Do not fabricate PnL. Do not widen MAX_OPEN_POSITIONS, MVP_ASSETS or PAPER_PROMOTE_UNIVERSE for this family. Do not re-run the #117 top-1 catalog on the same window.

`keep_flag_false=true`. Do not fabricate PnL. Do not enable live. Do not average venues. Do not widen MAX_OPEN_POSITIONS or the runtime allowlist for this family. Do not re-run the #117 top-1 catalog on the same window.
