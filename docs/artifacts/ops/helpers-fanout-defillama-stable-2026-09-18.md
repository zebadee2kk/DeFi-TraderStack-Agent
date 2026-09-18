# helpers-fanout-defillama-stable-2026-09-18

Paper-only slice toward fee-aware PAPER-EXECUTABLE strategy.
Tip pulled: `main` @ `f3659a7` (#165). Branch:
`feat/defillama-stable-net-issuance-2026-09-18`.

## What landed

1. **Pre-registration (recipe-first)**  
   `docs/artifacts/strategy-search/defillama-stable-net-issuance-dual-print-recipe.md`
2. **Fetcher** `src/traderstack/market/defillama_stablecoins.py`  
   host `https://stablecoins.llama.fi`; parse charts; net-issuance; LAG_DAYS=2;
   `PIT_SAFE_LIVE_HISTORY=False`; refuse live history for backtest.
3. **Research + CLI** `stable_net_issuance.py` / `_cli.py` + entry point
   `traderstack-stable-net-issuance`.
4. **Tests** `tests/test_stable_net_issuance.py` — 8 passed.
5. **Honest run report**  
   `docs/artifacts/strategy-search/defillama-stable-net-issuance-dual-print.md`  
   + `var/ops/defillama_stable_net_issuance_dual_print.json`  
   → `print_kind=unavailable`, `dual_print_passers=0`, `can_promote=false`.

## PIT verdict

**NOT PIT-SAFE.** No `as_of` / revision feed; `/stablecoincharts/all` is the
current view of history and may rewrite past circulating values. Live pull
fetched 3216 days and was **refused** for dual-print scoring (skip-not-invent).
Future score only with an operator `pit_safe` snapshot archive.

## Helpers fanout

| Helper | Role | Result |
|---|---|---|
| claude1 | design / PIT | see scratch md / empty→operator |
| claude2 | impl | see scratch md / empty→operator |
| claude3 | honesty | see scratch md / empty→operator |
| codex | QA | see scratch md / empty→operator |

## Honesty bar

- Never invented PnL.
- Never set `PAPER_PROMOTE_*=true`.
- Promote / `can_promote` still **blocked**.
- Weather pivot noted in report (collectors on main; empty eval remains success).

## Paper-fill gap (#165 soak; diagnostic only)

The paper-perp-hedge soak observed **0** hedges because all promote voters stayed
false, so the paper loop produced no spot fills for the hedge path to latch onto
(plumbing PASS, fills absent). Options without flipping defaults: diagnostic
funnel counters (`plan_rejected` / dust-exit / no-voter-flat), a fixtures-only
paper fill injector marked `can_promote=false`, or a longer soak once an
independent non-promote research path has fills. Do **not** flip `PAPER_PROMOTE_*`
to manufacture hedges.

## Helper sizes at commit time

| claude1 | design/PIT | empty→operator; ec=129 |
| claude2 | impl | empty→operator; ec=129 |
| claude3 | honesty | empty→operator; ec=129 |
| codex | QA | empty→operator; ec=1 |
