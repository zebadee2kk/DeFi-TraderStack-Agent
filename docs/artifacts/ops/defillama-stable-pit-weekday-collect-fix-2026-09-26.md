# DefiLlama PIT weekday collect — root cause + fix (2026-09-26)

**Paper only. No PAPER_PROMOTE_* changes.**

## tip_days before / after

| When | tip_days | as_of tips |
|---|---:|---|
| Before today's prior collect | **1** | 2026-09-18 only |
| After 2026-09-26 00:09 UTC collect | **2** | + 2026-09-26 |
| Sep 19–25 | **missing** | no backfill (recipe forbids inventing tip days) |

`tips.jsonl` tip_day on the Sep 26 fetch is **2026-09-25** (DefiLlama chart tip lags the fetch UTC day — expected).

## Root cause of "weekday routine failed"

There was **no weekday/daily automation**. After day-one (#169 / helpers-fanout-defillama-pit):

> Operator next: Schedule daily `TRADING_MODE=paper traderstack-defillama-stable-snapshot --live`.

`crontab -l` empty; `/etc/cron.d` had no traderstack job. Gap Sep 19–25 is absence of schedule, not a collector code crash on Sep 25.

Collector itself works: immutable `as_of=` refuse-overwrite, append `tips.jsonl`, regenerate `STATUS.md`.

## Fix landed

- Helper: `ops/defillama_stable_pit/weekday_collect.sh` (check → live → check; logs under `var/ops/defillama_stable_pit/`)
- Suggested crontab (operator install; not auto-installed here):

```cron
15 0 * * * cd /home/rham-admin/src/DeFi-TraderStack-Agent && TRADING_MODE=paper ops/defillama_stable_pit/weekday_collect.sh >> var/ops/defillama_stable_pit/cron.log 2>&1
```

## Re-collect today?

`as_of=2026-09-26/` already exists — default refuse overwrite. Do **not** `--force` unless recovering a corrupt tip. Next growth = tomorrow's UTC day.

## Dual-print

`enough_for_dual_print=false` (min tip_days=720). Leave promote false.
