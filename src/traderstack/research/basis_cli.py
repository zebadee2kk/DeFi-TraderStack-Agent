"""`traderstack-download-basis`: OKX + Binance Vision daily mark−index basis (#134).

Writes one ``[{opened_at, value}]`` JSON series per venue and symbol under
``--out-dir`` (default ``var/research/basis/<venue>/<SYMBOL>_basis_1d.json``)
in the shape ``traderstack-funding-carry --basis-dir`` and
``search_cli._parse_feature_series`` read, plus a probe table (venue,
source, first, last, days, gaps, bounded skips, truncation) and the
OKX × Binance Vision aligned-day count per symbol.

Skip-not-invent: an unreachable venue, a 403 after backoff, a checksum
mismatch, or an empty window is recorded as a skip and the process still
exits 0 — an empty research result is a successful result. Forbidden
constructions (funding premium, last-trade candles, funding-implied
basis) are refused in the adapters, not here. No Settings field, no
``PAPER_PROMOTE_*`` flip, no live path.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx

from traderstack.research.basis import (
    BasisProbeRow,
    align_basis_days,
    probe_row_from_fetch,
    utc_day,
    write_feature_series_json,
    yesterday_utc,
)
from traderstack.research.basis_binance_vision import (
    BINANCE_VISION_BASE,
    DEFAULT_VISION_CACHE_DIR,
    fetch_binance_vision_basis,
)
from traderstack.research.basis_okx import fetch_okx_basis
from traderstack.research.edge_series import OKX_BASE, EdgeSeriesFetch

BASIS_VENUES: tuple[str, ...] = ("okx", "binance_vision")
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD")
DEFAULT_SINCE_UTC = datetime(2020, 1, 1, tzinfo=UTC)
DEFAULT_OUT_DIR = Path("var/research/basis")
DEFAULT_REPORT_MD = Path("docs/artifacts/strategy-search/pit-basis-second-venue.md")
DUAL_BASIS_MIN_ALIGNED_DAYS = 720


def basis_series_path(out_dir: Path, venue: str, symbol: str) -> Path:
    return out_dir / venue / f"{symbol.upper().replace('/', '')}_basis_1d.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download daily point-in-time mark−index basis from OKX "
            "(history-mark-price-candles − history-index-candles) and "
            "Binance Vision (markPriceKlines − indexPriceKlines zips, sha256 "
            "verified) into the [{opened_at, value}] JSON that "
            "traderstack-funding-carry --basis-dir reads. Skip-not-invent: "
            "premium / last-trade / funding-implied constructions are refused; "
            "a missing day is a skip, never a zero; an unreachable venue exits 0 "
            "with a recorded skip. Research only; no PAPER_PROMOTE_* flip."
        )
    )
    parser.add_argument(
        "--venue",
        action="append",
        choices=BASIS_VENUES,
        default=None,
        help="venue to pull (repeat; default both)",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="symbol to pull (repeat; default BTC/USD ETH/USD)",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="ISO8601 or unix seconds (UTC day open); default 2020-01-01",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="ISO8601 or unix seconds (UTC day open); default yesterday UTC",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_VISION_CACHE_DIR)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--stdout-md", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def parse_day(value: str | None, *, default: datetime) -> datetime:
    if value is None:
        return utc_day(default)
    try:
        return utc_day(datetime.fromtimestamp(int(value), tz=UTC))
    except ValueError:
        pass
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return utc_day(parsed)


async def download_basis(
    venues: tuple[str, ...],
    symbols: tuple[str, ...],
    *,
    since: datetime,
    until: datetime,
    cache_dir: Path,
    timeout: float = 30.0,
) -> dict[str, dict[str, EdgeSeriesFetch]]:
    """Fetch each venue independently (own client; never blended)."""
    results: dict[str, dict[str, EdgeSeriesFetch]] = {venue: {} for venue in venues}
    if "okx" in venues:
        async with httpx.AsyncClient(base_url=OKX_BASE, timeout=timeout) as client:
            for symbol in symbols:
                results["okx"][symbol.upper()] = await fetch_okx_basis(
                    symbol, client=client, since=since, until=until
                )
    if "binance_vision" in venues:
        async with httpx.AsyncClient(
            base_url=BINANCE_VISION_BASE, timeout=max(timeout, 60.0), follow_redirects=True
        ) as client:
            for symbol in symbols:
                results["binance_vision"][symbol.upper()] = await fetch_binance_vision_basis(
                    symbol, client=client, since=since, until=until, cache_dir=cache_dir
                )
    return results


def build_probe_rows(results: dict[str, dict[str, EdgeSeriesFetch]]) -> list[BasisProbeRow]:
    rows: list[BasisProbeRow] = []
    for venue in sorted(results):
        for symbol in sorted(results[venue]):
            rows.append(probe_row_from_fetch(venue, symbol, results[venue][symbol]))
    return rows


def pairwise_alignment(
    results: dict[str, dict[str, EdgeSeriesFetch]],
    *,
    first_venue: str = "okx",
    second_venue: str = "binance_vision",
) -> list[dict[str, str]]:
    """Aligned-day counts between two venues per symbol (skip when either is absent)."""
    out: list[dict[str, str]] = []
    first_map = results.get(first_venue, {})
    second_map = results.get(second_venue, {})
    for symbol in sorted(set(first_map) | set(second_map)):
        left = first_map.get(symbol)
        right = second_map.get(symbol)
        if left is None or right is None or left.status != "ok" or right.status != "ok":
            out.append(
                {
                    "symbol": symbol,
                    "pair": f"{first_venue}×{second_venue}",
                    "aligned_days": "0",
                    "dropped_first": "0",
                    "dropped_second": "0",
                    "first": "",
                    "last": "",
                    "dual_basis": "no",
                    "note": "one or both series skipped — not aligned, not filled",
                }
            )
            continue
        aligned_left, _aligned_right, dropped_left, dropped_right = align_basis_days(
            left.points, right.points
        )
        out.append(
            {
                "symbol": symbol,
                "pair": f"{first_venue}×{second_venue}",
                "aligned_days": str(len(aligned_left)),
                "dropped_first": str(dropped_left),
                "dropped_second": str(dropped_right),
                "first": aligned_left[0][0].date().isoformat() if aligned_left else "",
                "last": aligned_left[-1][0].date().isoformat() if aligned_left else "",
                "dual_basis": ("yes" if len(aligned_left) >= DUAL_BASIS_MIN_ALIGNED_DAYS else "no"),
                "note": "",
            }
        )
    return out


def render_probe_markdown(
    rows: list[BasisProbeRow],
    alignment: list[dict[str, str]],
    *,
    since: datetime,
    until: datetime,
    generated_at: datetime,
    written: dict[str, str],
) -> str:
    ok_rows = [row for row in rows if row.status == "ok"]
    dual = all(item["dual_basis"] == "yes" for item in alignment) and bool(alignment)
    lines = [
        "# PIT basis — second venue probe (OKX + Binance Vision mark−index)",
        "",
        (
            f"Generated: {generated_at.isoformat()} by `traderstack-download-basis`. "
            "Paper / research only."
        ),
        "",
        (
            f"Window requested: **{since.date()} → {until.date()}** (UTC day opens; "
            "today's bar is never included)."
        ),
        "",
        (
            "Construction: daily **mark close − index close, over index close**, "
            "labelled by the UTC day open of that bar. OKX "
            "`history-mark-price-candles` − `history-index-candles` (USDT-margined swap "
            "vs USDT index; `confirm==1` rows only). Binance Vision USDT-M "
            "`markPriceKlines` − `indexPriceKlines` (sha256 `.CHECKSUM` verified per zip). "
            "Quote is **USDT** on both venues, not USD."
        ),
        "",
        (
            "Refused in code: `premium` / `premiumIndexKlines` (funding-formula premium), "
            "`klines` / `market/candles` (last-trade), `fundingRate` (funding-implied). "
            "A day missing on either side of a venue is a **skip**, never a zero. "
            "An unreachable venue is a **skip** and this report says so."
        ),
        "",
        "## Probe table",
        "",
        "| venue | symbol | status | first | last | days | gaps | bounded skips | truncated | source |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | :---: | --- |",
    ]
    if not rows:
        lines.append("| *(no venue requested)* |  |  |  |  |  |  |  |  |  |")
    for row in rows:
        lines.append(
            f"| {row.venue} | {row.symbol} | **{row.status}** | {row.first or '—'} | "
            f"{row.last or '—'} | {row.days} | {row.gaps} | {row.bounded_skips} | "
            f"{'yes' if row.truncated else 'no'} | `{row.source}` |"
        )
    lines.extend(["", "## OKX × Binance Vision alignment (per symbol)", ""])
    lines.append(
        "| symbol | pair | aligned days | dropped OKX-only | dropped Vision-only | first | last | ≥720 aligned |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | --- | --- | :---: |")
    if not alignment:
        lines.append("| *(nothing to align)* |  |  |  |  |  |  |  |")
    for item in alignment:
        lines.append(
            f"| {item['symbol']} | {item['pair']} | {item['aligned_days']} | "
            f"{item['dropped_first']} | {item['dropped_second']} | {item['first'] or '—'} | "
            f"{item['last'] or '—'} | **{item['dual_basis']}** |"
        )
    lines.extend(
        [
            "",
            (
                f"Dual basis (two independent venues, ≥{DUAL_BASIS_MIN_ALIGNED_DAYS} aligned "
                f"daily bars on every symbol): **{'yes' if dual else 'no'}**."
            ),
            "",
            "## Notes per series",
            "",
        ]
    )
    for row in rows:
        lines.append(f"- `{row.venue}:{row.symbol}` **{row.status}** — {row.reason}")
    if not rows:
        lines.append("- (none)")
    lines.extend(["", "## Files written", ""])
    if written:
        for key in sorted(written):
            lines.append(f"- `{key}` → `{written[key]}`")
    else:
        lines.append("- none (every requested series was skipped; empty is success)")
    if not ok_rows:
        lines.extend(
            [
                "",
                (
                    "**Result: UNAVAILABLE** — no venue returned a verified mark−index "
                    "series for this window. Nothing was invented."
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Honesty",
            "",
            (
                "- These are USDT-perp vs USDT-index prints on OKX and Binance; they are not "
                "a Kraken USD series and are labelled as such wherever they are scored."
            ),
            (
                "- Basis for day D is the day-D close and is applied only to the day-D "
                "hedged-carry PnL (close D−1 → close D); it never enters the harvest decision."
            ),
            "- No `PAPER_PROMOTE_*` default changes. No Settings field. No live path.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    venues = tuple(dict.fromkeys(args.venue)) if args.venue else BASIS_VENUES
    symbols = tuple(args.symbol) if args.symbol else DEFAULT_SYMBOLS
    since = parse_day(args.since, default=DEFAULT_SINCE_UTC)
    until = parse_day(args.until, default=yesterday_utc())
    if since > until:
        raise SystemExit(f"--since {since.date()} is after --until {until.date()}")
    results = asyncio.run(
        download_basis(
            venues,
            symbols,
            since=since,
            until=until,
            cache_dir=args.cache_dir,
            timeout=args.timeout,
        )
    )
    written: dict[str, str] = {}
    for venue, by_symbol in results.items():
        for symbol, fetch in by_symbol.items():
            if fetch.status != "ok" or not fetch.points:
                continue
            path = basis_series_path(args.out_dir, venue, symbol)
            write_feature_series_json(path, fetch.points)
            written[f"{venue}:{symbol}"] = str(path)
    rows = build_probe_rows(results)
    alignment = pairwise_alignment(results)
    markdown = render_probe_markdown(
        rows,
        alignment,
        since=since,
        until=until,
        generated_at=datetime.now(UTC),
        written=written,
    )
    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_md.write_text(markdown)
    if args.stdout_md:
        print(markdown)
    else:
        ok = sum(1 for row in rows if row.status == "ok")
        print(
            f"wrote {len(written)} basis series under {args.out_dir} "
            f"({ok}/{len(rows)} series ok; skipped series are recorded, not invented); "
            f"probe table → {args.report_md}"
        )
    return 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
