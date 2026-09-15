"""``traderstack-polymarket-weather-resolve``: resolve the PIT tape (#141).

Runs daily from the operator host. For every tape market whose local close
plus a settle lag has passed, it pairs the pre-registered decision row with
the **official station high** (IEM ASOS primary, NCEI GHCN-Daily
cross-check), writes a resolved JSONL row, and emits one
``ResolvedWeatherRow`` JSON array per calendar month for
``traderstack-polymarket-weather-eval --resolved``.

Fail-closed rules, fixed here rather than per run:

* a row whose observation or forecast is not strictly before ``close_at`` is
  dropped as look-ahead;
* an unmatched or disagreeing station pair is ``station_unmatched`` — the
  row is not emitted, and Gamma's settlement ``outcomePrices`` are never
  used as a substitute;
* one print per calendar month, so prints are independent by disjoint event
  dates rather than by re-scoring the same rows against another source.

No PnL is computed here and no ``PAPER_PROMOTE_*`` pin is ever written. An
empty tape exits 0 with an honest rows=0 report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from traderstack.config import Settings
from traderstack.logging_config import configure_logging
from traderstack.polymarket.cities import CITY_CATALOG
from traderstack.polymarket.service import _build_registries, require_paper_trading_mode
from traderstack.polymarket.stations import (
    GHCN_SOURCE,
    IEM_SOURCE,
    GhcnDailyClient,
    IemAsosClient,
    StationFetch,
    resolve_official_high,
)
from traderstack.polymarket.tape import (
    PolymarketWeatherResolvedTape,
    PolymarketWeatherTape,
    ResolvedTapeRow,
    SourceStatus,
    TapeStatus,
    render_tape_status_markdown,
    select_decision_rows,
    split_prints_by_month,
)

DEFAULT_PRINT_DIR = Path("var/ops/polymarket_weather_prints")
DEFAULT_OUTPUT_MD = Path("docs/artifacts/strategy-search/polymarket-weather-tape.md")


@dataclass
class ResolveOutcome:
    status: TapeStatus
    markdown: str
    print_paths: tuple[Path, Path | None]
    prints_written: tuple[Path, ...]


async def resolve_tape(
    settings: Settings,
    *,
    tape: PolymarketWeatherTape,
    resolved_tape: PolymarketWeatherResolvedTape,
    iem: IemAsosClient,
    ghcn: GhcnDailyClient,
    settle_lag_hours: float,
    min_lead_hours: float,
    station_tolerance_f: float,
    now: datetime | None = None,
) -> tuple[TapeStatus, tuple[ResolvedTapeRow, ...]]:
    require_paper_trading_mode(settings)
    moment = now or datetime.now(UTC)
    observations = tape.read()
    decision_rows = select_decision_rows(observations, min_lead_hours=min_lead_hours)
    already = resolved_tape.resolved_market_ids()

    per_stage = {"awaiting_close": 0, "already_resolved": 0, "newly_resolved": 0}
    drop_reasons: dict[str, int] = {}
    fetches: list[StationFetch] = []

    for row in decision_rows:
        if row.market_id in already:
            per_stage["already_resolved"] += 1
            continue
        if moment < row.close_at + timedelta(hours=settle_lag_hours):
            per_stage["awaiting_close"] += 1
            continue
        city = CITY_CATALOG.get(row.city_slug)
        if city is None:
            drop_reasons["city_not_in_catalog"] = drop_reasons.get("city_not_in_catalog", 0) + 1
            continue
        official = await resolve_official_high(
            city,
            row.event_date,
            iem=iem,
            ghcn=ghcn,
            tolerance_f=station_tolerance_f,
        )
        fetches.extend(official.fetches)
        if official.status != "ok" or official.high_f is None:
            key = f"station_unmatched:{official.reason}"
            drop_reasons[key] = drop_reasons.get(key, 0) + 1
            continue
        resolved_tape.append_sync(
            ResolvedTapeRow(
                **row.model_dump(),
                official_high_f=official.high_f,
                station_id=official.station_id,
                resolution_source=official.resolution_source,
                crosscheck_high_f=official.crosscheck_high_f,
                crosscheck_source=official.crosscheck_source,
                resolution_mismatch=official.mismatch_f,
                resolved_at=moment,
            )
        )
        per_stage["newly_resolved"] += 1

    resolved_rows = resolved_tape.read()
    prints = split_prints_by_month(resolved_rows)
    eligible = sum(len(rows) for rows in prints.values())
    per_city: dict[str, int] = {}
    for row in decision_rows:
        per_city[row.city_slug] = per_city.get(row.city_slug, 0) + 1
    dates = [row.event_date for row in decision_rows]

    status = TapeStatus(
        generated_at=moment,
        tape_path=str(tape.path),
        resolved_path=str(resolved_tape.path),
        observations=len(observations),
        markets=len({row.market_id for row in observations}),
        decision_rows=len(decision_rows),
        resolved_rows=len(resolved_rows),
        eligible_rows=eligible,
        window_start=min(dates) if dates else None,
        window_end=max(dates) if dates else None,
        per_city=per_city,
        per_stage=per_stage,
        drop_reasons=drop_reasons,
        prints={key: len(rows) for key, rows in prints.items()},
        sources=_source_statuses(fetches),
        fee_haircut=settings.polymarket_weather_fee_haircut,
        min_lead_hours=min_lead_hours,
        settle_lag_hours=settle_lag_hours,
        station_tolerance_f=station_tolerance_f,
        print_kind="dual_print" if len(prints) >= 2 else "single_print",
        notes=_notes(len(resolved_rows), len(prints)),
    )
    return status, resolved_rows


def _source_statuses(fetches: list[StationFetch]) -> list[SourceStatus]:
    """One ok/skipped line per series actually probed. Never invented."""

    statuses: list[SourceStatus] = []
    for source in (IEM_SOURCE, GHCN_SOURCE):
        rows = [item for item in fetches if item.source == source]
        if not rows:
            statuses.append(
                SourceStatus(
                    name=source,
                    status="skipped",
                    detail="not probed in this run (no row was due for resolution)",
                )
            )
            continue
        ok = [item for item in rows if item.status == "ok"]
        skipped = [item for item in rows if item.status == "skipped"]
        detail = f"{len(ok)} ok / {len(skipped)} skipped"
        if skipped:
            detail += f"; first skip: {skipped[0].reason}"
        statuses.append(SourceStatus(name=source, status="ok" if ok else "skipped", detail=detail))
    return statuses


def _notes(resolved: int, print_count: int) -> list[str]:
    notes = [
        (
            "Point-in-time by construction: every row's CLOB mid and NWP high "
            "were read while the market was open. Settlement prices are never "
            "read back as a mid (that would be look-ahead)."
        ),
        (
            "Resolution is the IEM ASOS daily maximum with an NCEI GHCN-Daily "
            "cross-check. Polymarket itself resolves on the NOAA hourly "
            "'Temp' maximum at the same airport, which can differ by a degree; "
            "rows where the two free sources disagree beyond the tolerance are "
            "dropped rather than scored on the flattering one."
        ),
        (
            "Celsius-resolved cities (London, Seoul, Toronto, Zhengzhou, "
            "Singapore, ...) are catalogued but skipped as unit_unsupported: "
            "single-degree °C buckets need a unit-aware bucket model."
        ),
        (
            "`PAPER_PROMOTE_POLYMARKET_WEATHER` is not a `Settings` field and "
            "is not added by this CLI. No PAPER_PROMOTE_* default changes."
        ),
    ]
    if resolved == 0:
        notes.append(
            "rows=0. The tape has to be collected while markets are open, so a "
            "freshly built tape is legitimately empty. An empty print is the "
            "successful outcome; nothing is back-filled from settlement."
        )
    if print_count < 2:
        notes.append(
            "Fewer than two monthly prints: the dual-print bar cannot be "
            "attempted, and a single print can never promote."
        )
    return notes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve the Polymarket weather point-in-time tape against official "
            "station highs and emit per-month print packs for the fee-aware "
            "evaluator. Report-only: no PnL, no CLOB orders, no promote pin."
        )
    )
    parser.add_argument("--tape-path", default=None)
    parser.add_argument("--resolved-path", default=None)
    parser.add_argument("--settle-lag-hours", type=float, default=None)
    parser.add_argument("--min-lead-hours", type=float, default=0.0)
    parser.add_argument("--station-tolerance-f", type=float, default=1.0)
    parser.add_argument("--emit-resolved-dir", type=Path, default=DEFAULT_PRINT_DIR)
    parser.add_argument(
        "--output-json", type=Path, default=Path("var/ops/polymarket_weather_tape.json")
    )
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--stdout-md", action="store_true")
    return parser


async def _run(args: argparse.Namespace, settings: Settings | None = None) -> ResolveOutcome:
    settings = settings or Settings()
    require_paper_trading_mode(settings)
    configure_logging(settings)
    tape = PolymarketWeatherTape(Path(args.tape_path or settings.polymarket_weather_tape_path))
    resolved_tape = PolymarketWeatherResolvedTape(
        Path(args.resolved_path or settings.polymarket_weather_resolved_path)
    )
    registries = _build_registries(settings)
    iem = IemAsosClient(
        base_url=settings.polymarket_weather_iem_base_url,
        registry=registries["iem"],
        timeout_seconds=settings.provider_timeout_seconds,
    )
    ghcn = GhcnDailyClient(
        base_url=settings.polymarket_weather_ghcn_base_url,
        registry=registries["ghcn"],
        timeout_seconds=settings.provider_timeout_seconds,
    )
    settle_lag = (
        args.settle_lag_hours
        if args.settle_lag_hours is not None
        else settings.polymarket_weather_settle_lag_hours
    )
    status, resolved_rows = await resolve_tape(
        settings,
        tape=tape,
        resolved_tape=resolved_tape,
        iem=iem,
        ghcn=ghcn,
        settle_lag_hours=settle_lag,
        min_lead_hours=args.min_lead_hours,
        station_tolerance_f=args.station_tolerance_f,
    )
    prints = split_prints_by_month(resolved_rows)
    written: list[Path] = []
    if prints:
        args.emit_resolved_dir.mkdir(parents=True, exist_ok=True)
        for key, rows in prints.items():
            path = args.emit_resolved_dir / f"{key}.json"
            payload: list[dict[str, Any]] = [row.model_dump(mode="json") for row in rows]
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written.append(path)
    markdown = render_tape_status_markdown(status)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown, encoding="utf-8")
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(status.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return ResolveOutcome(
        status=status,
        markdown=markdown,
        print_paths=(args.output_json, args.output_md),
        prints_written=tuple(written),
    )


def run(args: argparse.Namespace, settings: Settings | None = None) -> ResolveOutcome:
    return asyncio.run(_run(args, settings))


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    outcome = run(args)
    if args.stdout_md:
        print(outcome.markdown)
    else:
        status = outcome.status
        print(
            "WEATHER TAPE (report-only): "
            f"observations={status.observations} decision_rows={status.decision_rows} "
            f"resolved_rows={status.resolved_rows} prints={len(status.prints)} "
            f"({status.print_kind}); wrote {outcome.print_paths[1]}. "
            "No PnL here; PAPER_PROMOTE_* flags are unchanged. Empty is success."
        )


if __name__ == "__main__":
    main()
