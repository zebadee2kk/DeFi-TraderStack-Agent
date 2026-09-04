import os
import signal

import pytest

from traderstack import killswitch
from traderstack.config import Settings
from traderstack.killswitch import (
    DEFAULT_KILL_SWITCH_FILE,
    KillSwitch,
    install_signal_handler,
    kill_main,
    resume_main,
)


@pytest.fixture(autouse=True)
def clear_signal_latch():
    killswitch._reset_signal_latch_for_tests()
    yield
    killswitch._reset_signal_latch_for_tests()


class FakeRedis:
    """Minimal stand-in for redis.asyncio.Redis: one key, optional failure."""

    def __init__(self, value: object = None, *, fail: bool = False) -> None:
        self.value = value
        self.fail = fail
        self.reads: list[str] = []

    async def get(self, key: str) -> object:
        self.reads.append(key)
        if self.fail:
            raise ConnectionError("redis unreachable")
        return self.value


# --- channels -------------------------------------------------------------


def test_clear_when_no_channel_is_engaged(tmp_path) -> None:
    switch = KillSwitch(settings_flag=False, sentinel_path=tmp_path / "KILL")
    assert switch.engaged is False
    assert switch.engaged_sources == ()


def test_settings_flag_engages(tmp_path) -> None:
    switch = KillSwitch(settings_flag=True, sentinel_path=tmp_path / "KILL")
    assert switch.engaged is True
    assert "settings" in switch.engaged_sources


def test_sentinel_file_engages_and_clearing_it_releases(tmp_path) -> None:
    sentinel = tmp_path / "KILL"
    switch = KillSwitch(sentinel_path=sentinel)
    assert switch.engaged is False

    sentinel.write_text("halt", encoding="utf-8")
    assert switch.engaged is True
    assert switch.engaged_sources == ("file",)

    sentinel.unlink()
    assert switch.engaged is False


@pytest.mark.asyncio
async def test_redis_key_engages_after_refresh(tmp_path) -> None:
    redis = FakeRedis(value="1")
    switch = KillSwitch(
        sentinel_path=tmp_path / "KILL", redis_key="traderstack:kill_switch", redis_client=redis
    )
    assert switch.engaged is False  # not probed yet

    assert await switch.refresh() is True
    assert switch.engaged is True
    assert switch.engaged_sources == ("redis",)
    assert redis.reads == ["traderstack:kill_switch"]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "0", "false", "", b"no"])
async def test_falsy_redis_values_do_not_engage(tmp_path, value) -> None:
    switch = KillSwitch(
        sentinel_path=tmp_path / "KILL", redis_key="k", redis_client=FakeRedis(value=value)
    )
    assert await switch.refresh() is False


@pytest.mark.asyncio
async def test_unreachable_redis_fails_closed(tmp_path) -> None:
    switch = KillSwitch(
        sentinel_path=tmp_path / "KILL", redis_key="k", redis_client=FakeRedis(fail=True)
    )
    assert await switch.refresh() is True
    assert switch.redis_error is not None
    assert "redis" in switch.engaged_sources


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="platform has no SIGUSR1")
def test_sigusr1_engages(tmp_path) -> None:
    switch = KillSwitch(sentinel_path=tmp_path / "KILL")
    assert switch.engaged is False

    assert install_signal_handler() is True
    os.kill(os.getpid(), signal.SIGUSR1)
    assert switch.engaged is True
    assert "signal" in switch.engaged_sources


def test_any_single_channel_is_sufficient(tmp_path) -> None:
    sentinel = tmp_path / "KILL"
    sentinel.write_text("halt", encoding="utf-8")
    switch = KillSwitch(settings_flag=False, sentinel_path=sentinel, redis_engaged=False)
    assert switch.engaged is True


# --- settings wiring -------------------------------------------------------


def test_from_settings_leaves_redis_disabled_by_default(tmp_path) -> None:
    switch = KillSwitch.from_settings(
        Settings(kill_switch=False, kill_switch_file=str(tmp_path / "KILL")),
        redis_client=FakeRedis(value="1"),
    )
    assert switch.redis_client is None
    assert switch.redis_key is None
    assert switch.engaged is False


@pytest.mark.asyncio
async def test_from_settings_enables_redis_when_configured(tmp_path) -> None:
    redis = FakeRedis(value="1")
    switch = KillSwitch.from_settings(
        Settings(
            kill_switch=False,
            kill_switch_file=str(tmp_path / "KILL"),
            kill_switch_redis_enabled=True,
            kill_switch_redis_key="halt:key",
        ),
        redis_client=redis,
    )
    assert await switch.refresh() is True
    assert redis.reads == ["halt:key"]


# --- operator console scripts ---------------------------------------------


def test_kill_and_resume_scripts_toggle_the_sentinel(tmp_path, capsys) -> None:
    sentinel = tmp_path / "state" / "KILL"
    switch = KillSwitch(sentinel_path=sentinel)

    assert kill_main(["--file", str(sentinel), "--reason", "drill"]) == 0
    assert sentinel.exists()
    assert "drill" in sentinel.read_text(encoding="utf-8")
    assert switch.engaged is True

    assert resume_main(["--file", str(sentinel)]) == 0
    assert not sentinel.exists()
    assert switch.engaged is False


def test_resume_is_idempotent_when_no_sentinel_exists(tmp_path, capsys) -> None:
    assert resume_main(["--file", str(tmp_path / "absent")]) == 0
    assert "no kill switch sentinel" in capsys.readouterr().out


def test_scripts_honour_the_kill_switch_file_environment_variable(tmp_path, monkeypatch) -> None:
    sentinel = tmp_path / "ENVKILL"
    monkeypatch.setenv("KILL_SWITCH_FILE", str(sentinel))
    assert kill_main([]) == 0
    assert sentinel.exists()
    assert resume_main([]) == 0
    assert not sentinel.exists()


def test_default_sentinel_path_matches_the_settings_default() -> None:
    assert Settings().kill_switch_file == DEFAULT_KILL_SWITCH_FILE
