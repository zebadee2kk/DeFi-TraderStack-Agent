# Paper session note — 2026-10-03

Report-only documentation of work already completed. **Not a scored edge. Not a promote. Not live.**

**Explicit honesty for this session:**

- Gamma **5229027** is **unresolved and unscored** (no fill, no settlement, no USDC score).
- The **296-market** temperature pass **passed nothing** (0 markets cleared the bar).
- The Crucix adapter change is **local-only** and is **NOT part of this commit**.

Checkout tip at session write-up: local HEAD around `6116873` on
`feat/paper-promote-fund-z-harvest-sign-hold-2026-09-26` (uncommitted Crucix
adapter dirt left unstaged).

---

## Public pricing (not Richard's invoice)

- No standalone Grok Bot price observed.
- Cursor Pro is **$20/mo**.
- Completed paper PnL does **not** cover that.
- His billed tier was **not visible**.

---

## Fund_z closed

- Fund_z is **closed**.
- Main had landed through PR **#188** (`cc73394`) then **#189** (`fefa000`).
- **48h soak** PID **45859** died with **no final JSON** (mid-snapshot only, fee-negative).
- **7d soak** PID **2638509** died about **15h** in; last log **2026-09-27 12:03 BST**; no `host_fee_aware_probe.json`.
- Hiabs dual-print after #188 was **dropped unfinished**.
- `PAPER_PROMOTE` flags stayed **false**.
- No notional scale.
- No new fund_z, funding, basis, or catalog PR in this session.

---

## Crucix local (NOT in this commit)

Local-only; zero API key; **not** included in this documentation commit.

| Field | Value |
|---|---|
| Clone | `/home/rham-admin/src/Crucix` @ `3db7068` |
| Node PID | **914691** |
| Wrapper PID | **914686** |
| Started | **2026-10-03 14:03 BST** |
| Health | `GET http://127.0.0.1:3117/api/health` status **ok** around **2026-10-03 14:05 UTC**, same PID |
| Earlier health | `sourcesOk` **27**, `sourcesFailed` **2**, `llmEnabled` **false** |
| Heartbeat | `var/ops/crucix-local-heartbeat.log`: **DEAD** `2026-10-03T14:02:33+01:00` exit **143**; **START** `2026-10-03T14:03:23+01:00` |
| Soak? | **Not a soak** |

Gitignored `.env` (do not read secrets into the commit):

- `CRUCIX_ENABLED=true`
- `CRUCIX_BASE_URL=http://127.0.0.1:3117`
- `CRUCIX_API_KEY` blank
- No SearXNG, no Perplexica, no paid key

Live adapter reads observed this session:

- `GET /alerts` was **404**.
- Uncommitted local adapter reads `GET /api/data`.
- Live read: `NewsSnapshot` `source_id=crucix:data`, `item_count=50`, `event_score=0.0`, `adverse_event=false`.
- polymarket **0**, conditionId **0**, clob **0**. Polymarket match count **0**.
- `tests/test_crucix.py` **17 passed** on that checkout with `PYTHONPATH` set to it.
- Those tests are **not on main**.

Uncommitted local files left unstaged (not this commit):
`src/traderstack/market/crucix.py`, `tests/test_crucix.py`,
`tests/fixtures/crucix_api_data.json`.

---

## PR #189 Miami score (already landed; do not rescore)

PR **#189** already scored Miami **90-91°F** on **2026-09-18**, Gamma **4608557**,
**NO** at **0.54**, net **-10.322 USDC** on **$10** after V2 fee and spread.
**Not a winner.** Do not rescore.

---

## Frozen unresolved: Gamma 5229027

**Unresolved and unscored.**

| Field | Value |
|---|---|
| Market | San Francisco highest temperature **82-83°F** on October 5 |
| End | `2026-10-05T12:00:00Z` |
| Side | **NO** |
| Bucket | **[82, 84)** |
| Open-Meteo | **94.7°F** at 37.6188,-122.3750 |
| NOAA daytime | **84.0°F** |
| Forecasts vs bucket | Both **outside** the bucket |
| NO book | `2026-10-03T13:13:50.891Z` best_bid **0.63**, best_ask **0.9**, half-spread **0.135**, fee haircut **0.02** |
| Win-at-ask sketch | A win at **0.90** is about **0.08** per $1 after the haircut |
| Note | NOAA is **one degree** from the bucket |
| Outcome | **No fill, no settlement, no USDC score** |

---

## Los Angeles Gamma 5174515 (not traded)

Los Angeles Gamma **5174515** (**100-101°F** on **3 Oct**) **not traded**:
Open-Meteo **101.8°F** vs NOAA **85°F**.

---

## 2026-10-03 one pass — 296 open temperature markets

**None passed.**

| Field | Value |
|---|---|
| Cities | Atlanta, Austin, Chicago, Dallas, Denver, Houston, Los Angeles, Miami, New York City, San Francisco, Seattle |
| Dates | 2026-10-03 through 2026-10-05 |
| Gamma fetch | `2026-10-03T14:04:38Z`–`14:04:40Z` |
| Forecasts | `14:04:41Z`–`14:04:47Z` |
| CLOB books | **239** books `14:04:47Z`–`14:05:30Z`, **0** HTTP errors |
| Excluded | **5229027** |
| Passed | **0** |

Bar (all required):

- both forecasts same side
- closer forecast at least **5°F** outside the bucket
- real `best_ask`
- net `(1 - ask - 0.02)` at least **0.25**
- ask `>= 0.90` rejected

Skip counts:

| Reason | Count |
|---|---:|
| no_ask | 55 |
| disagree | 57 |
| ask_too_high | 130 |
| too_close | 53 |
| net_too_small | 1 |

First skip: Gamma **5171532** Dallas **66-67°F** on **2026-10-03**,
Open-Meteo **74.2°F**, NOAA **77°F**, **NO**, slack **6.2°F**,
best_bid **0.999**, best_ask **null**.

Only `net_too_small`: Gamma **5174512** **NO** ask **0.84** net **0.14** slack **5.6°F**.

No second recipe.

---

## Still missing (do not invent)

- `DUNE_API_KEY`
- `DUNE_QUERY_IDS`
- `LUNARCRUSH_API_KEY`
- `CRYPTOPANIC_API_KEY`
- `PERPLEXITY_API_KEY`
- `ALTFINS_API_KEY`
