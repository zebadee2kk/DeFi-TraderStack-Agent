"""Zero-trade diagnosis: the opportunity funnel (#131).

Every path a cycle can stop at -- zero signal, stale data, pre-trade
rejection, risk rejection, meta-agent veto, planner rejection, fill withheld,
successful fill -- must land on the right stage, the right nearest gate, and
the right headline category, and the accumulated report must persist those
counts verbatim.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.agents.review import (
    UNAVAILABLE_REASON,
    VETO_REASON,
    MetaAgentMode,
    MetaAgentReview,
)
from traderstack.audit import JsonlAuditSink
from traderstack.execution.ledger import (
    ExecutionLedger,
    ExecutionLedgerState,
    ExecutionOrder,
    OrderLifecycleState,
)
from traderstack.funnel_cli import main as funnel_main
from traderstack.market.models import MarketSource, MarketTick
from traderstack.models import RiskDecision, RiskResult, Side, TradeProposal
from traderstack.opportunity_funnel import (
    MAX_REASON_KEYS,
    OVERFLOW_KEY,
    BlockingGate,
    FunnelCategory,
    FunnelStage,
    OpportunityFunnel,
    OpportunityFunnelReport,
    classify,
    diagnose,
    funnel_from_audit,
)
from traderstack.pipeline import PaperOrderIntent, PipelineResult
from traderstack.pretrade import PreTradeCheck
from traderstack.runtime import RuntimeResult

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def _tick(symbol: str = "BTC/USD", age_seconds: float = 1.0) -> MarketTick:
    return MarketTick(
        source=MarketSource.KRAKEN,
        symbol=symbol,
        observed_at=NOW - timedelta(seconds=age_seconds),
        bid=19_990,
        ask=20_010,
        last=20_000,
    )


def _proposal(strategy_id: str = "vertical-slice-v1", side: Side = Side.BUY) -> TradeProposal:
    return TradeProposal(
        strategy_id=strategy_id,
        asset="BTC",
        side=side,
        confidence=0.6,
        requested_notional_usd=1_000,
        thesis="fixture",
        signal_ids=["pretrade-backtest-gate-v1"],
        source_freshness_seconds=1.0,
    )


def _risk(proposal: TradeProposal, decision: RiskDecision, approved: float, *reasons: str):
    return RiskResult(
        decision_id=proposal.decision_id,
        decision=decision,
        approved_notional_usd=approved,
        reasons=list(reasons),
        policy_version="mvp-v1+fixture",
    )


def _allowed(
    *,
    strategy_id: str = "vertical-slice-v1",
    exit_reason: str | None = None,
    status: str | None = None,
    reason: str | None = None,
    meta_review: MetaAgentReview | None = None,
    extra_rejections: list[str] | None = None,
    paper_order: bool = True,
    symbol: str = "BTC/USD",
) -> RuntimeResult:
    proposal = _proposal(strategy_id, Side.SELL if exit_reason else Side.BUY)
    order = (
        PaperOrderIntent(
            decision_id=str(proposal.decision_id), asset="BTC", side=proposal.side, notional_usd=900
        )
        if paper_order
        else None
    )
    return RuntimeResult(
        tick=_tick(symbol),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            rejection_reasons=extra_rejections or [],
            proposal=proposal,
            risk_result=_risk(proposal, RiskDecision.ALLOW, 900),
            paper_order=order,
            exit_reason=exit_reason,
        ),
        meta_review=meta_review,
        execution_status=status,
        execution_reason=reason,
        candles_loaded=400,
        candle_last_opened_at=NOW - timedelta(hours=1),
    )


def _review(*, suppressed: bool, reason: str | None = None) -> MetaAgentReview:
    return MetaAgentReview(
        mode=MetaAgentMode.VETO,
        called=True,
        approved=not suppressed,
        prompt_version="v1",
        prompt_hash="sha256:fixture",
        rationale="fixture rationale",
        suppressed_order=suppressed,
        suppression_reason=reason,
    )


# --- classification: one test per path -------------------------------------


def test_stale_tick_stops_at_market_data_as_no_opportunity() -> None:
    result = RuntimeResult(
        tick=_tick(age_seconds=30),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=False, rejection_reasons=["stale_primary_tick"]
        ),
    )
    observation = classify(result, now=NOW)
    assert observation.stage is FunnelStage.CYCLE
    assert observation.gate is BlockingGate.MARKET_DATA
    assert observation.category is FunnelCategory.NO_OPPORTUNITY
    assert observation.reasons == ["stale_primary_tick"]
    assert observation.tick_age_seconds == 30.0


def test_missing_reference_price_is_market_data_gate() -> None:
    result = RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=False, rejection_reasons=["no_independent_reference_price"]
        ),
    )
    observation = classify(result)
    assert observation.gate is BlockingGate.MARKET_DATA
    assert observation.tick_age_seconds is None  # no wall clock supplied


def test_stale_candles_stop_at_candle_history_before_the_signal_stage() -> None:
    result = RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            rejection_reasons=["stale_candle_history"],
            pretrade_check=PreTradeCheck(passed=False, reasons=["stale_candle_history"]),
        ),
        candles_loaded=400,
        candle_last_opened_at=NOW - timedelta(hours=5),
    )
    observation = classify(result)
    assert observation.stage is FunnelStage.VALID_MARKET_DATA
    assert observation.gate is BlockingGate.CANDLE_HISTORY
    assert observation.category is FunnelCategory.NO_OPPORTUNITY
    assert observation.candle_age_seconds is not None and observation.candle_age_seconds > 4 * 3600


def test_missing_candle_history_is_candle_history_gate_without_a_check() -> None:
    result = RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True, rejection_reasons=["missing_candle_history"]
        ),
    )
    assert classify(result).gate is BlockingGate.CANDLE_HISTORY


def test_no_strategy_consensus_is_the_signal_gate_and_no_opportunity() -> None:
    result = RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            rejection_reasons=["no_strategy_consensus"],
            pretrade_check=PreTradeCheck(
                passed=False, reasons=["no_strategy_consensus"], candles_evaluated=400
            ),
        ),
    )
    observation = classify(result)
    assert observation.stage is FunnelStage.VALID_MARKET_DATA
    assert observation.gate is BlockingGate.SIGNAL
    assert observation.category is FunnelCategory.NO_OPPORTUNITY
    assert observation.reasons == ["no_strategy_consensus"]


def test_pretrade_backtest_rejection_is_an_opportunity_rejected() -> None:
    result = RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            rejection_reasons=["backtest_sharpe_below_minimum"],
            pretrade_check=PreTradeCheck(
                passed=False,
                reasons=["backtest_sharpe_below_minimum"],
                confirmed_side=Side.BUY,
                confidence=0.6,
            ),
        ),
    )
    observation = classify(result)
    assert observation.stage is FunnelStage.SIGNAL_CANDIDATE
    assert observation.gate is BlockingGate.PRETRADE
    assert observation.category is FunnelCategory.OPPORTUNITY_REJECTED


def test_adverse_news_is_an_intelligence_rejection_not_a_missing_signal() -> None:
    result = RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True, rejection_reasons=["adverse_news_event"]
        ),
    )
    observation = classify(result)
    assert observation.gate is BlockingGate.INTELLIGENCE
    assert observation.category is FunnelCategory.OPPORTUNITY_REJECTED


def test_promote_universe_exclusion_is_no_opportunity() -> None:
    result = RuntimeResult(
        tick=_tick("SOL/USD"),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True, rejection_reasons=["promote_universe_excluded"]
        ),
    )
    observation = classify(result)
    assert observation.gate is BlockingGate.UNIVERSE
    assert observation.category is FunnelCategory.NO_OPPORTUNITY


def test_risk_rejection_reaches_pretrade_eligible_and_names_the_risk_reasons() -> None:
    proposal = _proposal()
    result = RuntimeResult(
        tick=_tick(),
        references=[],
        pipeline=PipelineResult(
            accepted_market_data=True,
            proposal=proposal,
            risk_result=_risk(proposal, RiskDecision.REJECT, 0, "kill_switch_enabled"),
        ),
    )
    observation = classify(result)
    assert observation.stage is FunnelStage.PRETRADE_ELIGIBLE
    assert observation.gate is BlockingGate.RISK
    assert observation.category is FunnelCategory.OPPORTUNITY_REJECTED
    assert observation.reasons == ["kill_switch_enabled"]
    assert observation.strategy_id == "vertical-slice-v1"
    assert observation.decision_id == str(proposal.decision_id)


def test_meta_agent_veto_reaches_risk_allowed_and_stops_there() -> None:
    result = _allowed(
        paper_order=False,
        meta_review=_review(suppressed=True, reason=VETO_REASON),
        extra_rejections=[VETO_REASON],
    )
    observation = classify(result)
    assert observation.stage is FunnelStage.RISK_ALLOWED
    assert observation.gate is BlockingGate.META_AGENT
    assert observation.category is FunnelCategory.OPPORTUNITY_REJECTED
    assert observation.reasons == [VETO_REASON]
    assert observation.reason_text == "fixture rationale"


def test_meta_agent_unavailable_suppression_is_the_meta_agent_gate() -> None:
    result = _allowed(
        paper_order=False,
        meta_review=_review(suppressed=True, reason=UNAVAILABLE_REASON),
        extra_rejections=[UNAVAILABLE_REASON],
    )
    assert classify(result).reasons == [UNAVAILABLE_REASON]


def test_planner_rejection_reaches_meta_agent_retained() -> None:
    result = _allowed(status="plan_rejected", reason="quantity rounds to zero at lot step 0.001")
    observation = classify(result)
    assert observation.stage is FunnelStage.META_AGENT_RETAINED
    assert observation.gate is BlockingGate.PLANNER
    assert observation.category is FunnelCategory.OPPORTUNITY_REJECTED
    assert observation.reasons == ["plan_rejected"]
    assert observation.reason_text is not None and "lot step" in observation.reason_text


def test_withheld_paper_fill_is_fill_unavailable() -> None:
    result = _allowed(status="paper_fill_withheld", reason="kill switch engaged")
    observation = classify(result)
    assert observation.stage is FunnelStage.META_AGENT_RETAINED
    assert observation.gate is BlockingGate.FILL
    assert observation.category is FunnelCategory.FILL_UNAVAILABLE


def test_no_execution_path_at_all_is_fill_unavailable_with_an_explicit_reason() -> None:
    observation = classify(_allowed(status=None))
    assert observation.gate is BlockingGate.FILL
    assert observation.reasons == ["execution_not_attempted"]


def test_venue_submission_is_planner_accepted_but_pending() -> None:
    observation = classify(_allowed(status="submitted"))
    assert observation.stage is FunnelStage.PLANNER_ACCEPTED
    assert observation.gate is BlockingGate.FILL
    assert "venue_fill_pending" in observation.reasons


def test_paper_fill_is_the_filled_stage() -> None:
    observation = classify(_allowed(status="paper_filled"))
    assert observation.stage is FunnelStage.FILLED
    assert observation.gate is None
    assert observation.category is FunnelCategory.FILLED
    assert "filled" in observation.explain()


def test_exit_fill_is_flagged_as_an_exit() -> None:
    observation = classify(_allowed(exit_reason="exit_stop_loss", status="paper_filled"))
    assert observation.is_exit is True
    assert observation.stage is FunnelStage.FILLED


def test_ledger_filled_override_promotes_a_pending_submission() -> None:
    observation = classify(_allowed(status="submitted"), filled=True)
    assert observation.stage is FunnelStage.FILLED


# --- accumulation and diagnosis ------------------------------------------------


def test_zero_signal_run_names_the_dominant_gate_and_exact_counts() -> None:
    funnel = OpportunityFunnel(paper_fills_enabled=True, submission_enabled=False)
    for _ in range(5):
        funnel.observe(
            RuntimeResult(
                tick=_tick(),
                references=[],
                pipeline=PipelineResult(
                    accepted_market_data=True,
                    rejection_reasons=["no_strategy_consensus"],
                    pretrade_check=PreTradeCheck(passed=False, reasons=["no_strategy_consensus"]),
                ),
            ),
            now=NOW,
        )
    funnel.observe(
        RuntimeResult(
            tick=_tick(age_seconds=40),
            references=[],
            pipeline=PipelineResult(
                accepted_market_data=False, rejection_reasons=["stale_primary_tick"]
            ),
        ),
        now=NOW,
    )
    report = funnel.snapshot()

    assert report.totals.stage_count(FunnelStage.CYCLE) == 6
    assert report.totals.stage_count(FunnelStage.VALID_MARKET_DATA) == 5
    assert report.totals.stage_count(FunnelStage.SIGNAL_CANDIDATE) == 0
    assert report.totals.stage_count(FunnelStage.FILLED) == 0
    assert report.totals.blocked_by_gate == {"signal": 5, "market_data": 1}
    assert report.reasons_by_gate == {
        "signal": {"no_strategy_consensus": 5},
        "market_data": {"stale_primary_tick": 1},
    }
    assert report.totals.categories == {"no_opportunity": 6}
    assert report.diagnosis.dominant_gate == "signal"
    assert report.diagnosis.dominant_gate_count == 5
    assert report.diagnosis.dominant_reason == "no_strategy_consensus"
    assert report.diagnosis.category == "no_opportunity"
    assert "not a safety rejection" in report.diagnosis.verdict
    assert report.tick_age_seconds.max == 40.0
    assert report.first_observed_at is not None and report.last_observed_at is not None
    assert report.by_symbol["BTC/USD"].stage_count(FunnelStage.CYCLE) == 6
    assert report.by_strategy == {}  # nothing ever formed a proposal
    assert "no_strategy_consensus" in report.render()


def test_the_report_distinguishes_rejected_from_fill_unavailable_from_filled() -> None:
    funnel = OpportunityFunnel()
    funnel.observe(_allowed(status="paper_filled"))
    funnel.observe(_allowed(status="paper_fill_withheld", reason="reconciliation blocked"))
    funnel.observe(_allowed(status="plan_rejected", reason="below min notional"))
    funnel.observe(
        _allowed(
            paper_order=False,
            meta_review=_review(suppressed=True, reason=VETO_REASON),
            extra_rejections=[VETO_REASON],
        )
    )
    report = funnel.snapshot()
    assert report.totals.categories == {
        "filled": 1,
        "fill_unavailable": 1,
        "opportunity_rejected": 2,
    }
    assert report.totals.stage_count(FunnelStage.RISK_ALLOWED) == 4
    assert report.totals.stage_count(FunnelStage.META_AGENT_RETAINED) == 3
    assert report.totals.stage_count(FunnelStage.PLANNER_ACCEPTED) == 1
    assert report.totals.stage_count(FunnelStage.FILLED) == 1
    assert report.by_strategy["vertical-slice-v1"].stage_count(FunnelStage.FILLED) == 1
    assert report.execution_statuses == {
        "paper_filled": 1,
        "paper_fill_withheld": 1,
        "plan_rejected": 1,
    }
    assert report.reason_examples["planner"] == "below min notional"


def test_reason_maps_are_bounded() -> None:
    funnel = OpportunityFunnel()
    for index in range(MAX_REASON_KEYS + 10):
        funnel.observe(
            RuntimeResult(
                tick=_tick(),
                references=[],
                pipeline=PipelineResult(
                    accepted_market_data=False, rejection_reasons=[f"reason_{index}"]
                ),
            )
        )
    reasons = funnel.snapshot().reasons_by_gate["market_data"]
    assert len(reasons) == MAX_REASON_KEYS + 1
    assert reasons[OVERFLOW_KEY] == 10


def test_ledger_join_promotes_pending_venue_orders_to_fills() -> None:
    funnel = OpportunityFunnel()
    result = _allowed(status="submitted")
    funnel.observe(result)
    before = funnel.snapshot()
    assert before.pending_venue_decisions == 1
    assert before.totals.stage_count(FunnelStage.FILLED) == 0
    assert before.totals.categories == {"fill_unavailable": 1}

    decision_id = str(result.pipeline.proposal.decision_id)  # type: ignore[union-attr]
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="venue-1",
            decision_id=decision_id,
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.05,
            state=OrderLifecycleState.FILLED,
            filled_quantity=0.05,
            average_fill_price_usd=20_000,
        )
    )
    assert funnel.apply_ledger(ledger) == 1
    after = funnel.snapshot()
    assert after.pending_venue_decisions == 0
    assert after.totals.stage_count(FunnelStage.FILLED) == 1
    assert after.totals.categories == {"filled": 1}
    assert after.totals.blocked_by_gate == {}
    assert "fill" not in after.reasons_by_gate


def test_observe_with_a_ledger_sees_a_fill_on_the_same_cycle() -> None:
    result = _allowed(status="submitted")
    decision_id = str(result.pipeline.proposal.decision_id)  # type: ignore[union-attr]
    ledger = ExecutionLedger()
    ledger.register_order(
        ExecutionOrder(
            order_id="venue-1",
            decision_id=decision_id,
            asset="BTC",
            side=Side.BUY,
            requested_quantity=0.05,
            state=OrderLifecycleState.FILLED,
        )
    )
    observation = OpportunityFunnel().observe(result, ledger=ledger)
    assert observation.stage is FunnelStage.FILLED


def test_diagnose_on_an_empty_report() -> None:
    assert diagnose(OpportunityFunnelReport()).verdict == "no cycles observed"


def test_diagnostic_mode_verdict_says_withholding_was_by_design() -> None:
    funnel = OpportunityFunnel(diagnostic_mode=True)
    funnel.observe(_allowed(status="diagnostic_withheld", reason="diagnostic mode"))
    verdict = funnel.snapshot().diagnosis.verdict
    assert "diagnostic mode withheld" in verdict


# --- persistence and offline reconstruction ----------------------------------


def test_snapshot_round_trips_through_json(tmp_path: Path) -> None:
    funnel = OpportunityFunnel(paper_fills_enabled=True)
    funnel.observe(_allowed(status="paper_filled"), now=NOW)
    path = tmp_path / "ops" / "opportunity_funnel.json"
    funnel.write(path)
    restored = OpportunityFunnelReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert restored.model_dump() == funnel.snapshot().model_dump()
    assert restored.diagnosis.fills == 1


async def test_funnel_from_audit_rebuilds_the_run_and_joins_the_ledger(tmp_path: Path) -> None:
    audit = tmp_path / "audit" / "runtime.jsonl"
    sink = JsonlAuditSink(audit)
    submitted = _allowed(status="submitted")
    await sink(
        RuntimeResult(
            tick=_tick(),
            references=[],
            pipeline=PipelineResult(
                accepted_market_data=False, rejection_reasons=["stale_primary_tick"]
            ),
        )
    )
    await sink(_allowed(status="paper_filled"))
    await sink(submitted)
    audit.open("a", encoding="utf-8").write("{torn")  # a killed-mid-write tail

    decision_id = str(submitted.pipeline.proposal.decision_id)  # type: ignore[union-attr]
    ledger_path = tmp_path / "state" / "execution_ledger.json"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(
        ExecutionLedgerState(
            orders={
                "venue-1": ExecutionOrder(
                    order_id="venue-1",
                    decision_id=decision_id,
                    asset="BTC",
                    side=Side.BUY,
                    requested_quantity=0.05,
                    state=OrderLifecycleState.FILLED,
                )
            }
        ).model_dump_json(),
        encoding="utf-8",
    )

    funnel = funnel_from_audit(
        audit,
        ledger=ExecutionLedger.from_state(
            ExecutionLedgerState.model_validate_json(ledger_path.read_text(encoding="utf-8"))
        ),
    )
    report = funnel.snapshot()
    assert funnel.skipped_lines == 1
    assert report.totals.stage_count(FunnelStage.CYCLE) == 3
    assert report.totals.stage_count(FunnelStage.FILLED) == 2
    assert report.totals.blocked_by_gate == {"market_data": 1}
    assert report.paper_fills_enabled is True
    assert report.submission_enabled is True
    assert report.tick_age_seconds.samples == 0  # wall clock is not in the audit trail
    assert report.candle_age_seconds.samples == 2

    output = tmp_path / "funnel.json"
    code = funnel_main(
        [
            "--audit-path",
            str(audit),
            "--ledger-path",
            str(ledger_path),
            "--json",
            "--output",
            str(output),
        ]
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["totals"]["stages"]["filled"] == 2


def test_funnel_cli_reports_a_missing_audit_trail(tmp_path: Path, capsys) -> None:
    assert funnel_main(["--audit-path", str(tmp_path / "missing.jsonl")]) == 2
    assert "no runtime audit trail" in capsys.readouterr().out


# --- on-chain regime gate (#139) ---


def test_onchain_regime_rejection_is_a_policy_withhold_after_a_side_existed() -> None:
    for reason in ("onchain_regime_blocked", "onchain_regime_unavailable"):
        check = PreTradeCheck(passed=True, confirmed_side=Side.BUY, reasons=[], confidence=0.6)
        result = RuntimeResult(
            tick=_tick(),
            references=[],
            pipeline=PipelineResult(
                accepted_market_data=True, rejection_reasons=[reason], pretrade_check=check
            ),
            candles_loaded=720,
        )
        observation = classify(result)
        assert observation.stage is FunnelStage.SIGNAL_CANDIDATE, reason
        assert observation.gate is BlockingGate.INTELLIGENCE, reason
        assert observation.category is FunnelCategory.OPPORTUNITY_REJECTED, reason
        assert observation.reasons == [reason]
        # Without a pre-trade gate the default BUY path lands on the same gate.
        bare = RuntimeResult(
            tick=_tick(),
            references=[],
            pipeline=PipelineResult(accepted_market_data=True, rejection_reasons=[reason]),
        )
        assert classify(bare).gate is BlockingGate.INTELLIGENCE, reason
        assert classify(bare).stage is FunnelStage.SIGNAL_CANDIDATE, reason
