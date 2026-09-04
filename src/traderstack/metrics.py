"""Prometheus metrics for pipeline, risk, execution and provider observability.

Mirrors the style of ``traderstack.health`` (module-level ``prometheus_client``
collectors, plain functions to record observations) so callers only need
additive one-line hooks rather than any control-flow changes.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, Histogram

if TYPE_CHECKING:
    from traderstack.pipeline import PipelineResult

# --- pipeline outcomes -------------------------------------------------

pipeline_outcomes_total = Counter(
    "traderstack_pipeline_outcomes_total",
    "Pipeline runs by symbol and outcome (accepted or rejected)",
    ("symbol", "outcome"),
)
pipeline_rejections_total = Counter(
    "traderstack_pipeline_rejections_total",
    "Pipeline rejections by symbol and rejection reason",
    ("symbol", "reason"),
)

# --- proposals and risk decisions --------------------------------------

proposals_total = Counter(
    "traderstack_proposals_total",
    "Trade proposals produced by the pipeline, by symbol",
    ("symbol",),
)
risk_decisions_total = Counter(
    "traderstack_risk_decisions_total",
    "Risk engine decisions by symbol and decision (allow/reduce/reject)",
    ("symbol", "decision"),
)

# --- paper execution -----------------------------------------------------

paper_orders_submitted_total = Counter(
    "traderstack_paper_orders_submitted_total",
    "Paper orders submitted for execution, by symbol and side",
    ("symbol", "side"),
)

# --- provider fetches ----------------------------------------------------

provider_fetch_latency_seconds = Histogram(
    "traderstack_provider_fetch_latency_seconds",
    "Latency of external provider fetches, by provider and kind",
    ("provider", "kind"),
)
provider_fetch_failures_total = Counter(
    "traderstack_provider_fetch_failures_total",
    "Failed external provider fetches, by provider and kind",
    ("provider", "kind"),
)

# --- candle history --------------------------------------------------------

candle_history_size = Gauge(
    "traderstack_candle_history_size",
    "Number of candles loaded for the most recent cycle, by symbol",
    ("symbol",),
)

# --- intelligence sources --------------------------------------------------

intelligence_sources_present = Gauge(
    "traderstack_intelligence_sources_present",
    "Whether a given intelligence/market source contributed to the last cycle "
    "for a symbol (1 present, 0 absent)",
    ("symbol", "source"),
)

# --- portfolio -------------------------------------------------------------

portfolio_nav_usd = Gauge(
    "traderstack_portfolio_nav_usd",
    "Current portfolio net asset value in USD",
)
portfolio_cash_usd = Gauge(
    "traderstack_portfolio_cash_usd",
    "Current portfolio cash balance in USD",
)
portfolio_drawdown_pct = Gauge(
    "traderstack_portfolio_drawdown_pct",
    "Current drawdown from peak NAV as a fraction (0-1)",
)

# --- event sinks -------------------------------------------------------

event_sink_failures_total = Counter(
    "traderstack_event_sink_failures_total",
    "Runtime event sink failures, by sink name",
    ("sink",),
)


def record_pipeline_result(symbol: str, pipeline: PipelineResult) -> None:
    """Record pipeline-level outcome/rejection/proposal/risk metrics for one cycle."""

    outcome = "accepted" if pipeline.accepted_market_data else "rejected"
    pipeline_outcomes_total.labels(symbol=symbol, outcome=outcome).inc()
    for reason in pipeline.rejection_reasons:
        pipeline_rejections_total.labels(symbol=symbol, reason=reason).inc()

    if pipeline.proposal is not None:
        proposals_total.labels(symbol=symbol).inc()

    if pipeline.risk_result is not None:
        risk_decisions_total.labels(
            symbol=symbol, decision=pipeline.risk_result.decision.value
        ).inc()

    if pipeline.feature_vector is not None:
        for source in pipeline.feature_vector.source_ids:
            intelligence_sources_present.labels(symbol=symbol, source=source).set(1)


def record_paper_order_submitted(symbol: str, side: str) -> None:
    paper_orders_submitted_total.labels(symbol=symbol, side=side).inc()


def record_candles_loaded(symbol: str, count: int) -> None:
    candle_history_size.labels(symbol=symbol).set(count)


def record_provider_fetch(provider: str, kind: str, seconds: float, *, failed: bool) -> None:
    provider_fetch_latency_seconds.labels(provider=provider, kind=kind).observe(seconds)
    if failed:
        provider_fetch_failures_total.labels(provider=provider, kind=kind).inc()


def record_portfolio_snapshot(nav_usd: float, cash_usd: float, peak_nav_usd: float) -> None:
    portfolio_nav_usd.set(nav_usd)
    portfolio_cash_usd.set(cash_usd)
    drawdown = 0.0 if peak_nav_usd <= 0 else max(0.0, 1 - (nav_usd / peak_nav_usd))
    portfolio_drawdown_pct.set(drawdown)


def record_event_sink_failure(sink: str) -> None:
    event_sink_failures_total.labels(sink=sink).inc()


async def timed_provider_call[T](provider: str, kind: str, awaitable: Awaitable[T]) -> T:
    """Await ``awaitable``, recording provider fetch latency/failure metrics.

    Re-raises whatever the awaitable raises so callers keep their existing
    error handling (e.g. ``asyncio.gather(..., return_exceptions=True)``).
    """

    started = time.monotonic()
    try:
        result = await awaitable
    except BaseException:
        record_provider_fetch(provider, kind, time.monotonic() - started, failed=True)
        raise
    record_provider_fetch(provider, kind, time.monotonic() - started, failed=False)
    return result
