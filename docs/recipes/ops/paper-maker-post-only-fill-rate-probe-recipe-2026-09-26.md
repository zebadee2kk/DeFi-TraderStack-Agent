# Paper maker / post-only fill-rate probe — PRE-REGISTRATION (2026-09-26)

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT MAKER EDGE. NOT LIVE.**

Frozen **before** any fill-rate measurement. Purpose: unblock or keep-blocked
the maker/rebate path that edge-status lists as *blocked until post-only
paper fill-rate evidence*.

## Goal

Measure whether the existing Kraken paper path (`PAPER_SIMULATE_FILLS` +
`PaperFillSimulator`) can produce **honest** post-only / maker fill vs
cancel / time-to-fill evidence over a bounded window (≤2h), OR document
that the simulator is **INVALID** for maker evidence.

## Probe gate (required)

1. Search for existing post-only / maker simulation on the Kraken paper path.
2. If present: use it; record fill_rate, cancel_rate, time-to-fill.
3. If absent: run a **minimal** paper probe that places post-only-*style*
   intents through `PAPER_SIMULATE_FILLS` / `PaperFillSimulator` and records
   whether fills are immediate, delayed, or cancelled.
4. **Honesty stop:** if the paper simulator always fills immediately at
   mid ± adverse slip (taker-style), document maker evidence as **INVALID**
   / **UNAVAILABLE** and **stop**. Do not invent resting-queue behaviour.
   Do not score dual-prints at maker bps.

## Explicit non-goals

- Do **not** flip any `PAPER_PROMOTE_*`.
- Do **not** add `PAPER_MAKER_FEE_BPS` or score at maker fees.
- Do **not** fake maker edge from taker fills.
- Do **not** implement a full #73 post-only planner in this slice unless
  measurement already proves a resting path exists (it does not today per
  EXECUTION-ARCHITECTURE: maker path is #73 and does not exist yet).

## Pre-registered measures

| Measure | Note |
|---|---|
| post_only_path_exists | true/false from code probe |
| orders_attempted | N paper intents |
| fills | count of PaperFillStatus.FILLED |
| cancels | count of cancel/expire (0 if simulator has no cancel path) |
| time_to_fill_ms | wall time from apply() start to FILLED; sync ≈ 0 |
| maker_evidence_status | VALID / INVALID / UNAVAILABLE |
| fill_rate | fills/attempted, or UNAVAILABLE when INVALID |

## Artifacts

- Recipe (this file): `docs/recipes/ops/paper-maker-post-only-fill-rate-probe-recipe-2026-09-26.md`
- Probe: `ops/paper_maker_fill_probe/probe_immediate_fill.py`
- Report: `docs/artifacts/ops/paper-maker-post-only-fill-rate-probe-2026-09-26.md`
- Raw JSON: `var/ops/paper_maker_fill_probe_20260926.json`

## Tip at freeze

`origin/main` @ `fc30e5b` (#181 fund_z fee-aware multi-hour soak).
Branch: `feat/maker-probe-fund-mom-2026-09-26`.
