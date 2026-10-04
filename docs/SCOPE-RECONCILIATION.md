# Scope reconciliation — original charter vs current implementation

**Programme issue:** #191  
**Date:** 2026-10-04  
**Purpose:** distinguish *implemented in code* from *operational, collecting, persisted and usable for alpha discovery*.

## Executive finding

The project remains aligned with the original safety model, but it has drifted toward
strategy-catalog validation while the original data/intelligence flywheel is only
partially operational.

The charter's primary objective is to determine whether quantitative market features,
on-chain intelligence, social/news/world signals and bounded LLM reasoning can produce
persistent risk-adjusted alpha after realistic costs. The current repository has strong
validation and safety controls, but several intelligence adapters are not proven active
on the operator system, much research evidence remains in JSONL/report artifacts rather
than a queryable longitudinal feature store, and profitable-wallet/cohort intelligence
is not yet a first-class subsystem.

A capability is **not considered complete** merely because an adapter or parser exists.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| ACTIVE | Configured, reachable and demonstrated collecting useful data |
| IMPLEMENTED_NOT_PROVEN | Code exists; current operator-runtime collection not demonstrated |
| BLOCKED_CREDENTIAL | Runtime needs a credential/query id not currently evidenced as configured |
| BLOCKED_DATA | Code exists but the required point-in-time/history dataset is missing |
| RESEARCH_ONLY | Data/path exists but is intentionally not part of the trading decision path |
| DELIBERATELY_DISABLED | Available but off by policy/default |
| GAP | Original-scope capability is materially absent |
| RETIRED | Explicitly no longer part of the intended architecture |

## Capability map

| Original capability | Current implementation | Persistence today | Operational evidence | Status | Main gap / issue |
| --- | --- | --- | --- | --- | --- |
| Venue-native market data | Kraken WS/REST, reference adapters, cross-venue support | runtime JSONL; optional Postgres runtime events; candle store | Core paper path exercised | ACTIVE | Continue freshness/coverage health under #191 |
| Historical candles | Kraken, Coinbase, Binance Vision/archive tooling | research JSON / candle store depending path | Multi-year fetchers implemented; reachability has varied by environment | IMPLEMENTED_NOT_PROVEN | Prove scheduled collection + coverage |
| Funding / basis | Hyperliquid/HTX/OKX/Binance Vision research paths | research artifacts / tapes | Multiple fee-aware replays completed | ACTIVE | Finish independent basis coverage (#134) |
| Liquidations / OI / derivatives features | Partial research/edge-data paths | feature/runtime artifacts | Not a unified long-history store | IMPLEMENTED_NOT_PROVEN | #192; provider health |
| Dune on-chain | `DuneOnChainProvider` expects configured query ids | runtime feature snapshot only when enabled | 2026-10-03 inventory reported no key/query ids | BLOCKED_CREDENTIAL | #191; expand beyond two precomputed fields |
| Large-wallet accumulation | Dune field `large_wallet_accumulation` | feature snapshot only | No wallet-level history/cohort system | GAP | #193 plus #192 |
| Profitable-wallet discovery | No first-class wallet ranking/cohort engine | none | None | GAP | #193 |
| DEX pool / wallet-flow microstructure | Robinhood Chain + proposed pool work | limited runtime/research evidence | Partial | IMPLEMENTED_NOT_PROVEN | #77, #192 |
| Social narrative | LunarCrush adapter | runtime feature snapshot only when enabled | 2026-10-03 inventory reported no key | BLOCKED_CREDENTIAL | #191, #192 |
| Crypto news | CryptoPanic adapter | runtime feature snapshot only when enabled | 2026-10-03 inventory reported no key | BLOCKED_CREDENTIAL | #191, #192 |
| Perplexity news/research | Provider exists | runtime feature snapshot only when enabled | 2026-10-03 inventory reported no key | BLOCKED_CREDENTIAL | #191, #192 |
| altFINS | Provider exists | runtime feature snapshot only when enabled | 2026-10-03 inventory reported no key | BLOCKED_CREDENTIAL | #191, #192 |
| Crucix | Adapter now maps live `/api/data` without inventing a signal; legacy alerts supported | runtime news snapshot when configured; no longitudinal world-event store | Adapter integration merged in #194; operator activation still must be proved | IMPLEMENTED_NOT_PROVEN | #191, #192, #193 |
| Coin Metrics regime | Community provider / opt-in regime gate | runtime feature snapshot | Gate default off | DELIBERATELY_DISABLED | Decide research value under #191 |
| DefiLlama | Stablecoin/PIT research helpers | research artifacts | Public source; historical PIT limitations documented | RESEARCH_ONLY | Persist safe observations under #192 |
| CoinGecko / CMC references | Reference-price adapters | runtime events | Used as market-data references where configured | ACTIVE | Provider-health audit under #191 |
| Polymarket Gamma/CLOB | Weather + crypto-threshold collectors | JSONL research tapes under `var/audit/` | Live GET-only collection demonstrated | ACTIVE | Move to durable queryable warehouse (#192) |
| Polymarket weather | Open-Meteo/NOAA + station resolution | JSONL + committed reports | Real resolved single-print evidence exists; not profitable proof | RESEARCH_ONLY | Treat as one module under #193 |
| Polymarket crypto threshold | Gamma/CLOB + Deribit probability wedge | JSONL crypto wedge tape | Collector reached Gamma/CLOB/Deribit; Crucix previously stood aside | RESEARCH_ONLY | Treat as one module under #193 |
| Polymarket wallet intelligence | No proper live/historical wallet-cohort path | none | None | GAP | #193 |
| Deribit options reference | Public option-chain client for crypto wedge | JSONL wedge tape / reports | Live public endpoint exercised | ACTIVE | Generalise as one external probability source |
| Cross-prediction-market comparison | Not first-class | none | None | GAP | Research in #193 where economically comparable |
| Weather/NWP | Open-Meteo + NOAA paths | weather tapes | Live Open-Meteo tape and resolution evidence | ACTIVE | Broader category evidence, calibration |
| LLM/meta-agent | Constrained reviewer and specialist architecture | audit/runtime events | Implemented with bounded authority | IMPLEMENTED_NOT_PROVEN | Measure incremental value (#72) |
| Pattern discovery | Governed design exists in #57 | no mature shared feature warehouse | Not operating as continuous discovery loop | GAP | #192 then #57 |
| Longitudinal feature/signal store | Postgres runtime events + candle store exist; no first-class normalized provider/feature warehouse | fragmented Postgres + JSONL + reports | Partial | GAP | #192 |
| Reproducible audit trail | JSONL runtime + hash-chained risk audit + reports | durable local files; optional Postgres events | Strong evidence | ACTIVE | Preserve alongside #192 warehouse |
| Paper execution | Paper runtime / Hummingbot integration / fee-aware reporting | execution ledger + audit | Substantial evidence | ACTIVE | Remaining live-readiness issues |
| Shadow/live promotion | Shadow issue/backlog and strict live deferral | n/a | Live intentionally blocked | DELIBERATELY_DISABLED | #46 and remaining safety blockers |

## Data-persistence reality

The HLD describes PostgreSQL for durable state, a time-series feature/signal store,
Redis for ephemeral state, and reproducible research datasets.

The repo currently has useful persistence primitives:

- `PostgresRuntimeEventStore`;
- `PostgresCandleStore`;
- optional `--persistent-events`;
- Redis publication/cache/state paths;
- runtime and risk JSONL audit trails;
- Polymarket and other research JSONL tapes;
- committed research reports/artifacts.

However, there is not yet one durable point-in-time warehouse that lets research ask:

> What did the system know at time T across market, wallet, on-chain, news,
> Crucix, social, derivatives and prediction-market sources, and what happened
> after T?

That is the purpose of #192. JSONL/hash-chain audit outputs should remain independent
evidence and must not be removed when the warehouse is added.

## Alpha-discovery priority

Until #191–#193 establish the data flywheel, further research should prefer:

1. activating and measuring existing resources;
2. accumulating point-in-time data;
3. wallet/cohort and world-signal research on Polymarket;
4. rescoring existing frozen hypotheses only when genuinely new data is available;
5. governed pattern discovery (#57) against the shared warehouse.

Avoid adding more isolated strategy-family variants solely because an earlier family
failed. New strategy work should have a distinct economic mechanism or new information source.

## Immediate operator-resource audit

The last committed/operator evidence indicates these need explicit re-verification on
the actual runtime:

| Provider | Required evidence |
| --- | --- |
| Crucix | configured? reachable? `/api/data` valid? last success? collection destination? |
| Dune | key + query ids? auth valid? rows/day? query provenance? |
| LunarCrush | key? auth/plan valid? rows/day? |
| CryptoPanic | key/plan? auth valid? rows/day? |
| Perplexity | key? request path valid? cost/quota? rows/day? |
| altFINS | key? endpoint/plan valid? rows/day? |
| Coin Metrics | intentionally off vs active research collection |
| DefiLlama | collector schedule actually running and PIT-safe fields persisted |
| Polymarket | weather + crypto collectors scheduled, not only manually invoked |
| Deribit | collection freshness and coverage alongside Polymarket markets |

The `traderstack-resource-audit` work in #191 should make this machine-readable and
must never print credential values.

## Programme dependencies

```text
#191 scope/resource truth
        |
        v
#192 longitudinal signal warehouse
        |
        +--------> #57 governed pattern discovery
        |
        v
#193 Polymarket wallet + world-signal programme
        |
        v
paper validation -> shadow validation -> controlled live-capital gates
```

Execution/risk/security blockers remain prerequisites for live capital regardless of
research success.

## Definition of restored direction

The project is back on the original path when all of the following are true:

- every intended provider is explicitly ACTIVE, DELIBERATELY_DISABLED or BLOCKED with reason;
- active collectors have freshness and volume health;
- useful raw/normalized observations accumulate durably with point-in-time provenance;
- historical queries can reconstruct what was knowable at decision time;
- wallet/on-chain/world-event information is first-class research data;
- #57 can search the same governed warehouse and produce reproducible hypotheses;
- Polymarket research combines market microstructure, wallet behaviour and external/world signals;
- promotion still requires holdout, realistic costs, paper/shadow evidence and deterministic risk controls.
