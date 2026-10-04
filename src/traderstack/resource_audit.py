"""Safe operator resource audit for issue #191.

This command answers a narrower question than traderstack-check-config:
which intended data resources are configured, where local evidence is stored,
and whether collected JSONL evidence is fresh.

Secret values are never rendered. Network probing is opt-in and limited to
read-only public endpoints in this first slice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import SecretStr

from traderstack.config import Settings
from traderstack.market.crucix import crucix_effective_base_url, crucix_should_register
from traderstack.provider_health_journal import (
    DEFAULT_PROVIDER_HEALTH_PATH,
    load_latest_provider_health,
)

ACTIVE = "ACTIVE"
DELIBERATELY_DISABLED = "DELIBERATELY_DISABLED"
BLOCKED_CREDENTIAL = "BLOCKED_CREDENTIAL"
BLOCKED_NETWORK = "BLOCKED_NETWORK"
IMPLEMENTED_NOT_PROVEN = "IMPLEMENTED_NOT_PROVEN"


@dataclass(frozen=True)
class ResourceRow:
    provider: str
    role: str
    status: str
    configured: bool
    credential_source: str
    network: str
    auth: str
    last_success: str
    rows_24h: int
    rows_7d: int
    destination: str
    stale: str
    action: str


def _secret_present(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())


def _dotenv_nonblank_keys(path: Path = Path(".env")) -> set[str]:
    if not path.is_file():
        return set()
    keys: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() and value.strip():
            keys.add(key.strip())
    return keys


def _credential_source(names: Iterable[str], *, dotenv_keys: set[str]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return "env"
    if any(name in dotenv_keys for name in names):
        return ".env"
    return "unset"


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


_TIMESTAMP_KEYS = (
    "observed_at",
    "timestamp",
    "recorded_at",
    "created_at",
    "forecast_issued_at",
    "resolved_at",
    "as_of",
)


def _evidence(path_text: str, *, now: datetime) -> tuple[str, int, int, str]:
    path = Path(path_text)
    if not path.is_file():
        return "never", 0, 0, "yes"

    newest: datetime | None = None
    rows_24h = 0
    rows_7d = 0
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                stamp = None
                if isinstance(payload, dict):
                    for key in _TIMESTAMP_KEYS:
                        stamp = _parse_timestamp(payload.get(key))
                        if stamp is not None:
                            break
                if stamp is None:
                    continue
                newest = max(newest, stamp) if newest is not None else stamp
                if stamp >= cutoff_24h:
                    rows_24h += 1
                if stamp >= cutoff_7d:
                    rows_7d += 1
    except OSError:
        return "unreadable", 0, 0, "unknown"

    if newest is None:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        stale = "yes" if mtime < cutoff_7d else "unknown"
        return mtime.isoformat(), 0, 0, stale

    return newest.isoformat(), rows_24h, rows_7d, "yes" if newest < cutoff_7d else "no"


def _provider_row(
    *,
    provider: str,
    role: str,
    configured: bool,
    action_if_missing: str,
    now: datetime,
    credential_source: str = "not_required",
    destination: str = "runtime feature vector / audit",
    evidence_path: str | None = None,
    deliberately_disabled: bool = False,
) -> ResourceRow:
    last_success = "not_recorded"
    rows_24h = 0
    rows_7d = 0
    stale = "unknown"

    if evidence_path:
        last_success, rows_24h, rows_7d, stale = _evidence(evidence_path, now=now)

    if deliberately_disabled:
        status = DELIBERATELY_DISABLED
        action = action_if_missing
    elif configured:
        status = IMPLEMENTED_NOT_PROVEN
        action = "run collector/probe and prove fresh durable collection"
    else:
        status = (
            BLOCKED_CREDENTIAL if credential_source != "not_required" else DELIBERATELY_DISABLED
        )
        action = action_if_missing

    return ResourceRow(
        provider=provider,
        role=role,
        status=status,
        configured=configured,
        credential_source=credential_source,
        network="not_probed",
        auth="not_probed" if configured else "not_applicable",
        last_success=last_success,
        rows_24h=rows_24h,
        rows_7d=rows_7d,
        destination=evidence_path or destination,
        stale=stale,
        action=action,
    )


def build_rows(settings: Settings, *, now: datetime | None = None) -> list[ResourceRow]:
    now = now or datetime.now(UTC)
    dotenv_keys = _dotenv_nonblank_keys()

    def source(*names: str) -> str:
        return _credential_source(names, dotenv_keys=dotenv_keys)

    crucix_key = None
    if settings.crucix_api_key is not None:
        candidate = settings.crucix_api_key.get_secret_value().strip()
        crucix_key = candidate or None
    crucix_on = crucix_should_register(
        enabled=settings.crucix_enabled,
        base_url=settings.crucix_base_url,
        api_key=crucix_key,
    )

    return [
        _provider_row(
            provider="Dune",
            role="on-chain netflow / accumulation",
            configured=_secret_present(settings.dune_api_key)
            and bool(settings.dune_query_ids.strip()),
            credential_source=source("DUNE_API_KEY", "DUNE_QUERY_IDS"),
            action_if_missing="set DUNE_API_KEY and DUNE_QUERY_IDS; then benchmark under #81",
            now=now,
        ),
        _provider_row(
            provider="LunarCrush",
            role="social / narrative",
            configured=_secret_present(settings.lunarcrush_api_key),
            credential_source=source("LUNARCRUSH_API_KEY"),
            action_if_missing="provision LUNARCRUSH_API_KEY or deliberately retire provider",
            now=now,
        ),
        _provider_row(
            provider="CryptoPanic",
            role="crypto news",
            configured=_secret_present(settings.cryptopanic_api_key),
            credential_source=source("CRYPTOPANIC_API_KEY"),
            action_if_missing="provision CRYPTOPANIC_API_KEY and confirm plan compatibility",
            now=now,
        ),
        _provider_row(
            provider="Perplexity",
            role="news / research snapshot",
            configured=_secret_present(settings.perplexity_api_key),
            credential_source=source("PERPLEXITY_API_KEY"),
            action_if_missing="provision PERPLEXITY_API_KEY or deliberately retire paid source",
            now=now,
        ),
        _provider_row(
            provider="altFINS",
            role="external technical signal",
            configured=_secret_present(settings.altfins_api_key),
            credential_source=source("ALTFINS_API_KEY"),
            action_if_missing="provision ALTFINS_API_KEY or deliberately retire provider",
            now=now,
        ),
        _provider_row(
            provider="Crucix",
            role="world/news context and stand-aside research",
            configured=crucix_on,
            credential_source=source("CRUCIX_API_KEY", "CRUCIX_BASE_URL", "CRUCIX_ENABLED")
            if crucix_on
            else "unset",
            action_if_missing=(
                "set CRUCIX_ENABLED/CRUCIX_BASE_URL as appropriate; "
                "key only if deployment requires it"
            ),
            now=now,
        ),
        _provider_row(
            provider="CoinGecko",
            role="reference price",
            configured=_secret_present(settings.coingecko_api_key),
            credential_source=source("COINGECKO_API_KEY"),
            action_if_missing="provision COINGECKO_API_KEY or confirm fallback policy",
            now=now,
        ),
        _provider_row(
            provider="CoinMarketCap",
            role="secondary reference price",
            configured=_secret_present(settings.coinmarketcap_api_key),
            credential_source=source("COINMARKETCAP_API_KEY"),
            action_if_missing="provision COINMARKETCAP_API_KEY or deliberately disable",
            now=now,
        ),
        _provider_row(
            provider="Coin Metrics",
            role="on-chain regime",
            configured=settings.onchain_regime_gate_enabled,
            action_if_missing="enable only after research justification; public community endpoint",
            deliberately_disabled=not settings.onchain_regime_gate_enabled,
            now=now,
        ),
        _provider_row(
            provider="Polymarket Data API",
            role="public wallet / trade / leaderboard research",
            configured=True,
            action_if_missing="run/schedule traderstack-polymarket-wallet-snapshot",
            now=now,
        ),
        _provider_row(
            provider="Polymarket crypto tape",
            role="Gamma/CLOB + Deribit probability research",
            configured=settings.polymarket_crypto_tape_enabled,
            evidence_path=settings.polymarket_crypto_tape_path,
            action_if_missing="enable/schedule POLYMARKET_CRYPTO_TAPE_ENABLED in paper mode",
            deliberately_disabled=not settings.polymarket_crypto_tape_enabled,
            now=now,
        ),
        _provider_row(
            provider="Polymarket weather tape",
            role="Gamma/CLOB + as-issued NWP observations",
            configured=settings.polymarket_weather_enabled,
            evidence_path=settings.polymarket_weather_tape_path,
            action_if_missing="enable/schedule the weather collector in paper mode",
            deliberately_disabled=not settings.polymarket_weather_enabled,
            now=now,
        ),
        _provider_row(
            provider="Polymarket weather resolutions",
            role="official station outcomes",
            configured=True,
            evidence_path=settings.polymarket_weather_resolved_path,
            action_if_missing="schedule resolver after settlement lag",
            now=now,
        ),
    ]


_PUBLIC_PROBES: dict[str, str] = {
    "Crucix": "/api/data",
    "Coin Metrics": (
        "/v4/timeseries/asset-metrics?assets=btc&metrics=CapMVRVCur&frequency=1d&page_size=1"
    ),
    "Polymarket Data API": "/v2/status",
    "Polymarket crypto tape": "/events?limit=1",
    "Polymarket weather tape": "/events?limit=1",
}


async def _probe_one(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        return BLOCKED_NETWORK, type(exc).__name__
    if 200 <= response.status_code < 400:
        return ACTIVE, f"http_{response.status_code}"
    if response.status_code in {401, 403}:
        return IMPLEMENTED_NOT_PROVEN, f"http_{response.status_code}"
    return BLOCKED_NETWORK, f"http_{response.status_code}"


async def probe_public(rows: list[ResourceRow], settings: Settings) -> list[ResourceRow]:
    bases = {
        "Crucix": crucix_effective_base_url(settings.crucix_base_url),
        "Coin Metrics": settings.coinmetrics_base_url,
        "Polymarket Data API": "https://data-api.polymarket.com",
        "Polymarket crypto tape": settings.polymarket_gamma_base_url,
        "Polymarket weather tape": settings.polymarket_gamma_base_url,
    }
    timeout = min(settings.provider_timeout_seconds, 10.0)
    updated: list[ResourceRow] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for row in rows:
            path = _PUBLIC_PROBES.get(row.provider)
            if path is None or (row.provider == "Crucix" and not row.configured):
                updated.append(row)
                continue
            status, network = await _probe_one(client, bases[row.provider].rstrip("/") + path)
            values = asdict(row)
            values["network"] = network
            values["auth"] = (
                "not_required" if network.startswith(("http_2", "http_3")) else row.auth
            )
            if row.configured or row.provider == "Coin Metrics":
                values["status"] = status
            if status != ACTIVE:
                values["action"] = f"{row.action}; public probe={network}"
            updated.append(ResourceRow(**values))
    return updated


_JOURNAL_PROVIDER_NAMES: dict[str, str] = {
    "Dune": "dune",
    "LunarCrush": "lunarcrush",
    "CryptoPanic": "cryptopanic",
    "Perplexity": "perplexity",
    "altFINS": "altfins",
    "Crucix": "crucix",
    "CoinGecko": "coingecko",
    "CoinMarketCap": "coinmarketcap",
    "Coin Metrics": "coinmetrics",
    "Polymarket Data API": "polymarket_data",
}


def apply_journal_health(
    rows: list[ResourceRow],
    *,
    path: Path = DEFAULT_PROVIDER_HEALTH_PATH,
    now: datetime | None = None,
) -> list[ResourceRow]:
    now = now or datetime.now(UTC)
    latest = load_latest_provider_health(path)
    updated: list[ResourceRow] = []

    for row in rows:
        registry_name = _JOURNAL_PROVIDER_NAMES.get(row.provider)
        event = latest.get(registry_name) if registry_name is not None else None
        if event is None:
            updated.append(row)
            continue

        values = asdict(row)
        if event.last_success_at is not None:
            values["last_success"] = event.last_success_at.isoformat()
            age = now - event.last_success_at.astimezone(UTC)
            values["stale"] = "yes" if age > timedelta(days=7) else "no"

        if event.state == "open":
            values["status"] = BLOCKED_NETWORK
            values["network"] = "breaker_open"
            values["action"] = (
                "provider circuit is open; inspect latest provider error and upstream reachability"
            )
        elif event.last_success_at is not None and (
            now - event.last_success_at.astimezone(UTC)
        ) <= timedelta(days=7):
            values["status"] = ACTIVE
            values["network"] = "recent_success"
            values["auth"] = "validated_by_success"

        updated.append(ResourceRow(**values))
    return updated


def render_table(rows: list[ResourceRow]) -> str:
    headers = (
        "provider",
        "status",
        "configured",
        "credential",
        "network",
        "last_success",
        "24h",
        "7d",
        "stale",
        "destination",
        "action",
    )
    data = [
        (
            row.provider,
            row.status,
            "yes" if row.configured else "no",
            row.credential_source,
            row.network,
            row.last_success,
            str(row.rows_24h),
            str(row.rows_7d),
            row.stale,
            row.destination,
            row.action,
        )
        for row in rows
    ]
    widths = [len(header) for header in headers]
    for record in data:
        for index, value in enumerate(record):
            widths[index] = min(max(widths[index], len(value)), 42)

    def clip(value: str, width: int) -> str:
        return value if len(value) <= width else value[: width - 1] + "…"

    lines = [
        " | ".join(
            clip(header, widths[index]).ljust(widths[index]) for index, header in enumerate(headers)
        ),
        "-+-".join("-" * width for width in widths),
    ]
    for record in data:
        lines.append(
            " | ".join(
                clip(value, widths[index]).ljust(widths[index])
                for index, value in enumerate(record)
            )
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit intended data resources without printing credential values."
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--probe-public",
        action="store_true",
        help="perform read-only probes for public endpoints only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    rows = apply_journal_health(build_rows(settings))
    if args.probe_public:
        rows = asyncio.run(probe_public(rows, settings))
    if args.json:
        print(json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True))
    else:
        print(render_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
