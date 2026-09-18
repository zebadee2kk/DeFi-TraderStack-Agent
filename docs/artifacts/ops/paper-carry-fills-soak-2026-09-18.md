# Paper carry fills soak metrics — 2026-09-18

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PROFIT. NOT EDGE PROVEN.**

Pre-registered before soak:
`docs/artifacts/ops/paper-carry-fills-soak-recipe-2026-09-18.md`.

This slice wires a **paper-only** `PAPER_CARRY_HEDGE_DIAGNOSTIC` (default
**false**, not a `PAPER_PROMOTE_*` pin) so `PAPER_PERP_HEDGE=true` can open
`carry_hedged_sign`-directed paper perp hedges from public funding sign +
explicit HL/HTX mid **without** a promote-voter spot fill. Snapshot mids are
**not** historical PIT basis. Every `PAPER_PROMOTE_*` stayed **false**.
Both diagnostic soak flags restored **false** after the window.

- Generated (London): 2026-09-18 ~18:00 BST
- Generated (UTC): 2026-09-18 ~17:00 UTC
- Host: rh-lpt-win-01 WSL (`rham-admin`)
- Tip/branch: `feat/carry-paper-fills-2026-09-18` @ `00b89a5` (recipe `db6c073`)

## Window (meta)

```
phase=start utc=2026-09-18T16:51:32Z london=2026-09-18T17:51:32+0100 commit=00b89a5
phase=mid1 utc=2026-09-18T16:56:33Z london=2026-09-18T17:56:33+0100 commit=00b89a5
phase=end utc=2026-09-18T16:56:33Z london=2026-09-18T17:56:33+0100 commit=00b89a5
```

Bounded docker soak ≈ 300s. Raw: `var/ops/_carry_fills_soak_20260918/` (local).

## Pre-soak hygiene

| Check | Result |
|---|---|
| Recipe frozen before enabling flags | YES (`db6c073`) |
| `traderstack-check-config` paper perp | **active (cannot promote)** |
| Paper carry hedge diagnostic | **active (not a promote pin)** during soak |
| Promote pins | all **no** / false |
| Settings Field defaults | `paper_perp_hedge=False`, `paper_carry_hedge_diagnostic=False`, all `paper_promote_*=False` |

## Docker cycle soak (compose `app`)

### Observed (honest)

| Measure | Observed |
|---|---|
| `runtime_cycle_completed` (harvested window) | **1** (app slow to first cycle after recreate) |
| `traderstack_cycles_total` @ end | BTC **1** success |
| `paper_perp_hedged` | **1** (BTC; `diagnostic=True`, `signal=carry_hedged_sign`, venue=hyperliquid `midPx`, funding_rate=1.25e-05, spot_side=buy) |
| `paper_carry_diag_skipped` | **0** in harvested window |
| `paper_perp_funding_applied` | **0** (no new settlement in short window after open) |
| Metrics NAV @ end | **9984.049…** (checkpoint context only — **not** a promote print; unchanged by diagnostic synthetic spot) |
| Promote flipped | **NO** |

### Interpretation

With `PAPER_CARRY_HEDGE_DIAGNOSTIC=true` the cycle opened a
`carry_hedged_sign` paper perp hedge **without** needing a promote voter
spot fill — closing the #165 funnel gap for this research family. Only one
cycle completed in the 300s window after image recreate, so only BTC
hedged in docker before the capture ended. That is an honest cycle-count
limit, not an invented mid/funding failure.

## Host feed+book probe (complement — same day)

Script: `ops/paper_carry_fills/host_carry_probe.py` →
`var/ops/_carry_fills_soak_20260918/host_carry_probe.json`.

| Measure | Observed |
|---|---|
| Signal | `carry_hedged_sign` |
| Mid source BTC/ETH | **hyperliquid** `midPx` |
| `paper_perp_hedged` | **2** (BTC + ETH short perp; positive funding → buy spot / sell perp) |
| Spot portfolio NAV | **unchanged** 10000 → 10000 (synthetic fill not booked) |
| Errors | **0** |
| Promote Field defaults | **false** (verified via `Settings.model_fields[*].default`) |
| Promote flipped | **false** |

Host probe proves the diagnostic path with public HL data. It is **not**
live PnL and is **not** a promote print. Note: a bare `Settings()` during
the soak window reflected temporary `.env=true`; Field defaults and
post-restore `.env` are **false**.

## Env hygiene after soak

```
TRADING_MODE=paper
PAPER_SIMULATE_FILLS=true
PAPER_PERP_HEDGE=false
PAPER_CARRY_HEDGE_DIAGNOSTIC=false
PAPER_PROMOTE_EMA_9_21=false
PAPER_PROMOTE_EMA_9_21_ADX15=false
PAPER_PROMOTE_SEARCHED_STRATEGIES=false
PAPER_GARCH_SIZE=false
```

App recreated with restored flags.

## Harness landed this PR

- Recipe (pre-reg): `docs/artifacts/ops/paper-carry-fills-soak-recipe-2026-09-18.md`
- This metrics report
- `PAPER_CARRY_HEDGE_DIAGNOSTIC` Settings field (default false; not a promote pin)
- Cycle wiring: `ContinuousPaperService._maybe_open_carry_diagnostic_hedge`
- `ops/paper_carry_fills/soak_run.sh`, `ops/paper_carry_fills/host_carry_probe.py`
- Unit tests: `tests/test_paper_carry_diagnostic.py`

## Verdict

| Check | Result |
|---|---|
| Recipe pre-registered before soak | **PASS** |
| Paper-only / no live claim | **PASS** |
| `PAPER_PROMOTE_*` flipped / defaults true | **NO** |
| Snapshot mid treated as PIT basis | **NO** |
| Docker cycle-wired diagnostic hedge | **1** `paper_perp_hedged` (BTC) |
| Host HL carry diagnostic hedges | **2** (BTC+ETH) |
| Spot NAV invented by diagnostic | **NO** |
| Flags restored false | **PASS** |
| Promote / `can_promote` / edge proven | **BLOCKED** (unchanged) |

**Do not treat host probe or docker NAV as live profit or a promote print.**
This is plumbing toward measurable fee-aware **paper** PnL for the research
`carry_hedged_sign` family — not Settings promote and not production edge.
