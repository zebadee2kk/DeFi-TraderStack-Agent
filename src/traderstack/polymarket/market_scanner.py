from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from traderstack.polymarket.clob import BookMetrics
from traderstack.polymarket.parse import _json_list, _parse_datetime

SCORING_CONTRACT_VERSION = "polymarket-market-quality-v1"

# These weights rank researchability/execution quality only. They do not
# estimate expected return and cannot authorize a trade.
QUALITY_WEIGHTS = {
    "liquidity": 0.25,
    "spread": 0.20,
    "depth": 0.20,
    "time_to_resolution": 0.10,
    "wallet_coverage": 0.125,
    "external_context_coverage": 0.125,
}


@dataclass(frozen=True)
class MarketScanInput:
    market_id: str
    condition_id: str
    token_id: str
    category: str
    observed_at: datetime
    close_at: datetime
    best_bid: float | None
    best_ask: float | None
    bid_depth_usd: float | None
    ask_depth_usd: float | None
    liquidity_usd: float | None
    wallet_coverage: float | None
    external_context_coverage: float | None
    evidence_fresh: bool
    collector_healthy: bool


@dataclass(frozen=True)
class MarketScanResult:
    market_id: str
    condition_id: str
    token_id: str
    category: str
    observed_at: datetime
    eligible: bool
    quality_score: float | None
    scoring_contract_version: str
    components: dict[str, float]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _bounded_unit(value: float | None) -> float | None:
    if value is None or not isfinite(value):
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value


def _positive(value: float | None) -> float | None:
    if value is None or not isfinite(value) or value < 0.0:
        return None
    return value


def _liquidity_score(liquidity_usd: float) -> float:
    # Saturates at $50k visible/declared liquidity.
    return min(liquidity_usd / 50_000.0, 1.0)


def _spread_score(best_bid: float, best_ask: float) -> float:
    # Probability spread: full score at <=1 percentage point, zero at >=10.
    spread = best_ask - best_bid
    if spread <= 0.01:
        return 1.0
    if spread >= 0.10:
        return 0.0
    return 1.0 - ((spread - 0.01) / 0.09)


def _depth_score(bid_depth_usd: float, ask_depth_usd: float) -> float:
    # Conservative: score from the weaker side, saturating at $2,500.
    return min(min(bid_depth_usd, ask_depth_usd) / 2_500.0, 1.0)


def _time_score(hours: float) -> float:
    # Prefer enough time to investigate/execute without ranking very distant
    # markets as automatically superior. This is not an alpha assumption.
    if hours <= 0.0:
        return 0.0
    if hours < 1.0:
        return hours
    if hours <= 24.0 * 7:
        return 1.0
    if hours >= 24.0 * 60:
        return 0.5
    span = 24.0 * 53
    return 1.0 - (0.5 * ((hours - 24.0 * 7) / span))


def score_market(item: MarketScanInput) -> MarketScanResult:
    reasons: list[str] = []

    observed_at = item.observed_at
    close_at = item.close_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    else:
        observed_at = observed_at.astimezone(UTC)
    if close_at.tzinfo is None:
        close_at = close_at.replace(tzinfo=UTC)
    else:
        close_at = close_at.astimezone(UTC)

    if not item.market_id.strip():
        reasons.append("missing_market_id")
    if not item.condition_id.strip():
        reasons.append("missing_condition_id")
    if not item.token_id.strip():
        reasons.append("missing_token_id")
    if not item.evidence_fresh:
        reasons.append("stale_evidence")
    if not item.collector_healthy:
        reasons.append("collector_unhealthy")

    bid = item.best_bid
    ask = item.best_ask
    if bid is None or ask is None:
        reasons.append("one_sided_book")
    elif not (0.0 <= bid <= 1.0 and 0.0 <= ask <= 1.0):
        reasons.append("invalid_probability_price")
    elif ask < bid:
        reasons.append("crossed_book")

    liquidity = _positive(item.liquidity_usd)
    bid_depth = _positive(item.bid_depth_usd)
    ask_depth = _positive(item.ask_depth_usd)
    wallet_coverage = _bounded_unit(item.wallet_coverage)
    external_coverage = _bounded_unit(item.external_context_coverage)

    if liquidity is None:
        reasons.append("missing_liquidity")
    if bid_depth is None or ask_depth is None:
        reasons.append("missing_depth")
    if wallet_coverage is None:
        reasons.append("missing_wallet_coverage")
    if external_coverage is None:
        reasons.append("missing_external_context_coverage")

    hours = (close_at - observed_at).total_seconds() / 3600.0
    if hours <= 0.0:
        reasons.append("closed_or_expired")

    if reasons:
        return MarketScanResult(
            market_id=item.market_id,
            condition_id=item.condition_id,
            token_id=item.token_id,
            category=item.category.upper(),
            observed_at=observed_at,
            eligible=False,
            quality_score=None,
            scoring_contract_version=SCORING_CONTRACT_VERSION,
            components={},
            reasons=tuple(sorted(set(reasons))),
        )

    assert bid is not None and ask is not None
    assert liquidity is not None
    assert bid_depth is not None and ask_depth is not None
    assert wallet_coverage is not None and external_coverage is not None

    components = {
        "liquidity": _liquidity_score(liquidity),
        "spread": _spread_score(bid, ask),
        "depth": _depth_score(bid_depth, ask_depth),
        "time_to_resolution": _time_score(hours),
        "wallet_coverage": wallet_coverage,
        "external_context_coverage": external_coverage,
    }
    score = sum(QUALITY_WEIGHTS[name] * value for name, value in components.items())

    return MarketScanResult(
        market_id=item.market_id,
        condition_id=item.condition_id,
        token_id=item.token_id,
        category=item.category.upper(),
        observed_at=observed_at,
        eligible=True,
        quality_score=round(score, 12),
        scoring_contract_version=SCORING_CONTRACT_VERSION,
        components=components,
        reasons=(),
    )


def rank_markets(items: list[MarketScanInput]) -> list[MarketScanResult]:
    results = [score_market(item) for item in items]
    return sorted(
        results,
        key=lambda row: (
            not row.eligible,
            -(row.quality_score if row.quality_score is not None else -1.0),
            row.market_id,
            row.token_id,
        ),
    )


def _numeric(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def scan_input_from_gamma(
    payload: dict[str, Any],
    *,
    observed_at: datetime,
    category: str,
    book: BookMetrics,
    wallet_coverage: float | None,
    external_context_coverage: float | None,
    evidence_fresh: bool,
    collector_healthy: bool,
) -> MarketScanInput | None:
    """Reduce one untrusted open Gamma market into a scanner input.

    Only the YES token is ranked in this first slice. Missing identifiers,
    close time, liquidity or token metadata cause the market to be skipped
    rather than guessed.
    """

    if payload.get("closed") is True or payload.get("active") is False:
        return None
    if payload.get("acceptingOrders") is False or payload.get("enableOrderBook") is False:
        return None

    token_ids = _json_list(payload.get("clobTokenIds") or payload.get("clob_token_ids"))
    if len(token_ids) < 2 or not token_ids[0].strip():
        return None

    condition_raw = payload.get("conditionId") or payload.get("condition_id")
    market_raw = payload.get("id") or condition_raw
    close_at = _parse_datetime(payload.get("endDate") or payload.get("end_date_iso"))
    if not isinstance(condition_raw, str) or not condition_raw.strip():
        return None
    if market_raw is None or not str(market_raw).strip() or close_at is None:
        return None

    liquidity_raw = payload.get("liquidityNum")
    if liquidity_raw is None:
        liquidity_raw = payload.get("liquidity")
    if liquidity_raw is None:
        liquidity_raw = payload.get("liquidity_usd")
    liquidity = _numeric(liquidity_raw)
    if liquidity is None:
        return None

    return MarketScanInput(
        market_id=str(market_raw),
        condition_id=condition_raw,
        token_id=token_ids[0],
        category=category,
        observed_at=observed_at,
        close_at=close_at,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        bid_depth_usd=book.bid_depth_usd,
        ask_depth_usd=book.ask_depth_usd,
        liquidity_usd=liquidity,
        wallet_coverage=wallet_coverage,
        external_context_coverage=external_context_coverage,
        evidence_fresh=evidence_fresh,
        collector_healthy=collector_healthy,
    )
