"""Tests for traderstack-polymarket-crypto-eval (#142 slice-2)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from traderstack.config import Settings
from traderstack.polymarket.crypto_eval import (
    CAN_ENTER_PROMOTION_AVERAGE,
    SettlementRow,
    empty_live_report,
    polymarket_taker_fee,
    print_clears_calculator,
    render_crypto_wedge_eval_markdown,
    run_crypto_wedge_eval,
    treatment_side,
)
from traderstack.polymarket.crypto_eval_cli import build_parser, run
from traderstack.polymarket.crypto_models import (
    DEFAULT_PROMOTE_FLAG,
    MIN_ROWS_PER_PRINT,
    MIN_TRADES_PER_PRINT,
    MULTI_PRINT_BAR_PREREGISTERED,
    PREREGISTERED_WEDGE_THRESHOLD,
    PRIMARY_MODEL_VERSION,
    CrucixStatus,
    CryptoAsset,
    CryptoWedgeRow,
    WedgeRowStatus,
)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "trading_mode": "paper",
    }
    values.update(overrides)
    return Settings(**values)


def _row(**overrides: object) -> CryptoWedgeRow:
    values: dict[str, object] = {
        "status": WedgeRowStatus.OK,
        "market_id": "mkt-1",
        "asset": CryptoAsset.BTC,
        "strike_usd": 100_000.0,
        "resolves_at": datetime(2026, 9, 20, 16, tzinfo=UTC),
        "observed_at": datetime(2026, 9, 19, 12, tzinfo=UTC),
        "poly_mid": 0.40,
        "poly_best_bid": 0.39,
        "poly_best_ask": 0.41,
        "deribit_prob": 0.55,
        "wedge": 0.40 - 0.55,
        "model_version": PRIMARY_MODEL_VERSION,
        "crucix_status": CrucixStatus.CLEAR,
        "resolution_text_ok": True,
    }
    values.update(overrides)
    return CryptoWedgeRow.model_validate(values)


def test_constants_match_preregistration() -> None:
    assert PREREGISTERED_WEDGE_THRESHOLD == 0.05
    assert MIN_ROWS_PER_PRINT == 20
    assert MIN_TRADES_PER_PRINT == 8
    assert MULTI_PRINT_BAR_PREREGISTERED is True
    assert CAN_ENTER_PROMOTION_AVERAGE is False
    assert DEFAULT_PROMOTE_FLAG == "PAPER_PROMOTE_POLYMARKET_CRYPTO_WEDGE"


def test_treatment_side_and_fee() -> None:
    assert treatment_side(0.1) == "no"  # poly rich
    assert treatment_side(-0.1) == "yes"  # poly cheap
    fee = polymarket_taker_fee(0.5, shares=100.0)
    assert fee == pytest.approx(1.75)  # hits cap at p=0.5


def test_empty_live_cannot_promote() -> None:
    report = empty_live_report()
    assert report.print_kind == "single_print"
    assert report.can_promote is False
    assert report.keep_flag_false is True
    assert report.prints[0].fail_closed_reason == "empty_print"
    md = render_crypto_wedge_eval_markdown(report)
    assert "No candidate is promoted" in md
    assert "PAPER_PROMOTE_*" in md


def test_unsettled_skip_not_invent() -> None:
    rows = (_row(wedge=-0.12, poly_mid=0.40, deribit_prob=0.52),)
    report = run_crypto_wedge_eval({"p1": rows}, {})
    assert report.can_promote is False
    metrics = report.prints[0]
    assert metrics.n_unsettled == 1
    assert metrics.n_would_trade == 0
    assert metrics.fail_closed_reason == "no_settlements_skip_not_invent"


def test_stand_aside_when_crucix_not_clear() -> None:
    rows = (
        _row(
            crucix_status=CrucixStatus.NOT_CONFIGURED,
            wedge=-0.12,
            poly_mid=0.40,
            deribit_prob=0.52,
        ),
    )
    settlements = {
        "p1": (SettlementRow(market_id="mkt-1", yes_won=True, resolution_source="gamma"),)
    }
    report = run_crypto_wedge_eval({"p1": rows}, settlements)
    assert report.prints[0].n_stand_aside == 1
    assert report.prints[0].n_would_trade == 0


def test_scores_when_settled_and_clear() -> None:
    rows = (
        _row(
            market_id="mkt-a",
            wedge=-0.12,
            poly_mid=0.40,
            deribit_prob=0.52,
            poly_best_bid=0.39,
            poly_best_ask=0.41,
        ),
    )
    settlements = {
        "p1": (
            SettlementRow(
                market_id="mkt-a",
                yes_won=True,
                resolution_source="binance_vision_1m",
            ),
        )
    }
    report = run_crypto_wedge_eval({"p1": rows}, settlements)
    m = report.prints[0]
    assert m.n_would_trade == 1
    assert m.treatment_pnl != 0.0
    assert m.hedged_status == "skipped_not_invented"
    assert report.can_promote is False
    assert print_clears_calculator(m) is False  # below min rows


def test_lookahead_refused() -> None:
    rows = (
        _row(
            observed_at=datetime(2026, 9, 21, 12, tzinfo=UTC),
            resolves_at=datetime(2026, 9, 20, 16, tzinfo=UTC),
            wedge=-0.12,
        ),
    )
    settlements = {
        "p1": (SettlementRow(market_id="mkt-1", yes_won=False, resolution_source="gamma"),)
    }
    report = run_crypto_wedge_eval({"p1": rows}, settlements)
    assert report.prints[0].n_lookahead == 1
    assert report.prints[0].n_would_trade == 0


def test_cli_empty_live(tmp_path: Path) -> None:
    out_json = tmp_path / "eval.json"
    out_md = tmp_path / "eval.md"
    args = build_parser().parse_args(
        [
            "--empty-live",
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
        ]
    )
    run(args, settings=settings())
    assert out_json.exists()
    text = out_md.read_text(encoding="utf-8")
    assert "empty_print" in text
    assert "No candidate is promoted" in text


def test_cli_rejects_non_paper(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "--empty-live",
            "--output-json",
            str(tmp_path / "x.json"),
            "--output-md",
            str(tmp_path / "x.md"),
        ]
    )
    with pytest.raises(RuntimeError, match="TRADING_MODE=paper"):
        run(args, settings=settings(trading_mode="live"))
