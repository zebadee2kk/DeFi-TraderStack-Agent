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


def test_non_paper_trading_mode_is_unsafe() -> None:
    report = build_report(settings(trading_mode="live"))
    assert not report.safe
    assert any("TRADING_MODE" in w for w in report.warnings)


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


def test_main_exits_zero_on_safe_defaults(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
