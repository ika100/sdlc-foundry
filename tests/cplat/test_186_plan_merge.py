"""Spec 186 acceptance tests: a task that cannot pass alone is merged into the later task (AC-186.4, AC-186.5; #681).

Seams: a real git repo with an approved spec 007 and a committed plan (`cplat plan merge` is called as `cplat.main`), the run store of the
run record (`test_runs`), `units.detect` on a committed plan, the run allowlist of `preflight` and the dry run of `cplat headless`.
`plancmd` and `runs_agents.task_merge` do not exist yet: they are reached through `cplat.main` and imported inside the tests.
"""
import re
import subprocess

import pytest
import yaml

import cplat
import spec
from prompts186_support import ROOT, collapsed, prompt, sourced
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import repo as ship_repo  # noqa: F401  (fixture)
from test_spec import make
from units131_support import BRANCH, World, git, make_repo, plan_for

SPEC_ID = "007-price-alerts"
PLAN_REL = f"docs/specs/{SPEC_ID}/plan.md"
REASON = "the store alone cannot pass without the switch"

PLAN = """---
spec_id: 007-price-alerts
shape: service-python
spec_hash: "{hash}"
tasks:
  - {{id: t1, title: store, files: [a.py], covers: [AC-007.1], parallel_safe: true, depends_on: []}}
  - {{id: t2, title: switch, files: [b.py], covers: [AC-007.2], parallel_safe: true, depends_on: [t1]}}
  - {{id: t3, title: wire, files: [c.py], covers: [AC-007.1, AC-007.2], parallel_safe: false, depends_on: [t1, t2]}}
  - {{id: t4, title: docs, files: [d.py], covers: [AC-007.2], parallel_safe: true, depends_on: [t1]}}
---

## t1 — store

Body of t1.

**Files:** a.py

## t2 — switch

Body of t2.

**Files:** b.py
**Covers:** AC-007.2

## t3 — wire

Body of t3.
"""


@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


def commit(repo, msg="plan"):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


@pytest.fixture()
def r(tmp_path):
    root = tmp_path / "shop-api"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@t")
    s = make(root, status="approved", plan=False)
    (s.dir / "plan.md").write_text(PLAN.format(hash=s.ac_hash()))
    commit(root, "init")
    return root


def merge(capsys, repo, *args):
    capsys.readouterr()
    rc = cplat.main(["plan", "merge", *args, "--repo", str(repo)])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def plan_meta(repo):
    return yaml.safe_load((repo / PLAN_REL).read_text().split("---\n", 2)[1])


def task(repo, tid):
    return next(t for t in plan_meta(repo)["tasks"] if t["id"] == tid)


def spec_hash_line(repo):
    return next(ln for ln in (repo / PLAN_REL).read_text().splitlines() if ln.startswith("spec_hash:"))


# ---------------- AC-186.4: the command ----------------

def test_plan_merge_folds_the_task_into_the_later_one_ac_186_4(r, capsys):  # AC-186.4
    before = spec_hash_line(r)
    rc, out, err = merge(capsys, r, "t1", "t2", "--spec", SPEC_ID, "--reason", REASON)
    assert rc == 0, out + err
    meta = plan_meta(r)
    assert [t["id"] for t in meta["tasks"]] == ["t2", "t3", "t4"]
    t2 = task(r, "t2")
    assert t2["title"] == "switch"
    assert t2["files"] == ["b.py", "a.py"] and t2["covers"] == ["AC-007.2", "AC-007.1"] and t2["depends_on"] == []
    assert task(r, "t3")["depends_on"] == ["t2"] and task(r, "t4")["depends_on"] == ["t2"]     # dependants of t1 move to t2, no duplicate
    assert spec_hash_line(r) == before and meta["spec_hash"] == yaml.safe_load(before.split(":", 1)[1])
    assert spec.check(spec.read(r / "docs" / "specs" / SPEC_ID)) == []


def test_plan_merge_moves_the_prose_of_the_merged_task_ac_186_4(r, capsys):  # AC-186.4
    assert merge(capsys, r, "t1", "t2", "--spec", SPEC_ID, "--reason", REASON)[0] == 0
    text = (r / PLAN_REL).read_text()
    assert "## t1 —" not in text
    section = text.split("## t2 —", 1)[1].split("## t3 —", 1)[0]
    assert "Body of t1." in section and "Body of t2." in section and "Merged from t1" in section
    files_line = next(ln for ln in section.splitlines() if ln.startswith("**Files:**"))
    assert "a.py" in files_line and "b.py" in files_line


def test_plan_merge_prints_what_it_did_and_commits_only_the_plan_ac_186_4(r, capsys):  # AC-186.4
    rc, out, _ = merge(capsys, r, "t1", "t2", "--spec", SPEC_ID, "--reason", REASON)
    lines = out.splitlines()
    assert rc == 0 and lines[0] == f"MERGED t1 into t2: {REASON}"
    assert "files:" in lines[1] and "a.py" in lines[1] and "b.py" in lines[1] and "covers:" in lines[1] and "depends_on: none" in lines[1]
    assert lines[2].startswith("  dependants moved to t2:") and "t3" in lines[2] and "t4" in lines[2]
    assert re.fullmatch(r"  committed [0-9a-f]{7}", lines[3]) and lines[3].split()[-1] == git(r, "rev-parse", "--short=7", "HEAD")
    assert git(r, "log", "-1", "--format=%s") == f"chore(plan): {SPEC_ID} merge t1 into t2"
    body = git(r, "log", "-1", "--format=%b")
    assert REASON in body and "Plan-Merge: t1 into t2" in body and "Signed-off-by:" in body
    assert git(r, "show", "--name-only", "--format=", "HEAD").splitlines() == [PLAN_REL]
    assert git(r, "status", "--porcelain") == ""


def test_plan_merge_without_a_reason_says_the_default_ac_186_4(r, capsys):  # AC-186.4
    rc, out, _ = merge(capsys, r, "t1", "t2", "--spec", SPEC_ID)
    assert rc == 0 and out.splitlines()[0] == "MERGED t1 into t2: the checks of t1 pass only together with t2"


def test_plan_merge_finds_the_spec_from_the_feature_branch_ac_186_4(r, capsys):  # AC-186.4
    git(r, "checkout", "-q", "-b", f"feature/{SPEC_ID}")
    rc, out, err = merge(capsys, r, "t1", "t2")
    assert rc == 0, out + err
    assert [t["id"] for t in plan_meta(r)["tasks"]] == ["t2", "t3", "t4"]


def _refused(capsys, r, args, line_has):
    plan, head = (r / PLAN_REL).read_text(), git(r, "rev-parse", "HEAD")
    rc, out, err = merge(capsys, r, *args, "--spec", SPEC_ID)
    lines = [ln for ln in (out + err).splitlines() if ln.strip()]
    assert rc == 1 and len(lines) == 1 and lines[0].startswith("ERROR: ") and line_has in lines[0], (rc, out, err)
    assert (r / PLAN_REL).read_text() == plan and git(r, "rev-parse", "HEAD") == head


def test_an_unknown_task_is_refused_with_one_line_and_no_change_ac_186_4(r, capsys):  # AC-186.4
    _refused(capsys, r, ["t1", "t9"], "unknown task 't9' in " + SPEC_ID)
    _refused(capsys, r, ["t9", "t2"], "unknown task 't9' in " + SPEC_ID)


@pytest.mark.parametrize("done", ["t1", "t2"])
def test_a_done_task_is_not_merged_ac_186_4(r, capsys, done):  # AC-186.4
    p = r / PLAN_REL
    p.write_text(re.sub(rf"(  - \{{id: {done},[^\n]*?)\}}", r"\1, done: true}", p.read_text()))
    commit(r, "done")
    _refused(capsys, r, ["t1", "t2"], f"{done} is done: a done task is not merged")


def test_a_task_that_does_not_depend_on_the_other_is_refused_ac_186_4(r, capsys):  # AC-186.4
    _refused(capsys, r, ["t3", "t4"], "t4 does not depend on t3: only a task that depends directly on another is merged into it")
    _refused(capsys, r, ["t2", "t1"], "t1 does not depend on t2")


def test_a_merge_that_makes_the_plan_cyclic_is_refused_ac_186_4(r, capsys):  # AC-186.4
    # t2 depends on t1 and t3 depends on t2: folding t1 into t3 would make t2 and t3 wait for each other
    _refused(capsys, r, ["t1", "t3"], "the merged plan does not check")


def test_a_plan_with_uncommitted_changes_is_refused_ac_186_4(r, capsys):  # AC-186.4
    p = r / PLAN_REL
    p.write_text(p.read_text() + "\nA note.\n")
    _refused(capsys, r, ["t1", "t2"], "uncommitted changes")


# ---------------- AC-186.5: the run record and the PR block ----------------

def test_a_task_merge_is_recorded_under_the_architect_ac_186_5(ship_repo, store):  # AC-186.5
    import runs
    import runs_agents
    from test_runs_agents import begin, end, events
    begin(ship_repo)
    runs_agents.task_merge(runs.current(ship_repo), ship_repo, "t1", "t3", REASON)
    rec = end(ship_repo, store)
    (ev,) = events(rec, "svc:architect", "task-merge")
    assert (ev["task"], ev["into"], ev["reason"]) == ("t1", "t3", REASON)


def test_the_pr_block_names_both_tasks_and_the_reason_of_a_merge_ac_186_5(ship_repo, store, capsys):  # AC-186.5
    import runs
    from test_runs_agents import begin
    begin(ship_repo)
    rid = runs.current(ship_repo)
    rc, out, err = merge(capsys, ship_repo, "t1", "t3", "--spec", SPEC_ID, "--reason", REASON)
    assert rc == 0, out + err
    capsys.readouterr()
    assert cplat.main(["platform", "runs", "report", "--pr", rid, "--dir", str(ship_repo)]) == 0
    block = capsys.readouterr().out
    part = block.split("#### Hand-backs and fix rounds", 1)[1].split("####", 1)[0]
    assert f"merged task t1 into t3: {REASON}" in part


# ---------------- AC-186.5: unit mode goes on with the merged task ----------------

def _unit_repo(tmp_path, merged_away, done=(), name="shop-api"):
    r = make_repo(tmp_path, plan=False, name=name)
    text = plan_for(3, 3, spec.read(r / "docs" / "specs" / "007-price-alerts").ac_hash())
    keep = [ln for ln in text.splitlines(True) if not any(ln.startswith(f"  - {{id: {t},") for t in merged_away)]
    text = "".join(keep)
    for t in done:
        text = re.sub(rf"(  - \{{id: {t},[^\n]*?)\}}", r"\1, done: true}", text)
    (r / PLAN_REL).write_text(text)
    commit(r, "plan")
    return r


def test_a_task_gone_from_the_committed_plan_counts_as_merged_in_its_unit_ac_186_5(tmp_path):  # AC-186.5
    import units
    r = _unit_repo(tmp_path, merged_away=["t2"], done=["t1"])
    assert units.detect(r, "build", "007-price-alerts", "task:t2") is not None       # t2 was merged away: its unit checkpoints
    assert units.detect(r, "build", "007-price-alerts", "batch:t1,t2") is not None
    assert units.detect(r, "build", "007-price-alerts", "task:t3") is None           # t3 is still open and carries the work


# ---------------- AC-186.5: the run allowlist ----------------

COMMANDS = ["/component:build", "/component:ship", "/system:ship"]


@pytest.mark.parametrize("command", COMMANDS)
def test_the_run_allowlist_allows_cplat_plan_merge_ac_186_5(command):  # AC-186.5
    import preflight
    rules = preflight.run_allowlist(command, [BRANCH])
    assert "Bash(cplat plan merge *)" in rules and len(rules) == len(set(rules))
    assert any(preflight.matches(rule, "cplat plan merge t2 t3 --reason x") for rule in rules)
    assert not [x for x in preflight.refused_rules("main") if preflight.matches(x, "cplat plan merge t2 t3")]
    preflight._self_check()


def test_the_dry_run_prints_cplat_plan_merge_in_the_allowlist_ac_186_5(tmp_path, monkeypatch, capsys):  # AC-186.5
    w = World(tmp_path, monkeypatch, plan=True)
    for prompt_text in (None, "/component:build 7"):
        assert w.run("--dry-run", **({"prompt": prompt_text} if prompt_text else {})) == 0
        block = [ln[2:] for ln in capsys.readouterr().out.splitlines() if ln.startswith("  ")]
        assert "Bash(cplat plan merge *)" in block


# ---------------- AC-186.5: the prompts and their register entries ----------------

def test_the_build_prompt_merges_a_task_that_cannot_pass_alone_and_registers_it_ac_186_5():  # AC-186.5
    path = "plugins/component/commands/build.md"
    assert "cplat plan merge" in prompt(path)
    found = sourced(path, "#681")
    assert found and any("cplat plan merge" in collapsed(str(e["text"])) for e in found) and {e["class"] for e in found} == {"experience"}


def test_the_architect_plans_a_change_and_what_makes_it_pass_as_one_task_and_registers_it_ac_186_5():  # AC-186.5
    found = sourced("plugins/svc/agents/architect.md", "#681")
    assert found and {e["class"] for e in found} == {"experience"}


def test_the_rule_register_still_checks_with_the_new_entries_ac_186_5():  # AC-186.5
    import rulescheck
    assert sourced("plugins/component/commands/build.md", "#681") and sourced("plugins/svc/agents/architect.md", "#681")
    result = rulescheck.check(ROOT)
    assert result.ok, [f"{f.file}:{f.line} {f.kind}" for f in result.failures][:5]
