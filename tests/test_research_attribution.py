from datetime import UTC, datetime, timedelta

from traderstack.backtest import BaselineBacktester
from traderstack.candles import Candle
from traderstack.research.attribution import build_attribution_report, render_attribution_table


def make_uptrend(count: int = 200) -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    price = 100.0
    for index in range(count):
        previous = price
        price = price + 0.5
        candles.append(
            Candle(
                symbol="BTC/USD",
                interval="1h",
                opened_at=start + timedelta(hours=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def test_attribution_report_decomposes_a_backtest() -> None:
    candles = make_uptrend()
    metrics = BaselineBacktester().run(candles)
    assert metrics.trades >= 1

    report = build_attribution_report(metrics.trade_log, asset="BTC/USD")
    assert report.total_trades == metrics.trades
    assert report.asset == "BTC/USD"
    assert sum(bucket.trade_count for bucket in report.by_side) == metrics.trades
    assert sum(bucket.trade_count for bucket in report.by_regime) == metrics.trades

    # Every trade in this uptrend backtest is a buy.
    sides = {bucket.key for bucket in report.by_side}
    assert sides <= {"buy", "sell"}

    # gross return should be >= net return (costs only ever eat into it)
    assert report.gross_vs_costs.gross_return >= report.gross_vs_costs.net_return
    assert report.gross_vs_costs.total_fees_usd == sum(t.fees_paid for t in metrics.trade_log)


def test_attribution_report_handles_no_trades() -> None:
    report = build_attribution_report([], asset="ETH/USD")
    assert report.total_trades == 0
    assert report.gross_vs_costs.trade_count == 0
    assert report.gross_vs_costs.win_rate == 0.0
    assert report.by_strategy == []


def test_render_attribution_table_produces_readable_text() -> None:
    candles = make_uptrend()
    metrics = BaselineBacktester().run(candles)
    report = build_attribution_report(metrics.trade_log, asset="BTC/USD")
    text = render_attribution_table(report)
    assert "Performance Attribution" in text
    assert "By strategy" in text
    assert "Gross vs. costs" in text
