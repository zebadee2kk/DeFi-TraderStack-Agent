"""Fee realism (#138): the fee tier can only make paper and research costs equal
or more expensive, is frozen on live Settings, is not RiskEngine policy, and no
research CLI can select a maker role before post-only fill-rate evidence exists.
"""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

from traderstack.config import Settings
from traderstack.execution.ledger import ExecutionLedger, FeeSource
from traderstack.execution.paper_fill import PaperFillSimulator, PaperFillStatus
from traderstack.fee_tiers import (
    FEE_TIER_IDS,
    PILOT_FEE_TIER_ID,
    resolve_research_costs,
)
from traderstack.models import Side
from traderstack.pipeline import PaperOrderIntent
from traderstack.portfolio import InMemoryPortfolioBook
from traderstack.research.search import research_fee_bps
from traderstack.risk import RISK_LIMIT_FIELDS, derive_policy_version

RESEARCH_CLI_MODULES = (
    "traderstack.research.cli",
    "traderstack.research.search_cli",
    "traderstack.research.miles_cli",
    "traderstack.research.daily_robustness_cli",
    "traderstack.research.harder_gates_cli",
    "traderstack.research.honesty_pack_cli",
    "traderstack.research.second_print_cli",
    "traderstack.research.dual_print_search_cli",
    "traderstack.research.liq_regime_search_cli",
    "traderstack.research.intraday_dual_print_cli",
    "traderstack.research.relative_value_cli",
    "traderstack.research.cross_sectional_momentum_cli",
    "traderstack.research.donchian_breakout_cli",
    "traderstack.research.tsmom_cli",
    "traderstack.research.bollinger_fade_cli",
    "traderstack.research.calendar_seasonality_cli",
    "traderstack.research.lead_lag_cli",
    "traderstack.research.volume_breakout_cli",
)


def test_paper_fee_tier_cannot_be_rewritten_on_live_settings() -> None:
    settings = Settings(paper_fee_tier="kraken_pro_spot_t1")
    with pytest.raises(ValidationError):
        settings.paper_fee_tier = "kraken_pro_spot_t12"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        settings.paper_fee_tier = "modelled"  # type: ignore[misc]
    assert settings.paper_fee_tier == "kraken_pro_spot_t1"
    assert settings.effective_paper_fee_bps == 80.0


def test_no_tier_makes_research_or_paper_cheaper_than_the_pretrade_fee() -> None:
    for tier_id in FEE_TIER_IDS:
        settings = Settings(paper_fee_tier=tier_id)  # type: ignore[arg-type]
        assert settings.effective_paper_fee_bps >= 0
        assert research_fee_bps(10.0, settings.effective_paper_fee_bps) >= 10.0
        costs = resolve_research_costs(fee_bps=None, fee_tier=None, settings=settings)
        assert costs.fee_bps >= settings.pretrade_fee_bps
        assert costs.fee_bps >= settings.effective_paper_fee_bps
        assert costs.stamp.role == "taker"


def test_pilot_default_is_the_most_expensive_published_tier() -> None:
    default = Settings()
    assert default.paper_fee_tier == PILOT_FEE_TIER_ID
    for tier_id in FEE_TIER_IDS:
        other = Settings(paper_fee_tier=tier_id)  # type: ignore[arg-type]
        assert other.effective_paper_fee_bps <= default.effective_paper_fee_bps


def test_fee_tier_is_not_risk_engine_policy() -> None:
    assert "paper_fee_tier" not in RISK_LIMIT_FIELDS
    versions = {
        derive_policy_version(Settings(kill_switch=False, paper_fee_tier=tier_id))  # type: ignore[arg-type]
        for tier_id in FEE_TIER_IDS
    }
    assert len(versions) == 1


def test_free_form_tier_strings_never_reach_a_fee_number(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in ("maker", "kraken_pro_spot_t1;maker", "0", "-40", "kraken_pro_spot_t4", ""):
        monkeypatch.setenv("PAPER_FEE_TIER", bad)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.delenv("PAPER_FEE_TIER")
    with pytest.raises(ValidationError):
        Settings(paper_fee_tier="maker")  # type: ignore[arg-type]


@pytest.mark.parametrize("module_name", RESEARCH_CLI_MODULES)
def test_every_research_cli_has_fee_tier_and_rejects_a_maker_role(module_name: str) -> None:
    parser = importlib.import_module(module_name).build_parser()
    options = parser._option_string_actions
    assert "--fee-tier" in options
    assert "--fee-role" not in options
    assert "--maker" not in options
    assert "--fee-maker-bps" not in options
    tier_action = options["--fee-tier"]
    assert tier_action.default is None
    assert tuple(tier_action.choices) == FEE_TIER_IDS
    with pytest.raises(SystemExit):
        parser.parse_args(["--fee-role", "maker"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--fee-tier", "maker"])


def test_tier_taker_paper_fill_cannot_increase_approved_notional() -> None:
    intent = PaperOrderIntent(decision_id="d-138", asset="BTC", side=Side.BUY, notional_usd=1_000)
    ledger = ExecutionLedger()
    book = InMemoryPortfolioBook(starting_nav_usd=10_000)
    simulator = PaperFillSimulator(paper_fee_bps=80.0, paper_slippage_bps=5.0)

    outcome = simulator.apply(intent, mid_usd=20_000.0, ledger=ledger, portfolio=book)

    assert outcome.status is PaperFillStatus.FILLED
    assert outcome.fill is not None
    filled_notional = outcome.fill.quantity * outcome.fill.price_usd
    assert filled_notional <= intent.notional_usd * (1 + 5.0 / 10_000) + 1e-6
    assert outcome.fill.price_usd >= 20_000.0  # still mid + adverse slippage (a taker fill)
    assert outcome.fee_usd == pytest.approx(filled_notional * 80.0 / 10_000)
    order = next(iter(ledger.orders.values()))
    assert order.fee_source is FeeSource.MODELLED
    assert book.nav_usd == pytest.approx(10_000 - outcome.fee_usd)
