"""Parity between `Settings` and `.env.example`.

The two are hand-maintained in separate files and drift silently when a
workstream adds a `Settings` field but forgets the `.env.example` line (or
vice versa). This test is the guard rail: every `Settings` field must have a
documented line, and every `.env.example` key must be an actual field --
except the handful of keys consumed only by docker-compose services (never
read by `Settings` itself), which are named explicitly below.
"""

from pathlib import Path

from traderstack.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# Consumed directly by docker-compose.yml (Postgres/Hummingbot service
# containers), never read through `Settings`. Documented in .env.example
# comments alongside DATABASE_URL / HUMMINGBOT_* as such.
DOCKER_ONLY_ENV_KEYS = {
    "postgres_password",
    "hummingbot_config_password",
    "hummingbot_db_password",
}


def _env_example_keys() -> set[str]:
    keys: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        keys.add(key.lower())
    return keys


def test_every_settings_field_has_an_env_example_line() -> None:
    fields = set(Settings.model_fields.keys())
    env_keys = _env_example_keys()
    missing = sorted(fields - env_keys)
    assert not missing, (
        f"Settings field(s) with no .env.example line: {missing}. "
        "Add a documented ENV_VAR_NAME=... line for each."
    )


def test_every_env_example_key_is_a_settings_field_or_a_known_docker_only_key() -> None:
    fields = set(Settings.model_fields.keys())
    env_keys = _env_example_keys()
    orphaned = sorted(env_keys - fields - DOCKER_ONLY_ENV_KEYS)
    assert not orphaned, (
        f".env.example key(s) with no matching Settings field: {orphaned}. "
        "Either add the Settings field, remove the stale line, or add the key to "
        "DOCKER_ONLY_ENV_KEYS in this test with a note on which service reads it."
    )
