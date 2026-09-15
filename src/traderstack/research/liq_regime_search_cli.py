"""`traderstack-liq-regime-search`: liquidation/regime-conditioned catalog.

Scores the frozen core (vol-regime wrappers + unconditioned controls)
plus optional liquidation / funding / OI / cross-venue families when an
aligned series exists. Dual-print only if historical liquidation series
exists on BTC and ETH **and** a second venue print is supplied.
Otherwise the run is labeled single-print and cannot promote.

Never flips ``PAPER_PROMOTE_*``. Empty search is success. No live.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.fee_tiers import add_fee_tier_argument, resolve_research_costs
from traderstack.research.binance_spot import (
    DEFAULT_BINANCE_SYMBOLS,
    download_binance_spot_histories,
)
from traderstack.research.cli import load_candles_from_json
from traderstack.research.daily_robustness import KRAKEN_PUBLIC_OHLC_MAX_BARS
from traderstack.research.daily_robustness_cli import _load_histories
from traderstack.research.edge_series import fetch_edge_bundle
from traderstack.research.liq_regime_search import (
    MIN_SECOND_VENUE_BARS,
    historical_liquidation_usable,
    render_liq_regime_markdown,
    run_liq_regime_search,
)
from traderstack.research.search_cli import _parse_feature_series
from traderstack.research.second_print import (
    SECOND_PRINT_BARS,
    primary_first_opened_at,
    remap_binance_for_scoring,
    slice_ending_before,
)

DEFAULT_SYMBOLS = ("BTC/USD", "ETH/USD")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score a pre-registered liquidation/regime-conditioned catalog "
            "on Kraken public Spot daily (720-bar cap) with fee-aware "
            "walk-forward + holdout. Dual-print only if a historical "
            "liquidation series exists on BTC and ETH. Otherwise "
            "SINGLE-PRINT and cannot promote. Does not flip PAPER_PROMOTE_*. "
            "Empty search is success."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--candles",
        type=Path,
        action="append",
        help="JSON candle array (repeat per asset). Symbol+interval from file.",
    )
    source.add_argument(
        "--live-kraken",
        action="store_true",
        help=(
            "fetch BTC/ETH daily from Kraken public OHLC "
            f"(hard cap {KRAKEN_PUBLIC_OHLC_MAX_BARS} bars) and probe "
            "public funding / OI / liquidation REST"
        ),
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="override live Kraken symbols (repeat; default BTC/USD ETH/USD)",
    )
    parser.add_argument("--max-candles", type=int, default=KRAKEN_PUBLIC_OHLC_MAX_BARS)
    parser.add_argument("--starting-equity", type=float, default=None)
    parser.add_argument("--fee-bps", type=float, default=None)
    # --- fee realism (#138) ---
    add_fee_tier_argument(parser)
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--train-size", type=int, default=180)
    parser.add_argument("--test-size", type=int, default=60)
    parser.add_argument("--step-size", type=int, default=60)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument(
        "--fetch-edge-series",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="download public funding/OI and probe liquidations (default on for --live-kraken)",
    )
    parser.add_argument(
        "--liquidation-z",
        type=Path,
        default=None,
        help="optional aligned [{opened_at, value}] series; omitted = family skipped",
    )
    parser.add_argument("--funding-z", type=Path, default=None)
    parser.add_argument("--oi-z", type=Path, default=None)
    parser.add_argument("--cross-venue-z", type=Path, default=None)
    parser.add_argument(
        "--binance-candles",
        type=Path,
        action="append",
        default=None,
        help="offline second-venue JSON (used only when historical liq exists)",
    )
    parser.add_argument(
        "--binance",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="fetch Binance.US older-720 only if historical liq exists (default on)",
    )
    parser.add_argument("--min-second-venue-bars", type=int, default=MIN_SECOND_VENUE_BARS)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/liq_regime_search.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/liq-regime-search.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _history_key(candles: tuple[Candle, ...]) -> str:
    return f"{candles[0].symbol}@{candles[0].interval}"


def _as_history_notes(notes: list[str]) -> list[dict[str, str]]:
    return [{"note": item, "source": "liq_regime_search"} for item in notes]


def _load_binance_files(paths: list[Path]) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    histories: dict[str, tuple[Candle, ...]] = {}
    notes: list[str] = []
    for path in paths:
        candles = load_candles_from_json(path)
        if not candles:
            raise ValueError(f"{path}: no candles")
        histories[_history_key(candles)] = candles
        notes.append(
            f"loaded {len(candles)} {candles[0].interval} bars for "
            f"{candles[0].symbol} from {path} (second_venue_json; non-Kraken)"
        )
    return histories, notes


def _load_live_binance(
    end_before: datetime,
) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    try:
        histories, _source, notes = asyncio.run(
            download_binance_spot_histories(
                DEFAULT_BINANCE_SYMBOLS,
                end_before=end_before,
                max_candles=SECOND_PRINT_BARS,
            )
        )
    except (OSError, TypeError, ValueError, httpx.HTTPError) as exc:
        return {}, [f"Binance Spot daily skipped: {exc}"]
    sliced: dict[str, tuple[Candle, ...]] = {}
    for key, candles in histories.items():
        cut = slice_ending_before(candles, before=end_before, bars=SECOND_PRINT_BARS)
        if cut:
            sliced[key] = cut
    return sliced, notes


def run(args: argparse.Namespace, settings: Settings | None = None) -> tuple[Path, Path]:
    settings = settings or Settings()
    if args.live_kraken:
        args.yahoo = False
        if args.symbol is None:
            args.symbol = list(DEFAULT_SYMBOLS)
    else:
        args.yahoo = False
        args.live_kraken = False

    kraken_histories, notes = _load_histories(args)
    history_notes = _as_history_notes(notes)

    funding = _parse_feature_series(args.funding_z) if args.funding_z else None
    open_interest = _parse_feature_series(args.oi_z) if args.oi_z else None
    liquidation = _parse_feature_series(args.liquidation_z) if args.liquidation_z else None
    cross_venue = _parse_feature_series(args.cross_venue_z) if args.cross_venue_z else None
    funding_by_symbol = None
    oi_by_symbol = None
    liq_by_symbol = None
    edge_notes: list[dict[str, str]] = []

    fetch_edge = (
        args.fetch_edge_series if args.fetch_edge_series is not None else bool(args.live_kraken)
    )
    symbols = tuple(args.symbol) if args.symbol else DEFAULT_SYMBOLS
    if fetch_edge:
        bundle = asyncio.run(fetch_edge_bundle(symbols))
        edge_notes = [note.as_note() for note in bundle.notes]
        if bundle.funding:
            funding_by_symbol = bundle.funding
        if bundle.open_interest:
            oi_by_symbol = bundle.open_interest
        if bundle.liquidation:
            liq_by_symbol = bundle.liquidation

    have_liq = historical_liquidation_usable(liquidation, liq_by_symbol)
    second_histories: dict[str, tuple[Candle, ...]] | None = None
    if have_liq and args.binance_candles:
        loaded, extra = _load_binance_files(args.binance_candles)
        notes.extend(extra)
        history_notes.extend(_as_history_notes(extra))
        remapped = remap_binance_for_scoring(loaded)
        second_histories = remapped or loaded
    elif have_liq and args.binance and args.live_kraken:
        primary_first, source = primary_first_opened_at(kraken_histories)
        extra_note = f"primary first bar {primary_first.isoformat()} (source={source})"
        notes.append(extra_note)
        history_notes.append({"note": extra_note, "source": "liq_regime_search"})
        fetched, extra = _load_live_binance(primary_first)
        history_notes.extend(_as_history_notes(extra))
        remapped = remap_binance_for_scoring(fetched)
        second_histories = remapped or None
        if second_histories is None:
            history_notes.append(
                {
                    "note": (
                        "Binance second print missing or too short after remap; "
                        "staying single-print"
                    ),
                    "source": "liq_regime_search",
                }
            )
    elif have_liq and not args.binance:
        history_notes.append(
            {
                "note": "second venue skipped (--no-binance); single-print",
                "source": "liq_regime_search",
            }
        )
    elif not have_liq:
        history_notes.append(
            {
                "note": (
                    "No usable historical liquidation series — Binance dual-print "
                    "not fetched. Labeled single-print; cannot promote."
                ),
                "source": "liq_regime_search",
            }
        )

    # --- fee realism (#138) ---
    # Precedence: --fee-bps (stamped "explicit") > --fee-tier > PAPER_FEE_TIER;
    # the tier fee is max(PRETRADE_FEE_BPS, tier taker). Taker leg only.
    costs = resolve_research_costs(
        fee_bps=args.fee_bps,
        fee_tier=args.fee_tier,
        settings=settings,
        slippage_bps=args.slippage_bps,
    )
    fee_bps = costs.fee_bps
    slippage_bps = costs.slippage_bps
    report = run_liq_regime_search(
        kraken_histories,
        fee_bps=fee_bps,
        fee_tier=costs.stamp,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        liquidation=liquidation,
        liquidation_by_symbol=liq_by_symbol,
        funding=funding,
        funding_by_symbol=funding_by_symbol,
        open_interest=open_interest,
        open_interest_by_symbol=oi_by_symbol,
        cross_venue=cross_venue,
        second_venue_histories=second_histories,
        min_second_venue_bars=args.min_second_venue_bars,
        history_notes=history_notes,
        edge_notes=edge_notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_liq_regime_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        print(
            f"{report.print_kind.upper()}: wrote {args.output_json} and "
            f"{args.output_md} (selected={report.selected_candidate_id or 'none'}; "
            f"historical_liq={report.historical_liquidation}; "
            f"can_promote={report.can_promote}; "
            f"keep_flag_false={report.keep_flag_false}). "
            "PAPER_PROMOTE_* flags are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
