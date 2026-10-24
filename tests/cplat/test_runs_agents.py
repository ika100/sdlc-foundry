"""Spec 089: agent quality is recorded per agent, shape and model in the 087 run record (`cplat runs agent`, ship land, spec test-diff)."""
import json
import subprocess
import sys

import pytest

import core
import ship
import spec
import runs
from test_runs import clock, mem, store, stored, rgh, queued  # noqa: F401  (fixtures)
from test_ship import check, git, repo, gh, to_land  # noqa: F401  (fixtures)

ROOT = core.PLATFORM_ROOT
COMMANDS = ROOT / "plugins" / "svc" / "commands"
SPEC_ID = "007-price-alerts"
CODER = "svc-go:coder"                 # the fixture repo is a service-go repo, so the coder is routed to svc-go
ALL_METRICS = ["fix_rounds", "merge_conflicts", "out_of_plan", "red_ci", "refused_test_diffs", "replans", "tester_events", "findings"]


# ---------------- helpers ----------------

def commit(repo, msg="x"):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


def begin(repo, spec_id=SPEC_ID):
    d = ["--dir", str(repo)]
    assert runs.main(["begin", "build", *(["--spec", spec_id] if spec_id else []), *d]) == 0


def agent(repo, *args):
    return runs.main(["agent", *args, "--dir", str(repo)])


def end(repo, store, outcome="done"):
    assert runs.main(["end", "--outcome", outcome, "--dir", str(repo)]) == 0
    return stored(store)[-1]


def entry(rec, name):
    found = [e for e in rec["agents"] if e["agent"] == name]
    assert len(found) == 1, [e["agent"] for e in rec["agents"]]
    return found[0]


def events(rec, name, kind):
    return [e for e in entry(rec, name)["events"] if e["kind"] == kind]


def started(repo, store, capsys=None):
    begin(repo)
    if capsys:
        capsys.readouterr()


# ---------------- AC-089.1 sections and entries ----------------

def test_a_build_that_stops_in_phase_0_still_has_empty_sections(repo, store):
    """AC-089.1: even an escalated build with no agent has `agents: []`, `replans: []` and an `agent_metrics` object."""
    begin(repo)
    rec = end(repo, store, "escalated")
    assert rec["agents"] == [] and rec["replans"] == []
    assert rec["agent_metrics"] == {"schema": 1, "complete": True, "measured": [], "problems": []}


@pytest.mark.parametrize("outcome", ["done", "escalated", "failed", "abandoned"])
def test_every_outcome_carries_the_agents_that_took_part(repo, store, outcome):
    """AC-089.1: with any 087 outcome the record holds one entry per agent x shape x model, with agent, shape, model and model_id."""
    begin(repo)
    assert agent(repo, "spawned", "coder") == 0
    assert agent(repo, "spawned", "coder") == 0                       # the same agent twice is still one entry
    assert agent(repo, "spawned", "architect", "--model-id", "claude-opus-x") == 0
    rec = end(repo, store, outcome)
    assert rec["outcome"] == outcome and len(rec["agents"]) == 2
    c, a = entry(rec, CODER), entry(rec, "svc:architect")
    assert (c["id"], c["shape"], c["model"], c["model_id"]) == (f"{CODER}|service-go|sonnet", "service-go", "sonnet", None)
    assert (a["id"], a["shape"], a["model"], a["model_id"]) == ("svc:architect|service-go|opus", "service-go", "opus", "claude-opus-x")


def test_a_later_call_that_knows_the_model_id_fills_in_the_same_entry(repo, store):
    """AC-089.1: the entry key is agent|shape|model, so a later `--model-id` does not add an entry."""
    begin(repo)
    agent(repo, "spawned", "coder")
    agent(repo, "spawned", "coder", "--model-id", "claude-sonnet-x")
    (c,) = end(repo, store)["agents"]
    assert c["model_id"] == "claude-sonnet-x"


def test_a_repo_without_a_shape_records_shape_none(tmp_path, store):
    """AC-089.1: `shape` is `none` for a repo without one; quality and security are routed as shared:."""
    r = tmp_path / "plain"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    begin(r, None)
    agent(r, "spawned", "coder")
    agent(r, "spawned", "quality")
    rec = end(r, store)
    assert {(e["agent"], e["shape"]) for e in rec["agents"]} == {("svc:coder", "none"), ("shared:quality", "none")}


def test_a_build_inside_a_ship_run_records_into_the_ship_record(repo, gh, store, capsys):
    """AC-089.1: inside /svc:ship the sections live in the ship record."""
    ship.start(repo, "7", True)
    begin(repo)
    agent(repo, "spawned", "coder")
    agent(repo, "spawned", "architect")
    ship.set_phase(repo, "done")
    (r,) = stored(store)
    assert r["kind"] == "ship" and {e["agent"] for e in r["agents"]} == {CODER, "svc:architect"}
    assert r["agent_metrics"]["complete"] is True


def test_the_prompts_record_every_agent_that_is_spawned():
    """AC-089.1: build.md names the spawn call; ship.md records the architect; app build.md points to the per-repo recording."""
    build = (COMMANDS / "build.md").read_text()
    assert "cplat runs agent spawned" in build and "--model-id" in build
    assert "cplat runs agent spawned architect" in (COMMANDS / "ship.md").read_text()
    assert "089" in (ROOT / "plugins" / "app" / "commands" / "build.md").read_text()


# ---------------- AC-089.2 out-of-plan files ----------------

def test_files_outside_the_tasks_plan_count_against_the_architect(repo, store):
    """AC-089.2: one out-of-plan event per file outside the task's `files`, with task id and path; reported helpers are excepted."""
    begin(repo)
    pre = git(repo, "rev-parse", "HEAD")
    (repo / "a.py").write_text("ok\n")                    # in plan for t1
    (repo / "extra.py").write_text("x\n")                 # out of plan
    (repo / "sub").mkdir()
    (repo / "sub" / "more.py").write_text("x\n")          # out of plan
    (repo / "tests_helper.py").write_text("x\n")          # a reported helper
    commit(repo)
    assert agent(repo, "merged", "t1", "--since", pre, "--helper", "tests_helper.py") == 0
    rec = end(repo, store)
    evs = events(rec, "svc:architect", "out-of-plan")
    assert sorted((e["task"], e["path"]) for e in evs) == [("t1", "extra.py"), ("t1", "sub/more.py")]
    assert entry(rec, "svc:architect")["counts"]["out_of_plan"] == 2
    assert entry(rec, CODER)["counts"]["fix_rounds"] == {"lint/type": 0, "test": 0, "ci": 0, "verification": 0}


def test_a_merge_inside_the_plan_counts_zero_not_unmeasured(repo, store):
    """AC-089.2 AC-089.9: a clean merge measures out-of-plan files as 0."""
    begin(repo)
    pre = git(repo, "rev-parse", "HEAD")
    (repo / "a.py").write_text("ok\n")
    commit(repo)
    agent(repo, "merged", "t1", "--since", pre)
    rec = end(repo, store)
    assert entry(rec, "svc:architect")["counts"]["out_of_plan"] == 0
    assert {"out_of_plan", "merge_conflicts", "fix_rounds"} <= set(rec["agent_metrics"]["measured"])


def test_calling_merged_twice_does_not_double_count(repo, store):
    """AC-089.2: an out-of-plan event is keyed by (task, path)."""
    begin(repo)
    pre = git(repo, "rev-parse", "HEAD")
    (repo / "extra.py").write_text("x\n")
    commit(repo)
    agent(repo, "merged", "t1", "--since", pre)
    agent(repo, "merged", "t1", "--since", pre)
    assert entry(end(repo, store), "svc:architect")["counts"]["out_of_plan"] == 1


# ---------------- AC-089.3 merge conflicts ----------------

def conflicted(repo):
    """t1 is done and touched a.py; t3's branch collides with it on a.py. Leaves the merge unfinished, like the build does."""
    (repo / "a.py").write_text("base\n")
    assert spec.main(["--repo", str(repo), "task-done", "007", "t1"]) == 0
    commit(repo, "base")
    git(repo, "checkout", "-qb", "task-t3")
    (repo / "a.py").write_text("one\n")
    commit(repo, "t3")
    git(repo, "checkout", "-q", "main")
    (repo / "a.py").write_text("two\n")
    commit(repo, "t1")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "merge", "task-t3"], cwd=repo, capture_output=True)   # CI has no git identity


def test_a_merge_conflict_is_one_architect_event_with_its_evidence(repo, store):
    """AC-089.3: spec, task, the colliding task, the conflicting paths, the plan author and an outcome (escalated by default)."""
    begin(repo)
    agent(repo, "spawned", "architect", "--model-id", "claude-opus-x")
    conflicted(repo)
    assert agent(repo, "conflict", "t3") == 0
    git(repo, "merge", "--abort")
    rec = end(repo, store, "escalated")
    (ev,) = events(rec, "svc:architect", "merge-conflict")
    assert (ev["spec"], ev["task"], ev["with"], ev["paths"], ev["outcome"]) == (SPEC_ID, "t3", "t1", ["a.py"], "escalated")
    assert ev["author"] == {"agent": "svc:architect", "model": "opus", "model_id": "claude-opus-x"}
    assert entry(rec, "svc:architect")["counts"]["merge_conflicts"] == 1


def test_a_conflict_can_name_its_partner_and_paths(repo, store):
    """AC-089.3: explicit --with and --path win over what git says."""
    begin(repo)
    agent(repo, "conflict", "t3", "--with", "t2", "--path", "x.py", "--path", "y.py")
    (ev,) = events(end(repo, store), "svc:architect", "merge-conflict")
    assert (ev["with"], ev["paths"]) == ("t2", ["x.py", "y.py"])


def test_the_outcome_of_one_conflict_changes_in_place(repo, store):
    """AC-089.3: re-planned, then resolved: one conflict is one event."""
    begin(repo)
    conflicted(repo)
    agent(repo, "conflict", "t3", "--outcome", "re-planned")
    git(repo, "merge", "--abort")
    assert agent(repo, "conflict-outcome", "t3", "resolved") == 0
    rec = end(repo, store)
    (ev,) = events(rec, "svc:architect", "merge-conflict")
    assert ev["outcome"] == "resolved"
    c = entry(rec, "svc:architect")["counts"]
    assert (c["merge_conflicts"], c["conflicts_resolved"]) == (1, 1)


def pointer(repo):
    return (repo / ".git" / "cplat-run.json").read_text()


def test_a_bad_conflict_outcome_is_malformed_and_never_fails(repo, store, capsys):
    """AC-089.3 AC-089.10: an unknown outcome records nothing and marks the metrics incomplete."""
    begin(repo)
    capsys.readouterr()
    assert agent(repo, "conflict-outcome", "t3", "resolved") == 0     # no conflict for t3: malformed too
    assert agent(repo, "conflict", "t3", "--outcome", "resolved") == 0   # `resolved` is only set by conflict-outcome
    rec = end(repo, store)
    assert not any(e["kind"] == "merge-conflict" for a in rec["agents"] for e in a["events"])
    assert rec["agent_metrics"]["complete"] is False


def test_the_prompt_records_conflicts_before_the_merge_is_aborted():
    """AC-089.2 AC-089.3: build.md notes HEAD before a merge, records `merged ... --since` and `conflict` before `git merge --abort`."""
    text = (COMMANDS / "build.md").read_text()
    assert "PRE=$(git rev-parse HEAD)" in text
    assert "cplat runs agent merged" in text and "--since" in text and "--helper" in text
    i = text.index("cplat runs agent conflict")
    assert "git merge --abort" in text[i:i + 600]


# ---------------- AC-089.14 re-plans ----------------

def test_a_replan_is_recorded_and_linked_to_its_conflict(repo, store):
    """AC-089.14: the replans section gets one entry, the architect counts one re-plan, the conflict is `re-planned`, then `resolved`."""
    begin(repo)
    agent(repo, "conflict", "t3", "--outcome", "re-planned", "--with", "t1", "--path", "a.py")
    assert agent(repo, "replan", "t3", "--model-id", "claude-opus-y") == 0
    assert agent(repo, "conflict-outcome", "t3", "resolved") == 0
    rec = end(repo, store)
    assert rec["replans"] == [{"id": "re-plan:1", "spec": SPEC_ID, "task": "t3", "agent": "svc:architect", "model": "opus",
                               "model_id": "claude-opus-y", "conflict": "merge-conflict:1"}]
    arch = entry(rec, "svc:architect")
    assert arch["model_id"] == "claude-opus-y" and arch["counts"]["replans"] == 1
    (rp,) = [e for e in arch["events"] if e["kind"] == "re-plan"]
    assert (rp["id"], rp["task"], rp["conflict"]) == ("re-plan:1", "t3", "merge-conflict:1")
    (cf,) = [e for e in arch["events"] if e["kind"] == "merge-conflict"]
    assert cf["id"] == "merge-conflict:1" and cf["outcome"] == "resolved"


def test_a_replan_sets_the_conflict_to_replanned(repo, store):
    """AC-089.14: `replan` alone moves an escalated conflict to `re-planned`."""
    begin(repo)
    agent(repo, "conflict", "t3", "--with", "t1", "--path", "a.py")
    agent(repo, "replan", "t3")
    rec = end(repo, store)
    assert events(rec, "svc:architect", "merge-conflict")[0]["outcome"] == "re-planned"


def test_the_replan_spec_id_survives_redaction(repo, store):
    """AC-089.14: spec ids are 40+ characters long; the record keeps them instead of `<long-string>`."""
    long_id = "089-agent-quality-is-measured-per-agent-and"
    begin(repo, long_id)
    agent(repo, "conflict", "t3", "--with", "t1", "--path", "a.py", "--spec", long_id)
    agent(repo, "replan", "t3")
    rec = end(repo, store)
    assert rec["replans"][0]["spec"] == long_id
    assert events(rec, "svc:architect", "merge-conflict")[0]["spec"] == long_id


# ---------------- AC-089.4 fix rounds ----------------

def test_hand_backs_are_fix_rounds_with_a_cause(repo, store):
    """AC-089.4: each hand-back to a coder counts one fix round against that coder, by cause."""
    begin(repo)
    agent(repo, "fix-round", "lint/type", "--task", "t1")
    agent(repo, "fix-round", "test", "--task", "t2")
    agent(repo, "fix-round", "test")
    agent(repo, "fix-round", "ci")
    agent(repo, "fix-round", "verification", "--task", "t3")
    rec = end(repo, store)
    c = entry(rec, CODER)
    assert c["counts"]["fix_rounds"] == {"lint/type": 1, "test": 2, "ci": 1, "verification": 1}
    assert [(e["cause"], e["task"]) for e in c["events"] if e["kind"] == "fix-round"] == [
        ("lint/type", "t1"), ("test", "t2"), ("test", None), ("ci", None), ("verification", "t3")]


def test_an_unknown_fix_round_cause_is_not_counted(repo, store, capsys):
    """AC-089.4 AC-089.10: only lint/type, test, ci and verification are causes."""
    begin(repo)
    capsys.readouterr()
    assert agent(repo, "fix-round", "lint") == 0
    rec = end(repo, store)
    assert not any(e["kind"] == "fix-round" for a in rec["agents"] for e in a["events"])
    assert rec["agent_metrics"]["complete"] is False


def test_the_prompt_names_every_fix_round_cause():
    """AC-089.4: build.md records hand-backs with the four causes."""
    text = (COMMANDS / "build.md").read_text()
    for cause in ("lint/type", "verification"):
        assert f"cplat runs agent fix-round {cause}" in text or f"fix-round {cause}" in text
    assert "cplat runs agent fix-round" in text and "fix-round ci" in text and "fix-round test" in text
    assert "fix-round ci" in (COMMANDS / "ship.md").read_text()


# ---------------- AC-089.5 red CI in ship land ----------------

def test_a_red_ci_round_counts_against_the_coder_with_the_check_name(repo, rgh, store):
    """AC-089.5: land records one red-CI event on the shape's coder, caused by the first red check; never quality or security."""
    to_land(repo, rgh, merge=False)
    rgh.checks = [[check("test (pytest + coverage)", "fail"), check("lint", "fail")]]
    rgh.logs["42"] = ["--- FAIL: TestPriceAlert"]
    assert not ship.land(repo, timeout=600, interval=10, queue_timeout=20)[0]
    rgh.checks = [[check("test", "pass")]]
    assert ship.land(repo, timeout=600, interval=10, queue_timeout=20)[0]
    (r,) = stored(store)
    (ev,) = events(r, CODER, "red-ci")
    assert ev["check"] == "test (pytest + coverage)" and ev["checks"] == ["test (pytest + coverage)", "lint"]
    assert entry(r, CODER)["counts"]["red_ci"] == 1
    assert {e["agent"] for e in r["agents"]} == {CODER}
    assert "red_ci" in r["agent_metrics"]["measured"]


def test_reruns_are_never_counted_against_an_agent(repo, rgh, store):
    """AC-089.5: a stuck run, a transient failure, then green: red_ci is measured and 0, and only the real red round counts."""
    to_land(repo, rgh, merge=False)
    rgh.checks = [[check("test", "fail")]]
    rgh.logs["42"] = ["--- FAIL: TestPriceAlert", "expected 3, got 4"]
    assert not ship.land(repo, timeout=600, interval=10, queue_timeout=20)[0]
    rgh.checks = [[queued("e2e")]] * 6 + [[check("e2e", "fail")]]
    assert not ship.land(repo, timeout=600, interval=10, queue_timeout=20)[0]
    maven = "[ERROR] Failed to read artifact descriptor for org.apache.maven.shared:maven-shared-utils:jar:3.4.2"
    rgh.logs["42"] = [maven]
    rgh.checks = [[check("java", "fail")], [check("java", "fail")], [check("java", "pending")], [check("java", "pass")]]
    assert ship.land(repo, timeout=600, interval=10, queue_timeout=20)[0]
    (r,) = stored(store)
    assert [e["check"] for e in events(r, CODER, "red-ci")] == ["test", "e2e"]       # `java` was a transient rerun


def test_a_green_land_measures_red_ci_as_zero(repo, gh, store):
    """AC-089.5 AC-089.9: a green conclusion marks the metric measured with no event."""
    to_land(repo, gh, merge=False)
    gh.checks = [[check("test", "pass")]]
    assert ship.land(repo, timeout=60, interval=10)[0]
    (r,) = stored(store)
    assert entry(r, CODER)["counts"]["red_ci"] == 0 and "red_ci" in r["agent_metrics"]["measured"]


def test_a_failing_recording_never_changes_what_land_returns(repo, gh, store, monkeypatch):
    """AC-089.5 AC-089.10: if recording the red round raises, land still returns RED exactly as before."""
    import runs_agents

    def boom(*a, **k):
        raise RuntimeError("recording is broken")

    monkeypatch.setattr(runs_agents, "red_ci", boom)
    to_land(repo, gh)
    gh.checks = [[check("test", "fail")]]
    ok, lines = ship.land(repo, timeout=600, interval=10)
    assert not ok and "RED: 1 of 1" in lines[0] and ship.load_state(repo)["fix_rounds"] == 1


# ---------------- AC-089.6 review findings ----------------

def verification(repo, rows):
    d = repo / "docs" / "specs" / SPEC_ID
    body = "| Criterion | Verdict | Notes |\n|---|---|---|\n" + "".join(f"| {c} | {v} | n |\n" for c, v in rows)
    (d / "verification.md").write_text("# Verification\n\n**Result:** fail\n\n" + body)


def test_first_pass_findings_count_by_severity_against_the_covering_coders(repo, store):
    """AC-089.6: not met and partial rows, plus unacceptable deviations (an AC id or a task id), with the covering tasks."""
    begin(repo)
    verification(repo, [("AC-007.1", "not met"), ("AC-007.2", "partial")])
    assert agent(repo, "findings", "--cycle", "1", "--deviation", "AC-007.2", "--deviation", "t2") == 0
    rec = end(repo, store)
    c = entry(rec, CODER)
    assert c["counts"]["findings"]["first"] == {"not met": 1, "partial": 1, "deviation": 2}
    assert c["counts"]["findings"]["after fix"] == {"not met": 0, "partial": 0, "deviation": 0}
    by = {(e["severity"], e["criterion"], e["task"]): e for e in c["events"] if e["kind"] == "finding"}
    nm = by[("not met", "AC-007.1", None)]
    assert (nm["pass"], nm["cycle"], nm["tasks"]) == ("first", 1, ["t1", "t3"])
    assert by[("partial", "AC-007.2", None)]["tasks"] == ["t2", "t3"]
    assert by[("deviation", "AC-007.2", None)]["tasks"] == ["t2", "t3"]
    assert by[("deviation", None, "t2")]["tasks"] == ["t2"]
    assert {"findings", "fix_rounds"} <= set(rec["agent_metrics"]["measured"])


def test_findings_of_later_cycles_are_after_fix(repo, store):
    """AC-089.6: cycle 2 findings are counted separately as `after fix`; a repeated call upserts."""
    begin(repo)
    verification(repo, [("AC-007.1", "not met"), ("AC-007.2", "met")])
    agent(repo, "findings", "--cycle", "1")
    agent(repo, "findings", "--cycle", "1")
    agent(repo, "findings", "--cycle", "2")
    c = entry(end(repo, store), CODER)["counts"]["findings"]
    assert c["first"]["not met"] == 1 and c["after fix"]["not met"] == 1


def test_findings_without_a_verification_md_are_malformed(repo, store):
    """AC-089.6 AC-089.10: no verification.md: nothing counted, the record says so."""
    begin(repo)
    assert agent(repo, "findings", "--cycle", "1") == 0
    rec = end(repo, store)
    assert rec["agent_metrics"]["complete"] is False and rec["agent_metrics"]["problems"]


def test_the_prompt_records_each_reviewer_pass():
    """AC-089.6: build.md records the findings after each reviewer pass."""
    assert "cplat runs agent findings --cycle" in (COMMANDS / "build.md").read_text()


# ---------------- AC-089.7 refused acceptance-test diffs ----------------

def go_test_repo(repo):
    sp = repo / "docs" / "specs" / SPEC_ID / "spec.md"       # test-diff guards the tests of a spec being built
    sp.write_text(sp.read_text().replace("status: approved", "status: building"))
    (repo / "pkg").mkdir()
    (repo / "pkg" / "x_test.go").write_text("package pkg\n// AC-007.1\nfunc TestA() { want(1) }\n")
    commit(repo, "red")


def test_a_refused_test_diff_counts_against_the_coder_with_the_file(repo, store, capsys):
    """AC-089.7: a refusal records one event with the file and the task; the output and exit code are unchanged."""
    begin(repo)
    go_test_repo(repo)
    (repo / "pkg" / "x_test.go").write_text("package pkg\n// AC-007.1\nfunc TestA() { want(2) }\n")
    capsys.readouterr()
    assert spec.main(["--repo", str(repo), "test-diff", "HEAD", "--task", "t1"]) == 1
    assert "pkg/x_test.go: changed" in capsys.readouterr().out
    rec = end(repo, store)
    (ev,) = events(rec, CODER, "refused-test-diff")
    assert (ev["file"], ev["task"]) == ("pkg/x_test.go", "t1") and ev["reason"]
    assert entry(rec, CODER)["counts"]["refused_test_diffs"] == 1


def test_the_quality_agent_is_charged_when_it_changed_the_test(repo, store):
    """AC-089.7: `--by quality` counts against the quality agent."""
    begin(repo)
    go_test_repo(repo)
    (repo / "pkg" / "x_test.go").write_text("package pkg\n// AC-007.1\nfunc TestA() { want(3) }\n")
    assert spec.main(["--repo", str(repo), "test-diff", "HEAD", "--by", "quality"]) == 1
    rec = end(repo, store)
    q = entry(rec, "shared:quality")
    assert q["counts"] == {"refused_test_diffs": 1} and q["events"][0]["file"] == "pkg/x_test.go"
    assert not any(e["kind"] == "refused-test-diff" for e in entry(rec, CODER).get("events", []))


def test_a_passing_test_diff_measures_refusals_as_zero(repo, store):
    """AC-089.7 AC-089.9: a green diff check counts 0 rather than leaving the metric unmeasured."""
    begin(repo)
    go_test_repo(repo)
    assert spec.main(["--repo", str(repo), "test-diff", "HEAD"]) == 0
    rec = end(repo, store)
    assert entry(rec, CODER)["counts"]["refused_test_diffs"] == 0 and "refused_test_diffs" in rec["agent_metrics"]["measured"]


def test_a_failing_recording_never_changes_the_test_diff_result(repo, store, monkeypatch):
    """AC-089.7 AC-089.10: the exit code stays 1 when recording raises."""
    import runs_agents
    monkeypatch.setattr(runs_agents, "refused_test_diff", lambda *a, **k: 1 / 0)
    begin(repo)
    go_test_repo(repo)
    (repo / "pkg" / "x_test.go").write_text("package pkg\n// AC-007.1\nfunc TestA() { want(2) }\n")
    assert spec.main(["--repo", str(repo), "test-diff", "HEAD", "--task", "t1"]) == 1


def test_the_prompt_passes_task_and_quality_to_test_diff():
    """AC-089.7: build.md adds `--task` in Phase 2 and `--by quality` in Phase 3."""
    text = (COMMANDS / "build.md").read_text()
    assert "test-diff $RED --task" in text and "--by quality" in text


# ---------------- AC-089.8 tester events ----------------

def test_untraced_criteria_and_wrong_failures_count_against_the_tester(repo, store):
    """AC-089.8: one event per criterion or test, with the reason."""
    begin(repo)
    assert agent(repo, "tester", "--untraced", "AC-007.1", "--untraced", "AC-007.2", "--wrong-failure", "test_alert") == 0
    agent(repo, "tester", "--untraced", "AC-007.1")                        # repeated: not counted twice
    rec = end(repo, store)
    t = entry(rec, "svc-go:tester")
    assert t["counts"] == {"tester_events": {"untraced": 2, "wrong failure": 1}}
    assert sorted((e["reason"], e["criterion"], e["test"]) for e in t["events"]) == [
        ("untraced", "AC-007.1", None), ("untraced", "AC-007.2", None), ("wrong failure", None, "test_alert")]


def test_a_tester_call_without_ids_measures_zero(repo, store):
    """AC-089.8 AC-089.9: a clean Phase 1 is 0 events, not 'not measured'."""
    begin(repo)
    assert agent(repo, "tester") == 0
    rec = end(repo, store)
    assert entry(rec, "svc-go:tester")["counts"] == {"tester_events": {"untraced": 0, "wrong failure": 0}}
    assert rec["agent_metrics"]["measured"] == ["tester_events"]


def test_the_prompt_records_the_tester_after_the_red_checks():
    """AC-089.8: build.md calls `cplat runs agent tester` with --untraced and --wrong-failure."""
    text = (COMMANDS / "build.md").read_text()
    assert "cplat runs agent tester" in text and "--untraced" in text and "--wrong-failure" in text


# ---------------- AC-089.9 not measured ----------------

def test_metrics_that_were_never_observed_are_null_not_zero(repo, store):
    """AC-089.9: the phase never ran: the counts are null and `measured` lists only what was observed."""
    begin(repo)
    agent(repo, "spawned", "coder")
    agent(repo, "spawned", "architect")
    rec = end(repo, store, "escalated")
    assert entry(rec, CODER)["counts"] == {"fix_rounds": None, "red_ci": None, "findings": None, "refused_test_diffs": None}
    assert entry(rec, "svc:architect")["counts"]["out_of_plan"] is None
    assert rec["agent_metrics"]["measured"] == []


def test_a_measured_metric_does_not_measure_the_others(repo, store):
    """AC-089.9: a fix round measures fix_rounds only; `measured` is sorted and unique."""
    begin(repo)
    agent(repo, "fix-round", "ci")
    agent(repo, "fix-round", "test")
    rec = end(repo, store)
    c = entry(rec, CODER)["counts"]
    assert c["fix_rounds"]["ci"] == 1 and c["red_ci"] is None and c["findings"] is None
    assert rec["agent_metrics"]["measured"] == ["fix_rounds"]


# ---------------- AC-089.10 recording never stops a build ----------------

def test_a_malformed_call_exits_zero_prints_one_warning_and_flags_the_record(repo, store, capsys):
    """AC-089.10: a malformed event does not fail the run; stdout stays empty, stderr gets one WARNING line."""
    begin(repo)
    capsys.readouterr()
    assert agent(repo, "fix-round", "lint") == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err.count("WARNING: agent metric not recorded") == 1
    assert "marked incomplete" in out.err
    rec = end(repo, store)
    assert rec["outcome"] == "done"
    m = rec["agent_metrics"]
    assert m["complete"] is False and any("fix-round" in p or "lint" in p for p in m["problems"])


@pytest.mark.parametrize("argv", [["bogus"], ["fix-round"], ["merged"], ["tester", "--nope"], ["findings", "--cycle", "x"], []])
def test_an_unparsable_call_never_exits_nonzero(repo, store, capsys, argv):
    """AC-089.10: argparse errors are swallowed too: exit 0, nothing on stdout, the record incomplete."""
    begin(repo)
    capsys.readouterr()
    assert agent(repo, *argv) == 0
    assert capsys.readouterr().out == ""
    assert end(repo, store)["agent_metrics"]["complete"] is False


def test_a_call_outside_any_run_is_a_silent_no_op(repo, store, capsys):
    """AC-089.10: without an active run nothing is recorded and nothing fails."""
    assert agent(repo, "fix-round", "ci") == 0
    assert capsys.readouterr().out == "" and stored(store) == []


def test_an_unwritable_active_record_still_ends_up_marked_incomplete(repo, store, monkeypatch):
    """AC-089.10: when the active file cannot be written, the finished record still says its agent metrics are incomplete."""
    begin(repo)
    agent(repo, "spawned", "coder")

    def boom(*a, **k):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(runs, "_write_active", boom)
        assert agent(repo, "fix-round", "ci") == 0
    rec = end(repo, store)
    assert rec["outcome"] == "done" and rec["agent_metrics"]["complete"] is False and rec["agent_metrics"]["problems"]


def test_mark_incomplete_survives_a_missing_run(repo):
    """AC-089.10: the runs.py helpers never raise, whatever the run id."""
    runs.mark_incomplete(None, "agent_metrics", "malformed: x")
    runs.mark_incomplete("no-such-run", "agent_metrics", "malformed: x")
    assert runs.mutate(None, lambda rec: None) == "none" and runs.mutate("no-such-run", lambda rec: None) == "none"


def test_mutate_reports_ok_and_error(repo, store):
    """AC-089.10: `runs.mutate` is the generic in-place change: ok, or error with nothing written."""
    begin(repo)
    rid = json.loads(pointer(repo))["run_id"]
    assert runs.mutate(rid, lambda rec: rec.update(marker=1)) == "ok" and runs.active(rid)["marker"] == 1

    def bad(rec):
        rec["marker"] = 2
        raise ValueError("no")

    assert runs.mutate(rid, bad) == "error" and runs.active(rid)["marker"] == 1
    assert runs.current_run(repo) == rid


def test_the_help_line_mentions_agent_metrics():
    """AC-089.10: `cplat runs ... agent` is listed in the cplat docstring."""
    assert "agent" in (ROOT / "scripts" / "cplat" / "cplat.py").read_text().split("runs init|flush|report|begin|phase|end", 1)[1].split("\n", 1)[0]
