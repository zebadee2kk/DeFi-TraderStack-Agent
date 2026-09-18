"""``traderstack-polymarket-crypto-eval``: fee-aware #142 wedge evaluation.

Report-only. Isolated from the crypto paper loop. Never signs, never posts
CLOB/Deribit orders, never flips ``PAPER_PROMOTE_*``. Empty tape / missing
settlements is success (skip-not-invent).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from traderstack.config import Settings
from traderstack.polymarket.crypto_eval import (
    CryptoWedgeRow,
    empty_live_report,
    load_settlements,
    load_tape_jsonl,
    render_crypto_wedge_eval_markdown,
    run_crypto_wedge_eval,
)
from traderstack.polymarket.crypto_models import PREREGISTERED_WEDGE_THRESHOLD
from traderstack.polymarket.service import require_paper_trading_mode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fee-aware evaluation of the #142 Polymarket crypto-threshold vs "
            "Deribit wedge rule. Dual independent prints are required before "
            "anyone may talk about promotion. Does not flip PAPER_PROMOTE_*. "
            "Empty / negative is success. No CLOB or Deribit orders."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--empty-live",
        action="store_true",
        help=(
            "write the honest empty report (no settled point-in-time tape + "
            "settlement pack in this environment)"
        ),
    )
    source.add_argument(
        "--tape",
        type=Path,
        action="append",
        help="JSONL CryptoWedgeRow tape (repeat; each file is a print)",
    )
    parser.add_argument(
        "--settlements",
        type=Path,
        action="append",
        default=None,
        help=(
            "JSON settlement pack [{market_id, yes_won, resolution_source, ...}] "
            "(repeat to align with --tape prints; skip-not-invent when omitted)"
        ),
    )
    parser.add_argument("--wedge-threshold", type=float, default=PREREGISTERED_WEDGE_THRESHOLD)
    parser.add_argument("--half-spread", type=float, default=0.01)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/polymarket_crypto_wedge_eval.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/polymarket-crypto-wedge-eval.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _print_id_for(path: Path, index: int) -> str:
    stem = path.stem.strip() or f"print_{index + 1}"
    return stem


def _load_prints(paths: list[Path]) -> dict[str, tuple[CryptoWedgeRow, ...]]:
    prints: dict[str, tuple[CryptoWedgeRow, ...]] = {}
    for index, path in enumerate(paths):
        print_id = _print_id_for(path, index)
        if print_id in prints:
            print_id = f"{print_id}_{index + 1}"
        prints[print_id] = load_tape_jsonl(path)
    return prints


def _load_settlement_packs(
    paths: list[Path] | None,
    print_ids: list[str],
) -> dict[str, tuple]:
    if not paths:
        return {}
    out: dict[str, tuple] = {}
    for index, path in enumerate(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        pack = load_settlements(payload)
        if index < len(print_ids):
            out[print_ids[index]] = pack
        else:
            out[_print_id_for(path, index)] = pack
    return out


def run(args: argparse.Namespace, settings: Settings | None = None) -> tuple[Path, Path]:
    settings = settings or Settings()
    require_paper_trading_mode(settings)
    notes = [f"TRADING_MODE={settings.trading_mode}; report-only; venue_submitted=false"]
    if args.empty_live:
        report = empty_live_report(
            holdout_fraction=args.holdout_fraction,
            wedge_threshold=args.wedge_threshold,
            extra_notes=notes,
        )
    else:
        prints = _load_prints(args.tape)
        settlements = _load_settlement_packs(args.settlements, list(prints.keys()))
        notes.append(
            "Tape/settlement files are operator/fixture input. "
            + ", ".join(f"{key} n={len(value)}" for key, value in prints.items())
        )
        if not settlements:
            notes.append(
                "No --settlements supplied; rows that clear the wedge+Crucix mask "
                "are recorded as unsettled (skip-not-invent), not scored."
            )
        report = run_crypto_wedge_eval(
            prints,
            settlements,
            wedge_threshold=args.wedge_threshold,
            holdout_fraction=args.holdout_fraction,
            default_half_spread=args.half_spread,
            data_notes=notes,
        )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    markdown = render_crypto_wedge_eval_markdown(report)
    args.output_md.write_text(markdown, encoding="utf-8")
    if args.stdout_md:
        print(markdown)
    else:
        print(
            f"CRYPTO WEDGE EVAL {report.print_kind} (report-only): wrote "
            f"{args.output_json} and {args.output_md} "
            f"(independent={str(report.independent).lower()}; "
            f"can_promote={str(report.can_promote).lower()}; "
            f"keep_flag_false={str(report.keep_flag_false).lower()}). "
            "PAPER_PROMOTE_* flags are unchanged. Empty/negative is success."
        )
    return args.output_json, args.output_md


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
