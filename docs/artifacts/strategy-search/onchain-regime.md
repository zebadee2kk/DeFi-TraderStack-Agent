# On-chain regime overlay (MVRV-Z / NUPL) on the frozen TSMOM catalog

Generated: 2026-09-14T09:38:20.590996+00:00
Base catalog K=8 (+ control `ma_cross_10_30`, informational); overlays=3; ranking_key=`mean_holdout_excess_among_dual_print_passers`.
Costs: fee=10 bps + slippage=5 bps (gate C 2× fees). Walk-forward: train=180 test=60 step=60; holdout_fraction=20%. Print kind: daily bars, fill at next-bar open.
`can_promote=false`; `keep_flag_false=true`; `multi_venue_bar_preregistered=true`; `can_average_venues=false`.

## Data sources reached (status per series)

| series | status |
| --- | --- |
| Kraken public Spot daily (primary 720) | ok — first 2024-09-24T00:00:00+00:00 (`this_run_kraken_btc_first_bar`), last 2026-09-13T00:00:00+00:00, bars BTC=720 / ETH=720 / SOL=720 |
| Binance.US older-720 (`older_720_ending_before_primary_first_bar`) | ok — binance_us_spot; BTC 720 / ETH 720; 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00 |
| Coin Metrics community `coinmetrics:community:v4:CapMVRVCur+CapMrktCurUSD` (btc; onchain-regime-v1; window 1460 d; min points 730; stale limit 3 d) | ok — 5902 committed daily points 2010-07-18 → 2026-09-13 |
| Coin Metrics `CapRealUSD`, `SplyAct1d` | skipped — HTTP 403 on the community plan |

## Honesty / pre-registered rules

Pre-registered on-chain regime overlay (frozen before any Coin Metrics, Kraken or Binance.US score). Base catalog: the frozen TSMOM names (tsmom_lo_21, tsmom_lo_63, tsmom_lo_126, tsmom_lo_252, tsmom_ls_21, tsmom_ls_63, tsmom_ls_126, tsmom_ls_252); control ma_cross_10_30 is scored ungated, informational, and cannot pass. Treatment: each base name is scored ungated and gated; a gated name withholds a BUY (flat) when the newest Coin Metrics community regime row with time strictly before the decision bar (`newest_regime_row_strictly_before_decision_bar`) breaches the overlay rule; SELL and flat pass through untouched; a missing or stale row (`no_forward_fill_beyond_3_days`) also withholds the BUY (fail closed, never forward-filled, never zero-filled). Regime features are onchain-regime-v1: MVRV-Z = (mcap − realised cap) / pstdev(mcap over the trailing 1460 rows), percentile = rank of MVRV-Z inside that trailing window, NUPL = 1 − 1/MVRV; None until 730 points. Overlays (frozen): mvrvz_p90 (percentile > 0.90), mvrvz_p80 (> 0.80), nupl_075 (NUPL > 0.75). The BTC series gates every scored name (frozen market-regime assumption; SOL has no community MVRV; ETH's own series is a follow-up). Prints: Kraken public Spot daily 720 AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed BTC+ETH bars ending strictly before the primary Kraken first bar), each scored with the #96+A+B+C combined gates on BTC+ETH (SOL reported, not a gate; `btc_eth_signs_as_96_abc_sol_reported_not_required`). An overlay whose series does not cover a print is skipped on that print (a skip, never a zero). Deltas are gated − ungated mean holdout excess AND walk-forward total on every scored print. Verdict rule: `over_mean_ho_and_wf_total_deltas_on_every_scored_print:helps_if_some_gt_0_and_none_lt_0;hurts_if_some_lt_0_and_none_gt_0;mixed_fail_if_both_signs;neutral_if_all_zero`. Passer rule: `gated_name_dual_print_passer_and_mean_ho_and_wf_total_deltas_ge_0_on_both_prints`. Ranking key among overlay passers: mean_holdout_excess_among_dual_print_passers (Kraken mean holdout excess; tie-break gated id). CAN_AVERAGE_VENUES=false; MULTI_VENUE_BAR_PREREGISTERED=true; CAN_PROMOTE=false. Fees are paper-research 10+5 (gate C 20+10). PAPER_PROMOTE_* stays default false. No live. An empty overlay-passer set is success. Era prints, Deflated Sharpe and PBO (#135/#136) are a follow-up, not claimed here. Frozen overlay catalog (3): mvrvz_p90, mvrvz_p80 (MVRV-Z trailing-window percentile) and nupl_075 (NUPL). Applied to the 8 frozen TSMOM names → 24 gated ids. Do not grow this list, move a threshold, or change the window after seeing PnL. The runtime gate (ONCHAIN_REGIME_GATE_ENABLED) uses the MVRV-Z percentile only; NUPL is published as a feature and scored here. This run: regime series ok; base names scored 8; gated names scored on Kraken 24 / on Binance.US 24. Base dual-print passers: 0. Overlay passers: 0. mixed_fail: 10. No overlay passer. Leave every PAPER_PROMOTE_* false. The runtime gate stays off by default.

## Overlay bar (frozen before scoring)

Pre-registered on-chain regime overlay (frozen before any Coin Metrics, Kraken or Binance.US score). Base catalog: the frozen TSMOM names (tsmom_lo_21, tsmom_lo_63, tsmom_lo_126, tsmom_lo_252, tsmom_ls_21, tsmom_ls_63, tsmom_ls_126, tsmom_ls_252); control ma_cross_10_30 is scored ungated, informational, and cannot pass. Treatment: each base name is scored ungated and gated; a gated name withholds a BUY (flat) when the newest Coin Metrics community regime row with time strictly before the decision bar (`newest_regime_row_strictly_before_decision_bar`) breaches the overlay rule; SELL and flat pass through untouched; a missing or stale row (`no_forward_fill_beyond_3_days`) also withholds the BUY (fail closed, never forward-filled, never zero-filled). Regime features are onchain-regime-v1: MVRV-Z = (mcap − realised cap) / pstdev(mcap over the trailing 1460 rows), percentile = rank of MVRV-Z inside that trailing window, NUPL = 1 − 1/MVRV; None until 730 points. Overlays (frozen): mvrvz_p90 (percentile > 0.90), mvrvz_p80 (> 0.80), nupl_075 (NUPL > 0.75). The BTC series gates every scored name (frozen market-regime assumption; SOL has no community MVRV; ETH's own series is a follow-up). Prints: Kraken public Spot daily 720 AND the #102 Binance.US older-720 (`older_720_ending_before_primary_first_bar`: 720 committed BTC+ETH bars ending strictly before the primary Kraken first bar), each scored with the #96+A+B+C combined gates on BTC+ETH (SOL reported, not a gate; `btc_eth_signs_as_96_abc_sol_reported_not_required`). An overlay whose series does not cover a print is skipped on that print (a skip, never a zero). Deltas are gated − ungated mean holdout excess AND walk-forward total on every scored print. Verdict rule: `over_mean_ho_and_wf_total_deltas_on_every_scored_print:helps_if_some_gt_0_and_none_lt_0;hurts_if_some_lt_0_and_none_gt_0;mixed_fail_if_both_signs;neutral_if_all_zero`. Passer rule: `gated_name_dual_print_passer_and_mean_ho_and_wf_total_deltas_ge_0_on_both_prints`. Ranking key among overlay passers: mean_holdout_excess_among_dual_print_passers (Kraken mean holdout excess; tie-break gated id). CAN_AVERAGE_VENUES=false; MULTI_VENUE_BAR_PREREGISTERED=true; CAN_PROMOTE=false. Fees are paper-research 10+5 (gate C 20+10). PAPER_PROMOTE_* stays default false. No live. An empty overlay-passer set is success. Era prints, Deflated Sharpe and PBO (#135/#136) are a follow-up, not claimed here.

## Overlay catalog (frozen)

Frozen overlay catalog (3): mvrvz_p90, mvrvz_p80 (MVRV-Z trailing-window percentile) and nupl_075 (NUPL). Applied to the 8 frozen TSMOM names → 24 gated ids. Do not grow this list, move a threshold, or change the window after seeing PnL. The runtime gate (ONCHAIN_REGIME_GATE_ENABLED) uses the MVRV-Z percentile only; NUPL is published as a feature and scored here.

| overlay | field | rule |
| --- | --- | --- |
| `mvrvz_p90` | `mvrv_z_percentile` | BUY withheld when mvrv_z_percentile > 0.9 |
| `mvrvz_p80` | `mvrv_z_percentile` | BUY withheld when mvrv_z_percentile > 0.8 |
| `nupl_075` | `nupl` | BUY withheld when nupl > 0.75 |

## Regime coverage per print (skip-not-invent)

| print | overlay | usable | bars | bars the overlay would block | reason |
| --- | --- | :---: | ---: | ---: | --- |
| kraken | `mvrvz_p90` | yes | 720 | 53 | — |
| kraken | `mvrvz_p80` | yes | 720 | 201 | — |
| kraken | `nupl_075` | yes | 720 | 0 | — |
| binance | `mvrvz_p90` | yes | 720 | 3 | — |
| binance | `mvrvz_p80` | yes | 720 | 110 | — |
| binance | `nupl_075` | yes | 720 | 0 | — |

## Data

- Kraken public Spot OHLC (`GET /0/public/OHLC`) returns at most 720 of the most recent committed bars per pair/interval — about two calendar years of daily. `since` pages forward only; older history cannot be retrieved from this endpoint. Charts-spot PI_* is a different print (research-only, often zero volume) and is not used here. Yahoo Finance daily is an optional longer A/B and is labeled non-Kraken; it is not the paper path.
- BTC/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- ETH/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- SOL/USD@1d: 720 committed Kraken bars 2024-09-24T00:00:00+00:00 → 2026-09-13T00:00:00+00:00 (public OHLC cap; requested 720, received 720 committed)
- primary first bar 2024-09-24T00:00:00+00:00 (source=this_run_kraken_btc_first_bar)
- universe=BTC/USD,ETH/USD,SOL/USD (SOL optional report-only; skip-not-invent)
- BTCUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- BTCUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- BTCUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00 (non-Kraken; report-only)
- ETHUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- ETHUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- ETHUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00 (non-Kraken; report-only)
- SOLUSDT: https://api.binance.com HTTP 451
- https://api.binance.com is geo-restricted (HTTP 451); not treated as confirmation.
- SOLUSDT: https://api.binance.com unavailable or restricted; using https://api.binance.us (labeled Binance.US, not Binance.com).
- SOLUSDT@1d: 720 committed binance_us_spot 1d bars 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00 (non-Kraken; report-only)
- Coin Metrics community GET https://community-api.coinmetrics.io/v4/timeseries/asset-metrics assets=btc metrics=CapMVRVCur,CapMrktCurUSD frequency=1d: 5902 rows
- Coin Metrics community (btc) regime series: ok — 5902 committed daily points 2010-07-18 → 2026-09-13 (onchain-regime-v1).
- CapRealUSD and SplyAct1d return HTTP 403 ('not available with supplied credentials') on the Coin Metrics community plan and are skipped, not invented; realised cap is CapMrktCurUSD / CapMVRVCur and NUPL is 1 - 1/MVRV (exact identities).
- SOL/USD present (720 bars); reported, not a gate.

## Binance.US second print (required gate)

Binance.US Spot published taker is typically 10 bps at the lowest listed tier. This print uses the paper-research defaults `max(PRETRADE_FEE_BPS, PAPER_FEE_BPS)` + `PRETRADE_SLIPPAGE_BPS` (10+5; gate C at 20+10) so costs stay comparable to the Kraken print. Not a maker-rebate or VIP study. Quote is USDT, not USD.

- Rule: `older_720_ending_before_primary_first_bar`
- Venue label: `binance_us_spot`
- Status: **available**
- Bars: BTC 720 / ETH 720 / SOL 720
- Span: 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00
- Overlaps primary window: no
- Fail-closed reason: —

## Overlay effect — Kraken primary 720

Ungated vs gated on the same print, same bars, same costs. Δ is gated − ungated. `blocked bars` counts bars on which the overlay rule was breached strictly before the bar (whether or not the base voter was long).

| overlay | base | ungated mean HO | gated mean HO | Δ mean HO | ungated WF | gated WF | Δ WF | blocked bars | gated dual-print | verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | --- |
| `mvrvz_p90` | `tsmom_lo_21` | +8.48% | +8.48% | +0.00% | +5.46% | +4.15% | -1.31% | 53 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_lo_63` | +4.16% | +4.16% | +0.00% | +3.22% | +1.98% | -1.24% | 53 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_lo_126` | -2.70% | -2.70% | +0.00% | +2.87% | +1.56% | -1.31% | 53 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_lo_252` | -1.23% | -1.23% | +0.00% | -3.99% | -5.35% | -1.35% | 53 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_ls_21` | +7.54% | +7.54% | +0.00% | +7.66% | +6.29% | -1.37% | 53 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_ls_63` | +7.81% | +7.81% | +0.00% | +3.67% | +2.43% | -1.24% | 53 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_ls_126` | -10.88% | -10.88% | +0.00% | +3.50% | +2.16% | -1.33% | 53 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_ls_252` | -3.69% | -3.69% | +0.00% | -5.68% | -6.72% | -1.04% | 53 | no | mixed_fail |
| `mvrvz_p80` | `tsmom_lo_21` | +8.48% | +8.48% | +0.00% | +5.46% | -1.34% | -6.80% | 201 | no | hurts |
| `mvrvz_p80` | `tsmom_lo_63` | +4.16% | +4.16% | +0.00% | +3.22% | -1.93% | -5.15% | 201 | no | mixed_fail |
| `mvrvz_p80` | `tsmom_lo_126` | -2.70% | -2.70% | +0.00% | +2.87% | -0.58% | -3.45% | 201 | no | hurts |
| `mvrvz_p80` | `tsmom_lo_252` | -1.23% | -1.23% | +0.00% | -3.99% | -5.59% | -1.60% | 201 | no | hurts |
| `mvrvz_p80` | `tsmom_ls_21` | +7.54% | +7.54% | +0.00% | +7.66% | +0.53% | -7.13% | 201 | no | hurts |
| `mvrvz_p80` | `tsmom_ls_63` | +7.81% | +7.81% | +0.00% | +3.67% | -1.25% | -4.92% | 201 | no | mixed_fail |
| `mvrvz_p80` | `tsmom_ls_126` | -10.88% | -10.88% | +0.00% | +3.50% | +0.13% | -3.36% | 201 | no | hurts |
| `mvrvz_p80` | `tsmom_ls_252` | -3.69% | -3.69% | +0.00% | -5.68% | -6.97% | -1.29% | 201 | no | hurts |
| `nupl_075` | `tsmom_lo_21` | +8.48% | +8.48% | +0.00% | +5.46% | +5.46% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_lo_63` | +4.16% | +4.16% | +0.00% | +3.22% | +3.22% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_lo_126` | -2.70% | -2.70% | +0.00% | +2.87% | +2.87% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_lo_252` | -1.23% | -1.23% | +0.00% | -3.99% | -3.99% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_ls_21` | +7.54% | +7.54% | +0.00% | +7.66% | +7.66% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_ls_63` | +7.81% | +7.81% | +0.00% | +3.67% | +3.67% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_ls_126` | -10.88% | -10.88% | +0.00% | +3.50% | +3.50% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_ls_252` | -3.69% | -3.69% | +0.00% | -5.68% | -5.68% | +0.00% | 0 | no | neutral |

## Overlay effect — Binance.US older-720

| overlay | base | ungated mean HO | gated mean HO | Δ mean HO | ungated WF | gated WF | Δ WF | blocked bars | gated dual-print | verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | --- |
| `mvrvz_p90` | `tsmom_lo_21` | -16.56% | -16.56% | +0.00% | +7.79% | +8.71% | +0.92% | 3 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_lo_63` | -12.28% | -12.28% | +0.00% | +11.22% | +12.33% | +1.11% | 3 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_lo_126` | -0.25% | -0.25% | +0.00% | +14.80% | +15.92% | +1.12% | 3 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_lo_252` | -11.02% | -11.02% | +0.00% | +17.93% | +19.04% | +1.12% | 3 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_ls_21` | -28.52% | -28.52% | +0.00% | +0.77% | +1.53% | +0.75% | 3 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_ls_63` | -22.53% | -22.53% | +0.00% | +6.87% | +7.97% | +1.10% | 3 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_ls_126` | +2.66% | +2.66% | +0.00% | +14.39% | +15.51% | +1.12% | 3 | no | mixed_fail |
| `mvrvz_p90` | `tsmom_ls_252` | -16.55% | -16.55% | +0.00% | +18.23% | +19.34% | +1.12% | 3 | no | mixed_fail |
| `mvrvz_p80` | `tsmom_lo_21` | -16.56% | -17.72% | -1.16% | +7.79% | +3.14% | -4.65% | 110 | no | hurts |
| `mvrvz_p80` | `tsmom_lo_63` | -12.28% | -9.43% | +2.85% | +11.22% | +4.25% | -6.97% | 110 | no | mixed_fail |
| `mvrvz_p80` | `tsmom_lo_126` | -0.25% | -7.50% | -7.25% | +14.80% | +7.72% | -7.09% | 110 | no | hurts |
| `mvrvz_p80` | `tsmom_lo_252` | -11.02% | -16.30% | -5.27% | +17.93% | +10.84% | -7.09% | 110 | no | hurts |
| `mvrvz_p80` | `tsmom_ls_21` | -28.52% | -29.67% | -1.15% | +0.77% | -3.41% | -4.19% | 110 | no | hurts |
| `mvrvz_p80` | `tsmom_ls_63` | -22.53% | -20.40% | +2.12% | +6.87% | +0.02% | -6.85% | 110 | no | mixed_fail |
| `mvrvz_p80` | `tsmom_ls_126` | +2.66% | -5.55% | -8.20% | +14.39% | +7.30% | -7.09% | 110 | no | hurts |
| `mvrvz_p80` | `tsmom_ls_252` | -16.55% | -21.03% | -4.49% | +18.23% | +11.14% | -7.09% | 110 | no | hurts |
| `nupl_075` | `tsmom_lo_21` | -16.56% | -16.56% | +0.00% | +7.79% | +7.79% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_lo_63` | -12.28% | -12.28% | +0.00% | +11.22% | +11.22% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_lo_126` | -0.25% | -0.25% | +0.00% | +14.80% | +14.80% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_lo_252` | -11.02% | -11.02% | +0.00% | +17.93% | +17.93% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_ls_21` | -28.52% | -28.52% | +0.00% | +0.77% | +0.77% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_ls_63` | -22.53% | -22.53% | +0.00% | +6.87% | +6.87% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_ls_126` | +2.66% | +2.66% | +0.00% | +14.39% | +14.39% | +0.00% | 0 | no | neutral |
| `nupl_075` | `tsmom_ls_252` | -16.55% | -16.55% | +0.00% | +18.23% | +18.23% | +0.00% | 0 | no | neutral |

## Verdict per overlay × base (frozen rule)

`over_mean_ho_and_wf_total_deltas_on_every_scored_print:helps_if_some_gt_0_and_none_lt_0;hurts_if_some_lt_0_and_none_gt_0;mixed_fail_if_both_signs;neutral_if_all_zero`. Deltas are mean holdout excess and walk-forward total on every scored print. An overlay that helps on one print or metric and hurts on the other is **mixed_fail** (FAIL), not an edge.

| gated id | Kraken Δ mean HO | Kraken Δ WF | Binance Δ mean HO | Binance Δ WF | verdict | overlay passer |
| --- | ---: | ---: | ---: | ---: | --- | :---: |
| `tsmom_lo_21__mvrvz_p90` | +0.00% | -1.31% | +0.00% | +0.92% | mixed_fail | no |
| `tsmom_lo_63__mvrvz_p90` | +0.00% | -1.24% | +0.00% | +1.11% | mixed_fail | no |
| `tsmom_lo_126__mvrvz_p90` | +0.00% | -1.31% | +0.00% | +1.12% | mixed_fail | no |
| `tsmom_lo_252__mvrvz_p90` | +0.00% | -1.35% | +0.00% | +1.12% | mixed_fail | no |
| `tsmom_ls_21__mvrvz_p90` | +0.00% | -1.37% | +0.00% | +0.75% | mixed_fail | no |
| `tsmom_ls_63__mvrvz_p90` | +0.00% | -1.24% | +0.00% | +1.10% | mixed_fail | no |
| `tsmom_ls_126__mvrvz_p90` | +0.00% | -1.33% | +0.00% | +1.12% | mixed_fail | no |
| `tsmom_ls_252__mvrvz_p90` | +0.00% | -1.04% | +0.00% | +1.12% | mixed_fail | no |
| `tsmom_lo_21__mvrvz_p80` | +0.00% | -6.80% | -1.16% | -4.65% | hurts | no |
| `tsmom_lo_63__mvrvz_p80` | +0.00% | -5.15% | +2.85% | -6.97% | mixed_fail | no |
| `tsmom_lo_126__mvrvz_p80` | +0.00% | -3.45% | -7.25% | -7.09% | hurts | no |
| `tsmom_lo_252__mvrvz_p80` | +0.00% | -1.60% | -5.27% | -7.09% | hurts | no |
| `tsmom_ls_21__mvrvz_p80` | +0.00% | -7.13% | -1.15% | -4.19% | hurts | no |
| `tsmom_ls_63__mvrvz_p80` | +0.00% | -4.92% | +2.12% | -6.85% | mixed_fail | no |
| `tsmom_ls_126__mvrvz_p80` | +0.00% | -3.36% | -8.20% | -7.09% | hurts | no |
| `tsmom_ls_252__mvrvz_p80` | +0.00% | -1.29% | -4.49% | -7.09% | hurts | no |
| `tsmom_lo_21__nupl_075` | +0.00% | +0.00% | +0.00% | +0.00% | neutral | no |
| `tsmom_lo_63__nupl_075` | +0.00% | +0.00% | +0.00% | +0.00% | neutral | no |
| `tsmom_lo_126__nupl_075` | +0.00% | +0.00% | +0.00% | +0.00% | neutral | no |
| `tsmom_lo_252__nupl_075` | +0.00% | +0.00% | +0.00% | +0.00% | neutral | no |
| `tsmom_ls_21__nupl_075` | +0.00% | +0.00% | +0.00% | +0.00% | neutral | no |
| `tsmom_ls_63__nupl_075` | +0.00% | +0.00% | +0.00% | +0.00% | neutral | no |
| `tsmom_ls_126__nupl_075` | +0.00% | +0.00% | +0.00% | +0.00% | neutral | no |
| `tsmom_ls_252__nupl_075` | +0.00% | +0.00% | +0.00% | +0.00% | neutral | no |

## Overlay passers (promotion ranking)

Frozen passer rule: `gated_name_dual_print_passer_and_mean_ho_and_wf_total_deltas_ge_0_on_both_prints`. Empty table = no overlay passer (success). This CLI cannot add or flip a `PAPER_PROMOTE_*` pin.

| rank | gated id | Kraken mean HO | Binance mean HO | can flip flag |
| ---: | --- | ---: | ---: | :---: |
| — | — | n/a | n/a | no |

## Full catalog (informational)

| id | family | Kraken combined | Binance combined | dual-print | Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO |
| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: | ---: |
| `tsmom_lo_21` | tsmom | FAIL | FAIL | no | +8.48% | -16.56% | +9.03% | +7.93% |
| `tsmom_lo_63` | tsmom | FAIL | FAIL | no | +4.16% | -12.28% | -6.37% | +14.68% |
| `tsmom_lo_126` | tsmom | FAIL | FAIL | no | -2.70% | -0.25% | +0.72% | -6.13% |
| `tsmom_lo_252` | tsmom | FAIL | FAIL | no | -1.23% | -11.02% | +1.80% | -4.25% |
| `tsmom_ls_21` | tsmom | FAIL | FAIL | no | +7.54% | -28.52% | +15.99% | -0.91% |
| `tsmom_ls_63` | tsmom | FAIL | FAIL | no | +7.81% | -22.53% | -12.79% | +28.41% |
| `tsmom_ls_126` | tsmom | FAIL | FAIL | no | -10.88% | +2.66% | -7.56% | -14.19% |
| `tsmom_ls_252` | tsmom | FAIL | FAIL | no | -3.69% | -16.55% | +3.39% | -10.76% |
| `ma_cross_10_30` | control | FAIL | FAIL | no | -0.52% | -35.00% | +3.21% | -4.25% |
| `tsmom_lo_126__mvrvz_p80` | tsmom_onchain_regime | FAIL | FAIL | no | -2.70% | -7.50% | +0.72% | -6.13% |
| `tsmom_lo_126__mvrvz_p90` | tsmom_onchain_regime | FAIL | FAIL | no | -2.70% | -0.25% | +0.72% | -6.13% |
| `tsmom_lo_126__nupl_075` | tsmom_onchain_regime | FAIL | FAIL | no | -2.70% | -0.25% | +0.72% | -6.13% |
| `tsmom_lo_21__mvrvz_p80` | tsmom_onchain_regime | FAIL | FAIL | no | +8.48% | -17.72% | +9.03% | +7.93% |
| `tsmom_lo_21__mvrvz_p90` | tsmom_onchain_regime | FAIL | FAIL | no | +8.48% | -16.56% | +9.03% | +7.93% |
| `tsmom_lo_21__nupl_075` | tsmom_onchain_regime | FAIL | FAIL | no | +8.48% | -16.56% | +9.03% | +7.93% |
| `tsmom_lo_252__mvrvz_p80` | tsmom_onchain_regime | FAIL | FAIL | no | -1.23% | -16.30% | +1.80% | -4.25% |
| `tsmom_lo_252__mvrvz_p90` | tsmom_onchain_regime | FAIL | FAIL | no | -1.23% | -11.02% | +1.80% | -4.25% |
| `tsmom_lo_252__nupl_075` | tsmom_onchain_regime | FAIL | FAIL | no | -1.23% | -11.02% | +1.80% | -4.25% |
| `tsmom_lo_63__mvrvz_p80` | tsmom_onchain_regime | FAIL | FAIL | no | +4.16% | -9.43% | -6.37% | +14.68% |
| `tsmom_lo_63__mvrvz_p90` | tsmom_onchain_regime | FAIL | FAIL | no | +4.16% | -12.28% | -6.37% | +14.68% |
| `tsmom_lo_63__nupl_075` | tsmom_onchain_regime | FAIL | FAIL | no | +4.16% | -12.28% | -6.37% | +14.68% |
| `tsmom_ls_126__mvrvz_p80` | tsmom_onchain_regime | FAIL | FAIL | no | -10.88% | -5.55% | -7.56% | -14.19% |
| `tsmom_ls_126__mvrvz_p90` | tsmom_onchain_regime | FAIL | FAIL | no | -10.88% | +2.66% | -7.56% | -14.19% |
| `tsmom_ls_126__nupl_075` | tsmom_onchain_regime | FAIL | FAIL | no | -10.88% | +2.66% | -7.56% | -14.19% |
| `tsmom_ls_21__mvrvz_p80` | tsmom_onchain_regime | FAIL | FAIL | no | +7.54% | -29.67% | +15.99% | -0.91% |
| `tsmom_ls_21__mvrvz_p90` | tsmom_onchain_regime | FAIL | FAIL | no | +7.54% | -28.52% | +15.99% | -0.91% |
| `tsmom_ls_21__nupl_075` | tsmom_onchain_regime | FAIL | FAIL | no | +7.54% | -28.52% | +15.99% | -0.91% |
| `tsmom_ls_252__mvrvz_p80` | tsmom_onchain_regime | FAIL | FAIL | no | -3.69% | -21.03% | +3.39% | -10.76% |
| `tsmom_ls_252__mvrvz_p90` | tsmom_onchain_regime | FAIL | FAIL | no | -3.69% | -16.55% | +3.39% | -10.76% |
| `tsmom_ls_252__nupl_075` | tsmom_onchain_regime | FAIL | FAIL | no | -3.69% | -16.55% | +3.39% | -10.76% |
| `tsmom_ls_63__mvrvz_p80` | tsmom_onchain_regime | FAIL | FAIL | no | +7.81% | -20.40% | -12.79% | +28.41% |
| `tsmom_ls_63__mvrvz_p90` | tsmom_onchain_regime | FAIL | FAIL | no | +7.81% | -22.53% | -12.79% | +28.41% |
| `tsmom_ls_63__nupl_075` | tsmom_onchain_regime | FAIL | FAIL | no | +7.81% | -22.53% | -12.79% | +28.41% |

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** This overlay search does not flip a pin, does not add a pin, and does not enable live. An empty overlay-passer set is the successful outcome.

- Coin Metrics community regime series: **ok**.
- Overlay passers (`gated_name_dual_print_passer_and_mean_ho_and_wf_total_deltas_ge_0_on_both_prints`): 0 (none).
- Base (ungated) dual-print passers: 0 (none); unchanged from `traderstack-tsmom` by construction.
- Binance.US `older_720_ending_before_primary_first_bar`: scored (binance_us_spot; 720 BTC / 720 ETH; 2022-10-05T00:00:00+00:00 → 2024-09-23T00:00:00+00:00).
- **mixed_fail** (helps on one print/metric, hurts on another): `tsmom_lo_21__mvrvz_p90`, `tsmom_lo_63__mvrvz_p90`, `tsmom_lo_126__mvrvz_p90`, `tsmom_lo_252__mvrvz_p90`, `tsmom_ls_21__mvrvz_p90`, `tsmom_ls_63__mvrvz_p90`, `tsmom_ls_126__mvrvz_p90`, `tsmom_ls_252__mvrvz_p90`, `tsmom_lo_63__mvrvz_p80`, `tsmom_ls_63__mvrvz_p80`. Reported as FAIL, not as an edge.
- The runtime gate (`ONCHAIN_REGIME_GATE_ENABLED`) stays **off** by default regardless of this table; it can only withhold new longs.
- Do not enable live. Do not fabricate PnL. Do not retune thresholds, the window, or the overlay list after seeing this table. Era prints / DSR / PBO (#135, #136) are a follow-up.

`keep_flag_false=true`; `can_promote=false`. Do not fabricate PnL. Do not enable live. Do not average Binance.US with the Kraken primary window. Do not retune the overlay thresholds, the 1460-day window, or the stale limit after seeing this table.
