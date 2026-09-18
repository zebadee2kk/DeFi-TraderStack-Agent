# Paper perp-hedge soak — PRE-REGISTRATION (2026-09-18)

**HONESTY: PAPER ONLY. NOT A PROMOTE CLAIM. NOT LIVE PnL.**

Frozen **before** enabling \PAPER_PERP_HEDGE=true\ and before any soak
window. Prior plumbing soak (#114 / \ar/ops/paper-perp-hedge-soak.md\)
is not re-used as this run's metrics.

## Goal

Exercise the cycle-wired paper hedge+funding path
(\execution/paper_perp.py\ + \execution/paper_perp_feed.py\) under
\TRADING_MODE=paper\ and record **honest** plumbing metrics. This does
**not** unlock \can_promote\. Snapshot HL/HTX mids are **not** a
historical PIT mark−index / perp-mid−spot-mid series.

## Pre-registered measures (what this soak counts)

| Measure | How counted | Pass / note |
|---|---|---|
| Duration / cycles | Wall clock + \untime_cycle_completed\ log count in window | Bounded (target ~8–15 min or ≥30 cycles) |
| Mid source | \paper_perp_hedged\ log \enue\ + \source\ | Explicit HL \midPx\ or HTX bid/ask mid; never Kraken spot |
| Hedge opens | count \paper_perp_hedged\ | ≥0 (0 is OK if no spot fill to hedge) |
| Hedge skips | count \paper_perp_hedge_skipped\ by reason | Expected: already-open / no mid |
| Funding applications | count \paper_perp_funding_applied\ | May be 0 if no same-venue settlement in window — not a fail |
| Mid / funding fetch failures | \paper_perp_mid_fetch_failed\ / \paper_perp_funding_fetch_failed\ | Prefer 0 hard failures |
| Kill-switch withhold | With \KILL\ engaged: new hedges + funding withheld (\paper_perp_withheld\ / skip) | Drill optional; default soak leaves kill **off** but path must remain able to withhold |
| Promote pins | \	raderstack-check-config\ + \.env\ | Every \PAPER_PROMOTE_*=false\; no pin flipped |
| \PAPER_PERP_HEDGE\ hygiene | true only during soak | Restore **false** after |
| NAV / spot PnL | Portfolio checkpoint if present | **Plumbing context only** — never claimed as live profit or promote print |

## Explicit non-goals

- Do **not** invent PnL, funding, or basis.
- Do **not** set any \PAPER_PROMOTE_*=true\.
- Do **not** treat snapshot mids as PIT basis for research scoring.
- Do **not** claim subscription-funding readiness from this soak alone.
- Hedged carry research remains \keep_flag_false\ / not Kraken spot-executable.

## Config for the soak window

| Setting | Value |
|---|---|
| \TRADING_MODE\ | \paper\ |
| \PAPER_SIMULATE_FILLS\ | \	rue\ |
| \PAPER_PERP_HEDGE\ | \	rue\ during soak only |
| \PAPER_PROMOTE_*\ | all \alse\ (unchanged) |
| \PAPER_GARCH_SIZE\ | \alse\ |
| Mid preference | auto → Hyperliquid \midPx\, HTX bid/ask mid fallback; BitMEX not required |

## Artifacts (committed report path)

- Recipe (this file): \docs/artifacts/ops/paper-perp-hedge-soak-recipe-2026-09-18.md- Metrics report: \docs/artifacts/ops/paper-perp-hedge-soak-2026-09-18.md- Raw capture (local, not required in git): \ar/ops/_perp_hedge_soak_20260918/
## Blocker policy

If docker/app cannot run: document the blocker, keep promote flags false,
and land harness/docs/CLI fixes only — do not invent soak metrics.

## Tip at freeze

\main\ @ \800e22\ (#164). Branch: \eat/paper-perp-hedge-soak-2026-09-18\.
