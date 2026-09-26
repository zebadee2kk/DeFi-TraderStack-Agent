# Paper maker / post-only fill-rate probe (2026-09-26)

Generated: `2026-09-26T08:53:40.962056+00:00`

**maker_evidence_status: `INVALID`**
**fill_rate: `UNAVAILABLE`**

## Measurement

- post_only_path_exists: `False`
- post_only_code_hits: `[]`
- orders_attempted: `20`
- fills: `20`
- cancels: `0`
- rejected: `0`
- time_to_fill_ms_max: `0.5548870000211537`
- time_to_fill_ms_mean: `0.07485849999113725`
- always_immediate_sync_fills: `True`
- PAPER_PROMOTE_* flipped: `False`

## Honesty

PaperFillSimulator fills every intent synchronously at mid ± adverse slippage (taker-style). No post-only / resting / cancel path exists (#73 not implemented). Immediate 100% fill is INVALID for maker fill-rate evidence. Do not assume maker fees. Stop.

≤2h soak not required: simulator has no resting queue, so wall-clock cannot create maker fill vs cancel observations.

## Decision

Maker/rebate path remains **blocked**. Do not score dual-prints at maker bps. No `PAPER_PROMOTE_*` changes.
