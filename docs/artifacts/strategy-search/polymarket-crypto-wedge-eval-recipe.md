# Polymarket crypto-threshold vs Deribit — fee-aware eval recipe (#142 slice-2)

**Status:** pre-registered recipe. **Not a result.** No PnL is claimed here.
**Date:** 2026-09-18 · repo tip at authoring: `e48e21a` (re-pin commit in any run report).
**Never flips `PAPER_PROMOTE_*`.** Empty / cannot-promote is success.

## Why this exists

`traderstack-polymarket-crypto-collect` (#142 / collector shakedown) writes a
point-in-time wedge tape and freezes rules in
`src/traderstack/polymarket/crypto_models.py` (`CRYPTO_WEDGE_RULES`). The
evaluator named in `docs/EVALUATION-FRAMEWORK.md` —
`traderstack-polymarket-crypto-eval` — was deferred. This recipe freezes the
slice-2 score path **before** any settlement pull or score that could bias
the catalog.

Weather (#141 / #157) remains a parallel paper path: its eval already
exists, but the live tape starts empty and cannot promote on a single
print. This slice does **not** retune weather gates after seeing empty
prints.

## Frozen decision rule (already in crypto_models; do not retune after PnL)

1. Universe: Polymarket daily BTC/ETH "above $K on <date>" markets vs Deribit
   option-implied `P(S_T > K)` (`bs_n_d2_markiv_interp_v1`).
2. Decision row: latest `status=ok` observation per `(market_id)` with
   `observed_at < resolves_at` (look-ahead refuse).
3. Trade mask: `|wedge| >= 0.05` **and** Crucix positively `clear`.
   `adverse` / `unavailable` / `not_configured` stand aside (gate can only
   remove).
4. Treatment side: if `wedge > 0` (poly rich) → sell YES / buy NO; if
   `wedge < 0` (poly cheap) → buy YES. No size/notional in the tape.
5. Controls on the **same** mask: `always_hold` (PnL 0) and `fade_the_mid`
   (opposite side).
6. Fees (frozen): Polymarket taker `shares * 0.07 * p * (1-p)` cap 1.75 /
   100 shares; Deribit option taker 0.0003 underlying/contract cap 12.5%
   premium; hedge perp 5 bps. Unhedged (Polymarket-only) is the primary
   promote-bar metric; hedged is reported when option fill inputs exist,
   otherwise `hedged=skipped_not_invented`.
7. Entry honesty: conservative fill uses mid ± half-spread when bid/ask
   present; mid-fill is reported and **cannot** promote.
8. Resolution sources (disjoint prints): (A) Binance Vision 1m close at
   noon ET vs strike; (B) Gamma settled `outcomePrices`. Settlement is
   never read back as a decision-time mid.
9. Print bar: `MULTI_PRINT_BAR_PREREGISTERED=true`; two independent prints
   (BTC vs ETH **or** non-overlapping resolution dates); `MIN_ROWS_PER_PRINT=20`,
   `MIN_TRADES_PER_PRINT=8`. Calculator also requires treatment excess vs
   hold **and** fade > 0 on eligible set and dated holdout tail (20%).
10. `PAPER_PROMOTE_POLYMARKET_CRYPTO_WEDGE` is **not** a Settings field.
    `can_promote` stays false in this CLI. Empty is success.

## What this run may score

- Operator-supplied `--tape` JSONL of `CryptoWedgeRow` observations.
- Operator-supplied `--settlements` JSON of
  `{market_id, yes_won, resolution_source, resolves_at}` — skip-not-invent
  when missing.
- `--empty-live` when no point-in-time tape + settlement pack exists in
  this environment (honest default).
- Fixture packs under `tests/fixtures/polymarket_crypto/` prove the
  calculator offline; fixtures cannot promote.

## Exact command skeleton

```bash
cd /path/to/DeFi-TraderStack-Agent
. .venv/bin/activate

# Honest live empty (no settled PIT tape in repo):
TRADING_MODE=paper traderstack-polymarket-crypto-eval --empty-live \
  --output-md docs/artifacts/strategy-search/polymarket-crypto-wedge-eval.md \
  --output-json var/ops/polymarket_crypto_wedge_eval.json

# When operator has tape + settlements (never invent fills):
TRADING_MODE=paper traderstack-polymarket-crypto-eval \
  --tape var/audit/polymarket_crypto_wedge_tape.jsonl \
  --settlements var/ops/polymarket_crypto_settlements.json \
  --output-md docs/artifacts/strategy-search/polymarket-crypto-wedge-eval.md
```

## Paper-executable path (forward)

1. Cron `traderstack-polymarket-crypto-collect --once` every 15m while
   markets are open (GET-only; paper mode).
2. After resolution, append settlements from Binance Vision **or** Gamma
   `outcomePrices` (two sources → dual-print independence). Never use
   settlement as mid.
3. Re-run eval; promote remains blocked until dual independent prints
   clear the calculator **and** a separate Settings pin lands default
   false (out of scope here).

## Out of scope / cannot-promote reasons

- No Crucix clear in a typical operator env → gated mask empty.
- No weeks of PIT tape → empty_print.
- Single print / overlapping same-source dates → print_kind=single_print.
- Hedged path without Deribit fill tape → skipped_not_invented.
