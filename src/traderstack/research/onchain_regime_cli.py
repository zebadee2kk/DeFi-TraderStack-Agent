"""`traderstack-onchain-regime`: MVRV-Z / NUPL overlay on the TSMOM catalog (#139).

Scores the frozen TSMOM catalog ungated and gated by three pre-registered
Coin Metrics community regime overlays on the Kraken primary 720-bar
daily window and the #102 Binance.US older-720. A regime series that
cannot be reached is a **skip**: every overlay is skipped with a note,
the ungated base catalog is still scored, exit 0. Never flips
``PAPER_PROMOTE_*``; the runtime gate stays opt-in. An empty overlay
passer set is success. Paper-only; no live.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

import httpx

from traderstack.candles import Candle
from traderstack.config import Settings
from traderstack.market.coinmetrics import (
    COINMETRICS_COMMUNITY_BASE_URL,
    OnChainDailyRow,
    OnChainRegimePoint,
    derive_regime_series,
    drop_uncommitted_rows,
    fetch_asset_metric_rows,
    load_regime_rows_json,
    save_regime_rows_json,
)
from traderstack.research.binance_spot import download_binance_spot_histories
from traderstack.research.cli import load_candles_from_json
from traderstack.research.daily_robustness import KRAKEN_PUBLIC_OHLC_MAX_BARS
from traderstack.research.daily_robustness_cli import _load_histories
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.miles_search import research_fee_bps
from traderstack.research.onchain_regime import (
    OVERLAY_IDS,
    REGIME_SOURCE_ASSET,
    render_onchain_regime_markdown,
    run_onchain_regime_search,
)
from traderstack.research.second_print import SECOND_PRINT_BARS, primary_first_opened_at
from traderstack.research.tsmom import UNIVERSE

DEFAULT_KRAKEN_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD")
DEFAULT_BINANCE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
FETCH_ERRORS = (OSError, TypeError, ValueError, httpx.HTTPError)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "On-chain regime overlay: the frozen TSMOM catalog scored ungated "
            f"and gated by {', '.join(OVERLAY_IDS)} (Coin Metrics community "
            "MVRV-Z percentile / NUPL, BTC series, rows strictly before the "
            "decision bar). Two prints: Kraken primary 720 and the #102 "
            "Binance.US older-720. Skip-not-invent. Does not flip "
            "PAPER_PROMOTE_* flags; the runtime gate stays opt-in. An empty "
            "overlay passer set is success. No live."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--candles",
        type=Path,
        action="append",
        help="Kraken JSON candle array (repeat per asset). Symbol+interval from file.",
    )
    source.add_argument(
        "--live",
        action="store_true",
        help=(
            "fetch Kraken public OHLC daily (720-bar cap), Binance Spot daily "
            "BTCUSDT/ETHUSDT/SOLUSDT (api.binance.com, then .us) and the Coin "
            "Metrics community BTC series (unless --onchain-json is given)"
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
        help="override live Kraken symbols (repeat; default BTC/USD ETH/USD SOL/USD)",
    )
    parser.add_argument(
        "--onchain-json",
        type=Path,
        default=None,
        help=(
            "offline Coin Metrics rows (JSON list of {asset, day, mvrv, "
            "market_cap_usd}); without it and without --live every overlay is skipped"
        ),
    )
    parser.add_argument(
        "--save-onchain-json",
        type=Path,
        default=None,
        help="write the fetched Coin Metrics rows to this path for offline reruns",
    )
    parser.add_argument(
        "--coinmetrics-base-url",
        default=COINMETRICS_COMMUNITY_BASE_URL,
        help="Coin Metrics community base URL (no key)",
    )
    parser.add_argument(
        "--onchain-asset",
        default=REGIME_SOURCE_ASSET,
        help="Coin Metrics asset for the regime series (frozen default btc)",
    )
    parser.add_argument("--max-candles", type=int, default=KRAKEN_PUBLIC_OHLC_MAX_BARS)
    parser.add_argument("--starting-equity", type=float, default=None)
    parser.add_argument("--fee-bps", type=float, default=None)
    parser.add_argument("--slippage-bps", type=float, default=None)
    parser.add_argument("--train-size", type=int, default=180)
    parser.add_argument("--test-size", type=int, default=60)
    parser.add_argument("--step-size", type=int, default=60)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("var/ops/onchain-regime.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/artifacts/strategy-search/onchain-regime.md"),
    )
    parser.add_argument("--stdout-md", action="store_true")
    return parser


def _history_key(candles: tuple[Candle, ...]) -> str:
    return f"{candles[0].symbol}@{candles[0].interval}"


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
    except FETCH_ERRORS as exc:
        return {}, None, [f"Binance Spot daily skipped: {exc}"]


async def _fetch_live_rows(base_url: str, asset: str) -> tuple[OnChainDailyRow, ...]:
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60) as client:
        return await fetch_asset_metric_rows(client, asset=asset)


def fetch_live_regime_rows(base_url: str, asset: str) -> tuple[OnChainDailyRow, ...]:
    """Single entry point for the live Coin Metrics pull (monkeypatch target)."""
    return asyncio.run(_fetch_live_rows(base_url, asset))


def load_regime_series(
    args: argparse.Namespace,
) -> tuple[tuple[OnChainRegimePoint, ...], str | None, list[str]]:
    """Return (series, skip_reason, notes). Failure → empty series + reason."""
    notes: list[str] = []
    rows: tuple[OnChainDailyRow, ...] = ()
    if args.onchain_json is not None:
        try:
            rows = load_regime_rows_json(args.onchain_json)
        except (OSError, TypeError, ValueError) as exc:
            reason = f"offline Coin Metrics rows unreadable ({args.onchain_json}): {exc}"
            notes.append(f"Coin Metrics community: skipped — {reason}")
            return (), reason, notes
        notes.append(f"Coin Metrics rows loaded offline from {args.onchain_json} ({len(rows)})")
    elif args.live:
        try:
            rows = fetch_live_regime_rows(args.coinmetrics_base_url, args.onchain_asset)
        except FETCH_ERRORS as exc:
            reason = f"Coin Metrics community unreachable: {type(exc).__name__}: {exc}"
            notes.append(f"Coin Metrics community: skipped — {reason}")
            return (), reason, notes
        notes.append(
            f"Coin Metrics community GET {args.coinmetrics_base_url}"
            f"/v4/timeseries/asset-metrics assets={args.onchain_asset} "
            f"metrics=CapMVRVCur,CapMrktCurUSD frequency=1d: {len(rows)} rows"
        )
        if args.save_onchain_json is not None:
            save_regime_rows_json(args.save_onchain_json, rows)
            notes.append(f"Coin Metrics rows saved to {args.save_onchain_json}")
    else:
        reason = "offline run without --onchain-json; every overlay skipped (not zero-filled)"
        notes.append(f"Coin Metrics community: skipped — {reason}")
        return (), reason, notes
    committed = drop_uncommitted_rows(rows)
    if len(committed) != len(rows):
        notes.append(
            f"dropped {len(rows) - len(committed)} uncommitted Coin Metrics row(s) dated "
            "today UTC or later"
        )
    if not committed:
        reason = "Coin Metrics returned no committed rows"
        notes.append(f"Coin Metrics community: skipped — {reason}")
        return (), reason, notes
    series = derive_regime_series(committed)
    return series, None, notes


def run(
    args: argparse.Namespace,
    settings: Settings | None = None,
    *,
    candidates: tuple[SearchCandidate, ...] | None = None,
) -> tuple[Path, Path]:
    settings = settings or Settings()
    if args.live:
        args.live_kraken = True
        args.yahoo = False
        if args.symbol is None:
            args.symbol = list(DEFAULT_KRAKEN_SYMBOLS)
    else:
        args.live_kraken = False
        args.yahoo = False
    kraken_histories, notes = _load_histories(args)
    primary_first, source = primary_first_opened_at(kraken_histories)
    notes.append(f"primary first bar {primary_first.isoformat()} (source={source})")
    notes.append("universe=" + ",".join(UNIVERSE) + " (SOL optional report-only; skip-not-invent)")

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

    series, skip_reason, regime_notes = load_regime_series(args)
    notes.extend(regime_notes)

    fee_bps = (
        args.fee_bps
        if args.fee_bps is not None
        else research_fee_bps(settings.pretrade_fee_bps, settings.paper_fee_bps)
    )
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.pretrade_slippage_bps
    )
    report = run_onchain_regime_search(
        kraken_histories,
        binance_histories,
        series,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=args.starting_equity or settings.paper_starting_nav_usd,
        train_size=args.train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        holdout_fraction=args.holdout_fraction,
        min_trades=args.min_trades,
        base_candidates=candidates,
        binance_source=binance_source,
        regime_skip_reason=skip_reason,
        regime_source_asset=str(args.onchain_asset).lower(),
        data_notes=notes,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(report.model_dump_json(indent=2) + "\n")
    markdown = render_onchain_regime_markdown(report)
    args.output_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        status = "OVERLAY PASSER" if report.any_overlay_passer else "NO OVERLAY PASSER"
        print(
            f"{status}: wrote {args.output_json} and {args.output_md} "
            f"(regime={report.regime_status}; "
            f"overlay_passers={len(report.overlay_passer_ids)}; "
            f"mixed_fail={len(report.mixed_fail_ids)}; "
            f"base_dual_print={len(report.base_dual_print_passer_ids)}; "
            f"ranking_key={report.ranking_key}; "
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
