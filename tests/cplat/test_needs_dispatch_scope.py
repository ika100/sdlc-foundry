"""`cplat needs` for the dispatcher (spec 167): repo scope, the kinds `budget` and `stuck`, escalations of issue units."""
import json
import subprocess

import pytest

import cplat
import dispatch_state
import needs
import runs
from test_needs import FakeGh, issue

SLUG = "acme/shop-api"
BUDGET = {"id": f"budget:{SLUG}:2026-11-10", "kind": "budget", "stage": "Build", "since": "2026-11-10T08:00:00Z",
          "object": {"type": "dispatch", "repo": SLUG}, "reason": "daily token budget reached", "command": "raise it"}


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    d = tmp_path / "shop-api"
    (d / ".platform").mkdir(parents=True)
    (d / ".platform" / "dispatch.yml").write_text("slots: 1\n")
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "config", "remote.origin.url", f"https://github.com/{SLUG}.git"], check=True)
    fake = FakeGh()
    monkeypatch.setattr(needs, "gh", fake)
    return d, fake


def doc_of(d, capsys, *extra):
    rc = cplat.main(["needs", "--json", "--repo-dir", str(d), *extra])
    out = capsys.readouterr()
    assert rc == 0, out.err
    return json.loads(out.out)


def kind(doc, k):
    return [i for i in doc["items"] if i["kind"] == k]


def put_needs(slug, *items):
    path = dispatch_state.needs_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": list(items)}))


def unit_run(number, outcome="escalated", reason="tests keep failing", run=None, kind_="dispatch"):
    rid = runs.start(kind_, repo=SLUG)
    fields = {"issue": {"repo": SLUG, "number": number, "url": f"https://github.com/{SLUG}/issues/{number}"}}
    runs.finish(rid, outcome, escalation={"reason": reason, "cause": "code", **({"run": run} if run else {})} if outcome == "escalated" else None,
                fields=fields)
    return rid


def test_a_repo_with_a_policy_file_and_no_system_has_its_own_scope(repo, capsys):
    d, fake = repo
    fake.issues[SLUG] = [issue(5, ["triage"], title="odd thing")]
    put_needs(SLUG, BUDGET)
    put_needs("other/repo", {**BUDGET, "id": "budget:other/repo:x", "object": {"type": "dispatch", "repo": "other/repo"}})
    doc = doc_of(d, capsys)
    assert [i["id"] for i in kind(doc, "triage")] == [f"triage:{SLUG}:5"]            # a triage issue without alert label
    assert [i["id"] for i in kind(doc, "budget")] == [BUDGET["id"]]                  # the other repo's need is not listed


def test_a_directory_with_neither_file_still_fails(tmp_path, capsys):
    rc = cplat.main(["needs", "--json", "--repo-dir", str(tmp_path)])
    assert rc == 1 and "system.yaml" in capsys.readouterr().err


def test_an_issue_unit_escalation_names_the_label_command(repo, capsys):
    d, _ = repo
    rid = unit_run(7)
    [e] = kind(doc_of(d, capsys), "escalation")
    assert e["id"] == f"escalation:{rid}" and e["object"]["issue"] == 7 and "tests keep failing" in e["reason"]
    assert e["command"] == "gh issue edit 7 --remove-label needs-decision" and e["cwd_repo"] == SLUG


def test_a_newer_run_hides_the_escalation_only_for_the_same_issue(repo, capsys):
    d, _ = repo
    unit_run(7)
    unit_run(8, outcome="done")
    assert len(kind(doc_of(d, capsys), "escalation")) == 1
    unit_run(7, outcome="done")
    assert kind(doc_of(d, capsys), "escalation") == []


def test_a_unit_naming_an_escalated_ship_run_is_left_to_that_run(repo, capsys):
    d, _ = repo
    ship = runs.start("ship", repo=SLUG, spec="007-x")
    runs.phase(ship, "build")
    runs.finish(ship, "escalated", escalation={"reason": "ci", "cause": "code"})
    unit_run(7, run=ship)
    [e] = kind(doc_of(d, capsys), "escalation")
    assert e["object"]["run_id"] == ship
