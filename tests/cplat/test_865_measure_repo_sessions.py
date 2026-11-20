"""#865: journey measure counts the tokens of every repo session and its subagents once, and follows component ships."""
from journey181_support import COORD, Transcript, at, run_record, system_ship, world  # noqa: F401  (fixture)


def u(n):
    """A usage block of n tokens in all (cache reads, as in real transcripts)."""
    return {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": n, "output_tokens": 0}


def coordinator():
    return Transcript().model(0, u(100), "m_c1").bash(10, 50, "cplat system ship next shop --wait").model(60, u(200), "m_c2")


def test_repo_sessions_and_their_subagents_count_each_message_once(world, capsys):
    child = Transcript().model(15, u(1000), "m_r1").model(40, u(2000), "m_r2")
    sub = Transcript().model(20, u(4000), "m_s1").model(40, u(2000), "m_r2")    # m_r2 also in the parent: counted once
    world.child("child1", child, subagent=sub)
    system_ship(world)
    coord_sub = Transcript().model(5, u(10), "m_cs1")
    code, out, _ = world.measure(capsys, world.coordinator(coordinator(), subagent=coord_sub))
    assert code == 0
    t = out["tokens"]
    assert t["total"] == 100 + 200 + 10 + 1000 + 2000 + 4000 and t["api_calls"] == 7   # with the tool call of the coordinator
    assert t["by_actor"] == {"coordinator": 300, "coordinator_subagents": 10, "repo_sessions": 3000, "repo_subagents": 4000}


def test_a_component_ship_is_a_root_like_a_system_ship(world, capsys):
    world.child("child1", Transcript().model(15, u(1000), "m_r1").bash(16, 40, "devbox run test"))
    world.add_records(
        run_record("s1", "ship", 5, 55, repo="ika100-demo/shop-api", sessions=[COORD], ships=["h1"]),
        run_record("h1", "headless", 5, 55, repo="ika100-demo/shop-api", sessions=["child1"], parent="s1"),
        run_record("x1", "ship", 5, 55, repo="other/repo", sessions=["stranger"]))   # not the journey's: no root
    world.child("stranger", Transcript().model(15, u(99999), "m_x1"))
    code, out, err = world.measure(capsys, world.coordinator(coordinator()))
    assert code == 0 and "no system ship run record" not in err
    assert out["wall"]["repo_sessions"] == 1
    assert out["tokens"]["by_actor"]["repo_sessions"] == 1000 and out["tokens"]["total"] == 1300
    assert out["wall"]["agents"]["children"] > 20                  # the repo session's work is agent time, not waiting


def test_repo_session_tokens_belong_to_the_step_that_contains_them(world, capsys, tmp_path):
    world.child("child1", Transcript().model(15, u(1000), "m_r1").model(45, u(2000), "m_r2"))
    system_ship(world)
    steps = tmp_path / "steps.tsv"
    steps.write_text(f"{at(0)}\tfirst\n{at(30)}\tsecond\n")
    code, out, _ = world.measure(capsys, world.coordinator(coordinator()), "--steps", str(steps))
    assert code == 0
    first, second = out["steps"]
    assert first["tokens"] == 1100 and first["tokens_by_actor"]["repo_sessions"] == 1000
    assert second["tokens"] == 2200 and second["tokens_by_actor"]["repo_sessions"] == 2000
    assert out["steps_total"]["tokens"] == out["tokens"]["total"] == 3300


def test_the_text_output_shows_the_token_split(world, capsys):
    world.child("child1", Transcript().model(15, u(3_000_000), "m_r1"))
    system_ship(world)
    code, text, _ = world.measure_text(capsys, world.coordinator(coordinator()))
    assert code == 0
    assert "tokens 3.0 M" in text
    assert "repo sessions 3.0 M" in text and "coordinator 0.0 M" in text
