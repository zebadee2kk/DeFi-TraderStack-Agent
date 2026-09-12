from datetime import UTC, date, datetime

from traderstack.polymarket.edge import calculate_edge, model_probability, normal_cdf
from traderstack.polymarket.models import (
    ContractSide,
    ForecastPoint,
    ParsedTemperatureMarket,
    TemperatureContract,
)


def _threshold(threshold_f: float = 90.0) -> ParsedTemperatureMarket:
    return ParsedTemperatureMarket(
        market_id="m1",
        question="Will the highest temperature in Miami be 90°F or higher on September 12, 2026?",
        city_slug="miami",
        city_name="Miami",
        event_date=date(2026, 9, 12),
        contract=TemperatureContract.THRESHOLD_OR_HIGHER,
        threshold_f=threshold_f,
        yes_token_id="yes",
        no_token_id="no",
    )


def _forecast(high_f: float = 92.4, sigma_f: float = 2.5) -> ForecastPoint:
    return ForecastPoint(
        city_slug="miami",
        event_date=date(2026, 9, 12),
        high_f=high_f,
        source="open_meteo",
        issued_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
        sigma_f=sigma_f,
    )


def test_normal_cdf_known_values() -> None:
    assert normal_cdf(0.0) == 0.5
    assert abs(normal_cdf(1.0) - 0.841344746) < 1e-6


def test_threshold_model_probability_above_forecast() -> None:
    # mean 92.4, threshold 90, sigma 2.5 → P(T>=90) well above 0.5
    prob = model_probability(_threshold(), _forecast())
    assert 0.80 < prob < 0.90


def test_bucket_probability_near_mean() -> None:
    market = ParsedTemperatureMarket(
        market_id="m2",
        question="Highest temperature in Honolulu on September 12, 2026: 86-87°F",
        city_slug="honolulu",
        city_name="Honolulu",
        event_date=date(2026, 9, 12),
        contract=TemperatureContract.BUCKET,
        bucket_low_f=86.0,
        bucket_high_f=87.0,
        yes_token_id="yes",
        no_token_id="no",
    )
    forecast = ForecastPoint(
        city_slug="honolulu",
        event_date=date(2026, 9, 12),
        high_f=86.5,
        source="open_meteo",
        issued_at=datetime(2026, 9, 11, 12, tzinfo=UTC),
        sigma_f=2.5,
    )
    prob = model_probability(market, forecast)
    assert 0.25 < prob < 0.40


def test_calculate_edge_buys_yes_when_model_above_mid() -> None:
    edge = calculate_edge(_threshold(), _forecast(), 0.55, fee_haircut=0.02)
    assert edge.side is ContractSide.YES
    assert edge.net_edge >= 0.08
    assert edge.net_edge == edge.raw_edge - 0.02


def test_calculate_edge_buys_no_when_model_below_mid() -> None:
    edge = calculate_edge(_threshold(110.0), _forecast(100.0), 0.40, fee_haircut=0.02)
    assert edge.side is ContractSide.NO
    assert edge.raw_edge < 0
    assert edge.net_edge == abs(edge.raw_edge) - 0.02


def test_fee_haircut_can_push_below_min_edge() -> None:
    # model ≈ mid; haircut makes net negative
    edge = calculate_edge(_threshold(92.4), _forecast(92.4), 0.50, fee_haircut=0.02)
    assert edge.net_edge < 0.08
