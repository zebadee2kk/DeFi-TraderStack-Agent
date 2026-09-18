# Crucix config to unblock Polymarket crypto wedge (paper-only)

**No secrets in git.** Set these only in local `.env` / operator secrets store.

The #142 crypto wedge gate stands aside when Crucix status is
`not_configured`. Enabling Crucix does **not** invent edge and does
**not** flip any `PAPER_PROMOTE_*` pin. The gate can only **remove**
would-trades (stand-aside).

## Local keys (never commit values)

| Key | Purpose |
|---|---|
| `CRUCIX_ENABLED=true` | Opt in the Crucix intelligence adapter |
| `CRUCIX_BASE_URL` | Base URL reachable from the app process |
| `CRUCIX_API_KEY` | Local API key — **not** written to git |

## Compose reachability

`docker-compose.yml` maps `host.docker.internal` → host gateway so a
host-side Crucix process is reachable from the `app` container, e.g.:

```bash
# local .env only — example shape, not a real key
CRUCIX_ENABLED=true
CRUCIX_BASE_URL=http://host.docker.internal:8787
CRUCIX_API_KEY=replace-me-locally
```

Confirm with `traderstack-check-config` and a paper
`traderstack-polymarket-crypto-collect --once` that Crucix is no longer
`not_configured`. Keep `TRADING_MODE=paper`. Leave every
`PAPER_PROMOTE_*=false`.

See also: `.env.example` (`CRUCIX_*`), `docs/RUNBOOK.md` (intel /
polymarket crypto wedge sections),
`docs/artifacts/strategy-search/polymarket-crypto-wedge-eval.md`.
