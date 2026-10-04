from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from traderstack.config import Settings


def _module():
    path = Path(__file__).resolve().parents[1] / "ops" / "run-with-host-published-services.py"
    spec = importlib.util.spec_from_file_location("host_published_runner", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _module()


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://u:p@postgres:5432/traderstack",
        "redis_url": "redis://redis:6379/0",
    }
    values.update(overrides)
    return Settings(**values)


def test_host_published_urls_translate_compose_dns_only() -> None:
    database_url, redis_url = runner.host_published_urls(settings())
    assert database_url == "postgresql+asyncpg://u:p@127.0.0.1:5432/traderstack"
    assert redis_url == "redis://127.0.0.1:6379/0"


def test_host_published_urls_leave_existing_host_urls_unchanged() -> None:
    cfg = settings(
        database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/traderstack",
        redis_url="redis://127.0.0.1:6379/0",
    )
    database_url, redis_url = runner.host_published_urls(cfg)
    assert database_url == cfg.database_url
    assert redis_url == cfg.redis_url
