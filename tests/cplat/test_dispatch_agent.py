"""Module-level tests of dispatch_agent (spec 167): the premise and mode checks against the fake claude of the dispatcher world."""
import dispatch_agent as da
import dispatch_state as ds

from dispatch_world import SLUG, world  # noqa: F401  (fixture)


def _issue(n, title="stale thing", updated="2026-11-02T08:00:00Z"):
    return {"number": n, "title": title, "body": "it breaks", "createdAt": "2026-11-01T08:00:00Z", "updatedAt": updated}


def _main(world):
    return da._git(world.repo, "rev-parse", "origin/main")[1]


def test_resolved_with_a_commit_on_main_is_kept_with_the_full_sha(world):
    sha = world.commit("price.txt", "rounded\n", "fix: round the price (#1)")
    world.answer("stale thing", verdict="resolved", evidence=sha[:9], why="rounded")
    out = da.premise(world.repo, _issue(1), _main(world))
    assert out["verdict"] == "resolved" and out["evidence"] == sha and out["tokens"] == 1500
    assert any("#1" in line for line in da.hints(world.repo, _issue(1)))
    assert "stale thing" in world.claude_calls()[0]["prompt"]


def test_evidence_off_main_or_unknown_is_holds(world):
    world.answer("stale thing", verdict="resolved", evidence="deadbeefdeadbeefdeadbeef", why="trust me")
    out = da.premise(world.repo, _issue(1), _main(world))
    assert out["verdict"] == "holds" and out["evidence"] is None


def test_a_failed_call_is_holds_and_not_cached(world):
    world.claude(fail=True)
    out = da.premise(world.repo, _issue(1), _main(world))
    assert out["verdict"] == "holds" and out["tokens"] is None
    assert not ds.load(SLUG)["checks"]


def test_the_premise_is_cached_by_main_and_update_time(world):
    main = _main(world)
    da.premise(world.repo, _issue(1), main)
    again = da.premise(world.repo, _issue(1), main)
    assert again["cached"] and again["tokens"] == 0 and len(world.claude_calls()) == 1
    da.premise(world.repo, _issue(1, updated="2026-11-03T08:00:00Z"), main)
    assert len(world.claude_calls()) == 2


def test_a_plan_with_a_batch_is_team_without_a_call(world):
    sid = world.spec(7, "price-alerts", plan="team")
    out = da.mode(world.repo, sid)
    assert out["mode"] == "team" and not world.claude_calls()
    assert da.mode(world.repo, world.spec(7, "price-alerts", plan="single"))["mode"] == "single"
    assert not world.claude_calls()


def test_a_spec_without_a_plan_asks_the_agent_once(world):
    sid = world.spec(9, "drafty", plan=None)
    world.answer(sid, mode="team", why="two parts")
    assert da.mode(world.repo, sid)["mode"] == "team"
    again = da.mode(world.repo, sid)
    assert again["mode"] == "team" and again["cached"] and len(world.claude_calls()) == 1


def test_a_failed_mode_call_is_single(world):
    sid = world.spec(9, "drafty", plan=None)
    world.claude(fail=True)
    assert da.mode(world.repo, sid)["mode"] == "single"


def test_the_answer_may_be_wrapped_in_prose():
    assert da._answer('Sure: ```json\n{"mode": "team"}\n```') == {"mode": "team"}
