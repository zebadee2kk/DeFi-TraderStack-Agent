from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.models import Side
from traderstack.research.daily_candidates import (
    DUAL_PRINT_SEARCH_CORE_IDS,
    DUAL_PRINT_SEARCH_OVERLAY_IDS,
    EXPANDED_HARDER_GATES_CORE_IDS,
    VolRegimeAgreeStrategy,
    default_dual_print_search_candidates,
    default_expanded_harder_gates_candidates,
)
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    DUAL_PRINT_RULES,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
    rank_dual_print_passers,
    render_dual_print_markdown,
    run_dual_print_search,
)
from traderstack.research.dual_print_search_cli import build_parser, run
from traderstack.research.miles_candidates import EmaCrossoverStrategy
from traderstack.research.second_print import DOCUMENTED_PRIMARY_FIRST_ISO, SECOND_PRINT_BARS
from traderstack.strategies import Regime


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def make_candles(
    prices: list[float],
    *,
    symbol: str = "BTC/USD",
    interval: str = "1d",
    start: datetime | None = None,
) -> tuple[Candle, ...]:
    opened = start or datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, price in enumerate(prices):
        previous = prices[index - 1] if index else price
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                opened_at=opened + timedelta(days=index),
                open=previous,
                high=max(previous, price) * 1.002,
                low=min(previous, price) * 0.998,
                close=price,
                volume=1_000 + index,
            )
        )
    return tuple(candles)


def downtrend(
    count: int, *, symbol: str = "BTC/USD", start: datetime | None = None
) -> tuple[Candle, ...]:
    return make_candles(
        [200.0 - 0.25 * index for index in range(count)], symbol=symbol, start=start
    )


def write_candles(path: Path, candles: tuple[Candle, ...]) -> None:
    path.write_text(json.dumps([candle.model_dump(mode="json") for candle in candles]))


def _tiny_catalog():
    return tuple(
        item
        for item in default_expanded_harder_gates_candidates()
        if item.candidate_id in {"ema_9_21", "ema_9_21_adx15"}
    )


def _search(
    kraken: dict[str, tuple[Candle, ...]],
    binance: dict[str, tuple[Candle, ...]] | None = None,
    **overrides: object,
):
    kwargs: dict[str, object] = {
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "train_size": 80,
        "test_size": 40,
        "step_size": 40,
        "holdout_fraction": 0.2,
        "min_trades": 1,
        "candidates": _tiny_catalog(),
    }
    kwargs.update(overrides)
    return run_dual_print_search(kraken, binance, **kwargs)  # type: ignore[arg-type]


def _row(
    candidate_id: str,
    *,
    kraken_combined: bool,
    binance_combined: bool,
    kraken_ho: float | None,
    binance_ho: float | None = None,
) -> DualPrintRow:
    return DualPrintRow(
        candidate_id=candidate_id,
        family="ema_cross",
        label=candidate_id,
        kraken_combined=kraken_combined,
        binance_combined=binance_combined,
        dual_print=kraken_combined and binance_combined,
        kraken_mean_holdout_excess=kraken_ho,
        binance_mean_holdout_excess=binance_ho,
    )


def test_promote_defaults_stay_false() -> None:
    cfg = settings()
    assert cfg.paper_promote_ema_9_21 is False
    assert cfg.paper_promote_ema_9_21_adx15 is False
    assert cfg.paper_promote_searched_strategies is False
    assert cfg.paper_garch_size is False
    assert not hasattr(cfg, "paper_promote_dual_print")


def test_dual_print_bar_is_frozen_before_scoring() -> None:
    assert MULTI_VENUE_BAR_PREREGISTERED is True
    assert CAN_AVERAGE_VENUES is False
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert RANKING_KEY == "mean_holdout_excess_among_dual_print_passers"
    assert SELECTION_RULE == "pre_registered_top1_mean_holdout_excess_among_dual_print_passers"
    assert RANKING_KEY in DUAL_PRINT_RULES
    assert "MULTI_VENUE_BAR_PREREGISTERED=true" in DUAL_PRINT_RULES
    assert "CAN_AVERAGE_VENUES=false" in DUAL_PRINT_RULES
    assert SECOND_PRINT_BARS == 720
    assert DOCUMENTED_PRIMARY_FIRST_ISO == "2024-09-22T00:00:00+00:00"


def test_dual_print_catalog_is_frozen_superset_of_99() -> None:
    catalog = default_dual_print_search_candidates()
    ids = [item.candidate_id for item in catalog]
    assert ids == list(DUAL_PRINT_SEARCH_CORE_IDS)
    assert len(ids) == len(set(ids))
    assert len(ids) == 65
    assert list(EXPANDED_HARDER_GATES_CORE_IDS) == ids[: len(EXPANDED_HARDER_GATES_CORE_IDS)]
    for extra in (
        "ema_6_19",
        "ema_10_30",
        "ema_15_45",
        "ema_21_63",
        "ema_9_21_adx12",
        "ema_9_21_ma100_riskoff",
        "dual_mom_8_40",
        "dip_mr_30_1_5_vol",
        "ema_9_21_vol_regime",
        "ema_12_26_vol_regime",
    ):
        assert extra in ids
    overlay = default_dual_print_search_candidates(btc_overlay=downtrend(220, symbol="BTC/USD"))
    overlay_ids = [item.candidate_id for item in overlay]
    assert overlay_ids == list(DUAL_PRINT_SEARCH_CORE_IDS + DUAL_PRINT_SEARCH_OVERLAY_IDS)
    assert len(overlay_ids) == 70
    assert "ema_8_21_btc_ma200_riskoff" in overlay_ids
    families = {item.family for item in catalog}
    assert "ema_cross_vol_regime" in families


def test_ranking_uses_kraken_holdout_among_dual_print_passers() -> None:
    rows = [
        _row(
            "kraken_only",
            kraken_combined=True,
            binance_combined=False,
            kraken_ho=0.40,
            binance_ho=-0.10,
        ),
        _row(
            "dual_low_kraken_high_binance",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.08,
            binance_ho=0.50,
        ),
        _row(
            "dual_high_kraken",
            kraken_combined=True,
            binance_combined=True,
            kraken_ho=0.12,
            binance_ho=0.01,
        ),
        _row(
            "binance_only",
            kraken_combined=False,
            binance_combined=True,
            kraken_ho=0.30,
            binance_ho=0.40,
        ),
    ]
    passers = rank_dual_print_passers(rows)
    assert [row.candidate_id for row in passers] == [
        "dual_high_kraken",
        "dual_low_kraken_high_binance",
    ]
    assert passers[0].selected is True
    assert passers[0].can_promote is False
    assert passers[1].selected is False
    assert rows[0].selected is False
    assert rows[3].dual_print is False


def test_ranking_tie_breaks_on_candidate_id() -> None:
    rows = [
        _row("zeta", kraken_combined=True, binance_combined=True, kraken_ho=0.10),
        _row("alpha", kraken_combined=True, binance_combined=True, kraken_ho=0.10),
    ]
    passers = rank_dual_print_passers(rows)
    assert [row.candidate_id for row in passers] == ["alpha", "zeta"]


def test_empty_binance_is_success_and_cannot_promote() -> None:
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=start),
        },
        {},
    )
    assert report.binance_slice.available is False
    assert report.any_dual_print_passer is False
    assert report.selected_candidate_id is None
    assert report.recommended_promote_flag is None
    assert report.keep_flag_false is True
    assert report.multi_venue_bar_preregistered is True
    assert report.can_average_venues is False
    rendered = render_dual_print_markdown(report)
    assert "Keep every `PAPER_PROMOTE_*=false`" in rendered
    assert "Do not add a new promote flag" in rendered
    assert settings().paper_promote_ema_9_21_adx15 is False


def test_short_binance_slice_fails_closed() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2023, 1, 1, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=primary),
        },
        {
            "BTCUSDT@1d": downtrend(100, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(100, symbol="ETHUSDT", start=older),
        },
    )
    assert report.binance_slice.available is False
    assert "shorter than 720" in (report.binance_slice.fail_closed_reason or "")
    assert report.any_dual_print_passer is False
    assert report.keep_flag_false is True


def test_binance_series_on_or_after_primary_fails_closed() -> None:
    """Bars at/after the Kraken first open are dropped; leftover is too short."""
    start = datetime(2024, 9, 22, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=start),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=start),
        },
        {
            "BTCUSDT@1d": downtrend(720, symbol="BTCUSDT", start=start),
            "ETHUSDT@1d": downtrend(720, symbol="ETHUSDT", start=start),
        },
    )
    assert report.binance_slice.available is False
    reason = report.binance_slice.fail_closed_reason or ""
    assert "shorter than 720" in reason or "overlaps" in reason
    assert report.binance_slice.overlaps_primary_window is False
    assert report.any_dual_print_passer is False


def test_binance_older_slice_is_scored_and_and_gate_holds() -> None:
    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    report = _search(
        {
            "BTC/USD@1d": downtrend(720, symbol="BTC/USD", start=primary),
            "ETH/USD@1d": downtrend(720, symbol="ETH/USD", start=primary),
        },
        {
            "BTCUSDT@1d": downtrend(720, symbol="BTCUSDT", start=older),
            "ETHUSDT@1d": downtrend(720, symbol="ETHUSDT", start=older),
        },
        binance_source="binance_us_spot",
    )
    assert report.binance_slice.available is True
    assert report.binance_slice.overlaps_primary_window is False
    assert report.binance_slice.bars_btc == 720
    assert report.keep_flag_false is True
    assert all(row.can_promote is False for row in report.rows)
    for row in report.rows:
        expected = row.kraken_combined and row.binance_combined
        assert row.dual_print is expected
    rendered = render_dual_print_markdown(report)
    assert "Binance.US" in rendered
    assert "`keep_flag_false=true`" in rendered
    assert RANKING_KEY in rendered


def test_vol_regime_wrapper_flattens_on_disagree() -> None:
    inner = EmaCrossoverStrategy(strategy_id="ema_9_21_vol_regime", fast_span=9, slow_span=21)
    wrapper = VolRegimeAgreeStrategy(strategy_id="ema_9_21_vol_regime", inner=inner)
    candles = downtrend(40)
    raw = inner.evaluate(candles, Regime.TRENDING_DOWN)
    assert raw.side is Side.SELL
    agreed = wrapper.evaluate(candles, Regime.TRENDING_DOWN)
    assert agreed.side is Side.SELL
    disagreed = wrapper.evaluate(candles, Regime.TRENDING_UP)
    assert disagreed.side is None
    assert "vol-regime" in disagreed.rationale


def test_cli_defaults_and_writes(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--candles", "unused.json", "--no-binance"])
    assert args.output_md.name == "dual-print-search.md"

    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    btc_usdt = tmp_path / "btcusdt.json"
    eth_usdt = tmp_path / "ethusdt.json"
    write_candles(btc, downtrend(240, symbol="BTC/USD", start=primary))
    write_candles(eth, downtrend(240, symbol="ETH/USD", start=primary))
    write_candles(btc_usdt, downtrend(720, symbol="BTCUSDT", start=older))
    write_candles(eth_usdt, downtrend(720, symbol="ETHUSDT", start=older))
    out_json = tmp_path / "ops" / "dual.json"
    out_md = tmp_path / "ops" / "dual.md"
    parsed = build_parser().parse_args(
        [
            "--candles",
            str(btc),
            "--candles",
            str(eth),
            "--binance-candles",
            str(btc_usdt),
            "--binance-candles",
            str(eth_usdt),
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
            "--min-trades",
            "1",
            "--fee-bps",
            "10",
        ]
    )
    # CLI scores the full frozen catalog; 240-bar Kraken is enough to
    # prove wiring and fail-closed dual-print when gate B cannot form.
    written_json, written_md = run(parsed, settings=settings(), candidates=_tiny_catalog())
    assert written_json.is_file()
    assert written_md.is_file()
    payload = json.loads(written_json.read_text())
    assert payload["ranking_key"] == RANKING_KEY
    assert payload["keep_flag_false"] is True
    assert payload["multi_venue_bar_preregistered"] is True
    assert payload["can_average_venues"] is False
    assert payload["any_dual_print_passer"] is False
    assert payload["selected_candidate_id"] is None
    text = written_md.read_text()
    assert "Dual-print daily strategy search" in text
    assert "Keep every `PAPER_PROMOTE_*=false`" in text
    assert settings().paper_promote_ema_9_21 is False
    assert settings().paper_promote_ema_9_21_adx15 is False


# --- search evidence (#135) ---
def _evidence_row(
    candidate_id: str,
    *,
    dual_print: bool,
    kraken_ho: float,
    evidence_pass: bool,
) -> DualPrintRow:
    return DualPrintRow(
        candidate_id=candidate_id,
        family="ema_cross",
        label=candidate_id,
        kraken_combined=dual_print,
        binance_combined=dual_print,
        dual_print=dual_print,
        kraken_mean_holdout_excess=kraken_ho,
        evidence_pass=evidence_pass,
    )


def test_evidence_selected_only_on_a_row_with_evidence() -> None:
    rows = [
        _evidence_row("raw_top", dual_print=True, kraken_ho=0.30, evidence_pass=False),
        _evidence_row("evidence_second", dual_print=True, kraken_ho=0.20, evidence_pass=True),
        _evidence_row("not_dual", dual_print=False, kraken_ho=0.90, evidence_pass=True),
    ]
    passers = rank_dual_print_passers(rows)
    assert [row.candidate_id for row in passers] == ["raw_top", "evidence_second"]
    assert passers[0].selected is True
    assert passers[0].evidence_selected is False
    assert passers[1].evidence_selected is True
    assert rows[2].evidence_selected is False
    assert all(row.can_promote is False for row in rows)


def test_merged_row_requires_both_prints_evidence() -> None:
    from traderstack.research.dual_print_search import _merge_row
    from traderstack.research.evidence import CandidateEvidence
    from traderstack.research.harder_gates import CandidateHarderResult

    candidate = _tiny_catalog()[0]

    def harder(*, combined: bool, evidence_pass: bool) -> CandidateHarderResult:
        return CandidateHarderResult(
            candidate_id=candidate.candidate_id,
            family=candidate.family,
            label=candidate.label,
            combined=combined,
            evidence=CandidateEvidence(
                candidate_id=candidate.candidate_id, evidence_pass=evidence_pass
            ),
            evidence_pass=evidence_pass,
        )

    passing = harder(combined=True, evidence_pass=True)
    both = _merge_row(candidate, passing, harder(combined=True, evidence_pass=True))
    assert both.dual_print is True and both.evidence_pass is True
    assert both.kraken_evidence is not None and both.binance_evidence is not None
    one = _merge_row(candidate, passing, harder(combined=True, evidence_pass=False))
    assert one.dual_print is True and one.evidence_pass is False
    raw_fail = _merge_row(candidate, passing, harder(combined=False, evidence_pass=True))
    assert raw_fail.dual_print is False and raw_fail.evidence_pass is False
    missing = _merge_row(candidate, passing, None)
    assert missing.binance_evidence is None and missing.evidence_pass is False


def test_cli_payload_carries_print_kind_evidence_and_era_coverage(tmp_path: Path) -> None:
    from traderstack.research.evidence import ERA_WINDOWS

    primary = datetime(2024, 9, 22, tzinfo=UTC)
    older = datetime(2022, 10, 3, tzinfo=UTC)
    btc = tmp_path / "btc.json"
    eth = tmp_path / "eth.json"
    btc_usdt = tmp_path / "btcusdt.json"
    eth_usdt = tmp_path / "ethusdt.json"
    write_candles(btc, downtrend(240, symbol="BTC/USD", start=primary))
    write_candles(eth, downtrend(240, symbol="ETH/USD", start=primary))
    write_candles(btc_usdt, downtrend(720, symbol="BTCUSDT", start=older))
    write_candles(eth_usdt, downtrend(720, symbol="ETHUSDT", start=older))
    out_json = tmp_path / "ops" / "dual.json"
    out_md = tmp_path / "ops" / "dual.md"
    parsed = build_parser().parse_args(
        [
            "--candles",
            str(btc),
            "--candles",
            str(eth),
            "--binance-candles",
            str(btc_usdt),
            "--binance-candles",
            str(eth_usdt),
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
            "--train-size",
            "80",
            "--test-size",
            "40",
            "--step-size",
            "40",
            "--min-trades",
            "1",
            "--fee-bps",
            "10",
        ]
    )
    written_json, written_md = run(parsed, settings=settings(), candidates=_tiny_catalog())
    payload = json.loads(written_json.read_text())
    assert payload["print_kind"] == "venue"
    assert payload["kraken_evidence"] is not None
    assert payload["kraken_evidence"]["trial_count"] == len(_tiny_catalog())
    assert payload["evidence_passer_ids"] == []
    assert payload["evidence_selected_candidate_id"] is None
    assert payload["recommended_promote_flag"] is None
    assert len(payload["era_coverage"]) == 2 * len(ERA_WINDOWS)
    venues = {row["venue"] for row in payload["era_coverage"]}
    assert venues == {"kraken", "binance_json"}
    assert all(row["scoreable"] is False for row in payload["era_coverage"])
    assert "DSR >= 0.95" in payload["evidence_rules"]
    text = written_md.read_text()
    assert "## Evidence" in text
    assert "DSR" in text
    assert "## Print policy / era coverage" in text
    assert "print_kind=`venue`" in text
