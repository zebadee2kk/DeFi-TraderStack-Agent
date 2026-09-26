"""HL asilletto cross-sectional funding-rank dual-era dual-print.

Frozen ``fund_xs_rank_*`` catalog. Dual era on Hyperliquid multi-asset
funding from asiletto81 asset_ctxs. Paper-perp fees 5+5 x 2 on turnover.
Never flips ``PAPER_PROMOTE_*``. Distinct from fund_z_harvest / fund_div /
xs-topk / BTC-ETH price RV.
"""

from __future__ import annotations

import csv
import io
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from traderstack.research.edge_series import (
    ASILLETTO81_HL_ARCHIVE_FIRST_UTC,
    ASILLETTO81_HL_ARCHIVE_LAST_UTC,
    _asilletto_decompress,
    _asilletto_yyyymmdd,
)
from traderstack.research.funding_carry import (
    CARRY_LEGS,
    SHORT_STEP_SIZE,
    SHORT_TEST_SIZE,
    SHORT_TRAIN_SIZE,
    choose_walkforward,
)
from traderstack.research.harder_gates import paper_promote_flag_name

FAMILY = "fund_xs_rank"
DEFAULT_FEE_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 5.0
MIN_CROSS_SECTION = 8
MIN_ERA_DAYS = 300
HOLDOUT_FRACTION = 0.20
PAPER_PATH_READY = True
EXECUTABLE_NOTE = (
    "paper-perp multi-asset funding-rank; conceptually via PAPER_PERP_HEDGE; "
    "this CLI does not flip PAPER_PERP_HEDGE or PAPER_PROMOTE_*; not Kraken-spot"
)

# Dual-era freeze (inclusive UTC days) — pinned before any score.
ERA_A_START = datetime(2024, 1, 1, tzinfo=UTC)
ERA_A_END = datetime(2025, 4, 1, tzinfo=UTC)
ERA_B_START = datetime(2025, 4, 2, tzinfo=UTC)
ERA_B_END = datetime(2026, 6, 1, tzinfo=UTC)

# 100 coins present across archive sample days (probe 2026-09-26); BTC+ETH included.
CORE_UNIVERSE: tuple[str, ...] = (
    "AAVE",
    "ACE",
    "ADA",
    "APE",
    "APT",
    "ARB",
    "ARK",
    "ATOM",
    "AVAX",
    "BADGER",
    "BANANA",
    "BCH",
    "BIGTIME",
    "BLUR",
    "BLZ",
    "BNB",
    "BNT",
    "BSV",
    "BTC",
    "CAKE",
    "CANTO",
    "CFX",
    "COMP",
    "CRV",
    "CYBER",
    "DOGE",
    "DOT",
    "DYDX",
    "ETH",
    "FET",
    "FIL",
    "FRIEND",
    "FTM",
    "FTT",
    "FXS",
    "GALA",
    "GAS",
    "GMT",
    "GMX",
    "HPOS",
    "ILV",
    "IMX",
    "INJ",
    "JTO",
    "JUP",
    "KAS",
    "LDO",
    "LINK",
    "LOOM",
    "LTC",
    "MATIC",
    "MAV",
    "MEME",
    "MINA",
    "MKR",
    "NEAR",
    "NEO",
    "NFTI",
    "NTRN",
    "OGN",
    "OP",
    "ORBS",
    "ORDI",
    "OX",
    "PENDLE",
    "POLYX",
    "PYTH",
    "RDNT",
    "REQ",
    "RLB",
    "RNDR",
    "RSR",
    "RUNE",
    "SEI",
    "SHIA",
    "SNX",
    "SOL",
    "STG",
    "STRAX",
    "STX",
    "SUI",
    "SUPER",
    "SUSHI",
    "TIA",
    "TON",
    "TRB",
    "TRX",
    "UNI",
    "UNIBOT",
    "USTC",
    "WIF",
    "WLD",
    "XRP",
    "YGG",
    "ZEN",
    "ZRO",
    "kBONK",
    "kLUNC",
    "kPEPE",
    "kSHIB",
)

# (id, label, mode, k)  mode in {ls, short_top, long_bottom, flat}
RANK_CATALOG: tuple[tuple[str, str, str, int], ...] = (
    ("fund_xs_rank_ls_k3", "dollar-neutral L/S k=3 by funding rank", "ls", 3),
    ("fund_xs_rank_ls_k5", "dollar-neutral L/S k=5 by funding rank", "ls", 5),
    ("fund_xs_rank_ls_k8", "dollar-neutral L/S k=8 by funding rank", "ls", 8),
    ("fund_xs_rank_short_top_k5", "short-only top-5 high funding", "short_top", 5),
    ("fund_xs_rank_long_bottom_k5", "long-only bottom-5 low funding", "long_bottom", 5),
    ("fund_xs_rank_ew_flat", "always-flat control (cannot promote)", "flat", 0),
)
RANK_IDS: tuple[str, ...] = tuple(item[0] for item in RANK_CATALOG)
CONTROL_IDS: frozenset[str] = frozenset({"fund_xs_rank_ew_flat"})

RULES = (
    "Pre-registered HL asilletto cross-sectional funding-rank dual-era "
    "dual-print (frozen before score). Daily last funding per coin from "
    "asilletto81 asset_ctxs; CORE_UNIVERSE=100 incl BTC+ETH; "
    "MIN_CROSS_SECTION=8. Dollar-neutral L/S or single-sleeve catalogs. "
    "Fees 5+5 bps x 2 on gross turnover. Dual eras A/B non-overlapping. "
    "PAPER_PROMOTE_* stays false. Empty set success. Not a retune of "
    "fund_z_harvest / fund_div / xs-topk / price RV."
)


def _utc_day(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return datetime(ts.year, ts.month, ts.day, tzinfo=UTC)


def _compound(returns: list[float]) -> float:
    equity = 1.0
    for item in returns:
        equity *= 1.0 + item
    return equity - 1.0


def _wf_mean(per_print: list[float]) -> float | None:
    if len(per_print) < 2:
        return None
    sizes = choose_walkforward(
        len(per_print),
        train_size=SHORT_TRAIN_SIZE,
        test_size=SHORT_TEST_SIZE,
        step_size=SHORT_STEP_SIZE,
        warmup=0,
    )
    if sizes is None:
        return None
    train, test, step, _warmup = sizes
    fold_totals: list[float] = []
    start = 0
    while True:
        test_start = start + train
        test_end = test_start + test
        if test_end > len(per_print):
            break
        fold_totals.append(_compound(per_print[test_start:test_end]))
        start += step
    if not fold_totals:
        return None
    return sum(fold_totals) / len(fold_totals)


def _compact_funding_path(cache_dir: Path) -> Path:
    # Sibling compact cache next to asset_ctxs (gitignored under var/).
    return cache_dir.parent / "daily_funding_last_core100.json"


def _load_compact_panel(
    compact_path: Path,
    *,
    coins: tuple[str, ...],
    start: datetime,
    end: datetime,
) -> dict[datetime, dict[str, float]] | None:
    import json

    if not compact_path.is_file() or compact_path.stat().st_size <= 0:
        return None
    try:
        raw = json.loads(compact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(raw, dict) or "days" not in raw:
        return None
    want = set(coins)
    start_d = _utc_day(start)
    end_d = _utc_day(end)
    panel: dict[datetime, dict[str, float]] = {}
    for day_key, mapping in raw["days"].items():
        try:
            day = datetime.strptime(day_key, "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if day < start_d or day > end_d:
            continue
        if not isinstance(mapping, dict):
            continue
        filtered = {
            coin: float(val)
            for coin, val in mapping.items()
            if coin in want and isinstance(val, (int, float))
        }
        if filtered:
            panel[day] = filtered
    return panel


def _write_compact_panel(compact_path: Path, panel: dict[datetime, dict[str, float]]) -> None:
    import json

    payload = {
        "universe": list(CORE_UNIVERSE),
        "days": {_asilletto_yyyymmdd(day): vals for day, vals in sorted(panel.items())},
    }
    compact_path.parent.mkdir(parents=True, exist_ok=True)
    compact_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")


def load_asilletto_daily_funding(
    cache_dir: Path,
    *,
    coins: tuple[str, ...] = CORE_UNIVERSE,
    start: datetime = ASILLETTO81_HL_ARCHIVE_FIRST_UTC,
    end: datetime = ASILLETTO81_HL_ARCHIVE_LAST_UTC,
) -> tuple[dict[datetime, dict[str, float]], list[dict[str, str]]]:
    """Load last funding print per UTC day per coin from asiletto lz4 CSVs.

    Missing days / coins are omitted (never zero-filled). Prefers a compact
    JSON cache beside asset_ctxs when present; otherwise builds it.
    """
    notes: list[dict[str, str]] = []
    if not cache_dir.is_dir():
        notes.append(
            {
                "name": "asilletto_dir",
                "status": "skipped",
                "reason": f"missing cache dir {cache_dir}",
            }
        )
        return {}, notes

    compact_path = _compact_funding_path(cache_dir)
    cached = _load_compact_panel(compact_path, coins=coins, start=start, end=end)
    if cached is not None and cached:
        notes.append(
            {
                "name": "asilletto_funding_compact",
                "status": "ok",
                "reason": f"loaded compact cache {compact_path.name}; days={len(cached)}",
            }
        )
        return cached, notes

    want = set(coins)
    panel: dict[datetime, dict[str, float]] = {}
    day = _utc_day(start)
    end_d = _utc_day(end)
    files_read = 0
    files_missing = 0
    while day <= end_d:
        day_path = cache_dir / f"{_asilletto_yyyymmdd(day)}.csv.lz4"
        if not day_path.is_file() or day_path.stat().st_size <= 0:
            files_missing += 1
            day = day + timedelta(days=1)
            continue
        try:
            text = _asilletto_decompress(day_path.read_bytes())
        except (RuntimeError, OSError, UnicodeDecodeError, ValueError) as exc:
            notes.append(
                {
                    "name": f"asilletto_day:{_asilletto_yyyymmdd(day)}",
                    "status": "skipped",
                    "reason": f"decompress failed: {type(exc).__name__}",
                }
            )
            day = day + timedelta(days=1)
            continue
        reader = csv.reader(io.StringIO(text))
        try:
            header = next(reader)
        except StopIteration:
            day = day + timedelta(days=1)
            continue
        header_l = [h.strip().lower() for h in header]
        try:
            coin_i = header_l.index("coin")
            fund_i = header_l.index("funding")
        except ValueError:
            day = day + timedelta(days=1)
            continue
        last: dict[str, float] = {}
        for row in reader:
            if len(row) <= max(coin_i, fund_i):
                continue
            coin = row[coin_i].strip()
            if coin not in want:
                continue
            raw = row[fund_i]
            if raw == "":
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isnan(value):
                continue
            last[coin] = value
        if last:
            panel[day] = last
            files_read += 1
            if files_read % 50 == 0:
                print(
                    f"asilletto funding progress days={files_read} last={_asilletto_yyyymmdd(day)}",
                    flush=True,
                )
        day = day + timedelta(days=1)

    if panel:
        try:
            _write_compact_panel(compact_path, panel)
            notes.append(
                {
                    "name": "asilletto_funding_compact_write",
                    "status": "ok",
                    "reason": f"wrote {compact_path.name}; days={len(panel)}",
                }
            )
        except OSError as exc:
            notes.append(
                {
                    "name": "asilletto_funding_compact_write",
                    "status": "skipped",
                    "reason": f"write failed: {type(exc).__name__}",
                }
            )

    notes.append(
        {
            "name": "asilletto_funding_panel",
            "status": "ok" if files_read else "skipped",
            "reason": (
                f"days_with_funding={files_read}; missing_or_empty_files={files_missing}; "
                f"universe={len(want)}; span={_asilletto_yyyymmdd(start)}→{_asilletto_yyyymmdd(end)}"
            ),
        }
    )
    return panel, notes


def _target_weights(
    funding_by_coin: dict[str, float],
    *,
    mode: str,
    k: int,
) -> dict[str, float]:
    if mode == "flat" or k <= 0:
        return {}
    ranked = sorted(funding_by_coin.items(), key=lambda item: item[1])
    if len(ranked) < MIN_CROSS_SECTION:
        return {}
    k_eff = min(k, len(ranked) // 2) if mode == "ls" else min(k, len(ranked))
    if k_eff <= 0:
        return {}
    weights: dict[str, float] = {}
    if mode == "ls":
        bottom = ranked[:k_eff]
        top = ranked[-k_eff:]
        long_w = 1.0 / (2.0 * k_eff)
        short_w = -1.0 / (2.0 * k_eff)
        for coin, _rate in bottom:
            weights[coin] = long_w
        for coin, _rate in top:
            weights[coin] = short_w
    elif mode == "short_top":
        top = ranked[-k_eff:]
        w = -1.0 / k_eff
        for coin, _rate in top:
            weights[coin] = w
    elif mode == "long_bottom":
        bottom = ranked[:k_eff]
        w = 1.0 / k_eff
        for coin, _rate in bottom:
            weights[coin] = w
    return weights


def _gross_turnover(prev: dict[str, float], curr: dict[str, float]) -> float:
    coins = set(prev) | set(curr)
    return 0.5 * sum(abs(curr.get(c, 0.0) - prev.get(c, 0.0)) for c in coins)


def _daily_returns(
    panel: dict[datetime, dict[str, float]],
    *,
    mode: str,
    k: int,
    fee_bps: float,
    slippage_bps: float,
    legs: int = CARRY_LEGS,
) -> list[tuple[datetime, float]]:
    """Funding-income PnL under target weights; fees on turnover."""
    cost_per_turnover = legs * (fee_bps + slippage_bps) / 10_000.0
    days = sorted(panel)
    prev_w: dict[str, float] = {}
    out: list[tuple[datetime, float]] = []
    for day in days:
        day_fund = {c: panel[day][c] for c in panel[day] if c in CORE_UNIVERSE}
        # Presence gate: BTC+ETH should be in the day panel when available;
        # days without MIN_CROSS_SECTION go flat.
        target = _target_weights(day_fund, mode=mode, k=k)
        turnover = _gross_turnover(prev_w, target)
        fee = turnover * cost_per_turnover
        # Funding accrues on the *previous* open weights for this day's
        # settlement (decision at prior close). Use prev_w for income,
        # then flip to target after paying fees — classic next-open fill.
        income = 0.0
        for coin, weight in prev_w.items():
            rate = day_fund.get(coin)
            if rate is None:
                continue
            # Long pays positive funding; short receives it.
            income += -weight * rate
        out.append((day, income - fee))
        prev_w = target
    return out


def _score_series(
    daily: list[tuple[datetime, float]],
) -> dict[str, float | int | str | None]:
    per_print = [ret for _ts, ret in daily]
    if len(per_print) < 2:
        return {
            "print_count": len(per_print),
            "skipped_reason": "era tape too short",
            "mean_wf_total_return": None,
            "mean_holdout_excess_return": None,
        }
    holdout_size = max(int(len(per_print) * HOLDOUT_FRACTION), 1)
    if holdout_size >= len(per_print):
        holdout_size = max(1, len(per_print) // 5)
    research = per_print[:-holdout_size]
    holdout = per_print[-holdout_size:]
    wf = _wf_mean(research)
    ho = _compound(holdout) if holdout else None
    return {
        "print_count": len(per_print),
        "research_prints": len(research),
        "holdout_prints": len(holdout),
        "skipped_reason": None if wf is not None else "walkforward_insufficient_prints",
        "mean_wf_total_return": wf,
        "mean_holdout_excess_return": ho,
        "full_sample_total_return": _compound(per_print),
    }


def _eligible(metrics: dict[str, float | int | str | None]) -> bool:
    wf = metrics.get("mean_wf_total_return")
    ho = metrics.get("mean_holdout_excess_return")
    return isinstance(wf, float) and wf > 0 and isinstance(ho, float) and ho > 0


def _slice_panel(
    panel: dict[datetime, dict[str, float]],
    start: datetime,
    end: datetime,
) -> dict[datetime, dict[str, float]]:
    start_d = _utc_day(start)
    end_d = _utc_day(end)
    return {day: vals for day, vals in panel.items() if start_d <= day <= end_d}


def _btc_eth_presence(panel: dict[datetime, dict[str, float]]) -> dict[str, float | int]:
    if not panel:
        return {"days": 0, "btc_days": 0, "eth_days": 0, "both_frac": 0.0}
    btc = sum(1 for vals in panel.values() if "BTC" in vals)
    eth = sum(1 for vals in panel.values() if "ETH" in vals)
    both = sum(1 for vals in panel.values() if "BTC" in vals and "ETH" in vals)
    n = len(panel)
    return {
        "days": n,
        "btc_days": btc,
        "eth_days": eth,
        "both_days": both,
        "both_frac": both / n if n else 0.0,
    }


class RankCandidate(BaseModel):
    candidate_id: str
    family: str = FAMILY
    label: str
    mode: str
    k: int
    era_a: dict[str, float | int | str | None] = Field(default_factory=dict)
    era_b: dict[str, float | int | str | None] = Field(default_factory=dict)
    eligible_a: bool = False
    eligible_b: bool = False
    eligible: bool = False
    is_control: bool = False
    executable: str = EXECUTABLE_NOTE


class FundXsRankReport(BaseModel):
    generated_at: datetime
    print_kind: Literal["single_print", "dual_print", "unavailable"]
    primary_era: str = "era_a_2024-01-01_2025-04-01"
    second_era: str = "era_b_2025-04-02_2026-06-01"
    funding_venue: str = "hyperliquid_asilletto"
    fee_bps: float
    slippage_bps: float
    legs: int = CARRY_LEGS
    min_cross_section: int = MIN_CROSS_SECTION
    universe_size: int = len(CORE_UNIVERSE)
    keep_flag_false: bool = True
    can_promote: bool = False
    paper_path_ready: bool = PAPER_PATH_READY
    executable_note: str = EXECUTABLE_NOTE
    core_ids: list[str] = Field(default_factory=lambda: list(RANK_IDS))
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    dual_print_passers: int = 0
    rules: str = RULES
    history_notes: list[dict[str, str]] = Field(default_factory=list)
    presence_a: dict[str, float | int] = Field(default_factory=dict)
    presence_b: dict[str, float | int] = Field(default_factory=dict)
    candidates: list[RankCandidate] = Field(default_factory=list)
    recommended_promote_flag: str | None = None

    def model_dump_json_safe(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def run_fund_xs_rank(
    panel: dict[datetime, dict[str, float]],
    *,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    history_notes: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> FundXsRankReport:
    generated = now or datetime.now(UTC)
    notes = list(history_notes or [])

    # Universe richness gate
    coin_days: dict[str, int] = {}
    for vals in panel.values():
        for coin in vals:
            if coin in CORE_UNIVERSE:
                coin_days[coin] = coin_days.get(coin, 0) + 1
    long_coins = sorted(c for c, n in coin_days.items() if n >= MIN_ERA_DAYS)
    notes.append(
        {
            "name": "universe_long_tapes",
            "status": "ok" if len(long_coins) >= MIN_CROSS_SECTION else "skipped",
            "reason": (
                f"coins_with>={MIN_ERA_DAYS}_days={len(long_coins)}; "
                f"btc={'BTC' in long_coins}; eth={'ETH' in long_coins}"
            ),
        }
    )
    if len(long_coins) < MIN_CROSS_SECTION or "BTC" not in long_coins or "ETH" not in long_coins:
        notes.append(
            {
                "name": "probe_gate",
                "status": "skipped",
                "reason": "need >=8 long-tape coins including BTC+ETH",
            }
        )
        return FundXsRankReport(
            generated_at=generated,
            print_kind="unavailable",
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
        )

    panel_a = _slice_panel(panel, ERA_A_START, ERA_A_END)
    panel_b = _slice_panel(panel, ERA_B_START, ERA_B_END)
    presence_a = _btc_eth_presence(panel_a)
    presence_b = _btc_eth_presence(panel_b)
    notes.append(
        {
            "name": "era_a_panel",
            "status": "ok" if len(panel_a) >= MIN_ERA_DAYS else "skipped",
            "reason": f"days={len(panel_a)}; both_frac={presence_a.get('both_frac')}",
        }
    )
    notes.append(
        {
            "name": "era_b_panel",
            "status": "ok" if len(panel_b) >= MIN_ERA_DAYS else "skipped",
            "reason": f"days={len(panel_b)}; both_frac={presence_b.get('both_frac')}",
        }
    )
    if len(panel_a) < MIN_ERA_DAYS or len(panel_b) < MIN_ERA_DAYS:
        return FundXsRankReport(
            generated_at=generated,
            print_kind="unavailable",
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
            presence_a=presence_a,
            presence_b=presence_b,
        )

    # BTC+ETH membership gate: both must appear on >=80% of era days
    if float(presence_a.get("both_frac", 0)) < 0.80 or float(presence_b.get("both_frac", 0)) < 0.80:
        notes.append(
            {
                "name": "btc_eth_presence",
                "status": "skipped",
                "reason": "BTC+ETH both_frac < 0.80 in an era",
            }
        )
        return FundXsRankReport(
            generated_at=generated,
            print_kind="unavailable",
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            history_notes=notes,
            presence_a=presence_a,
            presence_b=presence_b,
        )

    candidates: list[RankCandidate] = []
    for candidate_id, label, mode, k in RANK_CATALOG:
        daily_a = _daily_returns(
            panel_a, mode=mode, k=k, fee_bps=fee_bps, slippage_bps=slippage_bps
        )
        daily_b = _daily_returns(
            panel_b, mode=mode, k=k, fee_bps=fee_bps, slippage_bps=slippage_bps
        )
        metrics_a = _score_series(daily_a)
        metrics_b = _score_series(daily_b)
        elig_a = _eligible(metrics_a) and candidate_id not in CONTROL_IDS
        elig_b = _eligible(metrics_b) and candidate_id not in CONTROL_IDS
        candidates.append(
            RankCandidate(
                candidate_id=candidate_id,
                label=label,
                mode=mode,
                k=k,
                era_a=metrics_a,
                era_b=metrics_b,
                eligible_a=elig_a,
                eligible_b=elig_b,
                eligible=elig_a and elig_b,
                is_control=candidate_id in CONTROL_IDS,
            )
        )

    passers = sorted(c.candidate_id for c in candidates if c.eligible)
    return FundXsRankReport(
        generated_at=generated,
        print_kind="dual_print",
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        dual_print_passer_ids=passers,
        dual_print_passers=len(passers),
        history_notes=notes,
        presence_a=presence_a,
        presence_b=presence_b,
        candidates=candidates,
        can_promote=False,
        keep_flag_false=True,
        recommended_promote_flag=(paper_promote_flag_name(passers[0]) if passers else None),
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def render_fund_xs_rank_markdown(report: FundXsRankReport) -> str:
    lines = [
        "# HL asilletto cross-sectional funding-rank dual-era dual-print",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Print kind: **{report.print_kind}**. funding=`{report.funding_venue}`; "
            f"eras=`{report.primary_era}` x `{report.second_era}`; "
            f"universe={report.universe_size}; min_cross_section={report.min_cross_section}; "
            f"can_promote=`{str(report.can_promote).lower()}`; "
            f"keep_flag_false=`{str(report.keep_flag_false).lower()}`; "
            f"dual_print_passers=`{report.dual_print_passers}`; "
            f"paper_path_ready=`{str(report.paper_path_ready).lower()}`"
        ),
        "",
        "## Rules",
        "",
        report.rules,
        "",
        f"Executability: {report.executable_note}",
        "",
        (
            f"Fees: {report.fee_bps:g}+{report.slippage_bps:g} bps x {report.legs} legs "
            "on gross turnover `0.5*Σ|Δw|`."
        ),
        "",
        "## History notes",
        "",
    ]
    for note in report.history_notes:
        lines.append(
            f"- `{note.get('name', '')}` **{note.get('status', '')}**: {note.get('reason', '')}"
        )
    lines.extend(
        [
            "",
            "## BTC+ETH presence",
            "",
            f"- Era A: {report.presence_a}",
            f"- Era B: {report.presence_b}",
            "",
            "## Candidates",
            "",
            "| id | eraA WF | eraA HO | eligA | eraB WF | eraB HO | eligB | dual |",
            "| --- | ---: | ---: | :---: | ---: | ---: | :---: | :---: |",
        ]
    )
    for row in report.candidates:
        wf_a = row.era_a.get("mean_wf_total_return")
        ho_a = row.era_a.get("mean_holdout_excess_return")
        wf_b = row.era_b.get("mean_wf_total_return")
        ho_b = row.era_b.get("mean_holdout_excess_return")
        lines.append(
            f"| `{row.candidate_id}` | {_pct(wf_a if isinstance(wf_a, float) else None)} | "
            f"{_pct(ho_a if isinstance(ho_a, float) else None)} | "
            f"{'yes' if row.eligible_a else 'no'} | "
            f"{_pct(wf_b if isinstance(wf_b, float) else None)} | "
            f"{_pct(ho_b if isinstance(ho_b, float) else None)} | "
            f"{'yes' if row.eligible_b else 'no'} | "
            f"{'yes' if row.eligible else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Dual-print passers",
            "",
            (
                ", ".join(f"`{i}`" for i in report.dual_print_passer_ids)
                if report.dual_print_passer_ids
                else "**0** dual-print passers."
            ),
            "",
            "## Promotion decision",
            "",
            (
                "**No candidate is auto-enabled.** can_promote=false; "
                "keep_flag_false=true. "
                f"Recommended pin name (defaults false if added later): "
                f"`{report.recommended_promote_flag or 'n/a'}`. "
                "No live path. PAPER_PROMOTE_* untouched."
            ),
            "",
        ]
    )
    return "\n".join(lines)
