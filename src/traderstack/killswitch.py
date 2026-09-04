"""Operator kill switch, operable from outside the LLM runtime (Epic 7).

Layer 1 of the control hierarchy: when engaged, no new risk is authorised at
all. Four independent channels can engage it, and *any* of them is sufficient:

1. ``Settings.kill_switch`` -- version-controlled configuration.
2. A sentinel file (``KILL_SWITCH_FILE``, default ``var/state/KILL``). Any
   operator with filesystem access can ``touch`` it; no process cooperation and
   no API call is required, which is the point.
3. A Redis key (``KILL_SWITCH_REDIS_KEY``), so a remote operator or an external
   monitor can halt the fleet. Optional; off unless
   ``KILL_SWITCH_REDIS_ENABLED`` is true.
4. ``SIGUSR1`` delivered to the process.

There is deliberately no path that *disengages* the switch from inside this
process: ``traderstack-resume`` is a separate console entry point an operator
runs, and the settings flag is version-controlled. Nothing in the agent runtime
can clear a sentinel file it never learns to write.

Redis is checked asynchronously (``refresh``) at the start of every service
cycle and cached, so ``engaged`` stays a cheap synchronous property the
deterministic risk engine can consult on every evaluation.
"""

from __future__ import annotations

import argparse
import os
import signal
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType

from prometheus_client import Gauge

from traderstack.config import Settings

KILL_SWITCH_REASON = "kill_switch_enabled"
DEFAULT_KILL_SWITCH_FILE = "var/state/KILL"

kill_switch_engaged = Gauge(
    "traderstack_kill_switch_engaged",
    "Operator kill switch state: 1 engaged (no new risk), 0 clear",
)
kill_switch_sources = Gauge(
    "traderstack_kill_switch_source_engaged",
    "Which kill-switch channel is engaging the halt (1 engaged, 0 clear)",
    ("source",),
)

_SOURCES = ("settings", "file", "redis", "signal")

# Process-wide SIGUSR1 latch. Set by the signal handler, never cleared from
# inside the runtime -- a signalled halt survives until the process restarts.
_signal_engaged = False


def _handle_sigusr1(signum: int, frame: FrameType | None) -> None:
    global _signal_engaged
    _signal_engaged = True


def install_signal_handler() -> bool:
    """Install the SIGUSR1 handler. Returns False where the platform lacks it."""

    if not hasattr(signal, "SIGUSR1"):
        return False
    try:
        signal.signal(signal.SIGUSR1, _handle_sigusr1)
    except ValueError:
        # Not on the main thread; the other three channels still apply.
        return False
    return True


def signal_engaged() -> bool:
    return _signal_engaged


def _reset_signal_latch_for_tests() -> None:
    global _signal_engaged
    _signal_engaged = False


class RedisKeyProbe:
    """Minimal protocol for the Redis client the kill switch reads."""

    async def get(self, key: str) -> object: ...  # pragma: no cover - protocol only


@dataclass
class KillSwitch:
    """Live, multi-channel halt consulted by the risk engine on every decision."""

    settings_flag: bool = False
    sentinel_path: Path | None = None
    redis_key: str | None = None
    redis_client: RedisKeyProbe | None = None
    # Cached result of the last successful Redis probe. A probe that raises
    # leaves the cached value engaged: an unreachable halt channel is
    # inconsistent state, and the default response to that is no new risk.
    redis_engaged: bool = False
    redis_error: str | None = None
    last_refreshed_at: datetime | None = field(default=None)

    @classmethod
    def from_settings(
        cls, settings: Settings, *, redis_client: RedisKeyProbe | None = None
    ) -> KillSwitch:
        return cls(
            settings_flag=settings.kill_switch,
            sentinel_path=Path(settings.kill_switch_file),
            redis_key=settings.kill_switch_redis_key
            if settings.kill_switch_redis_enabled
            else None,
            redis_client=redis_client if settings.kill_switch_redis_enabled else None,
        )

    # --- evaluation ----------------------------------------------------

    @property
    def file_engaged(self) -> bool:
        return self.sentinel_path is not None and self.sentinel_path.exists()

    @property
    def engaged(self) -> bool:
        return bool(
            self.settings_flag or self.file_engaged or self.redis_engaged or signal_engaged()
        )

    @property
    def engaged_sources(self) -> tuple[str, ...]:
        active = []
        if self.settings_flag:
            active.append("settings")
        if self.file_engaged:
            active.append("file")
        if self.redis_engaged:
            active.append("redis")
        if signal_engaged():
            active.append("signal")
        return tuple(active)

    async def refresh(self) -> bool:
        """Re-probe the out-of-process channels and publish the gauges.

        Called at the start of every service cycle. Returns the engaged state.
        """

        if self.redis_client is not None and self.redis_key is not None:
            try:
                value = await self.redis_client.get(self.redis_key)
            except Exception as exc:  # noqa: BLE001 - unknown halt state fails closed.
                self.redis_error = f"{type(exc).__name__}: {exc}"
                self.redis_engaged = True
            else:
                self.redis_error = None
                self.redis_engaged = _truthy(value)
        self.last_refreshed_at = datetime.now(UTC)
        return self.publish()

    def publish(self) -> bool:
        """Publish the current state to Prometheus without re-probing Redis."""

        engaged = self.engaged
        active = set(self.engaged_sources)
        kill_switch_engaged.set(1 if engaged else 0)
        for source in _SOURCES:
            kill_switch_sources.labels(source=source).set(1 if source in active else 0)
        return engaged


def _truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


# --- operator console scripts ------------------------------------------


def _sentinel_path(explicit: str | None) -> Path:
    return Path(explicit or os.environ.get("KILL_SWITCH_FILE") or DEFAULT_KILL_SWITCH_FILE)


def engage(path: Path, reason: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat()
    path.write_text(f"{stamp} {reason}\n", encoding="utf-8")
    return path


def disengage(path: Path) -> bool:
    if not path.exists():
        return False
    path.unlink()
    return True


def kill_main(argv: list[str] | None = None) -> int:
    """``traderstack-kill``: engage the halt by writing the sentinel file."""

    parser = argparse.ArgumentParser(
        description="Engage the TraderStack kill switch (no new risk will be authorised)"
    )
    parser.add_argument("--file", default=None, help="sentinel path (default $KILL_SWITCH_FILE)")
    parser.add_argument("--reason", default="operator kill switch engaged")
    args = parser.parse_args(argv)
    path = engage(_sentinel_path(args.file), args.reason)
    print(f"kill switch ENGAGED via {path}")
    return 0


def resume_main(argv: list[str] | None = None) -> int:
    """``traderstack-resume``: clear the sentinel file."""

    parser = argparse.ArgumentParser(description="Clear the TraderStack kill-switch sentinel file")
    parser.add_argument("--file", default=None, help="sentinel path (default $KILL_SWITCH_FILE)")
    args = parser.parse_args(argv)
    path = _sentinel_path(args.file)
    removed = disengage(path)
    if removed:
        print(f"kill switch sentinel removed: {path}")
    else:
        print(f"no kill switch sentinel at {path}")
    print("other channels (KILL_SWITCH setting, Redis key, SIGUSR1) are unaffected")
    return 0
