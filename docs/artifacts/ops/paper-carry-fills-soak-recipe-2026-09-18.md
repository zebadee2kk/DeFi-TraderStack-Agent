# Paper carry fills soak — PRE-REGISTRATION (2026-09-18)

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PnL. NOT EDGE PROVEN.**

Frozen **before** enabling PAPER_PERP_HEDGE=true and
PAPER_CARRY_HEDGE_DIAGNOSTIC=true, and before any soak window.
Prior #165 soak (docs/artifacts/ops/paper-perp-hedge-soak-2026-09-18.md)
recorded plumbing PASS with **0** cycle-wired hedges because hedges
required a spot paper fill and every PAPER_PROMOTE_*=false produced
no promote-voter fills. This recipe addresses that funnel gap for the
**research** passer family carry_hedged_sign without inventing a
Settings promote pin.

## Goal

Exercise the paper perp+hedge path so a bounded soak can produce
paper_perp_hedged events driven by the **research** carry_hedged_sign
rule (harvest |funding| via cash-and-carry side from the **public**
same-venue funding tape + explicit HL/HTX mid), under
TRADING_MODE=paper. This is plumbing toward measurable fee-aware
**paper** PnL for the only dual-print research passer family that is
not Kraken spot-executable. It is **not** a promote unlock.

## Signal that drives hedges (frozen)

| Item | Value |
|---|---|
| Research id | carry_hedged_sign (informational; dual-print passer in funding-carry-daily; keep_flag_false; not Kraken spot-executable) |
| Input | Latest public funding settlement rate from the **same** venue as the perp mid (HL preferred, HTX fallback; BitMEX not required) |
| Decision | Always harvest when at least one settlement exists (matches research _want_harvest with no abs/z threshold). Missing tape → **skip**, never invent a rate. |
| Spot side | 
ate > 0 → BUY spot / SELL perp (receive funding as short); 
ate < 0 → SELL spot / BUY perp; 
ate == 0 → skip |
| Mid | Explicit Hyperliquid midPx or HTX bid/ask mid — **never** Kraken spot mid |
| Notional | Fixed diagnostic notional USD (constant in code; not a promote size) |
| Spot NAV | Synthetic spot fill is **not** booked into the spot portfolio (perp book stays separate; no invented NAV) |
| Promote | No PAPER_PROMOTE_* pin; diagnostic flag is **not** a promote pin |

## Opt-in flags (defaults stay false)

| Setting | Default | Soak window |
|---|---|---|
| TRADING_MODE | paper | paper |
| PAPER_PERP_HEDGE | alse | 	rue during soak only |
| PAPER_CARRY_HEDGE_DIAGNOSTIC | alse | 	rue during soak only |
| Every PAPER_PROMOTE_* | alse | **unchanged false** |
| PAPER_GARCH_SIZE | alse | alse |

PAPER_CARRY_HEDGE_DIAGNOSTIC is a paper-only soak diagnostic. It must
not be named or described as a promote pin. Live/shadow ignore both
flags.

## Pre-registered measures

| Measure | How counted | Pass / note |
|---|---|---|
| Duration / cycles | Wall clock + 
untime_cycle_completed | Bounded (~8–15 min or ≥20 cycles) |
| Mid source | paper_perp_hedged log enue + source | Explicit HL/HTX; never Kraken spot |
| Hedge opens | count paper_perp_hedged | ≥0; **target ≥1** when diagnostic+hedge on and public mid+funding reachable; 0 still OK if blocked (document why) |
| Signal skips | paper_carry_diag_skipped by reason | Expected: no funding / zero rate / already-open / no mid |
| Funding applications | count paper_perp_funding_applied | May be 0 in a short window |
| Kill withhold | optional drill | Path must still withhold when kill engaged |
| Promote pins | 	raderstack-check-config + .env | Every PAPER_PROMOTE_*=false |
| Flag hygiene | both diagnostic flags | Restore **false** after soak |
| PnL claims | none | Do **not** invent or claim live/promote PnL from this soak |

## Explicit non-goals

- Do **not** invent PnL, funding, basis, or mids.
- Do **not** set any PAPER_PROMOTE_*=true (defaults or soak).
- Do **not** treat snapshot mids as PIT basis for research scoring.
- Do **not** claim can_promote / subscription-funding readiness.
- Do **not** describe this as edge proven in production.
- Maker/rebate path remains blocked until post-only evidence.

## Artifacts

- Recipe (this file): docs/artifacts/ops/paper-carry-fills-soak-recipe-2026-09-18.md
- Metrics report: docs/artifacts/ops/paper-carry-fills-soak-2026-09-18.md
- Raw capture (local): ar/ops/_carry_fills_soak_20260918/
- Synthesis: docs/artifacts/ops/helpers-fanout-carry-paper-fills-2026-09-18.md (and scratch mirror)

## Blocker policy

If docker/app or public HL/HTX is unreachable: document the blocker,
keep promote flags false, land harness/docs/CLI only — do not invent
soak metrics. Host feed+book probe may complement docker (same honesty).

## Tip at freeze

main @ dc9ef7d (#173). Branch: eat/carry-paper-fills-2026-09-18.
