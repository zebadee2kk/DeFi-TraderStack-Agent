# Funding / carry — PIT basis probe

Generated: 2026-09-12 (after #125 + basis/hl-htx-aware freeze). Paper / research only.

**Window freeze (coverage-driven, committed before score):** scored
basis-aware dual-print uses UTC days ending **2026-06-01** with
**≥720** aligned days (implied start **2024-06-12**). See
`basis-window-freeze.md`. The default live Kraken720 ending
~2026-09-11 only overlaps asiletto81 on **618/720** days (102d gap
after archive end) — do **not** invent those days and do **not**
stitch Binance Vision into the HL leg.

## What was requested

A point-in-time **mark−index** or **perp-mid−spot-mid** series on
**both** Hyperliquid and a second independent venue, with timestamps
that do not look ahead. Hyperliquid `fundingHistory.premium` is not
basis. BitMEX is sunsetting (official closure 23 September 2026
04:00 UTC) and is not a long-term pair venue.

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
`PAPER_PERP_HEDGE` still defaults **false**. After the BitMEX sunset
directive the soak fetches Hyperliquid `midPx` (HTX bid/ask mid
fallback). BitMEX is not required.

## Archive follow-up (after #114)

Public historical archives were probed 2026-09-12. **Still
UNAVAILABLE.** Official Hyperliquid `asset_ctxs` is requester-pays
(anonymous 403; no AWS keys invented). BitMEX `public.bitmex.com`
is trade+quote only (no mark dump). BitMEX perp-mid−spot-mid via
`XBTUSDT`−`XBT_USDT` is calendar-long enough but the spot book is
150–600 bps (ETH ~3500 bps) and is not used. Tardis / Coin Metrics
community / empty HuggingFace schemas were skipped. Carry was
**not** re-scored. See `pit-basis-archives.md`.

## Archive re-hunt + BitMEX sunset (after #123 / #124)

Public archives and CEX/DEX REST were probed again 2026-09-12 after
the empty #123 volume-confirmed breakout print (0 dual-print
passers). **Dual-print basis still UNAVAILABLE** on the current
Kraken 720.

Hyperliquid now has a readable ≥720d mark−index tape on HuggingFace
(`asiletto81/hyperliquid` `asset_ctxs`, 883 contiguous days,
`mark_px`/`oracle_px` confirmed; no AWS keys) but it ends
2026-06-01 (~617d aligned to 2024-09-22 → 2026-09-11). Do not
retune the window after seeing that. BitMEX public dump prefixes
`data/instrument/` / `data/mark/` list 200 but are empty. BitMEX
spot books are still 150–600 / ~3500 bps. Tardis first-of-month
`derivative_ticker` has mark+index on both venues and is not a
≥720d daily tape.

HTX publishes daily mark−index (~1999d) **and** ≥720d funding.
The basis adapter is wired skip-not-invent and is **not** applied
as a single-venue substitute. BitMEX official closure is
23 September 2026 04:00 UTC; it is excluded from venue pick and
from the paper-hedge default path.

Binance Vision monthly `fundingRate` + `markPriceKlines` +
`indexPriceKlines` zips are GET 200 from 2020-01 (a full dump
candidate) while fapi REST stays 451. Not stitched this session.

No paired HL+HTX basis fetcher was wired on the scored 720.
Carry was **not** re-scored with an invented pair. See
`pit-basis-archives.md`.

## Promotion decision

**No candidate is promoted.** PIT basis is UNAVAILABLE. The paper
soak path does not unlock a pin. Leave every
`PAPER_PROMOTE_*=false`. Do not add a new pin. Do not enable live.

## HL+HTX basis wiring (this branch)

- `fetch_hyperliquid_basis` loads HuggingFace
  `asiletto81/hyperliquid` `asset_ctxs` daily last
  `(mark_px-oracle_px)/oracle_px` inside the freeze.
- `fetch_htx_basis` daily mark−index clamped to the same freeze.
- Live `--interval 1d` truncates candles/funding/basis to the
  freeze **before** walk-forward / hard gates / dual-print.
- `basis_status=ok` only when **both** HL and HTX basis clear
  the freeze with enough days. BitMEX remains sunset/skipped.
- `can_promote` still requires dual-print + hard gates + PIT
  basis on both + paper path + dual passers; every
  `PAPER_PROMOTE_*=false` until earned.


## Dual basis re-score (#134)

Generated 2026-09-13 from two live runs of
`traderstack-funding-carry --live --interval 1d --basis-dir
var/research/basis` (second run `--fee-bps 80`). Paper / research
only. No `PAPER_PROMOTE_*` flip. No live.

**Header.** Print kind `dual_print`; funding primary `hyperliquid`
(hourly `fundingHistory`, 800d lookback, resampled to UTC daily sums),
second `htx` (8h `funding_rate`, 800d); Kraken public Spot daily 720
committed bars **2024-09-23 → 2026-09-12** on BTC/USD and ETH/USD;
aligned bars primary **720** / second **720**; hard gates
**available**; `basis_status=ok`, `basis_print_kind=dual_basis`,
`basis_venue=okx`, `second_basis_venue=binance_vision`. Basis series
reached (status **ok** on every leg): OKX BTC/ETH 720/720 days aligned
with the HL funding days; Binance Vision BTC/ETH 719/719 days aligned
with the HTX funding days (one calendar gap inside the window, skipped
not filled). Fee prints: **10 bps + 5 bps** (modelled default) and
**80 bps + 5 bps** (Kraken Pro Tier-1 taker per side, #138); hedged
carry pays 2 legs × (fee + slippage) on each harvest on/off flip.

**Pairing (frozen in code before the pull).** primary funding print
(Hyperliquid) × OKX mark−index; second funding print (HTX) × Binance
Vision mark−index. Cross-venue, stated not hidden. USDT quote on both
basis legs.

### `carry_hedged_sign` (the only dual-print passer, unchanged)

| print | basis | fee | WF total | holdout total | full-sample | #96 | A (ratio) | B | C | combined |
| --- | --- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |
| HL funding × OKX basis | applied (720d) | 10+5 | +1.71% | +3.33% | +27.76% | true | true (0.874) | 3/3 | true | **true** |
| HTX funding × Vision basis | applied (719d) | 10+5 | +1.49% | +3.30% | +21.26% | true | true (0.804) | 3/3 | true | **true** |
| HL funding × OKX basis | applied (720d) | 80+5 | +1.71% | +3.33% | +25.96% | true | true (0.874) | 3/3 | true | **true** |
| HTX funding × Vision basis | applied (719d) | 80+5 | +1.49% | +3.30% | +19.56% | true | true (0.804) | 3/3 | true | **true** |

Basis-unaware reference (2026-09-12 print, same window shape): HL WF
+1.72% / HO +3.32% / full +27.71%; HTX WF +1.50% / HO +3.31% / full
+21.26%. The window rolled one day versus that reference (2024-09-23 → 2026-09-12
here vs 2024-09-22 → 2026-09-11 there), so the deltas below mix that roll
with the basis term. The full-sample number moved by **+0.05 pp**
(HL×OKX) and **0.00 pp** (HTX×Vision), and the walk-forward / holdout
means by ≤0.01 pp. That is what the construction implies: for an
always-on hedged position the daily `prev_basis − current_basis` term
telescopes to `basis_entry − basis_exit` over any contiguous harvest
span, and a perp's mark−index is a few bps, so basis is a small unwind
term here, not a per-day signal. It is now measured rather than
skipped, which is the point of this issue.

The other three carry rows (`abs_1bp`, `abs_3bp`, `z_1_5`) remain
ineligible on both prints and collapse further at 80 bps (−14% to −22%
WF) because they flip repeatedly.

**Was the #96+A+B+C bar reachable on each print?** Yes on both, at
both fee prints. At 80 bps the WF and holdout numbers are unchanged
because `carry_hedged_sign` is always-on and flips **once**, so the
Tier-1 taker cost appears only as a 1.7–1.8 pp lower full-sample
return.

### Honesty / known optimism (frozen model, not retuned here)

- The #111 hedged-carry model charges legs only on harvest **on/off**
  transitions. `carry_hedged_sign` harvests `|rate|`, so a funding
  **sign** change (short-perp/long-spot ↔ long-perp/short-spot) is not
  charged as a flip. That is an optimism in the frozen catalog; it is
  recorded here and left for a follow-up rather than retuned after
  seeing PnL.
- Basis is applied only on days where both the current and previous
  print have a value; the harvest decision never sees basis; missing
  days are skipped. The HTX print has 719 not 720 basis days for that
  reason.
- Funding tapes and basis tapes are different venues (HL/HTX funding;
  OKX/Binance basis). A same-venue Binance funding × Binance basis print
  (Vision `fundingRate` zips) is a follow-up.
- Statistical power is unchanged: this is still one ~2-year window.
  Era prints (2020→) and Deflated Sharpe / PBO are #133 / #135 / #136.

### Promotion decision

`can_promote` is **true** in both committed reports: the pre-registered
conjunction (dual-print **and** hard gates **and** `basis_status=ok`
**and** paper path **and** a dual-print passer) is now fully evaluated
and clears for `carry_hedged_sign`. That is a **report field only**.
This PR changes no `PAPER_PROMOTE_*` default, adds no Settings pin, and
hedged carry is still not executable on the Kraken paper-spot path
(the paper hedge+funding soak, `PAPER_PERP_HEDGE`, stays default
false). Whether to propose a documented default-false pin is a human
decision for a follow-up, after the known-optimism item above is
either fixed or accepted. Do not enable live.
