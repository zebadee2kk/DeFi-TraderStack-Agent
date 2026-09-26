# Paper carry fee-aware PnL soak — PRE-REGISTRATION (2026-09-26)

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PnL. NOT EDGE PROVEN.**

Frozen **before** enabling PAPER_PERP_HEDGE=true and
PAPER_CARRY_HEDGE_DIAGNOSTIC=true, and before any extended soak window.
Builds on #174 (docs/artifacts/ops/paper-carry-fills-soak-2026-09-18.md)
which proved diagnostic paper_perp_hedged (docker 1 + host 2) but did
**not** export fee-aware paper PnL components for open carry hedges.

## Goal

Run an **extended** paper soak on the carry hedge diagnostic path and
record **measurable fee-aware paper PnL** from real book state + public
mids / funding prints. Formula (perp book only; spot NAV untouched by
diagnostic):

    fee_aware_paper_pnl_usd =
        funding_pnl_usd
      + unrealized_mtm_usd(marks)
      - fees_usd

- funding_pnl_usd: from caller-supplied same-venue settlements only
  (0 is honest when no new print arrives in-window after open).
- unrealized_mtm_usd: from explicit HL/HTX mid marks only — never invent
  mid; missing mark for an open asset sets marks_incomplete=true
  (do **not** zero-fill missing marks).
- fees_usd: modelled paper **perp** open fees charged by PaperPerpBook
  (PAPER_FEE_BPS + adverse PAPER_SLIPPAGE_BPS at fill).

This is **diagnostic paper PnL != promote != live**.

## Fee assumptions (frozen)

| Leg | Assumption | Notes |
|---|---|---|
| Spot (if booked) | Pilot Kraken Pro Tier-1 **taker 80 bps** + **5 bps** slip | Diagnostic synthetic spot fill is **not** booked into the spot portfolio — spot fee drag is **not** charged in this soak. Documented for honesty if a future path books the leg. |
| Perp open | PAPER_FEE_BPS default **10 bps** + PAPER_SLIPPAGE_BPS default **5 bps** | Matches cli.py wiring: perp stub prices HL/HTX mids; inventing a Kraken spot tier as the perp fee is forbidden. |
| Maker / rebate | **Not assumed** | No post-only fill-rate evidence. |

## Opt-in flags (defaults stay false)

| Setting | Default | Soak window |
|---|---|---|
| TRADING_MODE | paper | paper |
| PAPER_PERP_HEDGE | false | true during soak only (host probe via Settings.model_copy; .env stays false unless docker path is used) |
| PAPER_CARRY_HEDGE_DIAGNOSTIC | false | true during soak only |
| Every PAPER_PROMOTE_* | false | **unchanged false** |
| PAPER_GARCH_SIZE | false | false |

Restore both diagnostic flags to **false** after the window (verify .env
and Field defaults). PAPER_CARRY_HEDGE_DIAGNOSTIC is **not** a promote pin.
Do **not** flip Settings pins for research carry_hedged_sign
(funding-carry-daily.md: can_promote=true research-only,
keep_flag_false=true — not Kraken-spot executable).

## Pre-registered soak duration

| Surface | Target | Acceptable partial |
|---|---|---|
| Host fee-aware probe | **>=30-60 min** wall with open hedges + periodic MTM samples | Shorter if network blocks; document limit; never invent PnL |
| Docker compose app | >=30 min wall **or** >=20 runtime_cycle_completed | Host probe + documented blocker if docker flaky |

## Pre-registered measures (must record; never invent)

| Measure | Source | Note |
|---|---|---|
| Hedge opens | count paper_perp_hedged / book positions | >=0; target >=1 when flags on + public mid+funding reachable |
| Mid source | venue + quote source | Explicit HL/HTX; never Kraken spot |
| Funding prints applied | funding_prints_applied / paper_perp_funding_applied | May be **0** in sub-hourly windows — honest |
| Fees USD | book total_fees_usd | From paper_fee_bps on open; not invented NAV |
| Unrealized MTM USD | unrealized_mtm_usd(marks) vs explicit mid | Skip asset if mid missing |
| Fee-aware paper PnL | funding + MTM - fees via harvest helper | Perp book only; UNAVAILABLE if marks incomplete |
| Spot NAV delta | portfolio snapshot | Diagnostic must **not** invent spot NAV move |
| Promote pins | check-config + .env + Field defaults | All PAPER_PROMOTE_*=false |
| Flag hygiene | both soak flags | Restored **false** after |

## Explicit non-goals

- Do **not** invent PnL, funding, basis, or mids.
- Do **not** set any PAPER_PROMOTE_*=true.
- Do **not** treat diagnostic paper PnL as promote / live / edge proven.
- Do **not** book synthetic diagnostic spot fills into the spot portfolio.
- Do **not** flip research keep_flag_false Settings pins.
- Maker/rebate path remains blocked until post-only evidence.

## Artifacts

- Recipe (this file): docs/recipes/ops/paper-carry-fee-aware-pnl-soak-recipe-2026-09-26.md
- Metrics report: docs/artifacts/ops/paper-carry-fee-aware-pnl-soak-2026-09-26.md
- Raw: var/ops/_carry_fee_aware_pnl_soak_20260926/
- Host probe: ops/paper_carry_pnl_soak/host_fee_aware_probe.py

## Tip at freeze

main @ 566d0a5 (#174). Branch: feat/paper-carry-pnl-soak-2026-09-26.
