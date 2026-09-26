# HL asilletto cross-sectional funding-rank dual-era dual-print

**Recipe tip (re-freeze):** `6912b5f` (`docs/artifacts/strategy-search/fund-xs-rank-hl-dual-era-dual-print-recipe.md`). Initial recipe commit `b94582f`; scorer `cc16a73` / compact cache `c40d930`.


Generated: 2026-09-26T02:03:04.428726+00:00
Print kind: **dual_print**. funding=`hyperliquid_asilletto`; eras=`era_a_2024-01-01_2025-04-01` x `era_b_2025-04-02_2026-06-01`; universe=100; min_cross_section=8; can_promote=`false`; keep_flag_false=`true`; dual_print_passers=`0`; paper_path_ready=`true`

## Rules

Pre-registered HL asilletto cross-sectional funding-rank dual-era dual-print (frozen before score). Daily last funding per coin from asilletto81 asset_ctxs; CORE_UNIVERSE=100 incl BTC+ETH; MIN_CROSS_SECTION=8. Dollar-neutral L/S or single-sleeve catalogs. Fees 5+5 bps x 2 on gross turnover. Dual eras A/B non-overlapping. PAPER_PROMOTE_* stays false. Empty set success. Not a retune of fund_z_harvest / fund_div / xs-topk / price RV.

Executability: paper-perp multi-asset funding-rank; conceptually via PAPER_PERP_HEDGE; this CLI does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot

Fees: 5+5 bps x 2 legs on gross turnover `0.5*Σ|Δw|`.

## History notes

- `asilletto_funding_compact` **ok**: loaded compact cache daily_funding_last_core100.json; days=760
- `universe_long_tapes` **ok**: coins_with>=300_days=100; btc=True; eth=True
- `era_a_panel` **ok**: days=334; both_frac=1.0
- `era_b_panel` **ok**: days=426; both_frac=1.0

## BTC+ETH presence

- Era A: {'days': 334, 'btc_days': 334, 'eth_days': 334, 'both_days': 334, 'both_frac': 1.0}
- Era B: {'days': 426, 'btc_days': 426, 'eth_days': 426, 'both_days': 426, 'both_frac': 1.0}

## Candidates

| id | eraA WF | eraA HO | eligA | eraB WF | eraB HO | eligB | dual |
| --- | ---: | ---: | :---: | ---: | ---: | :---: | :---: |
| `fund_xs_rank_ls_k3` | -5.05% | -8.36% | no | -4.55% | -9.62% | no | no |
| `fund_xs_rank_ls_k5` | -4.64% | -7.87% | no | -4.23% | -8.99% | no | no |
| `fund_xs_rank_ls_k8` | -4.15% | -7.29% | no | -3.83% | -8.22% | no | no |
| `fund_xs_rank_short_top_k5` | -5.01% | -6.61% | no | -4.09% | -7.11% | no | no |
| `fund_xs_rank_long_bottom_k5` | -4.26% | -9.11% | no | -4.37% | -10.83% | no | no |
| `fund_xs_rank_ew_flat` | 0.00% | 0.00% | no | 0.00% | 0.00% | no | no |

## Dual-print passers

**0** dual-print passers.

## Promotion decision

**No candidate is auto-enabled.** can_promote=false; keep_flag_false=true. Recommended pin name (defaults false if added later): `n/a`. No live path. PAPER_PROMOTE_* untouched.
