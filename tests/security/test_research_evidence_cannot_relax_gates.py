"""The #135 evidence layer can only withhold a promotion, never create one.

Thresholds are module constants (not ``Settings``), the ranking key and
selection rule are untouched, ``PAPER_PROMOTE_*`` defaults stay false, and
the numbers are deterministic. A raw dual-print / combined passer whose
evidence fails is still shown as a raw pass but gets no recommended flag.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research import dual_print_search, harder_gates
from traderstack.research.daily_candidates import default_expanded_harder_gates_candidates
from traderstack.research.daily_robustness import KRAKEN_DAILY_CAP_NOTE
from traderstack.research.dual_print_search import (
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
    rank_dual_print_passers,
    run_dual_print_search,
)
from traderstack.research.evidence import (
    DSR_MIN,
    EVIDENCE_SEED,
    PBO_MAX,
    CandidateEvidence,
    CatalogEvidence,
)
from traderstack.research.harder_gates import (
    HARDER_GATES_NOTE,
    CandidateHarderResult,
    HarderGatesReport,
    paper_promote_flag_name,
    run_harder_gates,
)
from traderstack.research.harder_gates import RANKING_KEY as HARDER_RANKING_KEY
from traderstack.research.harder_gates import SELECTION_RULE as HARDER_SELECTION_RULE


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
    )


def _candles(count: int, *, symbol: str, start: datetime, slope: float) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    prices = [200.0 + slope * index for index in range(count)]
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                opened_at=start + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def _catalog() -> tuple:
    return tuple(
        item
        for item in default_expanded_harder_gates_candidates()
        if item.candidate_id in {"ema_9_21", "ema_9_21_adx15"}
    )


def _fake_evidence(
    candidate_ids: list[str], *, passing: set[str], trial_count: int
) -> CatalogEvidence:
    return CatalogEvidence(
        trial_count=trial_count,
        candidates=[
            CandidateEvidence(
                candidate_id=candidate_id,
                evidence_pass=candidate_id in passing,
                reasons=[] if candidate_id in passing else ["BTC/USD:pbo_above_max"],
            )
            for candidate_id in candidate_ids
        ],
        evidence_passer_ids=[item for item in candidate_ids if item in passing],
    )


def _fake_harder_report(rows: list[CandidateHarderResult]) -> HarderGatesReport:
    """A HarderGatesReport whose ranking/promotion already ran (raw pass shown)."""
    return HarderGatesReport(
        generated_at=datetime(2026, 9, 13, tzinfo=UTC),
        symbols=["BTC/USD", "ETH/USD"],
        intervals=["1d"],
        fee_bps=10.0,
        slippage_bps=5.0,
        fee_stress_fee_bps=20.0,
        fee_stress_slippage_bps=10.0,
        cost_note="test",
        starting_equity=10_000.0,
        train_size=80,
        test_size=40,
        step_size=40,
        holdout_fraction=0.2,
        min_trades=1,
        selection_rule=HARDER_SELECTION_RULE,
        magnitude_ratio_min=0.25,
        multiwindow_count=3,
        multiwindow_bars=240,
        multiwindow_min_passes=2,
        fee_stress_multiplier=2.0,
        ranking_key=HARDER_RANKING_KEY,
        catalog_name="custom",
        catalog_note="test",
        kraken_cap_note=KRAKEN_DAILY_CAP_NOTE,
        gates_note=HARDER_GATES_NOTE,
        candidates=rows,
        honesty="test",
    )


def _harder_row(candidate_id: str, *, combined: bool, evidence_pass: bool) -> CandidateHarderResult:
    return CandidateHarderResult(
        candidate_id=candidate_id,
        family="ema_cross",
        label=candidate_id,
        combined=combined,
        combined_rank=1 if combined else None,
        selected=combined,
        promoted=combined and evidence_pass,
        mean_holdout_excess=0.10,
        baseline_btc_holdout=0.10,
        baseline_eth_holdout=0.10,
        evidence=CandidateEvidence(
            candidate_id=candidate_id,
            evidence_pass=evidence_pass,
            reasons=[] if evidence_pass else ["ETH/USD:dsr_not_passed"],
        ),
        evidence_pass=evidence_pass,
    )


def test_thresholds_are_not_settings_fields() -> None:
    names = set(Settings.model_fields)
    for token in ("dsr", "pbo", "bootstrap", "evidence", "era_window"):
        assert not any(token in name.lower() for name in names), token
    assert DSR_MIN == 0.95
    assert PBO_MAX == 0.50
    assert EVIDENCE_SEED == 20260913


def test_promote_defaults_stay_false_and_no_new_pin() -> None:
    cfg = _settings()
    assert cfg.paper_promote_ema_9_21 is False
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.paper_promote_searched_strategies is False
    assert cfg.paper_garch_size is False
    assert not hasattr(cfg, "paper_promote_evidence")
    assert cfg.trading_mode == "paper"


def test_ranking_and_selection_rules_are_unchanged() -> None:
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert HARDER_RANKING_KEY == "mean_holdout_excess_among_combined_passers"
    assert HARDER_SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_combined_passers"


def test_non_dual_print_row_is_never_evidence_selected() -> None:
    rows = [
        DualPrintRow(
            candidate_id="kraken_only_with_evidence",
            family="ema_cross",
            label="x",
            kraken_combined=True,
            binance_combined=False,
            dual_print=False,
            kraken_mean_holdout_excess=0.5,
            evidence_pass=True,
        ),
        DualPrintRow(
            candidate_id="dual_without_evidence",
            family="ema_cross",
            label="y",
            kraken_combined=True,
            binance_combined=True,
            dual_print=True,
            kraken_mean_holdout_excess=0.1,
            evidence_pass=False,
        ),
    ]
    passers = rank_dual_print_passers(rows)
    assert [row.candidate_id for row in passers] == ["dual_without_evidence"]
    assert passers[0].selected is True
    assert passers[0].evidence_selected is False
    assert rows[0].evidence_selected is False
    assert dual_print_search.evidence_selected_row(passers) is None
    assert dual_print_search.evidence_passer_ids_of(passers) == []


def test_evidence_selected_never_reorders_ranking() -> None:
    rows = [
        DualPrintRow(
            candidate_id="top_raw_no_evidence",
            family="f",
            label="a",
            kraken_combined=True,
            binance_combined=True,
            dual_print=True,
            kraken_mean_holdout_excess=0.30,
            evidence_pass=False,
        ),
        DualPrintRow(
            candidate_id="second_raw_with_evidence",
            family="f",
            label="b",
            kraken_combined=True,
            binance_combined=True,
            dual_print=True,
            kraken_mean_holdout_excess=0.20,
            evidence_pass=True,
        ),
    ]
    passers = rank_dual_print_passers(rows)
    assert [row.candidate_id for row in passers] == [
        "top_raw_no_evidence",
        "second_raw_with_evidence",
    ]
    assert passers[0].selected is True and passers[0].evidence_selected is False
    assert passers[1].selected is False and passers[1].evidence_selected is True
    ids = dual_print_search.evidence_passer_ids_of(passers)
    assert ids == ["second_raw_with_evidence"]
    assert set(ids) <= {row.candidate_id for row in passers}


def test_raw_dual_print_top1_failing_evidence_withholds_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    ids = [item.candidate_id for item in catalog]

    def fake_run_harder_gates(histories, **kwargs):  # type: ignore[no-untyped-def]
        return _fake_harder_report(
            [_harder_row(candidate_id, combined=True, evidence_pass=False) for candidate_id in ids]
        )

    monkeypatch.setattr(dual_print_search, "run_harder_gates", fake_run_harder_gates)
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    report = run_dual_print_search(
        {
            "BTC/USD@1d": _candles(720, symbol="BTC/USD", start=primary, slope=-0.25),
            "ETH/USD@1d": _candles(720, symbol="ETH/USD", start=primary, slope=-0.25),
        },
        {
            "BTCUSDT@1d": _candles(720, symbol="BTCUSDT", start=older, slope=-0.25),
            "ETHUSDT@1d": _candles(720, symbol="ETHUSDT", start=older, slope=-0.25),
        },
        fee_bps=10.0,
        candidates=catalog,
        binance_source="binance_us_spot",
    )
    assert report.binance_slice.available is True
    assert report.dual_print_passer_ids == sorted(ids)
    assert report.selected_candidate_id == min(ids)
    assert report.any_dual_print_passer is True
    # raw pass is still shown; evidence withholds the recommendation
    assert report.evidence_passer_ids == []
    assert report.evidence_selected_candidate_id is None
    assert report.recommended_promote_flag is None
    assert "recommended promote flag is withheld" in report.honesty
    assert all(row.evidence_selected is False for row in report.rows)
    assert _settings().paper_promote_ema_9_21 is False


def test_evidence_passers_are_subset_of_dual_print_passers(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog()
    ids = [item.candidate_id for item in catalog]
    passing = {"ema_9_21_adx15"}

    def fake_run_harder_gates(histories, **kwargs):  # type: ignore[no-untyped-def]
        return _fake_harder_report(
            [
                _harder_row(candidate_id, combined=True, evidence_pass=candidate_id in passing)
                for candidate_id in ids
            ]
        )

    monkeypatch.setattr(dual_print_search, "run_harder_gates", fake_run_harder_gates)
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    report = run_dual_print_search(
        {
            "BTC/USD@1d": _candles(720, symbol="BTC/USD", start=primary, slope=-0.25),
            "ETH/USD@1d": _candles(720, symbol="ETH/USD", start=primary, slope=-0.25),
        },
        {
            "BTCUSDT@1d": _candles(720, symbol="BTCUSDT", start=older, slope=-0.25),
            "ETHUSDT@1d": _candles(720, symbol="ETHUSDT", start=older, slope=-0.25),
        },
        fee_bps=10.0,
        candidates=catalog,
        binance_source="binance_us_spot",
    )
    assert set(report.evidence_passer_ids) <= set(report.dual_print_passer_ids)
    assert report.evidence_passer_ids == ["ema_9_21_adx15"]
    # raw top-1 (tie-break on id) is still ema_9_21; the flag follows the evidence
    assert report.selected_candidate_id == "ema_9_21"
    assert report.evidence_selected_candidate_id == "ema_9_21_adx15"
    assert report.recommended_promote_flag == paper_promote_flag_name("ema_9_21_adx15")
    # a recommendation is a documented paper-only name; nothing flips
    assert _settings().paper_promote_ema_9_21_adx15 is False


def test_run_harder_gates_unpromotes_a_combined_passer_whose_evidence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    ids = [item.candidate_id for item in catalog]

    def fake_apply(rows: list[CandidateHarderResult]) -> CandidateHarderResult | None:
        for row in rows:
            row.selected = False
            row.promoted = False
        winner = rows[0]
        winner.combined = True
        winner.combined_rank = 1
        winner.rank = 1
        winner.selected = True
        winner.promoted = True
        return winner

    monkeypatch.setattr(harder_gates, "apply_combined_promotion", fake_apply)
    monkeypatch.setattr(
        harder_gates,
        "evaluate_catalog_evidence",
        lambda report, **kwargs: _fake_evidence(ids, passing=set(), trial_count=len(ids)),
    )
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = run_harder_gates(
        {
            "BTC/USD@1d": _candles(720, symbol="BTC/USD", start=start, slope=-0.25),
            "ETH/USD@1d": _candles(720, symbol="ETH/USD", start=start, slope=-0.25),
        },
        fee_bps=10.0,
        train_size=80,
        test_size=40,
        step_size=40,
        min_trades=1,
        candidates=catalog,
    )
    winner = report.candidates[0]
    assert winner.selected is True
    assert winner.combined is True
    assert winner.promoted is False
    assert winner.evidence_pass is False
    assert report.selected_candidate_id == winner.candidate_id
    assert winner.candidate_id in report.combined_passer_ids
    assert report.promoted_candidate_ids == []
    assert report.recommended_promote_flag is None
    assert report.any_promoted is False
    assert report.evidence_passer_ids == []
    assert "withheld promotion" in report.honesty


def test_evidence_cannot_promote_a_non_passer(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog()
    ids = [item.candidate_id for item in catalog]
    monkeypatch.setattr(
        harder_gates,
        "evaluate_catalog_evidence",
        lambda report, **kwargs: _fake_evidence(ids, passing=set(ids), trial_count=len(ids)),
    )
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = run_harder_gates(
        {
            "BTC/USD@1d": _candles(720, symbol="BTC/USD", start=start, slope=-0.25),
            "ETH/USD@1d": _candles(720, symbol="ETH/USD", start=start, slope=-0.25),
        },
        fee_bps=10.0,
        train_size=80,
        test_size=40,
        step_size=40,
        min_trades=1,
        candidates=catalog,
    )
    for row in report.candidates:
        assert row.evidence_pass is True
        if not row.combined:
            assert row.promoted is False
    assert report.evidence_passer_ids == [
        row.candidate_id for row in report.candidates if row.combined
    ]
    if not report.combined_passer_ids:
        assert report.promoted_candidate_ids == []
        assert report.recommended_promote_flag is None


def test_two_runs_produce_identical_evidence_json() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    histories = {
        "BTC/USD@1d": _candles(400, symbol="BTC/USD", start=start, slope=0.5),
        "ETH/USD@1d": _candles(400, symbol="ETH/USD", start=start, slope=-0.25),
    }
    kwargs = {
        "fee_bps": 10.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "min_trades": 1,
        "candidates": _catalog(),
        "now": datetime(2026, 9, 13, tzinfo=UTC),
    }
    first = run_harder_gates(histories, **kwargs)  # type: ignore[arg-type]
    second = run_harder_gates(histories, **kwargs)  # type: ignore[arg-type]
    assert first.evidence is not None and second.evidence is not None
    assert first.evidence.model_dump_json() == second.evidence.model_dump_json()
    assert first.evidence.seed == EVIDENCE_SEED
