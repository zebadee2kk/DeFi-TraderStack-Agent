# Polymarket wallet × world-context evaluation (#193 / #57 / #48)

This evaluator is the first statistical follow-on to the point-in-time fusion layer.
The catalog was frozen in issue #193 **before any conditioned PnL was inspected**.

## Fixed catalog

Base wallet hypotheses remain unchanged:

- `persistent_top10_follow`
- `top3_follow`
- `persistent_top10_fade`

The fixed context cells are:

- `baseline_all`
- `context_available` — coverage control only
- `news_adverse`
- `news_event_high` — event score >= 0.50
- `narrative_attention_high` — |mention velocity z| >= 1.0
- `narrative_sentiment_extreme` — |sentiment| >= 0.50
- `onchain_flow_extreme` — |exchange netflow z| >= 1.5
- `wallet_accumulation_extreme` — |large-wallet accumulation| >= 0.50
- `external_technical_extreme` — |external technical score| >= 0.50
- `liquidation_stress` — max |long/short liquidation notional z| >= 1.5

No threshold search is performed by the command.

## Time and sample contract

The existing 60 / 300 / 900 second copy delays, 24-hour hold, and 25 / 50 / 100 bps
per-side cost prints are retained.

The chronological 70/30 discovery/holdout boundary is calculated from the **baseline wallet
signal sequence first**. Context filters are then applied inside those fixed periods; each subset
does not get to choose its own later split.

A context cell is not interpreted as evidence unless it has at least:

- 30 discovery signals; and
- 15 holdout signals.

Sparse cells remain in the report as `insufficient_evidence`.

## Statistics

Each cell reports count, coverage, gross/net PnL, mean net PnL, win rate and max drawdown.
The treatment comparison is the context subset versus `baseline_all` for the same wallet
hypothesis, delay and cost print.

The command uses the repository's fixed-seed bootstrap machinery for the cell mean and a
fixed-seed baseline-resampling bootstrap for incremental mean.

DSR is corrected against the **entire frozen logical catalog** for the relevant split:
3 wallet hypotheses × 3 copy delays × 3 cost prints × 10 context cells = **270 trials**.
It is computed only when every one of those 270 cells has the required sample support and a
defined per-signal Sharpe. Sparse or degenerate cells cause DSR for that split to be withheld as
`global_catalog_sample_support_incomplete`; the evaluator never drops unavailable cells and
quietly reduces the trial count after seeing results.

PBO is explicitly withheld in this first conditional slice: treatment cells have different
signal support. Zero-filling the missing observations merely to create a rectangular CSCV matrix
would invent trades. A future matched-support implementation may compute PBO; until then it is
reported as not computed, never as a pass.

## Command

```bash
traderstack-polymarket-world-context-eval
```

This command is research-only. It does not mutate strategy configuration, create a promotion pin,
or enter the crypto decision/execution loop. Empty and negative results are valid outcomes.
