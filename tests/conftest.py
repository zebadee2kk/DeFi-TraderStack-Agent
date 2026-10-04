from traderstack.config import Settings


def pytest_sessionstart(session: object) -> None:
    """Keep repository tests deterministic on configured operator hosts.

    Production Settings still loads .env normally. Tests may opt into an env file
    explicitly via Settings(_env_file=...).
    """
    Settings.model_config["env_file"] = None
