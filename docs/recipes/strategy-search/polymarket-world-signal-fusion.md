# Polymarket wallet + world-signal fusion (#193)

This slice aligns already-persisted provider observations with the frozen wallet-derived
Polymarket signal candidates. It is **research-only**: no order path, signing path, promotion pin,
or position-sizing authority is imported or exposed.

## Point-in-time contract

For each candidate at time **T**:

- only provider observations with `observed_at <= T` are eligible;
- observations older than the configured context window are rejected (default: 24 hours);
- for each `source_id + asset`, only the latest eligible observation known at T is attached;
- asset-specific observations are attached only when the market text identifies that asset;
- `GLOBAL`, `ALL`, `MARKET`, and `WORLD` observations may attach to any market;
- missing context remains missing. It is never replaced with a later observation or invented value.

The first asset vocabulary is intentionally narrow: BTC/Bitcoin, ETH/Ethereum and SOL/Solana.
Expanding it is a schema/research change, not a reason to fuzzy-match arbitrary market text.

## Command

```bash
traderstack-polymarket-world-signal-fusion
```

Useful options:

```bash
traderstack-polymarket-world-signal-fusion \
  --category CRYPTO \
  --time-period MONTH \
  --cohort-ttl-hours 168 \
  --max-context-age-hours 24
```

The output is deterministic JSON containing the wallet hypothesis identity, signal timestamp,
market identity, and attached provider provenance/payload. The warehouse query is bounded to the
candidate time range plus the configured lookback, so future rows are not even needed by the
fusion stage.

## Interpretation

This output is context for hypothesis analysis under #193/#57. It is **not** evidence that a
provider field is predictive, and it must not be used to retune the frozen K=3 wallet hypotheses
after seeing outcomes. Provider usefulness still requires discovery/holdout evaluation,
multiple-testing controls, realistic execution costs, and independent time coverage.
