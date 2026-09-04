# Security Review — September 2026

**Scope:** the integrated MVP at commit `f1aface` (branch
`claude/robinhood-chain-config-1yjkt3`), ~10.4k lines under `src/traderstack/`
plus 9k lines of tests, the container/CI surface and the dependency set.

**Method:** adversarial review against this repository's own controls
(`docs/SECURITY-THREAT-MODEL.md`, `docs/RISK-PRINCIPLES.md`,
`docs/ADR-0001-PREBUILD-DECISIONS.md`, `docs/EXECUTION-ARCHITECTURE.md`) rather
than a generic checklist. Every source file was read. Seven named invariants
were attacked directly, each attempt written as an executable test; tests that
demonstrated a real defect were kept as regression tests alongside the fix, and
tests that only confirmed an invariant were kept as positive assertions of it.
New tests live in `tests/security/`.

**Reviewer's posture:** the venue, every provider, the RPC endpoint and the
model are all assumed hostile. "It fails closed" is the bar; "no code path
currently reaches it" is not.

---

## 1. Findings

| ID | Severity | Component | Description | Status | Test |
| --- | --- | --- | --- | --- | --- |
| SEC-2026-09-01 | **High** | `execution/reconcile.py`, `execution/ledger.py` | `_number` accepted non-finite venue numbers. A `/trading/trades` row with `"price": 1e400` (or `"inf"`, `NaN`, `Infinity` — all legal to `json.loads` and to `float()`) passed `Field(gt=0)`, was applied to the portfolio, and drove `cash_usd` to `-Infinity` and NAV to `NaN`. Every later `PortfolioSnapshot` then failed validation, so the service died after `max_consecutive_errors` — with the poisoned book already written to the checkpoint. | **Fixed** | `test_venue_response_integrity.py::test_a_non_finite_venue_number_never_reaches_the_portfolio`, `::test_execution_fill_rejects_non_finite_quantities_and_prices` |
| SEC-2026-09-02 | **High** | `execution/reconcile.py` | `_rows` converted an envelope it could not read (`{"data": {...}}`, `{"orders": "x"}`, `{"detail": "..."}`, `{}`) into an empty row list. `venue_knows_order` then answered `False`, which `IdempotentSubmitter._gate_retry` reads as "the venue never saw this order" and uses to authorise a **resubmission** — the exact double-execution the ledger exists to prevent. | **Fixed** | `test_venue_response_integrity.py::test_an_unreadable_orders_envelope_is_unknown_state_not_an_empty_venue`, `::test_a_genuinely_empty_venue_still_answers_no` |
| SEC-2026-09-03 | **High** | `killswitch.py`, `cli.py` | The Redis halt channel is documented as an implemented control and as fail-closed ("an unreachable Redis halt channel is treated as engaged"). In practice `cli.py` never constructed a Redis client, so `KILL_SWITCH_REDIS_ENABLED=true` produced a switch with `redis_client=None`; `refresh()` skipped the probe entirely and `redis_engaged` stayed `False`. An operator setting the Redis key to halt the fleet would have had **no effect at all**, silently. | **Fixed** | `test_halt_controls_cannot_be_bypassed.py::test_an_enabled_but_unwired_redis_halt_channel_reads_as_engaged`, `::test_an_unreachable_redis_halt_channel_stays_engaged_across_refreshes` |
| SEC-2026-09-04 | Medium | `config.py` | `Settings` was a mutable pydantic model. `settings.max_position_pct = 1.0` on the object a live `RiskEngine` holds succeeded and silently changed every limit and the derived `policy_version`. No code path did this today, but the central Zone C claim is that limits change only through version-controlled configuration; nothing enforced it. | **Fixed** | `test_halt_controls_cannot_be_bypassed.py::test_risk_limits_cannot_be_rewritten_on_a_live_settings_object`, `::test_a_settings_copy_cannot_be_smuggled_into_a_frozen_engine` |
| SEC-2026-09-05 | Medium | `logging_config.py` | The redaction processor matched only `key|token|password|secret` in key names. It therefore did **not** redact `Authorization` — the header name under which LunarCrush and Perplexity credentials are sent — nor `auth`, `credential`, `bearer`, `passwd` or `Cookie`. It also skipped tuples and never inspected string values. | **Fixed** | `test_secret_containment.py::test_the_redaction_processor_masks_every_credential_key_shape`, `::test_the_redaction_processor_walks_nested_containers` |
| SEC-2026-09-06 | Medium | `market/registry.py`, `market/intelligence_providers.py` | CryptoPanic authenticates with an `auth_token=` **query parameter** (its API offers no header). httpx embeds the full request URL in `HTTPStatusError`, and `ProviderRegistry._record_failure` stored `f"{type(exc).__name__}: {exc}"` verbatim in `health().last_error`. A 401/429 from CryptoPanic therefore parked the live API key in provider health state. | **Fixed** | `test_secret_containment.py::test_a_provider_registry_error_never_records_a_url_borne_credential`, `::test_credentials_carried_in_a_query_string_are_scrubbed_from_log_values` |
| SEC-2026-09-07 | Medium | `market/robinhood_chain_feed.py` | A Uniswap **v4** `Swap` log identifies its pool only by a pool id in `topics[1]`; the emitting contract is the PoolManager. `parse_swap_log` looked the pool id up but never checked `log["address"]`, so any contract could emit a log claiming an allowlisted pool id and have its price accepted as a real tick. The subscription filter asks the endpoint to restrict by address, but this module already declines to trust the endpoint (it verifies the chain id), so it must not trust it here either. v3 was unaffected — there the emitter *is* the allowlisted pool. | **Fixed** | `test_robinhood_chain_boundary.py::test_a_v4_swap_from_a_contract_other_than_the_pool_manager_is_rejected` |
| SEC-2026-09-08 | Medium | `agents/meta.py` | `MetaAgentDecision.rationale` and `risk_flags` were unbounded model-authored text. A 500 KB rationale validated fine and was then persisted verbatim into `TradeProposal.thesis`, the hash-chained risk audit JSONL, the runtime JSONL, the Postgres `payload` column and every Redis publish. It cannot change a decision, but it is unbounded attacker-influenced text crossing a trust boundary into durable storage. | **Fixed** | `test_llm_cannot_relax_risk.py::test_meta_agent_decision_bounds_model_authored_text` |
| SEC-2026-09-09 | Medium | `docker-compose.yml` | `hummingbot-api` — a service that places orders and holds exchange credentials, guarded only by HTTP Basic Auth whose `USERNAME`/`PASSWORD` **default to empty** — published `8000:8000` on all host interfaces. `postgres`, `redis`, `grafana` (with anonymous Viewer access explicitly enabled), `prometheus` and `loki` did the same. | **Fixed** | n/a (compose config; verified by inspection) |
| SEC-2026-09-10 | Medium | `docker-compose.yml` | `hummingbot-api` carried `env_file: [.env]`, injecting **every** credential this stack owns (Anthropic, Dune, Perplexity, CryptoPanic, LunarCrush, altFINS, CoinGecko, CMC, Postgres) into a third-party `:latest` image that needs none of them. The service's explicit `environment:` block already supplies what it actually uses. | **Fixed** | n/a (compose config; verified by inspection) |
| SEC-2026-09-11 | Medium | `docker-compose.yml`, `ops/promtail.yml` | `promtail` mounts `/var/run/docker.sock`. `:ro` on a unix socket does not make the Docker API read-only — it is a bidirectional request channel, so this grants the container root-equivalent host access. The same file explicitly refuses the socket for `hummingbot-api` on exactly these grounds. | **Open** | — |
| SEC-2026-09-12 | Medium | CI | `pip-audit --skip-editable` currently fails: the resolved environment's own `pip` 24.0 carries 7 advisories (PYSEC-2026-196/1795/1796/2875/2876/3721). The `security` CI job is therefore red on every run, which trains reviewers to ignore it. | **Open** | — |
| SEC-2026-09-13 | Low | CI, `pyproject.toml` | Dev tooling is unpinned (`ruff>=0.5`). The formatter's style changed between ruff releases, so `ruff format --check .` in CI drifts red without any source change (41 files at the time of review). | **Open** | — |
| SEC-2026-09-14 | Low | `docker-compose.yml` | Every non-app image floats on a mutable tag (`timescale/timescaledb:latest-pg16`, `hummingbot/hummingbot-api:latest`, `grafana/*:latest`, `prom/prometheus:latest`, `emqx:5`, `postgres:16`, `redis:7-alpine`), against the threat model's "pinned versions/commits where practical". The application `Dockerfile` correctly pins its base by digest. | **Open** | — |
| SEC-2026-09-15 | Low | `execution/robinhood_chain.py` | `EvmJsonRpcClient` opens a **new** `httpx.AsyncClient` per call when no client is injected, so the `eth_chainId` verification is not bound to the connection that later runs `eth_estimateGas`/`eth_call`/`eth_getTransactionCount`. A load-balanced or rebound endpoint could answer the check and the simulation from different chains. Impact is bounded because nothing signs. | **Open** | `test_robinhood_chain_boundary.py::test_the_chain_id_is_verified_on_the_same_connection_that_subscribes` (asserts the *feed* does bind them) |
| SEC-2026-09-16 | Low | `execution/robinhood_chain.py` | `prepare_swap` allowlists the router (`to`) but passes `calldata` and `value_wei` through entirely unvalidated — no method-selector allowlist, no recipient check, no `minAmountOut`/deadline check, and `value_wei` is not bounded by `max_notional_usd`. Scaffolding only (nothing calls it), but it is the file the future signer will consume. | **Open** | — |
| SEC-2026-09-17 | Low | `market/adapters.py`, `runtime.py` | `KrakenTickerProvider` does not filter ticks by the requested symbol (`KrakenBookProvider` does), and `PaperRuntime._next_tick` returns the first tick the stream yields. A venue that answers a `BTC/USD` subscription with an `ETH/USD` tick would have the pipeline derive its asset from `tick.symbol`. It fails closed downstream — reference prices are fetched for the *requested* asset, so the mismatch trips `no_independent_reference_price` — but it fails closed by accident rather than by check. | **Open** | — |
| SEC-2026-09-18 | Low | `risk.py`, `risk_audit.py` | `RISK_LIMIT_FIELDS` covers every limit the `RiskEngine` itself enforces (verified exhaustively by test), but `policy_version` does not cover the limits enforced *around* it: `pretrade_*`, `execution_min_notional_usd`, `execution_lot_step`, `execution_max_slippage_bps`, `max_nav_drift_bps`, `max_reference_divergence_bps`, `max_market_data_age_seconds`, `robinhood_chain_max_*`. Two audit records with identical `policy_version` can therefore come from runs with the pre-trade gate on and off. | **Open** | `test_halt_controls_cannot_be_bypassed.py::test_policy_version_moves_with_every_declared_risk_limit` |
| SEC-2026-09-19 | Low | `market/robinhood_chain_feed.py` | A single malformed log kills the feed for good: `log["data"]` raises `KeyError`, `bytes.fromhex` raises `ValueError`, `int(str(...), 16)` raises `ValueError`, and none are caught (unlike the Kraken feed's reconnect loop). Fail-closed, but a hostile endpoint can end the venue feed with one message. | **Open** | — |
| SEC-2026-09-20 | Low | `eventing.py` | `runtime_events.symbol` is `String(32)` while `MarketTick.symbol` comes from the venue unbounded. An over-long venue symbol fails the insert, which fails the sink, which fails the cycle. Fail-closed, but it is a provider-controlled string reaching a schema constraint. | **Open** | — |
| SEC-2026-09-21 | Informational | `cli_check.py` | `traderstack-check-config` still reports `ANTHROPIC_API_KEY` as "not yet wired into the continuous runtime (Epic 6)" and altFINS as "no adapter wired yet". Both are now wired. Operator-facing output that understates what is live. (Flagged to the docs/consistency agent rather than changed here.) | **Fixed** (integration pass: `cli_check.py` now reports meta-agent mode/model/budgets, altFINS, provider quotas, execution settings and every kill-switch channel) | `tests/test_cli_check.py` |

No **critical** findings. No hardcoded credentials, no injection sinks (every
SQL statement is SQLAlchemy-parameterised; there is no `eval`, `exec`, `pickle`,
`yaml.load`, `subprocess` or shell interpolation anywhere in `src/`), and
`bandit -r src -ll` reports nothing.

---

## 2. Invariants attacked, and what happened

### 2.1 No LLM path can relax risk — **holds**

Traced every field a meta-agent reply can reach: `MetaAgentDecision` →
`MetaAgentCall` → `MetaAgentReview` → `MetaAgentReviewer.apply` →
`PipelineResult`.

Attacks attempted and **all rejected**:

* extra fields naming risk outputs (`approved_notional_usd`, `side`, `asset`) —
  `extra="forbid"` rejects the whole reply rather than dropping the key, so it
  fails closed;
* `confidence_delta` of `10_000`, `-10_000`, `Infinity` and `NaN` — pydantic's
  `ge/le` comparison is `False` for NaN and Infinity, so all four are rejected;
* `"approve": "yes please"` — rejected, not coerced;
* six unicode/whitespace/control payloads in `rationale` (zero-width space,
  RTL override, directional isolates, CR/LF log-record injection, NBSP padding,
  whitespace-only, ANSI/bell/backspace terminal control bytes), each crossed
  with the extreme legal deltas `±0.15`.

In every case `approved_notional_usd`, `RiskResult.decision`,
`RiskResult.reasons`, `RiskResult.policy_version`, `proposal.side`,
`proposal.asset`, `proposal.requested_notional_usd` and the whole
`PaperOrderIntent` came back byte-identical. The structural reason is that
`MetaAgentReviewer.apply` calls `model_copy(update={"confidence": adjusted})` on
the *proposal only*, and `adjusted` is clamped to `[0, 1]` — and, decisively,
the risk engine has already run and sized the order before the model is asked
anything, so an approval is only ever permission to keep risk the deterministic
layer had already granted. `model_copy` cannot be turned against this because
the reviewer, not the model, chooses the update dict.

Fail-closed paths confirmed: veto, exception, timeout, exhausted budget, absent
client, and an evidence packet that cannot be built all suppress the paper
order in veto mode; advisory mode changes nothing at all.

The Perplexity adapter was checked the same way — it is model text parsed into
numbers. It forces a JSON-schema response, type-checks each field
(`isinstance` on numeric/bool/int), clamps `event_score` to `[0, 1]` and
`item_count` to `>= 0`, and raises on prose that is not the schema. Free-form
model output cannot become a feature value.

**One real gap found:** the text fields themselves were unbounded
(SEC-2026-09-08). Fixed.

### 2.2 Prompt-injection boundary — **holds**

Each intelligence adapter was fed a payload whose every string field carried an
injection marker (Dune `note`/`query_name`/`column_names`/`execution_id`,
LunarCrush `name`/`title`/`categories`, CryptoPanic `title`/`description`/
`slug`, altFINS `signalName`/`signalKey`/`symbol`, Perplexity
`citations`/`reasoning`). No marker survives into any `*Snapshot`, into
`AssetFeatureVector`, or into `EvidencePacket`. Every adapter reduces its source
to bounded numbers; the only free text in the packet is the deterministic
strategy rationale this repository generates itself
(`"MA separation=0.0123"`-style).

The system prompt is a frozen, content-addressed constant with no interpolation
points, and `PromptRegistry.register` refuses to re-register a name with
different text. `EvidencePacket`'s field set is asserted exactly, so a future
free-text field cannot be added without failing this test.

Structured logging was reviewed for leakage: the one place external text lands
verbatim is `RuntimeResult.candle_error` / `intelligence_error` / `book_error`
and the `runtime_cycle_failed` log line, all of which carry
`f"{type(exc).__name__}: {exc}"`. That is bounded by the exception's own
message; the credential-in-URL case is now scrubbed (SEC-2026-09-06), and
provider payload text does not reach these because
`IntelligenceOrchestrator._fetch_one` swallows provider exceptions entirely.
Prometheus label values were checked for cardinality/injection: every `source`,
`reason` and `outcome` label comes from a fixed vocabulary or from configuration,
never from a provider.

### 2.3 Secrets — **holds after fixes**

All 11 `SecretStr` fields on `Settings` were loaded with unique markers and
searched for across `repr(settings)`, `str(settings)`, `model_dump(mode="json")`,
`traderstack-check-config` output, `RuntimeResult`, and the audit JSONL. None
appear. Every `get_secret_value()` call site was reviewed: all eleven are in
`cli.py` (or `cli_check.py`'s presence check) and hand the plain string straight
into an adapter constructor, never into a model that gets dumped.

Credentials in transit: CoinGecko, CoinMarketCap, Dune, LunarCrush, altFINS,
Perplexity and Anthropic all authenticate by **header**; Hummingbot uses httpx
`auth=(user, pass)` rather than a URL. Only CryptoPanic uses a query parameter,
which is its API's only option — hence the scrubbing fix rather than a
relocation. `HummingbotHttpError` deliberately carries only a status code, never
a response body.

httpx redirects were checked specifically: `follow_redirects` is never set, and
httpx's default is `False`, so no adapter can be redirected to another host
while still carrying its `Authorization` header.

Redaction key-name edge cases now covered by test: `apiKey`, `API-KEY`,
`X-API-KEY`, `x_api_key`, `Authorization`, `auth`, `auth_token`, `credential`,
`credentials`, `bearer`, `password`, `passwd`, `Cookie`, `client_secret`, plus
nested dicts, lists and tuples at depth.

### 2.4 Kill switch and circuit breaker cannot be bypassed — **holds after fix**

No code path clears the sentinel file, and no public method on `KillSwitch` or
`RiskEngine` looks like an in-process release (asserted by reflection). The
SIGUSR1 latch has exactly one clearer, `_reset_signal_latch_for_tests`, which is
private and test-only; a signalled halt survives for the life of the process and
was confirmed to reject through a real `RiskEngine.evaluate`.
`traderstack-resume` is a separate console entry point that only unlinks a file.

`RiskEngine` is a frozen dataclass, so its `settings` and `kill_switch`
references cannot be swapped at runtime; with `Settings` now frozen too
(SEC-2026-09-04), a relaxed `model_copy` is inert. An engine constructed without
a live switch still honours the static `KILL_SWITCH` flag, so an un-wired engine
is no less safe.

The circuit breaker cannot be talked down: a winning trade recorded during a
suspension does not untrip it, and only the configured cool-down clears it.

`policy_version` was verified to move for **all 19** declared risk limits, and
the test asserts the declared set equals `RISK_LIMIT_FIELDS`, so adding a limit
without adding it to the digest fails. The limits enforced outside the engine
remain outside the digest — SEC-2026-09-18.

**One real gap found:** the Redis channel was inert (SEC-2026-09-03). Fixed.

### 2.5 Idempotency and replay — **holds after fixes**

* A replayed runtime event is idempotent at the sinks: the audit JSONL is
  append-only by design, and `PostgresCandleStore` upserts `ON CONFLICT DO
  NOTHING`.
* A duplicate fill id — repeated three times inside one page and again on the
  next pass — is applied exactly once; `processed_fill_ids` is persisted with
  the ledger, so it survives a restart.
* A reconciliation row with a spoofed `order_id` that matches a real ledger
  order is bounded three ways: asset and side must match, the cumulative fill
  cannot exceed `requested_quantity`, and the lifecycle transition table refuses
  to reopen a terminal order. A fill referencing an unknown order raises rather
  than creating one.
* A crafted Hummingbot response **did** break two things (SEC-2026-09-01,
  SEC-2026-09-02). Both fixed; `_number` now also refuses `bool` (which
  `isinstance(x, int)` had accepted as 1.0).
* Negative quantities and prices were already refused by `Field(gt=0)`; NaN was
  refused by the same constraint; only `+Infinity` slipped through, and now does
  not.
* `client_order_id` is a deterministic blake2s digest of `decision_id`, so a
  restart mints the same key, and `IdempotentSubmitter` refuses any decision that
  already has a ledger order in **any** state.

### 2.6 Robinhood Chain path — **holds after fix**

`keccak256` was cross-checked against an independent implementation
(PyCryptodome `Crypto.Hash.keccak`, `digest_bits=256`) over 509 inputs including
every sponge-padding boundary (135/136/137/271/272 bytes and 500 random
lengths): zero mismatches. Six digests are now pinned in the test suite, chosen
because they are independently verifiable from published sources — `keccak256("")`,
the ERC-20 `Transfer` and `Approval` topics, and the Uniswap v3 `Swap` topic
`0xc42079f9…fbcca67`, which the module derives rather than hardcodes.

Note on the digest quoted in the review brief: the correct Keccak-256 of `"abc"`
is `4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45`. The brief's
`4e03657aea45a94fc7d47b3d38fbaa33…` diverges after the 11th byte and does not
match either Keccak-256 or SHA3-256 of `"abc"`; the verified value is what is
pinned.

Malformed-log handling verified: `removed: true`, empty/absent/`None` topics, a
v4 log with only one topic, a foreign topic0, truncated data (`0x`, `0x00`, four
words where five are needed), a zero `sqrtPriceX96`, and an `int128` field
carrying an out-of-range value are all either dropped or raise
`OnChainFeedError` — none decode into a usable price. `pool_price` was probed at
`sqrt_price_x96 = 1`, `2^96`, `2^160-1` and `2^256-1` and neither overflows nor
returns a non-positive or non-finite price; the inverted branch raises on a zero
price, and the non-inverted branch is caught by `SwapEvent.price`'s `gt=0`.
Pool ids and addresses are normalised to lowercase at configuration time and at
lookup, so case cannot be used to evade the allowlist; a malformed pool
identifier is refused when the config is parsed, not when a log arrives.

Chain-id spoofing between the check and the subscribe: in the **feed** the
`eth_chainId` call, the mismatch check and the `eth_subscribe` all happen on one
`self.connect(...)` context (asserted by source inspection), so there is no
window. In the **executor** there is one — SEC-2026-09-15.

Nothing signs or broadcasts: neither module references `eth_sendTransaction`,
`eth_sendRawTransaction`, `eth_sign`, `eth_signTransaction`, `personal_sign`,
`eth_signTypedData`, `private_key`, `mnemonic` or `keystore`;
`EvmJsonRpcClient`'s public surface is exactly six read/simulate methods;
`prepare_swap` returns an `UnsignedSwapTransaction` with no signature field; and
`trading_mode="live"` is rejected outright. All asserted by test so a future
signing method fails the suite.

**One real gap found:** v4 emitter spoofing (SEC-2026-09-07). Fixed.

### 2.7 Fail-closed on parse errors — **holds after fixes**

Every external JSON parse was walked:

| Parser | Malformed body | Verdict |
| --- | --- | --- |
| `reconcile._rows` | returned `[]` for an unreadable envelope | **was fail-open** → fixed |
| `reconcile._number` | accepted `inf`/`NaN` | **was fail-open** → fixed |
| `reconcile._text` | raises when required | good |
| `reconcile._side` | raises on an unknown side | good |
| `reconcile._map_state` | unknown status → `None` → row skipped | acceptable (a status we cannot map is not evidence of a transition) |
| `KrakenCandleProvider.fetch` | `TypeError` on a non-list, `KeyError` on a missing OHLC key; `Candle` validators reject non-positive and inconsistent OHLC | good |
| `parse_kraken_ticker` / `parse_kraken_book_message` | strict `isinstance` on every field, returns `None` rather than a partial tick | good |
| `CoinGecko` / `CoinMarketCap` | `isinstance` guards on every price; a non-dict payload raises | good |
| `Dune` / `LunarCrush` / `CryptoPanic` / `altFINS` | each raises `TypeError`/`ValueError` on an unexpected shape | good |
| `Perplexity` | raises on non-JSON, non-object, or wrongly-typed fields | good |
| `Anthropic` (`agents/claude.py`) | raises on a non-dict body, a non-list `content`, a missing text block, and on `stop_reason` in `{refusal, max_tokens}` | good |
| `reconciliation._extract_nav` | raises on a non-dict, a missing account/connector, a non-numeric balance, or a negative total; `NaN` is caught by `Field(ge=0)` one step later | good |
| swap-feed decoder | see §2.6 | good |
| `JsonPortfolioCheckpointStore` / `JsonExecutionLedgerStore` | `model_validate_json` raises on a corrupt file | good |
| `risk_audit.verify_chain` | treats a malformed line as tampering | good |

The one place a "safe-looking default" remains by design is intelligence
absence: a news provider that fails yields `news=None`, which merges as
`event_score=0, adverse_event=False`. That is mitigated only by
`INTELLIGENCE_REQUIRED`, which **defaults to `false`** — see residual risks.

---

## 3. Container, CI and dependencies

**Good as found.** The application `Dockerfile` is a multi-stage build on a
digest-pinned base, runs as uid 10001, installs no build toolchain into the
runtime layer, takes no secrets as build args, and `.dockerignore` excludes
`.env`, `.env.*`, `var/` and `.git`. The `app` compose service is `read_only`
with `tmpfs:/tmp`, `no-new-privileges`, and CPU/memory limits. The compose file
already refuses upstream Hummingbot's Docker-socket mount, with a written
rationale. `.claude/hooks/session-start.sh` is `set -euo pipefail`, gated on
`CLAUDE_CODE_REMOTE`, and pipes nothing to a shell. No `.env` is tracked in git;
`.env.example` contains placeholders only.

**Changed.** Every published port is now bound to `127.0.0.1` (SEC-2026-09-09);
`hummingbot-api` no longer receives the whole `.env` (SEC-2026-09-10) and gained
`no-new-privileges`.

**Left open.** The promtail Docker socket (SEC-2026-09-11), the failing
`pip-audit` job (SEC-2026-09-12), unpinned dev tooling (SEC-2026-09-13) and
floating image tags (SEC-2026-09-14).

**Dependencies.** `pip-audit --skip-editable` reports advisories only against
the environment's own `pip`; no runtime dependency (`pydantic`,
`pydantic-settings`, `httpx`, `websockets`, `structlog`, `sqlalchemy`,
`asyncpg`, `redis`, `prometheus-client`) has a known advisory. Two
dependency-specific surfaces were checked by hand rather than by scanner:

* **`websockets` message size.** Both Kraken feeds and the swap feed use
  `websockets.connect(...)` without overriding `max_size`, so the library's 1 MiB
  default applies and an oversized frame raises rather than being buffered. The
  Kraken feeds additionally cap read time with `asyncio.wait_for` and reconnect
  with jittered backoff; the swap feed has no reconnect loop (SEC-2026-09-19).
* **`httpx` cross-host redirects.** Confirmed that no client sets
  `follow_redirects=True` anywhere, so a provider cannot 302 an
  `Authorization`-bearing request to a host of its choosing.

---

## 4. Residual risks the operator must accept or address before live capital

These are architectural or operational, not code defects. Each must be closed or
explicitly accepted before any real money reaches this system.

1. **No signing service exists.** `RobinhoodChainExecutor` stops at an unsigned
   transaction and `trading_mode="live"` is rejected outright, exactly as
   ADR-0001 requires — but that means there is no on-chain execution path at all.
   The isolated signer / smart-account with spending caps and allowlisted
   contracts (Roadmap Phase 8) is unbuilt. Anything that consumes an
   `UnsignedSwapTransaction` must re-verify chain id, nonce and gas itself
   (SEC-2026-09-15) and must validate the calldata (SEC-2026-09-16); this
   repository does none of that for it.
2. **Hummingbot has no client-order-id.** Verified: `hummingbot-api`'s
   `TradeRequest` has no such field, so the venue cannot deduplicate for us. The
   persistent `ExecutionLedger` is the *only* duplicate guard, and
   `venue_knows_order` falls back to matching pair/side/quantity — which cannot
   distinguish our order from an identical one placed by anything else on the
   same account. **The bot must have a dedicated subaccount with no other
   activity**, or the fallback will misidentify a stranger's order as ours (or,
   worse, ours as a stranger's).
3. **Redis-unreachable means halt.** Now genuinely true (SEC-2026-09-03), which
   is a behaviour change an operator must plan for: with
   `KILL_SWITCH_REDIS_ENABLED=true`, a Redis outage stops all new risk until
   Redis returns. That is the correct trade, but it makes Redis availability a
   hard dependency of trading, and it is off by default.
4. **Grafana anonymous access.** `GF_AUTH_ANONYMOUS_ENABLED=true` with Viewer
   role is still set. It is now loopback-only, but anyone with host access — or
   any future change that re-publishes the port — reads live NAV, positions and
   risk state without authenticating. Turn it off before this leaves a laptop.
5. **`INTELLIGENCE_REQUIRED` defaults to `false`.** With the default, a total
   intelligence outage degrades silently to `adverse_event=False` and the cycle
   trades on market data alone. The adverse-news block is only as good as the
   providers being up, and nothing distinguishes "no adverse news" from "no
   news".
6. **Reconciled fill prices have no sanity bound.** The planner enforces
   `EXECUTION_MAX_SLIPPAGE_BPS` against the validated tick on the way *out*, but
   a fill arriving through reconciliation is booked at whatever price the venue
   reports. A finite but absurd price (say `1e30`) still inflates NAV, and NAV
   drives proposal sizing (`nav_usd * demonstration_notional_pct`). Non-finite
   values are now rejected; a bounded plausibility check against the last mark
   is a genuine design change and is left to the owning agent.
7. **Promtail holds the Docker socket** (SEC-2026-09-11). Use a socket proxy, or
   switch promtail to the container log files it already mounts.
8. **CI's security job is red** (SEC-2026-09-12) and its format job drifts
   (SEC-2026-09-13). A permanently-failing security gate is worse than no gate.
9. **Non-app services are unhardened.** Only `app` has `read_only`,
   `no-new-privileges` (now also on `hummingbot-api`) and resource limits.
   Postgres, Redis, Grafana, Loki and Promtail have none, and all float on
   mutable tags (SEC-2026-09-14).
10. **The paper/live separation is enforced in three places, not one.**
    `build_service` rejects non-paper mode, `HummingbotPaperExecutor` requires a
    `_paper_trade` connector, and `RobinhoodChainExecutor` rejects `live`. There
    is no single choke point, so a fourth execution path added later could miss
    all three.
11. **`policy_version` under-describes the policy** (SEC-2026-09-18). Two audit
    records with the same policy version can come from materially different
    configurations.
12. **The audit trail is append-only by convention, not by permission.** The
    hash chain detects tampering after the fact; nothing prevents a process with
    write access from truncating the file and starting a fresh valid chain. A
    genuinely immutable sink (append-only filesystem attribute, WORM object
    storage, or an external log service) is required before the trail can be
    treated as evidence.

---

## 5. Files changed by this review

```
src/traderstack/agents/meta.py                  bound rationale/risk_flags
src/traderstack/cli.py                          wire the Redis halt channel
src/traderstack/config.py                       Settings frozen
src/traderstack/execution/ledger.py             ExecutionFill: allow_inf_nan=False
src/traderstack/execution/reconcile.py          _rows fail-closed; _number finite-only
src/traderstack/killswitch.py                   enabled-without-client => engaged
src/traderstack/logging_config.py               wider key pattern; query-param scrubbing
src/traderstack/market/registry.py              scrub recorded provider errors
src/traderstack/market/robinhood_chain_feed.py  v4 emitter must be the PoolManager
docker-compose.yml                              loopback ports; no .env to hummingbot-api
tests/security/*                                6 new modules, 150 tests
tests/test_robinhood_chain_feed.py              pass the pool manager to parse_swap_log
```
