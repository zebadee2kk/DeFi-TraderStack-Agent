import json
from datetime import UTC, datetime

import pytest

from traderstack.eventing import FanoutResultSink, RedisRuntimePublisher
from traderstack.market.models import MarketSource, MarketTick
from traderstack.pipeline import PipelineResult
from traderstack.runtime import RuntimeResult


def runtime_result() -> RuntimeResult:
    return RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=99,
            ask=101,
            last=100,
        ),
        references=[],
        pipeline=PipelineResult(accepted_market_data=True),
    )


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redis_publisher_emits_runtime_result() -> None:
    client = FakeRedis()
    publisher = RedisRuntimePublisher(
        "redis://unused",
        client=client,  # type: ignore[arg-type]
    )

    await publisher(runtime_result())

    assert len(client.published) == 1
    channel, payload = client.published[0]
    assert channel == "traderstack.runtime"
    assert json.loads(payload)["tick"]["symbol"] == "BTC/USD"


@pytest.mark.asyncio
async def test_fanout_calls_all_sinks_and_fails_if_any_sink_fails() -> None:
    calls: list[str] = []

    async def good_sink(result: RuntimeResult) -> None:
        calls.append(result.tick.symbol)

    async def bad_sink(result: RuntimeResult) -> None:
        calls.append(f"bad:{result.tick.symbol}")
        raise ValueError("sink unavailable")

    sink = FanoutResultSink((good_sink, bad_sink))
    with pytest.raises(RuntimeError, match="1 runtime event sink"):
        await sink(runtime_result())

    assert calls == ["BTC/USD", "bad:BTC/USD"]
