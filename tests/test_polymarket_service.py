import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from traderstack.config import Settings
from traderstack.killswitch import KillSwitch
from traderstack.polymarket.cli import load_fixtures
from traderstack.polymarket.ledger import PolymarketWeatherPaperLedger
from traderstack.polymarket.models import IntentStatus, PaperIntent
from traderstack.polymarket.service import (
    PolymarketWeatherPaperService,
    require_paper_trading_mode,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "polymarket"


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "trading_mode": "paper",
        "kill_switch": False,
        "polymarket_weather_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def _service(tmp_path: Path, **overrides: object) -> PolymarketWeatherPaperService:
    cfg = settings(**overrides)
    return PolymarketWeatherPaperService.from_settings(
        cfg,
        ledger=PolymarketWeatherPaperLedger(tmp_path / "paper.jsonl"),
        kill_switch=KillSwitch.from_settings(cfg),
        fixtures=load_fixtures(FIXTURES),
    )


@pytest.mark.asyncio
async def test_fixture_cycle_emits_paper_intents_not_orders(tmp_path: Path) -> None:
    report = await _service(tmp_path).run_once()
    statuses = {intent.status for intent in report.intents}
    assert IntentStatus.WOULD_TRADE in statuses
    assert IntentStatus.BELOW_EDGE in statuses
    assert IntentStatus.CITY_BLOCKED in statuses
    would = [intent for intent in report.intents if intent.status is IntentStatus.WOULD_TRADE]
    assert all(intent.venue_submitted is False for intent in would)
    assert all(intent.execution == "paper_intent_only" for intent in would)
    assert all(intent.trading_mode == "paper" for intent in would)
    assert all(intent.paper_notional_usd == 10.0 for intent in would)
    lines = (tmp_path / "paper.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert lines
    for line in lines:
        row = json.loads(line)
        assert row["venue_submitted"] is False
        assert row["execution"] == "paper_intent_only"


@pytest.mark.asyncio
async def test_kill_switch_withholds_would_trade(tmp_path: Path) -> None:
    report = await _service(tmp_path, kill_switch=True).run_once()
    assert report.kill_switch_engaged
    assert report.would_trade == 0
    assert report.withheld >= 1
    withheld = [intent for intent in report.intents if intent.status is IntentStatus.KILL_SWITCH]
    assert withheld
    assert all(intent.paper_notional_usd == 0.0 for intent in withheld)
    assert all("kill_switch" in " ".join(intent.reasons) for intent in withheld)


@pytest.mark.asyncio
async def test_sentinel_file_withholds_like_settings_flag(tmp_path: Path) -> None:
    sentinel = tmp_path / "KILL"
    sentinel.write_text("operator\n", encoding="utf-8")
    cfg = settings(kill_switch=False, kill_switch_file=str(sentinel))
    service = PolymarketWeatherPaperService.from_settings(
        cfg,
        ledger=PolymarketWeatherPaperLedger(tmp_path / "paper.jsonl"),
        kill_switch=KillSwitch.from_settings(cfg),
        fixtures=load_fixtures(FIXTURES),
    )
    report = await service.run_once()
    assert "file" in report.kill_switch_sources
    assert report.would_trade == 0
    assert report.withheld >= 1


def test_live_trading_mode_is_rejected(tmp_path: Path) -> None:
    cfg = settings(trading_mode="live")
    with pytest.raises(RuntimeError, match="TRADING_MODE=paper"):
        require_paper_trading_mode(cfg)
    with pytest.raises(RuntimeError, match="TRADING_MODE=paper"):
        PolymarketWeatherPaperService.from_settings(
            cfg,
            ledger=PolymarketWeatherPaperLedger(tmp_path / "paper.jsonl"),
            kill_switch=KillSwitch.from_settings(settings()),
            fixtures=load_fixtures(FIXTURES),
        )


@pytest.mark.asyncio
async def test_ledger_refuses_a_submitted_intent(tmp_path: Path) -> None:
    ledger = PolymarketWeatherPaperLedger(tmp_path / "paper.jsonl")
    with pytest.raises(RuntimeError, match="venue_submitted"):
        await ledger.append(
            PaperIntent.model_construct(
                status=IntentStatus.WOULD_TRADE,
                venue_submitted=True,  # type: ignore[arg-type]
            )
        )


def test_clock_is_injectable_for_deterministic_parses(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.clock = lambda: datetime(2026, 9, 11, 15, tzinfo=UTC)
    assert service.clock().date().isoformat() == "2026-09-11"
