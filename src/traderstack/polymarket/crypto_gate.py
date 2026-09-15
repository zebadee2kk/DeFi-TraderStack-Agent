"""Withhold-only Crucix stand-aside for the #142 wedge tape.

Direction is the whole point: *unknown is not clear*. Only a positively known
clear Crucix read leaves a row eligible; adverse, unavailable and
not_configured are all stand-aside. ``apply_crucix_gate`` can therefore only
clear bits from a mask - it has no size or side output, never reads ``Settings``
or ``RiskEngine``, and cannot turn a False into a True.
"""

from __future__ import annotations

from traderstack.intelligence import NewsSnapshot
from traderstack.polymarket.crypto_models import CrucixStatus


def crucix_status_from_snapshot(
    snapshot: NewsSnapshot | None,
    *,
    configured: bool,
) -> CrucixStatus:
    """Map a Crucix read to a status. Anything uncertain stands aside."""

    if not configured:
        return CrucixStatus.NOT_CONFIGURED
    if snapshot is None:
        return CrucixStatus.UNAVAILABLE
    if snapshot.adverse_event:
        return CrucixStatus.ADVERSE
    return CrucixStatus.CLEAR


def stand_aside(status: CrucixStatus) -> bool:
    """True unless the feed positively said clear."""

    return status is not CrucixStatus.CLEAR


def apply_crucix_gate(
    mask: tuple[bool, ...],
    statuses: tuple[CrucixStatus, ...],
) -> tuple[bool, ...]:
    """Return ``mask`` with every stand-aside row cleared.

    Invariant (pinned by tests/security/test_polymarket_crypto_wedge_boundary.py):
    the output is a bitwise subset of the input. The gate can only remove
    would-be trades; it can never add one, size one, or choose a side.
    """

    if len(mask) != len(statuses):
        raise ValueError("mask and statuses must have the same length")
    return tuple(
        bit and not stand_aside(status) for bit, status in zip(mask, statuses, strict=True)
    )
