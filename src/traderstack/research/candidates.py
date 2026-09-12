"""Pre-registered standalone strategy candidates for `traderstack-strategy-search`.

Each candidate is a single voter: it may take a side on its own. That is
deliberate -- the paper ensemble's 2-of-3 consensus is a *combination* rule,
not an evaluation of whether MA, momentum, or mean-reversion has edge by
itself. Search scores the pieces; promotion is what may later put a winner
back into the paper voter set.

Optional feature families (liquidation z-score, funding, open interest,
cross-venue divergence) are included in the catalog so they can be scored
when a point-in-time series is supplied. They are skipped, not invented,
when the series is absent.

Vol-regime filters wrap price voters and *can* register as paper voters
(they need only candles). Liquidation-agree wrappers require an aligned
series and stay research-only on the Kraken Spot OHLC paper path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from traderstack.candles import Candle
from traderstack.indicators import moving_average, zscore
from traderstack.models import Side
from traderstack.strategies import (
    MeanReversionStrategy,
    MomentumStrategy,
    Regime,
    StrategySignal,
    TrendStrategy,
)

CandidateFamily = Literal[
    "ma_cross",
    "momentum",
    "mean_reversion",
    "liquidation_z",
    "funding_z",
    "open_interest_z",
    "cross_venue",
]


@dataclass(frozen=True)
class AlwaysOnTrendStrategy:
    """MA cross that always takes a side (the "spam both ways" baseline).

    Distinct from `TrendStrategy`, which stays flat unless the regime matches.
    """

    strategy_id: str = "ma_always_on_v1"
    short_window: int = 10
    long_window: int = 30

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        if len(candles) < self.long_window:
            raise ValueError("insufficient candles for always-on MA")
        short = moving_average(candles, self.short_window)
        long = moving_average(candles, self.long_window)
        separation = short / long - 1.0
        side = Side.BUY if short >= long else Side.SELL
        confidence = min(abs(separation) / 0.01, 1.0)
        score = max(-1.0, min(1.0, separation / 0.01))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=confidence,
            regime=regime,
            rationale=f"always-on MA short={short:.4f} long={long:.4f}",
        )


@dataclass(frozen=True)
class FeatureZVoter:
    """Fade (or follow) an aligned exogenous z-score series, point-in-time only.

    `values` is `(opened_at, value)` sorted by time. Evaluation uses only
    points at or before the last candle in the window it is given.
    """

    strategy_id: str
    feature_name: str
    values: tuple[tuple[datetime, float], ...] = ()
    values_by_symbol: tuple[tuple[str, tuple[tuple[datetime, float], ...]], ...] = ()
    lookback: int = 20
    entry_z: float = 1.5
    fade: bool = True

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        cutoff = candles[-1].opened_at
        series = self.series_for(candles[-1].symbol)
        recent = [value for ts, value in series if ts <= cutoff][-self.lookback :]
        if len(recent) < self.lookback:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale=f"{self.feature_name}: insufficient aligned history",
            )
        current_z = zscore(recent[-1], recent)
        side: Side | None = None
        if self.fade:
            if current_z <= -self.entry_z:
                side = Side.BUY
            elif current_z >= self.entry_z:
                side = Side.SELL
        else:
            if current_z >= self.entry_z:
                side = Side.BUY
            elif current_z <= -self.entry_z:
                side = Side.SELL
        confidence = min(abs(current_z) / max(self.entry_z * 2, 1e-9), 1.0)
        score = -current_z if self.fade else current_z
        score = max(-1.0, min(1.0, score / max(self.entry_z * 2, 1e-9)))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=confidence if side is not None else 0.0,
            regime=regime,
            rationale=f"{self.feature_name} z={current_z:.3f}",
        )

    def series_for(self, symbol: str) -> tuple[tuple[datetime, float], ...]:
        key = symbol.upper()
        for name, series in self.values_by_symbol:
            if name == key:
                return series
        return self.values


def vol_regime_agrees(family: str, side: Side, regime: Regime) -> bool:
    """True when the classified vol/trend regime agrees with the proposed side.

    Trend / momentum / always-on MA: buy only in uptrend or high-vol, sell
    only in downtrend or high-vol. Mean-reversion: only in RANGE (do not
    fade a volatility spike).
    """
    if family == "mean_reversion":
        return regime is Regime.RANGE
    if side is Side.BUY:
        return regime in {Regime.TRENDING_UP, Regime.HIGH_VOLATILITY}
    if side is Side.SELL:
        return regime in {Regime.TRENDING_DOWN, Regime.HIGH_VOLATILITY}
    return False


def liquidation_z_agrees(
    side: Side,
    *,
    z_value: float,
    entry_z: float,
    fade: bool = True,
) -> bool:
    """Fade: buy after long washouts (z<=-entry), sell after short squeezes."""
    if fade:
        if side is Side.BUY:
            return z_value <= -entry_z
        if side is Side.SELL:
            return z_value >= entry_z
        return False
    if side is Side.BUY:
        return z_value >= entry_z
    if side is Side.SELL:
        return z_value <= -entry_z
    return False


@dataclass(frozen=True)
class RegimeAgreeVoter:
    """Wrap a price voter; flatten the side when vol and/or liq-z disagree."""

    inner: object
    strategy_id: str
    family: str
    vol_filter: bool = True
    liquidation: tuple[tuple[datetime, float], ...] = ()
    liquidation_by_symbol: tuple[tuple[str, tuple[tuple[datetime, float], ...]], ...] = ()
    liq_lookback: int = 20
    liq_entry_z: float = 1.0
    liq_fade: bool = True

    def _liq_series(self, symbol: str) -> tuple[tuple[datetime, float], ...]:
        key = symbol.upper()
        for name, series in self.liquidation_by_symbol:
            if name == key:
                return series
        return self.liquidation

    def _liq_z(self, candles: tuple[Candle, ...]) -> float | None:
        series = self._liq_series(candles[-1].symbol)
        if not series:
            return None
        cutoff = candles[-1].opened_at
        recent = [value for ts, value in series if ts <= cutoff][-self.liq_lookback :]
        if len(recent) < self.liq_lookback:
            return None
        return zscore(recent[-1], recent)

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        evaluate = getattr(self.inner, "evaluate", None)
        if evaluate is None:
            raise TypeError("regime-agree inner voter is missing evaluate()")
        signal = evaluate(candles, regime)
        if signal.side is None:
            return signal.model_copy(update={"strategy_id": self.strategy_id})
        reasons: list[str] = [signal.rationale]
        if self.vol_filter and not vol_regime_agrees(self.family, signal.side, regime):
            reasons.append(f"vol-regime {regime} disagrees with {signal.side}")
            return signal.model_copy(
                update={
                    "strategy_id": self.strategy_id,
                    "side": None,
                    "confidence": 0.0,
                    "rationale": "; ".join(reasons),
                }
            )
        if self.liquidation or self.liquidation_by_symbol:
            liq_z = self._liq_z(candles)
            if liq_z is None:
                reasons.append("liquidation z unavailable")
                return signal.model_copy(
                    update={
                        "strategy_id": self.strategy_id,
                        "side": None,
                        "confidence": 0.0,
                        "rationale": "; ".join(reasons),
                    }
                )
            if not liquidation_z_agrees(
                signal.side, z_value=liq_z, entry_z=self.liq_entry_z, fade=self.liq_fade
            ):
                reasons.append(f"liquidation z={liq_z:.3f} disagrees with {signal.side}")
                return signal.model_copy(
                    update={
                        "strategy_id": self.strategy_id,
                        "side": None,
                        "confidence": 0.0,
                        "rationale": "; ".join(reasons),
                    }
                )
            reasons.append(f"liquidation z={liq_z:.3f} agrees")
        return signal.model_copy(
            update={"strategy_id": self.strategy_id, "rationale": "; ".join(reasons)}
        )


@dataclass(frozen=True)
class SearchCandidate:
    candidate_id: str
    family: CandidateFamily
    label: str
    params: dict[str, Any]
    strategy: object
    requires_feature: str | None = None


def _inner_price_strategy(family: str, params: dict[str, Any]) -> object:
    if family == "ma_cross":
        if params.get("always_on"):
            return AlwaysOnTrendStrategy(
                strategy_id=str(
                    params.get("inner_strategy_id", params.get("strategy_id", "ma_always_on_v1"))
                ),
                short_window=int(params["short_window"]),
                long_window=int(params["long_window"]),
            )
        return TrendStrategy(
            strategy_id=str(params.get("inner_strategy_id", params.get("strategy_id", "trend_v1"))),
            short_window=int(params["short_window"]),
            long_window=int(params["long_window"]),
            minimum_separation=float(params.get("minimum_separation", 0.005)),
        )
    if family == "momentum":
        return MomentumStrategy(
            strategy_id=str(
                params.get("inner_strategy_id", params.get("strategy_id", "momentum_v1"))
            ),
            lookback=int(params["lookback"]),
            minimum_momentum=float(params.get("minimum_momentum", 0.02)),
        )
    if family == "mean_reversion":
        return MeanReversionStrategy(
            strategy_id=str(
                params.get("inner_strategy_id", params.get("strategy_id", "mean_reversion_v1"))
            ),
            lookback=int(params["lookback"]),
            entry_z=float(params.get("entry_z", 1.5)),
        )
    raise ValueError(f"family {family!r} is not a price-only voter")


def build_price_strategy(family: str, params: dict[str, Any]) -> object:
    """Rebuild a price-only voter from the catalog params stored in a report."""
    inner = _inner_price_strategy(family, params)
    if params.get("vol_regime_filter"):
        return RegimeAgreeVoter(
            inner=inner,
            strategy_id=str(params.get("strategy_id", "regime_agree")),
            family=family,
            vol_filter=True,
        )
    return inner


def _ma(
    candidate_id: str,
    *,
    short_window: int,
    long_window: int,
    minimum_separation: float = 0.005,
    always_on: bool = False,
    vol_regime_filter: bool = False,
) -> SearchCandidate:
    params: dict[str, Any] = {
        "short_window": short_window,
        "long_window": long_window,
        "minimum_separation": minimum_separation,
        "always_on": always_on,
        "strategy_id": candidate_id,
        "vol_regime_filter": vol_regime_filter,
    }
    strategy = build_price_strategy("ma_cross", params)
    label = f"{'always-on ' if always_on else ''}MA {short_window}/{long_window}" + (
        f" sep>={minimum_separation:g}" if not always_on else ""
    )
    if vol_regime_filter:
        label += " (vol-regime agree)"
    return SearchCandidate(
        candidate_id=candidate_id,
        family="ma_cross",
        label=label,
        params=params,
        strategy=strategy,
    )


def _mom(
    candidate_id: str,
    *,
    lookback: int,
    minimum_momentum: float = 0.02,
    vol_regime_filter: bool = False,
) -> SearchCandidate:
    params: dict[str, Any] = {
        "lookback": lookback,
        "minimum_momentum": minimum_momentum,
        "strategy_id": candidate_id,
        "vol_regime_filter": vol_regime_filter,
    }
    label = f"momentum {lookback}-bar min={minimum_momentum:g}"
    if vol_regime_filter:
        label += " (vol-regime agree)"
    return SearchCandidate(
        candidate_id=candidate_id,
        family="momentum",
        label=label,
        params=params,
        strategy=build_price_strategy("momentum", params),
    )


def _mr(
    candidate_id: str,
    *,
    lookback: int,
    entry_z: float,
    vol_regime_filter: bool = False,
) -> SearchCandidate:
    params: dict[str, Any] = {
        "lookback": lookback,
        "entry_z": entry_z,
        "strategy_id": candidate_id,
        "vol_regime_filter": vol_regime_filter,
    }
    label = f"mean-reversion {lookback}-bar |z|>={entry_z:g}"
    if vol_regime_filter:
        label += " (vol-regime agree / RANGE only)"
    return SearchCandidate(
        candidate_id=candidate_id,
        family="mean_reversion",
        label=label,
        params=params,
        strategy=build_price_strategy("mean_reversion", params),
    )


def default_price_candidates() -> tuple[SearchCandidate, ...]:
    """The pre-registered price-only catalog. Keep this list small and frozen."""
    return (
        _ma("ma_cross_5_20", short_window=5, long_window=20),
        _ma("ma_cross_10_30", short_window=10, long_window=30),
        _ma("ma_cross_20_50", short_window=20, long_window=50),
        _ma("ma_cross_10_30_wide", short_window=10, long_window=30, minimum_separation=0.01),
        _ma("ma_always_on_10_30", short_window=10, long_window=30, always_on=True),
        _mom("momentum_6", lookback=6),
        _mom("momentum_12", lookback=12),
        _mom("momentum_24", lookback=24),
        _mom("momentum_12_strict", lookback=12, minimum_momentum=0.04),
        _mr("mean_reversion_20_1_5", lookback=20, entry_z=1.5),
        _mr("mean_reversion_20_2_0", lookback=20, entry_z=2.0),
        _mr("mean_reversion_10_1_5", lookback=10, entry_z=1.5),
        _mr("mean_reversion_40_2_0", lookback=40, entry_z=2.0),
    )


def _by_symbol(
    mapping: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> tuple[tuple[str, tuple[tuple[datetime, float], ...]], ...]:
    if not mapping:
        return ()
    return tuple((key.upper(), values) for key, values in sorted(mapping.items()))


def _feature_z_candidate(
    *,
    candidate_id: str,
    family: CandidateFamily,
    feature_name: str,
    label: str,
    values: tuple[tuple[datetime, float], ...] | None,
    values_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
    fade: bool,
    entry_z: float = 1.5,
    lookback: int = 20,
) -> SearchCandidate:
    params = {
        "lookback": lookback,
        "entry_z": entry_z,
        "fade": fade,
        "strategy_id": candidate_id,
        "feature_name": feature_name,
    }
    return SearchCandidate(
        candidate_id=candidate_id,
        family=family,
        label=label,
        params=params,
        strategy=FeatureZVoter(
            strategy_id=candidate_id,
            feature_name=feature_name,
            values=values or (),
            values_by_symbol=_by_symbol(values_by_symbol),
            lookback=lookback,
            entry_z=entry_z,
            fade=fade,
        ),
        requires_feature=feature_name,
    )


def _liq_agree_candidate(
    inner: SearchCandidate,
    *,
    liquidation: tuple[tuple[datetime, float], ...] | None,
    liquidation_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None,
) -> SearchCandidate:
    candidate_id = f"{inner.candidate_id}_liq_agree"
    params = dict(inner.params)
    params.update(
        {
            "strategy_id": candidate_id,
            "inner_strategy_id": inner.candidate_id,
            "vol_regime_filter": False,
            "liq_agree": True,
        }
    )
    return SearchCandidate(
        candidate_id=candidate_id,
        family="liquidation_z",
        label=f"{inner.label} (liquidation-z must agree with side)",
        params=params,
        strategy=RegimeAgreeVoter(
            inner=inner.strategy,
            strategy_id=candidate_id,
            family=inner.family,
            vol_filter=False,
            liquidation=liquidation or (),
            liquidation_by_symbol=_by_symbol(liquidation_by_symbol),
        ),
        requires_feature="liquidation_z",
    )


def expanded_price_candidates() -> tuple[SearchCandidate, ...]:
    """Pre-registered expanded catalog: v1 price voters plus vol-regime filters."""
    return default_price_candidates() + (
        _ma("ma_cross_10_30_vol", short_window=10, long_window=30, vol_regime_filter=True),
        _ma(
            "ma_always_on_10_30_vol",
            short_window=10,
            long_window=30,
            always_on=True,
            vol_regime_filter=True,
        ),
        _mom("momentum_6_vol", lookback=6, vol_regime_filter=True),
        _mom("momentum_12_vol", lookback=12, vol_regime_filter=True),
        _mr("mean_reversion_20_1_5_vol", lookback=20, entry_z=1.5, vol_regime_filter=True),
        _mr("mean_reversion_20_2_0_vol", lookback=20, entry_z=2.0, vol_regime_filter=True),
    )


def feature_candidates(
    *,
    liquidation: tuple[tuple[datetime, float], ...] | None = None,
    liquidation_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    funding: tuple[tuple[datetime, float], ...] | None = None,
    funding_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    open_interest: tuple[tuple[datetime, float], ...] | None = None,
    open_interest_by_symbol: dict[str, tuple[tuple[datetime, float], ...]] | None = None,
    cross_venue: tuple[tuple[datetime, float], ...] | None = None,
) -> tuple[SearchCandidate, ...]:
    """Optional families. Omitted series are not instantiated (not zero-filled)."""
    out: list[SearchCandidate] = []
    have_liq = liquidation is not None or bool(liquidation_by_symbol)
    have_funding = funding is not None or bool(funding_by_symbol)
    have_oi = open_interest is not None or bool(open_interest_by_symbol)
    if have_liq:
        out.append(
            _feature_z_candidate(
                candidate_id="liquidation_z_fade",
                family="liquidation_z",
                feature_name="liquidation_z",
                label="fade liquidation z-score |z|>=1.5",
                values=liquidation,
                values_by_symbol=liquidation_by_symbol,
                fade=True,
            )
        )
        out.append(
            _feature_z_candidate(
                candidate_id="liquidation_z_follow",
                family="liquidation_z",
                feature_name="liquidation_z",
                label="follow liquidation z-score |z|>=1.5",
                values=liquidation,
                values_by_symbol=liquidation_by_symbol,
                fade=False,
            )
        )
        for inner in (
            _mom("momentum_12", lookback=12),
            _ma("ma_cross_10_30", short_window=10, long_window=30),
            _mr("mean_reversion_20_1_5", lookback=20, entry_z=1.5),
        ):
            out.append(
                _liq_agree_candidate(
                    inner,
                    liquidation=liquidation,
                    liquidation_by_symbol=liquidation_by_symbol,
                )
            )
    if have_funding:
        out.append(
            _feature_z_candidate(
                candidate_id="funding_z_fade",
                family="funding_z",
                feature_name="funding_z",
                label="fade funding-rate z |z|>=1.5",
                values=funding,
                values_by_symbol=funding_by_symbol,
                fade=True,
            )
        )
        out.append(
            _feature_z_candidate(
                candidate_id="funding_z_follow",
                family="funding_z",
                feature_name="funding_z",
                label="follow funding-rate z |z|>=1.5",
                values=funding,
                values_by_symbol=funding_by_symbol,
                fade=False,
            )
        )
    if have_oi:
        out.append(
            _feature_z_candidate(
                candidate_id="oi_z_fade",
                family="open_interest_z",
                feature_name="open_interest_z",
                label="fade open-interest z |z|>=1.5",
                values=open_interest,
                values_by_symbol=open_interest_by_symbol,
                fade=True,
            )
        )
        out.append(
            _feature_z_candidate(
                candidate_id="oi_z_follow",
                family="open_interest_z",
                feature_name="open_interest_z",
                label="follow open-interest z |z|>=1.5",
                values=open_interest,
                values_by_symbol=open_interest_by_symbol,
                fade=False,
            )
        )
    if cross_venue is not None:
        out.append(
            _feature_z_candidate(
                candidate_id="cross_venue_fade",
                family="cross_venue",
                feature_name="cross_venue_divergence_z",
                label="fade cross-venue divergence z |z|>=1.5",
                values=cross_venue,
                values_by_symbol=None,
                fade=True,
            )
        )
    return tuple(out)


FEATURE_CATALOG: tuple[tuple[CandidateFamily, str, str], ...] = (
    ("liquidation_z", "liquidation_z_fade", "fade liquidation z-score |z|>=1.5"),
    ("liquidation_z", "liquidation_z_follow", "follow liquidation z-score |z|>=1.5"),
    ("funding_z", "funding_z_fade", "fade funding-rate z |z|>=1.5"),
    ("funding_z", "funding_z_follow", "follow funding-rate z |z|>=1.5"),
    ("open_interest_z", "oi_z_fade", "fade open-interest z |z|>=1.5"),
    ("open_interest_z", "oi_z_follow", "follow open-interest z |z|>=1.5"),
    ("cross_venue", "cross_venue_fade", "fade cross-venue divergence z |z|>=1.5"),
)
