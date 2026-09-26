# Paper fund_z_harvest_sign_hold fee-aware multi-hour soak — 2026-09-26

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PROFIT. NOT EDGE PROVEN.**

Pre-registered before soak:
`docs/recipes/ops/paper-fund-z-fee-aware-multi-hour-soak-recipe-2026-09-26.md`.

Reused #176 host fee-aware probe / harvest; extended with `--mode fund_z`
(named passer wiring via #177 `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD`).
Docker not required — host probe is the soak surface. Flags enabled only via
`Settings.model_copy`; `.env` and Field defaults stayed **false**.

Interrupt note (attempt 1 aborted by WSL reboot; no PnL claimed):
`docs/artifacts/ops/paper-fund-z-fee-aware-multi-hour-soak-interrupt-2026-09-26.md`.

- Generated (London): 2026-09-26 ~09:18 BST
- Generated (UTC): 2026-09-26 ~08:18 UTC
- Tip/branch: `feat/fund-z-fee-aware-multi-hour-soak-2026-09-26` @ main tip including #176/#177 (+ #178/#179)
- Worktree: `/home/rham-admin/src/DeFi-TraderStack-Agent-fund-z-soak` (home path; `/tmp` wiped on WSL reboot)
- Raw: `var/ops/_fund_z_fee_aware_multi_hour_soak_20260926/host_fee_aware_probe.json`

## Window (meta)

| Item | Value |
|---|---|
| started_utc | 2026-09-26T02:13:59.868449+00:00 |
| ended_utc | 2026-09-26T08:14:10.611131+00:00 |
| started_london | 2026-09-26 03:13:59 BST |
| ended_london | 2026-09-26 09:14:10 BST |
| duration_requested_s | 21600 (6h) |
| duration_observed_s | 21610 (~6.003h) |
| sample_every_s | 60 |
| sample_count | 349 |
| mode | fund_z |
| signal | fund_z_harvest_sign_hold |

## Funding-interval expectation

HL funding often ~1h. Observed **12** funding prints applied (BTC+ETH across
six hourly settlements: 04:00–09:00 BST). Matches the pre-registered ~1h cadence.

## Fee assumptions (frozen; as executed)

| Leg | Assumption | Charged? |
|---|---|---|
| Spot (if booked) | Pilot Kraken Pro Tier-1 taker **80 bps** + **5 slip** | **No** — synthetic spot not booked |
| Perp open | `PAPER_FEE_BPS=10.0` + `PAPER_SLIPPAGE_BPS=5.0` | **Yes** — on hedge open |
| Maker / rebate | Not assumed | No |

## Observed metrics (honest; not invented)

| Measure | Observed |
|---|---|
| Hedge opens | **2** (BTC + ETH short perp; HL `midPx`) |
| Mid source | hyperliquid `/info metaAndAssetCtxs midPx` |
| Funding prints applied | **12** (6 BTC + 6 ETH hourly) |
| Total fees USD | **0.199900** |
| Final funding PnL USD | **0.013189** |
| Final unrealized MTM USD | **0.122011** |
| Final fee-aware paper PnL USD | **-0.064699** |
| Marks incomplete | **False** |
| Spot NAV before → after | **10000.0 → 10000.0** (unchanged) |
| Errors | **0** |

### Positions at end

| Asset | Side | Qty | Entry | Funding PnL USD | Final mark |
|---|---|---|---|---|---|
| BTC | sell | 0.00119002 | 83990.48375 | 0.005705 | 84017.5 |
| ETH | sell | 0.03712021 | 2692.603025 | 0.007484 | 2688.45 |

### Formula check

```
fee_aware = funding + mtm - fees
          = 0.013189 + 0.122011 - 0.199900
          = -0.064699
```

### Funding vs open fees (fee-survivability lens)

| Compare | USD |
|---|---|
| Cumulative funding (6h) | 0.013189 |
| Open fees (once) | 0.199900 |
| Funding covers fees? | **NO** |

Rough order-of-magnitude: ~0.0022 USD funding / hour on this $100×2 notional
book. Covering 0.20 USD open fees from funding alone would need on the order of
**~90 hours** of similar prints (ignoring MTM noise). MTM helped in this window
but fee-aware PnL remained negative.

## Promote / flag hygiene

| Check | Before | After |
|---|---|---|
| `trading_mode` paper | True | True |
| `paper_perp_hedge` default | False | False |
| `paper_carry_hedge_diagnostic` default | False | False |
| `paper_promote_fund_z_harvest_sign_hold` default | False | False |
| `paper_promote_ema_9_21` | False | False |
| `paper_promote_ema_9_21_adx15` | False | False |
| `paper_promote_searched_strategies` | False | False |
| `paper_garch_size` | False | False |

`.env` never flipped for this soak (`PAPER_PERP_HEDGE=false`,
`PAPER_CARRY_HEDGE_DIAGNOSTIC=false`, `PAPER_PROMOTE_FUND_Z_*` absent / false).
In-process enable: `paper_perp_hedge=true` + `paper_promote_fund_z_harvest_sign_hold=true`
via `Settings.model_copy` only. Field defaults never edited.

## Docker

Host probe used (compose DNS historically flaky). Not required for this result.

## Verdict

| Check | Result |
|---|---|
| Recipe pre-registered before soak | **PASS** |
| Paper-only / no live claim | **PASS** |
| Named passer signal `fund_z_harvest_sign_hold` | **PASS** |
| Promote pin path (not diagnostic) | **PASS** |
| Multi-hour window (≥3h; target 6h) | **PASS** (~6.003h) |
| Fee-aware paper PnL measurable | **YES** (`-0.064699` USD) |
| Funding settlements observed | **YES** (12 prints) |
| Funding outweighs open fees at 6h | **NO** |
| Spot NAV invented | **NO** |
| Flags restored false | **PASS** |
| Promote / edge proven | **BLOCKED** (unchanged) |

## Honest recommendation

**Paper-perp `fund_z_harvest_sign_hold` does not look fee-survivable at a
multi-hour (3–6h) horizon under the frozen perp open-fee model
(10+5 bps) on $100 notional per asset.** Funding accrued (~0.013 USD / 6h)
is an order of magnitude below open fees (~0.20 USD). Keep
`PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD=false` and research
`keep_flag_false`. Do **not** treat this as live profit or a promote print.

Optional later work (still paper-only): much longer soak (≥24–96h) or lower
fee assumptions only if independently evidenced — never invent PnL.

## Next recommended step

1. Leave all soak flags **false**.
2. Do not flip Settings Field defaults.
3. Do not go live / shadow on this pin from this soak alone.
