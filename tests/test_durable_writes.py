"""Durability of checkpoint, ledger and audit writers (#67)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from traderstack._fs import (
    DurableStateError,
    append_jsonl,
    fsync_directory,
    read_text_strict,
    write_atomic,
)
from traderstack.audit import JsonlAuditSink
from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.execution.ledger import ExecutionLedger, ExecutionOrder, OrderLifecycleState
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.health import RuntimeHealth
from traderstack.models import Side
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.risk_audit import JsonlRiskAuditTrail
from traderstack.service import ContinuousPaperService


def _track_fsync(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the path of every fd passed to ``os.fsync`` (Linux /proc)."""

    synced: list[str] = []
    real_fsync = os.fsync

    def tracking_fsync(fd: int) -> None:
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            target = str(fd)
        synced.append(target)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", tracking_fsync)
    return synced


def test_write_atomic_fsyncs_the_file_and_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced = _track_fsync(monkeypatch)
    path = tmp_path / "state" / "execution_ledger.json"
    write_atomic(path, '{"ok": true}')

    assert path.read_text(encoding="utf-8") == '{"ok": true}'
    assert not path.with_suffix(path.suffix + ".tmp").exists()
    # Temp-file contents and the parent directory after replace.
    assert any(entry.endswith((".tmp", "execution_ledger.json")) for entry in synced)
    assert any(Path(entry).resolve() == tmp_path.joinpath("state").resolve() for entry in synced)


def test_append_jsonl_fsyncs_each_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced = _track_fsync(monkeypatch)
    path = tmp_path / "audit" / "runtime.jsonl"
    append_jsonl(path, '{"a":1}')

    assert path.read_text(encoding="utf-8") == '{"a":1}\n'
    assert any(entry.endswith("runtime.jsonl") for entry in synced)
    assert any(Path(entry).resolve() == tmp_path.joinpath("audit").resolve() for entry in synced)


def test_directory_fsync_failure_is_best_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directory fsync is OS-dependent; a failure must not lose the file write."""

    real_fsync = os.fsync

    def failing_dir_fsync(fd: int) -> None:
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            target = ""
        if Path(target).is_dir() or target.endswith(str(tmp_path)):
            raise OSError(22, "Invalid argument")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", failing_dir_fsync)
    path = tmp_path / "ledger.json"
    write_atomic(path, '{"ok": true}')
    assert path.read_text(encoding="utf-8") == '{"ok": true}'
    fsync_directory(tmp_path)  # must not raise


def test_read_text_strict_missing_is_none(tmp_path: Path) -> None:
    assert read_text_strict(tmp_path / "missing.json", what="execution ledger") is None


def test_read_text_strict_empty_file_is_halt(tmp_path: Path) -> None:
    path = tmp_path / "execution_ledger.json"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(DurableStateError, match="empty"):
        read_text_strict(path, what="execution ledger")


@pytest.mark.asyncio
async def test_ledger_store_save_fsyncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synced = _track_fsync(monkeypatch)
    store = JsonExecutionLedgerStore(tmp_path / "execution_ledger.json")
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="ts-1",
            decision_id="d1",
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.05,
            state=OrderLifecycleState.SUBMITTED,
        )
    )
    await store.save(ledger)
    assert any("execution_ledger" in entry for entry in synced)
    assert any(Path(entry).resolve() == tmp_path.resolve() for entry in synced)


@pytest.mark.asyncio
async def test_checkpoint_store_save_fsyncs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced = _track_fsync(monkeypatch)
    store = JsonPortfolioCheckpointStore(tmp_path / "portfolio.json")
    await store.save(InMemoryPortfolioBook(starting_nav_usd=10_000))
    assert any("portfolio" in entry for entry in synced)
    restored = await store.load()
    assert restored is not None
    assert restored.starting_nav_usd == pytest.approx(10_000)


@pytest.mark.asyncio
async def test_corrupt_ledger_raises_and_is_not_a_fresh_start(tmp_path: Path) -> None:
    path = tmp_path / "execution_ledger.json"
    path.write_text("{broken", encoding="utf-8")
    store = JsonExecutionLedgerStore(path)
    with pytest.raises(DurableStateError, match="unparsable"):
        await store.load()


@pytest.mark.asyncio
async def test_empty_ledger_raises_and_is_not_a_fresh_start(tmp_path: Path) -> None:
    path = tmp_path / "execution_ledger.json"
    path.write_text("", encoding="utf-8")
    store = JsonExecutionLedgerStore(path)
    with pytest.raises(DurableStateError, match="empty"):
        await store.load()


@pytest.mark.asyncio
async def test_corrupt_checkpoint_raises(tmp_path: Path) -> None:
    path = tmp_path / "portfolio.json"
    path.write_text('{"starting_nav_usd": "nope"}', encoding="utf-8")
    store = JsonPortfolioCheckpointStore(path)
    with pytest.raises(DurableStateError, match="unparsable"):
        await store.load()


@pytest.mark.asyncio
async def test_audit_sinks_fsync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    from traderstack.market.models import MarketSource, MarketTick
    from traderstack.pipeline import PipelineResult
    from traderstack.runtime import RuntimeResult

    synced = _track_fsync(monkeypatch)
    sink = JsonlAuditSink(tmp_path / "runtime.jsonl")
    await sink(
        RuntimeResult(
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
    )
    assert any(entry.endswith("runtime.jsonl") for entry in synced)


def test_risk_audit_fsyncs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from traderstack.config import Settings
    from traderstack.models import PortfolioSnapshot, Side, TradeProposal
    from traderstack.risk import RiskEngine

    synced = _track_fsync(monkeypatch)
    trail = JsonlRiskAuditTrail(tmp_path / "risk_decisions.jsonl")
    config = Settings(kill_switch=False)
    engine = RiskEngine(config)
    proposal = TradeProposal(
        strategy_id="s",
        asset="BTC",
        side=Side.BUY,
        confidence=0.5,
        requested_notional_usd=100,
        thesis="t",
        source_freshness_seconds=1,
    )
    snapshot = PortfolioSnapshot(
        nav_usd=10_000, cash_usd=10_000, daily_pnl_usd=0, peak_nav_usd=10_000
    )
    trail.record(proposal, engine.evaluate(proposal, snapshot), config)
    assert any(entry.endswith("risk_decisions.jsonl") for entry in synced)


def test_durable_state_failure_makes_health_unhealthy_and_stays_blocked() -> None:
    health = RuntimeHealth()
    health.record_durable_state_failure("execution ledger is empty")
    assert not health.healthy
    assert health.reconciliation_blocked
    assert health.durable_state_error == "execution ledger is empty"

    health.record_reconciliation_success()
    assert health.reconciliation_blocked
    assert not health.healthy

    health.record_success("BTC/USD")
    assert not health.healthy


@pytest.mark.asyncio
async def test_service_refuses_to_run_when_durable_state_is_corrupt() -> None:
    """A torn ledger must not enter the cycle loop (no resubmission window)."""

    class _BoomRuntime:
        async def run_once(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("run_once must not be called after a durable halt")

    health = RuntimeHealth()
    health.record_durable_state_failure("execution ledger at /tmp/x is empty")
    service = ContinuousPaperService(
        runtime=_BoomRuntime(),  # type: ignore[arg-type]
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        symbols=("BTC/USD",),
        submit=True,
        health=health,
    )
    assert not service.submission_enabled
    await service.run()
