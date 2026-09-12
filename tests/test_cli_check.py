import pytest

from traderstack.cli_check import build_report, main, render_report
from traderstack.config import Settings


def settings(**overrides):
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def test_default_paper_settings_are_safe() -> None:
    report = build_report(settings())
    assert report.safe
    assert report.warnings == []


def test_live_trading_mode_is_unsafe() -> None:
    report = build_report(settings(trading_mode="live"))
    assert not report.safe
    assert any("TRADING_MODE" in w for w in report.warnings)


def test_shadow_trading_mode_is_reported_as_record_only() -> None:
    # Isolate the shadow-live axis: default PAPER_RESEARCH_MODE=true is
    # paper-only and would otherwise warn that the flag is ignored.
    report = build_report(settings(trading_mode="shadow", paper_research_mode=False))
    assert report.safe
    effect = next(item for item in report.items if "shadow-live" in item.label)
    assert effect.value == "record only"
    assert "no Hummingbot submit" in effect.detail


def test_kill_switch_disengaged_outside_development_is_unsafe() -> None:
    report = build_report(settings(kill_switch=False, app_env="production"))
    assert not report.safe
    assert any("KILL_SWITCH=false" in w for w in report.warnings)


def test_kill_switch_disengaged_in_development_is_safe() -> None:
    report = build_report(settings(kill_switch=False, app_env="development"))
    assert report.safe


def test_robinhood_chain_feed_without_config_is_unsafe() -> None:
    report = build_report(settings(venue_feed="robinhood_chain"))
    assert not report.safe
    assert any("robinhood_chain" in w for w in report.warnings)


def test_kraken_rest_feed_is_safe_in_paper() -> None:
    report = build_report(settings(venue_feed="kraken_rest"))
    assert report.safe
    rest = next(item for item in report.items if "kraken REST" in item.label)
    assert "paper-only" in rest.value


def test_kraken_rest_feed_with_non_paper_mode_is_unsafe() -> None:
    report = build_report(settings(venue_feed="kraken_rest", trading_mode="live"))
    assert not report.safe
    assert any("kraken_rest" in w and "paper-only" in w for w in report.warnings)


def test_robinhood_chain_feed_fully_configured_is_safe_on_that_axis() -> None:
    report = build_report(
        settings(
            venue_feed="robinhood_chain",
            robinhood_chain_rpc_url="https://example.invalid",
            robinhood_chain_id=4663,
            robinhood_chain_ws_url="wss://example.invalid",
            robinhood_chain_pools="ETH/USDG:v3:0xPOOL:18:6:token0:5",
        )
    )
    assert not any("robinhood_chain" in w for w in report.warnings)


def test_paper_research_mode_is_active_on_default_paper_settings() -> None:
    report = build_report(settings())
    item = next(i for i in report.items if i.label == "Paper research mode")
    assert item.value == "active"
    assert "min agreeing strategies=1" in item.detail
    assert report.safe


def test_paper_research_mode_off_is_reported() -> None:
    report = build_report(settings(paper_research_mode=False))
    item = next(i for i in report.items if i.label == "Paper research mode")
    assert item.value == "off"
    assert report.safe


def test_paper_research_mode_ignored_on_live_is_unsafe() -> None:
    report = build_report(settings(trading_mode="live", paper_research_mode=True))
    item = next(i for i in report.items if i.label == "Paper research mode")
    assert item.value == "ignored"
    assert any("PAPER_RESEARCH_MODE" in w for w in report.warnings)


def test_paper_reference_resilience_and_pretrade_thresholds_are_active_on_paper() -> None:
    report = build_report(settings())
    resilience = next(i for i in report.items if i.label == "Paper reference resilience")
    thresholds = next(i for i in report.items if i.label == "Paper pretrade thresholds")
    assert resilience.value == "active"
    assert "last-good" in resilience.detail
    assert thresholds.value == "active"
    assert "min total return=-0.15" in thresholds.detail
    assert report.safe


def test_paper_reference_resilience_ignored_on_live() -> None:
    report = build_report(settings(trading_mode="live"))
    resilience = next(i for i in report.items if i.label == "Paper reference resilience")
    thresholds = next(i for i in report.items if i.label == "Paper pretrade thresholds")
    assert resilience.value == "ignored"
    assert thresholds.value == "ignored"


def test_paper_research_keeps_two_voters_when_intel_configured() -> None:
    report = build_report(settings(lunarcrush_api_key="secret-key"))
    item = next(i for i in report.items if i.label == "Paper research mode")
    assert item.value == "active"
    assert "min agreeing strategies=2" in item.detail


def test_promote_searched_strategies_default_is_safe() -> None:
    report = build_report(settings())
    assert report.safe
    item = next(i for i in report.items if "Promote searched strategies" in i.label)
    assert item.value == "no"


def test_intraday_dual_print_is_report_only() -> None:
    report = build_report(settings())
    item = next(i for i in report.items if i.label == "Intraday (4h/1h) dual-print search")
    assert item.value == "report-only"
    assert "traderstack-intraday-dual-print" in item.detail
    assert "PAPER_PROMOTE_*" in item.detail


def test_funding_carry_is_report_only() -> None:
    report = build_report(settings())
    item = next(i for i in report.items if i.label == "Funding / carry search")
    assert item.value == "report-only"
    assert "traderstack-funding-carry" in item.detail
    assert "PAPER_PROMOTE_*" in item.detail
    assert "single-print cannot promote" in item.detail


def test_promote_without_report_is_unsafe() -> None:
    report = build_report(
        settings(
            paper_promote_searched_strategies=True,
            paper_search_report_path="var/ops/does-not-exist.json",
        )
    )
    assert not report.safe
    assert any("PAPER_PROMOTE_SEARCHED_STRATEGIES" in w for w in report.warnings)


def test_paper_garch_size_default_is_off_and_safe() -> None:
    report = build_report(settings())
    assert report.safe
    item = next(i for i in report.items if i.label == "Paper GARCH size overlay")
    assert item.value == "off"


def test_paper_garch_size_on_warns_until_a_winner_exists() -> None:
    report = build_report(settings(paper_garch_size=True))
    assert not report.safe
    assert any("PAPER_GARCH_SIZE" in warning for warning in report.warnings)


def test_promote_ema_9_21_default_is_off_and_safe() -> None:
    report = build_report(settings())
    assert report.safe
    item = next(i for i in report.items if i.label == "Promote ema_9_21 as paper voter")
    assert item.value == "no"


def test_promote_universe_default_is_documented_and_unused() -> None:
    report = build_report(settings())
    assert report.safe
    item = next(i for i in report.items if i.label == "Paper promote universe")
    assert item.value == "BTC/USD, ETH/USD"
    assert "used only when a daily paper pin is on" in item.detail


def test_promote_ema_9_21_on_paper_is_safe() -> None:
    report = build_report(settings(paper_promote_ema_9_21=True, pretrade_candle_interval="1h"))
    assert report.safe
    item = next(i for i in report.items if i.label == "Promote ema_9_21 as paper voter")
    assert item.value == "active"
    assert "ema_9_21" in item.detail
    assert "forced 1d" in item.detail
    candles = next(i for i in report.items if i.label == "Paper candle interval (promote ema_9_21)")
    assert candles.value == "1d"
    assert "PRETRADE_CANDLE_INTERVAL=1h is not used" in candles.detail
    drawdown = next(i for i in report.items if i.label == "Paper promote ema_9_21 max drawdown")
    assert drawdown.value == "30.00%"
    assert "PRETRADE_MAX_DRAWDOWN_PCT=15.00%" in drawdown.detail
    assert "walk-forward maxDD" in drawdown.detail
    count = next(i for i in report.items if i.label == "Paper promote candle count")
    assert count.value == "720"
    assert "PRETRADE_CANDLE_COUNT=400" in count.detail
    universe = next(i for i in report.items if i.label == "Paper promote universe")
    assert universe.value == "BTC/USD, ETH/USD"
    assert "promote_universe_excluded" in universe.detail


def test_promote_ema_9_21_tight_drawdown_ceiling_warns() -> None:
    report = build_report(
        settings(
            paper_promote_ema_9_21=True,
            paper_promote_ema_9_21_max_drawdown_pct=0.15,
        )
    )
    assert not report.safe
    assert any("MAX_DRAWDOWN_PCT is tighter" in warning for warning in report.warnings)


def test_promote_ema_9_21_raised_drawdown_ceiling_warns() -> None:
    report = build_report(
        settings(
            paper_promote_ema_9_21=True,
            paper_promote_ema_9_21_max_drawdown_pct=0.50,
        )
    )
    assert not report.safe
    assert any("above the documented 0.30" in warning for warning in report.warnings)
    assert any("full-history" in warning for warning in report.warnings)


def test_promote_ema_9_21_ignored_outside_paper() -> None:
    report = build_report(settings(trading_mode="shadow", paper_promote_ema_9_21=True))
    assert not report.safe
    item = next(i for i in report.items if i.label == "Promote ema_9_21 as paper voter")
    assert item.value == "ignored"
    assert any("PAPER_PROMOTE_EMA_9_21" in warning for warning in report.warnings)


def test_promote_ema_9_21_adx15_default_is_off() -> None:
    report = build_report(settings())
    item = next(i for i in report.items if i.label == "Promote ema_9_21_adx15 as paper voter")
    assert item.value == "no"


def test_promote_ema_9_21_adx15_on_paper_is_safe() -> None:
    report = build_report(
        settings(paper_promote_ema_9_21_adx15=True, pretrade_candle_interval="1h")
    )
    assert report.safe
    item = next(i for i in report.items if i.label == "Promote ema_9_21_adx15 as paper voter")
    assert item.value == "active"
    assert "ema_9_21_adx15" in item.detail
    drawdown = next(i for i in report.items if i.label == "Paper promote ema_9_21 max drawdown")
    assert drawdown.value == "30.00%"
    assert "PRETRADE_MAX_DRAWDOWN_PCT=15.00%" in drawdown.detail


def test_promote_ema_9_21_adx15_ignored_outside_paper() -> None:
    report = build_report(settings(trading_mode="shadow", paper_promote_ema_9_21_adx15=True))
    assert not report.safe
    assert any("PAPER_PROMOTE_EMA_9_21_ADX15" in warning for warning in report.warnings)


def test_promote_ema_9_21_wins_over_adx15() -> None:
    report = build_report(settings(paper_promote_ema_9_21=True, paper_promote_ema_9_21_adx15=True))
    assert not report.safe
    assert any("EMA_9_21_ADX15" in warning for warning in report.warnings)
    older = next(i for i in report.items if i.label == "Promote ema_9_21 as paper voter")
    newer = next(i for i in report.items if i.label == "Promote ema_9_21_adx15 as paper voter")
    assert older.value == "active"
    assert newer.value == "ignored"


def test_promote_ema_9_21_and_searched_together_warns() -> None:
    report = build_report(
        settings(
            paper_promote_ema_9_21=True,
            paper_promote_searched_strategies=True,
            paper_search_report_path="var/ops/does-not-exist.json",
        )
    )
    assert not report.safe
    assert any("takes precedence" in warning for warning in report.warnings)


def test_pretrade_gate_disabled_warns() -> None:
    report = build_report(settings(pretrade_backtest_enabled=False))
    assert not report.safe
    assert any("PRETRADE_BACKTEST_ENABLED" in w for w in report.warnings)


def test_intelligence_required_without_provider_warns() -> None:
    report = build_report(settings(intelligence_required=True))
    assert not report.safe
    assert any("INTELLIGENCE_REQUIRED" in w for w in report.warnings)


def test_intelligence_required_with_provider_is_safe() -> None:
    report = build_report(settings(intelligence_required=True, lunarcrush_api_key="secret-key"))
    assert not any("INTELLIGENCE_REQUIRED" in w for w in report.warnings)


def test_intelligence_required_with_crucix_enabled_is_safe() -> None:
    report = build_report(settings(intelligence_required=True, crucix_enabled=True))
    assert not any("INTELLIGENCE_REQUIRED" in w for w in report.warnings)
    crucix = next(item for item in report.items if "Crucix" in item.label)
    assert crucix.value == "yes"


def test_intelligence_required_with_blank_key_is_treated_as_missing() -> None:
    report = build_report(settings(intelligence_required=True, lunarcrush_api_key=""))
    assert not report.safe
    assert any("INTELLIGENCE_REQUIRED" in w for w in report.warnings)
    lunar = next(item for item in report.items if "LunarCrush" in item.label)
    assert lunar.value == "no"


def test_dune_key_without_query_ids_is_reported_but_not_usable() -> None:
    report = build_report(settings(dune_api_key="secret-key", dune_query_ids=""))
    dune_item = next(item for item in report.items if "Dune" in item.label)
    assert dune_item.value == "no"
    assert "DUNE_QUERY_IDS" in dune_item.detail


def test_secret_values_never_appear_in_rendered_output() -> None:
    secret = "super-secret-value-should-not-leak"
    report = build_report(
        settings(
            dune_api_key=secret,
            dune_query_ids="BTC:1",
            lunarcrush_api_key=secret,
            cryptopanic_api_key=secret,
            perplexity_api_key=secret,
            coingecko_api_key=secret,
            coinmarketcap_api_key=secret,
            hummingbot_api_username="operator",
            hummingbot_api_password=secret,
        )
    )
    rendered = render_report(report, app_env="development")
    assert secret not in rendered
    for item in report.items:
        assert secret not in item.value
        assert secret not in item.detail


def test_hummingbot_credentials_enable_execution_submit() -> None:
    without = build_report(settings())
    with_creds = build_report(
        settings(hummingbot_api_username="operator", hummingbot_api_password="secret")
    )
    without_item = next(i for i in without.items if "Execution submit" in i.label)
    with_item = next(i for i in with_creds.items if "Execution submit" in i.label)
    assert without_item.value == "no"
    assert with_item.value == "yes"


def test_render_report_includes_summary_line() -> None:
    report = build_report(settings())
    rendered = render_report(report, app_env="development")
    assert "No unsafe combinations found." in rendered


def test_main_exits_non_zero_on_unsafe_combination(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("TRADING_MODE", "live")
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "unsafe combination" in out


def test_meta_agent_veto_without_anthropic_key_is_unsafe() -> None:
    report = build_report(settings(meta_agent_mode="veto"))
    assert not report.safe
    assert any("META_AGENT_MODE=veto" in w for w in report.warnings)


def test_meta_agent_veto_with_anthropic_key_is_safe_on_that_axis() -> None:
    report = build_report(settings(meta_agent_mode="veto", anthropic_api_key="secret-key"))
    assert not any("META_AGENT_MODE=veto" in w for w in report.warnings)


def test_meta_agent_off_reports_mode_without_extra_detail() -> None:
    report = build_report(settings(meta_agent_mode="off"))
    assert report.safe
    mode_item = next(item for item in report.items if item.label == "Meta-agent mode")
    assert mode_item.value == "off"
    assert not any("model" in item.label for item in report.items)


def test_edge_feeds_are_reported_and_default_off() -> None:
    report = build_report(settings())
    liq = next(i for i in report.items if "liquidations" in i.label)
    ticker = next(i for i in report.items if "bookTicker" in i.label)
    assert liq.value == "no"
    assert ticker.value == "no"


def test_edge_feeds_enabled_in_non_paper_mode_warns_as_not_an_execution_venue() -> None:
    report = build_report(
        settings(trading_mode="live", binance_liq_enabled=True, book_ticker_enabled=True)
    )
    assert not report.safe
    assert any("paper-research" in w or "order routing" in w for w in report.warnings)


def test_crucix_is_off_by_default_in_check_config() -> None:
    report = build_report(settings())
    crucix = next(item for item in report.items if item.label.startswith("  Crucix"))
    assert crucix.value == "no"
    outage = next(item for item in report.items if "Crucix outage" in item.label)
    assert outage.value == "no"
    assert "unused unless" in outage.detail


def test_crucix_outage_fail_closed_is_reported_when_opted_in() -> None:
    report = build_report(settings(crucix_enabled=True))
    crucix = next(item for item in report.items if item.label.startswith("  Crucix"))
    assert crucix.value == "yes"
    outage = next(item for item in report.items if "Crucix outage" in item.label)
    assert outage.value == "yes"
    assert "intelligence_provider_unavailable" in outage.detail
    assert "paper/shadow/live" in outage.detail


def test_altfins_is_reported_as_an_intelligence_provider() -> None:
    without = build_report(settings())
    with_key = build_report(settings(altfins_api_key="secret-key"))
    without_item = next(i for i in without.items if "altFINS" in i.label)
    with_item = next(i for i in with_key.items if "altFINS" in i.label)
    assert without_item.value == "no"
    assert with_item.value == "yes"


def test_report_covers_provider_quotas_execution_and_kill_switch_channels() -> None:
    report = build_report(settings())
    labels = {item.label.strip() for item in report.items}
    assert "Reconcile interval (s)" in labels
    assert "Max NAV drift (bps)" in labels
    assert any("CoinGecko quota" in label for label in labels)
    assert any("sentinel file path" in label for label in labels)
    assert "Paper fee (bps)" in labels
    assert "Paper simulate fills" in labels
    simulate = next(item for item in report.items if item.label == "Paper simulate fills")
    assert simulate.value == "active"


def test_paper_slippage_above_execution_cap_warns() -> None:
    report = build_report(settings(paper_simulate_fills=True, paper_slippage_bps=80.0))
    assert not report.safe
    assert any(
        "PAPER_SLIPPAGE_BPS exceeds EXECUTION_MAX_SLIPPAGE_BPS" in w for w in report.warnings
    )


def test_position_exits_are_reported_on_default_paper_settings() -> None:
    report = build_report(settings())
    item = next(i for i in report.items if i.label == "Position exits")
    assert item.value == "active"
    assert "stop 2.00%" in item.detail
    assert "time 24 bars" in item.detail
    assert report.safe


def test_position_exits_ignored_on_live_warn() -> None:
    report = build_report(settings(trading_mode="live", paper_research_mode=False))
    item = next(i for i in report.items if i.label == "Position exits")
    assert item.value == "ignored"
    assert any("EXIT_*" in warning for warning in report.warnings)


def test_position_exits_disabled_when_all_rules_are_zero() -> None:
    report = build_report(
        settings(
            exit_stop_loss_pct=0.0,
            exit_take_profit_pct=0.0,
            exit_trailing_stop_pct=0.0,
            exit_time_stop_bars=0,
            exit_on_thesis_invalidation=False,
        )
    )
    item = next(i for i in report.items if i.label == "Position exits")
    assert item.value == "disabled"
    assert report.safe


def test_paper_fee_bps_zero_warns() -> None:
    report = build_report(settings(paper_fee_bps=0))
    assert not report.safe
    assert any("PAPER_FEE_BPS=0" in warning for warning in report.warnings)


def test_main_exits_zero_on_safe_defaults(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
