from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from traderstack.polymarket.wallet_signal_eval import ScoredSignal
from traderstack.polymarket.world_context_eval import (
    CONTEXT_IDS,
    _is_preregistered_contract,
    bootstrap_incremental_mean,
    build_global_trial_sharpes,
    build_parser,
    context_matches,
    evaluate_context_grid,
)
from traderstack.polymarket.world_signal_fusion import FusedSignalContext, ProviderContext


def _context(
    signal_at: datetime,
    payload: dict[str, object],
) -> FusedSignalContext:
    return FusedSignalContext(
        hypothesis="top3_follow",
        wallet="0x" + "1" * 40,
        token_id="token",
        condition_id="condition",
        signal_at=signal_at,
        title="Will Bitcoin be above $100k?",
        outcome="Yes",
        provider_context=(
            ProviderContext(
                source_id="canonical:test",
                asset="BTC",
                observed_at=signal_at - timedelta(minutes=5),
                age_seconds=300,
                payload=payload,
            ),
        ),
    )


def _signal(
    trade_at: datetime,
    pnl: float,
    *,
    hypothesis: str = "top3_follow",
) -> ScoredSignal:
    return ScoredSignal(
        hypothesis=hypothesis,  # type: ignore[arg-type]
        wallet="0x" + "1" * 40,
        token_id="token",
        condition_id="condition",
        trade_at=trade_at,
        cohort_snapshot_at=trade_at - timedelta(hours=1),
        copy_delay_seconds=60,
        hold_seconds=86400,
        cost_bps_per_side=25.0,
        copied_notional_usd=10.0,
        entry_timestamp=int(trade_at.timestamp()) + 60,
        entry_price=0.5,
        exit_timestamp=int(trade_at.timestamp()) + 86460,
        exit_price=0.6,
        gross_pnl_usd=pnl + 0.1,
        cost_usd=0.1,
        net_pnl_usd=pnl,
        direction=1,
        title="Will Bitcoin be above $100k?",
        outcome="Yes",
    )


def test_context_catalog_thresholds_are_frozen_and_missing_is_not_zero() -> None:
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    context = _context(
        now,
        {
            "news": {"adverse_event": True, "event_score": 0.7},
            "narrative": {"mention_velocity_z": -1.2, "sentiment": 0.6},
            "onchain": {
                "exchange_netflow_z": -1.6,
                "large_wallet_accumulation": 0.55,
            },
            "market": {"external_signal_score": -0.6},
            "edge": {"liq_notional_long_z": 1.6, "liq_notional_short_z": None},
        },
    )

    assert all(context_matches(context, context_id) for context_id in CONTEXT_IDS)
    assert not context_matches(None, "context_available")
    assert not context_matches(
        _context(now, {"news": {}, "narrative": {}, "onchain": {}, "market": {}, "edge": {}}),
        "news_event_high",
    )


def test_incremental_bootstrap_resamples_baseline_and_subset_together() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    baseline = [_signal(start + timedelta(hours=index), float(index)) for index in range(1, 7)]
    matches = [False, False, False, True, True, True]

    first = bootstrap_incremental_mean(baseline, matches, iterations=200, seed=135)
    second = bootstrap_incremental_mean(baseline, matches, iterations=200, seed=135)

    assert first == second
    assert first.computed
    assert first.point is not None and first.point > 0


def test_context_evaluation_uses_baseline_chronology_for_holdout() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    scored = [_signal(start + timedelta(hours=index), pnl=float(index - 4)) for index in range(10)]
    contexts = [
        _context(
            row.trade_at,
            {
                "news": {
                    "adverse_event": row.trade_at >= start + timedelta(hours=7),
                    "event_score": 0.8 if row.trade_at >= start + timedelta(hours=7) else 0.0,
                },
                "narrative": {},
                "onchain": {},
                "market": {},
                "edge": {},
            },
        )
        for row in scored
    ]

    cells = evaluate_context_grid(
        scored,
        contexts,
        holdout_fraction=0.30,
        discovery_min=2,
        holdout_min=1,
    )
    baseline_discovery = next(
        cell
        for cell in cells
        if cell.hypothesis == "top3_follow"
        and cell.context_id == "baseline_all"
        and cell.split == "discovery"
    )
    adverse_holdout = next(
        cell
        for cell in cells
        if cell.hypothesis == "top3_follow"
        and cell.context_id == "news_adverse"
        and cell.split == "holdout"
    )

    assert baseline_discovery.signals == 7
    assert adverse_holdout.baseline_signals == 3
    assert adverse_holdout.signals == 3
    assert adverse_holdout.sample_bar_met
    assert adverse_holdout.incremental_mean_net_pnl_usd == pytest.approx(0.0)


def test_sparse_context_cell_is_explicitly_insufficient() -> None:
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    scored = [_signal(now, 1.0)]
    contexts = [_context(now, {"news": {"adverse_event": True}})]

    cells = evaluate_context_grid(scored, contexts)
    cell = next(
        item
        for item in cells
        if item.hypothesis == "top3_follow"
        and item.context_id == "news_adverse"
        and item.split == "discovery"
    )

    assert not cell.sample_bar_met
    assert cell.deflated_sharpe["computed"] is False
    assert cell.deflated_sharpe["skipped_reason"] == "minimum_signal_count_not_met"


def test_dsr_catalog_uses_all_270_frozen_logical_trials() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    payload = {
        "news": {"adverse_event": True, "event_score": 0.7},
        "narrative": {"mention_velocity_z": 1.2, "sentiment": 0.6},
        "onchain": {
            "exchange_netflow_z": 1.6,
            "large_wallet_accumulation": 0.55,
        },
        "market": {"external_signal_score": 0.6},
        "edge": {"liq_notional_long_z": 1.6, "liq_notional_short_z": 0.0},
    }
    pnls = (-1.0, 0.5, 1.0, 2.0)
    scored = [
        _signal(
            start + timedelta(hours=index),
            pnl,
            hypothesis=hypothesis,
        )
        for hypothesis in ("persistent_top10_follow", "top3_follow", "persistent_top10_fade")
        for index, pnl in enumerate(pnls)
    ]
    contexts = [
        replace(
            _context(row.trade_at, payload),
            hypothesis=row.hypothesis,
        )
        for row in scored
    ]

    catalogs = build_global_trial_sharpes(
        [scored] * 9,
        contexts,
        holdout_fraction=0.30,
        discovery_min=1,
        holdout_min=1,
    )

    assert all(values is not None and len(values) == 270 for values in catalogs.values())

    cells = evaluate_context_grid(
        scored,
        contexts,
        holdout_fraction=0.30,
        discovery_min=1,
        holdout_min=1,
        global_trial_sharpes=catalogs,
        catalog_trial_count=270,
    )
    cell = next(
        item
        for item in cells
        if item.hypothesis == "top3_follow"
        and item.context_id == "baseline_all"
        and item.split == "holdout"
    )

    assert cell.deflated_sharpe["trials"] == 270
    assert cell.deflated_sharpe["skipped_reason"] == "trial_sharpes_have_no_dispersion"


def test_global_dsr_is_withheld_when_any_frozen_trial_lacks_support() -> None:
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    scored = [_signal(now, 1.0)]
    contexts = [_context(now, {"news": {"adverse_event": True}})]

    catalogs = build_global_trial_sharpes(
        [scored] * 9,
        contexts,
        discovery_min=1,
        holdout_min=1,
    )

    assert catalogs == {"discovery": None, "holdout": None, "all": None}

    cells = evaluate_context_grid(
        scored,
        contexts,
        discovery_min=1,
        holdout_min=1,
        global_trial_sharpes=catalogs,
        catalog_trial_count=270,
    )
    cell = next(
        item
        for item in cells
        if item.hypothesis == "top3_follow"
        and item.context_id == "baseline_all"
        and item.split == "discovery"
    )

    assert cell.sample_bar_met
    assert cell.deflated_sharpe["computed"] is False
    assert cell.deflated_sharpe["trials"] == 270
    assert cell.deflated_sharpe["skipped_reason"] == "global_catalog_sample_support_incomplete"


def test_cli_overrides_are_not_mislabeled_as_preregistered() -> None:
    parser = build_parser()

    assert _is_preregistered_contract(parser.parse_args([]))
    assert not _is_preregistered_contract(parser.parse_args(["--copy-delays", "60"]))
    assert not _is_preregistered_contract(parser.parse_args(["--cost-bps", "25"]))
    assert not _is_preregistered_contract(parser.parse_args(["--warehouse-limit", "1000"]))


def test_non_preregistered_run_cannot_emit_dsr() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    payload = {
        "news": {"adverse_event": True, "event_score": 0.7},
        "narrative": {"mention_velocity_z": 1.2, "sentiment": 0.6},
        "onchain": {
            "exchange_netflow_z": 1.6,
            "large_wallet_accumulation": 0.55,
        },
        "market": {"external_signal_score": 0.6},
        "edge": {"liq_notional_long_z": 1.6, "liq_notional_short_z": 0.0},
    }
    scored = [
        _signal(start + timedelta(hours=index), pnl)
        for index, pnl in enumerate((-1.0, 0.5, 1.0, 2.0))
    ]
    contexts = [_context(row.trade_at, payload) for row in scored]
    trial_catalog = tuple(float(index) / 100.0 for index in range(270))

    cells = evaluate_context_grid(
        scored,
        contexts,
        discovery_min=1,
        holdout_min=1,
        global_trial_sharpes={
            "discovery": trial_catalog,
            "holdout": trial_catalog,
            "all": trial_catalog,
        },
        catalog_trial_count=270,
        dsr_skip_reason="non_preregistered_parameters",
    )
    cell = next(
        item
        for item in cells
        if item.hypothesis == "top3_follow"
        and item.context_id == "baseline_all"
        and item.split == "holdout"
    )

    assert cell.deflated_sharpe["computed"] is False
    assert cell.deflated_sharpe["trials"] == 270
    assert cell.deflated_sharpe["skipped_reason"] == "non_preregistered_parameters"


def test_unknown_context_id_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown context_id"):
        context_matches(None, "made_up")
