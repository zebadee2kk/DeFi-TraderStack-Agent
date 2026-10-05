from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, model_validator


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SignalCandidateRecord(BaseModel):
    candidate_at: datetime
    asset: str = Field(min_length=1, max_length=32)
    hypothesis_id: str = Field(min_length=1, max_length=128)
    hypothesis_version: str = Field(min_length=1, max_length=64)
    horizon_seconds: int = Field(gt=0)
    direction: int = Field(ge=-1, le=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    feature_query_hash: str = Field(min_length=1, max_length=128)
    schema_version: str = Field(default="1.0", min_length=1, max_length=32)

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> SignalCandidateRecord:
        if self.direction == 0:
            raise ValueError("direction must be -1 or 1")
        self.candidate_at = _utc(self.candidate_at)
        self.asset = self.asset.upper()
        return self

    def event_key(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class SignalOutcomeRecord(BaseModel):
    candidate_event_key: str = Field(min_length=64, max_length=64)
    candidate_at: datetime
    outcome_at: datetime
    horizon_seconds: int = Field(gt=0)
    gross_return: float
    net_return: float
    gross_pnl_usd: float | None = None
    net_pnl_usd: float | None = None
    fee_bps: float = Field(ge=0.0)
    slippage_bps: float = Field(ge=0.0)
    schema_version: str = Field(default="1.0", min_length=1, max_length=32)

    @model_validator(mode="after")
    def _enforce_horizon_and_finite_values(self) -> SignalOutcomeRecord:
        self.candidate_at = _utc(self.candidate_at)
        self.outcome_at = _utc(self.outcome_at)
        required_at = self.candidate_at + timedelta(seconds=self.horizon_seconds)
        if self.outcome_at < required_at:
            raise ValueError("outcome_at precedes the registered candidate horizon")
        numeric = (
            self.gross_return,
            self.net_return,
            self.gross_pnl_usd,
            self.net_pnl_usd,
            self.fee_bps,
            self.slippage_bps,
        )
        if any(value is not None and not math.isfinite(float(value)) for value in numeric):
            raise ValueError("signal outcome values must be finite")
        return self

    def event_key(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


def build_candidate_row(record: SignalCandidateRecord) -> dict[str, object]:
    return {
        "event_key": record.event_key(),
        "candidate_at": record.candidate_at,
        "asset": record.asset,
        "hypothesis_id": record.hypothesis_id,
        "hypothesis_version": record.hypothesis_version,
        "horizon_seconds": record.horizon_seconds,
        "direction": record.direction,
        "confidence": record.confidence,
        "feature_query_hash": record.feature_query_hash,
        "schema_version": record.schema_version,
    }


def build_outcome_row(record: SignalOutcomeRecord) -> dict[str, object]:
    return {
        "event_key": record.event_key(),
        "candidate_event_key": record.candidate_event_key,
        "candidate_at": record.candidate_at,
        "outcome_at": record.outcome_at,
        "horizon_seconds": record.horizon_seconds,
        "gross_return": record.gross_return,
        "net_return": record.net_return,
        "gross_pnl_usd": record.gross_pnl_usd,
        "net_pnl_usd": record.net_pnl_usd,
        "fee_bps": record.fee_bps,
        "slippage_bps": record.slippage_bps,
        "schema_version": record.schema_version,
    }
