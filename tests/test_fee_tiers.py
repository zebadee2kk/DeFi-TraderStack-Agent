"""Fee realism (#138): frozen Kraken Pro tier catalog and the research cost resolver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from pydantic import ValidationError

from traderstack.backtest import simulate_positions
from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.fee_tiers import (
    ALL_FEE_TIERS,
    EXPLICIT_FEE_TIER_ID,
    FEE_TIER_IDS,
    KRAKEN_PRO_SPOT_TIERS,
    MODELLED_FEE_TIER_ID,
    PILOT_FEE_TIER_ID,
    FeeTierId,
    FeeTierStamp,
    effective_taker_bps,
    resolve_fee_tier,
    resolve_research_costs,
)
from traderstack.research.daily_candidates import default_balanced_holdout_candidates
from traderstack.research.daily_robustness import (
    render_daily_robustness_markdown,
    run_daily_robustness,
)
from traderstack.strategies import Regime


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def make_candles(prices: list[float], *, symbol: str = "BTC/USD") -> tuple[Candle, ...]:
    opened = datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=opened + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


# --- catalog -------------------------------------------------------------------


def test_catalog_is_the_brief_transcription() -> None:
    by_id = {tier.tier_id: tier for tier in KRAKEN_PRO_SPOT_TIERS}
    assert (by_id["kraken_pro_spot_t1"].maker_bps, by_id["kraken_pro_spot_t1"].taker_bps) == (
        40,
        80,
    )
    assert (by_id["kraken_pro_spot_t2"].maker_bps, by_id["kraken_pro_spot_t2"].taker_bps) == (
        30,
        60,
    )
    assert (by_id["kraken_pro_spot_t3"].maker_bps, by_id["kraken_pro_spot_t3"].taker_bps) == (
        22,
        38,
    )
    assert (by_id["kraken_pro_spot_t8"].maker_bps, by_id["kraken_pro_spot_t8"].taker_bps) == (8, 20)
    assert (by_id["kraken_pro_spot_t12"].maker_bps, by_id["kraken_pro_spot_t12"].taker_bps) == (
        0,
        10,
    )
    for tier in KRAKEN_PRO_SPOT_TIERS:
        assert tier.venue == "kraken"
        assert tier.source == "kraken.com/features/fee-schedule"
        assert tier.read_on == "2026-09-13"


def test_catalog_is_frozen_and_monotone() -> None:
    volumes = [tier.min_30d_volume_usd for tier in KRAKEN_PRO_SPOT_TIERS]
    assert volumes == sorted(volumes)
    makers = [tier.maker_bps for tier in KRAKEN_PRO_SPOT_TIERS]
    takers = [tier.taker_bps for tier in KRAKEN_PRO_SPOT_TIERS]
    assert makers == sorted(makers, reverse=True)
    assert takers == sorted(takers, reverse=True)
    for tier in ALL_FEE_TIERS:
        assert 0 <= tier.maker_bps <= tier.taker_bps  # no rebate, maker never above taker
    with pytest.raises(AttributeError):
        KRAKEN_PRO_SPOT_TIERS[0].taker_bps = 0.0  # type: ignore[misc]


def test_pilot_tier_is_tier_one() -> None:
    tier = resolve_fee_tier(PILOT_FEE_TIER_ID)
    assert (tier.maker_bps, tier.taker_bps) == (40.0, 80.0)
    assert tier.min_30d_volume_usd == 0.0


def test_unknown_tier_names_the_valid_ids() -> None:
    with pytest.raises(ValueError, match="kraken_pro_spot_t1"):
        resolve_fee_tier("kraken_pro_spot_t99")
    with pytest.raises(ValueError, match="valid ids"):
        resolve_fee_tier("maker")


def test_settings_literal_matches_the_catalog_ids() -> None:
    annotation = Settings.model_fields["paper_fee_tier"].annotation
    assert get_args(annotation) == FEE_TIER_IDS
    assert get_args(FeeTierId) == FEE_TIER_IDS
    assert Settings.model_fields["paper_fee_tier"].default == PILOT_FEE_TIER_ID
    assert MODELLED_FEE_TIER_ID in FEE_TIER_IDS


def test_effective_paper_fee_is_tier_taker_or_paper_fee_bps_when_modelled() -> None:
    assert settings().effective_paper_fee_bps == 80.0
    assert settings(paper_fee_tier="kraken_pro_spot_t3").effective_paper_fee_bps == 38.0
    assert settings(paper_fee_tier="modelled", paper_fee_bps=7.5).effective_paper_fee_bps == 7.5
    assert (
        settings(paper_fee_tier="kraken_pro_spot_t1", paper_fee_bps=0).effective_paper_fee_bps == 80
    )
    assert effective_taker_bps("modelled", paper_fee_bps=3.0) == 3.0


# --- resolver ------------------------------------------------------------------


def test_default_costs_are_pilot_tier_taker_plus_pretrade_slippage() -> None:
    costs = resolve_research_costs(fee_bps=None, fee_tier=None, settings=settings())
    assert costs.fee_bps == 80.0
    assert costs.slippage_bps == 5.0
    assert costs.stamp.tier_id == PILOT_FEE_TIER_ID
    assert costs.stamp.role == "taker"
    assert costs.stamp.fee_bps_used == 80.0
    assert costs.stamp.maker_bps == 40.0


def test_precedence_is_explicit_then_flag_then_settings() -> None:
    cfg = settings(paper_fee_tier="kraken_pro_spot_t2")
    by_settings = resolve_research_costs(fee_bps=None, fee_tier=None, settings=cfg)
    assert by_settings.fee_bps == 60.0
    by_flag = resolve_research_costs(fee_bps=None, fee_tier="kraken_pro_spot_t3", settings=cfg)
    assert by_flag.fee_bps == 38.0
    assert by_flag.stamp.tier_id == "kraken_pro_spot_t3"
    explicit = resolve_research_costs(fee_bps=10.0, fee_tier="kraken_pro_spot_t3", settings=cfg)
    assert explicit.fee_bps == 10.0
    assert explicit.stamp.tier_id == EXPLICIT_FEE_TIER_ID
    assert explicit.stamp.label == "--fee-bps 10"
    assert explicit.stamp.fee_bps_used == 10.0


def test_tier_fee_is_the_conservative_of_pretrade_and_taker() -> None:
    cfg = settings(pretrade_fee_bps=200.0)
    for tier_id in FEE_TIER_IDS:
        costs = resolve_research_costs(fee_bps=None, fee_tier=tier_id, settings=cfg)
        assert costs.fee_bps == 200.0
        assert costs.stamp.fee_bps_used == 200.0


def test_modelled_tier_reproduces_pre_138_costs() -> None:
    costs = resolve_research_costs(fee_bps=None, fee_tier="modelled", settings=settings())
    assert costs.fee_bps == 10.0
    assert costs.stamp.tier_id == "modelled"
    assert "optimistic" in costs.stamp.note


def test_explicit_slippage_overrides_pretrade_slippage() -> None:
    costs = resolve_research_costs(
        fee_bps=None, fee_tier=None, settings=settings(), slippage_bps=12.0
    )
    assert costs.slippage_bps == 12.0


def test_negative_explicit_fee_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_research_costs(fee_bps=-1.0, fee_tier=None, settings=settings())


def test_stamp_render_line_names_tier_maker_taker_and_not_assumed() -> None:
    line = resolve_research_costs(
        fee_bps=None, fee_tier=None, settings=settings()
    ).stamp.render_line()
    assert line.startswith(
        "Fee tier: Tier 1 ($0+ 30d) maker 40 / taker 80 bps (kraken_pro_spot_t1)"
    )
    assert "scored at taker 80 bps" in line
    assert "not assumed" in line


def test_stamp_role_can_only_be_taker() -> None:
    with pytest.raises(ValidationError):
        FeeTierStamp(
            tier_id="kraken_pro_spot_t1",
            venue="kraken",
            label="Tier 1",
            maker_bps=40,
            taker_bps=80,
            role="maker",  # type: ignore[arg-type]
            fee_bps_used=40,
            source="s",
            read_on="2026-09-13",
        )


# --- acceptance criterion: passes at 10 bps, fails at Tier 1 taker -------------


def _sawtooth(count: int) -> tuple[Candle, ...]:
    """Every even bar closes at 100, every odd bar at 101: a long entered on an
    even bar earns ~100 bps gross on the next bar."""

    return make_candles([100.0 if index % 2 == 0 else 101.0 for index in range(count)])


def _long_on_even_bars(window: tuple[Candle, ...]) -> tuple[float, Regime, list[str]]:
    index = len(window) - 1
    return (1.0 if index % 2 == 0 else 0.0), Regime.TRENDING_UP, ["scripted"]


def test_strategy_passes_at_ten_bps_and_fails_at_tier_one_taker() -> None:
    candles = _sawtooth(120)
    at_modelled = simulate_positions(
        candles, _long_on_even_bars, warmup=10, fee_bps=10.0, slippage_bps=5.0
    )
    at_tier_one = simulate_positions(
        candles, _long_on_even_bars, warmup=10, fee_bps=80.0, slippage_bps=5.0
    )
    assert at_modelled.trades >= 20
    assert at_tier_one.trades == at_modelled.trades
    assert at_modelled.total_return > 0
    assert at_tier_one.total_return < 0
    assert at_tier_one.total_fees > at_modelled.total_fees


def test_daily_robustness_report_says_which_fee_tier_scored_it() -> None:
    histories = {
        "BTC/USD@1d": _sawtooth(300),
        "ETH/USD@1d": make_candles(
            [100.0 if index % 2 == 0 else 101.0 for index in range(300)], symbol="ETH/USD"
        ),
    }
    catalog = tuple(
        item for item in default_balanced_holdout_candidates() if item.candidate_id == "ema_9_21"
    )
    costs = resolve_research_costs(fee_bps=None, fee_tier=None, settings=settings())
    report = run_daily_robustness(
        histories,
        fee_bps=costs.fee_bps,
        slippage_bps=costs.slippage_bps,
        train_size=80,
        test_size=40,
        step_size=40,
        min_trades=1,
        candidates=catalog,
        fee_tier=costs.stamp,
    )
    assert report.fee_bps == 80.0
    assert report.fee_tier is not None
    assert report.fee_tier.tier_id == PILOT_FEE_TIER_ID
    markdown = render_daily_robustness_markdown(report)
    assert "Costs: fee=80 bps + slippage=5 bps" in markdown
    assert "Fee tier: Tier 1 ($0+ 30d) maker 40 / taker 80 bps" in markdown
    assert "not assumed" in markdown
    # JSON round-trip keeps the stamp; a pre-#138 report without it still loads.
    payload = report.model_dump(mode="json")
    assert payload["fee_tier"]["taker_bps"] == 80.0
    payload.pop("fee_tier")
    assert type(report).model_validate(payload).fee_tier is None
