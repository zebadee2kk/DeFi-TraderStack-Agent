"""Operator-facing configuration check.

`traderstack-check-config` loads `Settings` the same way the runtime does,
prints a table of which features/providers are enabled, and warns (exiting
non-zero) on combinations that are unsafe for an operator to run unreviewed.

Secret *values* (API keys, passwords) are never printed — only whether a
secret is present, so the output is safe to paste into chat, a ticket, or CI
logs.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from pydantic import SecretStr

from traderstack.config import (
    EMA_9_21_PAPER_CANDLE_COUNT,
    EMA_9_21_PAPER_MAX_DRAWDOWN_PCT,
    EMA_9_21_PAPER_RESEARCH_WF_MAX_DRAWDOWN_PCT,
    PAPER_PROMOTE_UNIVERSE_SYMBOLS,
    Settings,
)
from traderstack.fee_tiers import MODELLED_FEE_TIER_ID, PILOT_FEE_TIER_ID, resolve_fee_tier
from traderstack.market.crucix import crucix_effective_base_url, crucix_should_register


@dataclass(frozen=True)
class CheckItem:
    label: str
    value: str
    detail: str = ""


@dataclass(frozen=True)
class ConfigReport:
    items: list[CheckItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return not self.warnings


def _flag(value: bool) -> str:
    return "yes" if value else "no"


def _has_secret(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())


def build_report(settings: Settings) -> ConfigReport:
    items: list[CheckItem] = []
    warnings: list[str] = []

    # --- Trading mode & kill switch -------------------------------------------------
    items.append(CheckItem("Trading mode", settings.trading_mode))
    if settings.trading_mode == "live":
        warnings.append(
            "TRADING_MODE='live' is rejected by the runtime; live capital is out of "
            "scope until the remaining gates in docs/MVP-BACKLOG.md close. "
            "Use paper (venue paper orders) or shadow (record would-have-been orders)."
        )
    elif settings.trading_mode == "shadow":
        items.append(
            CheckItem(
                "  shadow-live effect",
                "record only",
                "full decision/risk/meta-agent pipeline; no Hummingbot submit, "
                "no chain broadcast, no paper fills",
            )
        )

    kill_switch_state = (
        "engaged (safe: all proposals rejected)" if settings.kill_switch else "disengaged"
    )
    items.append(CheckItem("Kill switch", kill_switch_state))
    if not settings.kill_switch and settings.app_env.strip().lower() != "development":
        warnings.append(
            "KILL_SWITCH=false outside APP_ENV=development: the deterministic risk engine "
            "will not auto-reject via the kill-switch check. Confirm this is intentional "
            "before leaving the process running (see docs/RUNBOOK.md, 'Kill switch')."
        )

    # --- Venue / market data feed ----------------------------------------------------
    items.append(CheckItem("Venue feed", settings.venue_feed))
    if settings.venue_feed == "kraken_rest":
        items.append(
            CheckItem(
                "  kraken REST ticker",
                "paper-only public /0/public/Ticker",
                f"poll {settings.kraken_rest_poll_seconds}s",
            )
        )
        if settings.trading_mode != "paper":
            warnings.append(
                "VENUE_FEED=kraken_rest is paper-only and is rejected at startup "
                f"when TRADING_MODE={settings.trading_mode!r}. Use VENUE_FEED=kraken "
                "(WS) or switch TRADING_MODE=paper (see docs/RUNBOOK.md, "
                "'Kraken REST ticker fallback')."
            )
    if settings.venue_feed == "robinhood_chain":
        required: tuple[tuple[str, object], ...] = (
            ("ROBINHOOD_CHAIN_RPC_URL", settings.robinhood_chain_rpc_url),
            ("ROBINHOOD_CHAIN_ID", settings.robinhood_chain_id),
            ("ROBINHOOD_CHAIN_WS_URL", settings.robinhood_chain_ws_url),
            ("ROBINHOOD_CHAIN_POOLS", settings.robinhood_chain_pools or None),
        )
        missing = [name for name, value in required if not value]
        items.append(
            CheckItem(
                "  robinhood chain feed configured",
                _flag(not missing),
                ("missing: " + ", ".join(missing)) if missing else "",
            )
        )
        if missing:
            warnings.append(
                "VENUE_FEED=robinhood_chain but missing required settings: "
                + ", ".join(missing)
                + ". The runtime fails closed (raises) at startup without these."
            )

    # --- paper-research edge data plane ----------------------------------------------
    items.append(
        CheckItem(
            "Paper-research edge feeds",
            "informational only — not an execution venue",
        )
    )
    items.append(
        CheckItem(
            "  Binance USDT-M liquidations",
            _flag(settings.binance_liq_enabled),
            "research/risk context; RiskEngine does not size from these",
        )
    )
    book_ticker_value = settings.book_ticker_venue if settings.book_ticker_enabled else "no"
    items.append(
        CheckItem(
            "  Second-venue bookTicker",
            book_ticker_value,
            "cross-venue mid feature only" if settings.book_ticker_enabled else "",
        )
    )
    if settings.trading_mode != "paper" and (
        settings.binance_liq_enabled or settings.book_ticker_enabled
    ):
        warnings.append(
            "BINANCE_LIQ_ENABLED/BOOK_TICKER_ENABLED are paper-research features "
            "only; they do not add Binance/Bybit order routing. TRADING_MODE is "
            f"{settings.trading_mode!r} — confirm these feeds are not being treated "
            "as an execution venue."
        )

    # --- strategy search / paper voters ----------------------------------------------
    from traderstack.research.promotion import describe_promotion, load_search_report

    promote_value, promote_detail = describe_promotion(settings)
    items.append(
        CheckItem(
            "Promote searched strategies as paper voters",
            promote_value,
            promote_detail,
        )
    )
    items.append(
        CheckItem(
            "  search report path",
            settings.paper_search_report_path,
        )
    )
    items.append(
        CheckItem(
            "  pinned search promote id",
            settings.paper_promote_searched_strategy_id or "(none)",
        )
    )
    if settings.paper_promote_searched_strategies:
        from pathlib import Path

        report_path = Path(settings.paper_search_report_path)
        if not report_path.is_file():
            warnings.append(
                "PAPER_PROMOTE_SEARCHED_STRATEGIES=true but the search report "
                f"({settings.paper_search_report_path}) is missing. Leave the flag "
                "false until traderstack-strategy-search writes a gate-clearing winner."
            )
        else:
            try:
                search_report = load_search_report(report_path)
            except (OSError, ValueError) as exc:
                warnings.append(
                    "PAPER_PROMOTE_SEARCHED_STRATEGIES=true but the search report "
                    f"could not be read ({exc}). Leave the flag false."
                )
            else:
                if not search_report.any_promoted:
                    warnings.append(
                        "PAPER_PROMOTE_SEARCHED_STRATEGIES=true but the search report "
                        "has no promoted candidate. Leave the flag false — this is not "
                        "an edge."
                    )

    # --- miles-inspired ema_9_21 paper voter ------------------------------------------
    items.append(
        CheckItem(
            "Promote ema_9_21 as paper voter",
            (
                "active"
                if settings.paper_promote_ema_9_21_active
                else "ignored"
                if settings.paper_promote_ema_9_21
                else "no"
            ),
            (
                "sole voter ema_9_21; defaults suppressed; "
                f"candles forced {settings.effective_pretrade_candle_interval} "
                "(Kraken 1440); do not claim daily edge on 1h bars"
                if settings.paper_promote_ema_9_21_active
                else (
                    f"PAPER_PROMOTE_EMA_9_21 is paper-only; TRADING_MODE={settings.trading_mode}"
                    if settings.paper_promote_ema_9_21
                    else "default; ema_9_21 is not a paper voter"
                )
            ),
        )
    )
    if settings.paper_promote_ema_9_21_active:
        configured = settings.pretrade_candle_interval
        items.append(
            CheckItem(
                "Paper candle interval (promote ema_9_21)",
                settings.effective_pretrade_candle_interval,
                (
                    f"forced {settings.effective_pretrade_candle_interval} / 1440m "
                    f"for the daily-validated voter; PRETRADE_CANDLE_INTERVAL="
                    f"{configured} is not used for ingestion or the pre-trade gate"
                    if configured != settings.effective_pretrade_candle_interval
                    else (
                        "aligned with the daily Miles winner; paper ingestion, "
                        "feature bars, and the pre-trade backtest share this series"
                    )
                ),
            )
        )
    if settings.paper_daily_promote_active:
        items.append(
            CheckItem(
                "Paper promote ema_9_21 max drawdown",
                f"{settings.effective_pretrade_max_drawdown_pct:.2%}",
                (
                    "PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT applied to "
                    "research walk-forward maxDD (train=180 / test=60 / "
                    "step=60, warmup=train) — the #95–#100 definition. "
                    "Full-history backtest DD is a different series "
                    "(ETH ~43% on 400d) and is not this ceiling. "
                    f"PRETRADE_MAX_DRAWDOWN_PCT={settings.pretrade_max_drawdown_pct:.2%} "
                    "is the 1h / live / shadow bar and is not used on this path"
                ),
            )
        )
        items.append(
            CheckItem(
                "Paper promote candle count",
                str(settings.effective_pretrade_candle_count),
                (
                    "forced to the #95–#100 Kraken public OHLC cap "
                    f"({EMA_9_21_PAPER_CANDLE_COUNT}); "
                    f"PRETRADE_CANDLE_COUNT={settings.pretrade_candle_count} "
                    "is the 1h MA lookback and is not used on this path"
                ),
            )
        )
        if (
            settings.paper_promote_ema_9_21_max_drawdown_pct
            < EMA_9_21_PAPER_RESEARCH_WF_MAX_DRAWDOWN_PCT
        ):
            warnings.append(
                "PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT is tighter than the "
                "documented ema_9_21 Kraken daily WF maxDD (~23.35% on BTC+ETH). "
                "The daily promote path will reject cycles with "
                "walkforward_drawdown_above_maximum. Leave the "
                "documented default or raise it to the research envelope."
            )
        if settings.paper_promote_ema_9_21_max_drawdown_pct > EMA_9_21_PAPER_MAX_DRAWDOWN_PCT:
            warnings.append(
                "PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT is above the "
                "documented 0.30 BTC+ETH research envelope (ETH WF maxDD "
                "~28.77%). Do not raise this to cover full-history "
                "backtest DD (ETH ~43% on 400 daily bars) — that is a "
                "different series than the #95–#100 walk-forward definition."
            )
        if settings.paper_promote_ema_9_21_max_drawdown_pct >= 1.0:
            warnings.append(
                "PAPER_PROMOTE_EMA_9_21_MAX_DRAWDOWN_PCT=1.0 disables the "
                "pre-trade drawdown gate on the daily promote path. Do not "
                "disable the gate to 'see if it trades'."
            )
    if settings.paper_promote_ema_9_21 and settings.trading_mode != "paper":
        warnings.append(
            "PAPER_PROMOTE_EMA_9_21=true is ignored unless TRADING_MODE=paper. "
            "Live/shadow do not register ema_9_21 and keep "
            "PRETRADE_MAX_DRAWDOWN_PCT."
        )
    if settings.paper_promote_ema_9_21_active and settings.paper_promote_searched_strategies:
        warnings.append(
            "PAPER_PROMOTE_EMA_9_21=true takes precedence over "
            "PAPER_PROMOTE_SEARCHED_STRATEGIES; only ema_9_21 is registered."
        )

    # --- expanded harder-gates ema_9_21_adx15 paper voter ---
    items.append(
        CheckItem(
            "Promote ema_9_21_adx15 as paper voter",
            (
                "active"
                if settings.paper_promote_ema_9_21_adx15_active
                else "ignored"
                if settings.paper_promote_ema_9_21_adx15
                else "no"
            ),
            (
                "sole voter ema_9_21_adx15; defaults suppressed; "
                f"candles forced {settings.effective_pretrade_candle_interval} "
                "(Kraken 1440); do not claim daily edge on 1h bars"
                if settings.paper_promote_ema_9_21_adx15_active
                else (
                    "PAPER_PROMOTE_EMA_9_21 takes precedence; ema_9_21_adx15 not registered"
                    if settings.paper_promote_ema_9_21_adx15 and settings.paper_promote_ema_9_21
                    else (
                        "PAPER_PROMOTE_EMA_9_21_ADX15 is paper-only; "
                        f"TRADING_MODE={settings.trading_mode}"
                        if settings.paper_promote_ema_9_21_adx15
                        else "default; ema_9_21_adx15 is not a paper voter"
                    )
                )
            ),
        )
    )
    if settings.paper_promote_ema_9_21_adx15 and settings.trading_mode != "paper":
        warnings.append(
            "PAPER_PROMOTE_EMA_9_21_ADX15=true is ignored unless TRADING_MODE=paper. "
            "Live/shadow do not register ema_9_21_adx15 and keep "
            "PRETRADE_MAX_DRAWDOWN_PCT."
        )
    if settings.paper_promote_ema_9_21 and settings.paper_promote_ema_9_21_adx15:
        warnings.append(
            "PAPER_PROMOTE_EMA_9_21=true takes precedence over "
            "PAPER_PROMOTE_EMA_9_21_ADX15; only ema_9_21 is registered."
        )
    if settings.paper_promote_ema_9_21_adx15_active and settings.paper_promote_searched_strategies:
        warnings.append(
            "PAPER_PROMOTE_EMA_9_21_ADX15=true takes precedence over "
            "PAPER_PROMOTE_SEARCHED_STRATEGIES; only ema_9_21_adx15 is registered."
        )

    # --- paper daily promote universe (#100 honesty) ---
    envelope = ", ".join(PAPER_PROMOTE_UNIVERSE_SYMBOLS)
    configured_universe = ", ".join(settings.configured_promote_universe_symbols) or "(empty)"
    active_universe = ", ".join(settings.effective_promote_universe_symbols) or "(empty)"
    items.append(
        CheckItem(
            "Paper promote universe",
            (
                active_universe
                if settings.paper_daily_promote_active
                else "ignored"
                if settings.paper_promote_ema_9_21 or settings.paper_promote_ema_9_21_adx15
                else configured_universe
            ),
            (
                f"PAPER_PROMOTE_UNIVERSE; #100 honesty pack (BTC+ETH envelope). "
                f"MVP_ASSETS names outside {envelope} are skipped with "
                "promote_universe_excluded; not a claim of edge"
                if settings.paper_daily_promote_active
                else (
                    "daily pin is ignored unless TRADING_MODE=paper; "
                    f"full MVP_ASSETS still cycles ({', '.join(settings.assets) or 'none'})"
                    if settings.paper_promote_ema_9_21 or settings.paper_promote_ema_9_21_adx15
                    else (f"used only when a daily paper pin is on; hard envelope {envelope}")
                )
            ),
        )
    )
    extras = [
        symbol
        for symbol in settings.configured_promote_universe_symbols
        if symbol not in PAPER_PROMOTE_UNIVERSE_SYMBOLS
    ]
    if extras and (settings.paper_promote_ema_9_21 or settings.paper_promote_ema_9_21_adx15):
        warnings.append(
            "PAPER_PROMOTE_UNIVERSE includes "
            f"{', '.join(extras)} which is outside the #100 BTC/USD + ETH/USD "
            "research envelope and is ignored. SOL's ~50% WF maxDD is why "
            "that name is not on the promote path."
        )
    if settings.paper_daily_promote_active and not settings.effective_promote_universe_symbols:
        warnings.append(
            "PAPER_PROMOTE_UNIVERSE / MVP_ASSETS / {BTC/USD, ETH/USD} "
            "intersection is empty. The daily promote path will refuse to "
            "start rather than cycle a name outside the #100 envelope."
        )

    # --- intraday dual-print search (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "Intraday (4h/1h) dual-print search",
            "report-only",
            "traderstack-intraday-dual-print; #96+A+B+C on Kraken Spot "
            "and Binance.US older-720 of the same interval; no new "
            "PAPER_PROMOTE_* unless a dual-print passer exists (default false)",
        )
    )

    # --- funding / carry search (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "Funding / carry search",
            "report-only",
            "traderstack-funding-carry; OKX + Hyperliquid + HTX "
            "funding-z + hedged carry on BTC+ETH (BitMEX sunset "
            "23 September 2026 04:00 UTC, not selected; Binance/Bybit "
            "probed, skip-not-invent); "
            "1d resamples funding to UTC daily sums; PIT basis probed on "
            "Hyperliquid+HTX and recorded UNAVAILABLE on the current "
            "Kraken 720 (skip-not-invent); "
            # --- second-venue PIT basis (#134) ---
            "second-venue PIT basis: OKX + Binance Vision daily mark−index "
            "(traderstack-download-basis → --basis-dir; premium/last-trade "
            "refused; one venue alone is not applied; report-only); "
            "paper hedge+funding soak path is cycle-wired "
            "(PAPER_CARRY_PATH_READY=true when PAPER_PERP_HEDGE fetches "
            "an explicit HL/HTX mid + same-venue funding); snapshot "
            "mids are not historical PIT basis; single-print cannot "
            "promote; no new PAPER_PROMOTE_* unless dual-print + hard "
            "gates + PIT basis + paper path all clear (default false)",
        )
    )

    # --- BTC−ETH relative-value residual (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "BTC−ETH relative-value residual search",
            "report-only",
            "traderstack-relative-value; fade/follow daily BTC minus ETH "
            "excess return at frozen |z| thresholds; #96+A+B+C on Kraken "
            "Spot daily 720 and Binance.US older-720; paper-executable on "
            "Kraken spot BTC/ETH; no new PAPER_PROMOTE_* unless a "
            "dual-print passer exists (default false)",
        )
    )

    # --- cross-sectional momentum (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "BTC+ETH+SOL cross-sectional momentum search",
            "report-only",
            "traderstack-xs-momentum; long top-1 / optional short "
            "bottom-1 by frozen N-day return among BTC+ETH+SOL; "
            "#96+A+B+C on Kraken Spot daily 720 and Binance.US "
            "older-720 (SOL reported, not a gate); paper-executable "
            "on Kraken spot BTC/ETH/SOL; no new PAPER_PROMOTE_* "
            "unless a dual-print passer exists (default false)",
        )
    )

    # --- Donchian / channel breakout (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "Donchian / channel-breakout search",
            "report-only",
            "traderstack-donchian-breakout; long-only / long-short / "
            "ATR-buffered prior N-day channel on BTC+ETH (N in "
            "{20,55,100}); #96+A+B+C on Kraken Spot daily 720 and "
            "Binance.US older-720 (SOL reported, not a gate); "
            "paper-executable on Kraken spot BTC/ETH; no new "
            "PAPER_PROMOTE_* unless a dual-print passer exists "
            "(default false)",
        )
    )

    # --- time-series momentum (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "Time-series momentum search",
            "report-only",
            "traderstack-tsmom; long-only / long-short on each "
            "asset's own trailing N-day close-to-close return "
            "(N in {21,63,126,252}); #96+A+B+C on Kraken Spot "
            "daily 720 and Binance.US older-720 (SOL reported, "
            "not a gate); paper-executable on Kraken spot "
            "BTC/ETH; no new PAPER_PROMOTE_* unless a "
            "dual-print passer exists (default false)",
        )
    )

    # --- Bollinger band-fade (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "Bollinger band-fade search",
            "report-only",
            "traderstack-bollinger-fade; fade-to-inside / "
            "long-only fade / squeeze-breakout contrast on "
            "own-asset SMA ± k × sample stdev (period×k in "
            "{20x2,20x2.5,40x2}); #96+A+B+C on Kraken Spot "
            "daily 720 and Binance.US older-720 (SOL reported, "
            "not a gate); paper-executable on Kraken spot "
            "BTC/ETH; no new PAPER_PROMOTE_* unless a "
            "dual-print passer exists (default false)",
        )
    )

    # --- calendar seasonality (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "Calendar seasonality search",
            "report-only",
            "traderstack-calendar-seasonality; UTC day-of-week / "
            "month-of-year / turn-of-month long-only on the civil "
            "calendar of bar t (Mon / Fri / Mon+Fri / skip-weekend / "
            "Q4 / Jan / Nov+Dec / last-3+first-3); #96+A+B+C on "
            "Kraken Spot daily 720 and Binance.US older-720 (SOL "
            "reported, not a gate); paper-executable on Kraken "
            "spot BTC/ETH; no new PAPER_PROMOTE_* unless a "
            "dual-print passer exists (default false)",
        )
    )

    # --- BTC→ETH lead-lag (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "BTC→ETH lead-lag search",
            "report-only",
            "traderstack-lead-lag; ETH follows or fades lagged BTC "
            "L-day return (L in {1,2,3,5} follow-lo; {1,2,3} "
            "follow-ls / fade-lo; BTC-follows-ETH mirror lo {1,2}); "
            "not same-bar residual z-score; #96+A+B+C on Kraken "
            "Spot daily 720 and Binance.US older-720 (other leg "
            "flat; both legs required); paper-executable on "
            "Kraken spot BTC/ETH; no new PAPER_PROMOTE_* unless a "
            "dual-print passer exists (default false)",
        )
    )

    # --- volume-confirmed breakout (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "Volume-confirmed breakout search",
            "report-only",
            "traderstack-volume-breakout; long-only / long-short "
            "volume-confirmed prior N-day channel (N×mult in "
            "{20x1.5,55x1.5,20x2}; V=20 SMA through t−1) plus "
            "volume-surge long-only; not a Donchian N retune; "
            "#96+A+B+C on Kraken Spot daily 720 and Binance.US "
            "older-720 (SOL reported, not a gate); paper-executable "
            "on Kraken spot BTC/ETH; no new PAPER_PROMOTE_* unless "
            "a dual-print passer exists (default false)",
        )
    )

    # --- multi-year candle archives (#133) ---
    archive_path = settings.research_kraken_archive_path.strip()
    items.append(
        CheckItem(
            "Multi-year candle archives",
            "research-only",
            "traderstack-download-candles --venue coinbase|binance_vision|"
            "kraken_archive; longer history than Kraken's 720-bar REST cap. "
            "Offline research input only: never on the trading cycle, never "
            "read by the RiskEngine, and no PAPER_PROMOTE_* effect. Coinbase "
            "is paced inside its 10 req/s public limit and treats HTTP 429 as "
            "a skip; Binance Vision zips are sha256-verified against the "
            "published .CHECKSUM and fail closed; missing bars stay gaps",
        )
    )
    items.append(
        CheckItem(
            "  Kraken OHLCVT archive path",
            archive_path or "(unset)",
            (
                "manual download (support article 360047124832), ACTIVE PAIRS "
                "ONLY — survivorship-biased; a partial or unparsable file is "
                "refused outright"
            )
            if archive_path
            else "unset: --venue kraken_archive skips unless --archive-path is given",
        )
    )

    # --- Pre-trade self-check (backtest gate) -----------------------------------------
    items.append(
        CheckItem(
            "Pre-trade backtest gate",
            "enabled" if settings.pretrade_backtest_enabled else "disabled",
        )
    )
    if not settings.pretrade_backtest_enabled:
        warnings.append(
            "PRETRADE_BACKTEST_ENABLED=false: proposals reach the risk engine without a "
            "backtest/walk-forward self-check. This only removes a rejection source; the "
            "risk engine's hard limits still apply, but this reduces defense in depth."
        )

    # --- paper research mode ---
    if settings.paper_research_active:
        min_voters = 1 if not settings.optional_intelligence_configured else 2
        items.append(
            CheckItem(
                "Paper research mode",
                "active",
                f"candle-only baseline voter; min agreeing strategies={min_voters}",
            )
        )
    elif settings.paper_research_mode and settings.trading_mode != "paper":
        items.append(
            CheckItem(
                "Paper research mode",
                "ignored",
                f"PAPER_RESEARCH_MODE is paper-only; TRADING_MODE={settings.trading_mode}",
            )
        )
        warnings.append(
            "PAPER_RESEARCH_MODE=true is ignored unless TRADING_MODE=paper. "
            "Live/shadow keep the two-voter candle ensemble (see docs/RUNBOOK.md, "
            "'Paper research mode and strategy consensus')."
        )
    else:
        items.append(
            CheckItem(
                "Paper research mode",
                "off",
                "default two-voter candle ensemble; no paper-research baseline",
            )
        )

    # --- paper reference resilience / paper pretrade thresholds ---
    if settings.trading_mode == "paper":
        items.append(
            CheckItem(
                "Paper reference resilience",
                "active",
                f"cache {settings.paper_reference_cache_seconds:g}s; "
                f"last-good {settings.paper_reference_last_good_seconds:g}s on fetch failure",
            )
        )
        items.append(
            CheckItem(
                "Paper pretrade thresholds",
                "active",
                f"min total return={settings.paper_pretrade_min_total_return}; "
                f"min excess={settings.paper_pretrade_min_excess_return}; "
                f"min Sharpe={settings.paper_pretrade_min_sharpe}; "
                f"min trades={settings.paper_pretrade_min_trades}",
            )
        )
    else:
        items.append(
            CheckItem(
                "Paper reference resilience",
                "ignored",
                f"TRADING_MODE={settings.trading_mode}; last-good disabled (fail-closed)",
            )
        )
        items.append(
            CheckItem(
                "Paper pretrade thresholds",
                "ignored",
                f"TRADING_MODE={settings.trading_mode}; using PRETRADE_MIN_EXCESS_RETURN/"
                "PRETRADE_MIN_SHARPE",
            )
        )

    # --- Intelligence providers --------------------------------------------------------
    intelligence_providers = (
        ("Dune (on-chain)", settings.dune_api_key, bool(settings.dune_query_ids.strip())),
        ("LunarCrush (social)", settings.lunarcrush_api_key, True),
        ("CryptoPanic (news)", settings.cryptopanic_api_key, True),
        ("Perplexity (news)", settings.perplexity_api_key, True),
        ("altFINS (technical signal)", settings.altfins_api_key, True),
    )
    any_intelligence = False
    for label, key, extra_ok in intelligence_providers:
        present = _has_secret(key) and extra_ok
        any_intelligence = any_intelligence or present
        detail = ""
        if _has_secret(key) and not extra_ok:
            detail = "key set but DUNE_QUERY_IDS is empty — provider will not be used"
        items.append(CheckItem(f"  {label}", _flag(present), detail))

    # --- crucix intel ---
    crucix_present = crucix_should_register(
        enabled=settings.crucix_enabled,
        base_url=settings.crucix_base_url,
        api_key=settings.crucix_api_key.get_secret_value() if settings.crucix_api_key else None,
    )
    any_intelligence = any_intelligence or crucix_present
    items.append(
        CheckItem(
            "  Crucix (news/alerts)",
            _flag(crucix_present),
            crucix_effective_base_url(settings.crucix_base_url) if crucix_present else "",
        )
    )
    items.append(
        CheckItem(
            "Intelligence: Crucix outage fails closed",
            _flag(crucix_present),
            (
                "opted in: timeout/error rejects new risk with "
                "intelligence_provider_unavailable (paper/shadow/live share this path)"
                if crucix_present
                else "unused unless CRUCIX_ENABLED or CRUCIX_BASE_URL / CRUCIX_API_KEY is set"
            ),
        )
    )

    items.append(
        CheckItem(
            "Intelligence: cycle requires >=1 provider",
            _flag(settings.intelligence_required),
        )
    )
    if settings.intelligence_required and not any_intelligence:
        warnings.append(
            "INTELLIGENCE_REQUIRED=true but no intelligence provider has usable "
            "credentials (key + any required extra setting). The runtime raises at "
            "startup in this state."
        )
    items.append(
        CheckItem(
            "Intelligence: block on adverse news",
            _flag(settings.intelligence_block_on_adverse_news),
        )
    )

    # --- Reference price providers -----------------------------------------------------
    items.append(
        CheckItem("  CoinGecko reference price", _flag(_has_secret(settings.coingecko_api_key)))
    )
    items.append(
        CheckItem(
            "  CoinMarketCap reference price", _flag(_has_secret(settings.coinmarketcap_api_key))
        )
    )
    items.append(
        CheckItem(
            "  (both work unauthenticated too, at lower rate limits)",
            "",
        )
    )

    # --- Constrained meta-agent (Epic 6) ------------------------------------------------
    items.append(CheckItem("Meta-agent mode", settings.meta_agent_mode))
    anthropic_key_present = _has_secret(settings.anthropic_api_key)
    if settings.meta_agent_mode != "off":
        items.append(CheckItem("  model", settings.meta_agent_model))
        items.append(CheckItem("  ANTHROPIC_API_KEY present", _flag(anthropic_key_present)))
        items.append(
            CheckItem(
                "  daily budget (calls/tokens)",
                f"{settings.meta_agent_max_calls_per_day or '∞'}/"
                f"{settings.meta_agent_max_tokens_per_day or '∞'}",
            )
        )
        items.append(CheckItem("  evidence cache seconds", str(settings.meta_agent_cache_seconds)))
    if settings.meta_agent_mode == "veto" and not anthropic_key_present:
        warnings.append(
            "META_AGENT_MODE=veto but ANTHROPIC_API_KEY is not set: the runtime raises at "
            "startup rather than running a veto gate with no reviewer behind it "
            "(see docs/RUNBOOK.md, 'Meta-agent modes and budgets')."
        )
    elif settings.meta_agent_mode == "advisory":
        items.append(
            CheckItem(
                "  advisory-mode effect",
                "recorded only",
                "does not change confidence, sizing, or whether the order is sent",
            )
        )

    # --- Robinhood Chain execution scaffolding ------------------------------------------
    robinhood_execution_configured = bool(
        settings.robinhood_chain_rpc_url
        and settings.robinhood_chain_id
        and settings.robinhood_chain_allowed_tokens.strip()
        and settings.robinhood_chain_allowed_routers.strip()
    )
    items.append(
        CheckItem(
            "Robinhood Chain execution configured",
            _flag(robinhood_execution_configured),
            "rpc/chain id/token+router allowlists" if not robinhood_execution_configured else "",
        )
    )
    items.append(
        CheckItem(
            "  max notional (USD)",
            str(settings.robinhood_chain_max_notional_usd),
        )
    )
    if robinhood_execution_configured and settings.robinhood_chain_max_notional_usd <= 0:
        warnings.append(
            "Robinhood Chain execution is configured (rpc/chain id/allowlists set) but "
            "ROBINHOOD_CHAIN_MAX_NOTIONAL_USD<=0, which blocks every transaction by policy. "
            "This fails closed rather than unsafely — no action required unless unintended."
        )

    # --- Hummingbot paper execution -----------------------------------------------------
    hummingbot_credentials = bool(settings.hummingbot_api_username) and _has_secret(
        settings.hummingbot_api_password
    )
    items.append(
        CheckItem(
            "Execution submit possible (Hummingbot)",
            _flag(hummingbot_credentials),
            "requires HUMMINGBOT_API_USERNAME and HUMMINGBOT_API_PASSWORD"
            if not hummingbot_credentials
            else "",
        )
    )
    items.append(CheckItem("  account", settings.hummingbot_account_name))
    items.append(CheckItem("  connector", settings.hummingbot_connector_name))

    # --- Execution hardening (Epic 8): reconciliation gate & retries -------------------
    items.append(CheckItem("Reconcile interval (s)", str(settings.reconcile_interval_seconds)))
    items.append(CheckItem("Max NAV drift (bps)", str(settings.max_nav_drift_bps)))
    items.append(
        CheckItem(
            "Execution submit timeout / retries",
            f"{settings.execution_submit_timeout_seconds}s / {settings.execution_max_retries}",
        )
    )
    items.append(
        CheckItem(
            "  min notional / lot step / max slippage (bps)",
            f"${settings.execution_min_notional_usd} / {settings.execution_lot_step} / "
            f"{settings.execution_max_slippage_bps}",
        )
    )

    # --- Provider health, quota and caching wrapper (Epic 2/3) -------------------------
    items.append(
        CheckItem(
            "Provider timeout / failure threshold / cooldown (s)",
            f"{settings.provider_timeout_seconds}s / {settings.provider_failure_threshold} / "
            f"{settings.provider_breaker_cooldown_seconds}",
        )
    )
    items.append(
        CheckItem(
            "  CoinGecko quota (per min/day)",
            f"{settings.coingecko_calls_per_minute or 'unlimited'}/"
            f"{settings.coingecko_calls_per_day or 'unlimited'}",
        )
    )
    items.append(
        CheckItem(
            "  CoinMarketCap quota (per min/day)",
            f"{settings.coinmarketcap_calls_per_minute or 'unlimited'}/"
            f"{settings.coinmarketcap_calls_per_day or 'unlimited'}",
        )
    )
    items.append(
        CheckItem(
            "  candle provider quota (per min)",
            str(settings.candle_provider_calls_per_minute or "unlimited"),
        )
    )
    items.append(
        CheckItem(
            "  intelligence provider quota (per min)",
            str(settings.intelligence_provider_calls_per_minute or "unlimited"),
        )
    )

    # --- Kill switch channels (Epic 7): all four are independently sufficient ----------
    items.append(CheckItem("  sentinel file path", settings.kill_switch_file))
    items.append(
        CheckItem(
            "  Redis channel",
            _flag(settings.kill_switch_redis_enabled),
            settings.kill_switch_redis_key if settings.kill_switch_redis_enabled else "",
        )
    )
    items.append(
        CheckItem(
            "  channels",
            "settings flag, sentinel file, Redis key (if enabled), SIGUSR1 — any one halts",
        )
    )

    # --- audit anchoring (#68) ---
    if settings.audit_anchor_enabled:
        channels = "local file"
        if settings.audit_anchor_redis_enabled:
            channels += f", Redis ({settings.audit_anchor_redis_key})"
        items.append(
            CheckItem(
                "Audit anchoring",
                "on",
                f"every {settings.audit_anchor_every} records + shutdown -> {channels}",
            )
        )
        if not settings.audit_anchor_redis_enabled:
            items.append(
                CheckItem(
                    "  root of trust",
                    "local file only",
                    "same host as the trail it protects; enable AUDIT_ANCHOR_REDIS_ENABLED "
                    "with an insert-only ACL to move it off-process",
                )
            )
        items.append(CheckItem("  verify with", "traderstack-verify-audit"))
    else:
        items.append(
            CheckItem(
                "Audit anchoring",
                "off",
                "verify_chain alone cannot detect a whole-file rewrite of the "
                "risk audit trail (#68)",
            )
        )

    # --- position management (#58) ---
    if settings.position_exits_active:
        items.append(
            CheckItem(
                "Position exits",
                "active",
                f"stop {settings.exit_stop_loss_pct:.2%} / "
                f"TP {settings.exit_take_profit_pct:.2%} / "
                f"trail {settings.exit_trailing_stop_pct:.2%} / "
                f"time {settings.exit_time_stop_bars} bars / "
                f"thesis={'on' if settings.exit_on_thesis_invalidation else 'off'}",
            )
        )
    elif settings.trading_mode == "live" and settings.position_exits_enabled_by_settings:
        items.append(
            CheckItem(
                "Position exits",
                "ignored",
                f"TRADING_MODE=live; EXIT_* rules stay off until documented "
                f"(stop {settings.exit_stop_loss_pct:.2%})",
            )
        )
        warnings.append(
            "EXIT_* settings are configured but TRADING_MODE=live: position exits "
            "are not evaluated on the live path (see docs/RUNBOOK.md, "
            "'Deterministic position exits')."
        )
    else:
        items.append(
            CheckItem(
                "Position exits",
                "disabled",
                "no stop/TP/time/thesis rule is configured",
            )
        )

    # --- Risk policy limits (values only, no secrets) -----------------------------------
    items.append(CheckItem("Assets allowlisted", ", ".join(settings.assets) or "(none)"))
    items.append(CheckItem("Max position % of NAV", f"{settings.max_position_pct:.2%}"))
    items.append(CheckItem("Max daily loss % of NAV", f"{settings.max_daily_loss_pct:.2%}"))
    items.append(CheckItem("Max account drawdown %", f"{settings.max_account_drawdown_pct:.2%}"))
    # --- paper fees (#66) ---
    items.append(
        CheckItem(
            "Paper fee (bps)",
            str(settings.paper_fee_bps),
            "charged on a fill when the venue reports no fee; applied to NAV and breakers",
        )
    )
    if settings.paper_fee_bps == 0:
        warnings.append(
            "PAPER_FEE_BPS=0: fills with no venue fee are booked gross. Daily-loss and "
            "drawdown breakers will be optimistic versus a live fee schedule. Set this "
            "to match PRETRADE_FEE_BPS (default 10) unless the venue always reports fees."
        )

    # --- miles-inspired GARCH sizing (paper research) --------------------------------
    items.append(
        CheckItem(
            "Paper GARCH size overlay",
            "active" if settings.paper_garch_size_active else "off",
            (
                f"target vol={settings.paper_garch_target_vol:g}; reduce-only"
                if settings.paper_garch_size_active
                else "default; RiskEngine does not apply GARCH size"
            ),
        )
    )
    if settings.paper_garch_size and settings.trading_mode != "paper":
        warnings.append(
            "PAPER_GARCH_SIZE=true is ignored unless TRADING_MODE=paper. "
            "Live/shadow do not apply the GARCH overlay."
        )
    if settings.paper_garch_size_active:
        warnings.append(
            "PAPER_GARCH_SIZE=true: leave this false until "
            "docs/artifacts/strategy-search/miles-inspired-report.md shows a "
            "candidate with walk-forward total_return>0 and holdout "
            "excess_return>0 after fees. The overlay can only reduce size."
        )
    # --- paper fill simulation ---
    items.append(
        CheckItem(
            "Paper simulate fills",
            (
                "active"
                if settings.trading_mode == "paper" and settings.paper_simulate_fills
                else "ignored"
            ),
            (
                # --- fee realism (#138) --- PAPER_FEE_TIER taker (PAPER_FEE_BPS when modelled)
                f"mid ± {settings.paper_slippage_bps:g} bps; fee "
                f"{settings.effective_paper_fee_bps:g} bps ({settings.paper_fee_tier}); "
                "no Hummingbot required"
                if settings.trading_mode == "paper" and settings.paper_simulate_fills
                else (
                    f"TRADING_MODE={settings.trading_mode}"
                    if settings.trading_mode != "paper"
                    else "PAPER_SIMULATE_FILLS=false; NAV stays flat until a venue fill"
                )
            ),
        )
    )
    if (
        settings.trading_mode == "paper"
        and settings.paper_simulate_fills
        and settings.paper_slippage_bps > settings.execution_max_slippage_bps
    ):
        warnings.append(
            "PAPER_SLIPPAGE_BPS exceeds EXECUTION_MAX_SLIPPAGE_BPS: the planner will "
            "reject every paper fill (fail closed). Lower PAPER_SLIPPAGE_BPS or raise "
            "the execution slippage cap."
        )

    # --- paper perp / hedge path ---
    items.append(
        CheckItem(
            "Paper perp / hedge stub",
            (
                "active (cannot promote)"
                if settings.trading_mode == "paper" and settings.paper_perp_hedge
                else "off"
            ),
            (
                "TRADING_MODE=paper only; kill switch withholds new hedges; "
                "fetches explicit HL midPx / HTX bid/ask mid (never Kraken "
                "spot; BitMEX not required); same-venue public funding tape; "
                "PAPER_CARRY_PATH_READY is the soak path only; PIT basis "
                "UNAVAILABLE so cannot promote; no PAPER_PROMOTE_* flip"
                if settings.trading_mode == "paper"
                else f"ignored unless TRADING_MODE=paper (got {settings.trading_mode!r})"
            ),
        )
    )
    if settings.paper_perp_hedge and settings.trading_mode != "paper":
        warnings.append(
            "PAPER_PERP_HEDGE is paper-only; "
            f"TRADING_MODE={settings.trading_mode} ignores the path and "
            "cannot enable live."
        )
    if settings.paper_perp_hedge and settings.trading_mode == "paper":
        warnings.append(
            "PAPER_PERP_HEDGE=true exercises the paper hedge+funding soak "
            "(explicit HL/HTX mid + same-venue funding; BitMEX not "
            "required). PIT basis is UNAVAILABLE on Hyperliquid+HTX for "
            "the current Kraken 720; snapshot mids are not a "
            "historical series. Leave every PAPER_PROMOTE_* false."
        )

    # --- opportunity funnel (#131) ---------------------------------------------------
    items.append(
        CheckItem(
            "Opportunity diagnostic mode",
            "active (no fills, no submissions)" if settings.opportunity_diagnostic_mode else "off",
            (
                "every gate runs and is audited unchanged; paper fills and venue submits "
                "are withheld (execution_status=diagnostic_withheld); the funnel names "
                "the nearest blocking gate per cycle. NAV will not move."
                if settings.opportunity_diagnostic_mode
                else "fills/submits follow PAPER_SIMULATE_FILLS and --submit"
            ),
        )
    )

    # --- polymarket weather research (paper-only, opt-in) ------------------------------
    items.append(
        CheckItem(
            "Polymarket weather research",
            "enabled" if settings.polymarket_weather_enabled else "disabled (opt-in)",
            "dedicated CLI; crypto paper loop does not read this",
        )
    )
    items.append(
        CheckItem(
            "  paper intents only (no CLOB orders)",
            "yes",
            "no private key / signing settings exist",
        )
    )
    items.append(
        CheckItem(
            "  MIN_EDGE / cities / forecast",
            f"{settings.polymarket_weather_min_edge:.2f} / "
            f"{settings.polymarket_weather_cities or '(none)'} / "
            f"{settings.polymarket_weather_forecast_provider}",
        )
    )
    items.append(CheckItem("  paper ledger", settings.polymarket_weather_ledger_path))
    # --- polymarket weather eval (report-only; no promote pin) ---
    items.append(
        CheckItem(
            "  fee-aware weather eval CLI",
            "report-only",
            "traderstack-polymarket-weather-eval; dual independent prints "
            "required to promote; no PAPER_PROMOTE_POLYMARKET_WEATHER pin",
        )
    )
    if settings.polymarket_weather_enabled and settings.trading_mode != "paper":
        warnings.append(
            "POLYMARKET_WEATHER_ENABLED=true but TRADING_MODE="
            f"{settings.trading_mode!r}: the weather CLI refuses to run unless "
            "TRADING_MODE=paper. Live Polymarket CLOB trading is not implemented."
        )
    if settings.polymarket_weather_enabled and not settings.polymarket_weather_city_slugs:
        warnings.append(
            "POLYMARKET_WEATHER_ENABLED=true but POLYMARKET_WEATHER_CITIES is empty: "
            "the weather CLI fails closed (no cities to research)."
        )

    # --- fee realism (#138) ---
    fee_tier = resolve_fee_tier(settings.paper_fee_tier)
    items.append(
        CheckItem(
            "Paper fee tier",
            settings.paper_fee_tier,
            (
                f"maker {fee_tier.maker_bps:g} / taker {fee_tier.taker_bps:g} bps; paper "
                "fills, no-venue-fee reconcile fallback and research charge taker "
                f"{settings.effective_paper_fee_bps:g} bps (research fee = max(PRETRADE_FEE_BPS "
                f"{settings.pretrade_fee_bps:g}, taker) = "
                f"{max(settings.pretrade_fee_bps, settings.effective_paper_fee_bps):g}); "
                "maker not assumed (no post-only fill-rate evidence); PAPER_FEE_BPS "
                f"{settings.paper_fee_bps:g} only when PAPER_FEE_TIER=modelled and on the "
                f"paper perp stub; source {fee_tier.source} read {fee_tier.read_on}"
            ),
        )
    )
    if settings.paper_fee_tier == MODELLED_FEE_TIER_ID:
        warnings.append(
            f"PAPER_FEE_TIER=modelled: research and paper fills use the pre-#138 "
            f"PAPER_FEE_BPS={settings.paper_fee_bps:g} bps model, four to eight times "
            "optimistic versus Kraken Pro Tier 1 (taker 80 bps). Set "
            f"PAPER_FEE_TIER={PILOT_FEE_TIER_ID} for a pilot-sized account."
        )

    # --- polymarket crypto-threshold vs Deribit wedge tape (#142; paper-only, opt-in) ---
    items.append(
        CheckItem(
            "Polymarket crypto wedge tape",
            "enabled" if settings.polymarket_crypto_tape_enabled else "disabled (opt-in)",
            "traderstack-polymarket-crypto-collect; read-only tape of CLOB mid vs "
            "Deribit option-implied probability; no CLOB orders, no signing",
        )
    )
    items.append(
        CheckItem(
            "  Deribit read-only (no private endpoints)",
            _flag(True),
            f"{settings.deribit_base_url} public/get_instruments + "
            "public/get_book_summary_by_currency, GET only",
        )
    )
    items.append(
        CheckItem(
            "  assets / lookahead / freshness / expiry gap",
            f"{settings.polymarket_crypto_assets or '(none)'} / "
            f"{settings.polymarket_crypto_lookahead_days}d / "
            f"{settings.polymarket_crypto_max_staleness_seconds:g}s / "
            f"{settings.polymarket_crypto_max_expiry_gap_hours:g}h",
            "a stale or one-sided read is recorded with a non-ok status, never as a zero",
        )
    )
    items.append(CheckItem("  wedge tape path", settings.polymarket_crypto_tape_path))
    crypto_crucix_on = crucix_should_register(
        enabled=settings.crucix_enabled,
        base_url=settings.crucix_base_url,
        api_key=settings.crucix_api_key.get_secret_value() if settings.crucix_api_key else None,
    )
    items.append(
        CheckItem(
            "  Crucix stand-aside gate",
            "configured (withhold-only)"
            if crypto_crucix_on
            else "not configured: every row records not_configured; gated mask will be empty",
        )
    )
    items.append(
        CheckItem(
            "  evaluator",
            "slice 2: traderstack-polymarket-crypto-eval not yet shipped",
            "no PAPER_PROMOTE_POLYMARKET_CRYPTO_WEDGE pin exists and none is planned here",
        )
    )
    if settings.polymarket_crypto_tape_enabled and settings.trading_mode != "paper":
        warnings.append(
            "POLYMARKET_CRYPTO_TAPE_ENABLED=true with TRADING_MODE="
            f"{settings.trading_mode}: the collector refuses to run outside paper mode."
        )
    if settings.polymarket_crypto_tape_enabled and not settings.polymarket_crypto_asset_list:
        warnings.append(
            "POLYMARKET_CRYPTO_TAPE_ENABLED=true with an empty POLYMARKET_CRYPTO_ASSETS: "
            "no event slug can be discovered and the tape will stay empty."
        )
    unknown_crypto_assets = [
        asset for asset in settings.polymarket_crypto_asset_list if asset not in {"BTC", "ETH"}
    ]
    if unknown_crypto_assets:
        warnings.append(
            "POLYMARKET_CRYPTO_ASSETS contains "
            f"{', '.join(unknown_crypto_assets)}: only BTC and ETH have both a daily "
            "Polymarket threshold event and a Deribit option chain; they are skipped."
        )

    return ConfigReport(items=items, warnings=warnings)


def render_report(report: ConfigReport, *, app_env: str) -> str:
    lines: list[str] = []
    lines.append(f"traderstack config check (APP_ENV={app_env})")
    lines.append("=" * 78)
    width = max((len(item.label) for item in report.items), default=0)
    for item in report.items:
        row = f"{item.label:<{width}}  {item.value}"
        if item.detail:
            row += f"   ({item.detail})"
        lines.append(row.rstrip())
    lines.append("=" * 78)
    if report.warnings:
        lines.append(f"{len(report.warnings)} unsafe combination(s) found:")
        for warning in report.warnings:
            lines.append(f"  - {warning}")
    else:
        lines.append("No unsafe combinations found.")
    return "\n".join(lines)


def main() -> None:
    settings = Settings()
    report = build_report(settings)
    print(render_report(report, app_env=settings.app_env))
    sys.exit(0 if report.safe else 1)


if __name__ == "__main__":
    main()
