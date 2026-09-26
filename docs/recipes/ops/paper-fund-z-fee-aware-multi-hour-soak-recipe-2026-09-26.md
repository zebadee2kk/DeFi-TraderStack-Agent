# Paper fund_z_harvest_sign_hold fee-aware multi-hour soak — PRE-REGISTRATION (2026-09-26)

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PnL. NOT EDGE PROVEN.**

Frozen **before** enabling PAPER_PERP_HEDGE=true and
PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD=true for the soak window, and before
any multi-hour host probe. Builds on:

- #176 fee-aware paper PnL soak tooling (`ops/paper_carry_pnl_soak/host_fee_aware_probe.py`,
  `PaperPerpBook.harvest_fee_aware_paper_pnl`)
- #177 default-false `PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD` pin (named passer wiring)
- #175 dual-print passer name `fund_z_harvest_sign_hold` (research; keep_flag_false)

## Goal

Prove whether **funding can outweigh open fees** over a longer window for the
named passer paper-perp path. Run an extended paper soak (≥3h preferred;
≥6h if the machine stays up; ≥90 min minimum if interrupted) and record
**measurable fee-aware paper PnL** from real book state + public HL/HTX mids
and same-venue funding prints. Formula (perp book only; spot NAV untouched):

    fee_aware_paper_pnl_usd =
        funding_pnl_usd
      + unrealized_mtm_usd(marks)
      - fees_usd

## Funding-interval expectation (frozen)

Hyperliquid funding settlements are typically about **hourly** (~1h). A
multi-hour soak is required so funding has a realistic chance to compound
against one-time open fees (PAPER_FEE_BPS + PAPER_SLIPPAGE_BPS on hedge open).
Sub-hourly windows may honestly show **0** new funding prints after open.

| Target wall | Expected HL funding windows (approx) |
|---|---|
| ≥90 min | ~1 interval |
| ≥3 h | ~3 intervals |
| ≥6 h | ~6 intervals |

Never invent funding prints or PnL if a print does not arrive.

## Fee assumptions (frozen)

| Leg | Assumption | Notes |
|---|---|---|
| Spot (if booked) | Pilot Kraken Pro Tier-1 **taker 80 bps** + **5 bps** slip | Synthetic spot is **not** booked into spot NAV — spot fee drag **not** charged |
| Perp open | PAPER_FEE_BPS default **10 bps** + PAPER_SLIPPAGE_BPS default **5 bps** | Matches paper-perp book wiring; never invent Kraken spot as perp fee |
| Maker / rebate | **Not assumed** | No post-only evidence |

## Opt-in flags (defaults stay false; Field definitions never flipped)

| Setting | Default | Soak window only |
|---|---|---|
| TRADING_MODE | paper | paper |
| PAPER_PERP_HEDGE | false | true via Settings.model_copy (prefer; .env stays false on host probe) |
| PAPER_PROMOTE_FUND_Z_HARVEST_SIGN_HOLD | false | true via Settings.model_copy (named passer wiring) |
| PAPER_CARRY_HEDGE_DIAGNOSTIC | false | **prefer leave false** (promote pin path preferred) |
| Every other PAPER_PROMOTE_* | false | unchanged false |
| PAPER_GARCH_SIZE | false | false |

Restore **all** soak flags to **false** after the window. Do **not** flip
Settings Field defaults. Do **not** set TRADING_MODE=live. Host probe uses
in-process `Settings.model_copy` only so `.env` need not be rewritten.

## Pre-registered soak duration

| Surface | Target | Acceptable partial |
|---|---|---|
| Host fee-aware probe | **≥3h** preferred; **≥6h** if machine stays up | ≥90 min minimum if interrupted; document limit; never invent PnL |
| Docker compose app | optional | Host probe is fine if docker DNS still broken |

## Pre-registered measures (must record; never invent)

| Measure | Source | Note |
|---|---|---|
| Signal | book / probe meta | Must be `fund_z_harvest_sign_hold` on promote pin path |
| Hedge opens | book positions | ≥0; target ≥1 when flags on + public mid+funding reachable |
| Mid source | venue + quote source | Explicit HL/HTX; never Kraken spot |
| Funding prints applied | funding_prints_applied | Expect ~1/hour/asset on HL when open through settlements |
| Fees USD | book total_fees_usd | From paper open fees; not invented NAV |
| Unrealized MTM USD | unrealized_mtm_usd(marks) | Skip asset if mid missing; marks_incomplete if so |
| Fee-aware paper PnL | funding + MTM - fees | UNAVAILABLE if marks incomplete |
| Spot NAV delta | portfolio snapshot | Must not invent spot NAV move |
| Flag hygiene | defaults before/after | All soak flags **false** before and after |

## Explicit non-goals

- Do **not** invent PnL, funding, basis, or mids.
- Do **not** leave PAPER_PERP_HEDGE / PAPER_PROMOTE_FUND_Z_* / diagnostic true after.
- Do **not** flip Settings Field defaults or go live.
- Do **not** treat fee-aware paper PnL as promote / live / edge proven.
- Do **not** book synthetic spot fills into the spot portfolio.

## Artifacts

- Recipe (this file): docs/recipes/ops/paper-fund-z-fee-aware-multi-hour-soak-recipe-2026-09-26.md
- Metrics report: docs/artifacts/ops/paper-fund-z-fee-aware-multi-hour-soak-2026-09-26.md
- Raw: var/ops/_fund_z_fee_aware_multi_hour_soak_20260926/
- Host probe: ops/paper_carry_pnl_soak/host_fee_aware_probe.py (extended; #176 reuse)

## Tip at freeze

main @ 59b568a (#176 tip; includes #177 fund_z pin at a4e20bd).
Branch: feat/fund-z-fee-aware-multi-hour-soak-2026-09-26.
