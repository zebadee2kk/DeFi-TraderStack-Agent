"""Ensemble-trend v2 consensus catalog is a fresh frozen set; #137 stays untouched."""

from traderstack.research.ensemble_trend import (
    CATALOGS,
    CONTROL_ID,
    CORE_IDS,
    ENSEMBLE_CATALOG,
    ENSEMBLE_IDS,
    ENSEMBLE_LOOKBACKS,
    V2_CATALOG,
    V2_CORE_IDS,
    V2_IDS,
    V2_LONG_LOOKBACKS,
    V2_MID_LOOKBACKS,
    V2_STRICT_LOOKBACKS,
    V2_VOL_TARGET_ANNUAL,
    ensemble_trend_series,
    resolve_catalog,
)
from traderstack.research.ensemble_trend_cli import build_parser


def _prices(n: int = 400, start: float = 100.0) -> list[float]:
    # Mild uptrend with noise so some lookbacks open.
    out = []
    price = start
    for i in range(n):
        price *= 1.002 if i % 7 else 0.997
        out.append(price)
    return out


def test_v2_catalog_is_distinct_from_default() -> None:
    assert ENSEMBLE_LOOKBACKS == (5, 10, 20, 30, 60, 90, 150, 250, 360)
    assert V2_MID_LOOKBACKS == (30, 60, 90, 150)
    assert V2_LONG_LOOKBACKS == (60, 90, 150, 250)
    assert V2_STRICT_LOOKBACKS == (20, 30, 60, 90, 150)
    assert V2_VOL_TARGET_ANNUAL == 0.15
    assert len(ENSEMBLE_CATALOG) == 3
    assert len(V2_CATALOG) == 3
    assert len(CORE_IDS) == 4
    assert len(V2_CORE_IDS) == 4
    assert set(ENSEMBLE_IDS).isdisjoint(set(V2_IDS))
    assert all(cid.startswith("ens_trend_v2_") for cid in V2_IDS)
    assert CONTROL_ID in V2_CORE_IDS
    assert resolve_catalog("default") == ENSEMBLE_CATALOG
    assert resolve_catalog("v2") == V2_CATALOG
    assert set(CATALOGS) == {"default", "v2"}
    # default catalog keeps min_open=0
    assert all(item[3] == 0 for item in ENSEMBLE_CATALOG)
    assert V2_CATALOG[0][3] == 2 and V2_CATALOG[2][3] == 3


def test_resolve_catalog_rejects_unknown() -> None:
    try:
        resolve_catalog("retune_after_pnl")
    except ValueError as exc:
        assert "unknown catalog" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_min_open_zeros_weight_below_consensus() -> None:
    from datetime import UTC, datetime, timedelta

    from traderstack.candles import Candle

    prices = _prices(320)
    opened = datetime(2024, 1, 1, tzinfo=UTC)
    candles = tuple(
        Candle(
            symbol="BTC/USD",
            interval="1d",
            opened_at=opened + timedelta(days=i),
            open=prices[i - 1] if i else prices[i],
            high=prices[i] * 1.01,
            low=prices[i] * 0.99,
            close=prices[i],
            volume=5_000_000.0,
        )
        for i in range(len(prices))
    )
    lookbacks = V2_MID_LOOKBACKS
    free = ensemble_trend_series(candles, lookbacks=lookbacks, vol_target=0.15, min_open=0)
    gated = ensemble_trend_series(candles, lookbacks=lookbacks, vol_target=0.15, min_open=2)
    assert free and gated
    # Whenever open_count < 2, gated weight must be 0 while free may be positive.
    by_ts_free = {ts: (w, c) for ts, w, c in free}
    for ts, weight, count in gated:
        if count < 2:
            assert weight == 0.0
            free_w, _ = by_ts_free[ts]
            # free may still be fractional; gated is the consensus floor
            assert free_w >= 0.0


def test_cli_accepts_catalog_v2_and_candles_dir() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--catalog",
            "v2",
            "--candles-dir",
            "kraken",
            "var/research/candles/kraken",
            "--candles-dir",
            "coinbase",
            "var/research/candles/coinbase",
        ]
    )
    assert args.catalog == "v2"
    assert args.candles_dir == [
        ["kraken", "var/research/candles/kraken"],
        ["coinbase", "var/research/candles/coinbase"],
    ]
