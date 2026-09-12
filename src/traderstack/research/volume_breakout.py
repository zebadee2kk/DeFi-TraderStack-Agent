"""Volume-confirmed breakout dual-print (BTC+ETH; SOL optional).

Pre-registered before any live pull (do not retune after seeing PnL).

Treatment (frozen): this is **not** a Donchian N retune (#118).
Every promote-eligible name requires a **volume gate**. On each
asset, a long-only / long-short breakout compares close[t] to the
**prior** N-day channel — max(high) and min(low) of bars [t-N, t),
never including bar t's high/low in the breakout level — **and**
requires volume[t] > V-day volume SMA × mult. V is frozen at 20.
Volume SMA is computed on bars [t-V, t) (``volume_sma_through_t_minus_1``);
bar t is never in the SMA. A missing or non-positive volume skips
that bar (hold previous for breakout names; omit for surge names)
and is never invented. Quote volume is never substituted for base
volume. If a venue's daily bars lack usable volume, volume names
fail closed on that venue.

Long-only names enter long when close[t] > prior high **and** the
volume gate fires, and exit to flat when close[t] < prior N-day
low (exit does not require volume). Long/short names use the same
volume gate to enter or flip; an unconfirmed opposite-band break
holds the previous side. Between the bands the previous side is
held (start flat).

Volume-surge names have **no** channel: long when volume[t] >
SMA(V)×mult **and** close[t] > close[t−1]; flat otherwise.

Fill at t+1 open (same convention as donchian / tsmom). Each asset
is scored on its own OHLC. A missing/short series is skipped,
never zero-filled.

Multi-asset combined bar (frozen before scoring): the same #96+A+B+C
harder gates as #104 on **BTC and ETH**. SOL walk-forward and holdout
are reported when the series exists and are **not** a gate.
Equal-weight portfolio metrics are not used.

A name is a **dual-print passer** only if it clears combined harder
gates on **both**:

1. The Kraken public Spot daily primary window (720-bar cap).
2. The #102 Binance.US Spot daily print: 720 committed BTC+ETH bars
   ending strictly before the primary Kraken first bar.

Ranking key (frozen): ``mean_holdout_excess_among_dual_print_passers``
— Kraken BTC+ETH mean holdout excess among names that already cleared
both prints. Tie-break: ``candidate_id``. Binance holdout is a gate,
never averaged. A Kraken-only combined-passer cannot promote.

The informational control ``ma_cross_10_30`` is scored on the same
windows and **cannot** enter the passer set.

Paper-executable on Kraken spot (BTC/USD + ETH/USD; SOL/USD when
present via ``paper_simulate_fills``). Empty dual-print set is
success. This module never flips ``PAPER_PROMOTE_*`` and does not add
a Settings pin unless a committed report names a dual-print passer
(default false if added). No live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from traderstack.candles import Candle
from traderstack.models import Side
from traderstack.research.binance_spot import BINANCE_TAKER_BPS_NOTE
from traderstack.research.candidates import AlwaysOnTrendStrategy
from traderstack.research.daily_robustness import KRAKEN_DAILY_CAP_NOTE
from traderstack.research.donchian_breakout import prior_channel
from traderstack.research.dual_print_search import (
    CAN_AVERAGE_VENUES,
    CAN_ENTER_PROMOTION_AVERAGE,
    MULTI_VENUE_BAR_PREREGISTERED,
    RANKING_KEY,
    SELECTION_RULE,
    DualPrintRow,
    _binance_slice_meta,
    _merge_row,
    _score,
    rank_dual_print_passers,
)
from traderstack.research.harder_gates import (
    HARDER_GATES_NOTE,
    CandidateHarderResult,
    _pct,
    _ratio,
    _verdict,
    kraken_daily_candles,
    paper_promote_flag_name,
)
from traderstack.research.harder_gates import (
    RANKING_KEY as KRAKEN_COMBINED_RANKING_KEY,
)
from traderstack.research.miles_candidates import SearchCandidate
from traderstack.research.second_print import (
    BINANCE_SLICE_RULE,
    SECOND_PRINT_BARS,
    SliceMeta,
    primary_first_opened_at,
    remap_binance_for_scoring,
    slice_ending_before,
)
from traderstack.strategies import Regime, StrategySignal

VOL_LOOKBACK = 20
# (candidate_id, kind, channel_n, vol_lookback, vol_mult, long_short)
# kind in {breakout, surge}; channel_n is 0 for surge names.
VOLUME_BREAKOUT_CATALOG: tuple[tuple[str, str, int, int, float, bool], ...] = (
    ("volbrk_lo_20x1_5", "breakout", 20, 20, 1.5, False),
    ("volbrk_lo_55x1_5", "breakout", 55, 20, 1.5, False),
    ("volbrk_lo_20x2", "breakout", 20, 20, 2.0, False),
    ("volbrk_ls_20x1_5", "breakout", 20, 20, 1.5, True),
    ("volbrk_ls_55x1_5", "breakout", 55, 20, 1.5, True),
    ("volsurge_lo_20x2", "surge", 0, 20, 2.0, False),
    ("volsurge_lo_20x2_5", "surge", 0, 20, 2.5, False),
)
VOLUME_BREAKOUT_IDS: tuple[str, ...] = tuple(item[0] for item in VOLUME_BREAKOUT_CATALOG)
CONTROL_ID = "ma_cross_10_30"
CONTROL_IDS: frozenset[str] = frozenset({CONTROL_ID})
CORE_IDS: tuple[str, ...] = VOLUME_BREAKOUT_IDS + (CONTROL_ID,)
UNIVERSE: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")
SCORE_SYMBOLS: frozenset[str] = frozenset(UNIVERSE)
ALIAS_TO_CANONICAL: dict[str, str] = {
    "BTC/USD": "BTC/USD",
    "BTCUSDT": "BTC/USD",
    "BTC-USD": "BTC/USD",
    "XBT/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
    "ETHUSDT": "ETH/USD",
    "ETH-USD": "ETH/USD",
    "SOL/USD": "SOL/USD",
    "SOLUSDT": "SOL/USD",
    "SOL-USD": "SOL/USD",
}
PAPER_PATH_READY = True
MULTI_ASSET_GATE_RULE = "btc_eth_signs_as_96_abc_sol_reported_not_required"
EXIT_RULE = "opposite_band_same_n"
VOLUME_SMA_RULE = "volume_sma_through_t_minus_1"
FILL_RULE = "next_bar_open"
QUOTE_VOLUME_OMITTED_REASON = (
    "base volume only; quote volume is never substituted and a "
    "venue without usable base volume fails closed for volume names"
)

VOLUME_BREAKOUT_RULES = (
    "Pre-registered volume-confirmed breakout dual-print bar "
    "(frozen before any Kraken or Binance.US score). Treatment: "
    "this is not a Donchian N retune (#118) — every promote-eligible "
    "name requires a volume gate. Breakout names compare close[t] "
    "to the prior N-day channel (max high / min low of bars "
    "[t-N, t); bar t's high/low never set the breakout level) "
    f"**and** require volume[t] > V-day volume SMA × mult "
    f"(V frozen at {VOL_LOOKBACK}; decision `{VOLUME_SMA_RULE}`: "
    "SMA on bars [t-V, t), bar t excluded). "
    f"Exit rule `{EXIT_RULE}`: long-only exits to flat when "
    "close[t] < prior N-day low (exit does not require volume); "
    "long/short flips short only when that band breaks **and** "
    "the same volume gate fires (unconfirmed opposite-band holds). "
    "Between the bands the previous side is held (start flat). "
    "Volume-surge names have no channel: long when volume[t] > "
    "SMA(V)×mult and close[t] > close[t−1]; flat otherwise. "
    "Missing or non-positive volume skips that bar (never invented). "
    f"{QUOTE_VOLUME_OMITTED_REASON}. "
    f"Decision at bar t; fill `{FILL_RULE}` (t+1 open — no "
    "look-ahead into the fill bar). Each asset uses its own OHLC; "
    "a missing/short series is skipped, never zero-filled. "
    f"Multi-asset combined bar: `{MULTI_ASSET_GATE_RULE}` — #96 "
    "balanced-holdout and A magnitude and B multi-window and C 2× "
    "fees on BTC and ETH; SOL is reported when present and is not a "
    "gate. Equal-weight portfolio metrics are not used. A dual-print "
    "passer must combined-PASS the Kraken primary 720-bar daily "
    "window AND the #102 Binance.US older-720 "
    f"(`{BINANCE_SLICE_RULE}`: {SECOND_PRINT_BARS} committed daily "
    "BTC+ETH bars ending strictly before the primary Kraken first "
    "bar). "
    f"Ranking key: {RANKING_KEY} — Kraken BTC+ETH mean holdout "
    "excess among dual-print passers (tie-break: candidate_id). "
    "Binance holdout is a gate only; "
    f"CAN_AVERAGE_VENUES={str(CAN_AVERAGE_VENUES).lower()}. "
    f"MULTI_VENUE_BAR_PREREGISTERED="
    f"{str(MULTI_VENUE_BAR_PREREGISTERED).lower()}. "
    "A Kraken-only combined-passer is not a dual-print passer and "
    "cannot promote. The informational control ma_cross_10_30 "
    "cannot enter the passer set. Missing, short, or overlapping "
    "Binance fails closed (zero dual-print passers). Fees are "
    "paper-research 10+5 (gate C 20+10). Paper-executable on "
    "Kraken spot BTC/USD+ETH/USD (SOL optional) "
    f"(PAPER_PATH_READY={str(PAPER_PATH_READY).lower()}). "
    "PAPER_PROMOTE_* stays default false. No live. An empty "
    "dual-print set is success. Not an EMA reprint, not a "
    "BTC−ETH residual reprint, not cross-sectional momentum, "
    "not Donchian / channel breakout, not TSMOM, not Bollinger "
    "fade, not calendar seasonality, not lead-lag, and not a "
    "carry/basis family."
)

VOLUME_BREAKOUT_CATALOG_NOTE = (
    "Frozen catalog (K=8): long-only volume-confirmed breakout "
    "(`volbrk_lo_{20x1_5,55x1_5,20x2}`), long/short symmetric "
    "(`volbrk_ls_{20x1_5,55x1_5}`), volume-surge long-only "
    "(`volsurge_lo_{20x2,20x2_5}`), plus informational control "
    f"ma_cross_10_30 (cannot promote). V frozen at {VOL_LOOKBACK}; "
    f"volume SMA `{VOLUME_SMA_RULE}`. Do not grow this list or "
    "retune N / V / mult after seeing PnL. Channel and volume SMA "
    "are built from venue-local OHLC; a missing series or missing "
    "volume is skipped, never zero-filled or invented. "
    "PAPER_PROMOTE_* stays false unless a committed dual-print "
    "report names a paper-only pin and an operator flips it."
)

PAPER_EXECUTABLE_PATH_NOTE = (
    "This family is paper-executable on Kraken spot. Signals are "
    "candle-only long/short/flat on BTC/USD and ETH/USD (SOL/USD "
    "when present); paper_simulate_fills already books Side.BUY / "
    "Side.SELL. No perp, no funding, no hedge book, no invented "
    "basis. A Settings pin is still added only if a committed "
    "dual-print passer exists, and then default false."
)


def bar_has_usable_volume(candle: Candle) -> bool:
    return candle.volume > 0


def series_has_usable_volume(
    candles: tuple[Candle, ...],
    *,
    vol_lookback: int = VOL_LOOKBACK,
) -> bool:
    """Need V prior usable bars plus one decision bar. Fail closed otherwise."""
    if vol_lookback <= 0:
        return False
    return sum(1 for item in candles if bar_has_usable_volume(item)) >= vol_lookback + 1


def prior_volume_sma(
    candles: tuple[Candle, ...],
    index: int,
    vol_lookback: int = VOL_LOOKBACK,
) -> float | None:
    """SMA of volumes on bars ``[index-V, index)``. Bar t is excluded."""
    if vol_lookback <= 0 or index < vol_lookback:
        return None
    window = candles[index - vol_lookback : index]
    if len(window) < vol_lookback:
        return None
    volumes = [item.volume for item in window]
    if any(value <= 0 for value in volumes):
        return None
    return sum(volumes) / vol_lookback


def volume_confirmed(
    candles: tuple[Candle, ...],
    index: int,
    *,
    vol_lookback: int = VOL_LOOKBACK,
    vol_mult: float,
) -> bool | None:
    """Compare volume[t] to prior SMA × mult. ``None`` = skip-not-invent."""
    if index < 0 or index >= len(candles):
        return None
    today = candles[index].volume
    if today <= 0:
        return None
    sma = prior_volume_sma(candles, index, vol_lookback)
    if sma is None or sma <= 0:
        return None
    return today > sma * vol_mult


def volbrk_position_series(
    candles: tuple[Candle, ...],
    *,
    channel_n: int,
    vol_lookback: int = VOL_LOOKBACK,
    vol_mult: float,
    long_short: bool,
) -> tuple[tuple[datetime, float], ...]:
    """Point-in-time volume-confirmed breakout. Skip-not-invent volume."""
    warmup = max(channel_n, vol_lookback)
    if channel_n <= 0 or vol_lookback <= 0 or len(candles) < warmup + 1:
        return ()
    if not series_has_usable_volume(candles, vol_lookback=vol_lookback):
        return ()
    out: list[tuple[datetime, float]] = []
    position = 0.0
    for index in range(warmup, len(candles)):
        bounds = prior_channel(candles, index, channel_n)
        confirmed = volume_confirmed(
            candles,
            index,
            vol_lookback=vol_lookback,
            vol_mult=vol_mult,
        )
        if bounds is None or confirmed is None:
            out.append((candles[index].opened_at, position))
            continue
        prior_high, prior_low = bounds
        close = candles[index].close
        if close > prior_high and confirmed:
            position = 1.0
        elif close < prior_low:
            if long_short:
                if confirmed:
                    position = -1.0
            else:
                position = 0.0
        out.append((candles[index].opened_at, position))
    return tuple(out)


def volsurge_position_series(
    candles: tuple[Candle, ...],
    *,
    vol_lookback: int = VOL_LOOKBACK,
    vol_mult: float,
) -> tuple[tuple[datetime, float], ...]:
    """Volume surge + up-close. No channel. Missing volume skips the bar."""
    if vol_lookback <= 0 or len(candles) < vol_lookback + 1:
        return ()
    if not series_has_usable_volume(candles, vol_lookback=vol_lookback):
        return ()
    out: list[tuple[datetime, float]] = []
    for index in range(vol_lookback, len(candles)):
        confirmed = volume_confirmed(
            candles,
            index,
            vol_lookback=vol_lookback,
            vol_mult=vol_mult,
        )
        if confirmed is None:
            continue
        close = candles[index].close
        prior_close = candles[index - 1].close
        if close <= 0 or prior_close <= 0:
            continue
        value = 1.0 if confirmed and close > prior_close else 0.0
        out.append((candles[index].opened_at, value))
    return tuple(out)


def _histories_by_canonical(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, tuple[Candle, ...]]:
    out: dict[str, tuple[Candle, ...]] = {}
    for candles in histories.values():
        if not candles:
            continue
        canonical = ALIAS_TO_CANONICAL.get(candles[0].symbol.upper())
        if canonical is None:
            continue
        out[canonical] = candles
    return out


def volume_breakout_signals(
    histories: dict[str, tuple[Candle, ...]],
    *,
    kind: str,
    channel_n: int,
    vol_lookback: int,
    vol_mult: float,
    long_short: bool,
) -> dict[str, tuple[tuple[datetime, float], ...]]:
    """Per-asset assignments. Missing assets / unusable volume omitted."""
    by_canonical = _histories_by_canonical(histories)
    per_asset: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for asset, candles in by_canonical.items():
        if kind == "surge":
            series = volsurge_position_series(
                candles,
                vol_lookback=vol_lookback,
                vol_mult=vol_mult,
            )
        else:
            series = volbrk_position_series(
                candles,
                channel_n=channel_n,
                vol_lookback=vol_lookback,
                vol_mult=vol_mult,
                long_short=long_short,
            )
        if series:
            per_asset[asset] = series
    if not per_asset:
        return {}
    mapping: dict[str, tuple[tuple[datetime, float], ...]] = {}
    for alias, canonical in ALIAS_TO_CANONICAL.items():
        if canonical in per_asset:
            mapping[alias] = per_asset[canonical]
    return mapping


@dataclass(frozen=True)
class VolumeBreakoutVoter:
    """Look up a precomputed same-bar volume-breakout position."""

    strategy_id: str
    signals_by_symbol: tuple[tuple[str, tuple[tuple[datetime, float], ...]], ...] = ()

    def evaluate(self, candles: tuple[Candle, ...], regime: Regime) -> StrategySignal:
        cutoff = candles[-1].opened_at
        series = self.series_for(candles[-1].symbol)
        by_ts = {ts: value for ts, value in series}
        value = by_ts.get(cutoff)
        if value is None:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=candles[-1].symbol,
                side=None,
                score=0.0,
                confidence=0.0,
                regime=regime,
                rationale="volbrk: no same-bar assignment (warmup / skipped volume)",
            )
        side: Side | None = None
        if value > 0:
            side = Side.BUY
        elif value < 0:
            side = Side.SELL
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=candles[-1].symbol,
            side=side,
            score=max(-1.0, min(1.0, value)),
            confidence=1.0 if side is not None else 0.0,
            regime=regime,
            rationale=f"volbrk assignment={value:+.0f}",
        )

    def series_for(self, symbol: str) -> tuple[tuple[datetime, float], ...]:
        key = symbol.upper()
        for name, series in self.signals_by_symbol:
            if name == key:
                return series
        return ()


def _control_candidate() -> SearchCandidate:
    return SearchCandidate(
        candidate_id=CONTROL_ID,
        family="control",
        label="always-on MA 10/30 (informational; cannot promote)",
        params={"short_window": 10, "long_window": 30, "strategy_id": CONTROL_ID},
        strategy=AlwaysOnTrendStrategy(
            strategy_id=CONTROL_ID,
            short_window=10,
            long_window=30,
        ),
    )


def _book_label(
    *,
    kind: str,
    channel_n: int,
    vol_lookback: int,
    vol_mult: float,
    long_short: bool,
) -> str:
    gate = f"vol SMA({vol_lookback})×{vol_mult:g}"
    if kind == "surge":
        return f"long-only volume surge ({gate}; close > prior close)"
    book = "long/short symmetric" if long_short else "long-only"
    return f"{book} volume-confirmed Donchian {channel_n}d + {gate}"


def volume_breakout_candidates(
    histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    include_control: bool = True,
) -> tuple[SearchCandidate, ...]:
    """Instantiate the frozen catalog. Missing OHLC/volume → that name omitted."""
    out: list[SearchCandidate] = []
    source = histories or {}
    for candidate_id, kind, channel_n, vol_lookback, vol_mult, long_short in VOLUME_BREAKOUT_CATALOG:
        mapping = volume_breakout_signals(
            source,
            kind=kind,
            channel_n=channel_n,
            vol_lookback=vol_lookback,
            vol_mult=vol_mult,
            long_short=long_short,
        )
        if not mapping:
            continue
        by_symbol = tuple((key.upper(), values) for key, values in sorted(mapping.items()))
        out.append(
            SearchCandidate(
                candidate_id=candidate_id,
                family="volume_breakout" if kind == "breakout" else "volume_surge",
                label=_book_label(
                    kind=kind,
                    channel_n=channel_n,
                    vol_lookback=vol_lookback,
                    vol_mult=vol_mult,
                    long_short=long_short,
                ),
                params={
                    "kind": kind,
                    "channel_n": channel_n or None,
                    "vol_lookback": vol_lookback,
                    "vol_mult": vol_mult,
                    "long_short": long_short,
                    "exit_rule": EXIT_RULE if kind == "breakout" else "flat_otherwise",
                    "volume_sma_rule": VOLUME_SMA_RULE,
                    "fill_rule": FILL_RULE,
                    "strategy_id": candidate_id,
                    "multi_asset_gate": MULTI_ASSET_GATE_RULE,
                },
                strategy=VolumeBreakoutVoter(
                    strategy_id=candidate_id,
                    signals_by_symbol=by_symbol,
                ),
            )
        )
    if include_control:
        out.append(_control_candidate())
    return tuple(out)


def skipped_volume_breakout_families(
    histories: dict[str, tuple[Candle, ...]],
) -> list[dict[str, str]]:
    skipped: list[dict[str, str]] = []
    for candidate_id, kind, channel_n, vol_lookback, vol_mult, long_short in VOLUME_BREAKOUT_CATALOG:
        mapping = volume_breakout_signals(
            histories,
            kind=kind,
            channel_n=channel_n,
            vol_lookback=vol_lookback,
            vol_mult=vol_mult,
            long_short=long_short,
        )
        if mapping:
            continue
        need = (
            f"usable base volume (V={vol_lookback}) and "
            + (
                f"at least {max(channel_n, vol_lookback) + 1} OHLC bars"
                if kind == "breakout"
                else f"at least {vol_lookback + 1} OHLC bars"
            )
        )
        skipped.append(
            {
                "family": "volume_surge" if kind == "surge" else "volume_breakout",
                "candidate_id": candidate_id,
                "reason": (
                    f"{_book_label(kind=kind, channel_n=channel_n, vol_lookback=vol_lookback, vol_mult=vol_mult, long_short=long_short)}"
                    f": skipped — need {need}. Skip rather than invent "
                    "volume or zero-fill closes. Quote volume is not a substitute."
                ),
            }
        )
    return skipped


def _score_symbols_only(
    histories: dict[str, tuple[Candle, ...]],
) -> dict[str, tuple[Candle, ...]]:
    return {
        key: candles
        for key, candles in histories.items()
        if candles and candles[0].symbol.upper() in SCORE_SYMBOLS
    }


def rank_volume_breakout_passers(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Frozen ranking key among volume-breakout dual-print passers. Control excluded."""
    eligible = [row for row in rows if row.candidate_id not in CONTROL_IDS]
    return rank_dual_print_passers(eligible)


def eth_carried_informational(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Positive mean HO with a losing BTC holdout — #96 FAIL, not an edge."""
    flagged: list[DualPrintRow] = []
    for row in rows:
        if row.candidate_id in CONTROL_IDS:
            continue
        mean_ho = row.kraken_mean_holdout_excess
        btc_ho = row.kraken_btc_holdout
        if mean_ho is None or btc_ho is None:
            continue
        if mean_ho > 0 and btc_ho <= 0:
            flagged.append(row)
    return flagged


def btc_wf_fail_informational(rows: list[DualPrintRow]) -> list[DualPrintRow]:
    """Positive mean HO and BTC HO, but BTC walk-forward ≤ 0 — not an edge."""
    flagged: list[DualPrintRow] = []
    for row in rows:
        if row.candidate_id in CONTROL_IDS:
            continue
        mean_ho = row.kraken_mean_holdout_excess
        btc_ho = row.kraken_btc_holdout
        btc_wf = row.kraken_btc_wf
        if mean_ho is None or btc_ho is None or btc_wf is None:
            continue
        if mean_ho > 0 and btc_ho > 0 and btc_wf <= 0:
            flagged.append(row)
    return flagged


def _volume_data_notes(
    histories: dict[str, tuple[Candle, ...]],
    *,
    label: str,
) -> list[str]:
    notes: list[str] = []
    for symbol in UNIVERSE:
        candles = kraken_daily_candles(histories, symbol)
        if not candles:
            continue
        positive = sum(1 for item in candles if bar_has_usable_volume(item))
        if positive == 0:
            notes.append(
                f"{label} {symbol}: no usable base volume (all bars ≤ 0). "
                "Volume names fail closed on this venue. Do not invent "
                "quote volume."
            )
        elif not series_has_usable_volume(candles, vol_lookback=VOL_LOOKBACK):
            notes.append(
                f"{label} {symbol}: insufficient positive-volume bars "
                f"({positive}/{len(candles)}; need ≥{VOL_LOOKBACK + 1}). "
                "Volume names skip this series."
            )
        else:
            notes.append(
                f"{label} {symbol}: {positive}/{len(candles)} bars with "
                "base volume > 0 (quote volume is not substituted)."
            )
    return notes


class VolumeBreakoutReport(BaseModel):
    generated_at: datetime
    ranking_key: str
    selection_rule: str
    multi_asset_gate_rule: str
    catalog_k_core: int
    catalog_k_scored: int
    catalog_ids: list[str]
    catalog_note: str
    fee_bps: float
    slippage_bps: float
    train_size: int
    test_size: int
    step_size: int
    holdout_fraction: float
    min_trades: int
    primary_first: str
    primary_first_source: str
    primary_last: str | None = None
    primary_bars: int | None = None
    primary_bars_eth: int | None = None
    primary_bars_sol: int | None = None
    binance_slice: SliceMeta
    binance_source: str | None = None
    paper_path_ready: bool = True
    multi_venue_bar_preregistered: bool = True
    can_average_venues: bool = False
    can_enter_promotion_average: bool = False
    keep_flag_false: bool = True
    rows: list[DualPrintRow] = Field(default_factory=list)
    dual_print_passer_ids: list[str] = Field(default_factory=list)
    kraken_combined_passer_ids: list[str] = Field(default_factory=list)
    binance_combined_passer_ids: list[str] = Field(default_factory=list)
    eth_carried_ids: list[str] = Field(default_factory=list)
    btc_wf_fail_ids: list[str] = Field(default_factory=list)
    skipped_feature_families: list[dict[str, str]] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    recommended_promote_flag: str | None = None
    any_dual_print_passer: bool = False
    honesty: str
    recommendation: str
    rules: str = VOLUME_BREAKOUT_RULES
    gates_note: str = HARDER_GATES_NOTE
    fee_note: str = BINANCE_TAKER_BPS_NOTE
    kraken_cap_note: str = KRAKEN_DAILY_CAP_NOTE
    paper_path_note: str = PAPER_EXECUTABLE_PATH_NOTE
    data_notes: list[str] = Field(default_factory=list)


def _recommendation(
    *,
    selected_id: str | None,
    dual_ids: list[str],
    kraken_ids: list[str],
    binance_meta: SliceMeta,
    eth_carried: list[str],
    btc_wf_fail: list[str],
) -> str:
    lines = [
        (
            "**Keep every `PAPER_PROMOTE_*=false`.** This search does not "
            "flip a pin and does not enable live. An empty dual-print set "
            "is the successful outcome."
        ),
        "",
        (
            f"- Dual-print passers: {len(dual_ids)}"
            + (f" (`{'`, `'.join(dual_ids)}`)" if dual_ids else " (none)")
            + "."
        ),
        (
            f"- Kraken combined-passers (informational; control excluded "
            f"from ranking): {len(kraken_ids)}"
            + (f" (`{'`, `'.join(kraken_ids)}`)" if kraken_ids else "")
            + ". A Kraken-only passer cannot promote."
        ),
        (
            f"- Binance.US `{BINANCE_SLICE_RULE}`: "
            f"{'scored' if binance_meta.available else 'FAIL-CLOSED'} "
            f"({binance_meta.venue}; {binance_meta.bars_btc} BTC / "
            f"{binance_meta.bars_eth} ETH / {binance_meta.bars_sol} SOL; "
            f"{binance_meta.first} → {binance_meta.last})."
        ),
        (f"- Multi-asset gate: `{MULTI_ASSET_GATE_RULE}` (SOL reported, not required)."),
        (
            f"- Volume SMA: `{VOLUME_SMA_RULE}` (V={VOL_LOOKBACK}; "
            "missing volume skipped, never invented)."
        ),
        (
            f"- Paper path: ready on Kraken spot BTC/ETH "
            f"(SOL optional; PAPER_PATH_READY={str(PAPER_PATH_READY).lower()})."
        ),
    ]
    if eth_carried:
        lines.append(
            "- #96 FAIL (ETH-carried informational mean HO; BTC holdout "
            f"≤ 0): {', '.join(f'`{item}`' for item in eth_carried)}. "
            "A positive mean with a losing BTC holdout is not an edge."
        )
    if btc_wf_fail:
        lines.append(
            "- Informational positive mean HO and BTC HO with BTC "
            f"walk-forward ≤ 0: {', '.join(f'`{item}`' for item in btc_wf_fail)}. "
            "Same honesty as #118 Donchian / #119 TSMOM — still not an edge."
        )
    if selected_id is None:
        lines.append(
            "- Dual-print top-1: **none**. Do not add a new promote flag. "
            "Leave every existing `PAPER_PROMOTE_*` false."
        )
    else:
        flag = paper_promote_flag_name(selected_id)
        lines.append(
            f"- Dual-print top-1: `{selected_id}` by `{RANKING_KEY}`. "
            f"Documented paper-only name would be `{flag}` "
            "(default **false** if added). This run does not flip it."
        )
    lines.append(
        "- Do not enable live. Do not fabricate PnL. Do not re-run #104 "
        "or #108 EMA dual-prints. Do not re-run the #116 residual, "
        "#117 cross-sectional, #118 Donchian, #119 TSMOM, #120 "
        "Bollinger, #121 calendar, or #122 lead-lag catalogs on the "
        "same windows. Do not invent PIT basis for carry."
    )
    return "\n".join(lines)


def run_volume_breakout_search(
    kraken_histories: dict[str, tuple[Candle, ...]],
    binance_histories: dict[str, tuple[Candle, ...]] | None = None,
    *,
    fee_bps: float,
    slippage_bps: float = 5.0,
    starting_equity: float = 10_000.0,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int = 60,
    holdout_fraction: float = 0.20,
    min_trades: int = 3,
    candidates: tuple[SearchCandidate, ...] | None = None,
    binance_source: str | None = None,
    now: datetime | None = None,
    data_notes: list[str] | None = None,
) -> VolumeBreakoutReport:
    generated = now or datetime.now(UTC)
    kraken = _score_symbols_only(kraken_histories)
    if not kraken:
        raise ValueError("no Kraken BTC/ETH/SOL daily histories provided")
    primary_first, primary_source = primary_first_opened_at(kraken)
    btc = kraken_daily_candles(kraken, "BTC/USD")
    eth = kraken_daily_candles(kraken, "ETH/USD")
    sol = kraken_daily_candles(kraken, "SOL/USD")
    primary_last = btc[-1].opened_at.isoformat() if btc else None
    primary_bars = len(btc) if btc else None

    catalog = candidates if candidates is not None else volume_breakout_candidates(kraken)
    skipped = skipped_volume_breakout_families(kraken)

    raw_binance = binance_histories or {}
    sliced_binance = {
        key: slice_ending_before(candles, before=primary_first)
        for key, candles in raw_binance.items()
    }
    remapped = _score_symbols_only(remap_binance_for_scoring(sliced_binance))
    binance_meta = _binance_slice_meta(
        raw_binance=raw_binance,
        remapped=remapped,
        primary_first=primary_first,
        binance_source=binance_source,
    )

    kraken_report = _score(
        kraken,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        starting_equity=starting_equity,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        candidates=catalog,
        now=generated,
    )
    kraken_by_id = {row.candidate_id: row for row in kraken_report.candidates}

    binance_by_id: dict[str, CandidateHarderResult] = {}
    if binance_meta.available:
        if candidates is not None:
            binance_catalog = candidates
        else:
            binance_catalog = volume_breakout_candidates(remapped)
        binance_report = _score(
            remapped,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            starting_equity=starting_equity,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
            holdout_fraction=holdout_fraction,
            min_trades=min_trades,
            candidates=binance_catalog,
            now=generated,
        )
        binance_by_id = {row.candidate_id: row for row in binance_report.candidates}

    rows = [
        _merge_row(
            candidate,
            kraken_by_id.get(candidate.candidate_id),
            binance_by_id.get(candidate.candidate_id),
        )
        for candidate in catalog
    ]
    passers = rank_volume_breakout_passers(rows)
    selected = passers[0] if passers else None
    dual_ids = [row.candidate_id for row in passers]
    kraken_ids = [
        row.candidate_id
        for row in sorted(
            (
                item
                for item in rows
                if item.kraken_combined and item.candidate_id not in CONTROL_IDS
            ),
            key=lambda item: (
                item.kraken_combined_rank if item.kraken_combined_rank is not None else 10**9,
                item.candidate_id,
            ),
        )
    ]
    binance_ids = [
        row.candidate_id
        for row in rows
        if row.binance_combined and row.candidate_id not in CONTROL_IDS
    ]
    eth_carried = eth_carried_informational(rows)
    eth_carried_ids = [row.candidate_id for row in eth_carried]
    wf_fail = btc_wf_fail_informational(rows)
    btc_wf_fail_ids = [row.candidate_id for row in wf_fail]
    recommended = paper_promote_flag_name(selected.candidate_id) if selected is not None else None
    honesty = (
        VOLUME_BREAKOUT_RULES
        + " "
        + VOLUME_BREAKOUT_CATALOG_NOTE
        + f" This run scored K={len(catalog)} (core ids frozen at "
        f"{len(CORE_IDS)}). "
        f"Kraken combined-passers (ex-control): {len(kraken_ids)}. "
        f"Binance combined-passers (ex-control): {len(binance_ids)}. "
        f"Dual-print passers: {len(dual_ids)}."
    )
    if eth_carried_ids:
        honesty += (
            " Informational #96 FAIL (ETH-carried mean HO): "
            + ", ".join(f"`{item}`" for item in eth_carried_ids)
            + "."
        )
    if btc_wf_fail_ids:
        honesty += (
            " Informational BTC walk-forward fail (positive mean HO "
            "and BTC HO): " + ", ".join(f"`{item}`" for item in btc_wf_fail_ids) + "."
        )
    if selected is None:
        honesty += (
            " No dual-print passer. Leave every PAPER_PROMOTE_* false. "
            "Do not add a new promote flag."
        )
    else:
        honesty += (
            f" Dual-print top-1 is `{selected.candidate_id}` by "
            f"{RANKING_KEY}. Document a paper-only pin only; default "
            "false; do not enable live."
        )

    notes = list(data_notes or [])
    notes.extend(_volume_data_notes(kraken, label="Kraken"))
    if remapped:
        notes.extend(_volume_data_notes(remapped, label="Binance.US"))
    if not btc or not eth:
        notes.append(
            "BTC and/or ETH daily series missing on Kraken. Combined "
            "gates cannot pass. Skip-not-invent; do not zero-fill."
        )
    if sol:
        notes.append(f"SOL/USD present ({len(sol)} bars); reported, not a gate.")
    else:
        notes.append("SOL/USD absent; reported as n/a, not invented.")

    return VolumeBreakoutReport(
        generated_at=generated,
        ranking_key=RANKING_KEY,
        selection_rule=SELECTION_RULE,
        multi_asset_gate_rule=MULTI_ASSET_GATE_RULE,
        catalog_k_core=len(CORE_IDS),
        catalog_k_scored=len(catalog),
        catalog_ids=[item.candidate_id for item in catalog],
        catalog_note=VOLUME_BREAKOUT_CATALOG_NOTE,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        holdout_fraction=holdout_fraction,
        min_trades=min_trades,
        primary_first=primary_first.isoformat(),
        primary_first_source=primary_source,
        primary_last=primary_last,
        primary_bars=primary_bars,
        primary_bars_eth=len(eth) if eth else None,
        primary_bars_sol=len(sol) if sol else None,
        binance_slice=binance_meta,
        binance_source=binance_source,
        paper_path_ready=PAPER_PATH_READY,
        multi_venue_bar_preregistered=MULTI_VENUE_BAR_PREREGISTERED,
        can_average_venues=CAN_AVERAGE_VENUES,
        can_enter_promotion_average=CAN_ENTER_PROMOTION_AVERAGE,
        keep_flag_false=True,
        rows=rows,
        dual_print_passer_ids=dual_ids,
        kraken_combined_passer_ids=kraken_ids,
        binance_combined_passer_ids=binance_ids,
        eth_carried_ids=eth_carried_ids,
        btc_wf_fail_ids=btc_wf_fail_ids,
        skipped_feature_families=skipped,
        selected_candidate_id=selected.candidate_id if selected is not None else None,
        recommended_promote_flag=recommended,
        any_dual_print_passer=bool(dual_ids),
        honesty=honesty,
        recommendation=_recommendation(
            selected_id=selected.candidate_id if selected is not None else None,
            dual_ids=dual_ids,
            kraken_ids=kraken_ids,
            binance_meta=binance_meta,
            eth_carried=eth_carried_ids,
            btc_wf_fail=btc_wf_fail_ids,
        ),
        data_notes=notes,
    )


def _slice_lines(meta: SliceMeta) -> list[str]:
    status = "available" if meta.available else "UNAVAILABLE / fail-closed"
    return [
        f"- Rule: `{meta.rule}`",
        f"- Venue label: `{meta.venue}`",
        f"- Status: **{status}**",
        f"- Bars: BTC {meta.bars_btc} / ETH {meta.bars_eth} / SOL {meta.bars_sol}",
        f"- Span: {meta.first or 'n/a'} → {meta.last or 'n/a'}",
        f"- Overlaps primary window: {'yes' if meta.overlaps_primary_window else 'no'}",
        f"- Fail-closed reason: {meta.fail_closed_reason or '—'}",
    ]


def _passer_table(rows: list[DualPrintRow], *, venue: str) -> list[str]:
    if venue == "kraken":
        header = (
            "| rank | id | mean HO | BTC HO | ETH HO | SOL HO | ratio | "
            "#96 | A | B | C | dual-print |"
        )
        sep = (
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | "
            ":---: | :---: | :---: | :---: |"
        )
    else:
        header = (
            "| id | mean HO | BTC HO | ETH HO | SOL HO | ratio | #96 | A | B | C | dual-print |"
        )
        sep = "| --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: |"
    lines = [header, sep]
    if not rows:
        if venue == "kraken":
            lines.append("| — | — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |")
        else:
            lines.append("| — | n/a | n/a | n/a | n/a | n/a | — | — | — | — | no |")
        return lines
    for row in rows:
        if venue == "kraken":
            lines.append(
                f"| {row.kraken_combined_rank or '—'} | `{row.candidate_id}` | "
                f"{_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} | "
                f"{_pct(row.kraken_sol_holdout)} | "
                f"{_ratio(row.kraken_holdout_ratio)} | "
                f"{_verdict(row.kraken_eligible_96)} | {_verdict(row.kraken_gate_a)} | "
                f"{_verdict(row.kraken_gate_b)} | {_verdict(row.kraken_gate_c)} | "
                f"{'yes' if row.dual_print else 'no'} |"
            )
        else:
            lines.append(
                f"| `{row.candidate_id}` | {_pct(row.binance_mean_holdout_excess)} | "
                f"{_pct(row.binance_btc_holdout)} | {_pct(row.binance_eth_holdout)} | "
                f"{_pct(row.binance_sol_holdout)} | "
                f"{_ratio(row.binance_holdout_ratio)} | "
                f"{_verdict(row.binance_eligible_96)} | {_verdict(row.binance_gate_a)} | "
                f"{_verdict(row.binance_gate_b)} | {_verdict(row.binance_gate_c)} | "
                f"{'yes' if row.dual_print else 'no'} |"
            )
    return lines


def render_volume_breakout_markdown(
    report: VolumeBreakoutReport,
) -> str:
    dual_rows = [
        row for row in report.rows if row.dual_print and row.candidate_id not in CONTROL_IDS
    ]
    dual_rows.sort(key=lambda row: row.dual_print_rank or 10**9)
    kraken_rows = [
        row for row in report.rows if row.kraken_combined and row.candidate_id not in CONTROL_IDS
    ]
    kraken_rows.sort(key=lambda row: row.kraken_combined_rank or 10**9)
    binance_rows = [
        row for row in report.rows if row.binance_combined and row.candidate_id not in CONTROL_IDS
    ]
    binance_rows.sort(key=lambda row: row.candidate_id)
    lines: list[str] = [
        "# Volume-confirmed breakout dual-print (BTC+ETH; SOL optional)",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        (
            f"Catalog K scored={report.catalog_k_scored} "
            f"(frozen core={report.catalog_k_core}; "
            f"ranking_key=`{report.ranking_key}`)."
        ),
        (
            f"Baseline costs: fee={report.fee_bps:g} bps + slippage="
            f"{report.slippage_bps:g} bps. Walk-forward: train="
            f"{report.train_size} test={report.test_size} step="
            f"{report.step_size}; holdout_fraction={report.holdout_fraction:.0%}."
        ),
        (
            f"Primary Kraken first bar: {report.primary_first} "
            f"(source=`{report.primary_first_source}`; last="
            f"{report.primary_last or 'n/a'}; bars BTC="
            f"{report.primary_bars or 'n/a'} / ETH="
            f"{report.primary_bars_eth or 'n/a'} / SOL="
            f"{report.primary_bars_sol or 'n/a'})."
        ),
        (
            f"`multi_asset_gate_rule={report.multi_asset_gate_rule}`; "
            f"`multi_venue_bar_preregistered="
            f"{str(report.multi_venue_bar_preregistered).lower()}`; "
            f"`can_average_venues={str(report.can_average_venues).lower()}`; "
            f"`paper_path_ready={str(report.paper_path_ready).lower()}`; "
            f"`keep_flag_false={str(report.keep_flag_false).lower()}`."
        ),
        "",
        "## Honesty / pre-registered rules",
        "",
        report.honesty,
        "",
        "## Dual-print bar (frozen before scoring)",
        "",
        report.rules,
        "",
        "| print | rule | can enter ranking average? |",
        "| --- | --- | --- |",
        (
            "| Kraken primary 720 | public Spot daily, 720-bar cap; "
            f"#96+A+B+C on BTC+ETH (SOL reported); rank among "
            f"dual-print passers by `{report.ranking_key}` "
            "| **Kraken mean HO only** |"
        ),
        (
            "| Binance.US older 720 | same #102 definition: 720 committed "
            "daily BTC+ETH bars ending before the primary Kraken first "
            "bar; SOL optional report-only; must combined-PASS "
            "| **no** (gate only; not averaged) |"
        ),
        (
            f"| Kraken-only combined ranking (`{KRAKEN_COMBINED_RANKING_KEY}`) "
            "| informational | no |"
        ),
        "",
        "## Multi-asset gate (frozen)",
        "",
        (
            f"`{report.multi_asset_gate_rule}`: require BTC and ETH "
            "walk-forward total > 0 and holdout excess > 0, plus A/B/C, "
            "exactly as #96+#104. SOL walk-forward and holdout are "
            "printed in the tables when the series exists and **do not** "
            "gate. Equal-weight portfolio metrics were considered and "
            "**rejected** before scoring — that would be a different "
            "bar and is not used here."
        ),
        "",
        "## Treatment (frozen)",
        "",
        (
            "This is **not** a Donchian N retune (#118): every "
            "promote-eligible name requires a volume gate. On each "
            "asset at bar t, the channel is the max high and min "
            "low of the prior N bars `[t-N, t)`. Bar t's high/low never "
            f"enter that level. Volume SMA uses `{VOLUME_SMA_RULE}` "
            f"(V={VOL_LOOKBACK} bars `[t-V, t)`; bar t excluded). "
            "A missing or non-positive volume skips that bar and is "
            "never invented; quote volume is not a substitute. "
            f"Exit rule `{EXIT_RULE}`: long-only is flat after "
            "close[t] < prior low (no volume required to exit); "
            "long/short flips short only on that band **with** the "
            "same volume gate. Between the bands the previous side "
            "is held (start flat). Volume-surge names have no "
            "channel: long when volume[t] > SMA×mult and close[t] > "
            "close[t−1]; flat otherwise. Decision uses close[t]; the "
            f"shared backtest fills at `{FILL_RULE}` (bar t+1 open). "
            "A missing series is skipped, never zero-filled. A venue "
            "without usable base volume fails closed for volume names."
        ),
        "",
        "## Pre-registered catalog",
        "",
        report.catalog_note,
        "",
        ("Frozen core ids: " + ", ".join(f"`{item}`" for item in CORE_IDS) + "."),
        "",
        "## Paper path",
        "",
        report.paper_path_note,
        "",
        "## Kraken public OHLC cap",
        "",
        report.kraken_cap_note,
        "",
    ]
    if report.data_notes:
        lines.extend(["## Data", ""])
        for note in report.data_notes:
            lines.append(f"- {note}")
        lines.append("")
    if report.skipped_feature_families:
        lines.extend(["## Skipped (not invented)", ""])
        for item in report.skipped_feature_families:
            lines.append(f"- `{item['candidate_id']}`: {item['reason']}")
        lines.append("")

    lines.extend(
        [
            "## Binance.US second print (required gate)",
            "",
            report.fee_note,
            "",
        ]
    )
    lines.extend(_slice_lines(report.binance_slice))
    lines.extend(
        [
            "",
            (
                "`api.binance.com` is HTTP 451 from this environment; "
                "`api.binance.us` is labeled **Binance.US**, not Binance.com. "
                "A short or overlapping BTC/ETH series fails closed. Empty "
                "Binance means zero dual-print passers (success). Missing "
                "SOL on Binance is report-only (not a two-asset fallback "
                "and not a gate). Missing base volume fails closed for "
                "volume names; quote volume is not substituted."
            ),
            "",
            "## Dual-print passers (promotion ranking)",
            "",
            (
                f"Frozen ranking key: `{report.ranking_key}`. Only "
                "volume-confirmed names that already clear combined on "
                f"**both** prints appear here. `{CONTROL_ID}` is excluded. "
                "Empty table = no promotee (success). A new Settings pin "
                "is added only if this table is non-empty, and then "
                "default **false**."
            ),
            "",
            (
                "| dual rank | id | Kraken mean HO | Binance mean HO | "
                "Kraken BTC HO | Kraken ETH HO | Kraken SOL HO | "
                "selected | can flip flag |"
            ),
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | :---: | :---: |",
        ]
    )
    if not dual_rows:
        lines.append("| — | — | n/a | n/a | n/a | n/a | n/a | no | no |")
    else:
        for row in dual_rows:
            lines.append(
                f"| {row.dual_print_rank} | `{row.candidate_id}` | "
                f"{_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.binance_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} | "
                f"{_pct(row.kraken_sol_holdout)} | "
                f"{'yes' if row.selected else 'no'} | no |"
            )
    lines.extend(
        [
            "",
            "## Kraken combined-passers (informational)",
            "",
            (
                "These volume-confirmed names cleared #96+A+B+C on the "
                "Kraken primary window (BTC+ETH gates). They are **not** "
                "promotees unless they also appear in the dual-print "
                "table. Control omitted. SOL holdout is reported."
            ),
            "",
        ]
    )
    lines.extend(_passer_table(kraken_rows, venue="kraken"))
    lines.extend(
        [
            "",
            "## Binance.US combined-passers (informational)",
            "",
            (
                "These volume-confirmed names cleared #96+A+B+C on the "
                "Binance.US older-720. They cannot promote unless they "
                "also cleared Kraken. Control omitted. SOL holdout is "
                "reported."
            ),
            "",
        ]
    )
    lines.extend(_passer_table(binance_rows, venue="binance"))
    if report.eth_carried_ids:
        lines.extend(
            [
                "",
                "## #96 FAIL informational names (ETH-carried)",
                "",
                (
                    "These names have a **positive** Kraken mean holdout "
                    "excess while BTC holdout excess is ≤ 0. That is the "
                    "same honesty as `xs_mom_lo_vol_63` in #117 and "
                    "`tsmom_lo_63` / `tsmom_ls_63` in #119: the mean "
                    "is ETH-carried. **#96 FAIL**, not a combined-passer."
                ),
                "",
                "| id | Kraken mean HO | BTC HO | ETH HO |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        carried = {row.candidate_id: row for row in report.rows}
        for candidate_id in report.eth_carried_ids:
            row = carried[candidate_id]
            lines.append(
                f"| `{candidate_id}` | {_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} |"
            )
    if report.btc_wf_fail_ids:
        lines.extend(
            [
                "",
                "## Informational BTC walk-forward fails",
                "",
                (
                    "These names have a **positive** Kraken mean holdout "
                    "and **positive** BTC holdout, but BTC walk-forward "
                    "total is ≤ 0. Same honesty as #118 Donchian and "
                    "#119 TSMOM. Still not an edge."
                ),
                "",
                "| id | Kraken mean HO | BTC HO | BTC WF |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        by_id = {row.candidate_id: row for row in report.rows}
        for candidate_id in report.btc_wf_fail_ids:
            row = by_id[candidate_id]
            lines.append(
                f"| `{candidate_id}` | {_pct(row.kraken_mean_holdout_excess)} | "
                f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_btc_wf)} |"
            )
    lines.extend(
        [
            "",
            "## Full catalog (informational)",
            "",
            (
                "| id | family | Kraken combined | Binance combined | dual-print | "
                "Kraken mean HO | Binance mean HO | Kraken BTC HO | Kraken ETH HO |"
            ),
            "| --- | --- | :---: | :---: | :---: | ---: | ---: | ---: | ---: |",
        ]
    )
    family_by_id = {
        item: ("control" if item in CONTROL_IDS else "volume_breakout") for item in CORE_IDS
    }
    for row in report.rows:
        family_by_id[row.candidate_id] = (
            "control" if row.candidate_id in CONTROL_IDS else row.family
        )
    ordered = sorted(
        report.rows,
        key=lambda row: (
            0 if row.candidate_id not in CONTROL_IDS else 1,
            row.kraken_wf_rank if row.kraken_wf_rank is not None else 10**9,
            row.candidate_id,
        ),
    )
    for row in ordered:
        lines.append(
            f"| `{row.candidate_id}` | {family_by_id.get(row.candidate_id, row.family)} | "
            f"{_verdict(row.kraken_combined)} | "
            f"{_verdict(row.binance_combined)} | "
            f"{'yes' if row.dual_print and row.candidate_id not in CONTROL_IDS else 'no'} | "
            f"{_pct(row.kraken_mean_holdout_excess)} | "
            f"{_pct(row.binance_mean_holdout_excess)} | "
            f"{_pct(row.kraken_btc_holdout)} | {_pct(row.kraken_eth_holdout)} |"
        )
    lines.extend(
        [
            "",
            "## Operator recommendation",
            "",
            report.recommendation,
            "",
            (
                f"`keep_flag_false={str(report.keep_flag_false).lower()}`. "
                "Do not fabricate PnL. Do not enable live. Do not average "
                "Binance.US with the Kraken primary window. Do not re-run "
                "dead EMA dual-prints (#104 / #108), the #116 residual "
                "catalog, the #117 cross-sectional catalog, the #118 "
                "Donchian catalog, the #119 TSMOM catalog, the #120 "
                "Bollinger catalog, the #121 calendar catalog, or the "
                "#122 lead-lag catalog on the same windows. Do not invent "
                "carry basis."
            ),
            "",
        ]
    )
    return "\n".join(lines)
