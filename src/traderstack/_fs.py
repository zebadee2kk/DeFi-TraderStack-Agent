"""Durable filesystem helpers for ledger, checkpoint and audit writers.

Atomic replace of a temp file is only crash-safe against *process* death.
Against an OS crash or power loss the rename can become durable while the
file contents are still in the page cache — the classic ext4/XFS empty-file-
after-rename case. ``write_atomic`` fsyncs the temp file and then the parent
directory after ``os.replace``.

JSONL appenders call ``os.fsync`` after each record. The cadence is one line
per cycle (~5s), so the cost is negligible.

On some filesystems (certain NFS and overlayfs mounts) ``os.fsync`` of a
directory fd raises ``OSError`` (``EINVAL`` / ``EBADF``). That is swallowed
as best-effort after the *file* fsync has already succeeded. Operators on
such mounts should put ``--ledger-path`` on local POSIX storage; see
``docs/RUNBOOK.md``.
"""

from __future__ import annotations

import os
from pathlib import Path


class DurableStateError(ValueError):
    """An existing checkpoint or ledger file is empty or unparsable.

    A missing file is a legitimate fresh start. An existing-but-corrupt file
    is not: treating it as empty would silently forget every in-flight order
    and license a double submission.
    """


def fsync_directory(directory: Path) -> None:
    """Best-effort directory fsync so a rename is durable.

    ``OSError`` from the open or the fsync is ignored: directory fsync is
    not supported on every filesystem, and the file contents have already
    been fsynced. Operators should still prefer local POSIX storage for the
    idempotency ledger.
    """

    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        return
    finally:
        os.close(dir_fd)


def write_atomic(path: Path, payload: str, *, encoding: str = "utf-8") -> None:
    """Write ``payload`` via temp file + fsync + replace + directory fsync."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding=encoding) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def append_jsonl(path: Path, line: str, *, encoding: str = "utf-8") -> None:
    """Append one JSONL record and fsync it.

    A newly created file also gets a directory fsync so the directory entry
    itself survives a crash.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    if not line.endswith("\n"):
        line = line + "\n"
    with path.open("a", encoding=encoding) as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    if created:
        fsync_directory(path.parent)


def read_text_strict(path: Path, *, what: str) -> str | None:
    """Read a durable JSON document.

    Returns ``None`` when the file does not exist. Raises
    ``DurableStateError`` when it exists but is empty (the torn-write
    signature). Callers still validate JSON themselves and wrap parse
    failures as ``DurableStateError``.
    """

    path = Path(path)
    if not path.exists():
        return None
    payload = path.read_text(encoding="utf-8")
    if not payload.strip():
        raise DurableStateError(
            f"{what} at {path} exists but is empty; refusing to treat this as a fresh start"
        )
    return payload
