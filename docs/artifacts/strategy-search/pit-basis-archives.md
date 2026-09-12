# PIT basis archives — UNAVAILABLE

Generated: 2026-09-12 (after #123). Paper / research only.

Requested construction: point-in-time **mark−index** or
**perp-mid−spot-mid** for Hyperliquid and/or BitMEX over **≥720**
days, timestamps that do not look ahead. Hyperliquid
`fundingHistory.premium` and BitMEX `.XBTUSDPI` remain forbidden.

**Result: UNAVAILABLE** for dual-print basis. No skip-not-invent
fetcher was wired. Carry was **not** re-scored.
`basis_status` stays `skipped`. `can_promote` stays **false**.
No `PAPER_PROMOTE_*` flip. No live.

#123 volume-confirmed breakout dual-print passers: **0** (empty;
pins stay false). Do not re-run that catalog.

Dual-print + hard gates + paper soak path remain true from
#112/#114. The last promote blocker is still historical PIT basis
on **both** dual-print venues.

This re-hunt found a **new** public Hyperliquid mark−index tape
that clears ≥720 contiguous days (`asiletto81/hyperliquid`
`asset_ctxs`, 2024-01-01 → 2026-06-01, 883 days, columns
`mark_px`/`oracle_px` confirmed). BitMEX still has no matching
free tape. Dual-print basis therefore stays blocked. Do not
invent the BitMEX series. Do not stitch Tardis first-of-month
samples into a daily tape. Do not invent AWS keys.

## What would have been wired

A fetcher only if a public archive returned the requested
construction for ≥720 days **on both venues** (or one venue plus
a documented free path to the second) **without inventing
credentials** and without substituting last-trade, funding
premium, or an illiquid book for a mid. Paid / Tardis full
history is out unless it is freely usable here. Requester-pays
S3 that rejects anonymous GET is recorded, not pulled with
invented AWS keys.

## Probes (#115, this environment, 2026-09-12)

| source | path | HTTP / access | usable ≥720d mark−index or perp-mid−spot-mid? |
| --- | --- | --- | --- |
| Hyperliquid official S3 | `s3://hyperliquid-archive/asset_ctxs/YYYYMMDD.csv.lz4` | anonymous GET **403** (`Anonymous users cannot invoke requests against Requester Pays buckets. Please authenticate.`). `AWS_ACCESS_KEY_ID` unset; no `~/.aws` | **no** — docs + a 2026-04 blog claim daily files from 2023-05-20 (~1059 days by 2026-04-22) and live `metaAndAssetCtxs` fields include `markPx`/`oraclePx`/`midPx`, but this environment cannot read a single row. Do not invent AWS keys. Columns were **not** confirmed here. |
| Hyperliquid node S3 | `s3://hl-mainnet-node-data/` | anonymous GET **403** requester-pays | **no** — fills / replica cmds / misc events, not a mark−index tape we can read |
| Hydromancer Reservoir | `s3://hydromancer-reservoir` (`ap-northeast-1`) | anonymous GET **403** requester-pays | **no** — same credential bar; not pulled |
| Hyperliquid public REST | `POST /info` `metaAndAssetCtxs` / `fundingHistory` / `candleSnapshot` | reachable (already #113) | **no** — current snapshot only; `premium` is the funding-formula input; candles are last-trade |
| BitMEX public dump | `https://public.bitmex.com/` → `data/quote/`, `data/trade/`, `data/porl/` | list **200**; dated quote/trade files **200**. `data/instrument/` and `data/funding/` **404** at #115 | **no** — dump is trade + top-of-book quote + proof-of-reserves. No mark-price / instrument history folder. Trade is last-trade. Quote can form a perp mid, which is not mark−index by itself |
| BitMEX REST quote + index | `quote/bucketed` XBTUSD + `.BXBT` / `.BETH` | **200** (already #113) | **no** — perp-mid−**index**, not mark−index and not perp-mid−**spot-mid**. Hyperliquid cannot pair it |
| BitMEX REST quote + spot | `quote/bucketed` `XBTUSDT`/`ETHUSDT` vs `XBT_USDT`/`ETH_USDT` | **200**; spot listed 2022-05-17 (calendar span >720d) | **no** — theoretically perp-mid−spot-mid, but the spot book is not a mid. Last 5 **1d** buckets: `XBT_USDT` spread **150–603 bps**; `ETH_USDT` **3473–3725 bps**. Using that mid would invent basis from an illiquid book. Skip |
| BitMEX REST instrument | `GET /instrument` | **200** | **no** — current `markPrice` / `indicativeSettlePrice` / `midPrice` only |
| BitMEX premium index | `trade/bucketed` `.XBTUSDPI` / `.ETHUSDPI` | **200** | **no** — funding-formula premium (same class as HL `premium`) |
| CryptoDataDownload | `/data/bitmex/` | **404** | **no** |
| HuggingFace `GregM/hyperliquid-perp-open-data` | planned `funding`/`open_interest` with `mark_price`+`index_price` | **200** card; schema only | **no** — "Initialized. Data publication starts after … sink is live." No parquet rows |
| HuggingFace other HL sets | fills / L2 inventory / 1m OHLCV samples | **200** | **no** — last-trade or L2 inventory, not a ≥720d mark−index. Tessera OHLCV is a one-month sample |
| Tardis | `datasets.tardis.dev` CSV paths; `api.tardis.dev/v1/data-feeds/*` | CSV paths **404** (HEAD). `hyperliquid` from 2024-10-29: **401** "unauthorized requests, only … first day of each month". HL history since 2024-10-29 is **~318d < 720** even if paid (as of #115) | **no** — not freely usable; do not invent an API key |
| Coin Metrics community | `/v4/timeseries/market-candles?markets=bitmex-XBTUSD-future` | **403** "not available with supplied credentials" | **no** |
| Allium / Kaiko / CryptoStruct | vendor historical | not probed beyond docs | **no** — paid; skipped |

## Re-hunt probes (this environment, 2026-09-12, after #123)

New sources and re-checks. Do not treat a 403 / empty prefix / first-of-month sample as a ≥720d tape.

| source | path | HTTP / access | usable ≥720d mark−index or perp-mid−spot-mid? |
| --- | --- | --- | --- |
| HuggingFace `asiletto81/hyperliquid` | `asset_ctxs/YYYYMMDD.csv.lz4` (883 files) | GET **200**; lz4 magic `\x04"M\x18`; decompressed CSV | **HL only — yes, ≥720d mark−index**. Calendar **2024-01-01 → 2026-06-01**, **883 contiguous days, 0 gaps**. Header `time,coin,funding,open_interest,prev_day_px,day_ntl_vlm,premium,oracle_px,mark_px,mid_px,impact_bid_px,impact_ask_px`. BTC+ETH minute rows present (2024-01-01 BTC `mark_px` 42330 / `oracle_px` 42284; ETH 2284.6 / 2282; 2026-06-01 BTC 73654 / 73679). This is official `asset_ctxs` shape, not last-trade. **BitMEX cannot pair it.** Not wired: dual-print basis still needs the same construction on BitMEX. Ends 2026-06-01, so the current Kraken 720 (2024-09-22 → 2026-09-11) would align only ~617 days — the *archive* is still ≥720d |
| HuggingFace `Chainticks/perp-data` | `_manifest.json` + `hyperliquid_chain/funding/date=*/part-*.parquet` | LATEST_DATE **200** (`2026-08-11`); manifest **200**; parquet GET **200**; datasets-server rows **200** | **no ≥720d**. Columns are the requested construction (`mark_price`/`index_price`; `raw_json.mark_px`/`oracle_px`; `source_kind=hypercore_s3`). Longest contiguous run **2023-05-20 → 2024-04-28 (345d)** then stray single days in 2026. 352 unique funding dates over a 1170d calendar (818 missing). GregM twin repos still `status=initialized`, `files=[]` |
| HuggingFace `GregM/hyperliquid-perp-open-data` / `GregM/perp-data` | `_manifest.json` | **200**; `files: []` | **no** — still schema-only. Sample parquet path **404** |
| HuggingFace other HL dumps | `gionuibk/hyperliquid-data` (Nautilus last-trade bars); `gionuibk/hyperliquidL2Book-v2` (L2/candles from 2026-06); `gionuibk/hyperliquid-node-fills-by-block` (fills); `tessera-analytics/hyperliquid-ohlcv-1m` (2026-08 last-trade sample); `PhysiAI/HyperLiquid-Crawl` (empty test) | **200** | **no** — last-trade, L2 inventory, fills, or empty. Not mark−index. HF search `bitmex` datasets: **[]** |
| Official HL / node / Hydromancer S3 | same requester-pays paths as #115 | anonymous GET **403** | **no** — Do not invent AWS keys. 403 is not a downloaded series |
| BitMEX public dump prefixes | `data/`, `data/instrument/`, `data/funding/`, `data/mark/`, `data/liquidation/`, `data/fairPrice/`, `data/index/` | list **200** | **no** — root still only `data/quote/`, `data/trade/`, `data/porl/`. New prefixes are **empty** (0 Contents). Quote ≠ mark−index |
| BitMEX REST `instrument` + `startTime`/`endTime` | `GET /instrument?symbol=XBTUSD&startTime=2024-01-01&endTime=2024-01-02` | **200** `[]` | **no** — filter does not return historical mark snapshots |
| BitMEX REST `compositeIndex` | `GET /instrument/compositeIndex?symbol=.BXBT` | **200** | **no** — current index constituents (e.g. KRAK last), not a mark−index tape |
| BitMEX spot liquidity re-check | `quote/bucketed` 1d `XBT_USDT` / `ETH_USDT` vs liquid perps | **200** | **no** — still not a mid. Last 5 1d: `XBT_USDT` **150–603 bps**; `ETH_USDT` **3472–3725 bps**. Perp books are tight (`XBTUSD` ~2 bps; `XBTUSDT` ~1 bps) but spot is the other leg. Skip |
| Tardis first-of-month CSV (no key) | `datasets.tardis.dev/v1/{hyperliquid,bitmex}/derivative_ticker/…` | **200** gzip CSV | **columns are mark−index** (`index_price,mark_price` on both venues) but **first calendar day of each month only**. HL catalog `availableSince=2024-10-29` (~683d by 2026-09-12, still **<720** even if paid). Full history **401/unauthorized** without a key. Do not invent a Tardis key. Do not treat ~12 samples/year as a ≥720d daily tape |
| Tardis BitMEX `instrument` CSV | `…/bitmex/instrument/2024/01/01/XBTUSD.csv.gz` | **400** invalid `dataType` | **no** — allowed types are trades/quotes/derivative_ticker/… |
| Coin Metrics community | catalog + `market-candles` `bitmex-XBTUSD-future` | catalog **200** `data=[]`; candles **403** | **no** — still not available with supplied (empty) credentials |
| AlgoTick documented HTTP / R2 | `algotick.dev/v2/history/raw?dataset=funding&coin=BTC&date=2026-08-28`; `s3://algotick-data-lake/…` | HTTP **404**; S3 **NoSuchBucket** | **no** — docs claim `mark_price` only (no index). Endpoint not populated here |
| Dune `hyperliquid.market_data` | `GET /api/v1/query/5720613/results` (no key) | **401** `invalid API Key` | **no** — schema has `mark_px`/`oracle_px` but the API requires a key. Do not invent one |
| L1ticks | `https://l1ticks.com/` | TLS **UNEXPECTED_EOF** | **no** — paid microstructure dump; not reached |
| Zenodo `bitmex mark price` | `/api/records?q=…` | **200** | **no** — hits are equity-futures / medical / hospitality papers, not BitMEX mark |
| CryptoDataDownload `/data/bitmex/` / `/cdd/` | same | **404** | **no** |
| Binance Vision markPriceKlines / Binance `premiumIndex` | not a dual-print venue | Vision prefix **404**; REST **451** | **no** — not Hyperliquid or BitMEX; geo-blocked here |

## Honesty

- Do not treat requester-pays 403 as a downloaded series.
- Do not treat a 150–600 bps (ETH ~3500 bps) BitMEX spot book as
  perp-mid−spot-mid.
- Do not reconstruct mark from index × (1 + funding basis). That is
  circular with the carry we are trying to cost. BitMEX support docs
  publish that formula; it stays forbidden.
- Do not stitch Tardis first-of-month `derivative_ticker` rows into
  a daily basis series.
- `asiletto81/hyperliquid` is a real HL mark−index archive. It does
  **not** unlock dual-print basis by itself.
- `carry_hedged_sign` daily numbers in `funding-carry-daily.md`
  (HL WF +1.72% / BitMEX WF +2.55%) stay the **basis-unaware** model.
- `PAPER_CARRY_PATH_READY` is true only for the forward soak
  (`PAPER_PERP_HEDGE=true`). Snapshot mids are not this archive.

## Promotion decision

**No candidate is promoted.** Dual-print PIT basis archives are
UNAVAILABLE (BitMEX still missing). Leave every
`PAPER_PROMOTE_*=false`. Do not add a new pin. Do not
enable live. No `PAPER_PROMOTE_*` flip.

## Operator recommendation

Still blocked. Next concrete promote gate remaining: a public
≥720d **BitMEX** mark−index or liquid perp-mid−spot-mid tape
that this environment can GET without invented AWS / Tardis /
Dune / Coin Metrics keys. When that exists, wire skip-not-invent
on **both** venues (HL path: `asiletto81/hyperliquid` `asset_ctxs`)
and re-score `carry_hedged_sign` with basis costs. Until then
do not flip `PAPER_PROMOTE_*`.

Do **not** re-run candle dual-print catalogs #104 / #108 /
#116–#123 on the same Kraken 720 + Binance.US older-720 windows
(`ema_9_21` / `ema_9_21_adx15` stay default **false**). Do not
re-score carry on HL `premium` or BitMEX `.XBTUSDPI`.

The #115 proposed **BTC−ETH relative-value residual** was run
in #116 (0 dual-print passers). Later empty prints: #117 XS,
#118 Donchian, #119 TSMOM, #120 Bollinger, #121 calendar,
#122 lead-lag, **#123 volume-confirmed breakout (0 passers)**.
Those families stay closed on the same windows.
