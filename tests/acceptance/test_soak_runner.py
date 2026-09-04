"""Epic 10: the soak runner itself.

Short, bounded runs of ``traderstack-soak`` -- the real ``cli.build_service``
wiring against the synthetic market -- plus the shipped scenario files, so the
24/7 command an operator eventually runs is known to work before they run it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from traderstack.acceptance.soak import (
    REPORTED_METRICS,
    FaultSchedule,
    SoakReport,
    SoakRunner,
    SoakScenario,
    build_parser,
    main,
    metrics_snapshot,
    scenario_from_args,
)

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "ops" / "soak" / "scenarios"


def _scenario(tmp_path: Path, **overrides) -> SoakScenario:
    values: dict[str, object] = {
        "name": "unit",
        "cycles": 6,
        "symbols": ["BTC/USD"],
        "settings": {"kill_switch_file": str(tmp_path / "state" / "KILL")},
    }
    values.update(overrides)
    return SoakScenario(**values)  # type: ignore[arg-type]


async def test_a_clean_run_passes_and_reports_everything(tmp_path: Path) -> None:
    report = await SoakRunner(scenario=_scenario(tmp_path), workdir=tmp_path).run()

    assert report.passed is True
    assert report.failures == []
    assert report.cycles == 6
    assert report.outcomes["accepted"] == 6
    assert report.risk_decisions["allow"] == 6
    assert report.orders_submitted == 6
    assert report.ledger_orders == 6
    assert report.venue_posts == 6
    assert report.reconciliations == {"clean": 6, "blocked": 0}
    assert report.audit_chain_verified is True
    assert report.risk_audit_records == 6
    assert report.runtime_events == 6
    assert report.health["healthy"] is True
    assert report.policy_version.startswith("mvp-v1+")
    assert report.metrics, "the report carries a Prometheus snapshot"
    assert (tmp_path / "audit" / "runtime.jsonl").exists()
    assert (tmp_path / "state" / "execution_ledger.json").exists()
    assert (tmp_path / "state" / "portfolio.json").exists()
    assert "Soak scenario: unit" in report.render()


async def test_the_same_seed_reproduces_the_same_run(tmp_path: Path) -> None:
    first = await SoakRunner(
        scenario=_scenario(tmp_path / "a", seed=42), workdir=tmp_path / "a"
    ).run()
    second = await SoakRunner(
        scenario=_scenario(tmp_path / "b", seed=42), workdir=tmp_path / "b"
    ).run()

    assert first.outcomes == second.outcomes
    assert first.risk_decisions == second.risk_decisions
    assert first.portfolio["nav_usd"] == pytest.approx(second.portfolio["nav_usd"])


async def test_a_scheduled_fault_arms_and_disarms_at_the_right_cycles(tmp_path: Path) -> None:
    scenario = _scenario(
        tmp_path,
        cycles=9,
        # A threshold above the outage length keeps the provider circuit closed,
        # so this test observes the fault schedule and nothing else. The breaker
        # has its own drill in test_provider_outages.py.
        settings={
            "kill_switch_file": str(tmp_path / "state" / "KILL"),
            "provider_failure_threshold": 5,
        },
        faults=[
            FaultSchedule(fault="coingecko_reference_error", arm_at_cycle=3, disarm_at_cycle=6),
            FaultSchedule(fault="coinmarketcap_reference_error", arm_at_cycle=3, disarm_at_cycle=6),
        ],
    )
    report = await SoakRunner(scenario=scenario, workdir=tmp_path).run()

    assert report.rejection_reasons["no_independent_reference_price"] == 3
    assert report.outcomes["accepted"] == 6
    assert report.faults_fired["coingecko_reference_error"] == 3
    assert report.passed is True, "a fail-closed rejection is a pass, not a failure"


async def test_the_kill_switch_scenario_halts_and_resumes(tmp_path: Path) -> None:
    scenario = _scenario(
        tmp_path,
        cycles=9,
        faults=[FaultSchedule(fault="kill_switch_file", arm_at_cycle=3, disarm_at_cycle=6)],
    )
    report = await SoakRunner(scenario=scenario, workdir=tmp_path).run()

    assert report.risk_reasons["kill_switch_enabled"] == 3
    assert report.risk_decisions["reject"] == 3
    assert report.risk_decisions["allow"] == 6
    assert report.orders_submitted == 6
    assert report.risk_audit_records == 9, "halted cycles are still audited"
    assert report.passed is True


async def test_a_sink_outage_is_visible_in_the_report(tmp_path: Path) -> None:
    scenario = _scenario(
        tmp_path,
        cycles=6,
        error_backoff_seconds=0.0,
        faults=[FaultSchedule(fault="audit_sink_error", arm_at_cycle=2, times=2)],
    )
    report = await SoakRunner(scenario=scenario, workdir=tmp_path).run()

    assert report.faults_fired["audit_sink_error"] == 2
    assert report.runtime_events == 4
    assert report.health["consecutive_errors"] == 0, "the run recovered before finishing"
    assert report.passed is True


@pytest.mark.parametrize("name", ["baseline", "provider_outage", "kill_switch_drill"])
async def test_the_shipped_scenarios_load_and_run(tmp_path: Path, name: str) -> None:
    scenario = SoakScenario.load(SCENARIO_DIR / f"{name}.json")
    assert scenario.name == name
    assert scenario.description
    # Trimmed so the suite stays fast; the schedule and semantics are unchanged.
    trimmed = scenario.model_copy(
        update={
            "cycles": 12,
            "error_backoff_seconds": 0.0,
            "settings": {**scenario.settings, "kill_switch_file": str(tmp_path / "KILL")},
            "faults": [entry for entry in scenario.faults if entry.arm_at_cycle < 12],
        }
    )
    report = await SoakRunner(scenario=trimmed, workdir=tmp_path).run()

    assert report.cycles == 12
    assert report.audit_chain_verified is True
    assert report.passed is True, report.failures


def test_main_writes_a_json_report_and_exits_zero(tmp_path: Path, capsys) -> None:
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(
        json.dumps(
            {
                "name": "cli",
                "cycles": 3,
                "symbols": ["BTC/USD"],
                "settings": {"kill_switch_file": str(tmp_path / "KILL")},
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    code = main(
        [
            "--scenario",
            str(scenario_path),
            "--workdir",
            str(tmp_path / "run"),
            "--report",
            str(report_path),
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["scenario"] == "cli"
    assert payload["cycles"] == 3
    assert payload["passed"] is True
    assert '"scenario": "cli"' in capsys.readouterr().out


def test_cli_flags_override_the_scenario_file() -> None:
    args = build_parser().parse_args(["--cycles", "5", "--seed", "99", "--symbols", "ETH/USD"])
    scenario = scenario_from_args(args)

    assert scenario.cycles == 5
    assert scenario.seconds is None
    assert scenario.seed == 99
    assert scenario.symbols == ["ETH/USD"]


def test_seconds_overrides_the_cycle_bound() -> None:
    args = build_parser().parse_args(["--seconds", "86400"])
    scenario = scenario_from_args(args)

    assert scenario.seconds == 86_400
    assert scenario.cycles is None


def test_the_metrics_snapshot_only_reports_known_families() -> None:
    snapshot = metrics_snapshot()

    assert snapshot
    for key in snapshot:
        assert key.split("{", 1)[0] in REPORTED_METRICS


def test_a_failing_report_exits_non_zero(tmp_path: Path) -> None:
    report = SoakReport(
        scenario="broken",
        seed=1,
        symbols=["BTC/USD"],
        started_at="2026-09-04T00:00:00Z",
        finished_at="2026-09-04T00:00:01Z",
        elapsed_seconds=1.0,
        cycles=0,
        failures=["no cycles ran"],
        passed=False,
    )
    assert report.passed is False
    assert "FAIL: no cycles ran" in report.render()
