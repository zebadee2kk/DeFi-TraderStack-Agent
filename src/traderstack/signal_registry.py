"""Signal registry and versioning (Epic 4).

Every strategy, ensemble, and feature builder in this codebase is a frozen
dataclass whose behaviour is fully determined by its constructor parameters. That
means a stable, reproducible version identifier can be derived purely by
reflection -- `version_of(obj)` combines the object's class name with a short hash
of its (recursively normalized) constructor parameters, with no cooperation
required from the class itself. Two instances built with identical parameters
always produce the same version; changing any parameter changes it.

`SignalRegistry` records `(name -> version)` mappings so a backtest, walk-forward
run, or live decision can be traced back to the exact strategy configuration that
produced it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _normalize(value: Any) -> Any:
    """Recursively convert a value into a JSON-stable, order-independent form."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _normalize(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _normalize(model_dump())
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list | tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, float):
        # Avoid float-repr noise (e.g. 0.1 + 0.2) changing the hash spuriously.
        return round(value, 12)
    return value


def params_hash(obj: Any) -> str:
    """A short, stable hash of an object's (recursively normalized) parameters."""
    payload = json.dumps(_normalize(obj), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def version_of(obj: Any) -> str:
    """A version string combining the object's class name and a params hash.

    Identical constructor parameters always yield the same version; any change to
    a parameter (including a nested strategy inside an ensemble) changes it.
    """
    return f"{type(obj).__name__}:{params_hash(obj)}"


@dataclass(frozen=True)
class SignalRegistration:
    name: str
    version: str
    kind: str = "strategy"


@dataclass
class SignalRegistry:
    """In-memory record of which signal-producing components are in play."""

    _entries: dict[str, SignalRegistration] = field(default_factory=dict)

    def register(self, name: str, obj: Any, *, kind: str = "strategy") -> SignalRegistration:
        entry = SignalRegistration(name=name, version=version_of(obj), kind=kind)
        self._entries[name] = entry
        return entry

    def get(self, name: str) -> SignalRegistration | None:
        return self._entries.get(name)

    def all(self) -> tuple[SignalRegistration, ...]:
        return tuple(self._entries.values())
