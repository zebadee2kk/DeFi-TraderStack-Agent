"""Paper-only Polymarket weather research (opt-in; never live CLOB orders).

This package is deliberately *not* imported by the crypto paper loop
(``cli.build_service``, ``ContinuousPaperService``, ``RiskEngine``). Invoking
``traderstack-polymarket-weather-paper`` is the opt-in. It may only emit
would-trade intents to a dedicated JSONL ledger.

Hard constraints:
- public Gamma/CLOB GETs only; no signing, no private keys, no CLOB POSTs
- ``TRADING_MODE`` must stay ``paper``
- the operator kill switch withholds intents
- claimed weather-market win rates are unproven; see the validation notes in
  ``docs/EVALUATION-FRAMEWORK.md``
"""
