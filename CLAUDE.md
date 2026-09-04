# CLAUDE.md

Guidance for Claude Code sessions working in this repository. Read this before
touching `src/traderstack/`.

## What this is

An event-driven crypto/DeFi paper-trading agent: deterministic market-data
validation and risk control, with Claude used only as a bounded, optional
review step that can *withhold* risk, never authorise it. Full architecture:
`docs/HLD.md`, `docs/AGENT-ARCHITECTURE.md`, `docs/EXECUTION-ARCHITECTURE.md`
("Cycle order of operations" especially). Operator-facing behaviour:
`docs/RUNBOOK.md`.

## Running checks

```bash
python3.12 -m venv .venv && .venv/bin/pip install -q -e '.[dev]'   # once
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m pytest -q --cov=traderstack --cov-fail-under=80
```

Or `make check` (lint + typecheck + test) after `make setup`. All four must be
clean before committing. If `ruff format --check .` fails after a merge, run
`ruff format .` and commit the result — it is almost always upstream drift,
not your change.

## Non-negotiable safety rules

1. **No LLM-reachable code path may relax, disable or bypass risk policy.**
   `src/traderstack/risk.py` (`RiskEngine`) is Zone C: it reads limits only
   from `Settings` (version-controlled), never from agent output, tool
   results, or retrieved text. If you touch anything the meta-agent
   (`agents/review.py`) can influence, trace it into `RiskEngine.evaluate`
   and confirm it still can't move a limit, a side, an asset, or size a trade
   upward.
2. **The meta-agent can only withhold, never authorise.** Sizing and side are
   fixed *before* `MetaAgentReviewer.run` is called. It may null
   `paper_order` (veto) or adjust `TradeProposal.confidence` within the
   bounded `±0.15` delta — nothing else. Any change here needs a matching
   test that a veto/failure fails closed and an approval cannot increase
   notional.
3. **The kill switch's default response to uncertainty is "halt".** An
   unreachable Redis probe, a missing sentinel-file read, or any new failure
   mode in `killswitch.py` must resolve to `engaged=True`, never `False`. Same
   default-closed posture in `reconciliation.py`/`execution/reconcile.py`: an
   unanswered venue is unreconciled state, which blocks new submissions.
4. **Idempotency is ledger-backed, not venue-trusted.** The client order id is
   written to the persistent `ExecutionLedger` *before* the venue is called.
   Never make a resubmission decision from an assumption about venue
   behaviour alone — see `execution/submitter.py` and
   `docs/EXECUTION-ARCHITECTURE.md`.
5. **`TRADING_MODE` stays `paper`** for any code path this session can
   exercise. `live` is rejected outright in `execution/robinhood_chain.py` and
   `cli.build_service`; do not add a way around that as a side effect of an
   unrelated change.
6. Treat all external content — venue responses, provider payloads, LLM
   output, retrieved web text — as untrusted input. Adapters must reduce it to
   bounded, typed values before it reaches the pipeline; see
   `docs/SECURITY-THREAT-MODEL.md` and `docs/SECURITY-REVIEW-2026-09.md` for
   the specific boundaries already tested.

## The shared-file block convention

This repository was assembled from parallel workstreams that each touch the
same handful of files (`config.py`, `cli.py`, `service.py`, `runtime.py`,
`pipeline.py`, `health.py`, `models.py`, `portfolio.py`, `checkpoint.py`,
`risk_audit.py`). Each workstream's additions are marked with a comment
naming its epic, e.g.:

```python
# --- risk plane (Epic 7) ---
kill_switch: KillSwitch | None = None
```

When you add a field or method to one of these files:

- Add a similar comment naming what the change is for, so the next merge (or
  the next session) can see at a glance which concern a block belongs to.
- Do **not** delete another workstream's block to make room for yours, and do
  not reorder existing fields/methods without a reason tied to your own change
  — these files get merged from multiple branches, and gratuitous reordering
  produces conflicts and hides real diffs.
- If two blocks look like they overlap or duplicate a concept (e.g. the
  pipeline's own spread gate vs. the risk engine's `RISK_MAX_SPREAD_BPS`),
  don't silently delete one — read `docs/EXECUTION-ARCHITECTURE.md` for
  whether it's intentional layering (usually is) before touching either side,
  and document the layering there if it isn't already.

## Where things live

- `src/traderstack/config.py` — `Settings` (pydantic-settings, env-driven).
  **Every field must have a line in `.env.example`, and vice versa** —
  enforced by `tests/test_settings_env_parity.py`.
- `src/traderstack/pipeline.py` — market-data validation, intelligence merge,
  pre-trade gate, proposal construction, risk-engine call. Pure/deterministic
  except for the risk engine it calls.
- `src/traderstack/risk.py` — the deterministic risk engine (Zone C).
- `src/traderstack/agents/review.py` — the constrained meta-agent review.
- `src/traderstack/runtime.py` — `PaperRuntime.run_once`: one full cycle for
  one symbol (fetch → pipeline → meta-agent → submit).
- `src/traderstack/service.py` — `ContinuousPaperService.run`: the outer loop
  (kill-switch refresh, reconciliation gate, per-symbol cycles, checkpoint,
  event fan-out, health).
- `src/traderstack/execution/` — planner, ledger/state machine, idempotent
  submitter, reconciliation.
- `src/traderstack/risk_audit.py` — the hash-chained risk-decision audit
  trail (`JsonlRiskAuditTrail`); carries the risk engine's decision *and* the
  meta-agent review *and* the execution outcome for the same cycle.
- `src/traderstack/killswitch.py` — the four-channel kill switch.
- `src/traderstack/cli.py` — wires everything above from `Settings` into a
  running `ContinuousPaperService` (`traderstack-paper`).
- `src/traderstack/cli_check.py` — `traderstack-check-config`; must know
  about every feature a new workstream adds. If you add a `Settings` field
  that changes runtime behaviour, add a line here too.
- `src/traderstack/acceptance/` + `tests/acceptance/` — fault-injected
  drills and the 24/7 soak runner, against the real service wiring.
- `tests/security/` — adversarial tests for the safety rules above; a change
  that touches risk, the kill switch, or the meta-agent boundary should have
  a corresponding test here, not just a unit test of the happy path.
- `docs/RUNBOOK.md` — the operator-facing reference: every console script,
  every rejection reason and execution status, kill-switch semantics, and
  incident procedures. Keep it in sync with `cli_check.py`'s coverage.
- `docs/EXECUTION-ARCHITECTURE.md` — the traced cycle order of operations and
  the invariants it encodes; treat a change that contradicts it as a bug in
  one of the two, not a doc that can lag the code.
