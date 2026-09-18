# Edge-status memo — 2026-09-18

**Repo tip at score:** re-pin after DefiLlama PIT snapshot archive merge.

Paper / research only. Summarises strategy-search outcomes **#160–#169** plus
the PIT snapshot collector in this slice. **Not a profitability claim.** No
number here is invented. All `PAPER_PROMOTE_*` defaults stay **false**.
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

## Empty / skip streak (#160–#169)

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
| #169 | vol-target on `ma_cross_10_30` | **0** dual-print passers | Reduce-only VT scalars; promote blocked. |

Promote blocked after each of the above. Claude helper shells often exited
empty (ec=129); operator continued scoring.

## This slice — PIT-safe DefiLlama snapshot archive

Pre-registered recipe:
`docs/artifacts/strategy-search/defillama-stable-pit-snapshot-recipe.md`

Collector: `traderstack-defillama-stable-snapshot` writes immutable
`var/research/defillama/stablecoincharts/as_of=YYYY-MM-DD/` + append-only
`tips.jsonl`. PIT net-issuance = successive tip deltas only. Dual-print
score still refused until **≥720** distinct `as_of` tip days exist.

Day-one coverage: **1 tip day (or whatever the collect reports)** —
`enough_for_dual_print=false`. Honest `print_kind=unavailable` / skip; **no**
invented historical PnL from the live chart. Link from #166 unavailable
report: archive path is the forward unblocker, not a backfill.

Status artifact:
`var/research/defillama/stablecoincharts/STATUS.md` (local; may be gitignored)

## Paper-fill gap (honest)

- Spot paper path (Kraken `PAPER_SIMULATE_FILLS`) remains the only executable
  research path for candle long/flat families.
- Named research families that cleared **no** dual-print bar must not be
  described as edges.
- Hedged carry / basis-aware pins remain research-model only unless a
  committed dual-print passer exists (none today for spot-executable names).
- #165 hedge soak recorded **0 fills** — plumbing evidence only.

## Remaining ranked hypotheses (pre-registration only)

Do **not** retune failed catalogs. Next falsifiable slices, ranked:

1. ~~Vol-target overlay on frozen `ma_cross_10_30`~~ — scored #169; 0 passers.
2. ~~PIT-safe DefiLlama issuance archive~~ — collector landed this slice;
   wait for ≥720 tip days before re-scoring `stable_ni_*` (or keep daily
   collect). Do not invent backfill tips from one chart.
3. **Second-era / archive-era cells** for any future spot family that already
   has concurrent-venue plumbing but only one covered era (rank #4 pivot if
   snapshot path stalls).
4. **Polymarket** — keep collector/eval isolated; empty tapes stay success
   until a PIT mid+settlement dual-print framework exists.

Out of scope / do not revive without new data: BitMEX, failed #104/#108/#116–#123
N-retunes, Vision→HL stitch, inventing basis.

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** Empty dual-print sets remain the
successful outcome until a committed report names a fee-aware dual-print
passer that is paper-spot executable. Run the DefiLlama snapshot collector
on a schedule so tip coverage can grow without look-ahead.
