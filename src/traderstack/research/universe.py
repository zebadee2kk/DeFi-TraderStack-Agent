"""Point-in-time Kraken USD spot universe for wide-universe research (#140).

Two halves, deliberately separate:

1. **Listing** — ``fetch_kraken_usd_pairs`` reduces Kraken's public
   ``GET /0/public/AssetPairs`` payload to bounded, typed
   ``UniversePair`` rows: ``status == "online"``, quote in
   ``{ZUSD, USD}``, a ``wsname`` present, no ``.d`` dark-pool pairs,
   ``XBT -> BTC`` / ``XDG -> DOGE`` aliases, and a frozen exclusion list
   for stablecoins, fiat, tokenised commodities and wrapped duplicates.
   Anything malformed raises ``TypeError`` / ``ValueError`` — nothing is
   coerced silently (same posture as ``parse_binance_kline``).

2. **Membership** — ``liquidity_snapshots`` is pure: on the first day
   of every month it ranks the names that have a full trailing
   ``lookback``-day dollar-volume history **strictly before** the
   snapshot date by median ``close × volume`` and keeps the top ``n``.
   A name with too little history, or a zero median, is skipped for
   that month — never zero-filled, never ranked on a guess. A month
   with no rankable name emits no snapshot (skip, not zero).

Survivorship caveat (stated in every report header): ``AssetPairs`` is
the **current** listing. Delisted names are absent, so the membership
list is frozen from a dated listing and is not a true point-in-time
listing history (that needs the Kraken OHLCVT archive; #133). Within
that frozen list the monthly liquidity ranking is point-in-time.

Written so the ensemble-trend catalog (#137) can import it. Nothing
here reads ``Settings``, touches ``RiskEngine`` or the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median

import httpx
from pydantic import BaseModel, Field

from traderstack.candles import Candle

KRAKEN_ASSET_PAIRS_PATH = "/0/public/AssetPairs"
UNIVERSE_QUOTES: frozenset[str] = frozenset({"ZUSD", "USD"})
BASE_ALIASES: dict[str, str] = {"XBT": "BTC", "XDG": "DOGE"}
UNIVERSE_QUOTE = "USD"

# Frozen before any score. Stablecoins and fiat (no crypto beta to rank),
# tokenised commodities (gold / uranium), and wrapped or liquid-staked
# duplicates of BTC / ETH / SOL (double-counting the same beta). Any base
# that starts or ends with ``USD`` is also excluded (USDT, USDC, USDS,
# USDG, PYUSD, RLUSD, AUSD, ...).
EXCLUDED_BASES: frozenset[str] = frozenset(
    {
        # stablecoins not caught by the USD prefix/suffix rule
        "DAI",
        "MIM",
        "EURC",
        "EURQ",
        "EUROP",
        "EURT",
        "TUSD",
        "FDUSD",
        "GHO",
        "USTABLES",
        # fiat and fiat-pegged tokens
        "EUR",
        "GBP",
        "AUD",
        "CAD",
        "JPY",
        "CHF",
        "MXNB",
        "BRL1",
        "QCAD",
        "TGBP",
        "AUDX",
        # tokenised commodities
        "PAXG",
        "XAUT",
        "XU3O8",
        # wrapped / liquid-staked duplicates
        "WBTC",
        "TBTC",
        "CBBTC",
        "LBTC",
        "WETH",
        "WSTETH",
        "STETH",
        "CBETH",
        "RETH",
        "MSOL",
        "JITOSOL",
        "LSSOL",
        "LSETH",
        "METH",
        "CMETH",
    }
)
EXCLUSION_RULE = (
    "status=online; quote in {ZUSD, USD}; wsname present; no `.d` dark-pool "
    "pairs; XBT->BTC and XDG->DOGE aliases; drop any base that starts or "
    "ends with `USD`; drop the frozen EXCLUDED_BASES list (stablecoins, "
    "fiat, tokenised commodities, wrapped / liquid-staked duplicates)."
)

LIQUIDITY_LOOKBACK_DAYS = 30
LIQUIDITY_TOP_N = 20
LIQUIDITY_FILTER_RULE = "trailing_30d_median_dollar_volume_top_20_pit"
UNIVERSE_SOURCE_NOTE = (
    "Universe listing is Kraken public `GET /0/public/AssetPairs` at the "
    "fetch time recorded in the report header — a CURRENT listing. "
    "Delisted names are absent (survivorship), so membership is frozen "
    "from that dated listing and treated as a fixed candidate list, not "
    "a point-in-time listing history (that needs the Kraken OHLCVT "
    "archive, #133). Within the frozen list, monthly membership is "
    f"point-in-time: `{LIQUIDITY_FILTER_RULE}` uses only bars strictly "
    "before each snapshot date. Dollar volume is close × base volume "
    "from the OHLC print only. A name without a full trailing window, "
    "or with a zero median, is skipped for that month, never zero-filled."
)


@dataclass(frozen=True)
class UniversePair:
    """One bounded, typed row from Kraken's AssetPairs listing."""

    pair_key: str
    altname: str
    wsname: str
    base: str
    canonical: str


def canonical_symbol(base: str) -> str:
    """``XBT`` -> ``BTC/USD``; every other base -> ``BASE/USD``."""
    text = base.strip().upper()
    if not text:
        raise ValueError("base must not be empty")
    return f"{BASE_ALIASES.get(text, text)}/{UNIVERSE_QUOTE}"


def canonical_from_symbol(symbol: str) -> str:
    """Map a venue-local spot symbol (``XBT/USD``, ``BTC-USD``, ``BTCUSDT``,
    ``BTCUSD``) to the canonical ``BASE/USD`` key. Unknown quotes raise."""
    text = symbol.strip().upper().replace("-", "/")
    if "/" in text:
        base, _, quote = text.partition("/")
    else:
        for suffix in ("USDT", "USDC", "USD"):
            if text.endswith(suffix) and len(text) > len(suffix):
                base, quote = text[: -len(suffix)], suffix
                break
        else:
            raise ValueError(f"cannot derive a USD-quoted canonical symbol from {symbol!r}")
    if quote not in {"USD", "USDT", "USDC", "ZUSD"}:
        raise ValueError(f"symbol {symbol!r} is not USD-quoted")
    return canonical_symbol(base)


def is_excluded_base(base: str) -> bool:
    text = base.strip().upper()
    return text in EXCLUDED_BASES or text.startswith("USD") or text.endswith("USD")


def _text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise TypeError(f"AssetPairs field {key!r} must be a string")
    return value


def parse_asset_pairs(payload: object) -> tuple[UniversePair, ...]:
    """Reduce the AssetPairs body to online, USD-quoted, non-excluded pairs."""
    if not isinstance(payload, dict):
        raise TypeError("unexpected Kraken AssetPairs response")
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken AssetPairs error: {errors}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TypeError("unexpected Kraken AssetPairs result shape")
    out: list[UniversePair] = []
    seen: set[str] = set()
    for key, row in result.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            raise TypeError("unexpected Kraken AssetPairs row")
        if key.endswith(".d"):
            continue
        status = row.get("status")
        if status is not None and not isinstance(status, str):
            raise TypeError("AssetPairs status must be a string")
        if status != "online":
            continue
        quote = _text(row, "quote")
        if quote not in UNIVERSE_QUOTES:
            continue
        wsname = row.get("wsname")
        if wsname is None:
            continue
        if not isinstance(wsname, str) or "/" not in wsname:
            raise TypeError("AssetPairs wsname must be BASE/QUOTE")
        altname = _text(row, "altname")
        base = wsname.partition("/")[0].strip().upper()
        if not base:
            raise ValueError("AssetPairs wsname base must not be empty")
        if is_excluded_base(base):
            continue
        canonical = canonical_symbol(base)
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(
            UniversePair(
                pair_key=key,
                altname=altname,
                wsname=wsname,
                base=base,
                canonical=canonical,
            )
        )
    out.sort(key=lambda pair: pair.canonical)
    return tuple(out)


async def fetch_kraken_usd_pairs(client: httpx.AsyncClient) -> tuple[UniversePair, ...]:
    """One call to Kraken's public AssetPairs endpoint, reduced to typed rows."""
    response = await client.get(KRAKEN_ASSET_PAIRS_PATH)
    response.raise_for_status()
    return parse_asset_pairs(response.json())


class UniverseSnapshot(BaseModel):
    """Membership decided on ``snapshot_at`` from bars strictly before it."""

    snapshot_at: datetime
    names: list[str] = Field(default_factory=list)
    median_dollar_volume: dict[str, float] = Field(default_factory=dict)
    candidates_considered: int = 0
    candidates_skipped: int = 0


def dollar_volume_series(candles: tuple[Candle, ...]) -> dict[datetime, float]:
    """``close × base volume`` per bar; zero-volume bars are kept as 0.0 so a
    name that prints no volume ranks last (and is skipped by the snapshot)."""
    return {candle.opened_at: candle.close * candle.volume for candle in candles}


def histories_by_canonical(
    histories: dict[str, tuple[Candle, ...]],
    *,
    interval: str = "1d",
) -> dict[str, tuple[Candle, ...]]:
    """Key every history by canonical ``BASE/USD``; unknown quotes are dropped."""
    out: dict[str, tuple[Candle, ...]] = {}
    for candles in histories.values():
        if not candles or candles[0].interval != interval:
            continue
        try:
            canonical = canonical_from_symbol(candles[0].symbol)
        except ValueError:
            continue
        ordered = tuple(sorted(candles, key=lambda item: item.opened_at))
        existing = out.get(canonical)
        if existing is None or len(ordered) > len(existing):
            out[canonical] = ordered
    return out


def _month_starts(first: datetime, last: datetime, *, snapshot_day: int) -> list[datetime]:
    year, month = first.year, first.month
    out: list[datetime] = []
    while True:
        candidate = datetime(year, month, snapshot_day, tzinfo=UTC)
        if candidate > last:
            break
        if candidate > first:
            out.append(candidate)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


def liquidity_snapshots(
    histories: dict[str, tuple[Candle, ...]],
    *,
    snapshot_day: int = 1,
    lookback: int = LIQUIDITY_LOOKBACK_DAYS,
    top_n: int = LIQUIDITY_TOP_N,
) -> tuple[UniverseSnapshot, ...]:
    """Monthly point-in-time top-``n`` by trailing median dollar volume.

    Only bars with ``opened_at`` strictly before the snapshot date and
    within the trailing ``lookback`` calendar days count. A name needs a
    bar on every one of those days (no gaps) and a positive median to be
    rankable. Empty input -> no snapshots.
    """
    if lookback <= 0 or top_n <= 0:
        raise ValueError("lookback and top_n must be positive")
    by_name = histories_by_canonical(histories)
    if not by_name:
        return ()
    volume_by_name = {name: dollar_volume_series(candles) for name, candles in by_name.items()}
    first = min(candles[0].opened_at for candles in by_name.values())
    last = max(candles[-1].opened_at for candles in by_name.values())
    snapshots: list[UniverseSnapshot] = []
    for snapshot_at in _month_starts(first, last, snapshot_day=snapshot_day):
        window_start = snapshot_at - timedelta(days=lookback)
        ranked: list[tuple[float, str]] = []
        skipped = 0
        for name, series in volume_by_name.items():
            values = [value for ts, value in series.items() if window_start <= ts < snapshot_at]
            if len(values) < lookback:
                skipped += 1
                continue
            med = float(median(values))
            if med <= 0:
                skipped += 1
                continue
            ranked.append((med, name))
        if not ranked:
            continue
        ranked.sort(key=lambda item: (-item[0], item[1]))
        chosen = ranked[:top_n]
        snapshots.append(
            UniverseSnapshot(
                snapshot_at=snapshot_at,
                names=[name for _, name in chosen],
                median_dollar_volume={name: value for value, name in chosen},
                candidates_considered=len(volume_by_name),
                candidates_skipped=skipped,
            )
        )
    return tuple(snapshots)


def snapshot_for(snapshots: tuple[UniverseSnapshot, ...], at: datetime) -> UniverseSnapshot | None:
    """Most recent snapshot decided on or before ``at`` (None before the first)."""
    chosen: UniverseSnapshot | None = None
    for snapshot in snapshots:
        if snapshot.snapshot_at <= at:
            chosen = snapshot
        else:
            break
    return chosen


def eligible_names(
    snapshot: UniverseSnapshot,
    closes: dict[str, dict[datetime, float]],
    *,
    at: datetime,
    min_bars: int,
) -> tuple[str, ...]:
    """Snapshot members with at least ``min_bars`` closes on or before ``at``."""
    out: list[str] = []
    for name in snapshot.names:
        series = closes.get(name)
        if not series:
            continue
        count = sum(1 for ts in series if ts <= at)
        if count >= min_bars:
            out.append(name)
    return tuple(out)
