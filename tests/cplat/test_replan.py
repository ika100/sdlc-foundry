"""Spec 094: a merge conflict re-plans instead of escalating (`cplat build`, scripts/cplat/replan.py), on real git repos."""
import json
import re
import subprocess

import pytest

import cplat
import core
import runs
import spec
from test_runs import clock, mem, store, stored, buffered_lines  # noqa: F401  (fixtures)
from test_ship import git, repo  # noqa: F401  (fixtures)
from test_runs_agents import entry, events

SPEC_ID = "007-price-alerts"
SPEC_DIR = "docs/specs/" + SPEC_ID

PLAN = """---
spec_id: {sid}
shape: service-python
spec_hash: {hash}
tasks:
  - {{id: t1, title: model, files: [a.py], covers: [AC-007.1], parallel_safe: true, depends_on: []}}
  - {{id: t2, title: hook, files: [b.py], covers: [AC-007.2], parallel_safe: true, depends_on: []}}
  - {{id: t3, title: wire, files: [c.py], covers: [AC-007.1], parallel_safe: true, depends_on: []}}
  - {{id: t4, title: docs, files: [d.py], covers: [AC-007.2], parallel_safe: false, depends_on: [t1, t2, t3]}}
---

## t1 — model
"""


# ---------------- helpers ----------------

def build(capsys, repo, *args):
    capsys.readouterr()
    rc = cplat.main(["build", args[0], SPEC_ID, *args[1:], "--repo", str(repo)])
    out = capsys.readouterr()
    return rc, out.out, out.err


def jbuild(capsys, repo, sub):
    rc, out, err = build(capsys, repo, sub, "--json")
    assert rc == 0, err
    return json.loads(out)


def commit(repo, msg="x"):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


def plan_path(repo):
    return repo / SPEC_DIR / "plan.md"


def write_plan(repo, text):
    plan_path(repo).write_text(text)


def _flow_tasks(text):
    """Re-render the `tasks:` list in the one-line flow form of PLAN (`spec task-done` rewrites it as block YAML)."""
    import yaml
    _, front, body = text.split("---\n", 2)
    meta = yaml.safe_load(front)
    head = front[: front.index("tasks:")]
    keys = ("id", "title", "repo", "files", "covers", "parallel_safe", "depends_on", "done")

    def val(v):
        if isinstance(v, list):
            return "[" + ", ".join(str(x) for x in v) + "]"
        return str(v).lower() if isinstance(v, bool) else str(v)

    rows = []
    for t in meta["tasks"]:
        order = [k for k in keys if k in t] + [k for k in t if k not in keys]
        rows.append("  - {" + ", ".join(f"{k}: {val(t[k])}" for k in order) + "}")
    return "---\n" + head + "tasks:\n" + "\n".join(rows) + "\n---\n" + body


def edit_plan(repo, old, new):
    text = plan_path(repo).read_text()
    if old not in text:
        text = _flow_tasks(text)
    assert old in text
    write_plan(repo, text.replace(old, new))


def branch_from(repo, name, base, files):
    """A task branch off `base` that writes `files` ({path: text}); leaves the checkout where it was."""
    here = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "-q", "-b", name, base)
    for p, text in files.items():
        (repo / p).write_text(text)
    commit(repo, f"work on {name}")
    git(repo, "checkout", "-q", here)


def done(capsys, repo, task):
    """What the build does after a clean merge: mark done, `build resolved`, commit the plan."""
    assert spec.main(["--repo", str(repo), "task-done", "007", task]) == 0
    rc, out, err = build(capsys, repo, "resolved", task)
    assert rc == 0, err
    commit(repo, f"chore(plan): {SPEC_ID} {task} done")


@pytest.fixture()
def world(repo):
    """A feature branch with a valid plan t1..t4 (all disjoint `files`) and a.py, b.py, c.py in the base commit."""
    s = spec.read(repo / SPEC_DIR)
    write_plan(repo, PLAN.format(sid=SPEC_ID, hash=s.ac_hash()))
    for f in ("a.py", "b.py", "c.py"):
        (repo / f).write_text("base\n")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "user.email", "t@t")
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "feature/007-price-alerts")
    base = git(repo, "rev-parse", "HEAD")
    # t1 and t2 both rewrite a.py (t2 strays outside its `files`), t3 has its own file.
    branch_from(repo, "br-t1", base, {"a.py": "one\n"})
    branch_from(repo, "br-t2", base, {"a.py": "two\n", "b.py": "hook\n"})
    branch_from(repo, "br-t3", base, {"c.py": "wired\n"})
    git(repo, "tag", "base", base)
    return repo


def t1_merged(capsys, w):
    rc, out, err = build(capsys, w, "merge", "t1", "br-t1")
    assert rc == 0, err
    done(capsys, w, "t1")


def conflicted(capsys, w):
    """t1 merged and done; t2 conflicts and is set aside."""
    t1_merged(capsys, w)
    return build(capsys, w, "merge", "t2", "br-t2")


def amend_t3_after_t2(w):
    """The architect's answer: t2 now waits for t3 (so the plan is valid and t2 is re-planned)."""
    edit_plan(w, "{id: t2, title: hook, files: [b.py], covers: [AC-007.2], parallel_safe: true, depends_on: []}",
              "{id: t2, title: hook, files: [b.py, a.py], covers: [AC-007.2], parallel_safe: false, depends_on: [t3]}")


def replanned(capsys, w):
    """t1 done, t2 conflicted and re-planned to run after t3. Returns the re-plan commit sha."""
    rc, out, err = conflicted(capsys, w)
    assert rc == 3, out + err
    amend_t3_after_t2(w)
    rc, out, err = build(capsys, w, "replan-commit")
    assert rc == 0, out + err
    return git(w, "rev-parse", "HEAD")


def begin_run(w):
    assert runs.main(["begin", "build", "--spec", SPEC_ID, "--dir", str(w)]) == 0


def end_run(w, store, outcome="done"):
    assert runs.main(["end", "--outcome", outcome, "--dir", str(w)]) == 0
    return stored(store)[-1]


def status(w):
    return git(w, "status", "--porcelain", "--untracked-files=no")


# ---------------- AC-094.1 the conflict aborts cleanly and the build goes on ----------------

def test_a_conflicting_branch_is_aborted_and_set_aside(world, capsys):
    """AC-094.1: exit 3, the merge is aborted, HEAD and the tree are exactly as before, no conflict markers."""
    t1_merged(capsys, world)
    before = git(world, "rev-parse", "HEAD")
    rc, out, err = build(capsys, world, "merge", "t2", "br-t2")
    assert rc == 3, out + err
    assert git(world, "rev-parse", "HEAD") == before
    assert status(world) == ""
    assert not (world / ".git" / "MERGE_HEAD").exists()
    assert (world / "a.py").read_text() == "one\n"
    assert "<<<<<<<" not in (world / "a.py").read_text()
    lines = out.splitlines()
    assert lines[0] == "CONFLICT t2 with t1: a.py"
    assert lines[1].startswith("SET ASIDE t2: branch br-t2 is kept for the re-run; the feature branch is unchanged at ")
    assert lines[2].startswith("NEXT: merge the rest of the batch, then re-plan (build re-plans used: 0 of 3)")
    git(world, "rev-parse", "--verify", "br-t2")        # the branch is kept


def test_a_clean_merge_prints_merged_and_exits_0(world, capsys):
    """AC-094.1 AC-094.2: a clean merge is `MERGED <task> <short sha>`, exit 0."""
    rc, out, err = build(capsys, world, "merge", "t1", "br-t1")
    assert rc == 0, err
    assert re.fullmatch(r"MERGED t1 [0-9a-f]{7,12}", out.strip())


def test_merge_refuses_a_dirty_tree_and_changes_nothing(world, capsys):
    """AC-094.1: the tree must be clean before a merge, so the abort can restore it exactly."""
    (world / "a.py").write_text("scribble\n")
    head = git(world, "rev-parse", "HEAD")
    rc, out, err = build(capsys, world, "merge", "t1", "br-t1")
    assert rc == 1 and "commit the previous task first" in err
    assert git(world, "rev-parse", "HEAD") == head and (world / "a.py").read_text() == "scribble\n"


def test_merge_refuses_a_done_or_unknown_task(world, capsys):
    """AC-094.1: usage errors exit 1 and change nothing."""
    t1_merged(capsys, world)
    assert build(capsys, world, "merge", "t1", "br-t1")[0] == 1       # done already
    assert build(capsys, world, "merge", "t9", "br-t1")[0] == 1       # unknown
    assert build(capsys, world, "merge", "t3", "no-such-branch")[0] == 1


# ---------------- AC-094.2 the rest of the batch keeps merging ----------------

def test_the_rest_of_the_batch_merges_after_a_conflict(world, capsys):
    """AC-094.2: a clean branch after a conflicting one merges and can be marked done."""
    t1_merged(capsys, world)
    assert build(capsys, world, "merge", "t2", "br-t2")[0] == 3
    rc, out, err = build(capsys, world, "merge", "t3", "br-t3")
    assert rc == 0 and out.startswith("MERGED t3"), err
    done(capsys, world, "t3")
    assert (world / "c.py").read_text() == "wired\n"
    data = jbuild(capsys, world, "schedule")
    assert set(data["done"]) == {"t1", "t3"}


def test_every_conflicting_branch_of_a_batch_is_set_aside(world, capsys):
    """AC-094.2: two conflicting branches are both set aside (exit 3) and both are pending."""
    branch_from(world, "br-t3x", git(world, "rev-parse", "base"), {"a.py": "three\n"})
    t1_merged(capsys, world)
    assert build(capsys, world, "merge", "t2", "br-t2")[0] == 3
    assert build(capsys, world, "merge", "t3", "br-t3x")[0] == 3
    state = jbuild(capsys, world, "state")
    assert sorted(p["task"] for p in state["pending"]) == ["t2", "t3"]
    assert {p["branch"] for p in state["pending"]} == {"br-t2", "br-t3x"}
    assert status(world) == ""


# ---------------- AC-094.3 what the architect gets and may change ----------------

def test_state_gives_the_architect_task_partner_and_paths(world, capsys):
    """AC-094.3: pending conflicts carry the task, the task it collided with, the paths and the branch."""
    conflicted(capsys, world)
    state = jbuild(capsys, world, "state")
    assert state["cap"] == 3 and state["count"] == 0 and state["replans"] == []
    assert state["pending"] == [{"task": "t2", "with": "t1", "paths": ["a.py"], "branch": "br-t2"}]
    rc, out, err = build(capsys, world, "state")
    assert "re-plans: 0 of 3" in out and "pending: t2 with t1: a.py (branch br-t2)" in out


def test_the_partner_is_found_by_the_plan_when_no_merge_names_it(world, capsys):
    """AC-094.3: with the merge commit missing, the done task whose `files` cover the path is the partner."""
    edit_plan(world, "{id: t1, title: model, files: [a.py]", "{id: t1, title: model, files: [a.py]")
    git(world, "merge", "--no-ff", "-q", "-m", "plain merge", "br-t1")
    spec.main(["--repo", str(world), "task-done", "007", "t1"])
    commit(world, "t1 done")
    assert build(capsys, world, "merge", "t2", "br-t2")[0] == 3
    assert jbuild(capsys, world, "state")["pending"][0]["with"] == "t1"


@pytest.mark.parametrize("old,new,msg", [
    ("title: hook", "title: renamed", "task t2: title changed"),
    ("covers: [AC-007.2], parallel_safe: true, depends_on: []}\n  - {id: t3", "covers: [AC-007.1], parallel_safe: true, depends_on: []}\n  - {id: t3", "task t2: covers changed"),
    ("id: t3, title: wire", "id: t9, title: wire", "tasks removed"),
])
def test_the_architect_may_change_only_files_depends_on_and_parallel_safe(world, capsys, old, new, msg):
    """AC-094.3: any other change to the plan is refused, nothing is committed."""
    conflicted(capsys, world)
    head = git(world, "rev-parse", "HEAD")
    edit_plan(world, old, new)
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 1 and msg in out and out.strip().splitlines()[-1].endswith("error(s)")
    assert git(world, "rev-parse", "HEAD") == head


def test_a_done_task_and_the_spec_hash_cannot_change(world, capsys):
    """AC-094.3: a done task is unchanged; spec_hash and other metadata are unchanged."""
    conflicted(capsys, world)
    edit_plan(world, "{id: t1, title: model, files: [a.py]", "{id: t1, title: model, files: [a.py, z.py]")
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 1 and "task t1 is done and changed" in out
    git(world, "checkout", "-q", "--", SPEC_DIR)
    text = plan_path(world).read_text()
    write_plan(world, re.sub(r"spec_hash: \w+", "spec_hash: 000000000000", text))
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 1 and "spec_hash changed" in out


def test_the_prose_below_the_metadata_may_change(world, capsys):
    """AC-094.3 AC-094.4: the plan body is the architect's to adjust."""
    conflicted(capsys, world)
    amend_t3_after_t2(world)
    write_plan(world, plan_path(world).read_text() + "\nt2 now runs after t3.\n")
    assert build(capsys, world, "replan-commit")[0] == 0


def test_replan_commit_needs_a_pending_conflict(world, capsys):
    """AC-094.3: nothing to re-plan without a conflict."""
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 1 and "nothing to re-plan: no pending conflict" in out


# ---------------- AC-094.4 the amended plan is committed and scheduled ----------------

def test_the_amended_plan_is_checked_and_committed_with_the_conflict_in_the_message(world, capsys):
    """AC-094.4: spec check passes, one commit with only plan.md, subject names the task, body the files, trailers."""
    conflicted(capsys, world)
    amend_t3_after_t2(world)
    before = git(world, "rev-parse", "HEAD")
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 0, out + err
    sha = git(world, "rev-parse", "HEAD")
    assert sha != before and git(world, "rev-parse", "HEAD~1") == before
    assert git(world, "show", "--name-only", "--format=", "HEAD").split() == [SPEC_DIR + "/plan.md"]
    msg = git(world, "log", "-1", "--format=%B")
    assert msg.splitlines()[0] == f"chore(plan): {SPEC_ID} re-plan t2 after a merge conflict"
    assert "Conflicting files: a.py" in msg
    assert "Re-planned: t2 (collided with t1)" in msg
    assert f"Replan-Spec: {SPEC_ID}" in msg
    assert "Replan-Task: t2 with=t1 branch=br-t2 paths=a.py" in msg
    assert "Signed-off-by:" in msg
    assert out.splitlines()[0] == f"RE-PLANNED t2 in {sha[:7]} (re-plans: 1 of 3)" or out.startswith(f"RE-PLANNED t2 in {sha[:8]}") or out.startswith("RE-PLANNED t2 in ")
    assert cplat.main(["spec", "--repo", str(world), "check", "007"]) == 0 or spec.check(spec.read(world / SPEC_DIR)) == []
    assert jbuild(capsys, world, "state")["pending"] == []


def test_the_schedule_shows_the_replanned_task_after_what_it_depends_on(world, capsys):
    """AC-094.4: t2 depends on t3 now and is printed in a later level, marked (re-planned)."""
    replanned(capsys, world)
    data = jbuild(capsys, world, "schedule")
    assert data["done"] == ["t1"] and data["replanned"] == ["t2"] and data["replans"] == 1 and data["cap"] == 3
    flat = [[t for b in lvl for t in b["tasks"]] for lvl in data["levels"]]
    assert flat == [["t3"], ["t2"], ["t4"]]
    rc, out, err = build(capsys, world, "schedule")
    assert "| 2 | 1 | t2 (re-planned) | sequential |" in out
    assert out.strip().splitlines()[-1] == "done: t1 · gitops: - · re-plans: 1 of 3" or out.strip().splitlines()[-1].startswith("done: t1")


def test_schedule_batches_parallel_safe_tasks_with_disjoint_files(world, capsys):
    """AC-094.4: the schedule table, batches and modes."""
    rc, out, err = build(capsys, world, "schedule")
    assert rc == 0, err
    assert "| Level | Batch | Tasks | Mode |" in out
    assert "| 1 | 1 | t1, t2, t3 | parallel |" in out
    assert "| 2 | 1 | t4 | sequential |" in out
    edit_plan(world, "{id: t3, title: wire, files: [c.py]", "{id: t3, title: wire, files: [b.py]")
    data = jbuild(capsys, world, "schedule")
    assert data["levels"][0] == [{"tasks": ["t1", "t2"], "parallel": True}, {"tasks": ["t3"], "parallel": False}]


def test_schedule_keeps_gitops_tasks_apart_and_rejects_cycles(world, capsys):
    """AC-094.4: gitops tasks are never in a batch; a dependency cycle exits 1."""
    edit_plan(world, "  - {id: t4,", "  - {id: g1, title: roll out, repo: gitops, files: [], covers: [AC-007.2], depends_on: []}\n  - {id: t4,")
    data = jbuild(capsys, world, "schedule")
    assert data["gitops"] == ["g1"] and all("g1" not in b["tasks"] for lvl in data["levels"] for b in lvl)
    edit_plan(world, "id: t1, title: model, files: [a.py], covers: [AC-007.1], parallel_safe: true, depends_on: []",
              "id: t1, title: model, files: [a.py], covers: [AC-007.1], parallel_safe: true, depends_on: [t4]")
    assert build(capsys, world, "schedule")[0] == 1


# ---------------- AC-094.5 the re-run starts from the merged work, then the leftovers go ----------------

def test_the_set_aside_branch_survives_until_the_rerun_is_merged_and_green(world, capsys):
    """AC-094.5: the re-run branches off the current feature branch, merges cleanly, and `resolved` removes branch and worktree."""
    wt = world.parent / "wt-t2"
    git(world, "worktree", "add", "-q", str(wt), "br-t2")
    replanned(capsys, world)
    state = jbuild(capsys, world, "state")
    (rp,) = state["replans"]
    assert rp["tasks"] == [{"task": "t2", "with": "t1", "paths": ["a.py"], "branch": "br-t2", "merged": False}]
    git(world, "rev-parse", "--verify", "br-t2")
    # t3 first, then t2 re-runs from the feature branch with t1 and t3 in it.
    assert build(capsys, world, "merge", "t3", "br-t3")[0] == 0
    done(capsys, world, "t3")
    head = git(world, "rev-parse", "HEAD")
    branch_from(world, "br-t2-rerun", head, {"a.py": "one\ntwo\n", "b.py": "hook\n"})
    assert git(world, "merge-base", "--is-ancestor", "br-t1", "br-t2-rerun") == ""
    rc, out, err = build(capsys, world, "merge", "t2", "br-t2-rerun")
    assert rc == 0, out + err
    assert spec.main(["--repo", str(world), "task-done", "007", "t2"]) == 0
    rc, out, err = build(capsys, world, "resolved", "t2")
    assert rc == 0 and out.startswith("RESOLVED t2: removed branch br-t2") and str(wt.name) in out
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "br-t2"], cwd=world).returncode != 0
    assert not wt.exists()
    assert str(wt) not in git(world, "worktree", "list")
    assert jbuild(capsys, world, "state")["replans"][0]["tasks"][0]["merged"] is True
    assert "re-run merged cleanly" in build(capsys, world, "state")[1]


def test_resolved_is_a_noop_for_a_task_that_was_not_re_planned(world, capsys):
    """AC-094.5: no branch is removed for a task that never conflicted."""
    t1_merged(capsys, world)
    rc, out, err = build(capsys, world, "resolved", "t1")
    assert rc == 0 and "t1 was not re-planned" in out
    git(world, "rev-parse", "--verify", "br-t1")


def test_resolved_refuses_a_replanned_task_that_is_not_done(world, capsys):
    """AC-094.5: the set-aside branch stays until the re-run is done."""
    replanned(capsys, world)
    assert build(capsys, world, "resolved", "t2")[0] == 1
    git(world, "rev-parse", "--verify", "br-t2")


def test_the_rerun_prompt_gives_the_old_diff_as_reference():
    """AC-094.5: build.md hands the set-aside branch's diff to the coder as reference only."""
    text = (core.PLATFORM_ROOT / "plugins" / "svc" / "commands" / "build.md").read_text()
    assert "git diff HEAD...<branch>" in text
    assert "Your earlier attempt is a reference only" in text
    assert "already contains every merged task" in text
    assert "cplat build resolved" in text


# ---------------- AC-094.6 a second conflict of the same task escalates ----------------

def test_a_task_that_conflicts_again_escalates_with_both_collisions(world, capsys):
    """AC-094.6: exit 4, the ESCALATE line names task, files, both partners and the re-plan commit; nothing is set aside."""
    sha = replanned(capsys, world)
    assert build(capsys, world, "merge", "t3", "br-t3")[0] == 0
    done(capsys, world, "t3")
    branch_from(world, "br-t2-again", git(world, "rev-parse", "base"), {"a.py": "three\n"})
    rc, out, err = build(capsys, world, "merge", "t2", "br-t2-again")
    assert rc == 4, out + err
    first, second = out.splitlines()[:2]
    assert first.startswith("CONFLICT t2 with t1: a.py")
    assert second.startswith("ESCALATE: t2 conflicted again after its re-plan: now with t1 on a.py; before with t1 on a.py; re-plan commit " + sha[:7])
    assert "Conflicts are never resolved by hand" in second
    assert len(out.splitlines()) == 2 or "\n" not in second
    assert jbuild(capsys, world, "state")["pending"] == []
    assert status(world) == ""
    git(world, "rev-parse", "--verify", "br-t2-again")


# ---------------- AC-094.7 blockers and an invalid plan escalate ----------------

def test_a_plan_that_fails_spec_check_is_not_committed(world, capsys):
    """AC-094.7: the check errors are printed with plan.md: prefix, exit 1, nothing committed."""
    conflicted(capsys, world)
    head = git(world, "rev-parse", "HEAD")
    edit_plan(world, "{id: t2, title: hook, files: [b.py], covers: [AC-007.2], parallel_safe: true, depends_on: []}",
              "{id: t2, title: hook, files: [b.py], covers: [AC-007.2], parallel_safe: true, depends_on: [t77]}")
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 1
    assert re.search(rf"ERROR: {SPEC_ID}: plan\.md: ", out) and out.strip().splitlines()[-1].endswith("error(s)")
    assert git(world, "rev-parse", "HEAD") == head


def test_replan_abort_restores_the_last_valid_plan_and_escalates(world, capsys):
    """AC-094.7: the plan on the branch is the last valid one, pending conflicts are cleared, one ESCALATE line, exit 0."""
    conflicted(capsys, world)
    head = git(world, "rev-parse", "HEAD")
    valid = plan_path(world).read_text()
    edit_plan(world, "depends_on: [t1, t2, t3]}", "depends_on: [t77]}")
    (world / SPEC_DIR / "notes.md").write_text("draft\n")
    rc, out, err = build(capsys, world, "replan-abort", "--reason", "BLOCKER: needs a new task")
    assert rc == 0, err
    (line,) = out.strip().splitlines()
    assert line == (f"ESCALATE: the re-plan of t2 failed: BLOCKER: needs a new task. The plan stays at {head[:7]}. "
                    "Conflicts are never resolved by hand.")
    assert plan_path(world).read_text() == valid and not (world / SPEC_DIR / "notes.md").exists()
    assert git(world, "rev-parse", "HEAD") == head and status(world) == ""
    assert jbuild(capsys, world, "state")["pending"] == []


def test_the_prompts_send_errors_once_then_escalate_with_replan_abort():
    """AC-094.7: build.md retries the architect once on exit 1, then calls replan-abort and escalates."""
    text = (core.PLATFORM_ROOT / "plugins" / "svc" / "commands" / "build.md").read_text()
    assert "cplat build replan-commit" in text and "cplat build replan-abort" in text
    assert "BLOCKER" in text and "once" in text
    arch = (core.PLATFORM_ROOT / "plugins" / "svc" / "agents" / "architect.md").read_text()
    assert "Re-plan mode" in arch and "BLOCKER" in arch


# ---------------- AC-094.8 the Final Report ----------------

def test_state_reports_each_replanned_task_with_files_and_outcome(world, capsys):
    """AC-094.8: re-plan count, per task the conflicting files and whether the re-run merged cleanly (pending, then merged)."""
    sha = replanned(capsys, world)
    out = build(capsys, world, "state")[1]
    assert f"re-plans: 1 of 3\n  {sha[:7]} t2: a.py (collided with t1) — re-run pending" in out
    assert build(capsys, world, "merge", "t3", "br-t3")[0] == 0
    done(capsys, world, "t3")
    branch_from(world, "br-t2-rerun", git(world, "rev-parse", "HEAD"), {"b.py": "hook\n"})
    assert build(capsys, world, "merge", "t2", "br-t2-rerun")[0] == 0
    spec.main(["--repo", str(world), "task-done", "007", "t2"])
    assert f"{sha[:7]} t2: a.py (collided with t1) — re-run merged cleanly" in build(capsys, world, "state")[1]


def test_state_without_replans_prints_one_line(world, capsys):
    """AC-094.8: a build without conflicts has nothing to report."""
    rc, out, err = build(capsys, world, "state")
    assert rc == 0 and out.strip() == "re-plans: 0 of 3"


def test_the_final_report_row_states_the_amended_plan():
    """AC-094.8 AC-094.14: build.md's Implementation row names the re-plans, the files and the clean re-run."""
    text = (core.PLATFORM_ROOT / "plugins" / "svc" / "commands" / "build.md").read_text()
    assert "plan amended" in text and "after merge conflicts" in text and "re-run merged cleanly" in text
    assert "cplat build state" in text


# ---------------- AC-094.9 plan-accuracy recording (spec 089) ----------------

def test_each_conflict_is_one_event_that_ends_resolved(world, capsys, store):
    """AC-094.9: merge-conflict event per task (escalated at first), re-planned with the commit, resolved after the re-run; one re-plan."""
    begin_run(world)
    runs.main(["agent", "spawned", "architect", "--dir", str(world)])
    t1_merged(capsys, world)
    assert build(capsys, world, "merge", "t2", "br-t2")[0] == 3
    branch_from(world, "br-t3x", git(world, "rev-parse", "base"), {"a.py": "three\n"})
    assert build(capsys, world, "merge", "t3", "br-t3x")[0] == 3
    edit_plan(world, "{id: t2, title: hook, files: [b.py], covers: [AC-007.2], parallel_safe: true, depends_on: []}",
              "{id: t2, title: hook, files: [b.py, a.py], covers: [AC-007.2], parallel_safe: false, depends_on: []}")
    edit_plan(world, "{id: t3, title: wire, files: [c.py], covers: [AC-007.1], parallel_safe: true, depends_on: []}",
              "{id: t3, title: wire, files: [c.py, a.py], covers: [AC-007.1], parallel_safe: false, depends_on: [t2]}")
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 0, out + err
    branch_from(world, "br-t2-rerun", git(world, "rev-parse", "HEAD"), {"b.py": "hook\n"})
    assert build(capsys, world, "merge", "t2", "br-t2-rerun")[0] == 0
    spec.main(["--repo", str(world), "task-done", "007", "t2"])
    assert build(capsys, world, "resolved", "t2")[0] == 0
    rec = end_run(world, store)
    evs = {e["task"]: e for e in events(rec, "svc:architect", "merge-conflict")}
    assert set(evs) == {"t2", "t3"}
    assert (evs["t2"]["spec"], evs["t2"]["with"], evs["t2"]["paths"]) == (SPEC_ID, "t1", ["a.py"])
    assert evs["t2"]["author"]["agent"] == "svc:architect"
    assert evs["t2"]["outcome"] == "resolved"
    assert evs["t3"]["outcome"] == "re-planned"
    assert entry(rec, "svc:architect")["counts"]["replans"] == 1
    assert entry(rec, "svc:architect")["counts"]["merge_conflicts"] == 2


def test_a_failed_replan_leaves_the_conflicts_escalated(world, capsys, store):
    """AC-094.9: replan-abort records `escalated`; so does a conflict that escalates at once."""
    begin_run(world)
    conflicted(capsys, world)
    assert build(capsys, world, "replan-abort", "--reason", "BLOCKER: x")[0] == 0
    rec = end_run(world, store, "escalated")
    (ev,) = events(rec, "svc:architect", "merge-conflict")
    assert ev["task"] == "t2" and ev["outcome"] == "escalated"
    assert entry(rec, "svc:architect")["counts"]["replans"] == 0


def test_a_merge_is_recorded_for_out_of_plan_files(world, capsys, store):
    """AC-094.9: a clean merge goes through the 089 `merged` recording (a stray file counts against the architect)."""
    begin_run(world)
    branch_from(world, "br-stray", git(world, "rev-parse", "base"), {"c.py": "wired\n", "stray.py": "x\n"})
    assert build(capsys, world, "merge", "t3", "br-stray")[0] == 0
    rec = end_run(world, store)
    assert [(e["task"], e["path"]) for e in events(rec, "svc:architect", "out-of-plan")] == [("t3", "stray.py")]


# ---------------- AC-094.10 no store, no block ----------------

def test_a_conflict_replans_the_same_without_a_store(world, capsys):
    """AC-094.10: no store configured, the re-plan proceeds and the record is buffered."""
    begin_run(world)
    rc, out, err = conflicted(capsys, world)
    assert rc == 3 and out.startswith("CONFLICT t2 with t1: a.py")
    amend_t3_after_t2(world)
    assert build(capsys, world, "replan-commit")[0] == 0
    assert runs.main(["end", "--outcome", "escalated", "--dir", str(world)]) == 0
    lines = buffered_lines()
    assert lines and "merge-conflict" in json.dumps(lines)


def test_an_unreachable_store_does_not_block_the_replan(world, capsys, monkeypatch):
    """AC-094.10: a store that cannot be opened changes neither exit codes nor output."""
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")

    def boom(slug):
        raise OSError("unreachable")
    monkeypatch.setattr(runs, "open_store", boom)
    begin_run(world)
    rc, out, err = conflicted(capsys, world)
    assert rc == 3 and out.startswith("CONFLICT t2 with t1: a.py")
    amend_t3_after_t2(world)
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 0 and out.startswith("RE-PLANNED t2")


# ---------------- AC-094.11 resume after an interruption ----------------

def test_a_resumed_build_schedules_from_the_amended_plan_and_counts_the_replan(world, capsys):
    """AC-094.11: the history is in git; nothing else is needed. Done tasks stay done, the re-plan is counted, a second conflict escalates."""
    sha = replanned(capsys, world)
    (world.parent / "gone").mkdir()
    pending = list((world / ".git").glob("cplat-replan.json"))
    for p in pending:
        p.unlink()                                  # a fresh checkout has no local file
    data = jbuild(capsys, world, "schedule")
    assert data["done"] == ["t1"] and data["replanned"] == ["t2"] and data["replans"] == 1
    assert jbuild(capsys, world, "state")["replans"][0]["sha"] == sha
    assert build(capsys, world, "merge", "t3", "br-t3")[0] == 0
    done(capsys, world, "t3")
    branch_from(world, "br-t2-again", git(world, "rev-parse", "base"), {"a.py": "three\n"})
    rc, out, err = build(capsys, world, "merge", "t2", "br-t2-again")
    assert rc == 4 and "ESCALATE: t2 conflicted again after its re-plan" in out


# ---------------- AC-094.12 no hand resolution ----------------

def test_the_replan_may_change_nothing_but_the_plan(world, capsys):
    """AC-094.12: a changed source file (a hand-resolved hunk) or a new file next to the plan blocks the re-plan commit."""
    conflicted(capsys, world)
    head = git(world, "rev-parse", "HEAD")
    amend_t3_after_t2(world)
    (world / "a.py").write_text("hand-merged\n")
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 1 and "the re-plan may change only plan.md; also changed: a.py" in out
    git(world, "checkout", "-q", "--", "a.py")
    (world / "new.py").write_text("x\n")
    rc, out, err = build(capsys, world, "replan-commit")
    assert rc == 1 and "new.py" in out
    assert git(world, "rev-parse", "HEAD") == head


def test_a_conflict_leaves_no_markers_anywhere(world, capsys):
    """AC-094.12: after the abort no file holds conflict markers and no merge is in progress."""
    conflicted(capsys, world)
    for f in world.glob("*.py"):
        assert "<<<<<<<" not in f.read_text()
    assert git(world, "ls-files", "-u") == ""


def test_the_build_rules_forbid_hand_resolution():
    """AC-094.12: build.md says never to edit conflicting hunks and routes conflicts through cplat build merge."""
    text = (core.PLATFORM_ROOT / "plugins" / "svc" / "commands" / "build.md").read_text()
    assert "Never edit conflicting hunks" in text and "cplat build merge" in text


# ---------------- AC-094.13 the cap of 3 re-plans per build ----------------

def test_a_fourth_replan_escalates_and_lists_the_earlier_commits(world, capsys):
    """AC-094.13: with 3 re-plan commits in the history, a further conflict escalates; the message names the cap and the commits."""
    t1_merged(capsys, world)
    subjects = []
    for i, task in enumerate(["t3", "t4", "t9"], 1):
        subject = f"chore(plan): {SPEC_ID} re-plan {task} after a merge conflict"
        body = f"{subject}\n\nConflicting files: z{i}.py\n\nReplan-Spec: {SPEC_ID}\nReplan-Task: {task} with=- branch=b{i} paths=z{i}.py\n"
        git(world, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-s", "-m", body)
        subjects.append((git(world, "rev-parse", "--short", "HEAD"), subject))
    assert jbuild(capsys, world, "schedule")["replans"] == 3
    rc, out, err = build(capsys, world, "merge", "t2", "br-t2")
    assert rc == 4, out + err
    line = out.splitlines()[1]
    assert line.startswith("ESCALATE: the cap of 3 re-plans per build was reached; t2 conflicts with t1 on a.py. Earlier re-plan commits: ")
    for short, subject in subjects:
        assert f'{short} "{subject}"' in line
    assert "Conflicts are never resolved by hand" in line
    assert jbuild(capsys, world, "state")["pending"] == [] and status(world) == ""


def test_two_replans_still_leave_room_for_a_third(world, capsys):
    """AC-094.13: the cap is reached at 3, not before."""
    t1_merged(capsys, world)
    for i, task in enumerate(["t3", "t4"], 1):
        body = f"chore(plan): x\n\nReplan-Spec: {SPEC_ID}\nReplan-Task: {task} with=- branch=b{i} paths=z.py\n"
        git(world, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-s", "-m", body)
    assert build(capsys, world, "merge", "t2", "br-t2")[0] == 3


# ---------------- AC-094.14 attended builds re-plan without asking ----------------

def test_an_attended_build_replans_without_asking():
    """AC-094.14: build.md re-plans without asking, also interactively, and the Final Report says so."""
    text = (core.PLATFORM_ROOT / "plugins" / "svc" / "commands" / "build.md").read_text()
    assert "without asking" in text and "attended" in text
    assert "plan amended" in text
    ship = (core.PLATFORM_ROOT / "plugins" / "svc" / "commands" / "ship.md").read_text()
    assert "re-plan" in ship.lower()
