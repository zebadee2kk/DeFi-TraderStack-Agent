"""``traderstack-soak``: the paper-trading acceptance soak runner (Epic 10).

Runs the **real** service wiring -- ``cli.build_service``, so the same pipeline,
risk engine, pre-trade gate, planner, idempotent submitter, execution ledger,
reconcilers, kill switch and audit trails a live paper run uses -- against the
seeded synthetic market and the fault-injection wrappers in this package. No
network, no database, no vendor credentials.

A run is bounded by ``--cycles`` or ``--seconds``, optionally follows a JSON
scenario that arms and disarms faults at chosen cycles, and always ends by
emitting a machine-readable acceptance report: cycles, outcomes by reason,
orders, fills, reconciliations, faults fired, health, audit-chain verification
and a Prometheus metrics snapshot.

The 24/7 window itself is an operator activity, not a test: see
docs/RUNBOOK.md, "24/7 acceptance soak", for how to run
``traderstack-soak --seconds 86400`` and what counts as a pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import REGISTRY
from pydantic import BaseModel, Field

from traderstack.acceptance.faults import (
    FaultBoard,
    FaultyCandleProvider,
    FaultyEventSink,
    FaultyIntelligence,
    FaultyReferenceProvider,
    FaultyVenueApi,
    FaultyVenueFeed,
    SentinelFileFault,
)
from traderstack.acceptance.market import SyntheticMarket
from traderstack.audit import JsonlAuditSink
from traderstack.candles import Candle
from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.circuit_breaker import StrategyCircuitBreaker
from traderstack.cli import ServiceOverrides, build_service
from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger, OrderLifecycleState
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.killswitch import KillSwitch
from traderstack.market.models import MarketSource, MarketTick
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk_audit import JsonlRiskAuditTrail, verify_chain
from traderstack.runtime import RuntimeResult
from traderstack.service import ContinuousPaperService

#: Metric families included in the report's snapshot. A curated list rather than
#: the whole registry so the report stays readable and stable across releases.
REPORTED_METRICS: tuple[str, ...] = (
    "traderstack_cycles_total",
    "traderstack_pipeline_outcomes_total",
    "traderstack_pipeline_rejections_total",
    "traderstack_risk_decisions_total",
    "traderstack_proposals_total",
    "traderstack_paper_orders_submitted_total",
    "traderstack_event_sink_failures_total",
    "traderstack_provider_calls_total",
    "traderstack_provider_breaker_state",
    "traderstack_kill_switch_engaged",
    "traderstack_reconciliation_blocked",
    "traderstack_runtime_healthy",
    "traderstack_portfolio_nav_usd",
)

#: Settings a soak run pins regardless of the ambient environment, so a run is
#: reproducible from its scenario file alone. The scenario's own ``settings``
#: block still wins over these.
_BASE_SETTINGS: dict[str, Any] = {
    "trading_mode": "paper",
    "venue_feed": "kraken",
    "kill_switch": False,
    "kill_switch_redis_enabled": False,
    "hummingbot_api_username": "soak",
    "hummingbot_api_password": "soak",
    "intelligence_required": False,
    # The synthetic history is short on purpose (a soak is about operational
    # behaviour, not strategy quality), so the walk-forward stage has too little
    # data and is not required.
    "pretrade_candle_count": 200,
    "pretrade_min_candles": 120,
    "pretrade_min_excess_return": -10.0,
    "pretrade_min_sharpe": -1_000.0,
    "pretrade_max_drawdown_pct": 1.0,
    "pretrade_min_trades": 0,
    "pretrade_require_walkforward": False,
    "provider_timeout_seconds": 1.0,
    "reference_price_cache_seconds": 0.0,
    "coingecko_calls_per_minute": None,
    "coinmarketcap_calls_per_minute": None,
    "coinmarketcap_calls_per_day": None,
}


# --- scenario ---------------------------------------------------------------


class FaultSchedule(BaseModel):
    """Arm one named fault at a cycle, optionally disarming it later."""

    fault: str
    arm_at_cycle: int = Field(default=0, ge=0)
    disarm_at_cycle: int | None = Field(default=None, ge=0)
    #: Auto-disarm after this many activations (independent of the cycle count).
    times: int | None = Field(default=None, gt=0)


class SoakScenario(BaseModel):
    """A reproducible soak run: market, duration, settings and fault schedule."""

    name: str = "baseline"
    description: str = ""
    seed: int = 7
    symbols: list[str] = Field(default_factory=lambda: ["BTC/USD"])
    cycles: int | None = Field(default=20, gt=0)
    seconds: float | None = Field(default=None, gt=0)
    cycle_seconds: float = Field(default=0.0, ge=0)
    #: Backoff after a failed cycle, matching `ContinuousPaperService`'s default.
    error_backoff_seconds: float = Field(default=5.0, ge=0)
    submit: bool = True
    starting_nav_usd: float = Field(default=10_000.0, gt=0)
    drift: float = 0.006
    volatility: float = Field(default=0.0008, gt=0)
    spread_bps: float = Field(default=4.0, gt=0)
    history: int = Field(default=200, gt=1)
    faults: list[FaultSchedule] = Field(default_factory=list)
    #: Extra ``Settings`` overrides, applied last.
    settings: dict[str, Any] = Field(default_factory=dict)
    #: Cycles the scenario expects the service to refuse to submit on. Purely
    #: descriptive: it documents intent in the report, it does not gate the pass.
    expects_rejections: bool = False

    @classmethod
    def load(cls, path: Path) -> SoakScenario:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


# --- report -----------------------------------------------------------------


class SoakReport(BaseModel):
    """Machine-readable outcome of one soak run."""

    scenario: str
    description: str = ""
    seed: int
    symbols: list[str]
    started_at: datetime
    finished_at: datetime
    elapsed_seconds: float
    cycles: int
    outcomes: dict[str, int] = Field(default_factory=dict)
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    risk_decisions: dict[str, int] = Field(default_factory=dict)
    risk_reasons: dict[str, int] = Field(default_factory=dict)
    execution_statuses: dict[str, int] = Field(default_factory=dict)
    orders_submitted: int = 0
    ledger_orders: int = 0
    ledger_order_states: dict[str, int] = Field(default_factory=dict)
    fills_applied: int = 0
    venue_posts: int = 0
    reconciliations: dict[str, int] = Field(default_factory=dict)
    faults_fired: dict[str, int] = Field(default_factory=dict)
    provider_breakers: dict[str, str] = Field(default_factory=dict)
    health: dict[str, Any] = Field(default_factory=dict)
    portfolio: dict[str, float] = Field(default_factory=dict)
    audit_chain_verified: bool = False
    audit_chain_error: str | None = None
    risk_audit_records: int = 0
    runtime_events: int = 0
    policy_version: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    passed: bool = False

    def render(self) -> str:
        lines = [
            f"Soak scenario: {self.scenario}",
            "=" * 60,
        ]
        if self.description:
            lines.append(self.description)
        lines.extend(
            [
                f"seed={self.seed}  symbols={','.join(self.symbols)}",
                f"cycles={self.cycles}  elapsed={self.elapsed_seconds:.2f}s",
                f"policy_version={self.policy_version}",
                "",
                "Outcomes",
                "-" * 60,
            ]
        )
        lines.extend(f"  {key:<34}{value:>6}" for key, value in sorted(self.outcomes.items()))
        lines.append("\nRejection reasons")
        lines.append("-" * 60)
        if self.rejection_reasons:
            lines.extend(
                f"  {key:<34}{value:>6}" for key, value in sorted(self.rejection_reasons.items())
            )
        else:
            lines.append("  (none)")
        lines.append("\nRisk decisions")
        lines.append("-" * 60)
        lines.extend(f"  {key:<34}{value:>6}" for key, value in sorted(self.risk_decisions.items()))
        lines.append("\nRisk reasons")
        lines.append("-" * 60)
        if self.risk_reasons:
            lines.extend(
                f"  {key:<34}{value:>6}" for key, value in sorted(self.risk_reasons.items())
            )
        else:
            lines.append("  (none)")
        lines.append("\nExecution")
        lines.append("-" * 60)
        lines.append(f"  orders submitted                  {self.orders_submitted:>6}")
        lines.append(f"  ledger orders                     {self.ledger_orders:>6}")
        lines.append(f"  venue POSTs                       {self.venue_posts:>6}")
        lines.append(f"  fills applied                     {self.fills_applied:>6}")
        for key, value in sorted(self.execution_statuses.items()):
            lines.append(f"  status {key:<27}{value:>6}")
        lines.append("\nReconciliation")
        lines.append("-" * 60)
        for key, value in sorted(self.reconciliations.items()):
            lines.append(f"  {key:<34}{value:>6}")
        lines.append("\nFaults fired")
        lines.append("-" * 60)
        if self.faults_fired:
            lines.extend(
                f"  {key:<34}{value:>6}" for key, value in sorted(self.faults_fired.items())
            )
        else:
            lines.append("  (none)")
        lines.append("\nAudit")
        lines.append("-" * 60)
        lines.append(f"  risk chain verified               {self.audit_chain_verified!s:>6}")
        lines.append(f"  risk audit records                {self.risk_audit_records:>6}")
        lines.append(f"  runtime events                    {self.runtime_events:>6}")
        lines.append("\nResult")
        lines.append("-" * 60)
        lines.append(f"  passed: {self.passed}")
        for failure in self.failures:
            lines.append(f"  FAIL: {failure}")
        return "\n".join(lines)


# --- runner -----------------------------------------------------------------


@dataclass
class SoakRunner:
    """Assembles the real service against the synthetic market and drives it."""

    scenario: SoakScenario
    workdir: Path
    board: FaultBoard = field(default_factory=FaultBoard)
    results: list[RuntimeResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir)
        self.symbols = tuple(self.scenario.symbols)
        self.settings = Settings(**{**_BASE_SETTINGS, **self.scenario.settings})
        self.market = SyntheticMarket(
            symbols=self.symbols,
            seed=self.scenario.seed,
            drift=self.scenario.drift,
            volatility=self.scenario.volatility,
            spread_bps=self.scenario.spread_bps,
            history=self.scenario.history,
        )
        self.reconcile_clean = 0
        self.reconcile_blocked = 0

    # --- assembly ----------------------------------------------------------

    def _tick_of(self, symbol: str) -> MarketTick:
        return self.market.tick(symbol)

    def _candles_of(self, symbol: str, resolution: str, count: int) -> tuple[Candle, ...]:
        return self.market.candles(symbol, count=count)

    async def build(self) -> ContinuousPaperService:
        board = self.board
        self.venue_feed = FaultyVenueFeed(tick_of=self._tick_of, board=board)
        self.references = tuple(
            FaultyReferenceProvider(
                name=name, price_of=self.market.price_of, source=source, board=board
            )
            for name, source in (
                ("coingecko", MarketSource.COINGECKO),
                ("coinmarketcap", MarketSource.COINMARKETCAP),
            )
        )
        self.candles = FaultyCandleProvider(candles_of=self._candles_of, board=board)
        self.venue_api = FaultyVenueApi(
            account_name=self.settings.hummingbot_account_name,
            connector_name=self.settings.hummingbot_connector_name,
            nav_usd=self.scenario.starting_nav_usd,
            board=board,
        )
        self.venue_client = self.venue_api.client()
        # The intelligence orchestrator is not built by build_service without
        # credentials, so the soak injects a failable one directly afterwards.
        self.intelligence = FaultyIntelligence(board=board)

        self.kill_sentinel = SentinelFileFault(
            "kill_switch_file", Path(self.settings.kill_switch_file)
        )
        # A leftover sentinel from a previous run would silently halt this one.
        self.kill_sentinel.path.unlink(missing_ok=True)
        board.register(self.kill_sentinel)

        audit_path = self.workdir / "audit" / "runtime.jsonl"
        self.audit_sink = FaultyEventSink(
            name="audit", delegate=JsonlAuditSink(audit_path), board=board
        )
        self.audit_path = audit_path

        async def on_result(result: RuntimeResult) -> None:
            self.results.append(result)
            await self.audit_sink(result)

        checkpoint_store = JsonPortfolioCheckpointStore(
            self.workdir / "state" / "portfolio.json",
            circuit_breaker=StrategyCircuitBreaker.from_settings(self.settings),
        )
        self.ledger = ExecutionLedger()
        self.ledger_store = JsonExecutionLedgerStore(
            self.workdir / "state" / "execution_ledger.json"
        )
        self.risk_audit = JsonlRiskAuditTrail(self.workdir / "audit" / "risk_decisions.jsonl")
        self.portfolio = InMemoryPortfolioBook(starting_nav_usd=self.scenario.starting_nav_usd)

        service = build_service(
            self.settings,
            submit=self.scenario.submit,
            cycle_seconds=self.scenario.cycle_seconds,
            portfolio=self.portfolio,
            on_result=on_result,
            checkpoint_store=checkpoint_store,
            kill_switch=KillSwitch.from_settings(self.settings),
            circuit_breaker=StrategyCircuitBreaker.from_settings(self.settings),
            risk_audit=self.risk_audit,
            execution_ledger=self.ledger,
            ledger_store=self.ledger_store,
            overrides=ServiceOverrides(
                venue=self.venue_feed,
                references=self.references,
                candles=self.candles,
                symbols=self.symbols,
                venue_client=self.venue_client,
            ),
        )
        service.runtime.intelligence = self.intelligence
        service.error_backoff_seconds = self.scenario.error_backoff_seconds
        self.service = service
        return service

    # --- driving -----------------------------------------------------------

    def _apply_schedule(self, cycle: int) -> None:
        for entry in self.scenario.faults:
            if entry.disarm_at_cycle is not None and entry.disarm_at_cycle == cycle:
                self.board.disarm(entry.fault)
            if entry.arm_at_cycle == cycle:
                self.board.arm(entry.fault, times=entry.times)

    async def run(self) -> SoakReport:
        service = await self.build()
        started_at = datetime.now(UTC)
        started = time.monotonic()
        deadline = started + self.scenario.seconds if self.scenario.seconds else None
        max_cycles = self.scenario.cycles
        cycle = 0
        try:
            while True:
                if max_cycles is not None and cycle >= max_cycles:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                self._apply_schedule(cycle)
                # Driven one cycle at a time (rather than via `service.run()`) so
                # a fault can be armed at an exact cycle boundary; the per-cycle
                # work below is the same the service loop performs.
                if service.execution_reconciler is not None:
                    clean = await service.reconcile_now()
                    self.reconcile_clean += int(clean)
                    self.reconcile_blocked += int(not clean)
                for symbol in self.symbols:
                    await service._run_symbol_safely(symbol)
                cycle += 1
                if not service.health.healthy:
                    break
                if self.scenario.cycle_seconds > 0:
                    await asyncio.sleep(self.scenario.cycle_seconds)
        finally:
            await self.venue_client.aclose()
            self.board.disarm_all()
        return self._report(started_at, time.monotonic() - started, cycle)

    # --- reporting ---------------------------------------------------------

    def _report(self, started_at: datetime, elapsed: float, cycles: int) -> SoakReport:
        outcomes: Counter[str] = Counter()
        rejection_reasons: Counter[str] = Counter()
        risk_decisions: Counter[str] = Counter()
        risk_reasons: Counter[str] = Counter()
        execution_statuses: Counter[str] = Counter()
        orders_submitted = 0
        for result in self.results:
            outcomes["accepted" if result.pipeline.accepted_market_data else "rejected"] += 1
            rejection_reasons.update(result.pipeline.rejection_reasons)
            if result.candle_error:
                outcomes["candle_error"] += 1
            if result.intelligence_error:
                outcomes["intelligence_error"] += 1
            if result.pipeline.risk_result is not None:
                risk_decisions[result.pipeline.risk_result.decision.value] += 1
                risk_reasons.update(result.pipeline.risk_result.reasons)
            if result.execution_status is not None:
                execution_statuses[result.execution_status] += 1
            if result.execution_receipt is not None:
                orders_submitted += 1

        error_cycles = int(
            REGISTRY.get_sample_value(
                "traderstack_cycles_total", {"symbol": self.symbols[0], "outcome": "error"}
            )
            or 0
        )
        outcomes["error_cycles"] = error_cycles

        order_states: Counter[str] = Counter(
            order.state.value for order in self.ledger.orders.values()
        )
        fills = sum(
            1 for order in self.ledger.orders.values() if order.state is OrderLifecycleState.FILLED
        )

        verification = verify_chain(self.risk_audit.path) if self.risk_audit.path.exists() else None
        runtime_events = (
            len(
                [
                    line
                    for line in self.audit_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            )
            if self.audit_path.exists()
            else 0
        )

        report = SoakReport(
            scenario=self.scenario.name,
            description=self.scenario.description,
            seed=self.scenario.seed,
            symbols=list(self.symbols),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            elapsed_seconds=elapsed,
            cycles=cycles,
            outcomes=dict(outcomes),
            rejection_reasons=dict(rejection_reasons),
            risk_decisions=dict(risk_decisions),
            risk_reasons=dict(risk_reasons),
            execution_statuses=dict(execution_statuses),
            orders_submitted=orders_submitted,
            ledger_orders=len(self.ledger.orders),
            ledger_order_states=dict(order_states),
            fills_applied=fills,
            venue_posts=self.venue_api.posts,
            reconciliations={"clean": self.reconcile_clean, "blocked": self.reconcile_blocked},
            faults_fired=self.board.fired(),
            provider_breakers=self._provider_breakers(),
            health={
                "healthy": self.service.health.healthy,
                "consecutive_errors": self.service.health.consecutive_errors,
                "last_error": self.service.health.last_error,
                "reconciliation_blocked": self.service.health.reconciliation_blocked,
                "last_reconciliation_error": self.service.health.last_reconciliation_error,
            },
            portfolio={
                "nav_usd": self.portfolio.nav_usd,
                "cash_usd": float(self.portfolio.cash_usd or 0.0),
                "peak_nav_usd": float(self.portfolio.peak_nav_usd or 0.0),
            },
            audit_chain_verified=bool(verification and verification.valid),
            audit_chain_error=verification.error if verification else "no risk decisions recorded",
            risk_audit_records=verification.records if verification else 0,
            runtime_events=runtime_events,
            policy_version=self.service.runtime.pipeline.risk_engine.policy_version,
            metrics=metrics_snapshot(),
        )
        report.failures = evaluate(report, self.ledger)
        report.passed = not report.failures
        return report

    def _provider_breakers(self) -> dict[str, str]:
        breakers: dict[str, str] = {}
        for provider in self.service.runtime.references:
            registry = getattr(provider, "registry", None)
            if registry is not None:
                breakers[registry.name] = registry.health().state.value
        candles = self.service.runtime.candles
        registry = getattr(candles, "registry", None)
        if registry is not None:
            breakers[registry.name] = registry.health().state.value
        return breakers


def metrics_snapshot() -> dict[str, float]:
    """Current values of the reported metric families, keyed ``name{labels}``."""

    snapshot: dict[str, float] = {}
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            base = sample.name.removesuffix("_created")
            if sample.name.endswith("_created") or base not in REPORTED_METRICS:
                continue
            labels = ",".join(f"{key}={value}" for key, value in sorted(sample.labels.items()))
            snapshot[f"{sample.name}{{{labels}}}" if labels else sample.name] = float(sample.value)
    return snapshot


def evaluate(report: SoakReport, ledger: ExecutionLedger) -> list[str]:
    """The acceptance criteria a soak run has to satisfy to count as a pass."""

    failures: list[str] = []
    if report.cycles == 0:
        failures.append("no cycles ran")
    if report.risk_audit_records and not report.audit_chain_verified:
        failures.append(f"risk audit chain did not verify: {report.audit_chain_error}")
    if report.risk_audit_records == 0 and report.cycles > 0 and report.risk_decisions:
        failures.append("risk decisions were made but none were recorded in the audit trail")
    if report.orders_submitted > report.ledger_orders:
        failures.append(
            f"{report.orders_submitted} submissions for only {report.ledger_orders} ledger orders"
        )
    decisions = [order.decision_id for order in ledger.orders.values()]
    if len(decisions) != len(set(decisions)):
        failures.append("a decision produced more than one venue order")
    if report.venue_posts < report.orders_submitted:
        failures.append("more receipts than venue submissions -- the ledger and venue disagree")
    if (
        report.runtime_events == 0
        and report.cycles > 0
        and not report.faults_fired.get("audit_sink_error")
    ):
        failures.append("no runtime events were persisted")
    return failures


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the paper-trading acceptance soak: the real service wiring against a "
            "synthetic market, with optional scheduled fault injection."
        )
    )
    parser.add_argument("--scenario", type=Path, default=None, help="JSON scenario file")
    parser.add_argument("--cycles", type=int, default=None, help="stop after this many cycles")
    parser.add_argument("--seconds", type=float, default=None, help="stop after this long")
    parser.add_argument("--cycle-seconds", type=float, default=None, help="delay between cycles")
    parser.add_argument("--seed", type=int, default=None, help="synthetic market seed")
    parser.add_argument(
        "--symbols", default=None, help="comma-separated symbols, e.g. BTC/USD,ETH/USD"
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path("var/soak"),
        help="where the run's audit trail, ledger and checkpoint are written",
    )
    parser.add_argument("--report", type=Path, default=None, help="write the JSON report here")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    return parser


def scenario_from_args(args: argparse.Namespace) -> SoakScenario:
    scenario = SoakScenario.load(args.scenario) if args.scenario else SoakScenario()
    updates: dict[str, Any] = {}
    if args.cycles is not None:
        updates["cycles"] = args.cycles
        updates["seconds"] = None
    if args.seconds is not None:
        updates["seconds"] = args.seconds
        if args.cycles is None:
            updates["cycles"] = None
    if args.cycle_seconds is not None:
        updates["cycle_seconds"] = args.cycle_seconds
    if args.seed is not None:
        updates["seed"] = args.seed
    if args.symbols is not None:
        updates["symbols"] = [s.strip() for s in args.symbols.split(",") if s.strip()]
    return scenario.model_copy(update=updates) if updates else scenario


async def run_scenario(scenario: SoakScenario, workdir: Path) -> SoakReport:
    return await SoakRunner(scenario=scenario, workdir=workdir).run()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scenario = scenario_from_args(args)
    report = asyncio.run(run_scenario(scenario, args.workdir))
    payload = report.model_dump(mode="json")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str) if args.json else report.render())
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
