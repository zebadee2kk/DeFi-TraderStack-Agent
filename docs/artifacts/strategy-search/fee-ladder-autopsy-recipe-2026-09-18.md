# Fee-ladder autopsy recipe (pre-registration)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18. Re-pin commit SHA in the run report.
**Never flips PAPER_PROMOTE_*.** Empty dual-print set is success.

## Why this exists

Empty dual-print streak #160–#172 at pilot Kraken Pro spot Tier-1 taker
(80 bps + 5 bps slip) raises a strategic question: is the bar a pure
fee-blocker (names clear at research 10+5 but not at pilot 80+5), or is
there no edge even at optimistic fees? This note freezes the catalog and
the fee ladder **before** any re-score.

## Frozen catalog (choose BEFORE any re-score)

- Catalog: **oi_mom** (HL+Bybit OI-momentum dual-print from #172)
- Rationale: already has dual-print plumbing (Kraken x Coinbase, Bybit OI
  feature tape, HL gate); scored `dual_print_passers=0` at pilot 80+5;
  do **not** retune ids after seeing PnL.
- Frozen ids (unchanged from #172 recipe):
  `oi_mom_fade_7`, `oi_mom_fade_14`, `oi_mom_fade_30`,
  `oi_mom_follow_7`, `oi_mom_follow_14`, `oi_mom_follow_30`;
  control `ma_cross_10_30` (cannot promote).
- Do not mutate other catalogs (vol-target, sess-gap, fund_div, xs-topk).

## Frozen fee ladder (choose BEFORE any re-score)

All rows already defined in `traderstack.fee_tiers` (no invented tiers).
Slippage frozen at 5 bps for all rows. Scored at **taker** only.

| label | tier_id | fee_bps | slip_bps | note |
| --- | --- | ---: | ---: | --- |
| pilot | `kraken_pro_spot_t1` | 80 | 5 | promote bar; PAPER_PROMOTE_* gate |
| intermediate | `kraken_pro_spot_t3` | 38 | 5 | one intermediate already in fee_tiers (Tier 3 $10K+ 30d) |
| research | `modelled` | 10 | 5 | pre-#138 research default / PAPER_FEE_BPS |

**Not scored here (on purpose):** t2 (60), t8 (20), t12 (10 venue) —
recipe freezes exactly one intermediate to avoid post-hoc ladder fishing.

## Passer / honesty rules (frozen)

- A name is a dual-print passer only if eligible on both Kraken and Coinbase
  under the fee-aware paper bar and it is not the control.
- If something clears at 10+5 or 38+5 but not at 80+5: that is a
  **fee-blocker finding**. Still keep every `PAPER_PROMOTE_*=false`
  (pilot bar is the promote bar).
- Never invent PnL. Report only counts / typical WF trades from the
  machine-written JSON.
- `can_promote=false`; `keep_flag_false=true` at every rung.

## Exact commands (outputs under artifacts/)

```bash
# pilot 80+5 (already scored in #172; re-run only to stamp this autopsy)
traderstack-oi-mom --hl-oi-json var/ops/oi_cache/asilletto81_oi.json \
  --bybit-oi-json var/ops/oi_cache/bybit_oi.json --fee-bps 80 --slippage-bps 5 \
  --candles-dir kraken var/research/candles/kraken \
  --candles-dir coinbase var/research/candles/coinbase \
  --output-md docs/artifacts/strategy-search/fee-ladder-oi-mom-pilot-80.md \
  --output-json docs/artifacts/strategy-search/fee-ladder-oi-mom-pilot-80.json

# intermediate 38+5 (frozen kraken_pro_spot_t3)
traderstack-oi-mom ... --fee-bps 38 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/fee-ladder-oi-mom-t3-38.md \
  --output-json docs/artifacts/strategy-search/fee-ladder-oi-mom-t3-38.json

# research 10+5 (modelled)
traderstack-oi-mom ... --fee-bps 10 --slippage-bps 5 \
  --output-md docs/artifacts/strategy-search/fee-ladder-oi-mom-modelled-10.md \
  --output-json docs/artifacts/strategy-search/fee-ladder-oi-mom-modelled-10.json
```

## Promote

Keep every `PAPER_PROMOTE_*=false`. This autopsy never adds or flips a
promote pin. TRADING_MODE stays paper. No live path.
