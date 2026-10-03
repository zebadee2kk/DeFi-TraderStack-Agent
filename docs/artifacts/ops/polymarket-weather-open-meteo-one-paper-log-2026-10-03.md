# Polymarket weather one-paper log — Open-Meteo (2026-10-03)

Report-only. **Not a promotion claim.** Empty/negative is success.
Recipe frozen first at `docs/recipes/ops/polymarket-weather-open-meteo-one-paper-2026-10-03.md`
(commit before this score). `PAPER_PROMOTE_*` untouched.

## Tool path

| Item | Value |
|---|---|
| Signal | Open-Meteo NWP high (public; no key) — emitted on PIT tape |
| Settlement | IEM ASOS primary + NCEI GHCN cross-check (public; no key) |
| Crucix | not used / STOPPED (`CRUCIX_ENABLED` false/absent, blank URL/key) |
| Crypto wedge | not this test (stands aside without Crucix clear) |

## Frozen recipe (recap)

| Field | Value |
|---|---|
| market_id | `4608557` |
| question | Will the highest temperature in Miami be between 90-91°F on September 18? |
| side | **no** |
| ask paid | **0.540000** |
| half_spread | 0.005000 |
| shares | 18.518519 at $10.00 notional |
| fee (V2) | 0.322000 USDC (`shares * 0.07 * p * (1-p)`, cap 1.75/100) |
| hold | to resolution |

## Resolution

| Field | Value |
|---|---|
| official_high_f | **90.0** °F (iem_asos) |
| GHCN cross-check | 90.0 °F (ncei_ghcn_daily); mismatch=0.0 |
| YES won? | **True** (bucket 90.0-91.0 inclusive) |
| side won? | **False** |

## Score (n=1)

| Field | Value |
|---|---|
| n | 1 |
| resolved | yes |
| gross USDC | -10.000000 |
| fee USDC | 0.322000 |
| **net USDC after fees and spread** | **-10.322000** |

Spread was paid by entering at the touch ask (not mid). No soak left running.
Do not treat this single print as an edge. Promote flags remain false.
