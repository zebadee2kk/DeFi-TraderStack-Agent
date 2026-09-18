# Paper perp-hedge soak harness (paper-only)

Never flip `PAPER_PROMOTE_*`. Restore `PAPER_PERP_HEDGE=false` after soaks.

1. Freeze measures in `docs/artifacts/ops/paper-perp-hedge-soak-recipe-*.md` **before** enabling hedge.
2. Host probe (HL mid + funding + kill withhold): `.venv/bin/python ops/paper_perp_hedge/host_paper_perp_probe.py`
3. Docker bounded soak + kill drill: `bash ops/paper_perp_hedge/soak_run.sh 480` (compose `app` healthy; postgres/redis up).
4. Commit metrics under `docs/artifacts/ops/paper-perp-hedge-soak-*.md` — never invent PnL.

See also `docs/artifacts/ops/crucix-unblock-polymarket-wedge.md`.
