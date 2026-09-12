"""Pre-registered daily robustness catalogs (paper/research only).

``default_daily_robustness_candidates`` is the frozen #95 list (K=8).
``default_balanced_holdout_candidates`` is the pre-registered balanced-
holdout expansion (slower EMAs, a tiny dual-mom / dip grid, asset-local
and BTC-overlay MA risk-off, two GARCH size overlays).
``default_expanded_harder_gates_candidates`` is the post-#97 harder-gates
grid (more ADX, faster/slower EMAs, SMA200 variants, dual-mom, dip+vol).
Each grid is frozen before any Kraken window is scored. Do not grow a
list to chase a winner.

GARCH never chooses a side. ``PAPER_GARCH_SIZE`` stays false unless a
GARCH-sized candidate clears the bar in a committed report
(research-only pin; never live).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from traderstack.candles import Candle
from traderstack.indicators import momentum, moving_average, realized_volatility, zscore
from traderstack.models import Side
from traderstack.research.miles_candidates import EmaCrossoverStrategy, SearchCandidate
from traderstack.strategies import Regime, StrategySignal


@dataclass(frozen=True)
class DualMomentumStrategy:
    """Fast and slow lookback returns must agree; otherwise stay flat."""

    strategy_id: str
    fast_lookback: int = 21
    slow_lookback: int = 126
    minimum_momentum: float = 0.0

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        required = self.slow_lookback + 1
        if len(candles) < required:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol if candles else "",
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="insufficient candles for dual momentum",
            )
        fast = momentum(candles, self.fast_lookback)
        slow = momentum(candles, self.slow_lookback)
        side: Side | None = None
        if fast >= self.minimum_momentum and slow >= self.minimum_momentum:
            side = Side.BUY
        elif fast <= -self.minimum_momentum and slow <= -self.minimum_momentum:
            side = Side.SELL
        score = 0.0
        if side is Side.BUY:
            score = 1.0
        elif side is Side.SELL:
            score = -1.0
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score,
            confidence=1.0 if side is not None else 0.0,
            regime=regime,
            rationale=(
                f"dual-mom fast={self.fast_lookback}={fast:.4f} "
                f"slow={self.slow_lookback}={slow:.4f}"
            ),
        )


@dataclass(frozen=True)
class BuyTheDipVolFilterStrategy:
    """Long-only oversold dip; skip when short-horizon vol is elevated."""

    strategy_id: str
    lookback: int = 20
    entry_z: float = 1.5
    vol_lookback: int = 20
    baseline_vol_lookback: int = 60
    vol_multiple: float = 1.5

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        required = max(self.lookback, self.baseline_vol_lookback + 1, self.vol_lookback + 1)
        if len(candles) < required:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol if candles else "",
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="insufficient candles for buy-the-dip",
            )
        closes = [candle.close for candle in candles[-self.lookback :]]
        current_z = zscore(closes[-1], closes)
        short_vol = realized_volatility(candles, self.vol_lookback)
        baseline_vol = realized_volatility(candles, self.baseline_vol_lookback)
        if short_vol > self.vol_multiple * baseline_vol:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale=(
                    f"vol filter: short={short_vol:.4f} > "
                    f"{self.vol_multiple:g}× baseline={baseline_vol:.4f}"
                ),
            )
        side: Side | None = None
        if current_z <= -self.entry_z:
            side = Side.BUY
        confidence = min(abs(current_z) / max(self.entry_z * 2, 1e-9), 1.0)
        score = max(-1.0, min(1.0, -current_z / max(self.entry_z * 2, 1e-9)))
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=score if side is not None else 0.0,
            confidence=confidence if side is not None else 0.0,
            regime=regime,
            rationale=f"buy-the-dip z={current_z:.3f} vol={short_vol:.4f}",
        )


def _flat_signal(
    strategy_id: str,
    candles: tuple[Candle, ...],
    regime: Regime,
    rationale: str,
) -> StrategySignal:
    return StrategySignal(
        strategy_id=strategy_id,
        symbol=candles[-1].symbol if candles else "",
        side=None,
        score=0.0,
        confidence=0.0,
        regime=regime,
        rationale=rationale,
    )


@dataclass(frozen=True)
class MaRiskOffStrategy:
    """Inner signal, flattened when this asset's close is below its SMA."""

    strategy_id: str
    inner: EmaCrossoverStrategy
    ma_span: int = 200

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        signal = self.inner.evaluate(candles, regime)
        if signal.side is None:
            return signal
        if len(candles) < self.ma_span:
            return _flat_signal(
                self.strategy_id,
                candles,
                regime,
                f"insufficient candles for SMA{self.ma_span} risk-off",
            )
        ma = moving_average(candles, self.ma_span)
        if candles[-1].close < ma:
            return _flat_signal(
                self.strategy_id,
                candles,
                regime,
                f"risk-off: close < SMA{self.ma_span}",
            )
        return signal


@dataclass(frozen=True)
class ReferenceMaRiskOffStrategy:
    """Inner signal, flattened when a reference series (BTC) is below its SMA.

    Reference bars are point-in-time: only closes with ``opened_at`` <= the
    evaluated bar are used. Missing or short history fails closed (flat).
    """

    strategy_id: str
    inner: EmaCrossoverStrategy
    ma_span: int
    reference_symbol: str
    reference_opened_at: tuple[datetime, ...]
    reference_close: tuple[float, ...]

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        signal = self.inner.evaluate(candles, regime)
        if signal.side is None:
            return signal
        if not candles:
            return _flat_signal(self.strategy_id, candles, regime, "no candles")
        asof = candles[-1].opened_at
        closes: list[float] = []
        for opened_at, close in zip(self.reference_opened_at, self.reference_close, strict=True):
            if opened_at > asof:
                break
            closes.append(close)
        if len(closes) < self.ma_span:
            return _flat_signal(
                self.strategy_id,
                candles,
                regime,
                (f"insufficient {self.reference_symbol} history for SMA{self.ma_span} risk-off"),
            )
        ma = sum(closes[-self.ma_span :]) / self.ma_span
        if closes[-1] < ma:
            return _flat_signal(
                self.strategy_id,
                candles,
                regime,
                f"risk-off: {self.reference_symbol} close < SMA{self.ma_span}",
            )
        return signal


def _ema(
    candidate_id: str,
    *,
    fast: int,
    slow: int,
    adx_threshold: float | None = None,
    garch_sizing: bool = False,
) -> SearchCandidate:
    parts = [f"EMA {fast}/{slow}"]
    if adx_threshold is not None:
        parts.append(f"ADX>{adx_threshold:g}")
    if garch_sizing:
        parts.append("GARCH size [0.25, 2.0]")
    return SearchCandidate(
        candidate_id=candidate_id,
        family="ema_cross_garch" if garch_sizing else "ema_cross",
        label=" × ".join(parts),
        params={
            "fast_span": fast,
            "slow_span": slow,
            "adx_threshold": adx_threshold,
            "garch_sizing": garch_sizing,
            "strategy_id": candidate_id,
        },
        strategy=EmaCrossoverStrategy(
            strategy_id=candidate_id,
            fast_span=fast,
            slow_span=slow,
            adx_threshold=adx_threshold,
        ),
        garch_sizing=garch_sizing,
    )


def _ema_ma_riskoff(
    candidate_id: str,
    *,
    fast: int,
    slow: int,
    ma_span: int,
    adx_threshold: float | None = None,
) -> SearchCandidate:
    inner = EmaCrossoverStrategy(
        strategy_id=candidate_id,
        fast_span=fast,
        slow_span=slow,
        adx_threshold=adx_threshold,
    )
    parts = [f"EMA {fast}/{slow}"]
    if adx_threshold is not None:
        parts.append(f"ADX>{adx_threshold:g}")
    parts.append(f"asset SMA{ma_span} risk-off (flat below MA)")
    return SearchCandidate(
        candidate_id=candidate_id,
        family="ema_cross_riskoff",
        label=" × ".join(parts),
        params={
            "fast_span": fast,
            "slow_span": slow,
            "ma_span": ma_span,
            "adx_threshold": adx_threshold,
            "garch_sizing": False,
            "strategy_id": candidate_id,
            "risk_off": "asset_sma",
        },
        strategy=MaRiskOffStrategy(strategy_id=candidate_id, inner=inner, ma_span=ma_span),
    )


def _ema_btc_ma_riskoff(
    candidate_id: str,
    *,
    fast: int,
    slow: int,
    ma_span: int,
    btc_overlay: tuple[Candle, ...],
) -> SearchCandidate:
    inner = EmaCrossoverStrategy(strategy_id=candidate_id, fast_span=fast, slow_span=slow)
    return SearchCandidate(
        candidate_id=candidate_id,
        family="ema_cross_riskoff",
        label=(
            f"EMA {fast}/{slow} × {btc_overlay[0].symbol} SMA{ma_span} "
            "risk-off (flat when BTC below MA)"
        ),
        params={
            "fast_span": fast,
            "slow_span": slow,
            "ma_span": ma_span,
            "garch_sizing": False,
            "strategy_id": candidate_id,
            "risk_off": "btc_sma",
            "reference_symbol": btc_overlay[0].symbol,
            "reference_bars": len(btc_overlay),
        },
        strategy=ReferenceMaRiskOffStrategy(
            strategy_id=candidate_id,
            inner=inner,
            ma_span=ma_span,
            reference_symbol=btc_overlay[0].symbol,
            reference_opened_at=tuple(candle.opened_at for candle in btc_overlay),
            reference_close=tuple(candle.close for candle in btc_overlay),
        ),
    )


def _dual_mom(
    candidate_id: str,
    *,
    fast_lookback: int,
    slow_lookback: int,
    minimum_momentum: float = 0.0,
) -> SearchCandidate:
    strategy = DualMomentumStrategy(
        strategy_id=candidate_id,
        fast_lookback=fast_lookback,
        slow_lookback=slow_lookback,
        minimum_momentum=minimum_momentum,
    )
    return SearchCandidate(
        candidate_id=candidate_id,
        family="dual_momentum",
        label=f"dual-momentum {fast_lookback}/{slow_lookback} (agree or cash)",
        params={
            "fast_lookback": fast_lookback,
            "slow_lookback": slow_lookback,
            "minimum_momentum": minimum_momentum,
            "strategy_id": candidate_id,
        },
        strategy=strategy,
    )


def _dip(
    candidate_id: str,
    *,
    lookback: int,
    entry_z: float,
    vol_lookback: int,
    baseline_vol_lookback: int,
    vol_multiple: float,
) -> SearchCandidate:
    strategy = BuyTheDipVolFilterStrategy(
        strategy_id=candidate_id,
        lookback=lookback,
        entry_z=entry_z,
        vol_lookback=vol_lookback,
        baseline_vol_lookback=baseline_vol_lookback,
        vol_multiple=vol_multiple,
    )
    return SearchCandidate(
        candidate_id=candidate_id,
        family="buy_the_dip",
        label=(
            f"buy-the-dip {lookback}-bar |z|>={entry_z:g} "
            f"(skip if {vol_lookback}d vol > {vol_multiple:g}× {baseline_vol_lookback}d vol)"
        ),
        params={
            "lookback": lookback,
            "entry_z": entry_z,
            "vol_lookback": vol_lookback,
            "baseline_vol_lookback": baseline_vol_lookback,
            "vol_multiple": vol_multiple,
            "strategy_id": candidate_id,
        },
        strategy=strategy,
    )


def default_daily_robustness_candidates() -> tuple[SearchCandidate, ...]:
    """Frozen #95 daily catalog. Do not grow this list to chase a winner."""
    return (
        _ema("ema_9_21", fast=9, slow=21),
        _ema("ema_12_26", fast=12, slow=26),
        _ema("ema_9_21_adx20", fast=9, slow=21, adx_threshold=20.0),
        _ema("ema_12_26_adx20", fast=12, slow=26, adx_threshold=20.0),
        _ema("ema_9_21_adx25", fast=9, slow=21, adx_threshold=25.0),
        _ema("ema_12_26_adx25", fast=12, slow=26, adx_threshold=25.0),
        _dual_mom("dual_mom_21_126", fast_lookback=21, slow_lookback=126),
        _dip(
            "dip_mr_20_1_5_vol",
            lookback=20,
            entry_z=1.5,
            vol_lookback=20,
            baseline_vol_lookback=60,
            vol_multiple=1.5,
        ),
    )


BALANCED_HOLDOUT_GRID_NOTE = (
    "Pre-registered balanced-holdout grid (frozen before the Kraken window "
    "is scored): #95 EMA 9/21 and 12/26 ± ADX 20/25; slower EMA 20/50 and "
    "50/200 (± ADX 20 on 20/50); dual-mom lookbacks 12/60, 21/63, 21/126, "
    "63/126; buy-the-dip z=1.5 and z=2.0 with the same vol filter; asset-"
    "local SMA200 risk-off on ema_9_21 and ema_20_50; BTC SMA200 overlay "
    "on ema_9_21 when a Kraken BTC/USD daily series is bound; GARCH size "
    "overlays on ema_9_21 and ema_20_50 only. SOL is reported, not a "
    "promotion gate. Yahoo never enters the promotion average. "
    "PAPER_GARCH_SIZE stays false unless a GARCH-sized name clears."
)


def default_balanced_holdout_candidates(
    *,
    btc_overlay: tuple[Candle, ...] | None = None,
) -> tuple[SearchCandidate, ...]:
    """Frozen balanced-holdout catalog. Do not grow this list after seeing PnL."""
    catalog: list[SearchCandidate] = [
        _ema("ema_9_21", fast=9, slow=21),
        _ema("ema_12_26", fast=12, slow=26),
        _ema("ema_9_21_adx20", fast=9, slow=21, adx_threshold=20.0),
        _ema("ema_12_26_adx20", fast=12, slow=26, adx_threshold=20.0),
        _ema("ema_9_21_adx25", fast=9, slow=21, adx_threshold=25.0),
        _ema("ema_12_26_adx25", fast=12, slow=26, adx_threshold=25.0),
        _ema("ema_20_50", fast=20, slow=50),
        _ema("ema_50_200", fast=50, slow=200),
        _ema("ema_20_50_adx20", fast=20, slow=50, adx_threshold=20.0),
        _ema("ema_9_21_garch", fast=9, slow=21, garch_sizing=True),
        _ema("ema_20_50_garch", fast=20, slow=50, garch_sizing=True),
        _dual_mom("dual_mom_12_60", fast_lookback=12, slow_lookback=60),
        _dual_mom("dual_mom_21_63", fast_lookback=21, slow_lookback=63),
        _dual_mom("dual_mom_21_126", fast_lookback=21, slow_lookback=126),
        _dual_mom("dual_mom_63_126", fast_lookback=63, slow_lookback=126),
        _dip(
            "dip_mr_20_1_5_vol",
            lookback=20,
            entry_z=1.5,
            vol_lookback=20,
            baseline_vol_lookback=60,
            vol_multiple=1.5,
        ),
        _dip(
            "dip_mr_20_2_0_vol",
            lookback=20,
            entry_z=2.0,
            vol_lookback=20,
            baseline_vol_lookback=60,
            vol_multiple=1.5,
        ),
        _ema_ma_riskoff("ema_9_21_ma200_riskoff", fast=9, slow=21, ma_span=200),
        _ema_ma_riskoff("ema_20_50_ma200_riskoff", fast=20, slow=50, ma_span=200),
    ]
    if btc_overlay:
        catalog.append(
            _ema_btc_ma_riskoff(
                "ema_9_21_btc_ma200_riskoff",
                fast=9,
                slow=21,
                ma_span=200,
                btc_overlay=btc_overlay,
            )
        )
    return tuple(catalog)


# --- expanded harder-gates catalog (frozen before any Kraken pull) ---
# Do not grow, shrink, or reorder this list after seeing a live print.
# Overlay BTC-SMA names are appended only when a Kraken BTC/USD daily
# series is bound (same rule as the #96 balanced catalog).
EXPANDED_HARDER_GATES_CORE_IDS: tuple[str, ...] = (
    "ema_9_21",
    "ema_12_26",
    "ema_9_21_adx20",
    "ema_12_26_adx20",
    "ema_9_21_adx25",
    "ema_12_26_adx25",
    "ema_20_50",
    "ema_50_200",
    "ema_20_50_adx20",
    "ema_9_21_garch",
    "ema_20_50_garch",
    "dual_mom_12_60",
    "dual_mom_21_63",
    "dual_mom_21_126",
    "dual_mom_63_126",
    "dip_mr_20_1_5_vol",
    "dip_mr_20_2_0_vol",
    "ema_9_21_ma200_riskoff",
    "ema_20_50_ma200_riskoff",
    "ema_9_21_adx15",
    "ema_12_26_adx15",
    "ema_9_21_adx18",
    "ema_12_26_adx18",
    "ema_9_21_adx22",
    "ema_12_26_adx22",
    "ema_9_21_adx30",
    "ema_12_26_adx30",
    "ema_5_13",
    "ema_8_21",
    "ema_13_34",
    "ema_21_55",
    "ema_8_21_adx20",
    "ema_13_34_adx20",
    "ema_12_26_ma200_riskoff",
    "ema_8_21_ma200_riskoff",
    "ema_13_34_ma200_riskoff",
    "ema_12_26_adx20_ma200_riskoff",
    "dual_mom_10_50",
    "dual_mom_15_90",
    "dual_mom_21_90",
    "dual_mom_42_126",
    "dip_mr_10_1_5_vol",
    "dip_mr_15_1_5_vol",
    "dip_mr_20_1_0_vol",
    "dip_mr_20_1_5_vol2",
)
EXPANDED_HARDER_GATES_OVERLAY_IDS: tuple[str, ...] = (
    "ema_9_21_btc_ma200_riskoff",
    "ema_12_26_btc_ma200_riskoff",
    "ema_20_50_btc_ma200_riskoff",
)
EXPANDED_HARDER_GATES_GRID_NOTE = (
    "Pre-registered expanded harder-gates catalog (frozen before the "
    "Kraken window is scored). Includes the #96/#97 balanced grid plus "
    "ADX 15/18/22/30 on EMA 9/21 and 12/26; faster EMA 5/13 and 8/21; "
    "slower EMA 13/34 and 21/55; ADX20 on 8/21 and 13/34; asset-local "
    "SMA200 risk-off on 12/26, 8/21, 13/34, and 12/26+ADX20; dual-mom "
    "lookbacks 10/50, 15/90, 21/90, 42/126; dip+vol lookbacks 10/15 and "
    "z=1.0 plus a 2× vol-filter variant. BTC SMA200 overlays on "
    "ema_9_21 / ema_12_26 / ema_20_50 when a Kraken BTC/USD daily series "
    "is bound. SOL is reported, not a gate. Yahoo never enters ranking "
    "or A/B/C averages. Do not grow this list after seeing PnL. "
    "PAPER_GARCH_SIZE and PAPER_PROMOTE_EMA_9_21 stay false unless a "
    "committed report names a paper-only pin and an operator flips it."
)


def default_expanded_harder_gates_candidates(
    *,
    btc_overlay: tuple[Candle, ...] | None = None,
) -> tuple[SearchCandidate, ...]:
    """Frozen expanded harder-gates catalog. Do not grow after seeing PnL."""
    catalog: list[SearchCandidate] = [
        *default_balanced_holdout_candidates(),
        _ema("ema_9_21_adx15", fast=9, slow=21, adx_threshold=15.0),
        _ema("ema_12_26_adx15", fast=12, slow=26, adx_threshold=15.0),
        _ema("ema_9_21_adx18", fast=9, slow=21, adx_threshold=18.0),
        _ema("ema_12_26_adx18", fast=12, slow=26, adx_threshold=18.0),
        _ema("ema_9_21_adx22", fast=9, slow=21, adx_threshold=22.0),
        _ema("ema_12_26_adx22", fast=12, slow=26, adx_threshold=22.0),
        _ema("ema_9_21_adx30", fast=9, slow=21, adx_threshold=30.0),
        _ema("ema_12_26_adx30", fast=12, slow=26, adx_threshold=30.0),
        _ema("ema_5_13", fast=5, slow=13),
        _ema("ema_8_21", fast=8, slow=21),
        _ema("ema_13_34", fast=13, slow=34),
        _ema("ema_21_55", fast=21, slow=55),
        _ema("ema_8_21_adx20", fast=8, slow=21, adx_threshold=20.0),
        _ema("ema_13_34_adx20", fast=13, slow=34, adx_threshold=20.0),
        _ema_ma_riskoff("ema_12_26_ma200_riskoff", fast=12, slow=26, ma_span=200),
        _ema_ma_riskoff("ema_8_21_ma200_riskoff", fast=8, slow=21, ma_span=200),
        _ema_ma_riskoff("ema_13_34_ma200_riskoff", fast=13, slow=34, ma_span=200),
        _ema_ma_riskoff(
            "ema_12_26_adx20_ma200_riskoff",
            fast=12,
            slow=26,
            ma_span=200,
            adx_threshold=20.0,
        ),
        _dual_mom("dual_mom_10_50", fast_lookback=10, slow_lookback=50),
        _dual_mom("dual_mom_15_90", fast_lookback=15, slow_lookback=90),
        _dual_mom("dual_mom_21_90", fast_lookback=21, slow_lookback=90),
        _dual_mom("dual_mom_42_126", fast_lookback=42, slow_lookback=126),
        _dip(
            "dip_mr_10_1_5_vol",
            lookback=10,
            entry_z=1.5,
            vol_lookback=20,
            baseline_vol_lookback=60,
            vol_multiple=1.5,
        ),
        _dip(
            "dip_mr_15_1_5_vol",
            lookback=15,
            entry_z=1.5,
            vol_lookback=20,
            baseline_vol_lookback=60,
            vol_multiple=1.5,
        ),
        _dip(
            "dip_mr_20_1_0_vol",
            lookback=20,
            entry_z=1.0,
            vol_lookback=20,
            baseline_vol_lookback=60,
            vol_multiple=1.5,
        ),
        _dip(
            "dip_mr_20_1_5_vol2",
            lookback=20,
            entry_z=1.5,
            vol_lookback=20,
            baseline_vol_lookback=60,
            vol_multiple=2.0,
        ),
    ]
    if btc_overlay:
        catalog.extend(
            [
                _ema_btc_ma_riskoff(
                    "ema_9_21_btc_ma200_riskoff",
                    fast=9,
                    slow=21,
                    ma_span=200,
                    btc_overlay=btc_overlay,
                ),
                _ema_btc_ma_riskoff(
                    "ema_12_26_btc_ma200_riskoff",
                    fast=12,
                    slow=26,
                    ma_span=200,
                    btc_overlay=btc_overlay,
                ),
                _ema_btc_ma_riskoff(
                    "ema_20_50_btc_ma200_riskoff",
                    fast=20,
                    slow=50,
                    ma_span=200,
                    btc_overlay=btc_overlay,
                ),
            ]
        )
    ids = tuple(item.candidate_id for item in catalog)
    expected = EXPANDED_HARDER_GATES_CORE_IDS + (
        EXPANDED_HARDER_GATES_OVERLAY_IDS if btc_overlay else ()
    )
    if ids != expected:
        raise RuntimeError(
            "expanded harder-gates catalog drifted from the frozen id list"
        )
    return tuple(catalog)
