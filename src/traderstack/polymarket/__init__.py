"""Paper-only Polymarket weather research (opt-in; never live CLOB orders).

This package is deliberately *not* imported by the crypto paper loop
(``cli.build_service``, ``ContinuousPaperService``, ``RiskEngine``). Invoking
``traderstack-polymarket-weather-paper`` is the opt-in. It may only emit
would-trade intents to a dedicated JSONL ledger.
``traderstack-polymarket-weather-eval`` is the fee-aware report-only
evaluator for those hypotheses. It cannot promote without dual
independent prints and never writes a ``PAPER_PROMOTE_*`` pin.

Hard constraints:
- public Gamma/CLOB GETs only; no signing, no private keys, no CLOB POSTs
- ``TRADING_MODE`` must stay ``paper``
- the operator kill switch withholds intents
- claimed weather-market win rates are unproven; see the validation notes in
  ``docs/EVALUATION-FRAMEWORK.md``

``traderstack-polymarket-crypto-collect`` (#142) is a second, equally isolated
opt-in under the same hard constraints: it adds a read-only Deribit public
option client and appends point-in-time BTC/ETH threshold mid vs option-implied
probability observations to a dedicated tape. It records Crucix high-tier alerts
as a stand-aside status that can only withhold rows from a future trade mask,
and its evaluator is a later slice, so nothing here claims PnL.
"""
