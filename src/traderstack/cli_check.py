"""Operator-facing configuration check.

`traderstack-check-config` loads `Settings` the same way the runtime does,
prints a table of which features/providers are enabled, and warns (exiting
non-zero) on combinations that are unsafe for an operator to run unreviewed.

Secret *values* (API keys, passwords) are never printed — only whether a
secret is present, so the output is safe to paste into chat, a ticket, or CI
logs.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from pydantic import SecretStr

from traderstack.config import Settings

# Environment variables consumed directly (not via `Settings`) but still worth
# reporting on. Values are never read here, only presence in the process
# environment — this module must not import anything that would populate them
# into a printable object.
_ANTHROPIC_ENV = "ANTHROPIC_API_KEY"
_ALTFINS_ENV = "ALTFINS_API_KEY"


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


def _env_present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def build_report(settings: Settings) -> ConfigReport:
    items: list[CheckItem] = []
    warnings: list[str] = []

    # --- Trading mode & kill switch -------------------------------------------------
    items.append(CheckItem("Trading mode", settings.trading_mode))
    if settings.trading_mode != "paper":
        warnings.append(
            f"TRADING_MODE={settings.trading_mode!r}: MVP scope is paper trading only. "
            "shadow/live modes require explicit governance sign-off before use "
            "(see docs/MVP-BACKLOG.md, docs/SECURITY-THREAT-MODEL.md)."
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

    # --- Intelligence providers --------------------------------------------------------
    intelligence_providers = (
        ("Dune (on-chain)", settings.dune_api_key, bool(settings.dune_query_ids.strip())),
        ("LunarCrush (social)", settings.lunarcrush_api_key, True),
        ("CryptoPanic (news)", settings.cryptopanic_api_key, True),
        ("Perplexity (news)", settings.perplexity_api_key, True),
    )
    any_intelligence = False
    for label, key, extra_ok in intelligence_providers:
        present = _has_secret(key) and extra_ok
        any_intelligence = any_intelligence or present
        detail = ""
        if _has_secret(key) and not extra_ok:
            detail = "key set but DUNE_QUERY_IDS is empty — provider will not be used"
        items.append(CheckItem(f"  {label}", _flag(present), detail))

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

    # --- Providers not yet wired into Settings (informational only) --------------------
    items.append(
        CheckItem(
            "Claude meta-agent (ANTHROPIC_API_KEY)",
            _flag(_env_present(_ANTHROPIC_ENV)),
            "present in environment; not yet wired into the continuous runtime (Epic 6)",
        )
    )
    items.append(
        CheckItem(
            "altFINS (ALTFINS_API_KEY)",
            _flag(_env_present(_ALTFINS_ENV)),
            "present in environment; no adapter wired yet",
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

    # --- Risk policy limits (values only, no secrets) -----------------------------------
    items.append(CheckItem("Assets allowlisted", ", ".join(settings.assets) or "(none)"))
    items.append(CheckItem("Max position % of NAV", f"{settings.max_position_pct:.2%}"))
    items.append(CheckItem("Max daily loss % of NAV", f"{settings.max_daily_loss_pct:.2%}"))
    items.append(CheckItem("Max account drawdown %", f"{settings.max_account_drawdown_pct:.2%}"))

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
