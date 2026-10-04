"""Append-only provider health journal.

Operational evidence only: this is not the tamper-evident risk audit. Every
ProviderRegistry can emit its current health after an upstream success or
failure. The journal is intentionally local-file first so provider monitoring
still works when PostgreSQL itself is unavailable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from traderstack.market.registry import ProviderHealthReport

DEFAULT_PROVIDER_HEALTH_PATH = Path("var/ops/provider_health.jsonl")


@dataclass(frozen=True)
class ProviderHealthEvent:
    observed_at: datetime
    provider: str
    state: str
    consecutive_failures: int
    last_latency_seconds: float | None
    last_success_at: datetime | None
    last_error: str | None
    calls_last_minute: int
    calls_today: int

    def to_json(self) -> str:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat()
        payload["last_success_at"] = (
            self.last_success_at.isoformat() if self.last_success_at is not None else None
        )
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ProviderHealthJournal:
    path: Path

    def record(self, report: ProviderHealthReport) -> None:
        event = ProviderHealthEvent(
            observed_at=datetime.now(UTC),
            provider=report.name,
            state=str(report.state),
            consecutive_failures=report.consecutive_failures,
            last_latency_seconds=report.last_latency_seconds,
            last_success_at=report.last_success_at,
            last_error=report.last_error,
            calls_last_minute=report.calls_last_minute,
            calls_today=report.calls_today,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json())
            handle.write("\n")


def load_latest_provider_health(path: Path) -> dict[str, ProviderHealthEvent]:
    if not path.is_file():
        return {}

    latest: dict[str, ProviderHealthEvent] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
            observed_at = datetime.fromisoformat(str(payload["observed_at"]))
            last_success_raw = payload.get("last_success_at")
            last_success_at = (
                datetime.fromisoformat(str(last_success_raw))
                if last_success_raw is not None
                else None
            )
            event = ProviderHealthEvent(
                observed_at=observed_at,
                provider=str(payload["provider"]),
                state=str(payload["state"]),
                consecutive_failures=int(payload["consecutive_failures"]),
                last_latency_seconds=(
                    float(payload["last_latency_seconds"])
                    if payload.get("last_latency_seconds") is not None
                    else None
                ),
                last_success_at=last_success_at,
                last_error=(
                    str(payload["last_error"]) if payload.get("last_error") is not None else None
                ),
                calls_last_minute=int(payload["calls_last_minute"]),
                calls_today=int(payload["calls_today"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue

        previous = latest.get(event.provider)
        if previous is None or event.observed_at >= previous.observed_at:
            latest[event.provider] = event
    return latest


def load_provider_health_events(path: Path) -> list[ProviderHealthEvent]:
    if not path.is_file():
        return []

    events: list[ProviderHealthEvent] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
            observed_at = datetime.fromisoformat(str(payload["observed_at"]))
            last_success_raw = payload.get("last_success_at")
            last_success_at = (
                datetime.fromisoformat(str(last_success_raw))
                if last_success_raw is not None
                else None
            )
            events.append(
                ProviderHealthEvent(
                    observed_at=observed_at,
                    provider=str(payload["provider"]),
                    state=str(payload["state"]),
                    consecutive_failures=int(payload["consecutive_failures"]),
                    last_latency_seconds=(
                        float(payload["last_latency_seconds"])
                        if payload.get("last_latency_seconds") is not None
                        else None
                    ),
                    last_success_at=last_success_at,
                    last_error=(
                        str(payload["last_error"])
                        if payload.get("last_error") is not None
                        else None
                    ),
                    calls_last_minute=int(payload["calls_last_minute"]),
                    calls_today=int(payload["calls_today"]),
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return events
