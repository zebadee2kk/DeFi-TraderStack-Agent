from datetime import UTC, datetime

from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.runtime import RuntimeResult
from traderstack.trace_cli import build_parser, render_event


def test_build_parser_requires_decision_id() -> None:
    parser = build_parser()
    args = parser.parse_args(["decision-123"])
    assert args.decision_id == "decision-123"
    assert args.limit is None


def test_render_event_includes_outcome_and_rejection_reasons() -> None:
    result = RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=99,
            ask=101,
            last=100,
        ),
        references=[],
        pipeline=PipelineResult(accepted_market_data=False, rejection_reasons=["stale_primary_tick"]),
    )

    text = render_event(1, result)

    assert "BTC/USD" in text
    assert "outcome=rejected" in text
    assert "stale_primary_tick" in text


def test_render_event_includes_proposal_risk_and_paper_order_details() -> None:
    proposal = TradeProposal(
        strategy_id="s",
        asset="BTC",
        side=Side.BUY,
        confidence=0.75,
        requested_notional_usd=250.0,
        thesis="t",
        source_freshness_seconds=0,
    )
    risk_result = RiskResult(
        decision_id=proposal.decision_id,
        decision=RiskDecision.ALLOW,
        approved_notional_usd=250.0,
        policy_version="v1",
    )
    order = PaperOrderIntent(
        decision_id=str(proposal.decision_id), asset="BTC", side=Side.BUY, notional_usd=250.0
    )
    result = RuntimeResult(
        tick=MarketTick(
            source=MarketSource.KRAKEN,
            symbol="BTC/USD",
            observed_at=datetime.now(UTC),
            bid=99,
            ask=101,
            last=100,
        ),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True, proposal=proposal, risk_result=risk_result, paper_order=order
        ),
    )

    text = render_event(1, result)

    assert "outcome=accepted" in text
    assert "proposal: side=buy" in text
    assert "risk: decision=allow" in text
    assert "paper_order:" in text
