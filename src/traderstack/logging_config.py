"""Structured logging setup (structlog) shared by every entrypoint.

JSON output outside development so logs are machine-parseable when shipped to
Loki/CloudWatch/etc; a readable console renderer locally. A redaction
processor strips anything that looks like a secret regardless of environment
so credentials never reach stdout, an audit sink, or a log aggregator.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import structlog
from structlog.typing import EventDict, WrappedLogger

if TYPE_CHECKING:
    from traderstack.config import Settings

_REDACTED = "***REDACTED***"
# Matches keys containing any of these fragments, case-insensitively. Kept
# broad on purpose: it is far cheaper to over-redact an event-loop-adjacent
# field than to leak a credential into a shipped log.
_SECRET_KEY_PATTERN = re.compile(r"(key|token|password|secret)", re.IGNORECASE)


def redact_secrets(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor: replace the value of any secret-looking key.

    Walks one level of nested dicts/lists too, since event payloads
    (e.g. a dumped Settings or request body) commonly nest credentials.
    """

    def _scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (_REDACTED if _SECRET_KEY_PATTERN.search(str(key)) else _scrub(val))
                for key, val in value.items()
            }
        if isinstance(value, list):
            return [_scrub(item) for item in value]
        return value

    return {
        key: (_REDACTED if _SECRET_KEY_PATTERN.search(str(key)) else _scrub(value))
        for key, value in event_dict.items()
    }


def configure_logging(settings: Settings) -> None:
    """Configure structlog (and stdlib logging) for the given settings.

    JSON renderer when ``settings.app_env != "development"``, a human-readable
    console renderer otherwise. Safe to call multiple times (e.g. in tests).
    """

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        redact_secrets,
    ]

    if settings.app_env == "development":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
