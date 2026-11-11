"""Spec 181 AC-181.1 and AC-181.4: a coordinator's wait on its headless repo sessions is agent time while they work."""
from journey181_support import COORD, Transcript, split_of, system_ship, world  # noqa: F401  (fixture)


def coordinator_waiting_40():
    """08:00-09:00; `system ship next --wait` from 08:10 to 08:50, work around it (20 min of the coordinator's own)."""
    return (Transcript().model(0).bash(10, 50, "cplat system ship next shop --wait").model(60))


def test_children_working_during_the_wait_count_as_agents_ac_181_1(world, capsys):  # AC-181.1
    child = Transcript().call(15, 30, "Agent", description="build").bash(30, 45, "devbox run test")
    sub = Transcript().bash(15, 30, "pytest -q")
    world.child("child1", child, subagent=sub)
    system_ship(world)                                          # the repo session is found from the run records only
    code, out, _ = world.measure(capsys, world.coordinator(coordinator_waiting_40()))
    assert code == 0
    w = split_of(out["wall"])
    assert abs(w["agents"]["children"] - 30) <= 0.1             # repo session and its subagent
    assert abs(w["agents"]["coordinator"] - 20) <= 0.1
    assert abs(w["waiting_min"] - 10) <= 0.1 and abs(w["waiting"]["unattributed"] - 10) <= 0.1
    assert w["waiting"]["deploy"] == 0                          # `system ship next --wait` is never a kind
    assert w["person_min"] == 0 and w["wall_min"] == 60


def test_a_coordinator_subagent_working_during_an_agent_call_is_coordinator_time_ac_181_1(world, capsys):  # AC-181.1
    coord = Transcript().model(0).call(10, 50, "Agent", description="review").model(60)
    sub = Transcript().bash(15, 45, "pytest -q")                # the coordinator's own subagent, not a repo session
    code, out, _ = world.measure(capsys, world.coordinator(coord, subagent=sub))
    assert code == 0
    w = split_of(out["wall"])
    assert w["agents"]["children"] == 0                         # only repo sessions and their subagents are children
    assert abs(w["agents"]["coordinator"] - 50) <= 0.1          # own 20 min plus the subagent's 30 min
    assert abs(w["waiting_min"] - 10) <= 0.1 and w["person_min"] == 0   # 10-15 and 45-50: the call is open, nothing works


def test_the_repo_session_is_never_named_on_the_command_line_ac_181_1(world, capsys):  # AC-181.1
    world.child("child1", Transcript().bash(15, 45, "devbox run test"))
    code, out, err = world.measure(capsys, world.coordinator(coordinator_waiting_40()))      # no run records at all
    assert code == 0 and out["wall"]["agents"]["children"] == 0
    assert "no system ship run record overlaps the journey" in err
    assert any("no system ship run record" in x for x in out["warnings"])


def test_a_repo_session_without_a_transcript_is_warned_about_and_counted_ac_181_4(world, capsys):  # AC-181.4
    system_ship(world, "ghost1", child_span=(12, 32), phases=[("deploy", 12, 32)])
    code, out, err = world.measure(capsys, world.coordinator(coordinator_waiting_40()))
    assert code == 0
    lines = [x for x in err.splitlines() if x.startswith("WARNING")]
    assert len(lines) == 1 and "ika100-demo/shop-api" in lines[0] and "ghost1" in lines[0]
    assert len(out["warnings"]) == 1 and "ghost1" in out["warnings"][0]
    w = split_of(out["wall"])
    assert abs(w["waiting"]["no_transcript"] - 20) <= 0.1       # 08:12-08:32, where nothing else works
    assert w["waiting"]["deploy"] == 0                          # the deploy phase of the record does not win
    assert abs(w["waiting"]["unattributed"] - 20) <= 0.1        # the rest of the wait, 08:10-08:12 and 08:32-08:50


def test_the_coordinator_session_id_is_not_a_repo_session_ac_181_1(world, capsys):  # AC-181.1
    system_ship(world, "child1")
    world.child("child1", Transcript().bash(15, 45, "devbox run test"))
    code, out, err = world.measure(capsys, world.coordinator(coordinator_waiting_40()))
    assert code == 0 and "WARNING" not in err and COORD not in err
    assert out["wall"]["repo_sessions"] == 1
