"""dispatch_ready (spec 167 t13): verdicts and priority order as pure functions over the snapshot, the state and the units."""
import dispatch_backlog
import dispatch_policy
import dispatch_ready
import dispatch_state

from dispatch_world import SLUG, world  # noqa: F401  (fixture)


def _judge(world, units=None, state=None, **policy):
    world.policy(**policy)
    pol = dispatch_policy.load(world.repo)
    snap = dispatch_backlog.snapshot(world.repo, SLUG, max_age=0)
    cands = dispatch_backlog.candidates(snap, pol)
    st = state or dispatch_state.load(SLUG)
    return pol, dispatch_ready.judge(cands, snap, st, units or [], pol)


def _by_item(vs):
    return {v.item: v for v in vs}


def _unit(key, n=1, status="running", **extra):
    return {"unit": f"{key}.{n}", "key": key, "kind": "fix" if key.startswith("issue") else "ship", "status": status,
            "branch": f"fix/{key}" if key.startswith("issue") else "feature/x", **extra}


def test_reasons_and_their_text(world):
    world.issue(1, labels=["triaged", "in-progress"])
    world.issue(2, body="blocked by #1")
    world.issue(3)
    _, vs = _judge(world)
    by = _by_item(vs)
    assert dispatch_ready.text(by["#1"]).startswith("held: claimed (")
    assert dispatch_ready.text(by["#2"]) == "held: blocked (#1 is open)"
    assert dispatch_ready.text(by["#3"]) == "ready"


def test_skip_wins_over_every_other_reason_and_text_names_it(world):
    world.issue(1, labels=["triaged", "in-progress"])
    dispatch_state.skip(SLUG, "issue-1", "waiting for infra")
    _, vs = _judge(world)
    assert dispatch_ready.text(vs[0]) == "held: skipped: waiting for infra"


def test_items_with_a_unit_not_ended_or_ended_after_the_snapshot_have_no_verdict(world):
    world.issue(1)
    world.issue(2)
    world.issue(3)
    units = [_unit("issue-1", status="running"), _unit("issue-2", status="done", ended_at="2999-01-01T00:00:00"),
             _unit("issue-3", status="escalated", ended_at="2000-01-01T00:00:00")]
    _, vs = _judge(world, units=units)
    assert [v.item for v in vs] == ["#3"]


def test_own_dispatcher_claim_on_the_unit_branch_is_not_claimed_but_another_branch_is(world):
    own = "<!-- cplat-claim -->\nClaimed for branch `fix/issue-1` (cplat dispatch)."
    other = "<!-- cplat-claim -->\nClaimed for branch `fix/issue-2` (cplat dispatch)."
    world.issue(1, labels=["triaged", "in-progress"], comments=[own])
    world.issue(2, labels=["triaged", "in-progress"], comments=[other.replace("issue-2", "issue-9")])
    _, vs = _judge(world)
    by = _by_item(vs)
    assert by["#1"].ready and by["#2"].reason == "claimed"


def test_spec_without_issue_is_held_from_the_state_until_resume(world):
    world.spec(7, "price-alerts")
    dispatch_state.hold(SLUG, "spec-007", "needs-decision", "price-alerts.1")
    _, vs = _judge(world, sources=["specs"])
    assert vs[0].reason == "needs-decision"
    dispatch_state.hold(SLUG, "spec-007", "stuck", "price-alerts.1")
    _, vs = _judge(world, sources=["specs"])
    assert vs[0].reason == "stuck"
    dispatch_state.resume_item(SLUG, "spec-007")
    _, vs = _judge(world, sources=["specs"])
    assert vs[0].ready


def test_ship_busy_and_stale_helpers(world):
    world.issue(1)
    _, vs = _judge(world)
    assert dispatch_ready.text(dispatch_ready.hold_ship_busy(vs[0], "spec-007.1")) == "held: ship-busy (spec-007.1)"
    assert dispatch_ready.text(dispatch_ready.hold_stale(vs[0], "abc1234")) == "held: stale (abc1234)"
    assert dispatch_ready.ship_busy_unit([_unit("spec-007", status="running"), _unit("spec-008", status="done")]) == "spec-007.1"
    assert dispatch_ready.ship_busy_unit([_unit("spec-008", status="done")]) is None


def test_order_pins_first_then_rules_as_tie_breakers(world):
    world.issue(1, labels=["triaged"], created="2026-11-01T08:00:00Z")
    world.issue(2, labels=["triaged", "bug"], created="2026-11-03T08:00:00Z")
    world.issue(10, labels=["triaged"], created="2026-11-01T08:00:00Z")
    pol, vs = _judge(world, slots=3)
    keys = lambda out: [v.item for v in out]  # noqa: E731
    assert keys(dispatch_ready.order(vs, pol.values["priority"], [])) == ["#2", "#1", "#10"]
    assert keys(dispatch_ready.order(vs, ["oldest"], [])) == ["#1", "#10", "#2"]
    assert keys(dispatch_ready.order(vs, ["oldest"], ["issue-10", "issue-2"])) == ["#10", "#2", "#1"]


def test_a_spec_matches_a_label_of_a_tracked_issue(world):
    world.policy(sources=["issues", "specs"], slots=3)
    world.issue(42, labels=["triaged", "tracked", "bug"])
    world.spec(7, "price-alerts", tracks=(42,), priority="P2")
    world.spec(8, "refunds", priority="P2")
    pol, vs = _judge(world, sources=["issues", "specs"], slots=3)
    ready = [v for v in vs if v.ready]
    assert [v.item for v in dispatch_ready.order(ready, ["label:bug", "spec-order"], [])] == ["spec-007", "spec-008"]
