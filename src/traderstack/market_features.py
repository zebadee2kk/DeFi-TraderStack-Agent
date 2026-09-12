from dataclasses import dataclass

from traderstack.candles import Candle, periods_per_year
from traderstack.features import MarketFeatures
from traderstack.garch import (
    DEFAULT_MIN_TRAIN,
    DEFAULT_TARGET_VOL_ANN,
    candle_returns,
    one_step_forecast,
)
from traderstack.indicators import momentum, realized_volatility, volume_ratio


@dataclass(frozen=True)
class CandleMarketFeatureBuilder:
    trend_4h_lookback: int = 4
    trend_1d_lookback: int = 24
    volatility_lookback: int = 24
    volume_lookback: int = 24
    # --- miles-inspired GARCH sizing (paper research) ---
    # Off by default. When on, a one-step GARCH forecast is attached so the
    # paper RiskEngine can reduce size. The builder is still a pure function
    # of the window it is given.
    garch_enabled: bool = False
    garch_min_train: int = DEFAULT_MIN_TRAIN
    garch_target_vol_ann: float = DEFAULT_TARGET_VOL_ANN

    def build(self, candles: tuple[Candle, ...], *, spread_bps: float) -> MarketFeatures:
        required = max(
            self.trend_4h_lookback + 1,
            self.trend_1d_lookback + 1,
            self.volatility_lookback + 1,
            self.volume_lookback,
        )
        if len(candles) < required:
            raise ValueError("insufficient candles for market features")
        trend_4h = max(-1.0, min(1.0, momentum(candles, self.trend_4h_lookback) * 10.0))
        trend_1d = max(-1.0, min(1.0, momentum(candles, self.trend_1d_lookback) * 5.0))
        volatility = realized_volatility(candles, self.volatility_lookback)
        relative_volume = volume_ratio(candles, self.volume_lookback)
        garch_forecast_vol = self._garch_forecast_vol(candles)
        return MarketFeatures(
            trend_4h=trend_4h,
            trend_1d=trend_1d,
            volatility_z=volatility,
            relative_volume=relative_volume,
            spread_bps=spread_bps,
            garch_forecast_vol=garch_forecast_vol,
        )

    def _garch_forecast_vol(self, candles: tuple[Candle, ...]) -> float | None:
        if not self.garch_enabled:
            return None
        try:
            forecast = one_step_forecast(
                candle_returns(candles),
                periods=periods_per_year(candles[0].interval),
                target_vol_ann=self.garch_target_vol_ann,
                min_train=self.garch_min_train,
            )
        except ValueError:
            return None
        if forecast is None:
            return None
        return forecast.vol_ann
