import json
from datetime import UTC, datetime

import pytest

from traderstack.audit import JsonlAuditSink
from traderstack.market.models import MarketSource, MarketTick
from traderstack.pipeline import PipelineResult
from traderstack.runtime import RuntimeResult


@pytest.mark.asyncio
async def test_jsonl_audit_sink_appends_runtime_result(tmp_path) -> None:
    path = tmp_path / "audit" / "events.jsonl"
    sink = JsonlAuditSink(path)
    result = RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=99,
            ask=101,
            last=100,
        ),
        references=[],
        pipeline=PipelineResult(accepted_market_data=False),
    )

    await sink(result)
    await sink(result)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload["tick"]["symbol"] == "BTC/USD"
    assert payload["pipeline"]["accepted_market_data"] is False
