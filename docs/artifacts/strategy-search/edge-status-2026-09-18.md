# Edge-status memo — 2026-09-18

**Repo tip at score:** re-pin after vol-target merge (post-#168).

Paper / research only. Summarises strategy-search outcomes **#160–#167** plus
the session-gap dual-print in this slice. **Not a profitability claim.** No
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

## Empty / skip streak (#160–#167)

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

Promote blocked after each of the above. Claude helper shells often exited
empty (ec=129); operator continued scoring.

## Paper-fill gap (honest)

- Spot paper path (Kraken `PAPER_SIMULATE_FILLS`) remains the only executable
  research path for candle long/flat families.
- Named research families that cleared **no** dual-print bar must not be
  described as edges.
- Hedged carry / basis-aware pins remain research-model only unless a
  committed dual-print passer exists (none today for spot-executable names).
- #165 hedge soak recorded **0 fills** — plumbing evidence only.

## This slice — vol-target on frozen ma_cross_10_30

Pre-registered recipe:
`docs/artifacts/strategy-search/vol-target-ma-cross-dual-print-recipe.md`

Frozen catalog: control `ma_cross_10_30` (cannot promote) plus
`ma_cross_10_30_vt15|vt25|vt50` reduce-only realised-vol scalars (lookback 20,
max lev 1.0) scored at pilot **80+5** on Kraken×Coinbase daily OHLC. Run
report (re-pin SHA after merge):

`docs/artifacts/strategy-search/vol-target-ma-cross-dual-print.md`

Passer count is whatever the committed report prints (0 is success). This
memo does **not** invent PnL. Session-gap (#168) already landed with
`dual_print_passers=0`.

## Remaining ranked hypotheses (pre-registration only)

Do **not** retune failed catalogs. Next falsifiable slices, ranked:

1. **Vol-target overlay on frozen `ma_cross_10_30`** — scored this slice
   (`vol-target-ma-cross-dual-print.md`); accept whatever passer count the
   committed report prints (0 is success). Do not retune scalars after.
2. **PIT-safe DefiLlama (or other) issuance archive** — operator-dated
   snapshots + LAG_DAYS before any historical dual-print (#166 blocker).
3. **Second-era / archive-era cells** for any future spot family that already
   has concurrent-venue plumbing but only one covered era.
4. **Polymarket** — keep collector/eval isolated; empty tapes stay success
   until a PIT mid+settlement dual-print framework exists.

Session-gap (#168) returned 0 dual-print passers; no follow-up unless a
structural OHLC blocker appears.

Out of scope / do not revive without new data: BitMEX, failed #104/#108/#116–#123
N-retunes, Vision→HL stitch, inventing basis.

## Operator recommendation

**Keep every `PAPER_PROMOTE_*=false`.** Empty dual-print sets remain the
successful outcome until a committed report names a fee-aware dual-print
passer that is paper-spot executable.
