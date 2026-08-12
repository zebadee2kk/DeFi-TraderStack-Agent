from dataclasses import dataclass

from traderstack.candles import Candle
from traderstack.features import MarketFeatures
from traderstack.indicators import momentum, realized_volatility, volume_ratio


@dataclass(frozen=True)
class CandleMarketFeatureBuilder:
    trend_4h_lookback: int = 4
    trend_1d_lookback: int = 24
    volatility_lookback: int = 24
    volume_lookback: int = 24

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
        return MarketFeatures(
            trend_4h=trend_4h,
            trend_1d=trend_1d,
            volatility_z=volatility,
            relative_volume=relative_volume,
            spread_bps=spread_bps,
        )
