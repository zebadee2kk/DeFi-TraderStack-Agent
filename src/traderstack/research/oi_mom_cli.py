"""`traderstack-oi-mom`: HL/Bybit OI-momentum SPOT dual-print.

Scores the frozen ``oi_mom_*`` catalog on Kraken x Coinbase daily
spot BTC/ETH using aligned HL-minus-HTX OI momentum as the FeatureZ
series. OI is a filter only. Never flips ``PAPER_PROMOTE_*``. HTX/Binance/OKX OI UNAVAILABLE at >=720d.
Empty dual-print is success.
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
from traderstack.research.cli import load_candles_from_json
from traderstack.research.edge_series import (
    BYBIT_BASE,
    fetch_asilletto81_hyperliquid_open_interest,
    fetch_bybit_open_interest,
)
from traderstack.research.funding_carry import (
    DEFAULT_STEP_SIZE,
    DEFAULT_TEST_SIZE,
    DEFAULT_TRAIN_SIZE,
    DEFAULT_WARMUP,
    REQUIRED_SYMBOLS,
)
from traderstack.research.oi_mom import (
    OI_MOM_RULES,
    render_oi_mom_markdown,
    run_oi_mom,
)
from traderstack.research.xs_topk import PILOT_TIER_TAKER_BPS

SYMBOLS = REQUIRED_SYMBOLS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "HL/Bybit OI-momentum SPOT overlay dual-print on Kraken x "
            "Coinbase at pilot fees. Pre-registered oi_mom_* catalog. "
            "Never flips PAPER_PROMOTE_*."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="fetch public HL + HTX funding (required unless --hl-oi-json/--bybit-oi-json)",
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
    parser.add_argument("--hl-oi-json", type=Path, default=None)
    parser.add_argument("--bybit-oi-json", type=Path, default=None)
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/oi-mom-hl-bybit-dual-print.md"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/hl_htx_oi_mom_spot_dual_print.json"),
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


def _load_oi_json(path: Path) -> dict[str, tuple[tuple[datetime, float], ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, tuple[tuple[datetime, float], ...]] = {}
    if isinstance(payload, dict) and "by_symbol" in payload:
        payload = payload["by_symbol"]
    if not isinstance(payload, dict):
        raise TypeError(f"{path}: expected object keyed by symbol")
    for symbol, rows in payload.items():
        points: list[tuple[datetime, float]] = []
        for row in rows:
            if isinstance(row, dict):
                ts = datetime.fromisoformat(str(row["opened_at"]))
                points.append((ts, float(row["value"])))
            else:
                ts = datetime.fromisoformat(str(row[0]))
                points.append((ts, float(row[1])))
        out[str(symbol).upper()] = tuple(points)
    return out


async def fetch_hl_bybit_oi(
    symbols: tuple[str, ...],
    *,
    timeout: float = 60.0,
) -> tuple[
    dict[str, tuple[tuple[datetime, float], ...]],
    dict[str, tuple[tuple[datetime, float], ...]],
    list[dict[str, str]],
]:
    notes: list[dict[str, str]] = []
    hl: dict[str, tuple[tuple[datetime, float], ...]] = {}
    bybit: dict[str, tuple[tuple[datetime, float], ...]] = {}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for symbol in symbols:
            result = await fetch_asilletto81_hyperliquid_open_interest(symbol, client=client)
            notes.append(result.as_note())
            if result.status == 'ok':
                hl[symbol.upper()] = result.points
    async with httpx.AsyncClient(base_url=BYBIT_BASE, timeout=timeout, follow_redirects=True) as bybit_client:
        for symbol in symbols:
            result = await fetch_bybit_open_interest(symbol, client=bybit_client)
            notes.append(result.as_note())
            if result.status == 'ok':
                bybit[symbol.upper()] = result.points
    return hl, bybit, notes



def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _ = Settings()  # ensure defaults load; never mutate PAPER_PROMOTE_*

    candle_dirs = args.candles_dir or [
        ["kraken", "var/research/candles/kraken"],
        ["coinbase", "var/research/candles/coinbase"],
    ]
    history_notes: list[dict[str, str]] = []
    primary_venue, primary_dir = candle_dirs[0][0], Path(candle_dirs[0][1])
    histories = _load_symbol_candles(primary_dir, SYMBOLS)
    for symbol in SYMBOLS:
        series = histories.get(symbol.upper())
        if series:
            history_notes.append(
                {
                    "name": f"{primary_venue}:{symbol}",
                    "status": "ok",
                    "reason": (
                        f"{len(series)} daily bars "
                        f"{series[0].opened_at.isoformat()} -> {series[-1].opened_at.isoformat()}"
                    ),
                }
            )
        else:
            history_notes.append(
                {
                    "name": f"{primary_venue}:{symbol}",
                    "status": "skipped",
                    "reason": f"missing 1d candles under {primary_dir}",
                }
            )

    second_histories: dict[str, tuple[Candle, ...]] | None = None
    second_venue: str | None = None
    if len(candle_dirs) >= 2:
        second_venue, second_dir = candle_dirs[1][0], Path(candle_dirs[1][1])
        second_histories = _load_symbol_candles(second_dir, SYMBOLS)
        for symbol in SYMBOLS:
            series = second_histories.get(symbol.upper())
            if series:
                history_notes.append(
                    {
                        "name": f"{second_venue}:{symbol}",
                        "status": "ok",
                        "reason": (
                            f"{len(series)} daily bars "
                            f"{series[0].opened_at.isoformat()} -> "
                            f"{series[-1].opened_at.isoformat()}"
                        ),
                    }
                )
            else:
                history_notes.append(
                    {
                        "name": f"{second_venue}:{symbol}",
                        "status": "skipped",
                        "reason": f"missing 1d candles under {second_dir}",
                    }
                )
        if len(second_histories) < len(SYMBOLS):
            second_histories = None
            second_venue = None

    edge_notes: list[dict[str, str]] = []
    if args.hl_oi_json and args.bybit_oi_json:
        hl = _load_oi_json(args.hl_oi_json)
        bybit = _load_oi_json(args.bybit_oi_json)
        edge_notes.append(
            {
                "name": "oi_source",
                "status": "ok",
                "reason": f"offline files {args.hl_oi_json} + {args.bybit_oi_json}",
            }
        )
    elif args.live:
        hl, bybit, fetch_notes = asyncio.run(fetch_hl_bybit_oi(SYMBOLS))
        edge_notes.extend(fetch_notes)
    else:
        raise SystemExit("provide --live or both --hl-oi-json and --bybit-oi-json")

    report = run_oi_mom(
        histories,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        starting_equity=args.starting_equity,
        warmup=args.warmup,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        interval=args.interval,
        hl_oi_by_symbol=hl,
        bybit_oi_by_symbol=bybit,
        feature_oi_by_symbol=bybit,
        second_histories=second_histories,
        primary_candle_venue=primary_venue,
        second_candle_venue=second_venue,
        history_notes=history_notes,
    )
    # Attach raw fetch notes that are not already in report.edge_notes
    if edge_notes:
        report = report.model_copy(update={"edge_notes": list(report.edge_notes) + edge_notes})

    md = render_oi_mom_markdown(report)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(md, encoding="utf-8")
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    if args.stdout_md:
        print(md)
    print(
        f"wrote {args.output_md} dual_print_passers={report.dual_print_passers} "
        f"print_kind={report.print_kind} keep_flag_false={report.keep_flag_false}"
    )
    print(OI_MOM_RULES.split(".")[0] + ".")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
