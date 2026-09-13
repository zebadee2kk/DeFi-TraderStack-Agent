# Odds brief — how to raise the chance TraderStack finds a real edge

Generated: 2026-09-13. Paper / research only. Not a profitability claim.
Tracking issue: #132 (sub-issues #133–#143). Rendered version with the
same content: the session artifact linked from #132.

Grounded in the repo's own record (`strategy-search/edge-status-2026-09-12.md`:
twelve families, zero dual-print passers; `pit-basis-archives.md`: dual-print
basis UNAVAILABLE) and in sources checked online on 2026-09-13. Every data
source below was probed from the session environment with an unauthenticated
request; the probe result is stated next to it.

## Verdict

**The bottleneck is statistical power, not strategy ideas.** Every family
since #104 was scored on the same ~2-year Kraken 720 plus one older 720-day
Binance.US window. A two-year daily sample cannot distinguish a Sharpe-1
strategy from zero, so twelve empty catalogs are what you would expect even
if one of them worked.

Three things move the odds most:

1. Free multi-year data from independent venues is reachable now, including
   the point-in-time basis series the carry family was blocked on.
2. The search harness needs a selection-bias correction that scales with the
   number of trials (Deflated Sharpe, PBO) and an era-print policy.
3. The fee model is optimistic by four to eight times at the account size a
   pilot would start with.

## 1. Why the current window cannot say yes

Standard error of an annualised Sharpe: `SE ≈ sqrt((1 + SR²/2) / T_years)`.
Requiring t = 2:

| true Sharpe | SE at 2y | SE at 4y | years for t = 2 |
| ---: | ---: | ---: | ---: |
| 0.5 | 0.75 | 0.53 | ≈ 18 |
| 1.0 | 0.87 | 0.61 | ≈ 6 |
| 1.5 | 1.03 | 0.73 | ≈ 3.4 |
| 2.0 | 1.22 | 0.87 | ≈ 2.3 |

A pass on the current window would be as suspect as the fails are
uninformative, so the strict gates are right to stay. The window is also a
single regime (2024-09 → 2026-09, with BTC down roughly a quarter YTD in
2026). The dual-print rule asks for two venues **or** two non-overlapping
eras; the data below supplies both back to 2015/2016 on daily bars.

## 2. Free data reachable from this environment (probed 2026-09-13)

| source | serves | probe | unlocks |
| --- | --- | --- | --- |
| Coinbase Exchange `GET /products/{id}/candles` | 1m…1d OHLCV. BTC-USD daily from 2016-01, ETH-USD hourly from 2020. 300/request, paginate by start/end. 837 products | 200, no auth | second independent US spot venue with unbounded history; era prints 2016–19 / 2020–22 / 2022–24 |
| Kraken official OHLCVT archive (support 360047124832) | full history from inception, 8 timeframes, quarterly Google Drive zips | 200, links present | venue-native history without the 720 cap; active pairs only |
| Binance Vision `data.binance.vision/data/…` | spot klines from 2017-08; USDT-M `markPriceKlines`, `indexPriceKlines`, `premiumIndexKlines`, `fundingRate` from 2020-01. LUNAUSDT 2022-04 still present | 200 via S3 (REST is 451 here) | third venue; mark−index = PIT basis; funding since 2020 |
| OKX `history-mark-price-candles` / `history-index-candles` | daily mark and index for swaps; ETH from 2020-01, BTC from 2020-09; 100/page via `after`; rapid pagination → 403, so rate-limit | 200, no auth | mark−index is exactly the construction `pit-basis-archives.md` asks for, on a venue that is not Hyperliquid and not closing |
| Bybit `public.bybit.com/{premium_index,spot_index,trading}` | CSV directories | 200 listing (REST 403) | funding/trades only; premium index is not basis |
| Coin Metrics community `v4/timeseries/asset-metrics` | 31 free daily BTC metrics incl. `CapMVRVCur`, exchange flows, `AdrActCnt`, `HashRate` | 200, no key (`SplyAct1d` → 403, skip) | on-chain regime gate |
| Polymarket CLOB `/prices-history` | timestamped price series per token; resolved markets keep ≥12h granularity only | 200, no key | weather / crypto-threshold tapes (must be captured while open) |
| IEM ASOS `daily.py`, NCEI GHCN-Daily `TMAX` | official station highs (PHNL 2025-06-01..03 = 83/86/87 °F on both) | 200 | Polymarket weather resolution |
| Open-Meteo Historical Forecast / Previous Runs APIs | archived as-issued forecasts from 2021–22 (ECMWF 2017); fixed lead-time runs from 2024-01 | quota exhausted on the shared IP; run from the operator host | point-in-time forecasts for the weather tape |

Survivorship caveat: Kraken's archive and Binance Vision drop some delisted
markets. Irrelevant for BTC/ETH; for any multi-asset universe, freeze the
membership list from a dated snapshot and treat missing symbols as skips.

## 3. Strategy directions with published evidence (ranked)

1. **Ensemble trend with volatility sizing on a liquid universe.** Zarattini,
   Pagani, Barbon (SSRN 5209907, 2025): survivorship-free 2015-01 → 2025-03,
   CAGR 30%, Sharpe 1.58, Sortino 2.03, alpha +14% vs BTC, net of fees, on
   the top-20 liquid coins. Rules: enter on close above the max close over
   each lookback {5,10,20,30,60,90,150,250,360}d, trailing-stop exit, 25%
   vol target on 90d realised vol, equal-weight the open positions. The
   repo's #118 single-lookback, two-asset, two-year test is not this. → #137
2. **Funding carry scored with real basis.** `carry_hedged_sign` was positive
   after fees on both funding tapes; blocked only on basis. OKX and Binance
   mark−index remove that blocker. Literature: tick-level long-spot/short-perp
   Sharpe 6 before full costs; only ~40% of top funding spreads positive
   after costs and reversals. Expect small, cost-dominated. → #134
3. **On-chain regime overlay, not signal.** 2026 peer-reviewed three-cycle
   study: NUPL / MVRV-Z rules beat buy-and-hold on every metric. Use as a
   frozen-threshold gate over trend/carry; never sizing. → #139
4. **Cross-sectional momentum on 20+ names, long-only top-k.** #117's three
   assets had no cross section; shorting many coins is impractical. → #140
5. **Intraday seasonality** (21–23 UTC, Monday Asia-open effect) has
   evidence but is documented as localised and short-lived. Low priority;
   hourly Coinbase history makes it testable properly.

## 4. Harness: harder to fool, easier to pass honestly

- Deflated Sharpe per catalog run (trial count, Sharpe variance, skew,
  kurtosis) alongside the existing gates; `purgedcv` (PyPI) implements DSR,
  probabilistic Sharpe, purged k-fold, CPCV.
- Probability of backtest overfitting via CSCV, so "0 passers" and
  "1 passer with PBO 0.6" are distinguishable.
- Era prints instead of correlated venue prints; regime coverage per
  `EVALUATION-FRAMEWORK.md`.
- Trade-count floors from bootstrap CIs, not a fixed 3.
- Read the #131 funnel first: `signal` dominant confirms this brief;
  `pretrade`/`risk` dominant is the system working. → #135, #136, #143

## 5. The fee model

Research costs are 10 + 5 bps; gate C stresses 20 + 10. Kraken Pro spot
(kraken.com/features/fee-schedule):

| tier (30d volume) | maker | taker | round trip taker |
| --- | ---: | ---: | ---: |
| 1, $0+ | 0.40% | 0.80% | 160 bps |
| 2, $2.5K+ | 0.30% | 0.60% | 120 bps |
| 3, $10K+ | 0.22% | 0.38% | 76 bps |
| 8, ~$500K+ | 0.08% | 0.20% | 40 bps |
| 12, $10M+ | 0.00% | 0.10% | 20 bps |

A tiny-capital pilot pays four to eight times the modelled cost per side.
Fix: research at the pilot tier and add post-only maker orders (Kraken's
post-only flag cancels rather than crosses; maps onto the planner's reject
path). Measure fill rate in paper before assuming maker fees. → #138

## 6. Where the language model belongs

Agent Market Arena (live, 2025-08 → 2025-09): BTC buy-and-hold +0.66% while
four LLM agent frameworks ranged −9.09% to +5.02%; architecture, not model,
dominated. CryptoBench: strong at retrieval, weak at prediction. The repo's
veto-only meta-agent is the correct reading. Positive-EV uses: research
automation (freezing catalogs, writing reports, cross-checking pulls) and
news screening for the adverse-event gate. Keep it out of sizing and side.

## 7. Polymarket

The weather module (#44) is complete and tested but has never scored a
resolved row: no point-in-time tape of decision-time CLOB mid + as-issued
forecast + official station high exists, and the evaluator correctly refuses
settlement prices as mids. The blocker is a collector, not the model.
Public 2025 bots report profits on temperature markets; the same sources
say edges compressed from ~10 to ~3 points by 2026 and at least one bot
lost significantly from mid-July 2026 on calibration. Polymarket Fee
Structure V2 (2026-03-30): weather takers `shares × 0.05 × p × (1−p)`, max
$1.25/100 shares; makers 0. → #141

Crypto-threshold markets: arXiv 2606.19517 finds Polymarket Yes prices
5.6–6.3 pp above option-implied probabilities on BTC threshold markets, an
11-point pooled gap vs Deribit, a ~4h mean-reverting wedge, and a
delta-hedged proxy profitable after conservative costs. Deribit public API
is reachable. Crucix high-tier alerts are the stand-aside gate. → #142

## 8. Ninety-day sequence

1. #133 fetchers + #135 harness statistics.
2. #136 re-score the twelve frozen catalogs on four eras and two venues.
3. #134 carry with real basis at the pilot fee tier.
4. #137 ensemble-trend catalog, pre-registered.
5. #138 fee realism and post-only execution.
6. #143 24-hour diagnostic window; read the verdict before touching anything.
   #141 / #142 collectors start on day one because their tapes take weeks.

## What not to do

- No thirteenth two-asset, two-year catalog.
- No relaxing of the #96 bar or the dual-print rule; add DSR and eras beside them.
- No premium index as basis; no stitched vendor samples.
- Nothing here touches `RiskEngine`, the kill switch, or `TRADING_MODE`.

## Sources

- Zarattini, Pagani, Barbon, Catching Crypto Trends (SSRN 5209907); CXO Advisory summary of the rules
- Using on-chain data to predict Bitcoin cycles, Research in International Business and Finance (2026)
- Chan, Leveraged BTC Funding Carry Algorithm (SSRN 5292305); funding-rate arbitrage on CEX and DEX (ScienceDirect S2096720925000818)
- Bailey & López de Prado, The Deflated Sharpe Ratio (SSRN 2460551); The Probability of Backtest Overfitting; purgedcv (PyPI)
- Momentum Trading in Cryptocurrencies: TS vs XS (2025); Starkiller Capital on XS shorting constraints; A Trend Factor for the Cross Section of Cryptocurrency Returns (JFQA)
- When Agents Trade (arXiv 2510.11695); CryptoBench (arXiv 2512.00417)
- Do Prediction Markets Match Option Prices? (arXiv 2606.19517); Reichenbach & Walther, Polymarket accuracy/skill/bias (SSRN 5910522)
- Kraken fee schedule; Kraken maker/taker + post-only support article; Kraken OHLCVT archive article; Concretum Kraken-archive guide
- Coinbase product candles reference; binance/binance-public-data; OKX history mark/index candle docs (okxr)
- Polymarket prices-history docs; py-clob-client issues #189/#216; Polymarket Fee Structure V2 guides; public weather-bot repos (BallesJr, tobiasbischoff)
- Open-Meteo Historical Forecast and Previous Runs APIs; IEM ASOS; NCEI GHCN-Daily
- Quantpedia and Concretum on Bitcoin intraday seasonality; StatMuse BTC YTD 2026
