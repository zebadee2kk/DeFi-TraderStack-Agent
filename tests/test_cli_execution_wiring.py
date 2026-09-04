from pathlib import Path

import pytest

from traderstack.checkpoint import JsonPortfolioCheckpointStore
from traderstack.cli import build_parser, build_service
from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger
from traderstack.execution.ledger_store import JsonExecutionLedgerStore
from traderstack.execution.reconcile import HummingbotExecutionReconciler
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.reconciliation import HummingbotPortfolioReconciler
from traderstack.runtime import RuntimeResult


async def _noop(result: RuntimeResult) -> None:
    return None


def settings_for_paper_submission() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        hummingbot_api_username="user",
        hummingbot_api_password="secret",  # type: ignore[arg-type]
        pretrade_backtest_enabled=False,
        reconcile_interval_seconds=30.0,
        max_nav_drift_bps=15.0,
        execution_min_notional_usd=25.0,
        execution_lot_step=0.001,
        execution_max_slippage_bps=20.0,
        execution_submit_timeout_seconds=7.0,
        execution_max_retries=1,
    )


def test_parser_exposes_the_ledger_path() -> None:
    args = build_parser().parse_args([])
    assert args.ledger_path == "var/state/execution_ledger.json"


def test_build_service_wires_the_execution_stack(tmp_path: Path) -> None:
    settings = settings_for_paper_submission()
    ledger = ExecutionLedger()
    ledger_store = JsonExecutionLedgerStore(tmp_path / "execution_ledger.json")

    service = build_service(
        settings,
        submit=True,
        cycle_seconds=1.0,
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        on_result=_noop,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
        execution_ledger=ledger,
        ledger_store=ledger_store,
    )

    assert isinstance(service.execution_reconciler, HummingbotExecutionReconciler)
    assert isinstance(service.portfolio_reconciler, HummingbotPortfolioReconciler)
    assert service.portfolio_reconciler.max_nav_difference_bps == pytest.approx(15.0)
    assert service.reconcile_interval_seconds == pytest.approx(30.0)
    assert service.execution_ledger is ledger
    assert service.ledger_store is ledger_store

    submitter = service.runtime.submitter
    assert submitter is not None
    assert submitter.ledger is ledger
    assert submitter.ledger_store is ledger_store
    assert submitter.resolver is service.execution_reconciler
    assert submitter.timeout_seconds == pytest.approx(7.0)
    assert submitter.max_retries == 1
    assert submitter.planner.lot_step == pytest.approx(0.001)
    assert submitter.planner.min_notional_usd == pytest.approx(25.0)
    assert submitter.planner.max_slippage_bps == pytest.approx(20.0)


def test_build_service_without_submit_has_no_execution_stack(tmp_path: Path) -> None:
    settings = settings_for_paper_submission()
    service = build_service(
        settings,
        submit=False,
        cycle_seconds=1.0,
        portfolio=InMemoryPortfolioBook(starting_nav_usd=10_000),
        on_result=_noop,
        checkpoint_store=JsonPortfolioCheckpointStore(tmp_path / "portfolio.json"),
    )

    assert service.runtime.submitter is None
    assert service.execution_reconciler is None
    assert service.portfolio_reconciler is None
    assert not service.submission_enabled
