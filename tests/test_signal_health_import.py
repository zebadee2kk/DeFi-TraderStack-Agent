from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.provider_health_journal import ProviderHealthEvent, load_provider_health_events
from traderstack.signal_health_import import health_event_key, health_event_row


def _event() -> ProviderHealthEvent:
    return ProviderHealthEvent(
        observed_at=datetime(2026, 10, 4, 11, tzinfo=UTC),
        provider="polymarket_data",
        state="closed",
        consecutive_failures=0,
        last_latency_seconds=0.21,
        last_success_at=datetime(2026, 10, 4, 10, 59, tzinfo=UTC),
        last_error=None,
        calls_last_minute=2,
        calls_today=20,
    )


def test_health_event_key_is_deterministic() -> None:
    first = _event()
    second = _event()
    assert health_event_key(first) == health_event_key(second)


def test_health_event_key_changes_when_state_changes() -> None:
    first = _event()
    second = ProviderHealthEvent(
        **{**first.__dict__, "state": "open", "consecutive_failures": 3}
    )
    assert health_event_key(first) != health_event_key(second)


def test_health_event_row_preserves_point_in_time_provenance() -> None:
    row = health_event_row(_event())
    assert row["provider"] == "polymarket_data"
    assert row["state"] == "closed"
    assert row["payload"]["last_success_at"] == "2026-10-04T10:59:00+00:00"


def test_load_provider_health_events_returns_full_history(tmp_path: Path) -> None:
    first = _event()
    second = ProviderHealthEvent(
        **{
            **first.__dict__,
            "observed_at": first.observed_at + timedelta(minutes=1),
            "calls_today": 21,
        }
    )
    path = tmp_path / "health.jsonl"
    path.write_text(first.to_json() + "\n" + second.to_json() + "\n", encoding="utf-8")

    events = load_provider_health_events(path)
    assert [event.calls_today for event in events] == [20, 21]
