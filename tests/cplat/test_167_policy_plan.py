"""Spec 167 acceptance tests: the policy file and `cplat dispatch plan` (AC-167.1, AC-167.2).

Contract: design.md "The policy" (keys, errors), "Commands and output" (`plan` text and JSON). Seams: the world of
`dispatch_world.py` (fake `gh` on PATH, fake claude, a real clone), `cplat.main(["dispatch", ...])` in the clone.
"""
import datetime as dt
import re

import pytest

from dispatch_world import world  # noqa: F401  (fixture)

KEYS = ["slots", "budget", "sources", "ready", "priority", "gates", "serialize"]


def _nothing_happened(w, before):
    assert w.calls() == [] and w.gh_writes() == [] and w.fingerprint() == before


@pytest.mark.parametrize("verb", ["start", "resume"])
def test_without_a_policy_file_start_and_resume_exit_1_naming_it_and_start_nothing(world, verb):  # AC-167.1
    world.issue(1)
    before = world.fingerprint()
    r = world.run(verb, "--once") if verb == "start" else world.run(verb)
    assert r.rc == 1, r
    assert ".platform/dispatch.yml" in r.err and r.err.startswith("ERROR:")
    _nothing_happened(world, before)


@pytest.mark.parametrize("verb", ["start", "resume"])
@pytest.mark.parametrize("text", ["slots: 2\n", "slots: 2\nbudget:\n  per_unit:\n    cost: 20\n"])
def test_a_policy_without_the_daily_budget_is_refused_by_start_and_resume_naming_the_key(world, verb, text):  # AC-167.1
    world.issue(1)
    world.policy_text(text)
    before = world.fingerprint()
    r = world.run(verb, "--once") if verb == "start" else world.run(verb)
    assert r.rc == 1, r
    assert "budget.tokens_per_day" in r.err
    _nothing_happened(world, before)


@pytest.mark.parametrize("verb", ["plan", "status"])
@pytest.mark.parametrize("text,key,allowed", [
    ("budget:\n  tokens_per_day: 100\nfrobnicate: 1\n", "frobnicate", KEYS),
    ("budget:\n  tokens_per_day: 100\n  limit: 3\n", "budget.limit", ["tokens_per_day", "per_unit"]),
    ("budget:\n  tokens_per_day: 100\ngates:\n  approve: human\n", "gates.approve", ["approve_specs", "merge"]),
    ("budget:\n  tokens_per_day: 100\nready:\n  label: [bug]\n", "ready.label", ["labels", "exclude_labels"]),
])
def test_an_unknown_key_fails_naming_the_key_and_the_allowed_ones_on_every_command_ac_167_1(world, verb, text, key, allowed):  # AC-167.1
    world.policy_text(text)
    r = world.run(verb)
    assert r.rc == 1, r
    assert key in r.err and "allowed" in r.err and all(a in r.err for a in allowed), r.err


@pytest.mark.parametrize("text,key,words", [
    ("gates:\n  merge: manual\n", "gates.merge", ["manual", "green-ci"]),
    ("gates:\n  approve_specs: robot\n", "gates.approve_specs", ["robot", "human", "self"]),
    ("serialize: [e2e]\n", "serialize", ["merge"]),
    ("serialize: [merge, lint]\n", "serialize", ["lint", "e2e"]),
    ("slots: 0\n", "slots", ["0"]),
    ("slots: 11\n", "slots", ["11"]),
    ("sources: [prs]\n", "sources", ["prs", "issues", "specs"]),
    ("sources: []\n", "sources", ["issues", "specs"]),
    ("budget:\n  tokens_per_day: 0\n", "budget.tokens_per_day", ["0"]),
    ("budget:\n  tokens_per_day: 100\n  per_unit:\n    cost: free\n", "budget.per_unit.cost", ["free", "off"]),
])
@pytest.mark.parametrize("verb", ["plan", "start"])
def test_a_value_outside_the_allowed_ones_fails_naming_the_key_and_the_values_ac_167_1(world, verb, text, key, words):  # AC-167.1
    world.policy_text("budget:\n  tokens_per_day: 100\n" + text if not text.startswith("budget") else text)
    r = world.run("plan") if verb == "plan" else world.run("start", "--once")
    assert r.rc == 1, r
    assert key in r.err and all(w in r.err for w in words), r.err
    assert world.calls() == [] and world.gh_writes() == []


def test_plan_without_a_file_prints_the_marked_defaults_and_the_unset_budget_with_a_7_day_hint_ac_167_2(world):  # AC-167.2
    r = world.run("plan", "--json")
    assert r.rc == 0, r
    doc = r.json()
    pol = doc["policy"]
    assert pol["file"] is None
    assert pol["values"] == {"slots": 1, "budget": {"tokens_per_day": None, "per_unit": {}}, "sources": ["issues"],
                             "ready": {"labels": [], "exclude_labels": []}, "priority": ["label:bug", "label:p1", "spec-order", "oldest"],
                             "gates": {"approve_specs": "human", "merge": "green-ci"}, "serialize": ["merge"]}
    assert "slots" in pol["defaulted"] and pol["unset"] == ["budget.tokens_per_day"]
    hint = pol["usage_hint"]
    today = world.now.date()
    assert [h["day"] for h in hint] == [(today - dt.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    assert all("tokens" in h and (h["tokens"] is None or isinstance(h["tokens"], int)) for h in hint)
    text = world.run("plan").out
    assert "policy: defaults (no .platform/dispatch.yml)" in text
    assert re.search(r"budget\.tokens_per_day: unset .*last 7 days", text) and "(default)" in text


def test_plan_with_a_file_names_it_and_shows_the_set_values_ac_167_2(world):  # AC-167.2
    world.policy(slots=2, sources=["issues", "specs"], budget={"tokens_per_day": 5_000_000, "per_unit": {"cost": 20}})
    doc = world.plan()
    pol = doc["policy"]
    assert pol["file"] == ".platform/dispatch.yml" and pol["unset"] == []
    assert pol["values"]["slots"] == 2 and pol["values"]["sources"] == ["issues", "specs"]
    assert pol["values"]["budget"] == {"tokens_per_day": 5_000_000, "per_unit": {"cost": 20}}
    assert "slots" not in pol["defaulted"] and "gates.merge" in pol["defaulted"]
    assert doc["tokens"]["limit"] == 5_000_000 and doc["slots"]["total"] == 2
    text = world.run("plan").out
    assert "policy: .platform/dispatch.yml" in text and "tokens today:" in text


def test_plan_lists_every_candidate_once_in_order_with_kind_verdict_mode_and_slot_ac_167_2(world):  # AC-167.2
    world.policy(slots=2)
    world.issue(1, title="plain old one", labels=["triaged"], created="2026-11-01T08:00:00Z")
    world.issue(2, title="a bug", labels=["triaged", "bug"], created="2026-11-02T08:00:00Z")
    world.issue(3, title="another bug", labels=["triaged", "bug"], created="2026-11-03T08:00:00Z")
    world.issue(4, title="blocked one", labels=["triaged", "bug"], body="blocked by #1", created="2026-11-04T08:00:00Z")
    world.issue(5, title="not triaged", labels=["bug"])
    doc = world.plan()
    assert sorted(world.order(doc)) == ["#1", "#2", "#3", "#4"]     # the triaged issues, each once
    ready = [c for c in doc["candidates"] if c["verdict"] == "ready"]
    assert [c["item"] for c in ready] == ["#2", "#3", "#1"]
    assert all(c["kind"] == "fix" and c["mode"] == "single" for c in doc["candidates"] if c["item"] != "#4")
    assert [c["slot"] for c in ready] == [1, 2, None]               # two slots: the third queues
    held = world.cand(doc, "#4")
    assert held["verdict"] == "held" and held["reason"] == "blocked" and held["slot"] is None
    assert doc["slots"] == {"total": 2, "running": 0, "free": 2, "manual": []}
    assert doc["starts"]["allowed"] is True
    lines = world.run("plan").out.splitlines()
    rows = [re.split(r"\s{2,}", ln.strip()) for ln in lines[next(i for i, ln in enumerate(lines) if ln.startswith("candidates (")) + 1:]
            if ln.strip()]
    assert sorted(r[0] for r in rows) == ["#1", "#2", "#3", "#4"]
    by = {r[0]: r for r in rows}
    assert [r[0] for r in rows if r[2] == "ready"] == ["#2", "#3", "#1"]
    assert by["#2"][1:5] == ["fix", "ready", "single", "slot 1"] and by["#4"][2].startswith("held: blocked")
    assert by["#1"][4] == "queued"


def test_plan_changes_nothing_on_github_in_branches_worktrees_or_claims_ac_167_2(world):  # AC-167.2
    world.policy(slots=2, sources=["issues", "specs"])
    world.issue(1, labels=["triaged", "bug"])
    world.issue(2, labels=["triaged"], body="Depends on #1")
    world.issue(3, labels=["triaged", "in-progress"])
    world.spec(7, "price-alerts", plan="team")
    world.spec(8, "refunds", status="draft")
    before = world.fingerprint()
    for args in (("plan",), ("plan", "--json")):
        assert world.run(*args).rc == 0
    assert world.fingerprint() == before
    assert world.gh_writes() == [] and world.calls() == []
    assert not list((world.dispatch_dir() / "worktrees").glob("*"))


def test_plan_shows_a_spec_as_a_ship_candidate_with_its_mode_ac_167_2(world):  # AC-167.2
    world.policy(slots=1, sources=["specs"])
    sid = world.spec(7, "price-alerts", plan="team")
    doc = world.plan()
    [c] = doc["candidates"]
    assert c["kind"] == "ship" and c["verdict"] == "ready" and c["mode"] == "team" and c["slot"] == 1
    assert sid.startswith("007") and c["item"] in ("007", "spec-007", sid)
