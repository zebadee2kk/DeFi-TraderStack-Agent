# Funding / carry — PIT basis probe

Generated: 2026-09-12 (after #112). Paper / research only.

`basis_status=skipped`. Historical PIT basis remains UNAVAILABLE.
`paper_path_ready=true` for the forward paper soak only (after the
cycle-wired hedge+funding path). `can_promote=false`.
`keep_flag_false=true`. No `PAPER_PROMOTE_*` flip. No live.

## What was requested

A point-in-time **mark−index** or **perp-mid−spot-mid** series on
**both** Hyperliquid and BitMEX, with timestamps that do not look
ahead. Hyperliquid `fundingHistory.premium` is not basis.

`carry_hedged_sign` is re-scored with basis **only when that series
is present**. It is not present. The committed daily numbers in
`funding-carry-daily.md` (HL WF +1.72% / BitMEX WF +2.55%) stay the
basis-unaware model. This file does not invent a replacement PnL.

## Probe (this environment, 2026-09-12)

| venue | public path | result |
| --- | --- | --- |
| Hyperliquid | `POST /info` `metaAndAssetCtxs` | **current only** — BTC `markPx` 77130 / `oraclePx` 77172.1 / `midPx` 77129.5; ETH `markPx` 2524.3 / `oraclePx` 2525.43. No historical REST |
| Hyperliquid | `POST /info` `fundingHistory` | hourly `fundingRate` + `premium` — **not used** (`premium` is the funding-formula input) |
| Hyperliquid | `POST /info` `candleSnapshot` | last-trade OHLC — **not used** (last-trade is not mid) |
| BitMEX | `GET /api/v1/instrument` | **current only** — XBTUSD `markPrice` 77156.96 / `indicativeSettlePrice` 77155.45 / `midPrice` 77137.4 |
| BitMEX | `GET /api/v1/trade/bucketed` `.XBTUSDPI` / `.ETHUSDPI` | historical premium index (1d close −0.000299 on 2026-09-12) — **not used** (same class as HL premium) |
| BitMEX | `GET /api/v1/quote/bucketed` + `.BXBT` / `.BETH` | perp quote mid and composite index — **not wired**. That is perp-mid−index, not mark−index and not perp-mid−spot-mid. Hyperliquid cannot pair it |

Adapters: `fetch_hyperliquid_basis`, `fetch_bitmex_basis`. Both
return `status=skipped`. `traderstack-funding-carry --live` records
the notes. Dual-print basis requires the requested construction on
**both** venues.

## Paper perp / hedge stub (#113)

`execution/paper_perp.py` is paper-only. Kill switch withholds new
hedges. Funding is applied only from caller-supplied settlements.
A hedge requires an explicit perp mid — the Kraken spot mid is not
substituted. `PAPER_PERP_HEDGE` defaults **false**. After #113 the
cycle still passed `perp_mid_usd=None`, so production hedges skipped
and `PAPER_CARRY_PATH_READY` stayed **false**.

## Paper hedge+funding soak path (after #113)

`execution/paper_perp_feed.py` fetches a **current** Hyperliquid
`midPx` and/or BitMEX `midPrice` (never `markPx` / last-trade /
premium, never the Kraken spot mid) and recent public funding
settlements from the **same** venue. When `PAPER_PERP_HEDGE=true`
and `TRADING_MODE=paper`, the cycle passes that mid into
`PaperPerpBook` and applies new settlements on a schedule.

Those snapshot mids are **not** written into
`traderstack-funding-carry` scoring. Wiring live mids into the
historical window would invent a PIT series that the venues do not
publish. Research `basis_status` stays **skipped**.

`PAPER_CARRY_PATH_READY` is **true** for the forward soak (hedge +
funding exercised with real mid+funding inputs). `can_promote`
stays **false** while historical PIT basis is UNAVAILABLE.
`PAPER_PERP_HEDGE` still defaults **false**.

## Archive follow-up (after #114)

Public historical archives were probed 2026-09-12. **Still
UNAVAILABLE.** Official Hyperliquid `asset_ctxs` is requester-pays
(anonymous 403; no AWS keys invented). BitMEX `public.bitmex.com`
is trade+quote only (no mark dump). BitMEX perp-mid−spot-mid via
`XBTUSDT`−`XBT_USDT` is calendar-long enough but the spot book is
150–600 bps (ETH ~3500 bps) and is not used. Tardis / Coin Metrics
community / empty HuggingFace schemas were skipped. Carry was
**not** re-scored. See `pit-basis-archives.md`.

## Archive re-hunt (after #123)

Public archives were probed again 2026-09-12 after the empty
#123 volume-confirmed breakout print (0 dual-print passers).
**Dual-print basis still UNAVAILABLE.** Hyperliquid now has a
readable ≥720d mark−index tape on HuggingFace
(`asiletto81/hyperliquid` `asset_ctxs`, 883 contiguous days,
`mark_px`/`oracle_px` confirmed; no AWS keys). BitMEX public
dump prefixes `data/instrument/` / `data/mark/` list 200 but
are empty. BitMEX spot books are still 150–600 / ~3500 bps.
Tardis first-of-month `derivative_ticker` has mark+index on
both venues and is not a ≥720d daily tape. No fetcher was
wired. Carry was **not** re-scored. See
`pit-basis-archives.md`.

## Promotion decision

**No candidate is promoted.** PIT basis is UNAVAILABLE. The paper
soak path does not unlock a pin. Leave every
`PAPER_PROMOTE_*=false`. Do not add a new pin. Do not enable live.
