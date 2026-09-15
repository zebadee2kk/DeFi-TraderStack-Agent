"""Adversarial (#134): a hostile basis tape cannot move a control.

The basis adapters take untrusted venue payloads (OKX JSON, Binance
Vision zip contents). Everything that leaves them must be a bounded,
finite float on a UTC day; forbidden constructions must be refused in
code; and no basis series — however shaped — may flip ``can_promote``
past the dual-print / hard-gate / paper-path conjunction or touch a
``PAPER_PROMOTE_*`` default. The research modules must not import the
risk engine or the execution plane at all.
"""

from __future__ import annotations

import ast
import io
import math
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research import basis, basis_binance_vision, basis_cli, basis_okx
from traderstack.research.basis import (
    MAX_ABS_BASIS,
    basis_from_closes,
    bounded_basis,
    refuse_forbidden_basis_source,
)
from traderstack.research.basis_binance_vision import (
    parse_vision_kline_csv,
    unzip_single_csv,
)
from traderstack.research.basis_okx import fetch_okx_basis, parse_okx_candle_page
from traderstack.research.funding_carry import (
    PRINT_DUAL,
    PRINT_SINGLE,
    run_funding_carry,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
SRC = Path(__file__).resolve().parents[2] / "src" / "traderstack" / "research"


async def no_sleep(_seconds: float) -> None:
    return None


def make_candles(count: int, *, symbol: str, start: datetime = START) -> tuple[Candle, ...]:
    candles = []
    for index in range(count):
        price = 200.0 - 0.25 * index
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=start + timedelta(days=index),
                open=price,
                high=price * 1.002,
                low=price * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


HOSTILE_VALUES = [
    (float("nan"), 100.0),
    (100.0, float("nan")),
    (float("inf"), 100.0),
    (100.0, float("inf")),
    (1e9, 100.0),  # |basis| ≫ MAX_ABS_BASIS
    (100.0, -100.0),  # negative index
    (-100.0, 100.0),
    (100.0, 0.0),  # division by zero
    (100.0, 1e-300),  # overflow
]


@pytest.mark.parametrize(("mark", "index"), HOSTILE_VALUES)
def test_hostile_closes_yield_no_point(mark: float, index: float) -> None:
    assert bounded_basis(mark, index) is None
    points, skipped = basis_from_closes({START: mark}, {START: index})
    assert points == []
    assert skipped == 1


def test_every_emitted_basis_value_is_finite_and_bounded() -> None:
    mark = {START + timedelta(days=i): 100.0 * (1 + (i % 7) * 0.01) for i in range(50)}
    mark[START + timedelta(days=60)] = 1e12
    index = {day: 100.0 for day in mark}
    points, _skipped = basis_from_closes(mark, index)
    assert points
    assert all(math.isfinite(v) and abs(v) <= MAX_ABS_BASIS for _d, v in points)
    assert all(d.tzinfo is UTC and d.hour == 0 and d.minute == 0 for d, _v in points)


@pytest.mark.asyncio
async def test_hostile_okx_payload_cannot_produce_a_series() -> None:
    hostile_rows = [
        ["1704067200000", "1", "2", "0.5", "1e400", "1"],
        ["1704153600000", "1", "2", "0.5", "-1", "1"],
        ["1704240000000", "1", "2", "0.5", "NaN", "1"],
        ["1704326400000", "1", "2", "0.5", "Infinity", "1"],
        {"ts": "1704412800000", "c": "100"},
        None,
        ["1704499200000", "1", "2", "0.5", "100", "0"],  # uncommitted
        ["-5", "1", "2", "0.5", "100", "1"],
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "0", "data": hostile_rows})

    rows, _oldest = parse_okx_candle_page({"code": "0", "data": hostile_rows})
    assert rows == []
    async with httpx.AsyncClient(
        base_url="https://www.okx.com", transport=httpx.MockTransport(handler)
    ) as client:
        result = await fetch_okx_basis("BTC/USD", client=client, pause_seconds=0, sleep=no_sleep)
    assert result.status == "skipped"
    assert result.points == ()


def test_hostile_vision_csv_and_zip_cannot_produce_a_series() -> None:
    hostile = b"\n".join(
        [
            b"open_time,open,high,low,close",
            b"1704067200000,1,2,0.5,1e400",
            b"1704153600000,1,2,0.5,-1",
            b"1704240000000,1,2,0.5,nan",
            b"not,a,row",
            b"-1,1,2,0.5,100",
            b"\xff\xfe binary garbage",
        ]
    )
    assert parse_vision_kline_csv(hostile) == []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.csv", b"1,2,3,4,5")
        archive.writestr("../../etc/passwd", b"root")
    with pytest.raises(ValueError):
        unzip_single_csv(buffer.getvalue())
    with pytest.raises(zipfile.BadZipFile):
        unzip_single_csv(b"PK\x03\x04 not really a zip")


@pytest.mark.parametrize(
    "label",
    [
        "/fapi/v1/premiumIndex",
        "premiumIndexKlines",
        "/api/v5/market/candles",
        "/api/v5/market/history-candles",
        "/api/v5/public/funding-rate-history",
        "/fapi/v1/fundingRate",
        "fundingHistory.premium",
        "candleSnapshot",
        "/api/v1/trade/bucketed?symbol=.XBTUSDPI",
        "/data/futures/um/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2020-01.zip",
        "/data/futures/um/monthly/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2020-01.zip",
        "/linear-swap-api/v1/swap_historical_funding_rate",
        "avg_premium_index",
    ],
)
def test_forbidden_basis_sources_are_refused(label: str) -> None:
    with pytest.raises(ValueError):
        refuse_forbidden_basis_source(label)


def test_allowed_basis_sources_pass() -> None:
    for label in (
        "/api/v5/market/history-mark-price-candles",
        "/api/v5/market/history-index-candles",
        "/data/futures/um/monthly/markPriceKlines/BTCUSDT/1d/BTCUSDT-1d-2020-01.zip",
        "/data/futures/um/daily/indexPriceKlines/ETHUSDT/1d/ETHUSDT-1d-2026-09-12.zip",
    ):
        refuse_forbidden_basis_source(label)


def _hostile_basis(days: int, value: float) -> tuple[tuple[datetime, float], ...]:
    return tuple((START + timedelta(days=i), value) for i in range(days))


def test_hostile_basis_series_cannot_raise_can_promote_single_print() -> None:
    btc = make_candles(360, symbol="BTC/USD")
    eth = make_candles(360, symbol="ETH/USD")
    funding = tuple((c.opened_at, 0.001) for c in btc)
    # An absurdly favourable basis ramp (falling from +5% to −5%): pure gain if applied.
    hostile = tuple((START + timedelta(days=i), 0.05 - 0.1 * i / 360) for i in range(360))
    report = run_funding_carry(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        fee_bps=10.0,
        slippage_bps=5.0,
        train_size=80,
        test_size=40,
        step_size=40,
        warmup=8,
        holdout_fraction=0.2,
        min_trades=1,
        interval="1d",
        funding_by_symbol={"BTC/USD": funding, "ETH/USD": funding},
        primary_venue="okx",
        basis_by_symbol={"BTC/USD": hostile, "ETH/USD": hostile},
        basis_venue="okx",
    )
    assert report.print_kind == PRINT_SINGLE
    assert report.basis_status == "ok"
    assert report.can_promote is False
    assert report.any_promoted is False
    assert report.recommended_promote_flag is None
    assert report.keep_flag_false is True


def test_hostile_basis_cannot_unlock_dual_print_when_hard_gates_fail() -> None:
    start = START
    other = datetime(2023, 1, 1, tzinfo=UTC)
    btc = make_candles(360, symbol="BTC/USD", start=start)
    eth = make_candles(360, symbol="ETH/USD", start=start)
    other_btc = make_candles(360, symbol="BTC/USD", start=other)
    other_eth = make_candles(360, symbol="ETH/USD", start=other)
    funding = tuple((c.opened_at, 0.001) for c in btc)
    other_funding = tuple((c.opened_at, 0.001) for c in other_btc)
    hostile = tuple((c.opened_at, 0.05 - 0.1 * i / 360) for i, c in enumerate(btc))
    other_hostile = tuple((c.opened_at, 0.05 - 0.1 * i / 360) for i, c in enumerate(other_btc))
    report = run_funding_carry(
        {"BTC/USD@1d": btc, "ETH/USD@1d": eth},
        fee_bps=10.0,
        slippage_bps=5.0,
        train_size=80,
        test_size=40,
        step_size=40,
        warmup=8,
        holdout_fraction=0.2,
        min_trades=1,
        interval="1d",
        funding_by_symbol={"BTC/USD": funding, "ETH/USD": funding},
        second_funding_by_symbol={"BTC/USD": other_funding, "ETH/USD": other_funding},
        second_histories={"BTC/USD@1d": other_btc, "ETH/USD@1d": other_eth},
        primary_venue="hyperliquid",
        second_venue="htx",
        basis_by_symbol={"BTC/USD": hostile, "ETH/USD": hostile},
        second_basis_by_symbol={"BTC/USD": other_hostile, "ETH/USD": other_hostile},
        basis_venue="okx",
        second_basis_venue="binance_vision",
    )
    assert report.print_kind == PRINT_DUAL
    assert report.basis_status == "ok"
    assert report.basis_print_kind == "dual_basis"
    # 360 days < 720: hard gates stay UNAVAILABLE, so no basis can unlock promotion.
    assert report.hard_gates_available is False
    assert report.can_promote is False
    assert report.any_promoted is False
    assert report.promoted_candidate_ids == []
    assert report.recommended_promote_flag is None


def test_paper_promote_defaults_untouched_and_no_carry_pin() -> None:
    for name, field in Settings.model_fields.items():
        if name.startswith("paper_promote_") and field.annotation is bool:
            assert field.default is False, name
    assert "PAPER_PROMOTE_CARRY" not in Settings.model_fields
    assert "paper_promote_carry" not in Settings.model_fields
    assert Settings.model_fields["trading_mode"].default == "paper"


def _imports_of(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module", [basis, basis_okx, basis_binance_vision, basis_cli])
def test_basis_modules_do_not_reach_risk_or_execution(module: object) -> None:
    path = Path(str(getattr(module, "__file__", "")))
    assert path.is_relative_to(SRC)
    imported = _imports_of(path)
    forbidden = {
        name
        for name in imported
        if name.startswith(("traderstack.risk", "traderstack.execution", "traderstack.config"))
        or name in {"traderstack.runtime", "traderstack.service", "traderstack.pipeline"}
    }
    assert forbidden == set(), forbidden
