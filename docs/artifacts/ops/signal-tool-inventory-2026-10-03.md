# Signal-tool inventory (2026-10-03) — DeFi-TraderStack-Agent

Operator `.env` key names inspected; secret **values never printed**.
Process env had no relevant overrides. Code + `.env.example` cross-checked.

| Tool | Role | Configured? | Missing / gating env | What it can emit TODAY |
|---|---|---|---|---|
| Crucix (`market/crucix.py`) | News/narrative intel alerts → `NewsSnapshot` | **NO** | `CRUCIX_ENABLED` (false/absent), `CRUCIX_BASE_URL` (blank/absent), `CRUCIX_API_KEY` (absent) | Nothing — adapter must NOT register. **STOPPED.** |
| Dune (`intelligence_providers.DuneOnChainProvider`) | On-chain netflow / accumulation | **NO** | `DUNE_API_KEY`, `DUNE_QUERY_IDS` (empty) | Nothing |
| LunarCrush | Social sentiment | **NO** | `LUNARCRUSH_API_KEY` (absent from `.env`) | Nothing |
| CryptoPanic | News adversity | **NO** | `CRYPTOPANIC_API_KEY` (absent; plan alone is not enough) | Nothing |
| Perplexity Agent | News research snapshot | **NO** | `PERPLEXITY_API_KEY` (absent) | Nothing |
| altFINS | Technical signal feed score | **NO** | `ALTFINS_API_KEY` (absent) | Nothing |
| Open-Meteo (`polymarket/forecast.OpenMeteoClient`) | NWP daily high °F for weather markets | **YES** (public default URL) | none (optional `POLYMARKET_WEATHER_OPEN_METEO_BASE_URL`) | Daily high forecast points — **already emitted** on 2026-09-18 tape (`forecast_source=open_meteo`) |
| NOAA Weather.gov | Alternate NWP high | **YES** (public; User-Agent default) | none | Could emit if `POLYMARKET_WEATHER_FORECAST_PROVIDER=noaa`; not used on this tape |
| Polymarket Gamma + CLOB public | Market discovery + mids/book | **YES** (public defaults) | none | Events/markets/mids — used on tape |
| IEM ASOS (`polymarket/stations.py`) | Official station daily max °F | **YES** (public) | none | Station highs — used in resolve today |
| NCEI GHCN-Daily | Cross-check station max | **YES** (public) | none | Cross-check highs — used in resolve today |
| Coin Metrics community MVRV-Z | On-chain regime gate (#139) | URL yes; gate **OFF** | `ONCHAIN_REGIME_GATE_ENABLED=false` (default); no key needed for community API | Would emit MVRV-Z percentile if gate enabled; **not a Polymarket signal**; left off |
| Deribit public options | Crypto-wedge implied prob (#142) | URL yes | Crypto wedge also needs Crucix **clear**; Crucix not configured | Can fetch quotes, but trade mask stands aside (`not_configured`) — **not this test** |
| DefiLlama stablecoins | Stable circulating / net issuance research | **YES** (public `stablecoins.llama.fi`) | none for fetch | Research series only; live history **NOT_PIT_SAFE**; not wired as Polymarket signal |

## What we turned on

- Ran `traderstack-polymarket-weather-resolve` once (paper) against existing Open-Meteo PIT tape.
- Did **not** set `CRUCIX_ENABLED`, did **not** invent keys/URLs.
- Did **not** flip any `PAPER_PROMOTE_*` or live-trading flags (`TRADING_MODE=paper` already).

## Blocked on missing secrets

- Crucix: `CRUCIX_ENABLED`, `CRUCIX_BASE_URL`, `CRUCIX_API_KEY`
- Dune: `DUNE_API_KEY`, `DUNE_QUERY_IDS`
- LunarCrush: `LUNARCRUSH_API_KEY`
- CryptoPanic: `CRYPTOPANIC_API_KEY`
- Perplexity: `PERPLEXITY_API_KEY`
- altFINS: `ALTFINS_API_KEY`
