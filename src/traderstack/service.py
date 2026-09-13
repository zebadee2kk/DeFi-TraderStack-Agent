import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import structlog

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionFill, ExecutionLedger, ExecutionOrder
from traderstack.execution.paper_fill import PaperFillSimulator, PaperFillStatus
from traderstack.execution.paper_perp import PaperPerpBook
from traderstack.execution.paper_perp_feed import PaperPerpFeed, PaperPerpVenueName
from traderstack.execution.reconcile import ExecutionReconciliationResult
from traderstack.health import RuntimeHealth

# --- risk plane (Epic 7) ---
from traderstack.killswitch import KillSwitch
from traderstack.market.providers import EdgeFeedCollector
from traderstack.metrics import (  # --- observability (Epic 9) ---
    record_event_sink_failure,
    record_paper_fill,
    record_portfolio_snapshot,
)
from traderstack.opportunity_funnel import (  # --- opportunity funnel (#131) ---
    DIAGNOSTIC_WITHHELD_STATUS,
    OpportunityFunnel,
)
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.reconciliation import ReconciliationResult
from traderstack.risk_audit import JsonlRiskAuditTrail
from traderstack.runtime import PaperRuntime, RuntimeResult

_log = structlog.get_logger("traderstack.service")  # observability (Epic 9)

ResultHandler = Callable[[RuntimeResult], Awaitable[None]]
PortfolioHandler = Callable[[InMemoryPortfolioBook], Awaitable[None]]


# --- execution hardening (Epic 8) ---
class ExecutionReconcilerProtocol(Protocol):
    async def reconcile_state(
        self, ledger: ExecutionLedger, portfolio: InMemoryPortfolioBook
    ) -> ExecutionReconciliationResult: ...


class PortfolioReconcilerProtocol(Protocol):
    async def reconcile(self, portfolio: InMemoryPortfolioBook) -> ReconciliationResult: ...


class LedgerPersistence(Protocol):
    async def save(self, ledger: ExecutionLedger) -> None: ...


@dataclass
class ContinuousPaperService:
    runtime: PaperRuntime
    portfolio: InMemoryPortfolioBook
    symbols: tuple[str, ...]
    submit: bool = False
    cycle_interval_seconds: float = 5.0
    error_backoff_seconds: float = 5.0
    on_result: ResultHandler | None = None
    on_portfolio: PortfolioHandler | None = None
    execution_ledger: ExecutionLedger | None = None
    health: RuntimeHealth = field(default_factory=RuntimeHealth)
    # --- risk plane (Epic 7) ---
    # Out-of-process operator halt, re-probed at the start of every cycle and
    # consulted live by the risk engine.
    kill_switch: KillSwitch | None = None
    # Append-only hash-chained record of every risk decision the cycle produced.
    risk_audit: JsonlRiskAuditTrail | None = None
    # The limits in force, stamped into each audit record.
    settings: Settings | None = None
    # --- execution hardening (Epic 8) ---
    execution_reconciler: ExecutionReconcilerProtocol | None = None
    portfolio_reconciler: PortfolioReconcilerProtocol | None = None
    ledger_store: LedgerPersistence | None = None
    reconcile_interval_seconds: float = 60.0
    # --- paper fill simulation ---
    # Books ALLOW'd paper_order intents into the local book without Hummingbot.
    # Compose `app.command` has no --submit; this is the paper PnL path.
    paper_fill_simulator: PaperFillSimulator | None = None
    # --- paper perp / hedge path ---
    # Opt-in. After a spot paper fill, hedge only with an explicit venue
    # perp mid from paper_perp_feed (Hyperliquid midPx / BitMEX midPrice).
    # Kraken spot mid is never substituted. Same-venue funding prints
    # are applied on a schedule. Snapshot mids are not PIT basis.
    paper_perp_book: PaperPerpBook | None = None
    paper_perp_feed: PaperPerpFeed | None = None
    _paper_perp_venue: dict[str, PaperPerpVenueName] = field(default_factory=dict, init=False)
    _paper_perp_last_funding_at: dict[str, datetime] = field(default_factory=dict, init=False)
    # --- paper-research edge data plane ---
    # Background WS collectors (Binance liquidations / optional bookTicker).
    # Failure here is informational: missing features, not a halt.
    edge_collectors: tuple[EdgeFeedCollector, ...] = ()
    # --- opportunity funnel (#131) ---
    # Diagnostic-only mode (OPPORTUNITY_DIAGNOSTIC_MODE): every control runs
    # unchanged and every decision is audited, but no paper fill is booked and
    # no venue submission is attempted. It can only withhold, never relax.
    diagnostic_mode: bool = False
    # Live per-run funnel: where each cycle stopped and why. Evidence only.
    opportunity_funnel: OpportunityFunnel = field(default_factory=OpportunityFunnel)
    # When set, a JSON snapshot of the funnel is rewritten after every cycle.
    opportunity_funnel_path: Path | None = None
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _cycle: int = field(default=0, init=False)  # observability (Epic 9): monotonic cycle counter
    _last_reconcile_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        # --- opportunity funnel (#131) ---
        self.opportunity_funnel.set_flags(diagnostic_mode=self.diagnostic_mode)

    def stop(self) -> None:
        self._stop_event.set()

    async def _run_edge_collector(self, collector: EdgeFeedCollector) -> None:
        try:
            await collector.collect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - research feed; never halt the paper cycle.
            _log.warning(
                "edge_collector_stopped",
                feed=collector.feed_name,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def run(self) -> None:
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        # --- durability (#67) ---
        # A torn checkpoint/ledger is halt, not a fresh start. Do not enter
        # the cycle loop: even one submission against an empty in-memory
        # ledger would double-execute an order the on-disk file forgot.
        if self.health.durable_state_error is not None:
            _log.error(
                "service_halted_corrupt_durable_state",
                reason=self.health.durable_state_error,
            )
            return
        collector_tasks = [
            asyncio.create_task(
                self._run_edge_collector(collector), name=f"edge:{collector.feed_name}"
            )
            for collector in self.edge_collectors
        ]
        try:
            await self._run_cycles()
        finally:
            for task in collector_tasks:
                task.cancel()
            if collector_tasks:
                await asyncio.gather(*collector_tasks, return_exceptions=True)

    async def _run_cycles(self) -> None:
        while not self._stop_event.is_set():
            # --- execution hardening (Epic 8) ---
            await self._maybe_reconcile()
            for symbol in self.symbols:
                if self._stop_event.is_set():
                    break
                await self._run_symbol_safely(symbol)
                if not self.health.healthy:
                    self.stop()
                    break
            if not self._stop_event.is_set():
                await self._sleep_or_stop(self.cycle_interval_seconds)

    # --- risk plane (Epic 7) ---
    async def _refresh_kill_switch(self) -> None:
        """Re-evaluate the operator halt at the start of every cycle."""

        if self.kill_switch is not None:
            await self.kill_switch.refresh()

    async def _record_risk_decision(self, result: RuntimeResult) -> None:
        """Append this cycle's risk decision to the immutable audit trail.

        The record carries the meta-agent review and execution outcome
        alongside the risk engine's own decision, so a record showing
        ``result.decision == ALLOW`` next to a meta-agent veto is legible on
        its own -- the risk engine approved the notional, and the review
        withheld it before anything reached the venue.
        """

        if self.risk_audit is None or self.settings is None:
            return
        proposal = result.pipeline.proposal
        risk_result = result.pipeline.risk_result
        if proposal is None or risk_result is None:
            return
        await self.risk_audit.arecord(
            proposal,
            risk_result,
            self.settings,
            meta_review=result.meta_review,
            execution_status=result.execution_status,
            execution_reason=result.execution_reason,
        )

    async def _run_symbol_safely(self, symbol: str) -> None:
        self._cycle += 1  # observability (Epic 9)
        decision_id = None  # observability (Epic 9)
        log = _log.bind(symbol=symbol, cycle=self._cycle)  # observability (Epic 9)
        try:
            await self._refresh_kill_switch()  # --- risk plane (Epic 7) ---
            result = await self.runtime.run_once(
                symbol,
                self.portfolio.snapshot(),
                # --- execution hardening (Epic 8) ---
                submit=self.submission_enabled,
            )
            # --- paper fill simulation ---
            # Apply after risk allow + meta-agent review (paper_order set) and
            # before mark-to-market / audit / checkpoint so NAV, daily PnL and
            # the risk trail see the fill on the same cycle.
            result = await self._maybe_apply_paper_fill(result)
            await self._maybe_apply_paper_perp_funding(symbol)
            asset = (
                result.pipeline.feature_vector.asset
                if result.pipeline.feature_vector is not None
                else symbol.split("/", 1)[0].upper()
            )
            # Rejected market data must not mutate NAV, marks, or drawdown state.
            if result.pipeline.accepted_market_data:
                self.portfolio.mark(asset, result.tick.last)
            # --- observability (Epic 9): portfolio gauges + one structured log line/cycle ---
            snapshot = self.portfolio.snapshot()
            record_portfolio_snapshot(snapshot.nav_usd, snapshot.cash_usd, snapshot.peak_nav_usd)
            if result.pipeline.proposal is not None:
                decision_id = str(result.pipeline.proposal.decision_id)
            log = log.bind(decision_id=decision_id)
            log.info(
                "runtime_cycle_completed",
                trading_mode=result.trading_mode,
                outcome="accepted" if result.pipeline.accepted_market_data else "rejected",
                rejection_reasons=result.pipeline.rejection_reasons,
                risk_decision=(
                    result.pipeline.risk_result.decision.value
                    if result.pipeline.risk_result is not None
                    else None
                ),
                execution_status=result.execution_status,
            )
            # --- end observability (Epic 9) ---

            if (
                result.execution_receipt is not None
                and result.pipeline.paper_order is not None
                and self.execution_ledger is not None
                # --- execution hardening (Epic 8) ---
                # The submitter registers the order under its client order id
                # before the venue call; only the bare-executor path needs this.
                and not self.execution_ledger.has_order_for_decision(
                    result.pipeline.paper_order.decision_id
                )
            ):
                receipt = result.execution_receipt
                intent = result.pipeline.paper_order
                self.execution_ledger.register_order(
                    ExecutionOrder(
                        order_id=receipt.order_id,
                        decision_id=intent.decision_id,
                        asset=intent.asset,
                        side=intent.side,
                        requested_quantity=receipt.amount,
                    )
                )

            await self._record_risk_decision(result)  # --- risk plane (Epic 7) ---
            await self._observe_opportunity(result, log)  # --- opportunity funnel (#131) ---

            # --- paper-trading acceptance (Epic 10) ---
            # The portfolio checkpoint is written BEFORE the event fan-out. It is
            # the local, durable state a restart resumes from, whereas on_result
            # fans out to remote sinks (Postgres/Redis) that can be down for a
            # long time. Persisting it afterwards let a database outage freeze
            # the checkpoint while the execution ledger -- persisted by the
            # submitter regardless -- kept advancing, so a restart during the
            # outage resumed a book that no longer matched its own orders.
            if self.on_portfolio is not None:
                await self.on_portfolio(self.portfolio)
            if self.on_result is not None:
                try:
                    await self.on_result(result)
                except (
                    Exception
                ):  # observability (Epic 9): count sink failures, keep failing loudly
                    record_event_sink_failure("on_result")
                    raise
            self.health.record_success(symbol)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - service boundary records and backs off.
            log.warning(
                "runtime_cycle_failed", error=f"{type(exc).__name__}: {exc}"
            )  # observability (Epic 9)
            self.health.record_error(symbol, exc)
            await self._sleep_or_stop(self.error_backoff_seconds)

    # --- execution hardening (Epic 8) ---
    @property
    def submission_enabled(self) -> bool:
        """New risk is only allowed when venue state is known to be reconciled.

        A block stops *submission* only: market data, decisions and auditing all
        keep running, and existing positions are untouched.
        """

        return (
            self.submit
            and not self.health.reconciliation_blocked
            and self.health.durable_state_error is None
            and not self.diagnostic_mode  # --- opportunity funnel (#131) ---
        )

    # --- opportunity funnel (#131) ---
    async def _observe_opportunity(self, result: RuntimeResult, log: Any) -> None:
        """Record where this cycle stopped in the funnel; never affects it."""

        funnel = self.opportunity_funnel
        funnel.set_flags(
            paper_fills_enabled=self.paper_fill_enabled,
            submission_enabled=self.submission_enabled,
        )
        observation = funnel.observe(result, now=datetime.now(UTC), ledger=self.execution_ledger)
        if self.diagnostic_mode:
            log.info(
                "opportunity_diagnosis",
                stage=observation.stage.value,
                gate=observation.gate.value if observation.gate is not None else None,
                category=observation.category.value,
                reasons=observation.reasons,
                explanation=observation.explain(),
            )
        if self.opportunity_funnel_path is not None:
            try:
                await asyncio.to_thread(funnel.write, self.opportunity_funnel_path)
            except Exception as exc:  # noqa: BLE001 - a diagnostic file must never fail the cycle.
                log.warning("opportunity_funnel_write_failed", error=f"{type(exc).__name__}: {exc}")

    # --- paper fill simulation ---
    @property
    def paper_fill_enabled(self) -> bool:
        """Local paper fills are new risk; the same gates as venue submit apply.

        Kill switch / meta-agent veto already null ``paper_order``. This also
        withholds when venue state is unreconciled or durable state is torn.
        Does **not** require ``--submit`` or Hummingbot.
        """

        return (
            self.paper_fill_simulator is not None
            and self.execution_ledger is not None
            and not self.health.reconciliation_blocked
            and self.health.durable_state_error is None
            and not self.diagnostic_mode  # --- opportunity funnel (#131) ---
        )

    async def _maybe_apply_paper_fill(self, result: RuntimeResult) -> RuntimeResult:
        if result.trading_mode != "paper":
            return result
        intent = result.pipeline.paper_order
        if intent is None:
            return result
        # --- opportunity funnel (#131) ---
        # Diagnostic mode withholds after every upstream control has had its
        # say, so the funnel still shows what *would* have been booked. The
        # kill switch stays the first explanation when it is engaged.
        if self.diagnostic_mode:
            reason = "diagnostic mode: paper fill withheld; upstream controls allowed this order"
            if self.kill_switch is not None and self.kill_switch.engaged:
                reason = "kill switch engaged; diagnostic mode also withholds"
            return result.model_copy(
                update={"execution_status": DIAGNOSTIC_WITHHELD_STATUS, "execution_reason": reason}
            )
        if self.paper_fill_simulator is None:
            return result
        if self.kill_switch is not None and self.kill_switch.engaged:
            return result.model_copy(
                update={
                    "execution_status": PaperFillStatus.WITHHELD.value,
                    "execution_reason": "kill switch engaged; paper fill withheld",
                }
            )
        if not self.paper_fill_enabled or self.execution_ledger is None:
            reason = "paper fill withheld: unreconciled or torn durable state"
            if self.health.durable_state_error is not None:
                reason = f"paper fill withheld: {self.health.durable_state_error}"
            elif self.health.reconciliation_blocked:
                reason = "paper fill withheld: reconciliation blocked"
            return result.model_copy(
                update={
                    "execution_status": PaperFillStatus.WITHHELD.value,
                    "execution_reason": reason,
                }
            )

        outcome = self.paper_fill_simulator.apply(
            intent,
            mid_usd=result.tick.mid,
            ledger=self.execution_ledger,
            portfolio=self.portfolio,
        )
        if self.ledger_store is not None:
            await self.ledger_store.save(self.execution_ledger)
        record_paper_fill(
            result.tick.symbol,
            intent.side.value,
            outcome.status.value,
            fee_usd=outcome.fee_usd,
        )
        # --- paper perp / hedge path ---
        # Do not pass result.tick.mid: that is the Kraken spot mid.
        # A missing venue mid is a skip, not an invented number.
        if outcome.applied and outcome.fill is not None and self.paper_perp_book is not None:
            await self._maybe_hedge_paper_perp(result, outcome.fill, intent.decision_id)
        return result.model_copy(
            update={
                "execution_status": outcome.status.value,
                "execution_reason": outcome.reason,
            }
        )

    async def _maybe_hedge_paper_perp(
        self, result: RuntimeResult, fill: ExecutionFill, decision_id: str
    ) -> None:
        """Hedge a spot paper fill only with an explicit venue perp mid."""

        if self.paper_perp_book is None:
            return
        quote = None
        if self.paper_perp_feed is not None:
            try:
                quote = await self.paper_perp_feed.fetch_mid(result.tick.symbol)
            except Exception as exc:  # noqa: BLE001 - skip, never invent a mid.
                _log.warning(
                    "paper_perp_mid_fetch_failed",
                    symbol=result.tick.symbol,
                    error=f"{type(exc).__name__}: {exc}",
                )
                quote = None
        # Never fall back to result.tick.mid (Kraken spot).
        perp_mid = quote.mid_usd if quote is not None else None
        hedge = self.paper_perp_book.maybe_hedge_spot_fill(
            fill,
            perp_mid_usd=perp_mid,
            decision_id=decision_id,
            ledger=self.execution_ledger,
        )
        if hedge.applied and quote is not None:
            self._paper_perp_venue[fill.asset.upper()] = quote.venue
            self._paper_perp_last_funding_at[fill.asset.upper()] = quote.observed_at
            _log.info(
                "paper_perp_hedged",
                asset=fill.asset,
                venue=quote.venue,
                source=quote.source,
                mid_usd=quote.mid_usd,
            )
        elif hedge.reason:
            _log.info(
                "paper_perp_hedge_skipped",
                asset=fill.asset,
                status=hedge.status.value,
                reason=hedge.reason,
            )

    async def _maybe_apply_paper_perp_funding(self, symbol: str) -> None:
        """Apply new same-venue funding prints to an open paper perp."""

        if self.paper_perp_book is None or self.paper_perp_feed is None:
            return
        asset = symbol.split("/", 1)[0].upper()
        if asset not in self.paper_perp_book.positions:
            return
        venue = self._paper_perp_venue.get(asset)
        since = self._paper_perp_last_funding_at.get(asset)
        if venue is None or since is None:
            return
        try:
            tape = await self.paper_perp_feed.fetch_funding_since(symbol, venue=venue, since=since)
        except Exception as exc:  # noqa: BLE001 - skip, never invent a rate.
            _log.warning(
                "paper_perp_funding_fetch_failed",
                symbol=symbol,
                venue=venue,
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        if not tape.settlements:
            return
        mark = None
        try:
            quote = await self.paper_perp_feed.fetch_mid(symbol)
        except Exception:  # noqa: BLE001 - missing mark uses entry price.
            quote = None
        if quote is not None and quote.venue == venue:
            mark = quote.mid_usd
        outcome = self.paper_perp_book.apply_funding(
            tape.settlements,
            asset=asset,
            mark_usd=mark,
        )
        if outcome.applied and tape.settlements:
            self._paper_perp_last_funding_at[asset] = max(ts for ts, _rate in tape.settlements)
            _log.info(
                "paper_perp_funding_applied",
                asset=asset,
                venue=venue,
                prints=len(tape.settlements),
                funding_pnl_usd=outcome.funding_pnl_usd,
            )

    async def _maybe_reconcile(self) -> None:
        if self.execution_reconciler is None and self.portfolio_reconciler is None:
            return
        now = time.monotonic()
        if (
            self._last_reconcile_at is not None
            and now - self._last_reconcile_at < self.reconcile_interval_seconds
        ):
            return
        self._last_reconcile_at = now
        await self.reconcile_now()

    async def reconcile_now(self) -> bool:
        """Run one reconciliation pass; returns True when state is clean.

        Any failure — transport error, order-state divergence or NAV drift past
        the configured threshold — blocks submission until a later pass is clean.
        """

        reasons: list[str] = []
        try:
            if self.execution_reconciler is not None and self.execution_ledger is not None:
                execution = await self.execution_reconciler.reconcile_state(
                    self.execution_ledger, self.portfolio
                )
                reasons.extend(execution.conflicts)
                if self.ledger_store is not None:
                    await self.ledger_store.save(self.execution_ledger)
                if execution.applied_fills and self.on_portfolio is not None:
                    await self.on_portfolio(self.portfolio)
            if self.portfolio_reconciler is not None:
                portfolio_state = await self.portfolio_reconciler.reconcile(self.portfolio)
                reasons.extend(portfolio_state.reasons)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - an unanswered venue is unreconciled state.
            self.health.record_reconciliation_failure(f"{type(exc).__name__}: {exc}")
            return False

        if reasons:
            self.health.record_reconciliation_failure("; ".join(reasons))
            return False
        self.health.record_reconciliation_success()
        return True

    async def _sleep_or_stop(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass
