# PIT basis archives — UNAVAILABLE

Generated: 2026-09-12 (after #114). Paper / research only.

Requested construction: point-in-time **mark−index** or
**perp-mid−spot-mid** for Hyperliquid and/or BitMEX over **≥720**
days, timestamps that do not look ahead. Hyperliquid
`fundingHistory.premium` and BitMEX `.XBTUSDPI` remain forbidden.

**Result: UNAVAILABLE.** No skip-not-invent fetcher was wired. Carry
was **not** re-scored. `basis_status` stays `skipped`.
`can_promote` stays **false**. No `PAPER_PROMOTE_*` flip. No live.

Dual-print + hard gates + paper soak path remain true from #112/#114.
The last promote blocker is still historical PIT basis.

## What would have been wired

A fetcher only if a public archive returned the requested
construction for ≥720 days **without inventing credentials** and
without substituting last-trade, funding premium, or an illiquid
book for a mid. Paid / Tardis full history is out unless it is
freely usable here. Requester-pays S3 that rejects anonymous GET
is recorded, not pulled with invented AWS keys.

## Probes (this environment, 2026-09-12)

| source | path | HTTP / access | usable ≥720d mark−index or perp-mid−spot-mid? |
| --- | --- | --- | --- |
| Hyperliquid official S3 | `s3://hyperliquid-archive/asset_ctxs/YYYYMMDD.csv.lz4` | anonymous GET **403** (`Anonymous users cannot invoke requests against Requester Pays buckets. Please authenticate.`). `AWS_ACCESS_KEY_ID` unset; no `~/.aws` | **no** — docs + a 2026-04 blog claim daily files from 2023-05-20 (~1059 days by 2026-04-22) and live `metaAndAssetCtxs` fields include `markPx`/`oraclePx`/`midPx`, but this environment cannot read a single row. Do not invent AWS keys. Columns were **not** confirmed here. |
| Hyperliquid node S3 | `s3://hl-mainnet-node-data/` | anonymous GET **403** requester-pays | **no** — fills / replica cmds / misc events, not a mark−index tape we can read |
| Hydromancer Reservoir | `s3://hydromancer-reservoir` (`ap-northeast-1`) | anonymous GET **403** requester-pays | **no** — same credential bar; not pulled |
| Hyperliquid public REST | `POST /info` `metaAndAssetCtxs` / `fundingHistory` / `candleSnapshot` | reachable (already #113) | **no** — current snapshot only; `premium` is the funding-formula input; candles are last-trade |
| BitMEX public dump | `https://public.bitmex.com/` → `data/quote/`, `data/trade/`, `data/porl/` | list **200**; dated quote/trade files **200** (quote `20260911.csv.gz` 46 MB; trade same day 6 KB). `data/instrument/` and `data/funding/` **404** | **no** — dump is trade + top-of-book quote + proof-of-reserves. No mark-price / instrument history folder. Trade is last-trade. Quote can form a perp mid, which is not mark−index by itself |
| BitMEX REST quote + index | `quote/bucketed` XBTUSD + `.BXBT` / `.BETH` | **200** (already #113) | **no** — perp-mid−**index**, not mark−index and not perp-mid−**spot-mid**. Hyperliquid cannot pair it |
| BitMEX REST quote + spot | `quote/bucketed` `XBTUSDT`/`ETHUSDT` vs `XBT_USDT`/`ETH_USDT` | **200**; spot listed 2022-05-17 (calendar span >720d) | **no** — theoretically perp-mid−spot-mid, but the spot book is not a mid. Last 5 **1d** buckets: `XBT_USDT` spread **150–603 bps**; `ETH_USDT` **3473–3725 bps**. Using that mid would invent basis from an illiquid book. Skip |
| BitMEX REST instrument | `GET /instrument` | **200** | **no** — current `markPrice` / `indicativeSettlePrice` / `midPrice` only |
| BitMEX premium index | `trade/bucketed` `.XBTUSDPI` / `.ETHUSDPI` | **200** | **no** — funding-formula premium (same class as HL `premium`) |
| CryptoDataDownload | `/data/bitmex/` | **404** | **no** |
| HuggingFace `GregM/hyperliquid-perp-open-data` | planned `funding`/`open_interest` with `mark_price`+`index_price` | **200** card; schema only | **no** — "Initialized. Data publication starts after … sink is live." No parquet rows |
| HuggingFace other HL sets | fills / L2 inventory / 1m OHLCV samples | **200** | **no** — last-trade or L2 inventory, not a ≥720d mark−index. Tessera OHLCV is a one-month sample |
| Tardis | `datasets.tardis.dev` CSV paths; `api.tardis.dev/v1/data-feeds/*` | CSV paths **404** (HEAD). `hyperliquid` from 2024-10-29: **401** "unauthorized requests, only … first day of each month". HL history since 2024-10-29 is **~318d < 720** even if paid | **no** — not freely usable; do not invent an API key |
| Coin Metrics community | `/v4/timeseries/market-candles?markets=bitmex-XBTUSD-future` | **403** "not available with supplied credentials" | **no** |
| Allium / Kaiko / CryptoStruct | vendor historical | not probed beyond docs | **no** — paid; skipped |

## Honesty

- Do not treat requester-pays 403 as a downloaded series.
- Do not treat a 150–600 bps (ETH ~3500 bps) BitMEX spot book as
  perp-mid−spot-mid.
- Do not reconstruct mark from index × (1 + funding basis). That is
  circular with the carry we are trying to cost.
- `carry_hedged_sign` daily numbers in `funding-carry-daily.md`
  (HL WF +1.72% / BitMEX WF +2.55%) stay the **basis-unaware** model.
- `PAPER_CARRY_PATH_READY` is true only for the forward soak
  (`PAPER_PERP_HEDGE=true`). Snapshot mids are not this archive.

## Promotion decision

**No candidate is promoted.** PIT basis archives are UNAVAILABLE.
Leave every `PAPER_PROMOTE_*=false`. Do not add a new pin. Do not
enable live.

## Next falsifiable non-carry experiment

Do **not** re-run dead EMA dual-prints (#104 / `ema_9_21` /
`ema_9_21_adx15`). Do not re-run #105 liquidation, #106 Polymarket
weather, #108 4h non-EMA, or the 4h #110 funding print. Do not
re-score carry until a readable PIT series exists on **both**
dual-print venues without invented credentials.

**Propose: BTC−ETH relative-value residual** (new family, not
implemented this session).

| item | rule |
| --- | --- |
| Signal | Fade / follow the daily BTC minus ETH excess return at frozen \|z\| ≥ 1.0 / 1.5 / 2.0, plus an unconditioned `ma_cross_10_30` control. **Not** an EMA crossover catalog. |
| Costs | 10 + 5 bps (same paper bar). |
| Dual-print | Kraken public Spot **1d** 720 **and** the #102-style Binance.US older-720. Same #96+A+B+C combined gates. Venues are not averaged. |
| Paper path | Existing Kraken spot `paper_simulate_fills`. No perp book required. |
| Promote | Only if dual-print + hard gates + paper path all clear. Pin would still default **false**. Empty dual-print is success. |

Why this and not another carry reprint: carry is blocked on data we
do not have. BTC−ETH residual is a different bet, uses tapes this
repo already pulls, and fails closed if the older Binance.US print
does not confirm.

Runner-up (only if pair-residual is empty and a public historical
series exists): fee-aware **on-chain flow residual** (exchange inflow
/ stablecoin-supply z overlay) with skip-not-invent. Dune/DefiLlama
keys are not invented; missing series → empty print, not zeros.
