from traderstack.config import Settings
from traderstack.logging_config import configure_logging, redact_secrets


def test_redact_secrets_masks_top_level_secret_like_keys() -> None:
    event = redact_secrets(
        None,
        "info",
        {
            "event": "provider_call",
            "api_key": "sk-super-secret",
            "auth_token": "abc123",
            "password": "hunter2",
            "hummingbot_api_password": "hunter2",
            "secret_value": "shh",
            "symbol": "BTC/USD",
        },
    )

    assert event["api_key"] == "***REDACTED***"
    assert event["auth_token"] == "***REDACTED***"
    assert event["password"] == "***REDACTED***"
    assert event["hummingbot_api_password"] == "***REDACTED***"
    assert event["secret_value"] == "***REDACTED***"
    assert event["symbol"] == "BTC/USD"
    assert event["event"] == "provider_call"


def test_redact_secrets_masks_nested_dict_values() -> None:
    event = redact_secrets(
        None,
        "info",
        {"settings": {"database_url": "postgres://x", "COINGECKO_API_KEY": "topsecret"}},
    )

    assert event["settings"]["COINGECKO_API_KEY"] == "***REDACTED***"
    assert event["settings"]["database_url"] == "postgres://x"


def test_redact_secrets_masks_values_in_lists() -> None:
    event = redact_secrets(
        None,
        "info",
        {"headers": [{"x-api-key": "topsecret"}, {"symbol": "ETH/USD"}]},
    )

    assert event["headers"][0]["x-api-key"] == "***REDACTED***"
    assert event["headers"][1]["symbol"] == "ETH/USD"


def test_redact_secrets_leaves_non_secret_events_untouched() -> None:
    event = redact_secrets(None, "info", {"symbol": "BTC/USD", "outcome": "accepted"})

    assert event == {"symbol": "BTC/USD", "outcome": "accepted"}


def test_configure_logging_does_not_raise_for_development_or_production() -> None:
    configure_logging(Settings(app_env="development"))
    configure_logging(Settings(app_env="production"))
