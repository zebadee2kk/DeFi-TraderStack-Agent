"""Frozen Kraken Pro spot fee-tier catalog and the research cost resolver (#138).

Research costs used to be ``PRETRADE_FEE_BPS=10`` + ``PRETRADE_SLIPPAGE_BPS=5``
per leg. Kraken's published Pro spot schedule starts at 0.40% maker / 0.80%
taker at Tier 1 ($0+ 30-day volume), so a tiny-capital pilot pays four to
eight times the modelled cost per side. This module freezes the tiers the
odds brief (``docs/artifacts/research/odds-brief-2026-09-13.md`` section 5)
transcribed from ``kraken.com/features/fee-schedule`` and exposes the single
resolver every research CLI and the paper fill wiring use.

Rules:

* The catalog is a frozen constant with a ``source`` / ``read_on`` stamp. It
  is never scraped at runtime; re-read the schedule and bump ``read_on`` when
  the tiers change. Intermediate tiers not in the brief are not invented.
* Every paper fill and every research print is scored at the **taker** leg.
  Maker bps are reported for information only: no paper post-only fill-rate
  evidence exists yet (post-only orders are #73's design), so no report may
  assume maker fees. ``FeeTierStamp.role`` can only be ``"taker"``.
* The tier is read only from ``Settings`` (version-controlled) or an explicit
  research CLI flag. It never comes from a venue payload, provider response
  or meta-agent output, and ``RiskEngine`` never reads it: a fee can only
  make research and paper NAV *more* conservative.
* Pure, no I/O, no network. Must not import ``traderstack.config`` at module
  level (``Settings`` imports this module).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from traderstack.config import Settings

KRAKEN_FEE_SCHEDULE_SOURCE = "kraken.com/features/fee-schedule"
KRAKEN_FEE_SCHEDULE_READ_ON = "2026-09-13"

MODELLED_FEE_TIER_ID = "modelled"
PILOT_FEE_TIER_ID = "kraken_pro_spot_t1"

MAKER_NOT_ASSUMED_NOTE = (
    "Maker bps shown for information only, not assumed: "
    "no paper post-only fill-rate evidence exists yet."
)


@dataclass(frozen=True)
class FeeTier:
    """One row of a published venue fee schedule, in basis points per leg."""

    tier_id: str
    venue: str
    label: str
    min_30d_volume_usd: float
    maker_bps: float
    taker_bps: float
    source: str
    read_on: str


KRAKEN_PRO_SPOT_TIERS: tuple[FeeTier, ...] = (
    FeeTier(
        tier_id="kraken_pro_spot_t1",
        venue="kraken",
        label="Tier 1 ($0+ 30d)",
        min_30d_volume_usd=0.0,
        maker_bps=40.0,
        taker_bps=80.0,
        source=KRAKEN_FEE_SCHEDULE_SOURCE,
        read_on=KRAKEN_FEE_SCHEDULE_READ_ON,
    ),
    FeeTier(
        tier_id="kraken_pro_spot_t2",
        venue="kraken",
        label="Tier 2 ($2.5K+ 30d)",
        min_30d_volume_usd=2_500.0,
        maker_bps=30.0,
        taker_bps=60.0,
        source=KRAKEN_FEE_SCHEDULE_SOURCE,
        read_on=KRAKEN_FEE_SCHEDULE_READ_ON,
    ),
    FeeTier(
        tier_id="kraken_pro_spot_t3",
        venue="kraken",
        label="Tier 3 ($10K+ 30d)",
        min_30d_volume_usd=10_000.0,
        maker_bps=22.0,
        taker_bps=38.0,
        source=KRAKEN_FEE_SCHEDULE_SOURCE,
        read_on=KRAKEN_FEE_SCHEDULE_READ_ON,
    ),
    FeeTier(
        tier_id="kraken_pro_spot_t8",
        venue="kraken",
        label="Tier 8 (~$500K+ 30d)",
        min_30d_volume_usd=500_000.0,
        maker_bps=8.0,
        taker_bps=20.0,
        source=KRAKEN_FEE_SCHEDULE_SOURCE,
        read_on=KRAKEN_FEE_SCHEDULE_READ_ON,
    ),
    FeeTier(
        tier_id="kraken_pro_spot_t12",
        venue="kraken",
        label="Tier 12 ($10M+ 30d)",
        min_30d_volume_usd=10_000_000.0,
        maker_bps=0.0,
        taker_bps=10.0,
        source=KRAKEN_FEE_SCHEDULE_SOURCE,
        read_on=KRAKEN_FEE_SCHEDULE_READ_ON,
    ),
)

# Reproduces the pre-#138 behaviour: research and paper fills charged
# PAPER_FEE_BPS (default 10) per leg. Not a venue tier.
MODELLED_FEE_TIER = FeeTier(
    tier_id=MODELLED_FEE_TIER_ID,
    venue="modelled",
    label="pre-#138 modelled fee; not a venue tier",
    min_30d_volume_usd=0.0,
    maker_bps=10.0,
    taker_bps=10.0,
    source="PAPER_FEE_BPS / PRETRADE_FEE_BPS defaults",
    read_on=KRAKEN_FEE_SCHEDULE_READ_ON,
)

ALL_FEE_TIERS: tuple[FeeTier, ...] = (*KRAKEN_PRO_SPOT_TIERS, MODELLED_FEE_TIER)
FEE_TIER_IDS: tuple[str, ...] = tuple(tier.tier_id for tier in ALL_FEE_TIERS)
_FEE_TIERS_BY_ID: dict[str, FeeTier] = {tier.tier_id: tier for tier in ALL_FEE_TIERS}

# Written out (not built from FEE_TIER_IDS) so ``Settings`` can use the same
# literal without importing this module at class-definition time; a test
# asserts the two agree.
FeeTierId = Literal[
    "kraken_pro_spot_t1",
    "kraken_pro_spot_t2",
    "kraken_pro_spot_t3",
    "kraken_pro_spot_t8",
    "kraken_pro_spot_t12",
    "modelled",
]

EXPLICIT_FEE_TIER_ID = "explicit"


def resolve_fee_tier(tier_id: str) -> FeeTier:
    """Return the frozen tier for ``tier_id`` or raise naming the valid ids."""

    try:
        return _FEE_TIERS_BY_ID[tier_id]
    except KeyError:
        raise ValueError(
            f"unknown fee tier {tier_id!r}; valid ids: {', '.join(FEE_TIER_IDS)}"
        ) from None


def effective_taker_bps(tier_id: str, *, paper_fee_bps: float) -> float:
    """Taker bps charged on a paper fill: the tier's taker leg, or
    ``PAPER_FEE_BPS`` when the tier is ``modelled``."""

    tier = resolve_fee_tier(tier_id)
    if tier.tier_id == MODELLED_FEE_TIER_ID:
        return float(paper_fee_bps)
    return tier.taker_bps


class FeeTierStamp(BaseModel):
    """The fee tier a research report was scored at. Embedded in every report
    so a reader can see which fee killed (or spared) a candidate."""

    tier_id: str
    venue: str
    label: str
    maker_bps: float = Field(ge=0)
    taker_bps: float = Field(ge=0)
    # Only the taker leg may be scored until post-only orders (#73) exist and
    # a month of paper fill-rate data is on record. There is no maker role.
    role: Literal["taker"] = "taker"
    fee_bps_used: float = Field(ge=0)
    source: str
    read_on: str
    note: str = MAKER_NOT_ASSUMED_NOTE

    def render_line(self) -> str:
        return (
            f"Fee tier: {self.label} maker {self.maker_bps:g} / taker "
            f"{self.taker_bps:g} bps ({self.tier_id}); scored at {self.role} "
            f"{self.fee_bps_used:g} bps. {self.note}"
        )


def stamp_for_tier(tier: FeeTier, *, fee_bps_used: float) -> FeeTierStamp:
    return FeeTierStamp(
        tier_id=tier.tier_id,
        venue=tier.venue,
        label=tier.label,
        maker_bps=tier.maker_bps,
        taker_bps=tier.taker_bps,
        fee_bps_used=fee_bps_used,
        source=tier.source,
        read_on=tier.read_on,
    )


@dataclass(frozen=True)
class ResearchCosts:
    fee_bps: float
    slippage_bps: float
    stamp: FeeTierStamp


def resolve_research_costs(
    *,
    fee_bps: float | None,
    fee_tier: str | None,
    settings: Settings,
    slippage_bps: float | None = None,
) -> ResearchCosts:
    """Resolve the per-leg research costs and the stamp every report prints.

    Precedence: explicit ``--fee-bps`` (stamped ``explicit``) > ``--fee-tier``
    > ``settings.paper_fee_tier``. When a tier applies the fee used is
    ``max(PRETRADE_FEE_BPS, tier taker)`` so the research fee stays the
    conservative of the pre-trade and paper fees exactly as
    ``research_fee_bps`` does; a tier can never make research cheaper than
    ``PRETRADE_FEE_BPS``. Slippage stays ``PRETRADE_SLIPPAGE_BPS`` unless
    given explicitly.
    """

    resolved_slippage = (
        float(slippage_bps) if slippage_bps is not None else settings.pretrade_slippage_bps
    )
    if fee_bps is not None:
        if fee_bps < 0:
            raise ValueError("fee_bps must be >= 0")
        explicit = float(fee_bps)
        stamp = FeeTierStamp(
            tier_id=EXPLICIT_FEE_TIER_ID,
            venue="explicit",
            label=f"--fee-bps {explicit:g}",
            maker_bps=explicit,
            taker_bps=explicit,
            fee_bps_used=explicit,
            source="operator flag",
            read_on=KRAKEN_FEE_SCHEDULE_READ_ON,
            note=(
                "Explicit per-leg fee from the command line; not a venue tier. "
                + MAKER_NOT_ASSUMED_NOTE
            ),
        )
        return ResearchCosts(fee_bps=explicit, slippage_bps=resolved_slippage, stamp=stamp)
    tier = resolve_fee_tier(fee_tier if fee_tier is not None else settings.paper_fee_tier)
    taker = effective_taker_bps(tier.tier_id, paper_fee_bps=settings.paper_fee_bps)
    used = max(settings.pretrade_fee_bps, taker)
    if tier.tier_id == MODELLED_FEE_TIER_ID:
        stamp = FeeTierStamp(
            tier_id=tier.tier_id,
            venue=tier.venue,
            label=tier.label,
            maker_bps=taker,
            taker_bps=taker,
            fee_bps_used=used,
            source=tier.source,
            read_on=tier.read_on,
            note=(
                "PAPER_FEE_TIER=modelled: pre-#138 PAPER_FEE_BPS model, four to "
                "eight times optimistic versus Kraken Pro Tier 1. " + MAKER_NOT_ASSUMED_NOTE
            ),
        )
    else:
        stamp = stamp_for_tier(tier, fee_bps_used=used)
    return ResearchCosts(fee_bps=used, slippage_bps=resolved_slippage, stamp=stamp)


def add_fee_tier_argument(parser: argparse.ArgumentParser) -> None:
    """Attach ``--fee-tier`` to an argparse parser (kept here so every research
    CLI shares one help string and one default of ``None`` = PAPER_FEE_TIER)."""

    parser.add_argument(
        "--fee-tier",
        default=None,
        choices=FEE_TIER_IDS,
        help=(
            "Kraken Pro spot fee tier scored at the taker leg (default: PAPER_FEE_TIER, "
            f"{PILOT_FEE_TIER_ID}); --fee-bps overrides it and stamps the report 'explicit'"
        ),
    )
