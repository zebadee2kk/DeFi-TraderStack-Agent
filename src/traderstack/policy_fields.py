"""Which `Settings` fields are *not* risk policy, and why (#69 / SEC-2026-09-18).

`risk.py` declares what policy *is* (`RISK_LIMIT_FIELDS` for what
`RiskEngine.evaluate` enforces, `CONTROL_PLANE_FIELDS` for the deterministic
gates enforced around it). This module declares the complement: every remaining
`Settings` field, explicitly judged non-policy, with the reason grouped above
each block.

Why an exclude-list rather than an include-list, even a regex over field names:
an include-list reproduces SEC-2026-09-18 one layer up. A future gate whose name
does not match the pattern is silently left out of the digest — a false
negative, and exactly the failure the finding describes. An exclude-list can
only fail the other way: a genuinely non-policy field nobody classified gets
versioned too, which is harmless noise. Default-deny beats default-allow for a
completeness guarantee.

`tests/security/test_policy_version_covers_every_setting.py` fails if any
`Settings` field appears in none of the three tuples, so a new field cannot be
added without someone deciding which of them it belongs to.

This list lives outside `risk.py` on purpose: it is a census of the whole
settings surface, not risk logic, and `risk.py` is one of the files
`tests/security/test_polymarket_paper_only.py` holds to strict isolation from
the separate Polymarket paper strategy.
"""

from __future__ import annotations

NON_POLICY_FIELDS: tuple[str, ...] = (
    # Evidence-only diagnostics. `opportunity_diagnostic_mode` can only
    # withhold a fill, never authorise one, and
    # tests/security/test_diagnostic_mode_cannot_relax_controls.py pins that it
    # is not a risk limit and leaves the digest unmoved. Kept non-policy to
    # honour that deliberate decision rather than reverse it as a side effect
    # of this change.
    "opportunity_diagnostic_mode",
    # Credentials and identities. Secret material, never a limit.
    "altfins_api_key",
    "anthropic_api_key",
    "coingecko_api_key",
    "coinmarketcap_api_key",
    "crucix_api_key",
    "cryptopanic_api_key",
    "dune_api_key",
    "hummingbot_api_password",
    "hummingbot_api_username",
    "lunarcrush_api_key",
    "perplexity_api_key",
    "polymarket_weather_noaa_user_agent",
    # Endpoints. Where a service lives, not what it is allowed to do.
    "binance_liq_url",
    "book_ticker_url",
    "crucix_base_url",
    "database_url",
    "hummingbot_account_name",
    "hummingbot_api_url",
    "hummingbot_connector_name",
    "polymarket_clob_base_url",
    "polymarket_gamma_base_url",
    "polymarket_weather_noaa_base_url",
    "polymarket_weather_open_meteo_base_url",
    "redis_url",
    "robinhood_chain_connector_name",
    "robinhood_chain_explorer_url",
    "robinhood_chain_native_currency",
    "robinhood_chain_rpc_url",
    "robinhood_chain_ws_url",
    "venue_feed",
    # On-disk locations. Where output is written; changes no decision.
    "paper_search_report_path",
    "polymarket_weather_ledger_path",
    "research_kraken_archive_path",
    "risk_audit_path",
    # Provider budgets, caches, timeouts and reconnect policy. These shape cost
    # and liveness, and a breach fails closed through the provider registry
    # rather than by authorising anything.
    "binance_liq_max_age_seconds",
    "binance_liq_stale_after_seconds",
    "book_ticker_max_age_seconds",
    "book_ticker_stale_after_seconds",
    "candle_provider_calls_per_minute",
    "coingecko_calls_per_day",
    "coingecko_calls_per_minute",
    "coinmarketcap_calls_per_day",
    "coinmarketcap_calls_per_minute",
    "edge_backoff_base_seconds",
    "edge_backoff_max_seconds",
    "edge_max_reconnect_attempts",
    "intelligence_cache_seconds",
    "intelligence_provider_calls_per_minute",
    "kraken_backoff_base_seconds",
    "kraken_backoff_max_seconds",
    "kraken_max_reconnect_attempts",
    "kraken_rest_poll_seconds",
    "kraken_stale_after_seconds",
    "meta_agent_cache_seconds",
    "meta_agent_max_calls_per_day",
    "meta_agent_timeout_seconds",
    "paper_reference_cache_seconds",
    "paper_reference_last_good_seconds",
    "polymarket_weather_cache_seconds",
    "polymarket_weather_calls_per_minute",
    "provider_breaker_cooldown_seconds",
    "provider_failure_threshold",
    "provider_timeout_seconds",
    "reference_price_cache_seconds",
    # Research promotion and search bars. Deliberately NOT policy: they gate
    # which strategy the paper path may run, and
    # test_promotion_settings_do_not_move_risk_policy_version pins that a
    # promotion flag must not move the risk digest.
    "paper_fee_bps",
    "paper_perp_hedge",
    "paper_pretrade_min_excess_return",
    "paper_pretrade_min_sharpe",
    "paper_pretrade_min_total_return",
    "paper_pretrade_min_trades",
    "paper_pretrade_min_walkforward_excess_return",
    "paper_promote_ema_9_21",
    "paper_promote_ema_9_21_adx15",
    "paper_promote_ema_9_21_max_drawdown_pct",
    "paper_promote_searched_strategies",
    "paper_promote_searched_strategy_id",
    "paper_promote_universe",
    "paper_research_mode",
    "paper_search_min_trades",
    "paper_search_min_wf_excess_return",
    "paper_search_min_wf_total_return",
    "paper_search_require_holdout",
    "paper_search_require_wf_total_return",
    "paper_starting_nav_usd",
    # Polymarket weather research. A separate paper strategy with its own
    # ledger; it never reaches RiskEngine.evaluate.
    "polymarket_weather_cities",
    "polymarket_weather_enabled",
    "polymarket_weather_fee_haircut",
    "polymarket_weather_forecast_provider",
    "polymarket_weather_max_markets",
    "polymarket_weather_max_mid",
    "polymarket_weather_min_edge",
    "polymarket_weather_min_mid",
    "polymarket_weather_paper_notional_usd",
    "polymarket_weather_sigma_f",
    "polymarket_weather_tag_slug",
    # Market-data plumbing: which optional feeds are attached and how deep.
    # Availability, not authority.
    "binance_liq_baseline_seconds",
    "binance_liq_count_cap",
    "binance_liq_enabled",
    "binance_liq_window_seconds",
    "book_ticker_enabled",
    "book_ticker_quote",
    "book_ticker_venue",
    "crucix_enabled",
    "cryptopanic_api_plan",
    "dune_query_ids",
    "kraken_book_depth",
    "kraken_book_enabled",
    # Chain topology and observability labels.
    "app_env",
    "log_level",
    "risk_policy_label",
    "robinhood_chain_id",
    "robinhood_chain_pools",
    "robinhood_chain_v4_pool_manager",
    # Everything else deliberately reviewed and judged non-policy.
    "meta_agent_input_cost_per_mtok",
    "meta_agent_max_tokens",
    "meta_agent_max_tokens_per_day",
    "meta_agent_model",
    "meta_agent_output_cost_per_mtok",
)
