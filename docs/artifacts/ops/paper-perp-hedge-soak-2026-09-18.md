# Paper perp-hedge soak metrics — 2026-09-18

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PROFIT.**

Pre-registered before soak:
`docs/artifacts/ops/paper-perp-hedge-soak-recipe-2026-09-18.md`.

Snapshot HL/HTX mids are **not** historical PIT basis.
Every `PAPER_PROMOTE_*` stayed **false**. `PAPER_PERP_HEDGE` restored
**false** after the window.

- Generated (London): 2026-09-18 ~13:30 BST
- Generated (UTC): 2026-09-18 ~12:30 UTC
- Host: rh-lpt-win-01 WSL (`rham-admin`)
- Tip: `main` @ `b800e22` (#164); branch `feat/paper-perp-hedge-soak-2026-09-18`

## Window (meta)

```
phase=start utc=2026-09-18T12:16:04Z london=2026-09-18T13:16:04+0100 commit=b800e22
phase=mid1 utc=2026-09-18T12:24:05Z london=2026-09-18T13:24:05+0100 commit=b800e22
kill_drill_engage utc=2026-09-18T12:24:06Z
phase=kill utc=2026-09-18T12:24:52Z london=2026-09-18T13:24:52+0100 commit=b800e22
kill_drill_clear utc=2026-09-18T12:24:53Z
phase=end utc=2026-09-18T12:25:23Z london=2026-09-18T13:25:23+0100 commit=b800e22
```

Bounded soak ≈ 480s + ~75s kill drill. Raw:
`var/ops/_perp_hedge_soak_20260918/` (local).

## Pre-soak hygiene

| Check | Result |
|---|---|
| Recipe frozen before `PAPER_PERP_HEDGE=true` | YES |
| `traderstack-check-config` paper perp stub | **active (cannot promote)** — HL midPx / HTX bid/ask mid |
| Promote pins | all **no** / false |
| Postgres/redis | brought up (were down; app had been crash-looping on DB DNS) |
| App image | rebuilt from tip mid-window (old image idle); end window used tip image |

## Docker cycle soak (compose `app`)

### Observed (honest)

| Measure | Observed |
|---|---|
| `runtime_cycle_completed` (harvested end window) | **15** |
| `traderstack_cycles_total` @ end | BTC 5 / ETH 5 / SOL 5 success |
| `paper_perp_hedged` | **0** |
| `paper_perp_funding_applied` | **0** |
| Spot fills | only `plan_rejected` / `paper_fill_invalid_exit_size` (dust exits below min notional) — **no hedge trigger** |
| Kill drill (`metrics_kill`) | `traderstack_kill_switch_engaged=1.0` (source=`file`) |
| During kill | cycles with `risk_decision=reject` (new risk withheld) |
| After kill clear | `kill_switch_engaged=0.0`; cycles resume |
| Metrics NAV @ end | **9984.044670375004** (checkpoint context only — **not** a promote print) |
| Mid-window idle | After first recreate with hedge=true on **stale** image, runtime stayed idle (`runtime_healthy=0`, no new audit) until tip rebuild + recreate |

### Interpretation

Cycle-wired hedge path needs a **spot paper fill** to call
`_maybe_hedge_paper_perp`. This window produced no executable fills
(dust exit notionals), so docker logs show **zero** `paper_perp_*`
events. That is **not** invented as a funding or mid failure.

Kill-switch file channel engaged and cleared as drilled.

## Host feed+book probe (complement — same day)

Script: `var/ops/_host_paper_perp_probe.py` →
`var/ops/_perp_hedge_soak_20260918/host_probe.json`.

| Measure | Observed |
|---|---|
| Mid source BTC/ETH/SOL | **hyperliquid** `midPx` (`hyperliquid:/info metaAndAssetCtxs midPx`) |
| `paper_perp_hedged` | **yes** (BTC short perp vs synthetic spot fill) |
| Funding settlements (24h lookback) | **24** HL `fundingHistory` prints |
| `paper_perp_funding_applied` | **yes** (funding_pnl_usd ≈ 0.0213 on 0.001 BTC — paper book only) |
| Kill withhold | **`paper_perp_withheld`** (`kill switch engaged; paper perp hedge withheld`) |
| Errors | **0** |
| Promote flipped | **false** |

This probe proves mid + same-venue funding + withhold plumbing with
**public** HL data. It is **not** live PnL and is **not** booked into
the spot portfolio NAV.

## Env hygiene after soak

```
TRADING_MODE=paper
PAPER_SIMULATE_FILLS=true
PAPER_PERP_HEDGE=false
PAPER_PROMOTE_EMA_9_21=false
PAPER_PROMOTE_EMA_9_21_ADX15=false
PAPER_PROMOTE_SEARCHED_STRATEGIES=false
PAPER_GARCH_SIZE=false
```

## Crucix / polymarket wedge

See `docs/artifacts/ops/crucix-unblock-polymarket-wedge.md`.
Gate stands aside when Crucix is `not_configured`. Local `.env` only
(`CRUCIX_ENABLED` / `CRUCIX_BASE_URL` / `CRUCIX_API_KEY`) — **no secrets
in git**. Does not flip promote.

## Harness landed this PR

- Recipe (pre-reg): `docs/artifacts/ops/paper-perp-hedge-soak-recipe-2026-09-18.md`
- This metrics report
- Crucix unblock note (no secrets)
- `var/ops/_perp_hedge_soak_20260918_run.sh` (bounded soak + kill drill)
- `var/ops/_host_paper_perp_probe.py` (feed+book probe)
- `var/ops/_analyze_perp_soak_20260918.py` (report helper)

## Verdict

| Check | Result |
|---|---|
| Recipe pre-registered before soak | **PASS** |
| Paper-only / no live claim | **PASS** |
| `PAPER_PROMOTE_*` flipped | **NO** |
| Snapshot mid treated as PIT basis | **NO** |
| Docker kill-switch withhold | **PASS** (file channel) |
| Docker cycle-wired hedge/funding in-window | **NONE** (no spot fills — not a mid/funding invent) |
| Host HL mid + funding apply + withhold | **PASS** |
| `PAPER_PERP_HEDGE` restored false | **PASS** |
| Promote / subscription-funding readiness | **BLOCKED** (PIT basis / promote path unchanged) |

**Do not treat host probe funding_pnl or docker NAV as live profit or a
promote print.**
