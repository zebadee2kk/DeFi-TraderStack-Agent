# Paper carry fee-aware PnL soak — 2026-09-26

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PROFIT. NOT EDGE PROVEN.**

Pre-registered before soak:
`docs/recipes/ops/paper-carry-fee-aware-pnl-soak-recipe-2026-09-26.md`.

Extended host fee-aware probe on the `#174` carry diagnostic path.
Docker compose `app` was restarting (postgres DNS) — host probe is the
soak surface. Diagnostic flags enabled only via `Settings.model_copy`;
`.env` and Field defaults stayed **false**. Every `PAPER_PROMOTE_*` stayed
**false**. Spot NAV unchanged (diagnostic synthetic spot not booked).

- Generated (London): 2026-09-26 ~02:16 BST
- Generated (UTC): 2026-09-26 ~01:16 UTC
- Tip/branch: `feat/paper-carry-pnl-soak-2026-09-26`
- Raw: `var/ops/_carry_fee_aware_pnl_soak_20260926/host_fee_aware_probe.json`

## Window (meta)

| Item | Value |
|---|---|
| started_utc | 2026-09-26T00:15:34.989101+00:00 |
| ended_utc | 2026-09-26T01:16:21.851076+00:00 |
| duration_requested_s | 3600 |
| duration_observed_s | 3646 |
| sample_every_s | 60 |
| sample_count | 58 |
| signal | carry_hedged_sign |

## Fee assumptions (frozen; as executed)

| Leg | Assumption | Charged? |
|---|---|---|
| Spot (if booked) | Pilot Kraken Pro Tier-1 taker **80 bps** + **5 slip** | **No** — diagnostic spot not booked |
| Perp open | `PAPER_FEE_BPS=10.0` + `PAPER_SLIPPAGE_BPS=5.0` | **Yes** — on hedge open |
| Maker / rebate | Not assumed | No |

## Observed metrics (honest; not invented)

| Measure | Observed |
|---|---|
| Hedge opens | **2** (BTC + ETH short perp; HL `midPx`) |
| Mid source | hyperliquid `/info metaAndAssetCtxs midPx` |
| Funding prints applied | **2** (1 BTC + 1 ETH at ~01:00 UTC hour) |
| Total fees USD | **0.199900** |
| Final funding PnL USD | **0.001757** |
| Final unrealized MTM USD | **0.108027** |
| Final fee-aware paper PnL USD | **-0.090116** |
| Marks incomplete | **False** |
| Spot NAV before → after | **10000.0 → 10000.0** (unchanged) |
| Errors | **0** |

### Positions at end

| Asset | Side | Qty | Entry | Funding PnL USD | Final mark |
|---|---|---|---|---|---|
| BTC | sell | 0.00118982 | 84004.4768 | 0.000509 | 83918.5 |
| ETH | sell | 0.03715331 | 2690.2042 | 0.001248 | 2690.05 |

### Formula check

```
fee_aware = funding + mtm - fees
          = 0.001757 + 0.108027 - 0.199900
          = -0.090116
```

## Promote / flag hygiene

| Check | Before | After |
|---|---|---|
| `paper_perp_hedge` default | False | False |
| `paper_carry_hedge_diagnostic` default | False | False |
| `paper_promote_ema_9_21` | False | False |
| `paper_promote_ema_9_21_adx15` | False | False |
| `paper_promote_searched_strategies` | False | False |
| `paper_garch_size` | False | False |

`.env` was never flipped for this soak (in-process `Settings.model_copy` only).

## Docker

Compose `app` was **restarting** (postgres DNS / `socket.gaierror`). Multi-cycle
docker soak **blocked**. Host probe ran the ≥60 min window instead.

## Verdict

| Check | Result |
|---|---|
| Recipe pre-registered before soak | **PASS** |
| Paper-only / no live claim | **PASS** |
| `PAPER_PROMOTE_*` flipped / defaults true | **NO** |
| Fee-aware paper PnL measurable | **YES** (`-0.090116` USD) |
| Funding settlements observed | **YES** (2 prints) |
| Spot NAV invented | **NO** |
| Flags restored false | **PASS** (never written true to `.env`) |
| Promote / edge proven | **BLOCKED** (unchanged) |

**Do not treat this fee-aware paper PnL as live profit or a promote print.**
It is diagnostic paper book state under explicit HL mids + modelled perp fees.

## Next recommended step

1. Keep `PAPER_PROMOTE_*=false` and `keep_flag_false` for research `carry_hedged_sign`.
2. Optionally extend to a multi-hour host soak (≥3–6 funding hours) to thicken
   the funding component relative to open fees, still paper-only.
3. Do **not** flip Settings pins until a Kraken-spot-executable path exists
   (research model is dual_basis / not Kraken-spot executable).
