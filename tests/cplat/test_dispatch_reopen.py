"""A reopened issue is not closed as stale again, even when the user also removed its `stale-premise` label."""
from dispatch_world import world  # noqa: F401  (fixture)


def test_reopened_with_the_label_removed_is_not_closed_as_stale_again(world):
    world.policy(slots=1)
    sha = world.commit("price.txt", "rounded\n", "fix: round the price (#1)")
    world.issue(1, title="stale thing")
    world.answer("stale thing", verdict="resolved", evidence=sha, why="rounded")
    world.run("start", "--once")
    assert world.issue_of(1)["state"] == "CLOSED"
    assert 1 in world.state()["stale_closed"]
    world.edit_gh(lambda d: d["issues"]["1"].update(state="OPEN", labels=["triaged"]))
    asked = len([c for c in world.claude_calls() if "stale thing" in c["prompt"]])
    r = world.run("start", "--once")
    assert r.rc == 0, r
    assert world.issue_of(1)["state"] == "OPEN"
    assert len([c for c in world.comments_of(1) if "<!-- cplat-dispatch-stale -->" in c]) == 1
    assert len([c for c in world.claude_calls() if "stale thing" in c["prompt"]]) == asked
