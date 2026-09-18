# helpers-fanout-carry-paper-fills-2026-09-18

Paper-only slice toward fee-aware PAPER PnL for research `carry_hedged_sign`.
Tip pulled: `main` @ `dc9ef7d` (#173). Branch:
`feat/carry-paper-fills-2026-09-18`.

## What landed

1. **Pre-registration** before enabling flags:
   `docs/artifacts/ops/paper-carry-fills-soak-recipe-2026-09-18.md` (`db6c073`)
2. **Settings** `paper_carry_hedge_diagnostic` default **false** — not a
   `PAPER_PROMOTE_*` pin; requires `PAPER_PERP_HEDGE` + `TRADING_MODE=paper`.
3. **Cycle wiring** `ContinuousPaperService._maybe_open_carry_diagnostic_hedge`
   — public funding sign → `carry_hedged_sign` spot side → explicit HL/HTX mid
   → `paper_perp_hedged`; synthetic spot fill **not** booked into spot NAV.
4. **Bounded docker soak** (~300s) with both flags true, then restored **false**.
5. **Committed metrics**:
   `docs/artifacts/ops/paper-carry-fills-soak-2026-09-18.md`
6. Host probe: `ops/paper_carry_fills/host_carry_probe.py`
7. Tests: `tests/test_paper_carry_diagnostic.py` (+ cli_check coverage)

## Soak hedge counts (honest)

| surface | hedges | note |
|---|---:|---|
| docker | **1** | BTC `carry_hedged_sign` diagnostic; 1 cycle in window |
| host probe | **2** | BTC+ETH; NAV unchanged |

## Honesty bar

- Never invented PnL / funding / basis / mids.
- Never set `PAPER_PROMOTE_*=true` (Field defaults and restored `.env` false).
- Diagnostic flag is **not** described as promote or production edge.
- `can_promote` still blocked (PIT basis UNAVAILABLE).
- Maker/rebate still blocked until post-only evidence.

## Next

Fee-aware **paper** PnL accounting on open diagnostic hedges — still not a
Settings promote.
