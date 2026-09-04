import pytest

from traderstack import tracing


def test_traced_span_is_a_noop_context_manager_without_configuration() -> None:
    with tracing.traced_span("some.span", symbol="BTC/USD", decision_id=None) as span:
        assert span is None


@pytest.mark.asyncio
async def test_traced_call_awaits_and_returns_result_without_configuration() -> None:
    async def coro() -> int:
        return 42

    result = await tracing.traced_call("some.span", {"symbol": "BTC/USD"}, coro())

    assert result == 42


@pytest.mark.asyncio
async def test_traced_call_propagates_exceptions_without_configuration() -> None:
    async def boom() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await tracing.traced_call("some.span", {}, boom())


def test_configure_tracing_is_a_noop_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(tracing, "_tracer", None)

    enabled = tracing.configure_tracing()

    assert enabled is False
    assert tracing._tracer is None
