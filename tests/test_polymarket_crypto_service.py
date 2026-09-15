"""The #142 collector writes observations, never intents."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from traderstack.config import Settings
from traderstack.killswitch import KillSwitch
from traderstack.polymarket.crypto_cli import load_crypto_fixtures
from traderstack.polymarket.crypto_models import CrucixStatus, WedgeRowStatus
from traderstack.polymarket.crypto_service import (
    CryptoWedgeFixtures,
    PolymarketCryptoWedgeCollector,
    resolve_assets,
)
from traderstack.polymarket.crypto_tape import CryptoWedgeTape, read_rows

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "polymarket_crypto"
NOW = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "trading_mode": "paper",
        "kill_switch": False,
        "kill_switch_redis_enabled": False,
        "polymarket_crypto_tape_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def collector(
    tmp_path: Path,
    *,
    fixtures: CryptoWedgeFixtures | None = None,
    **overrides: object,
) -> PolymarketCryptoWedgeCollector:
    cfg = settings(**overrides)
    return PolymarketCryptoWedgeCollector.from_settings(
        cfg,
        tape=CryptoWedgeTape(tmp_path / "tape.jsonl"),
        kill_switch=KillSwitch.from_settings(cfg),
        fixtures=fixtures if fixtures is not None else load_crypto_fixtures(FIXTURES),
    )


async def test_cycle_writes_paper_tape_only_rows(tmp_path: Path) -> None:
    report = await collector(tmp_path).run_once()

    assert report.trading_mode == "paper"
    assert report.observed_at == NOW
    assert report.rows_ok == 2
    assert report.rows_written == 4
    lines = (tmp_path / "tape.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4
    payloads = [json.loads(line) for line in lines]
    assert all(row["venue_submitted"] is False for row in payloads)
    assert all(row["execution"] == "paper_tape_only" for row in payloads)
    assert all(row["trading_mode"] == "paper" for row in payloads)
    # No instruction-shaped field ever reaches the tape.
    assert not any(
        key in row for row in payloads for key in ("side", "size", "notional", "paper_order")
    )


async def test_ok_rows_carry_both_venue_timestamps_and_the_wedge(tmp_path: Path) -> None:
    report = await collector(tmp_path).run_once()
    ok_rows = [row for row in report.rows if row.status is WedgeRowStatus.OK]
    assert ok_rows
    for row in ok_rows:
        assert row.poly_book_ts is not None
        assert row.deribit_ts is not None
        assert row.poly_mid is not None and row.deribit_prob is not None
        assert row.wedge == pytest.approx(row.poly_mid - row.deribit_prob)
        assert row.model_version == "bs_n_d2_markiv_interp_v1"
        assert row.expiry_gap_hours == 8.0


async def test_one_sided_book_and_sparse_chain_are_recorded_not_invented(tmp_path: Path) -> None:
    report = await collector(tmp_path).run_once()
    by_strike = {row.strike_usd: row for row in report.rows}
    one_sided = by_strike[78000.0]
    assert one_sided.status is WedgeRowStatus.NO_TWO_SIDED_BOOK
    assert one_sided.poly_mid is None
    assert one_sided.wedge is None
    sparse = by_strike[999000.0]
    assert sparse.status is WedgeRowStatus.NO_OPTION_PROBABILITY
    assert sparse.deribit_prob is None
    assert any("sparse_chain" in reason for reason in sparse.reasons)


async def test_each_freshness_bound_is_checked_independently(tmp_path: Path) -> None:
    fixtures = load_crypto_fixtures(FIXTURES)
    # Advance the clock past the bound: the Polymarket book is now stale.
    fixtures.now = NOW + timedelta(seconds=200)
    report = await collector(tmp_path, fixtures=fixtures).run_once()
    statuses = {row.status for row in report.rows if row.strike_usd in (74000.0, 3000.0)}
    assert statuses == {WedgeRowStatus.STALE_POLYMARKET}

    # Keep the book fresh but age only the Deribit quotes.
    fresh = load_crypto_fixtures(FIXTURES)
    for rows in fresh.deribit_summary.values():
        for row in rows:
            row["creation_timestamp"] = row["creation_timestamp"] - 600_000
    report = await collector(tmp_path, fixtures=fresh).run_once()
    stale = [row for row in report.rows if row.strike_usd == 74000.0]
    assert stale and stale[0].status is WedgeRowStatus.STALE_DERIBIT
    assert stale[0].deribit_prob is not None  # the probability is still recorded as evidence


async def test_empty_discovery_is_a_successful_empty_cycle(tmp_path: Path) -> None:
    report = await collector(tmp_path, fixtures=CryptoWedgeFixtures(now=NOW)).run_once()
    assert report.rows_written == 0
    assert report.rows_ok == 0
    assert report.events_missing == report.slugs_requested == 6
    assert "empty cycle is a successful result" in report.render()
    assert not (tmp_path / "tape.jsonl").exists()


async def test_crucix_status_is_recorded_per_asset(tmp_path: Path) -> None:
    report = await collector(tmp_path).run_once()
    assert report.crucix_status == {"BTC": "clear", "ETH": "adverse"}
    btc = [row for row in report.rows if row.asset == "BTC"]
    eth = [row for row in report.rows if row.asset == "ETH"]
    assert all(row.crucix_status is CrucixStatus.CLEAR for row in btc)
    assert all(row.crucix_adverse is False for row in btc)
    assert all(row.crucix_status is CrucixStatus.ADVERSE for row in eth)
    assert all(row.crucix_adverse is True for row in eth)


async def test_unconfigured_crucix_records_not_configured(tmp_path: Path) -> None:
    fixtures = load_crypto_fixtures(FIXTURES)
    fixtures.crucix = {}
    report = await collector(tmp_path, fixtures=fixtures).run_once()
    assert set(report.crucix_status.values()) == {"not_configured"}
    assert all(row.crucix_status is CrucixStatus.NOT_CONFIGURED for row in report.rows)
    assert all(row.crucix_adverse is None for row in report.rows)


async def test_unreadable_crucix_payload_records_unavailable(tmp_path: Path) -> None:
    fixtures = load_crypto_fixtures(FIXTURES)
    fixtures.crucix = {"BTC": "not-a-payload", "ETH": "not-a-payload"}
    report = await collector(tmp_path, fixtures=fixtures).run_once()
    assert set(report.crucix_status.values()) == {"unavailable"}
    assert all(row.crucix_status is CrucixStatus.UNAVAILABLE for row in report.rows)


async def test_missing_deribit_chain_is_a_skip_not_a_zero(tmp_path: Path) -> None:
    fixtures = load_crypto_fixtures(FIXTURES)
    fixtures.deribit_summary = {}
    report = await collector(tmp_path, fixtures=fixtures).run_once()
    assert report.rows_ok == 0
    assert set(report.chain_errors) == {"BTC", "ETH"}
    assert all(row.deribit_prob is None for row in report.rows)
    assert "deribit chain unavailable" in report.render()


async def test_kill_switch_is_reported_and_changes_nothing_recorded(tmp_path: Path) -> None:
    clear = await collector(tmp_path).run_once()
    engaged = await collector(tmp_path, kill_switch=True).run_once()
    assert clear.kill_switch_engaged is False
    assert engaged.kill_switch_engaged is True
    assert "kill_switch=engaged" in engaged.render()
    assert [row.status for row in engaged.rows] == [row.status for row in clear.rows]
    assert [row.wedge for row in engaged.rows] == [row.wedge for row in clear.rows]


async def test_tape_round_trips_and_counts_malformed_lines(tmp_path: Path) -> None:
    report = await collector(tmp_path).run_once()
    path = tmp_path / "tape.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json}\n")
    result = read_rows(path)
    assert len(result.rows) == report.rows_written
    assert result.malformed_lines == 1
    assert read_rows(tmp_path / "missing.jsonl").rows == ()


def test_live_trading_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="TRADING_MODE=paper"):
        collector(tmp_path, trading_mode="live")


def test_unknown_assets_are_skipped_not_collected() -> None:
    known, unknown = resolve_assets(settings(polymarket_crypto_assets="BTC,DOGE,eth"))
    assert [asset.value for asset in known] == ["BTC", "ETH"]
    assert unknown == ("DOGE",)


async def test_a_venue_timestamp_in_the_future_is_also_refused(tmp_path: Path) -> None:
    """A venue clock far ahead of ours is not "very fresh"; it is unusable."""

    fixtures = load_crypto_fixtures(FIXTURES)
    for payload in fixtures.books.values():
        payload["timestamp"] = str(int(payload["timestamp"]) + 3_600_000)
    report = await collector(tmp_path, fixtures=fixtures).run_once()
    assert report.rows_ok == 0
    assert {row.status for row in report.rows} <= {
        WedgeRowStatus.STALE_POLYMARKET,
        WedgeRowStatus.NO_TWO_SIDED_BOOK,
        WedgeRowStatus.NO_OPTION_PROBABILITY,
    }
    assert any(row.status is WedgeRowStatus.STALE_POLYMARKET for row in report.rows)


async def test_each_row_is_stamped_with_its_own_read_time(tmp_path: Path) -> None:
    """A live cycle is ~50 GETs long, so the bound must age each row's own reads."""

    stamps = iter(
        [
            NOW,  # cycle start
            NOW,
            NOW + timedelta(seconds=300),  # by this row the book is well past the bound
            NOW + timedelta(seconds=300),
            NOW + timedelta(seconds=300),
            NOW + timedelta(seconds=300),
        ]
    )
    made = collector(tmp_path)
    made.clock = lambda: next(stamps)
    report = await made.run_once()
    statuses = [row.status for row in report.rows]
    assert statuses[0] is WedgeRowStatus.OK
    assert WedgeRowStatus.STALE_POLYMARKET in statuses
    assert report.rows[0].observed_at == NOW
    assert report.rows[-1].observed_at == NOW + timedelta(seconds=300)


async def test_an_unanswered_gamma_is_counted_apart_from_a_missing_event(
    tmp_path: Path,
) -> None:
    """An outage must not read as "the daily event does not exist"."""

    import httpx

    from traderstack.market.deribit import DeribitPublicClient
    from traderstack.polymarket.clob import ClobPublicClient
    from traderstack.polymarket.gamma import GammaClient

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "upstream"})

    cfg = settings()
    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        made = PolymarketCryptoWedgeCollector(
            settings=cfg,
            tape=CryptoWedgeTape(tmp_path / "tape.jsonl"),
            kill_switch=KillSwitch.from_settings(cfg),
            gamma=GammaClient(client=client),
            clob=ClobPublicClient(client=client),
            deribit=DeribitPublicClient(client=client),
            clock=lambda: NOW,
        )
        report = await made.run_once()

    assert report.events_error == report.slugs_requested == 6
    assert report.events_missing == 0
    assert report.rows_written == 0
    assert not (tmp_path / "tape.jsonl").exists()


async def test_unknown_assets_are_named_in_the_report(tmp_path: Path) -> None:
    report = await collector(tmp_path, polymarket_crypto_assets="BTC,DOGE").run_once()
    assert report.unknown_assets == ("DOGE",)
    assert "DOGE" in report.render()
    assert report.assets == ("BTC",)


async def test_the_option_chain_is_re_read_as_the_cycle_runs(tmp_path: Path) -> None:
    """One chain snapshot must not age out silently across a long cycle."""

    import httpx

    from traderstack.market.deribit import DeribitPublicClient
    from traderstack.polymarket.clob import ClobPublicClient
    from traderstack.polymarket.gamma import GammaClient

    expiry_ms = 1789372800000  # 2026-09-14T08:00:00Z
    book_ms = 1789365570000  # 2026-09-14T05:59:30Z
    description = (
        'This market will resolve to "Yes" if the Binance 1 minute candle for '
        "BTC/USDT 12:00 in the ET timezone (noon) has a final close above the "
        "price in the title."
    )
    markets = [
        {
            "id": f"m{index}",
            "question": f"Will the price of Bitcoin be above ${strike:,} on September 14?",
            "description": description,
            "clobTokenIds": json.dumps([f"yes{index}", f"no{index}"]),
            "endDate": "2026-09-14T16:00:00Z",
            "active": True,
            "closed": False,
            "acceptingOrders": True,
            "enableOrderBook": True,
        }
        for index, strike in enumerate((74000, 76000, 78000))
    ]
    deribit_calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/events":
            return httpx.Response(200, json=[{"slug": "bitcoin-above-on-x", "markets": markets}])
        if path == "/book":
            return httpx.Response(
                200,
                json={
                    "bids": [{"price": "0.60", "size": "1"}],
                    "asks": [{"price": "0.62", "size": "1"}],
                    "timestamp": str(book_ms),
                },
            )
        deribit_calls.append(path)
        if path.endswith("get_instruments"):
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "instrument_name": f"BTC-14SEP26-{strike}-C",
                            "option_type": "call",
                            "strike": float(strike),
                            "expiration_timestamp": expiry_ms,
                        }
                        for strike in (70000, 80000)
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "instrument_name": f"BTC-14SEP26-{strike}-C",
                        "mark_iv": 40.0,
                        "mark_price": 0.05,
                        "underlying_price": 76000.0,
                        "creation_timestamp": book_ms,
                    }
                    for strike in (70000, 80000)
                ]
            },
        )

    stamps = iter([NOW + timedelta(seconds=90 * step) for step in range(8)])
    cfg = settings(polymarket_crypto_assets="BTC", polymarket_crypto_lookahead_days=0)
    async with httpx.AsyncClient(
        base_url="https://example.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        made = PolymarketCryptoWedgeCollector(
            settings=cfg,
            tape=CryptoWedgeTape(tmp_path / "tape.jsonl"),
            kill_switch=KillSwitch.from_settings(cfg),
            gamma=GammaClient(client=client),
            clob=ClobPublicClient(client=client),
            deribit=DeribitPublicClient(client=client),
            clock=lambda: next(stamps),
        )
        report = await made.run_once()

    assert report.rows_written == 3
    # Two calls for the first snapshot, then a re-read once it is over half the
    # 120s bound old — not one snapshot stretched across the whole cycle.
    assert len(deribit_calls) > 2
