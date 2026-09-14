"""`traderstack-ensemble-trend`: ensemble-trend dual-print (#137).

Scores the frozen multi-lookback Donchian-on-close + trailing stop +
25% vol-target catalog on a top-20 point-in-time Kraken universe, on
the Kraken primary 720-bar daily window and the #102 Binance.US
older-720. A name must combined-pass **both** prints. Ranking is
Kraken mean holdout excess among dual-print passers. Fees come from
the frozen Kraken Pro tier table unless ``--fee-bps`` is explicit.
Era prints and DSR / PBO are reported as unavailable until #133 /
#135 land. Never flips ``PAPER_PROMOTE_*``. An empty passer set is
success. Paper-only; no live.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.research.binance_spot import download_binance_spot_histories
from traderstack.research.cli import load_candles_from_json
from traderstack.research.daily_robustness import (
    KRAKEN_DAILY_CAP_NOTE,
    KRAKEN_PUBLIC_OHLC_MAX_BARS,
)
from traderstack.research.download_candles import download_candles
from traderstack.research.ensemble_trend import (
    CANDIDATE_UNIVERSE,
    DEFAULT_KRAKEN_TIER,
    KRAKEN_PRO_TIERS,
    RANKING_KEY,
    fee_tier_taker_bps,
    render_ensemble_trend_markdown,
    run_ensemble_trend_search,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.second_print import SECOND_PRINT_BARS, primary_first_opened_at

DEFAULT_BINANCE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
# Kraken's public counter is roughly one request per second; the pull is
# sequential and sleeps between symbols so a 36-name universe stays polite.
KRAKEN_PULL_PAUSE_SECONDS = 1.1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ensemble-trend dual-print (#137): long-only multi-lookback "
            "Donchian-on-close {5..360} + trailing midpoint stop + 25% vol "
            "target on a frozen top-20 point-in-time Kraken universe. Must "
            "clear Kraken primary harder combined gates (#96+A+B+C on "
            "BTC+ETH; SOL reported) AND the #102 Binance.US older-720 "
            f"combined gates. Ranking key (frozen): {RANKING_KEY}. Fees from "
            "the frozen Kraken Pro tier table (--kraken-tier) unless "
            "--fee-bps is explicit. Era prints / DSR / PBO reported as "
            "unavailable until #133 / #135. Does not flip PAPER_PROMOTE_* "
            "flags. An empty dual-print set is success. Not a #118 Donchian "
            "N retune. No live."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--candles",
        type=Path,
        action="append",
        help=(
            "Kraken-format JSON candle array (repeat per asset; the whole "
            "universe may be supplied). Symbol+interval from file."
        ),
    )
    source.add_argument(
        "--live",
        action="store_true",
        help=(
            "fetch Kraken public OHLC daily (720-bar cap) for every frozen "
            "CANDIDATE_UNIVERSE pair (per-symbol failures are skip notes) and "
            "Binance Spot daily BTCUSDT/ETHUSDT/SOLUSDT (api.binance.com, then .us)"
        ),
    )
    parser.add_argument(
        "--binance-candles",
        type=Path,
        action="append",
        default=None,
        help="offline Binance JSON candle array (repeat; BTCUSDT/ETHUSDT/SOLUSDT)",
    )
    parser.add_argument(
        "--binance",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="fetch/score Binance Spot daily (default on; --no-binance is success)",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="override live Kraken symbols (repeat; default: frozen CANDIDATE_UNIVERSE)",
    )
    parser.add_argument("--max-candles", type=int, default=KRAKEN_PUBLIC_OHLC_MAX_BARS)
    parser.add_argument(
        "--kraken-tier",
        type=int,
        choices=sorted(KRAKEN_PRO_TIERS),
        default=DEFAULT_KRAKEN_TIER,
        help="frozen Kraken Pro tier; taker bps per side (default tier 1 = 80 bps)",
    )
    parser.add_argument("--starting-equity", type=float, default=None)
    parser.add_argument(
        "--fee-bps",
        type=float,
        default=None,
        help="explicit fee bps per side; overrides --kraken-tier when given",
    )
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--train-size", type=int, default=180)
    parser.add_argument("--test-size", type=int, default=60)
    parser.add_argument("--step-size", type=int, default=60)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/ensemble_trend.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/ensemble-trend.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _history_key(candles: tuple[Candle, ...]) -> str:
    return f"{candles[0].symbol}@{candles[0].interval}"


def _load_candle_files(paths: list[Path]) -> tuple[dict[str, tuple[Candle, ...]], list[str]]:
    histories: dict[str, tuple[Candle, ...]] = {}
    notes: list[str] = [KRAKEN_DAILY_CAP_NOTE]
    for path in paths:
        candles = load_candles_from_json(path)
        if not candles:
            raise ValueError(f"{path}: no candles")
        histories[_history_key(candles)] = candles
        notes.append(
            f"loaded {len(candles)} {candles[0].interval} bars for "
            f"{candles[0].symbol} from {path} (json)"
        )
    if not histories:
        raise ValueError("no candle histories loaded")
    return histories, notes


async def _pull_universe(
    symbols: tuple[str, ...],
    *,
    max_candles: int,
    pause_seconds: float,
) -> tuple[dict[str, tuple[Candle, ...]], list[str], list[str]]:
    """Sequential Kraken daily pull; an unknown pair or HTTP error is a skip."""
    histories: dict[str, tuple[Candle, ...]] = {}
    notes: list[str] = [KRAKEN_DAILY_CAP_NOTE]
    skipped: list[str] = []
    async with httpx.AsyncClient(base_url="https://api.kraken.com", timeout=30) as client:
        for position, symbol in enumerate(symbols):
            if position and pause_seconds > 0:
                await asyncio.sleep(pause_seconds)
            try:
                candles = await download_candles(
                    symbol, "1d", max_candles=max_candles, client=client
                )
            except (OSError, TypeError, ValueError, KeyError, httpx.HTTPError) as exc:
                skipped.append(symbol)
                notes.append(f"{symbol}@1d: Kraken skipped ({exc}); not invented")
                continue
            if not candles:
                skipped.append(symbol)
                notes.append(f"{symbol}@1d: Kraken returned no committed bars; skipped")
                continue
            key = f"{symbol.upper()}@1d"
            histories[key] = candles
            first = candles[0].opened_at.isoformat()
            last = candles[-1].opened_at.isoformat()
            cap = " (public OHLC cap)" if len(candles) >= KRAKEN_PUBLIC_OHLC_MAX_BARS else ""
            notes.append(f"{key}: {len(candles)} committed Kraken bars {first} → {last}{cap}")
    if not histories:
        raise ValueError("no candle histories loaded")
    return histories, notes, skipped


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
            f"{candles[0].symbol} from {path} (binance_json; non-Kraken)"
        )
    return histories, notes


def _load_live_binance(
    end_before: datetime,
) -> tuple[dict[str, tuple[Candle, ...]], str | None, list[str]]:
    try:
        return asyncio.run(
            download_binance_spot_histories(
                DEFAULT_BINANCE_SYMBOLS,
                end_before=end_before,
                max_candles=SECOND_PRINT_BARS,
            )
        )
    except (OSError, TypeError, ValueError, httpx.HTTPError) as exc:
        return {}, None, [f"Binance Spot daily skipped: {exc}"]


def resolve_fee_bps(args: argparse.Namespace) -> tuple[float, str, int | None]:
    """Explicit --fee-bps wins; otherwise the frozen Kraken Pro tier taker leg."""
    if args.fee_bps is not None:
        return float(args.fee_bps), "explicit_fee_bps", None
    tier = int(args.kraken_tier)
    return fee_tier_taker_bps(tier), "kraken_pro_tier_taker", tier


def run(
    args: argparse.Namespace,
    settings: Settings | None = None,
    *,
    candidates: tuple[SearchCandidate, ...] | None = None,
    pause_seconds: float = KRAKEN_PULL_PAUSE_SECONDS,
) -> tuple[Path, Path]:
    settings = settings or Settings()
    universe_skipped: list[str] = []
    started = time.monotonic()
    if args.live:
        symbols = tuple(args.symbol) if args.symbol else CANDIDATE_UNIVERSE
        kraken_histories, notes, universe_skipped = asyncio.run(
            _pull_universe(symbols, max_candles=args.max_candles, pause_seconds=pause_seconds)
        )
        notes.append(
            f"universe pull: {len(kraken_histories)} of {len(symbols)} symbols in "
            f"{time.monotonic() - started:.0f}s; skipped={len(universe_skipped)}"
        )
    else:
        kraken_histories, notes = _load_candle_files(list(args.candles))
    primary_first, source = primary_first_opened_at(kraken_histories)
    notes.append(f"primary first bar {primary_first.isoformat()} (source={source})")
    notes.append(
        "gate symbols=BTC/USD,ETH/USD (SOL/USD reported); remaining universe "
        "names feed point-in-time membership only (skip-not-invent)"
    )

    binance_histories: dict[str, tuple[Candle, ...]] = {}
    binance_source: str | None = None
    if args.binance_candles:
        loaded, extra = _load_binance_files(args.binance_candles)
        binance_histories.update(loaded)
        notes.extend(extra)
        binance_source = "binance_json"
    elif args.binance and args.live:
        fetched, binance_source, extra = _load_live_binance(primary_first)
        binance_histories.update(fetched)
        notes.extend(extra)
    elif not args.binance:
        notes.append("Binance Spot daily skipped (--no-binance); empty print is success")
    else:
        notes.append(
            "Binance Spot daily not fetched (offline --candles without "
            "--binance-candles); empty print is success"
        )

    fee_bps, fee_source, kraken_tier = resolve_fee_bps(args)
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.pretrade_slippage_bps
    )
    report = run_ensemble_trend_search(
        kraken_histories,
        binance_histories,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        candidates=candidates,
        binance_source=binance_source,
        kraken_tier=kraken_tier,
        fee_source=fee_source,
        universe_skipped=universe_skipped,
        data_notes=notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_ensemble_trend_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "DUAL-PRINT PASSER" if report.any_dual_print_passer else "NO DUAL-PRINT PASSER"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(selected={report.selected_candidate_id or 'none'}; "
            f"dual_print_passers={len(report.dual_print_passer_ids)}; "
            f"kraken_combined={len(report.kraken_combined_passer_ids)}; "
            f"binance_combined={len(report.binance_combined_passer_ids)}; "
            f"eth_carried={len(report.eth_carried_ids)}; "
            f"fee_bps={report.fee_bps:g} ({report.fee_source}); "
            f"universe_members_last={len(report.universe.members_last)}; "
            f"era_prints_available={str(report.era_prints_available).lower()}; "
            f"dsr_pbo_available={str(report.dsr_pbo_available).lower()}; "
            f"ranking_key={report.ranking_key}; "
            f"paper_path_ready={report.paper_path_ready}; "
            f"keep_flag_false={report.keep_flag_false}). "
            "PAPER_PROMOTE_* flags are unchanged."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
