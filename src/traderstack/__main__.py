import time

import structlog

from traderstack.config import Settings


def main() -> None:
    settings = Settings()
    log = structlog.get_logger()
    log.info(
        "traderstack_started",
        environment=settings.app_env,
        trading_mode=settings.trading_mode,
        assets=settings.assets,
        kill_switch=settings.kill_switch,
    )
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
