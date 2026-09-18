"""`traderstack-stable-net-issuance`: DefiLlama net-issuance SPOT dual-print.

Fetches public stablecoin charts when asked, but refuses historical dual-print
scoring unless an operator PIT archive is marked pit_safe. Never flips
``PAPER_PROMOTE_*``. UNAVAILABLE is success.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.market.defillama_stablecoins import (
    DEFILLAMA_STABLECOINS_BASE,
    PIT_VERDICT,
    StablecoinChartSeries,
    fetch_stablecoin_charts_all,
    parse_stablecoin_chart_rows,
)
from traderstack.research.cli import load_candles_from_json
from traderstack.research.funding_carry import (
    DEFAULT_STEP_SIZE,
    DEFAULT_TEST_SIZE,
    DEFAULT_TRAIN_SIZE,
    DEFAULT_WARMUP,
)
from traderstack.research.stable_net_issuance import (
    REQUIRED_SYMBOLS,
    STABLE_NI_RULES,
    render_stable_net_issuance_markdown,
    run_stable_net_issuance,
)
from traderstack.research.xs_topk import PILOT_TIER_TAKER_BPS

SYMBOLS = REQUIRED_SYMBOLS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "DefiLlama stablecoin net-issuance SPOT overlay dual-print on "
            "Kraken x Coinbase at pilot fees. Live history is not PIT-safe; "
            "score refuses without a pit_safe archive. Never flips PAPER_PROMOTE_*."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="fetch public DefiLlama stablecoincharts/all (fetch-only; score stays unavailable without --pit-archive)",
    )
    parser.add_argument(
        "--chart-json",
        type=Path,
        default=None,
        help="offline DefiLlama chart JSON array (still not pit_safe unless --pit-archive)",
    )
    parser.add_argument(
        "--pit-archive",
        type=Path,
        default=None,
        help="PIT archive JSON (pit_safe=true) OR dated snapshot dir (needs >=720 tips)",
    )
    parser.add_argument("--interval", default="1d", choices=("1d",))
    parser.add_argument("--fee-bps", type=float, default=PILOT_TIER_TAKER_BPS)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--starting-equity", type=float, default=10_000.0)
    parser.add_argument("--train-size", type=int, default=DEFAULT_TRAIN_SIZE)
    parser.add_argument("--test-size", type=int, default=DEFAULT_TEST_SIZE)
    parser.add_argument("--step-size", type=int, default=DEFAULT_STEP_SIZE)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument(
        "--candles-dir",
        nargs=2,
        action="append",
        metavar=("VENUE", "DIR"),
        default=None,
        help="venue label and candle directory (repeatable; expect kraken + coinbase)",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/defillama-stable-net-issuance-dual-print.md"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/defillama_stable_net_issuance_dual_print.json"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _load_symbol_candles(
    directory: Path, symbols: tuple[str, ...]
) -> dict[str, tuple[Candle, ...]]:
    wanted = {symbol.upper() for symbol in symbols}
    histories: dict[str, tuple[Candle, ...]] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".report.json"):
            continue
        try:
            candles = load_candles_from_json(path)
        except (TypeError, ValueError, OSError):
            continue
        if not candles or candles[0].interval != "1d":
            continue
        symbol = candles[0].symbol.upper()
        if symbol not in wanted:
            continue
        histories[symbol] = candles
    return histories


def _load_pit_archive(
    path: Path,
) -> tuple[StablecoinChartSeries | None, list | None, list[dict[str, str]], bool]:
    """Load PIT file or dated snapshot directory.

    Returns (series, issuance_points_or_None, notes, allowed_to_score).
    Directory archives require >=720 tip days (tip-delta PIT series).
    Bare chart arrays are never allowed.
    """
    from traderstack.market.defillama_stable_snapshots import (
        load_pit_series_from_archive,
        tips_path,
    )

    archive_dir = None
    if path.is_dir():
        archive_dir = path
    elif tips_path(path).is_file():
        archive_dir = path
    elif path.name == "tips.jsonl" and path.is_file():
        archive_dir = path.parent
    if archive_dir is not None:
        series, points, notes, allowed = load_pit_series_from_archive(archive_dir)
        return series, points, notes, allowed

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "rows" in payload:
        rows = payload["rows"]
        pit_safe = bool(payload.get("pit_safe", False))
        fetched_at = datetime.fromisoformat(str(payload.get("fetched_at")))
        series = parse_stablecoin_chart_rows(
            rows,
            fetched_at=fetched_at,
            endpoint=str(payload.get("endpoint", "pit_archive")),
            stablecoin_id=payload.get("stablecoin_id"),
        )
        series = series.model_copy(update={"pit_safe": pit_safe})
        return series, None, [], bool(pit_safe)
    if isinstance(payload, list):
        # bare chart array is never pit_safe
        return parse_stablecoin_chart_rows(payload), None, [], False
    raise TypeError(f"{path}: expected PIT archive object, chart list, or archive dir")


async def _maybe_fetch_live() -> StablecoinChartSeries | None:
    async with httpx.AsyncClient(
        base_url=DEFILLAMA_STABLECOINS_BASE,
        timeout=90.0,
        headers={"User-Agent": "traderstack-research/0.1"},
    ) as client:
        return await fetch_stablecoin_charts_all(client)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    _ = settings.trading_mode  # paper preference documented; CLI is offline/report

    history_notes: list[dict[str, str]] = [
        {"name": "rules", "status": "frozen", "reason": STABLE_NI_RULES[:160] + "…"},
        {"name": "pit", "status": "verdict", "reason": PIT_VERDICT},
    ]

    chart: StablecoinChartSeries | None = None
    issuance_points = None
    pit_archive_present = False
    if args.pit_archive is not None:
        chart, issuance_points, arch_notes, allowed = _load_pit_archive(args.pit_archive)
        pit_archive_present = True
        history_notes.extend(arch_notes)
        ps = getattr(chart, "pit_safe", False) if chart is not None else False
        history_notes.append(
            {
                "name": "pit_archive",
                "status": "loaded" if allowed else "insufficient",
                "reason": f"{args.pit_archive}; allowed={allowed}; pit_safe={ps}",
            }
        )
    elif args.chart_json is not None:
        raw = json.loads(args.chart_json.read_text(encoding="utf-8"))
        chart = parse_stablecoin_chart_rows(raw if isinstance(raw, list) else raw.get("rows", []))
        history_notes.append(
            {
                "name": "chart_json",
                "status": "loaded",
                "reason": f"{args.chart_json}; pit_safe=false (offline chart is not a PIT archive)",
            }
        )
    elif args.live:
        chart = asyncio.run(_maybe_fetch_live())
        history_notes.append(
            {
                "name": "live_fetch",
                "status": "ok" if chart is not None else "failed",
                "reason": (
                    f"fetched {len(chart.points) if chart else 0} days from "
                    f"{DEFILLAMA_STABLECOINS_BASE}; score refused without PIT archive"
                ),
            }
        )

    candles_dirs = args.candles_dir or [
        ("kraken", "var/research/candles/kraken"),
        ("coinbase", "var/research/candles/coinbase"),
    ]
    venue_histories: dict[str, dict[str, tuple[Candle, ...]]] = {}
    for venue, directory in candles_dirs:
        path = Path(directory)
        loaded = _load_symbol_candles(path, SYMBOLS) if path.is_dir() else {}
        venue_histories[str(venue).lower()] = loaded
        history_notes.append(
            {
                "name": f"candles:{venue}",
                "status": "ok" if loaded else "skipped",
                "reason": f"{path}: symbols={sorted(loaded)}",
            }
        )

    primary_venue = (
        "kraken" if "kraken" in venue_histories else next(iter(venue_histories), "kraken")
    )
    histories = venue_histories.get(primary_venue, {})
    second_venue = (
        "coinbase" if "coinbase" in venue_histories and primary_venue != "coinbase" else None
    )
    second_histories = venue_histories.get(second_venue) if second_venue else None

    report = run_stable_net_issuance(
        histories,
        fee_bps=float(args.fee_bps),
        slippage_bps=float(args.slippage_bps),
        starting_equity=float(args.starting_equity),
        warmup=int(args.warmup),
        train_size=int(args.train_size),
        test_size=int(args.test_size),
        step_size=int(args.step_size),
        holdout_fraction=float(args.holdout_fraction),
        min_trades=int(args.min_trades),
        interval=str(args.interval),
        chart=chart,
        issuance_points=issuance_points,
        pit_archive_present=pit_archive_present,
        second_histories=second_histories,
        primary_candle_venue=primary_venue,
        second_candle_venue=second_venue,
        history_notes=history_notes,
    )
    md = render_stable_net_issuance_markdown(report)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(md, encoding="utf-8")
    args.output_json.write_text(
        json.dumps(report.model_dump_json_safe(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.stdout_md:
        print(md)
    else:
        print(
            f"wrote {args.output_md} and {args.output_json}; "
            f"print_kind={report.print_kind}; dual_print_passers={report.dual_print_passers}; "
            f"can_promote={report.can_promote}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
