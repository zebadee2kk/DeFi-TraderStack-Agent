# Edge-status memo — 2026-09-18

**Repo tip at score:** `ae2f8ed` (post-#172; fee-ladder autopsy on same day).

Paper / research only. Summarises strategy-search outcomes **#160–#172** plus the same-day
fee-ladder autopsy on frozen oi_mom. **Not a profitability
claim.** No number here is invented. All `PAPER_PROMOTE_*` defaults stay **false**.
`TRADING_MODE` stays `paper`. No live path.

## Standing promote bar (unchanged)

A name cannot enter a paper pin unless **all** hold:

1. Dual independent prints (two venues **or** two non-overlapping eras).
2. Fee-aware walk-forward total return > 0 and holdout excess > 0 on **both**
   BTC and ETH (#96 balanced bar), plus harder A/B/C gates when the window
   allows.
3. Catalog + print policy frozen **before** the pull.
4. An operator-facing `PAPER_PROMOTE_*` flag is added only after a committed
   report names a passer, and that flag still defaults **false**.

Skip-not-invent: a missing series is a skip, not a zero-filled z.

## Empty / skip streak (#160–#170)

| id | family | result | note |
| --- | --- | --- | --- |
| #160 | xs-topk archive dual-print | **0** dual-print passers | Kraken×Coinbase archive cells scored; portfolio bar cleared by none. |
| #161 | xs-topk low-turnover catalog | **0** dual-print passers | Distinct `xs_topk_lt_*` ids; not a retune of #160. |
| #162 | HL−HTX funding-div spot overlay | **0** dual-print passers | Divergence feature aligned; spot FeatureZ fade/follow empty at pilot 80+5. |
| #163 | ensemble-trend v2 consensus | **0** dual-print passers | Fresh `ens_trend_v2_*` catalog; concurrent Kraken×Coinbase harder gates. |
| #164 | Polymarket crypto wedge | empty / no edge | Fee-aware eval; stand-aside / empty eligible set. |
| #165 | paper perp-hedge soak | **0 fills** | Harness + metrics only; promote stays false. |
| #166 | DefiLlama stable net-issuance | **NOT_PIT** | Live `/stablecoincharts/*` refuses historical dual-print (no as_of). |
| #167 | Polymarket weather live-tape | **empty_print** | Recipe + empty live collect; fail-closed success. |
| #168 | session-gap overnight/session | **0** dual-print passers | Kraken×Coinbase OHLC gap FeatureZ; promote blocked. |
| #169 | vol-target on `ma_cross_10_30` | **0** dual-print passers | Concurrent-venue Kraken×Coinbase; promote blocked. |
| #170 | DefiLlama PIT snapshot collector | day-one tip | `tip_days=1`; dual-print unavailable until ≥720 tips. |

Promote blocked after each of the above. Claude helper shells often exited
empty (ec=129); operator continued scoring.

## This slice — vol-target second-era dual-print

Pre-registered recipe:
`docs/artifacts/strategy-search/vol-target-ma-cross-second-era-dual-print-recipe.md`

Family picked because `traderstack-vol-target` already accepts `--candles-dir`
and has concurrent-venue plumbing from #169. Catalog **unchanged** (no retune).

Frozen cells (Coinbase public archive; `RESEARCH_KRAKEN_ARCHIVE_PATH` unset so
`kraken_archive` was not used):

- `coinbase_era_2024_2026`: 2024-09-24 → 2026-09-17 (724 daily bars BTC/ETH)
- `coinbase_era_2022_2024`: 2022-09-24 → 2024-09-23 (731 daily bars BTC/ETH)

Score artifact:
`docs/artifacts/strategy-search/vol-target-ma-cross-second-era-dual-print.md`

Result: **dual_print_passers=0**; `can_promote=false`; `keep_flag_false=true`.
Pilot 80+5 bps. Promote blocked.

## Paper-fill gap (honest)

- Spot paper path (Kraken `PAPER_SIMULATE_FILLS`) remains the only executable
  research path for candle long/flat families.
- Named research families that cleared **no** dual-print bar must not be
  described as edges.
- Hedged carry / basis-aware pins remain research-model only unless a
  committed dual-print passer exists (none today for spot-executable names).
- #165 hedge soak recorded **0 fills** — plumbing evidence only.
- #170 PIT snapshot archive is the forward unblocker for `stable_ni_*`; do not
  invent historical tips from one live chart.

## Remaining ranked hypotheses (pre-registration only)

Historical list through vol-target second-era. **Updated post-#172 + fee-ladder
list is at the bottom of this memo.** Struck items stay struck:

1. ~~Vol-target overlay on frozen `ma_cross_10_30` (concurrent venue)~~ — #169; 0 passers.
2. ~~PIT-safe DefiLlama issuance archive collector~~ — #170 landed; wait for ≥720
   tip days before re-scoring `stable_ni_*`. Do not invent backfill tips.
3. ~~Second-era / archive-era cell for vol-target~~ — #171; 0 passers.
4. ~~HL/Bybit OI-momentum dual-print~~ — #172; 0 passers at pilot 80+5.
5. ~~Fee-ladder autopsy on frozen oi_mom (80 / 38 / 10)~~ — 0 passers every rung;
   **not** a fee-blocker for oi_mom.
6. **Maker/rebate path** — blocked until post-only paper fill-rate evidence.
7. **Paper-perp fills for carry** — executable path; #165 soak 0 fills.
8. **Second-era cell for sess-gap or ens_trend_v2** — freeze recipe before pull.
9. **Polymarket** — keep collector/eval isolated until PIT dual-print framework.

Out of scope / do not revive without new data: BitMEX, failed #104/#108/#116–#123
N-retunes, Vision→HL stitch, inventing basis, flipping `PAPER_PROMOTE_*`,
oi_mom fee retunes after this autopsy.

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** Empty dual-print sets remain the
successful outcome until a committed report names a fee-aware dual-print
passer that is paper-spot executable. Continue scheduled DefiLlama snapshot
collects so tip coverage can grow without look-ahead.


## Follow-up — HL/Bybit OI-momentum (#172) — MERGED

Pre-registered recipe:
`docs/artifacts/strategy-search/oi-mom-hl-bybit-dual-print-recipe.md`

Score artifact:
`docs/artifacts/strategy-search/oi-mom-hl-bybit-dual-print.md`

Result: **dual_print_passers=0**; `can_promote=false`; `keep_flag_false=true`.
Pilot 80+5. Dual OI AVAILABLE (asilletto81 HL + Bybit). Promote blocked.
`PAPER_PROMOTE_*` untouched.

## Fee-ladder autopsy (strategic after empty streak #160–#172)

Pre-registered recipe:
`docs/artifacts/strategy-search/fee-ladder-autopsy-recipe-2026-09-18.md`

Frozen catalog **before** re-score: **oi_mom** (already dual-print capable;
ids not retuned). Ladder already in `fee_tiers`: pilot t1 80+5, one
intermediate t3 38+5, research modelled 10+5.

Memo: `docs/artifacts/strategy-search/fee-ladder-autopsy-2026-09-18.md`

| rung | dual_print_passers | note |
| --- | ---: | --- |
| pilot 80+5 | **0** | promote bar |
| t3 38+5 | **0** | intermediate |
| modelled 10+5 | **0** | research |

**Fee-blocker finding: no** for oi_mom — nothing clears at 10+5 either.
Typical core median WF trades ≈17; median fold turnover ≈2.8 (fee-invariant).
Best primary WF excess remains negative at all rungs. Promote still blocked.

## Remaining ranked hypotheses (updated)

Do **not** retune failed catalogs (including oi_mom fee retunes). Next
falsifiable slices:

1. **Maker/rebate path** — blocked until post-only paper fill-rate evidence;
   do not assume maker fees in dual-print scores.
2. **Paper-perp fills for carry** — executable path for funding/basis; #165
   soak had 0 fills (plumbing only).
3. **Second-era cell for sess-gap or ens_trend_v2** — freeze recipe before pull.
4. **DefiLlama PIT** — wait ≥720 tip days before `stable_ni_*` re-score.

Out of scope / do not revive without new data: BitMEX, failed N-retunes,
Vision→HL stitch, inventing basis, flipping `PAPER_PROMOTE_*`, post-hoc
fee-ladder fishing beyond the frozen three rungs above.

