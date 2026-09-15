"""One point-in-time wedge collection cycle (#142): discover → read → tape.

Never imported by the crypto paper loop. It emits no intents, no sizes and no
sides — only observations, each with both venue timestamps, appended to a
dedicated JSONL tape. The kill switch is refreshed and reported so an operator
sees its state, but there is nothing here for it to withhold (and deliberately
no "skip collection while engaged" behaviour, which would silently punch a hole
in the tape).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from traderstack.config import Settings
from traderstack.intelligence import NewsSnapshot
from traderstack.killswitch import KillSwitch
from traderstack.market.crucix import (
    CrucixIntelProvider,
    crucix_effective_base_url,
    crucix_should_register,
    parse_crucix_alerts,
)
from traderstack.market.deribit import (
    DeribitPublicClient,
    OptionInstrument,
    OptionQuote,
    reduce_book_summary,
    reduce_instruments,
)
from traderstack.market.registry import ProviderRegistry
from traderstack.polymarket.clob import ClobBook, ClobPublicClient, reduce_book
from traderstack.polymarket.crypto_gate import crucix_status_from_snapshot
from traderstack.polymarket.crypto_models import (
    CrucixStatus,
    CryptoAsset,
    CryptoWedgeRow,
    ParsedCryptoThresholdMarket,
    WedgeRowStatus,
)
from traderstack.polymarket.crypto_tape import CryptoWedgeTape
from traderstack.polymarket.crypto_threshold import (
    event_slugs,
    iter_event_markets,
    parse_crypto_threshold_market,
)
from traderstack.polymarket.gamma import GammaClient
from traderstack.polymarket.option_implied import implied_digital_probability
from traderstack.polymarket.service import require_paper_trading_mode

_REGISTRY_NAMES = ("polymarket_gamma", "polymarket_clob", "deribit", "crucix")


@dataclass
class CryptoWedgeFixtures:
    """Offline replacements for the Gamma / CLOB / Deribit / Crucix HTTP calls."""

    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    books: dict[str, Any] = field(default_factory=dict)
    deribit_instruments: dict[str, Any] = field(default_factory=dict)
    deribit_summary: dict[str, Any] = field(default_factory=dict)
    crucix: dict[str, Any] = field(default_factory=dict)
    now: datetime | None = None


@dataclass(frozen=True)
class _Chain:
    instruments: tuple[OptionInstrument, ...]
    quotes: tuple[OptionQuote, ...]
    error: str | None = None
    fetched_at: datetime | None = None


@dataclass
class CryptoWedgeCycleReport:
    trading_mode: str
    kill_switch_engaged: bool
    kill_switch_sources: tuple[str, ...]
    observed_at: datetime
    assets: tuple[str, ...]
    slugs_requested: int
    events_missing: int
    events_error: int
    markets_seen: int
    parsed: int
    unparsed: int
    rows_written: int
    rows_ok: int
    status_counts: dict[str, int]
    crucix_status: dict[str, str]
    chain_errors: dict[str, str]
    unknown_assets: tuple[str, ...] = ()
    rows: list[CryptoWedgeRow] = field(default_factory=list)

    def render(self) -> str:
        crucix = ", ".join(f"{k}={v}" for k, v in sorted(self.crucix_status.items())) or "-"
        statuses = ", ".join(f"{k}={v}" for k, v in sorted(self.status_counts.items())) or "-"
        lines = [
            (
                "Polymarket crypto-threshold vs Deribit wedge tape "
                "(paper_tape_only; read-only, no CLOB orders, no Deribit private endpoints)"
            ),
            f"TRADING_MODE={self.trading_mode}  kill_switch="
            f"{'engaged' if self.kill_switch_engaged else 'clear'}"
            + (f" ({', '.join(self.kill_switch_sources)})" if self.kill_switch_sources else ""),
            (
                f"observed_at={self.observed_at.isoformat()}  assets: "
                f"{', '.join(self.assets) or '(none)'}"
            ),
            (
                f"slugs={self.slugs_requested} events_missing={self.events_missing} "
                f"events_error={self.events_error} "
                f"markets_seen={self.markets_seen} parsed={self.parsed} "
                f"unparsed={self.unparsed} rows_written={self.rows_written} "
                f"rows_ok={self.rows_ok}"
            ),
            f"row status: {statuses}",
            f"crucix stand-aside: {crucix}",
        ]
        if self.unknown_assets:
            lines.append(
                "  skipped (no daily Polymarket event and/or no Deribit chain): "
                + ", ".join(self.unknown_assets)
            )
        if self.chain_errors:
            for asset, error in sorted(self.chain_errors.items()):
                lines.append(f"  deribit chain unavailable for {asset}: {error} (rows skipped)")
        if not self.rows_written:
            lines.append(
                "No rows written. An empty cycle is a successful result "
                "(no open event, or nothing fresh enough to record)."
            )
        lines.append(
            "Evidence only: no PnL, no promotion, no size and no side. The evaluator "
            "is a later slice; see docs/EVALUATION-FRAMEWORK.md (#142 pre-registered rules)."
        )
        return "\n".join(lines)


def _build_registries(settings: Settings) -> dict[str, ProviderRegistry]:
    return {
        name: ProviderRegistry(
            name=name,
            timeout_seconds=settings.provider_timeout_seconds,
            failure_threshold=settings.provider_failure_threshold,
            cooldown_seconds=settings.provider_breaker_cooldown_seconds,
            calls_per_minute=settings.polymarket_crypto_calls_per_minute,
            cache_ttl_seconds=settings.polymarket_crypto_cache_seconds,
        )
        for name in _REGISTRY_NAMES
    }


def _fixed_clock(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


def _secret(value: object) -> str | None:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        text = str(getter())
        return text or None
    if isinstance(value, str) and value.strip():
        return value
    return None


def resolve_assets(settings: Settings) -> tuple[tuple[CryptoAsset, ...], tuple[str, ...]]:
    """Return (known assets, unknown names). An unknown asset is skipped."""

    known: list[CryptoAsset] = []
    unknown: list[str] = []
    for name in settings.polymarket_crypto_asset_list:
        try:
            asset = CryptoAsset(name)
        except ValueError:
            unknown.append(name)
            continue
        if asset not in known:
            known.append(asset)
    return tuple(known), tuple(unknown)


@dataclass
class PolymarketCryptoWedgeCollector:
    settings: Settings
    tape: CryptoWedgeTape
    kill_switch: KillSwitch
    gamma: GammaClient | None = None
    clob: ClobPublicClient | None = None
    deribit: DeribitPublicClient | None = None
    crucix: CrucixIntelProvider | None = None
    fixtures: CryptoWedgeFixtures | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        tape: CryptoWedgeTape,
        kill_switch: KillSwitch,
        fixtures: CryptoWedgeFixtures | None = None,
    ) -> PolymarketCryptoWedgeCollector:
        require_paper_trading_mode(settings)
        if fixtures is not None:
            clock: Callable[[], datetime] = (
                _fixed_clock(fixtures.now)
                if fixtures.now is not None
                else (lambda: datetime.now(UTC))
            )
            return cls(
                settings=settings,
                tape=tape,
                kill_switch=kill_switch,
                fixtures=fixtures,
                clock=clock,
            )
        registries = _build_registries(settings)
        crucix: CrucixIntelProvider | None = None
        if crucix_should_register(
            enabled=settings.crucix_enabled,
            base_url=settings.crucix_base_url,
            api_key=_secret(settings.crucix_api_key),
        ):
            crucix = CrucixIntelProvider(
                base_url=crucix_effective_base_url(settings.crucix_base_url),
                api_key=_secret(settings.crucix_api_key),
            )
        return cls(
            settings=settings,
            tape=tape,
            kill_switch=kill_switch,
            gamma=GammaClient(
                base_url=settings.polymarket_gamma_base_url,
                registry=registries["polymarket_gamma"],
                timeout_seconds=settings.provider_timeout_seconds,
            ),
            clob=ClobPublicClient(
                base_url=settings.polymarket_clob_base_url,
                registry=registries["polymarket_clob"],
                timeout_seconds=settings.provider_timeout_seconds,
            ),
            deribit=DeribitPublicClient(
                base_url=settings.deribit_base_url,
                registry=registries["deribit"],
                timeout_seconds=settings.provider_timeout_seconds,
            ),
            crucix=crucix,
        )

    async def run_once(self) -> CryptoWedgeCycleReport:
        require_paper_trading_mode(self.settings)
        await self.kill_switch.refresh()
        now = self.clock()
        assets, unknown = resolve_assets(self.settings)

        chains: dict[CryptoAsset, _Chain] = {}
        crucix_status: dict[str, str] = {}
        statuses: dict[CryptoAsset, CrucixStatus] = {}
        chain_errors: dict[str, str] = {}
        for asset in assets:
            chain = await self._chain(asset, now)
            chains[asset] = chain
            if chain.error is not None:
                chain_errors[asset.value] = chain.error
            status = await self._crucix_status(asset)
            statuses[asset] = status
            crucix_status[asset.value] = status.value

        slugs = event_slugs(assets, now.date(), self.settings.polymarket_crypto_lookahead_days)
        events_missing = 0
        events_error = 0
        markets_seen = 0
        parsed_markets: list[ParsedCryptoThresholdMarket] = []
        unparsed = 0
        for slug in slugs:
            events, discovery_error = await self._events(slug)
            if discovery_error is not None:
                events_error += 1
                continue
            if not events:
                events_missing += 1
                continue
            for event_slug_text, payload in iter_event_markets(events):
                markets_seen += 1
                market = parse_crypto_threshold_market(payload, slug=event_slug_text or slug)
                if market is None:
                    unparsed += 1
                    continue
                if market.asset not in chains:
                    unparsed += 1
                    continue
                parsed_markets.append(market)

        rows: list[CryptoWedgeRow] = []
        status_counts: dict[str, int] = {}
        for market in parsed_markets:
            # Each row is stamped with its own read time, not the cycle start:
            # a full live cycle is ~66 CLOB GETs over minutes, and the freshness
            # bound must measure the age of *that* row's reads. For the same
            # reason the option chain is re-read once it is half the bound old,
            # instead of letting one snapshot age out across the cycle.
            row_now = self.clock()
            chains[market.asset] = await self._refresh_chain_if_stale(
                market.asset, chains[market.asset], row_now, chain_errors
            )
            row = await self._observe(
                market,
                chain=chains[market.asset],
                crucix=statuses[market.asset],
                now=row_now,
            )
            await self.tape.append(row)
            rows.append(row)
            status_counts[row.status.value] = status_counts.get(row.status.value, 0) + 1

        return CryptoWedgeCycleReport(
            trading_mode=self.settings.trading_mode,
            kill_switch_engaged=self.kill_switch.engaged,
            kill_switch_sources=self.kill_switch.engaged_sources,
            observed_at=now,
            assets=tuple(asset.value for asset in assets),
            slugs_requested=len(slugs),
            events_missing=events_missing,
            events_error=events_error,
            markets_seen=markets_seen,
            parsed=len(parsed_markets),
            unparsed=unparsed,
            rows_written=len(rows),
            rows_ok=sum(1 for row in rows if row.status is WedgeRowStatus.OK),
            status_counts=status_counts,
            crucix_status=crucix_status,
            chain_errors=chain_errors,
            unknown_assets=unknown,
            rows=rows,
        )

    async def _observe(
        self,
        market: ParsedCryptoThresholdMarket,
        *,
        chain: _Chain,
        crucix: CrucixStatus,
        now: datetime,
    ) -> CryptoWedgeRow:
        reasons: list[str] = []
        book: ClobBook | None = None
        try:
            book = await self._book(market.yes_token_id)
        except Exception as exc:  # noqa: BLE001 - an unreadable book is a skip, not a crash.
            reasons.append(f"clob book unavailable: {type(exc).__name__}")

        mid = book.mid if book is not None else None
        if mid is None and book is not None:
            reasons.append("book is one-sided: no mid")

        implied = None
        if chain.error is not None:
            reasons.append(f"deribit chain unavailable: {chain.error}")
        else:
            implied, skip_reason = implied_digital_probability(
                chain.quotes,
                chain.instruments,
                strike=market.strike_usd,
                resolves_at=market.resolves_at,
                now=now,
                max_expiry_gap_hours=self.settings.polymarket_crypto_max_expiry_gap_hours,
            )
            if skip_reason is not None:
                reasons.append(f"option probability skipped: {skip_reason}")

        bound = self.settings.polymarket_crypto_max_staleness_seconds
        poly_ts = book.venue_timestamp if book is not None else None
        deribit_ts = implied.deribit_observed_at if implied is not None else None
        # Absolute distance, so a venue timestamp implausibly far in the *future*
        # is also refused rather than read as "very fresh".
        poly_stale = poly_ts is None or abs((now - poly_ts).total_seconds()) > bound
        deribit_stale = deribit_ts is None or abs((now - deribit_ts).total_seconds()) > bound

        status = WedgeRowStatus.OK
        if mid is None:
            status = WedgeRowStatus.NO_TWO_SIDED_BOOK
        elif implied is None:
            status = WedgeRowStatus.NO_OPTION_PROBABILITY
        elif poly_stale:
            status = WedgeRowStatus.STALE_POLYMARKET
            reasons.append(f"polymarket book older than {bound:g}s")
        elif deribit_stale:
            status = WedgeRowStatus.STALE_DERIBIT
            reasons.append(f"deribit quote older than {bound:g}s")

        wedge = (
            mid - implied.probability
            if status is WedgeRowStatus.OK and mid is not None and implied is not None
            else None
        )
        return CryptoWedgeRow(
            status=status,
            market_id=market.market_id,
            question=market.question,
            asset=market.asset,
            strike_usd=market.strike_usd,
            resolves_at=market.resolves_at,
            observed_at=now,
            poly_mid=mid,
            poly_best_bid=book.best_bid if book is not None else None,
            poly_best_ask=book.best_ask if book is not None else None,
            poly_book_ts=poly_ts,
            deribit_prob=implied.probability if implied is not None else None,
            model_version=implied.model_version if implied is not None else None,
            expiry_lo=implied.expiry_lo if implied is not None else None,
            expiry_hi=implied.expiry_hi if implied is not None else None,
            expiry_gap_hours=implied.expiry_gap_hours if implied is not None else None,
            deribit_ts=deribit_ts,
            wedge=wedge,
            crucix_adverse=None
            if crucix is CrucixStatus.NOT_CONFIGURED
            else (crucix is CrucixStatus.ADVERSE),
            crucix_status=crucix,
            resolution_text_ok=market.resolution_text_ok,
            reasons=reasons,
        )

    async def _events(self, slug: str) -> tuple[tuple[dict[str, Any], ...], str | None]:
        """Return (events, error). An empty list with no error means the daily
        event does not exist yet; an error means Gamma did not answer. The two
        are counted separately so an outage never reads as "nothing listed"."""

        if self.fixtures is not None:
            rows = self.fixtures.events.get(slug)
            if not isinstance(rows, list):
                return (), None
            return tuple(row for row in rows if isinstance(row, dict)), None
        if self.gamma is None:
            raise RuntimeError("Gamma client is not configured")
        try:
            return await self.gamma.list_events_by_slug(slug=slug), None
        except Exception as exc:  # noqa: BLE001 - an unreachable Gamma is a skip.
            return (), type(exc).__name__

    async def _book(self, token_id: str) -> ClobBook:
        if self.fixtures is not None:
            if token_id not in self.fixtures.books:
                raise KeyError(f"fixture book missing for {token_id}")
            return reduce_book(self.fixtures.books[token_id])
        if self.clob is None:
            raise RuntimeError("CLOB client is not configured")
        return await self.clob.book(token_id)

    async def _refresh_chain_if_stale(
        self,
        asset: CryptoAsset,
        chain: _Chain,
        now: datetime,
        chain_errors: dict[str, str],
    ) -> _Chain:
        """Re-read the option chain once the snapshot is half the bound old.

        A failed refresh keeps the previous snapshot: its quotes then age past
        the freshness bound on their own and the affected rows are recorded as
        ``stale_deribit`` — never silently re-used as if they were fresh.
        """

        if self.fixtures is not None or chain.fetched_at is None:
            return chain
        age = abs((now - chain.fetched_at).total_seconds())
        if age <= self.settings.polymarket_crypto_max_staleness_seconds / 2:
            return chain
        refreshed = await self._chain(asset, now)
        if refreshed.error is not None:
            chain_errors[asset.value] = f"refresh failed: {refreshed.error}"
            return chain
        chain_errors.pop(asset.value, None)
        return refreshed

    async def _chain(self, asset: CryptoAsset, now: datetime) -> _Chain:
        if self.fixtures is not None:
            instruments_raw = self.fixtures.deribit_instruments.get(asset.value)
            summary_raw = self.fixtures.deribit_summary.get(asset.value)
            if instruments_raw is None or summary_raw is None:
                return _Chain(instruments=(), quotes=(), error="fixture chain missing")
            return _Chain(
                instruments=reduce_instruments(instruments_raw, currency=asset.value),
                quotes=reduce_book_summary(summary_raw),
            )
        if self.deribit is None:
            raise RuntimeError("Deribit client is not configured")
        try:
            instruments = await self.deribit.instruments(asset.value)
            quotes = await self.deribit.book_summary(asset.value)
        except Exception as exc:  # noqa: BLE001 - unreachable venue is a skip.
            return _Chain(instruments=(), quotes=(), error=type(exc).__name__)
        return _Chain(instruments=instruments, quotes=quotes, fetched_at=now)

    async def _crucix_status(self, asset: CryptoAsset) -> CrucixStatus:
        snapshot: NewsSnapshot | None
        if self.fixtures is not None:
            if asset.value not in self.fixtures.crucix:
                return CrucixStatus.NOT_CONFIGURED
            try:
                snapshot = parse_crucix_alerts(self.fixtures.crucix[asset.value], asset=asset.value)
            except Exception:  # noqa: BLE001 - an unreadable feed stands aside.
                snapshot = None
            return crucix_status_from_snapshot(snapshot, configured=True)
        if self.crucix is None:
            return CrucixStatus.NOT_CONFIGURED
        try:
            snapshot = await self.crucix.fetch(asset.value)
        except Exception:  # noqa: BLE001 - an unreachable feed stands aside.
            snapshot = None
        return crucix_status_from_snapshot(snapshot, configured=True)
