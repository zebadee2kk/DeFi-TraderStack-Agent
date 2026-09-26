# Ops note — `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD` (2026-09-26)

Paper / research only. **Not a profitability claim. Not a live path.**

## What this pin is

After #175 named dual-print passer `fund_z_harvest_sign_hold`
(HL×HTX funding + OKX×Binance Vision basis; paper-perp fees 5+5 bps × 2 legs;
hard gates combined=true on both prints), an operator-facing Settings pin exists:

| env | Settings field | default |
| --- | --- | ---: |
| `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD` | `paper_promote_fund_z_harvest_sign_hold` | **false** |

This is the documented honesty path after a committed report names a passer.
It does **not** enable trading by itself, does **not** flip live, and does
**not** claim spot edge.

## When it does anything

All of the following must hold:

1. `TRADING_MODE=paper` (unchanged default)
2. `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD=true` (explicit env; never default)
3. `PAPER_PERP_HEDGE=true` (paper-perp book/feed attached)

Then the cycle may open the same always-harvest `|rate|` paper-perp hedge
shape used by `PAPER_CARRY_HEDGE_DIAGNOSTIC`, logged as signal
`fund_z_harvest_sign_hold`. Synthetic spot is **not** booked into spot NAV.
Kraken spot is never used as a perp mid.

If the promote pin is true but `PAPER_PERP_HEDGE` is false, check-config
reports the pin as off / cannot promote and warns that the pin has no effect.

## What this is not

- Not Kraken-spot executability (score used paper-perp fee model, not 80+5 spot)
- Not a flip of `can_promote` in the #175 score report (`can_promote=false`,
  `keep_flag_false=true` remain the research honesty)
- Not permission to open live / shadow fills
- Not a claim that the dual-print WF/holdout numbers are bankable PnL

## Operator checklist

1. Leave the pin **false** unless you intentionally want the paper-perp soak path.
2. Keep every other `PAPER_PROMOTE_*=false` unless separately documented.
3. Do not set `TRADING_MODE=live`.
4. Prefer reading check-config before enabling anything.

Score / recipe context:

- `docs/artifacts/strategy-search/edge-status-2026-09-26.md`
- `docs/artifacts/strategy-search/fund-z-harvest-paper-perp-dual-print.md`
