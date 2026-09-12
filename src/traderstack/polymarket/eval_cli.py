"""``traderstack-polymarket-weather-eval``: fee-aware weather evaluation.

Report-only. Isolated from the crypto paper loop. Never signs, never
posts CLOB orders, never flips ``PAPER_PROMOTE_*``. An empty historical
tape is success.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from traderstack.config import Settings
from traderstack.polymarket.cities import DEFAULT_CITY_SLUGS
from traderstack.polymarket.eval import (
    DailyClose,
    ResolvedWeatherRow,
    empty_live_report,
    load_daily_closes,
    load_resolved_rows,
    render_weather_eval_markdown,
    run_weather_eval,
)
from traderstack.polymarket.service import require_paper_trading_mode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fee-aware evaluation of the #44 Polymarket weather NWP-vs-mid "
            "rule against always-hold and fade-the-mid. Dual independent "
            "prints are required before anyone may talk about promotion. "
            "Does not flip PAPER_PROMOTE_*. Empty / negative is success. "
            "No CLOB orders."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--resolved",
        type=Path,
        action="append",
        help="JSON array of resolved weather rows (repeat; each file is a print)",
    )
    source.add_argument(
        "--empty-live",
        action="store_true",
        help=(
            "write the honest empty historical-tape report (no point-in-time "
            "CLOB mid + official station-high series in this repo)"
        ),
    )
    parser.add_argument(
        "--btc-daily",
        type=Path,
        default=None,
        help="optional [{opened_at, close}] BTC daily series for the crypto overlay",
    )
    parser.add_argument("--min-edge", type=float, default=None)
    parser.add_argument("--fee-haircut", type=float, default=None)
    parser.add_argument("--sigma-f", type=float, default=None)
    parser.add_argument("--half-spread", type=float, default=None)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument(
        "--cities",
        default=None,
        help="comma-separated allowlist (default: #44 warm/stable set)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/polymarket_weather_eval.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/polymarket-weather-eval.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _print_id_for(path: Path, index: int) -> str:
    stem = path.stem.strip() or f"print_{index + 1}"
    return stem


def _load_prints(paths: list[Path]) -> dict[str, tuple[ResolvedWeatherRow, ...]]:
    prints: dict[str, tuple[ResolvedWeatherRow, ...]] = {}
    for index, path in enumerate(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        print_id = _print_id_for(path, index)
        if print_id in prints:
            print_id = f"{print_id}_{index + 1}"
        prints[print_id] = load_resolved_rows(payload, default_print_id=print_id)
    return prints


def _load_btc(path: Path | None) -> tuple[DailyClose, ...] | None:
    if path is None:
        return None
    return load_daily_closes(json.loads(path.read_text(encoding="utf-8")))


def run(args: argparse.Namespace, settings: Settings | None = None) -> tuple[Path, Path]:
    settings = settings or Settings()
    require_paper_trading_mode(settings)
    allowlist = (
        tuple(item.strip() for item in args.cities.split(",") if item.strip())
        if args.cities
        else DEFAULT_CITY_SLUGS
    )
    min_edge = args.min_edge if args.min_edge is not None else settings.polymarket_weather_min_edge
    fee_haircut = (
        args.fee_haircut
        if args.fee_haircut is not None
        else settings.polymarket_weather_fee_haircut
    )
    sigma_f = args.sigma_f if args.sigma_f is not None else settings.polymarket_weather_sigma_f
    half_spread = args.half_spread if args.half_spread is not None else 0.01
    notes = [f"TRADING_MODE={settings.trading_mode}; report-only; venue_submitted=false"]
    if args.empty_live:
        report = empty_live_report(
            min_edge=min_edge,
            fee_haircut=fee_haircut,
            sigma_f=sigma_f,
            default_half_spread=half_spread,
            holdout_fraction=args.holdout_fraction,
            allowlist=allowlist,
            extra_notes=notes,
        )
    else:
        prints = _load_prints(args.resolved)
        notes.append(
            "Resolved-row files are operator/fixture input, not a live CLOB tape. "
            + ", ".join(f"{key} n={len(value)}" for key, value in prints.items())
        )
        report = run_weather_eval(
            prints,
            min_edge=min_edge,
            fee_haircut=fee_haircut,
            sigma_f=sigma_f,
            default_half_spread=half_spread,
            holdout_fraction=args.holdout_fraction,
            allowlist=allowlist,
            min_mid=settings.polymarket_weather_min_mid,
            max_mid=settings.polymarket_weather_max_mid,
            btc_daily=_load_btc(args.btc_daily),
            crypto_fee_bps=max(settings.pretrade_fee_bps, settings.paper_fee_bps),
            data_notes=notes,
        )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_weather_eval_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        print(
            f"WEATHER EVAL {report.print_kind} (report-only): wrote "
            f"{args.output_json} and {args.output_md} "
            f"(independent={str(report.independent).lower()}; "
            f"can_promote={str(report.can_promote).lower()}; "
            f"keep_flag_false={str(report.keep_flag_false).lower()}; "
            f"crypto={report.crypto_overlay.status}). "
            "PAPER_PROMOTE_* flags are unchanged. Empty/negative is success."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
