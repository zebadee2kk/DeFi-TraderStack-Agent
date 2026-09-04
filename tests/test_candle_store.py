from datetime import UTC, datetime

from traderstack.candle_store import build_upsert_statement
from traderstack.candles import Candle


def make_candle(symbol: str = "BTC/USD", hour: int = 0) -> Candle:
    return Candle(
        symbol=symbol,
        interval="1h",
        opened_at=datetime(2026, 1, 1, hour, tzinfo=UTC),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
    )


def test_build_upsert_statement_returns_none_for_empty_batch() -> None:
    assert build_upsert_statement(()) is None


def test_build_upsert_statement_is_one_postgres_upsert_with_on_conflict_do_nothing() -> None:
    candles = (make_candle(hour=0), make_candle(hour=1), make_candle(hour=2))

    statement = build_upsert_statement(candles)
    assert statement is not None
    sql = str(statement.compile())

    # A single INSERT statement covers the whole batch -- no per-row select.
    assert sql.count("INSERT INTO candles") == 1
    assert "ON CONFLICT (symbol, interval, opened_at) DO NOTHING" in sql


def test_build_upsert_statement_batches_all_rows_in_one_statement() -> None:
    candles = tuple(make_candle(hour=h) for h in range(5))

    statement = build_upsert_statement(candles)
    assert statement is not None
    compiled = statement.compile()

    # Multi-row VALUES: five distinct opened_at bind parameters, one per row.
    opened_at_params = [key for key in compiled.params if key.startswith("opened_at")]
    assert len(opened_at_params) == 5
    assert {compiled.params[key].hour for key in opened_at_params} == {0, 1, 2, 3, 4}


def test_build_upsert_statement_uppercases_symbol() -> None:
    statement = build_upsert_statement((make_candle(symbol="eth/usd"),))
    assert statement is not None
    compiled = statement.compile()

    assert compiled.params["symbol_m0"] == "ETH/USD"
