from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from traderstack.market.registry import BreakerState, ProviderHealthReport
from traderstack.provider_health_journal import ProviderHealthJournal, load_latest_provider_health


def report(
    *,
    name: str = "dune",
    state: BreakerState = BreakerState.CLOSED,
    failures: int = 0,
    last_success_at: datetime | None = None,
    last_error: str | None = None,
) -> ProviderHealthReport:
    return ProviderHealthReport(
        name=name,
        state=state,
        consecutive_failures=failures,
        last_latency_seconds=0.25,
        last_success_at=last_success_at,
        last_error=last_error,
        calls_last_minute=1,
        calls_today=2,
    )


def test_journal_round_trips_latest_event(tmp_path: Path) -> None:
    path = tmp_path / "provider-health.jsonl"
    journal = ProviderHealthJournal(path)
    first = datetime(2026, 10, 4, 9, tzinfo=UTC)
    second = datetime(2026, 10, 4, 10, tzinfo=UTC)

    journal.record(report(last_success_at=first))
    journal.record(report(last_success_at=second))

    latest = load_latest_provider_health(path)
    assert latest["dune"].last_success_at == second
    assert latest["dune"].state == "closed"


def test_journal_preserves_sanitized_error_text(tmp_path: Path) -> None:
    path = tmp_path / "provider-health.jsonl"
    journal = ProviderHealthJournal(path)
    journal.record(
        report(
            state=BreakerState.OPEN,
            failures=3,
            last_error="HTTPStatusError: upstream unavailable",
        )
    )

    event = load_latest_provider_health(path)["dune"]
    assert event.state == "open"
    assert event.consecutive_failures == 3
    assert event.last_error == "HTTPStatusError: upstream unavailable"
