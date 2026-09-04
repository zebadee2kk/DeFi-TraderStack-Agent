"""Minimal, optional OpenTelemetry tracing.

Import-guarded: when the ``opentelemetry`` extra is not installed, every
helper here is a no-op (``traced_span`` yields ``None`` and nothing is
imported at module load). Even with the extra installed, tracing stays a
no-op until ``configure_tracing()`` is called with
``OTEL_EXPORTER_OTLP_ENDPOINT`` set in the environment — so this module is
always safe to import and use from hot paths (``PaperRuntime.run_once``,
provider fetches) regardless of deployment.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Awaitable, Iterator
from typing import Any

try:
    import opentelemetry.sdk.resources as _otel_resources  # type: ignore[import-not-found]
    import opentelemetry.sdk.trace as _otel_sdk_trace  # type: ignore[import-not-found]
    import opentelemetry.sdk.trace.export as _otel_export  # type: ignore[import-not-found]
    import opentelemetry.trace as _otel_trace  # type: ignore[import-not-found]

    _Resource = _otel_resources.Resource
    _TracerProvider = _otel_sdk_trace.TracerProvider
    _BatchSpanProcessor = _otel_export.BatchSpanProcessor
    _OTEL_INSTALLED = True
except ImportError:  # pragma: no cover - exercised by the no-op-path test
    _OTEL_INSTALLED = False

_tracer: Any = None


def configure_tracing(service_name: str = "traderstack") -> bool:
    """Set up an OTLP tracer if the extra is installed and an endpoint is configured.

    Returns True when tracing was actually enabled, False for every no-op
    case (extra missing, endpoint unset, exporter unavailable). Safe to call
    more than once; only the first call with an endpoint takes effect.
    """

    global _tracer
    if _tracer is not None:
        return True
    if not _OTEL_INSTALLED:
        return False
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )
    except ImportError:  # pragma: no cover - exporter subpackage missing
        return False

    provider = _TracerProvider(resource=_Resource.create({"service.name": service_name}))
    provider.add_span_processor(_BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    _otel_trace.set_tracer_provider(provider)
    _tracer = _otel_trace.get_tracer(service_name)
    return True


@contextlib.contextmanager
def traced_span(name: str, **attributes: object) -> Iterator[Any]:
    """Open a span named ``name`` with the given attributes; a no-op if tracing is off.

    Yields the live span (so callers can add attributes discovered mid-flight,
    e.g. a decision_id known only after the proposal is produced) or ``None``
    when tracing is disabled.
    """

    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


async def traced_call[T](name: str, attributes: dict[str, object], awaitable: Awaitable[T]) -> T:
    """Await ``awaitable`` inside a span named ``name`` with ``attributes``."""

    with traced_span(name, **attributes):
        return await awaitable
