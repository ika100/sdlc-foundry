"""Spec 181 AC-181.3: a waiting minute gets its kind from evidence, first match wins, never from a command name alone."""
import pytest

from journey181_support import KINDS, Transcript, run_record, split_of, world  # noqa: F401  (fixture)

CASES = [
    ("cplat pr wait 12", "ci"),
    ("cplat system wait shop", "deploy"),
    ("cplat component ship deploy", "deploy"),
    ("cplat instance promote shop staging", "promotion"),
    ("cplat resource restore db", "restore"),
    ("cplat resource backup db", "restore"),
    ("cplat system restore shop", "restore"),
    ("cplat cluster wait", "cluster"),
    ("cplat cluster new demo", "cluster"),
    ("devbox run cluster-up", "cluster"),
    ("cplat instance verify shop prod", "smoke"),
    ("cplat system ship next shop --wait", "wait"),
    ("cplat system ship land shop", "wait"),
    ("cplat component ship wait", "wait"),
    ("cplat spec land 012", "wait"),
    ("gh run watch 12", "wait"),
    ("gh pr checks 3 --watch", "wait"),
    ("while true; do sleep 30; cplat system status; done", "wait"),
    ("git status", None),
    ("devbox run test", None),
    ("cplat spec check", None),
]


@pytest.mark.parametrize("command,kind", CASES)
def test_command_wait_names_the_kind_of_a_wait_call_ac_181_3(command, kind):  # AC-181.3
    import journey_timeline
    assert journey_timeline.command_wait(command) == kind


def test_each_kinded_wait_call_counts_under_its_kind_ac_181_3(world, capsys):  # AC-181.3
    cmds = ["cplat pr wait 1", "cplat system wait shop", "cplat instance promote shop staging", "cplat resource restore db",
            "cplat cluster wait", "cplat instance verify shop prod"]
    t = Transcript()
    for i, c in enumerate(cmds):
        t.bash(5 * i, 5 * i + 5, c)
    code, out, _ = world.measure(capsys, world.coordinator(t), start="2026-11-10T08:00:00Z", end="2026-11-10T08:30:00Z")
    assert code == 0
    w = split_of(out["wall"])
    for kind in ("ci", "deploy", "promotion", "restore", "cluster", "smoke"):
        assert w["waiting"][kind] == pytest.approx(5, abs=0.1), kind
    assert w["waiting"]["unattributed"] <= 0.1 and w["wall_min"] == 30


def test_an_actions_run_in_a_wait_without_a_kind_counts_as_ci_ac_181_3(world, capsys):  # AC-181.3
    world.actions_runs((2, 6))
    t = Transcript().bash(0, 10, "gh run watch 99")
    code, out, _ = world.measure(capsys, world.coordinator(t), start="2026-11-10T08:00:00Z", end="2026-11-10T08:10:00Z")
    assert code == 0
    w = split_of(out["wall"])
    assert w["waiting"]["ci"] == pytest.approx(4, abs=0.1) and w["waiting"]["unattributed"] == pytest.approx(6, abs=0.1)


def test_a_record_phase_wins_over_an_actions_run_ac_181_3(world, capsys):  # AC-181.3
    world.actions_runs((2, 6))
    world.add_records(run_record("v1", "verify", 0, 10, repo="ika100-demo/shop-api"))
    t = Transcript().bash(0, 10, "gh run watch 99")
    code, out, _ = world.measure(capsys, world.coordinator(t), start="2026-11-10T08:00:00Z", end="2026-11-10T08:10:00Z")
    assert code == 0
    w = split_of(out["wall"])
    assert w["waiting"]["smoke"] == pytest.approx(10, abs=0.1) and w["waiting"]["ci"] == 0


def test_run_records_name_pr_waits_and_deploy_phases_ac_181_3(world, capsys):  # AC-181.3
    world.add_records(run_record("w1", "pr-wait", 0, 5), run_record("s1", "ship", 10, 15, phases=[("deploy", 10, 15)]))
    t = Transcript().bash(0, 20, "cplat system ship next shop --wait")
    code, out, _ = world.measure(capsys, world.coordinator(t), start="2026-11-10T08:00:00Z", end="2026-11-10T08:20:00Z")
    assert code == 0
    w = split_of(out["wall"])
    assert w["waiting"]["ci"] == pytest.approx(5, abs=0.1) and w["waiting"]["deploy"] == pytest.approx(5, abs=0.1)
    assert w["waiting"]["unattributed"] == pytest.approx(10, abs=0.1)


def test_a_wait_without_any_evidence_is_unattributed_not_guessed_ac_181_3(world, capsys):  # AC-181.3
    t = Transcript().bash(0, 20, "cplat system ship next shop --wait")
    code, out, _ = world.measure(capsys, world.coordinator(t), start="2026-11-10T08:00:00Z", end="2026-11-10T08:20:00Z")
    assert code == 0 and set(out["wall"]["waiting"]) == set(KINDS)
    assert out["wall"]["waiting"]["unattributed"] == pytest.approx(20, abs=0.1)
    assert sum(v for k, v in out["wall"]["waiting"].items() if k != "unattributed") == 0
