# Polymarket wallet-signal evaluation recipe (#193)

**Frozen before any score is inspected.** Research-only. No order path, no signing, no promotion pin.

## Population

Source rows are the point-in-time `wallet_observations` warehouse records created by
`traderstack-polymarket-wallet-snapshot`.

Default population:

- leaderboard category: `CRYPTO`;
- leaderboard time period: `MONTH`;
- exact cohort identity: `snapshot_id` / `snapshot_at`;
- legacy rows without a snapshot id are accepted only through the lower-confidence minute-bucket
  compatibility rule in `wallet_cohorts.py`;
- a cohort membership expires after **168 hours** unless a newer qualifying snapshot refreshes it;
- a trade can only be acted on when its trade timestamp is **after** the qualifying cohort snapshot;
- only **BUY** trades are considered in the first executable research slice. SELL copying is not
  silently modelled because a follower may not own the token.

## Frozen hypothesis catalog (K=3)

1. `persistent_top10_follow`
   - current point-in-time rank <= 10;
   - at least two qualifying snapshots observed up to that date;
   - follow later BUY trades in the same token.

2. `top3_follow`
   - current point-in-time rank <= 3;
   - no persistence requirement;
   - follow later BUY trades.

3. `persistent_top10_fade`
   - same cohort rule as `persistent_top10_follow`;
   - synthetic inverse exposure for research comparison only;
   - **not executable** until opposite-token/inventory semantics are explicitly implemented.

Do not add or retune rules after seeing results. A failed or empty print is a valid outcome.

## Copy-delay and price-quality grid

Frozen delays: **60 / 300 / 900 seconds**.

Entry target = leader trade timestamp + delay.
Exit target = entry target + **24 hours**.

Price source = public Polymarket Data API point-in-time price history for the exact outcome token.
A price point is refused when:

- it is after the requested target;
- it is older than 1,800 seconds from the target; or
- its reported resolution exceeds 1,800 seconds.

This deliberately means old/coarse history can produce no score. It must never be silently upgraded
to five-minute copy evidence.

## Costs and capacity

Frozen per-side cost sensitivity: **25 / 50 / 100 bps**.

Costs are charged on entry and exit value. They are a conservative all-in research sensitivity, not
a claim about the exact fee schedule of every Polymarket category.

Target copy notional = **$10** per signal, capped at **10% of the leader's observed trade notional**.
Signals with copied notional below **$1** are skipped.

## Evaluation

- chronology is preserved;
- default final **30%** of scored signals is the untouched holdout;
- report discovery / holdout / all separately;
- report signal count, gross PnL, net PnL, mean net PnL, win rate and max drawdown;
- results are normalized to the bounded copy notional above;
- price-unavailable / too-coarse and capacity skips are counted explicitly;
- no result can flip `PAPER_PROMOTE_*`, create an order, or grant execution authority.

## Interpretation

A positive result is a research lead only. Before any paper strategy is created it still requires:

- independent time coverage;
- category/regime breakdown;
- spread/depth validation from collected books;
- resolution/outcome validation where applicable;
- multiple-testing controls under #57 / #135;
- paper and shadow evidence under the normal promotion path.
