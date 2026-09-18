# helpers-fanout-defillama-pit-2026-09-18

Paper-only slice: PIT-safe DefiLlama stablecoin issuance snapshot archive
(unblock #166 forward path). Tip pulled: `main` @ `a4ad04e` (#169).
Branch: `feat/defillama-pit-snapshot-archive-2026-09-18`.

## What landed

1. **Recipe (docs first)**  
   `docs/artifacts/strategy-search/defillama-stable-pit-snapshot-recipe.md`  
   — as_of = fetch UTC day; layout under `var/research/defillama/stablecoincharts/`;
   LAG_DAYS=2; tip-delta PIT series; refuse live historical score; MIN_SNAPSHOT_DAYS=720.
2. **Collector module + CLI**  
   `src/traderstack/market/defillama_stable_snapshots.py`  
   `src/traderstack/research/defillama_stable_snapshot_cli.py`  
   entry point `traderstack-defillama-stable-snapshot`.
3. **CLI archive-dir loader** on `traderstack-stable-net-issuance --pit-archive`
   (dir or tips.jsonl; requires ≥720 tips to allow score).
4. **Tests** `tests/test_defillama_stable_snapshots.py` (+ existing #166 tests) —
   **17 passed**.
5. **Day-one live collect** — tip_days=1; enough_for_dual_print=false.
6. **Honest dual-print attempt** — `print_kind=unavailable`, passers=0,
   can_promote=false. Docs: `defillama-stable-pit-snapshot-day1.md`,
   `defillama-stable-pit-archive-dual-print-attempt.md`; #166 report linked;
   edge-status updated.

## Helpers fanout

| Helper | Role | Result |
|---|---|---|
| claude1 | design / PIT dating | empty→operator (fanout script quoting blocked on host; operator continued) |
| claude2 | impl review | empty→operator |
| claude3 | honesty | empty→operator |
| codex | QA | not launched (prior npm linux dep missing); operator QA via pytest |

## Honesty bar

- Never invented PnL / dual-print from one live chart.
- Never set `PAPER_PROMOTE_*=true` (defaults verified false).
- Promote / `can_promote` still **blocked**.
- Did **not** pivot to second-era/kraken_archive — snapshot path landed.

## Operator next

Schedule daily `TRADING_MODE=paper traderstack-defillama-stable-snapshot --live`.
Re-score `stable_ni_*` only after tip_days ≥ 720.
