# DefiLlama stablecoin PIT weekday cron — INSTALLED (2026-09-26)

**HONESTY: PAPER / PIT tip archive only. No tip-day backfill. Never invent history.**

Installed on WSL host after #185 landed `ops/defillama_stable_pit/weekday_collect.sh`
on `origin/main` @ `7b3f18a`. Root cause of Sep 19–25 gap was **no cron** after
day-one (not a collector crash). This installs the scheduleable entry only.

## Exact crontab line installed

```
5 16 * * 1-5 /bin/bash /home/rham-admin/src/DeFi-TraderStack-Agent/ops/defillama_stable_pit/weekday_collect.sh >> /home/rham-admin/src/DeFi-TraderStack-Agent/var/ops/defillama_stable_pit/cron.log 2>&1
```

- Schedule: **weekdays 16:05 UTC** (17:05 Europe/London BST)
- Script path: home repo copy synced from main tip content
- Log: `var/ops/defillama_stable_pit/cron.log`
- No Sep 19–25 backfill (recipe forbids inventing tip days)

## tip_days at install

`--check-only` after install probe: **tip_days=2** (`enough_for_dual_print=False`, min=720).

## Related

- Helper: `ops/defillama_stable_pit/weekday_collect.sh` (#185)
- Prior note: `docs/artifacts/ops/defillama-stable-pit-weekday-collect-fix-2026-09-26.md`
