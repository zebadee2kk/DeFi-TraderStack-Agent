"""Fault-injection harness for the paper-trading acceptance drills (Epic 10).

Every external dependency the live loop has gets a wrapper here that can be made
to fail on demand: reference-price providers, the candle-history provider, the
venue tick feed, the intelligence orchestrator, the meta-agent client, the
venue HTTP API (executor + reconcilers), the portfolio book and the runtime
event sinks.

Two rules shape the design:

* A fault is an *object*, not a flag. It has ``arm()`` / ``disarm()`` and counts
  how many times it actually fired, so a drill can assert the failure really
  happened rather than assuming the wiring reached it.
* The wrappers are the only fakes. Everything they feed -- pipeline, risk
  engine, submitter, ledger, reconciler, audit trail -- is the production code
  under test, because the point of an acceptance drill is the real fail-closed
  path, not a mock of it.

Nothing here is imported by the trading runtime.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from traderstack.agents.meta import EvidencePacket, MetaAgentDecision
from traderstack.candles import Candle
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.reconcile import ExecutionReconciliationResult
from traderstack.features import AssetFeatureVector
from traderstack.intelligence_orchestrator import ExternalIntelligence, IntelligenceOrchestrator
from traderstack.market.models import MarketSource, MarketTick, ReferencePrice
from traderstack.models import PortfolioSnapshot, RiskResult, TradeProposal
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.reconciliation import ReconciliationResult
from traderstack.risk import RiskEngine
from traderstack.runtime import RuntimeResult

# --- fault primitives -------------------------------------------------------


class Fault:
    """One injectable failure: ``arm()`` / ``disarm()`` plus a fired counter.

    ``trip()`` is the single place activation is decided and counted, so every
    subclass reports ``fired`` consistently regardless of what it does when it
    fires.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.armed = False
        self.fired = 0
        self._remaining: int | None = None

    def arm(self, *, times: int | None = None) -> Fault:
        """Arm the fault. ``times`` auto-disarms after that many activations."""

        if times is not None and times <= 0:
            raise ValueError("times must be positive")
        self.armed = True
        self._remaining = times
        return self

    def disarm(self) -> None:
        self.armed = False
        self._remaining = None

    def reset(self) -> None:
        self.disarm()
        self.fired = 0

    def trip(self) -> bool:
        """Consume one activation; True when the caller should fail."""

        if not self.armed:
            return False
        self.fired += 1
        if self._remaining is not None:
            self._remaining -= 1
            if self._remaining <= 0:
                self.disarm()
        return True

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only.
        return f"<{type(self).__name__} {self.name} armed={self.armed} fired={self.fired}>"


class RaiseFault(Fault):
    """Raises when armed. The default error names the fault."""

    def __init__(self, name: str, error: Callable[[], BaseException] | None = None) -> None:
        super().__init__(name)
        self.error = error or (lambda: RuntimeError(f"injected fault: {name}"))

    def raise_if_armed(self) -> None:
        if self.trip():
            raise self.error()

    async def check(self) -> None:
        self.raise_if_armed()


class HangFault(Fault):
    """Sleeps when armed, so a caller's timeout (or circuit breaker) fires."""

    def __init__(self, name: str, delay_seconds: float = 30.0) -> None:
        super().__init__(name)
        self.delay_seconds = delay_seconds

    async def check(self) -> None:
        if self.trip():
            await asyncio.sleep(self.delay_seconds)


class AgeFault(Fault):
    """Backdates an observation timestamp, producing stale data."""

    def __init__(self, name: str, age_seconds: float = 3_600.0) -> None:
        super().__init__(name)
        self.age_seconds = age_seconds

    def observed_at(self, now: datetime) -> datetime:
        return now - timedelta(seconds=self.age_seconds) if self.trip() else now


class ScaleFault(Fault):
    """Multiplies a served number, e.g. to force a reference-price divergence."""

    def __init__(self, name: str, multiplier: float = 1.10) -> None:
        super().__init__(name)
        self.multiplier = multiplier

    def apply(self, value: float) -> float:
        return value * self.multiplier if self.trip() else value


class SentinelFileFault(Fault):
    """Kill-switch drill: ``arm()`` writes the sentinel, ``disarm()`` removes it.

    Unlike the other faults this one changes state outside the process rather
    than at a call site, which is exactly how an operator engages the halt.
    """

    def __init__(self, name: str, path: Path, reason: str = "acceptance drill") -> None:
        super().__init__(name)
        self.path = Path(path)
        self.reason = reason

    def arm(self, *, times: int | None = None) -> Fault:
        super().arm(times=times)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(f"{datetime.now(UTC).isoformat()} {self.reason}\n", encoding="utf-8")
        self.trip()
        return self

    def disarm(self) -> None:
        super().disarm()
        self.path.unlink(missing_ok=True)


@dataclass
class FaultBoard:
    """Named registry of every fault a run can inject."""

    faults: dict[str, Fault] = field(default_factory=dict)

    def register(self, fault: Fault) -> Fault:
        if fault.name in self.faults:
            raise ValueError(f"duplicate fault name {fault.name!r}")
        self.faults[fault.name] = fault
        return fault

    def get(self, name: str) -> Fault:
        try:
            return self.faults[name]
        except KeyError:
            known = ", ".join(sorted(self.faults)) or "(none)"
            raise KeyError(f"unknown fault {name!r}; known faults: {known}") from None

    def arm(self, name: str, *, times: int | None = None) -> Fault:
        return self.get(name).arm(times=times)

    def disarm(self, name: str) -> None:
        self.get(name).disarm()

    def disarm_all(self) -> None:
        for fault in self.faults.values():
            fault.disarm()

    def fired(self) -> dict[str, int]:
        return {name: fault.fired for name, fault in self.faults.items() if fault.fired}

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.faults))


def _register[F: Fault](board: FaultBoard | None, fault: F) -> F:
    """Register a fault on the board (when there is one) and hand it back typed."""

    if board is not None:
        board.register(fault)
    return fault


# --- market data ------------------------------------------------------------


PriceLookup = Callable[[str], float]


@dataclass
class FaultyReferenceProvider:
    """A ``ReferencePriceProvider`` that can fail, hang, go stale or diverge."""

    name: str
    price_of: PriceLookup
    source: MarketSource = MarketSource.COINGECKO
    board: FaultBoard | None = None
    hang_seconds: float = 30.0
    stale_seconds: float = 3_600.0
    divergence_multiplier: float = 1.10
    calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.error = _register(self.board, RaiseFault(f"{self.name}_reference_error"))
        self.hang = _register(
            self.board, HangFault(f"{self.name}_reference_hang", self.hang_seconds)
        )
        self.stale = _register(
            self.board, AgeFault(f"{self.name}_reference_stale", self.stale_seconds)
        )
        self.divergence = _register(
            self.board,
            ScaleFault(f"{self.name}_reference_divergence", self.divergence_multiplier),
        )

    async def get_prices(self, assets: tuple[str, ...]) -> list[ReferencePrice]:
        self.calls += 1
        await self.hang.check()
        await self.error.check()
        now = datetime.now(UTC)
        return [
            ReferencePrice(
                source=self.source,
                asset=asset.upper(),
                currency="USD",
                observed_at=self.stale.observed_at(now),
                price=self.divergence.apply(self.price_of(asset)),
            )
            for asset in assets
        ]


CandleLookup = Callable[[str, str, int], tuple[Candle, ...]]


@dataclass
class FaultyCandleProvider:
    """A ``CandleHistoryProvider`` that can fail, hang, empty out or go stale."""

    candles_of: CandleLookup
    name: str = "candles"
    board: FaultBoard | None = None
    hang_seconds: float = 30.0
    stale_seconds: float = 86_400.0
    calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.error = _register(self.board, RaiseFault(f"{self.name}_history_error"))
        self.hang = _register(self.board, HangFault(f"{self.name}_history_hang", self.hang_seconds))
        self.stale = _register(
            self.board, AgeFault(f"{self.name}_history_stale", self.stale_seconds)
        )
        self.empty = _register(self.board, Fault(f"{self.name}_history_empty"))

    async def fetch(
        self, symbol: str, resolution: str = "1h", *, count: int = 250
    ) -> tuple[Candle, ...]:
        self.calls += 1
        await self.hang.check()
        await self.error.check()
        if self.empty.trip():
            return ()
        history = self.candles_of(symbol, resolution, count)
        # AgeFault shifts the whole series, so ordering and OHLC stay valid and
        # only the *freshness* of the newest bar changes.
        now = datetime.now(UTC)
        shift = self.stale.observed_at(now) - now
        if shift:
            history = tuple(
                candle.model_copy(update={"opened_at": candle.opened_at + shift})
                for candle in history
            )
        return history


TickFactory = Callable[[str], MarketTick]


@dataclass
class FaultyVenueFeed:
    """A ``VenueMarketDataProvider`` that can fail, hang, go stale or widen out."""

    tick_of: TickFactory
    name: str = "venue"
    board: FaultBoard | None = None
    hang_seconds: float = 30.0
    stale_seconds: float = 600.0
    spread_multiplier: float = 100.0
    calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.error = _register(self.board, RaiseFault(f"{self.name}_feed_error"))
        self.hang = _register(self.board, HangFault(f"{self.name}_feed_hang", self.hang_seconds))
        self.stale = _register(self.board, AgeFault(f"{self.name}_feed_stale", self.stale_seconds))
        self.spread = _register(
            self.board, ScaleFault(f"{self.name}_feed_spread", self.spread_multiplier)
        )

    async def stream_ticks(self, symbols: tuple[str, ...]) -> AsyncIterator[MarketTick]:
        for symbol in symbols:
            self.calls += 1
            await self.hang.check()
            await self.error.check()
            tick = self.tick_of(symbol)
            observed_at = self.stale.observed_at(tick.observed_at)
            half = (tick.ask - tick.bid) / 2
            widened = self.spread.apply(half)
            yield tick.model_copy(
                update={
                    "observed_at": observed_at,
                    "bid": tick.last - widened,
                    "ask": tick.last + widened,
                }
            )


# --- intelligence and the meta-agent ---------------------------------------


@dataclass
class FaultyIntelligence(IntelligenceOrchestrator):
    """An ``IntelligenceOrchestrator`` whose ``gather`` can be made to fail.

    Subclasses the real orchestrator so the runtime's declared type is honoured;
    only ``gather`` is replaced.
    """

    name: str = "intelligence"
    board: FaultBoard | None = None
    hang_seconds: float = 30.0
    calls: int = 0

    def __post_init__(self) -> None:
        self.error = _register(self.board, RaiseFault(f"{self.name}_error"))
        self.hang = _register(self.board, HangFault(f"{self.name}_hang", self.hang_seconds))

    async def gather(self, asset: str) -> ExternalIntelligence:
        self.calls += 1
        await self.hang.check()
        await self.error.check()
        return ExternalIntelligence(asset=asset.upper())


@dataclass
class FaultyMetaAgentClient:
    """A ``MetaAgentClient`` that can veto, raise or hang.

    In veto mode a raise or a hang must produce ``meta_agent_unavailable`` and
    no order; in advisory mode the same failure must change nothing.
    """

    approve: bool = True
    confidence_delta: float = 0.0
    name: str = "meta_agent"
    board: FaultBoard | None = None
    hang_seconds: float = 60.0
    calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.error = _register(self.board, RaiseFault(f"{self.name}_error"))
        self.hang = _register(self.board, HangFault(f"{self.name}_hang", self.hang_seconds))
        self.veto = _register(self.board, Fault(f"{self.name}_veto"))

    async def __call__(self, packet: EvidencePacket) -> MetaAgentDecision:
        self.calls += 1
        await self.hang.check()
        await self.error.check()
        approve = self.approve and not self.veto.trip()
        return MetaAgentDecision(
            approve=approve,
            confidence_delta=self.confidence_delta if approve else 0.0,
            rationale="synthetic acceptance-drill review",
        )


# --- risk plane -------------------------------------------------------------


@dataclass(frozen=True)
class FaultyRiskEngine(RiskEngine):
    """A ``RiskEngine`` that can be made unavailable.

    "Unavailable risk service = no new risk" is only meaningful if the service
    can actually break, so the drill breaks it here rather than asserting the
    happy path.
    """

    failure: RaiseFault = field(default_factory=lambda: RaiseFault("risk_engine_error"))

    def evaluate(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioSnapshot,
        features: AssetFeatureVector | None = None,
        *,
        now: datetime | None = None,
    ) -> RiskResult:
        self.failure.raise_if_armed()
        return super().evaluate(proposal, portfolio, features, now=now)


@dataclass
class FaultyPortfolioBook(InMemoryPortfolioBook):
    """A portfolio book that can serve a stale snapshot.

    ``stale_portfolio_state`` is a risk-engine rejection driven by the snapshot's
    ``observed_at``, so backdating it here is the only honest way to reach it.
    """

    stale: AgeFault = field(default_factory=lambda: AgeFault("portfolio_state_stale", 3_600.0))

    def snapshot(self, now: datetime | None = None) -> PortfolioSnapshot:
        moment = now or datetime.now(UTC)
        observed_at = self.stale.observed_at(moment)
        # roll_day() runs against real "now" so a backdated view never
        # re-anchors the daily PnL baseline.
        snapshot = super().snapshot(moment)
        return snapshot.model_copy(update={"observed_at": observed_at})


# --- reconciliation ---------------------------------------------------------


@dataclass
class FaultyExecutionReconciler:
    """An ``ExecutionReconcilerProtocol`` that can raise or report drift."""

    name: str = "execution_reconciler"
    board: FaultBoard | None = None
    conflict: str = "order o1 is filled locally but open at the venue"
    calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.error = _register(self.board, RaiseFault(f"{self.name}_error"))
        self.drift = _register(self.board, Fault(f"{self.name}_drift"))

    async def reconcile_state(
        self, ledger: ExecutionLedger, portfolio: InMemoryPortfolioBook
    ) -> ExecutionReconciliationResult:
        self.calls += 1
        await self.error.check()
        if self.drift.trip():
            return ExecutionReconciliationResult(conflicts=[self.conflict])
        return ExecutionReconciliationResult()


@dataclass
class FaultyPortfolioReconciler:
    """A ``PortfolioReconcilerProtocol`` that can raise or report NAV drift."""

    name: str = "portfolio_reconciler"
    board: FaultBoard | None = None
    drift_bps: float = 250.0
    max_nav_difference_bps: float = 25.0
    calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.error = _register(self.board, RaiseFault(f"{self.name}_error"))
        self.drift = _register(self.board, Fault(f"{self.name}_nav_drift"))

    async def reconcile(self, portfolio: InMemoryPortfolioBook) -> ReconciliationResult:
        self.calls += 1
        await self.error.check()
        internal = portfolio.nav_usd
        if not self.drift.trip():
            return ReconciliationResult(
                matched=True,
                internal_nav_usd=internal,
                external_nav_usd=internal,
                nav_difference_usd=0.0,
                nav_difference_bps=0.0,
            )
        difference = internal * self.drift_bps / 10_000
        return ReconciliationResult(
            matched=False,
            internal_nav_usd=internal,
            external_nav_usd=max(internal - difference, 0.0),
            nav_difference_usd=difference,
            nav_difference_bps=self.drift_bps,
            reasons=[
                (
                    f"portfolio NAV drift {self.drift_bps:.2f} bps exceeds "
                    f"{self.max_nav_difference_bps:.2f} bps"
                )
            ],
        )


# --- event sinks ------------------------------------------------------------


ResultHandler = Callable[[RuntimeResult], Awaitable[None]]


@dataclass
class FaultyEventSink:
    """A runtime event sink (audit / Postgres / Redis) that can be made to fail.

    Wraps an optional real sink so a database "restart" drill can prove the
    durable sink both stops and resumes persisting.
    """

    name: str = "audit"
    delegate: ResultHandler | None = None
    board: FaultBoard | None = None
    delivered: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.error = _register(self.board, RaiseFault(f"{self.name}_sink_error"))

    async def __call__(self, result: RuntimeResult) -> None:
        await self.error.check()
        if self.delegate is not None:
            await self.delegate(result)
        self.delivered += 1


# --- venue API --------------------------------------------------------------

_ORDER_ENDPOINT = "/trading/orders"
_ORDER_SEARCH_ENDPOINT = "/trading/orders/search"
_TRADES_ENDPOINT = "/trading/trades"
_PORTFOLIO_ENDPOINT = "/portfolio/state"


@dataclass
class FaultyVenueApi:
    """In-process stand-in for ``hummingbot-api``, driven by fault objects.

    Exposed as an ``httpx.AsyncClient`` so the *real* ``HummingbotPaperExecutor``
    and the real reconcilers run against it: only the socket is fake.
    """

    account_name: str = "paper_account"
    connector_name: str = "kraken_paper_trade"
    nav_usd: float = 10_000.0
    board: FaultBoard | None = None
    base_url: str = "http://hummingbot.invalid"
    posts: int = field(default=0, init=False)
    order_ids: list[str] = field(default_factory=list, init=False)
    venue_orders: list[dict[str, Any]] = field(default_factory=list, init=False)
    venue_trades: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.submit_timeout = _register(self.board, Fault("venue_submit_timeout"))
        self.submit_server_error = _register(self.board, Fault("venue_submit_server_error"))
        self.search_error = _register(self.board, Fault("venue_search_error"))
        self.nav_drift = _register(self.board, ScaleFault("venue_nav_drift", 0.95))

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == _ORDER_ENDPOINT and request.method == "POST":
            return self._handle_submit(request)
        if path == _ORDER_SEARCH_ENDPOINT:
            if self.search_error.trip():
                return httpx.Response(503, json={"detail": "injected venue search failure"})
            return httpx.Response(200, json=self.venue_orders)
        if path == _TRADES_ENDPOINT:
            return httpx.Response(200, json=self.venue_trades)
        if path == _PORTFOLIO_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    self.account_name: {
                        self.connector_name: [{"value": self.nav_drift.apply(self.nav_usd)}]
                    }
                },
            )
        return httpx.Response(404, json={"detail": f"unhandled path {path}"})

    def _handle_submit(self, request: httpx.Request) -> httpx.Response:
        self.posts += 1
        if self.submit_timeout.trip():
            raise httpx.TimeoutException("injected venue timeout", request=request)
        if self.submit_server_error.trip():
            return httpx.Response(503, json={"detail": "injected venue 503"})

        payload = json.loads(request.content or b"{}")
        order_id = f"venue-{self.posts}"
        self.order_ids.append(order_id)
        receipt = {
            "order_id": order_id,
            "account_name": self.account_name,
            "connector_name": self.connector_name,
            "trading_pair": payload.get("trading_pair", "BTC-USD"),
            "trade_type": payload.get("trade_type", "BUY"),
            "amount": payload.get("amount", 0.0),
            "order_type": payload.get("order_type", "MARKET"),
            "price": payload.get("price"),
            "status": "submitted",
        }
        self.venue_orders.append({**receipt, "status": "open"})
        return httpx.Response(201, json=receipt)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            transport=httpx.MockTransport(self._handle),
        )
