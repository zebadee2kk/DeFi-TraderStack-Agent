"""The wide-universe top-k family documents RiskEngine layering; it cannot widen it.

Acceptance criterion from #140: ``RiskEngine.max_positions`` layering is
documented rather than widened. The research modules must read nothing
from ``Settings``, import nothing from the risk plane, never emit a short,
and never produce a report row that can promote — even when every basket
is hand-marked as a passer.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research import universe, xs_topk
from traderstack.research.xs_topk import (
    CONTROL_ID,
    CORE_IDS,
    PILOT_TIER_TAKER_BPS,
    TOPK_IDS,
    TOPK_KS,
    CandidatePrint,
    EraCell,
    PrintMeta,
    PrintResult,
    RebalanceDecision,
    build_xs_topk_report,
    voter_from_decisions,
)
from traderstack.strategies import Regime


def settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
    )


def _bar(symbol: str, at: datetime) -> tuple[Candle, ...]:
    return (
        Candle(
            symbol=symbol,
            interval="1d",
            opened_at=at,
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
        ),
    )


def test_top_k_never_exceeds_default_position_limits() -> None:
    values = settings()
    assert values.trading_mode == "paper"
    assert max(TOPK_KS) <= values.max_open_positions == 5
    assert max(TOPK_KS) * values.max_position_pct <= values.max_gross_exposure_pct
    # The family names the limit it lives under; it does not carry a knob for it.
    assert "MAX_OPEN_POSITIONS" in xs_topk.MAX_POSITIONS_LAYERING_NOTE
    assert "max_positions_reached" in xs_topk.MAX_POSITIONS_LAYERING_NOTE


def test_research_modules_do_not_touch_settings_or_risk_plane() -> None:
    for module in (xs_topk, universe):
        source = inspect.getsource(module)
        assert "traderstack.risk" not in source
        assert "traderstack.killswitch" not in source
        assert "traderstack.execution" not in source
        assert "traderstack.runtime" not in source
        assert "traderstack.config" not in source
        assert "import Settings" not in source
        assert "Settings(" not in source  # never constructed, never mutated
        assert "os.environ" not in source


def test_promote_defaults_and_no_topk_pin() -> None:
    values = settings()
    fields = Settings.model_fields
    assert not any(name.startswith("paper_promote_xs_topk") for name in fields)
    for name in fields:
        if name.startswith("paper_promote_") and isinstance(getattr(values, name), bool):
            assert getattr(values, name) is False, name
    assert values.paper_garch_size is False


def test_voter_never_emits_sell_even_for_negative_weights() -> None:
    at = datetime(2024, 1, 1, tzinfo=UTC)
    hostile = (RebalanceDecision(decided_at=at, weights={"BTC/USD": -1.0, "ETH/USD": 5.0}),)
    voter = voter_from_decisions("xs_topk_ew_21_k3", hostile)
    btc = _bar("BTC/USD", at)
    eth = _bar("ETH/USD", at)
    assert voter.evaluate(btc, Regime.RANGE).side is None
    signal = voter.evaluate(eth, Regime.RANGE)
    assert signal.side is Side.BUY and signal.score <= 1.0
    assert Side.SELL not in {voter.evaluate(c, Regime.RANGE).side for c in (btc, eth)}


def _all_pass_print(venue: str, era_id: str) -> PrintResult:
    candidates = []
    for candidate_id in CORE_IDS:
        cell = EraCell(
            venue=venue,
            era_id=era_id,
            covered=True,
            bars=700,
            excess_vs_control_pilot=0.5,
            bar_pass=True,
        )
        candidates.append(
            CandidatePrint(
                candidate_id=candidate_id,
                venue=venue,
                cells=[cell],
                covered_cells=1,
                passed_cells=1,
                holdout_excess_pilot=0.2,
                holdout_pass=True,
                print_pass=True,
            )
        )
    return PrintResult(
        meta=PrintMeta(venue=venue, source="hand", status="ok", eras_covered=[era_id]),
        candidates=candidates,
    )


def test_twelve_hand_marked_passers_still_cannot_promote() -> None:
    report = build_xs_topk_report(
        [_all_pass_print("kraken", "2024-2026"), _all_pass_print("coinbase", "2024-2026")],
        fee_bps=10.0,
        slippage_bps=5.0,
        pilot_fee_bps=PILOT_TIER_TAKER_BPS,
        starting_equity=10_000.0,
        holdout_fraction=0.2,
    )
    assert sorted(report.dual_print_passer_ids) == sorted(TOPK_IDS)
    assert CONTROL_ID not in report.dual_print_passer_ids
    assert report.keep_flag_false is True
    assert all(row.can_promote is False for row in report.rows)
    flag = report.recommended_promote_flag
    assert flag is not None and flag.startswith("PAPER_PROMOTE_XS_TOPK_")
    # The recommended name is documentation only: no such Settings field exists.
    assert flag.lower() not in Settings.model_fields
    assert "Keep every `PAPER_PROMOTE_*=false`" in report.recommendation
    assert settings().trading_mode == "paper"
