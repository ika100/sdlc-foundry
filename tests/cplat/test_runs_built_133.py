"""Spec 133 (#338): build PRs show how they were built (`cplat platform runs report --pr`, `cplat pr open`)."""
import re
import subprocess

import pytest

import budget
import core
import cplat
import pr as prmod
import pr_open
import runs
import structure
from test_pr_open import Fake, allow

ROOT = core.PLATFORM_ROOT
START, END = "<!-- cplat:how-built -->", "<!-- /cplat:how-built -->"
SPEC_DIR = "docs/specs/133-built-thing"
HEADINGS = ["How it ran", "User decisions", "Hand-backs and fix rounds", "Deviations the reviewer accepted"]

VERIFICATION = """# Verification — 133 Built thing

**Result:** pass

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-133.1 | met | `t` | `x.py:1` | |

## Deviations from the plan

1. **`tests/helper.py` is in no task's `files`.** It is test support. Acceptable.
2. **t5 changed the order of the render check.** The plan says otherwise. Not acceptable as is: restore it.
- **The `_wait_e2e` pre-poll** waits before the first poll. Accepted: it avoids a false no-checks.
   - a nested detail that is acceptable but not an item of its own

## Contract

Matches design.md, acceptable.
"""

SPEC = """---
spec_id: 133-built-thing
title: Built thing
status: approved
---

# 133 — Built thing

## Open questions

- ~~First?~~ Answered (recommended default, 2026-11-03): yes.
- ~~Second?~~ Answered: no.
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "app"
    (r / SPEC_DIR).mkdir(parents=True)
    (r / SPEC_DIR / "spec.md").write_text(SPEC)
    (r / SPEC_DIR / "verification.md").write_text(VERIFICATION)
    _git(r.parent, "init", "-q", str(r))
    return r


def agent(name, *events):
    return {"id": f"{name}|platform|opus", "agent": name, "shape": "platform", "model": "opus", "model_id": None,
            "counts": {}, "events": [dict(ev, id=f"{ev['kind']}:{i + 1}") for i, ev in enumerate(events)]}


FULL = {
    "agents": [
        agent("svc:architect",
              {"kind": "merge-conflict", "task": "t4", "with": "t2", "paths": ["a.py"], "outcome": "re-planned"},
              {"kind": "re-plan", "task": "t4", "conflict": "merge-conflict:1"}),
        agent("svc:coder",
              {"kind": "fix-round", "cause": "lint/type", "task": "t3"},
              {"kind": "red-ci", "check": "e2e", "checks": ["e2e", "smoke"]},
              {"kind": "finding", "criterion": "AC-133.4", "task": None, "severity": "not met", "pass": "first",
               "cycle": 1, "tasks": ["t1"]},
              {"kind": "refused-test-diff", "file": "tests/test_x.py", "reason": "assertion changed", "task": "t3"}),
        agent("svc:tester", {"kind": "tester", "reason": "untraced", "criterion": "AC-133.2", "test": None}),
    ],
    "replans": [{"id": "re-plan:1", "spec": "133", "task": "t4"}],
    "execution": {"mode": "sequential", "reason": "worktree base is 1a2b3c4, not the feature head"},
    "ci_rounds": 2,
    "reruns": [{"check": "e2e", "reason": "transient"}],
    "gates": {"acceptance": "passed", "security": "passed"},
}


def make_run(spec="133", kind="build", **sections):
    rid = runs.start(kind, repo="acme/app", spec=spec)
    assert rid
    runs.mutate(rid, lambda rec: rec.update(sections))
    return rid


def report(rid, repo, capsys, *extra):
    code = cplat.main(["platform", "runs", "report", "--pr", rid, "--dir", str(repo), *extra])
    out = capsys.readouterr()
    return code, out.out, out.err


def part(block, heading):
    """The lines under one `#### heading` of the block."""
    m = re.search(rf"^#### {re.escape(heading)}\n(.*?)(?=^#### |^</details>)", block, re.M | re.S)
    assert m, block
    return m.group(1)


# ---------------- AC-133.1 ----------------

def test_report_pr_prints_the_marked_collapsed_block_with_four_headings_in_order_ac_133_1(repo, capsys, monkeypatch):
    """AC-133.1: exit 0, markers, <details>, the four headings in order; no run store needed."""
    monkeypatch.delenv("CPLAT_RUNS_REPO", raising=False)
    rid = make_run(**FULL)
    code, out, _ = report(rid, repo, capsys)
    assert code == 0
    lines = out.strip().splitlines()
    assert lines[0] == START and lines[1] == "<details><summary>How this was built</summary>"
    assert lines[-2:] == ["</details>", END]
    found = [ln[5:] for ln in lines if ln.startswith("#### ")]
    assert found == HEADINGS


def test_report_pr_reads_a_finished_run_from_the_local_buffer_ac_133_1(repo, capsys, monkeypatch):
    """AC-133.1: a finished run that stayed in the local buffer (CPLAT_RUNS_REPO unset) is found there."""
    monkeypatch.delenv("CPLAT_RUNS_REPO", raising=False)
    rid = make_run(**FULL)
    runs.finish(rid, "done")
    capsys.readouterr()
    assert runs.active(rid) is None
    code, out, _ = report(rid, repo, capsys)
    assert code == 0 and START in out and rid in out
    assert "t3 → svc:coder: lint/type" in out


# ---------------- AC-133.2 ----------------

def test_an_unknown_run_exits_1_with_nothing_on_stdout_ac_133_2(repo, capsys):
    """AC-133.2: exit 1, empty stdout, the run id and a hint on stderr."""
    code, out, err = report("20260101T000000Z-deadbeef", repo, capsys)
    assert code == 1 and out == ""
    assert "20260101T000000Z-deadbeef" in err and "fix:" in err


@pytest.mark.parametrize("extra", [["--agents"], ["--benchmarks"], ["--json"], ["--since", "7"], ["--repo", "acme/app"]])
def test_pr_cannot_be_combined_with_the_aggregate_options_ac_133_2(repo, capsys, extra):
    """AC-133.2: --pr with --agents, --benchmarks, --json, --since or --repo is refused with exit 1."""
    rid = make_run(**FULL)
    code, out, err = report(rid, repo, capsys, *extra)
    assert code == 1 and out == "" and "--pr" in err


# ---------------- AC-133.3 ----------------

def test_how_it_ran_names_run_kind_mode_replans_ci_gates_and_agents_ac_133_3(repo, capsys):
    """AC-133.3: run id and kind, execution mode with reason, re-plans, CI rounds, reruns, gates, agents."""
    rid = make_run(**FULL)
    _, out, _ = report(rid, repo, capsys)
    ran = part(out, "How it ran")
    assert f"run {rid} (build)" in ran
    assert "tasks: sequentially (worktree base is 1a2b3c4, not the feature head)" in ran
    assert "re-plans: 1" in ran and "CI rounds: 2" in ran and "reruns: 1" in ran
    assert "acceptance passed" in ran and "security passed" in ran
    assert "agents: svc:architect, svc:coder, svc:tester" in ran


def test_an_unrecorded_execution_mode_says_not_recorded_ac_133_3(repo, capsys):
    """AC-133.3: without an `execution` record the mode is `not recorded`."""
    rid = make_run()
    _, out, _ = report(rid, repo, capsys)
    assert "tasks: not recorded" in part(out, "How it ran")


def test_wall_time_sums_the_runs_it_resumes_ac_133_3(repo, capsys):
    """AC-133.3: wall time from started_at to ended_at, summed over the resumed local runs, with the run count."""
    first = make_run(started_at="2026-11-03T08:00:00Z")
    runs.mutate(first, lambda r: r.update(started_at="2026-11-03T08:00:00Z"))
    runs.finish(first, "escalated", escalation={"reason": "which database?", "cause": "decision"})
    capsys.readouterr()

    def fix(r):
        r.update(started_at="2026-11-03T09:00:00Z", ended_at="2026-11-03T09:30:00Z", resumes=first)
    second = make_run()
    runs.mutate(second, fix)
    buffered = [i for i in runs._read_buffer() if i["run_id"] == first][0]
    buffered["ended_at"] = "2026-11-03T08:45:00Z"
    with runs._locked():
        runs._buffer_add(buffered)
    _, out, _ = report(second, repo, capsys)
    assert "wall time 1h 15m over 2 runs" in part(out, "How it ran")


# ---------------- AC-133.4 ----------------

def test_budget_shows_used_against_each_limit_ac_133_4(repo, capsys, monkeypatch):
    """AC-133.4: minutes, invocations, reruns and cost used against the limit; `off` for no limit."""
    monkeypatch.setattr(budget, "_cost_of", lambda rec: 12.4)
    rid = make_run(**FULL)
    budget.open_root(rid, "acme/app#133", options=["minutes=off"], repo=repo)
    _, out, _ = report(rid, repo, capsys)
    line = [ln for ln in part(out, "How it ran").splitlines() if "budget:" in ln][0]
    assert re.search(r"minutes [\d.]+ of off", line)
    assert "invocations 0 of 60" in line or re.search(r"invocations \d+ of 60", line)
    assert "reruns 0 of 6" in line and "cost $12.40 of $15" in line


def test_an_unreadable_cost_says_unknown_ac_133_4(repo, capsys, monkeypatch):
    """AC-133.4: a cost that cannot be read is `unknown`."""
    monkeypatch.setattr(budget, "_cost_of", lambda rec: budget.UNKNOWN)
    rid = make_run()
    budget.open_root(rid, "acme/app#133", repo=repo)
    _, out, _ = report(rid, repo, capsys)
    assert "cost unknown of $15" in part(out, "How it ran")


def test_without_a_ledger_the_budget_is_not_recorded_ac_133_4(repo, capsys):
    """AC-133.4: no ledger → `budget: not recorded`."""
    rid = make_run()
    _, out, _ = report(rid, repo, capsys)
    assert "budget: not recorded" in part(out, "How it ran")


# ---------------- AC-133.5 ----------------

def test_user_decisions_list_budget_changes_escalations_refusals_and_answers_ac_133_5(repo, capsys, monkeypatch):
    """AC-133.5: budget change, decision escalations of resumed runs, test-diff refusal, #324 line, answered questions."""
    monkeypatch.setattr(budget, "_cost_of", lambda rec: 0.0)
    first = make_run()
    budget.open_root(first, "acme/app#133", repo=repo)
    runs.finish(first, "escalated", escalation={"reason": "budget exhausted: cost", "cause": "decision"})
    second = make_run(**FULL)
    runs.mutate(second, lambda r: r.update(resumes=first))
    budget.open_root(second, "acme/app#133", options=["cost=30"], repo=repo)
    capsys.readouterr()
    _, out, _ = report(second, repo, capsys)
    dec = part(out, "User decisions")
    assert "budget cost raised from 15 to 30" in dec
    assert f"stopped for a decision: budget exhausted: cost (run {first})" in dec
    assert "test-diff refused `tests/test_x.py` (task t3): assertion changed" in dec
    assert "user-approved test changes: not recorded (#324)" in dec
    assert "open questions answered in spec.md: 2" in dec


def test_approved_test_diffs_are_listed_when_recorded_ac_133_5(repo, capsys):
    """AC-133.5: the #324 hook: an `approved_test_diffs` section is shown instead of the not-recorded line."""
    rid = make_run(approved_test_diffs=[{"file": "tests/test_y.py", "task": "t2", "reason": "pin relaxed"}])
    _, out, _ = report(rid, repo, capsys)
    dec = part(out, "User decisions")
    assert "test change approved `tests/test_y.py` (task t2): pin relaxed" in dec
    assert "#324" not in dec


def test_no_decisions_says_none_recorded_ac_133_5(tmp_path, capsys):
    """AC-133.5: nothing recorded (an empty #324 section, no spec) → `none recorded`."""
    _git(tmp_path, "init", "-q")
    rid = make_run(spec=None, approved_test_diffs=[])
    _, out, _ = report(rid, tmp_path, capsys)
    assert part(out, "User decisions").strip() == "- none recorded"


# ---------------- AC-133.6 ----------------

def test_hand_backs_list_every_kind_of_event_ac_133_6(repo, capsys):
    """AC-133.6: fix round, red CI, finding, tester hand-back, merge conflict and re-plan, each with its agent."""
    rid = make_run(**FULL)
    _, out, _ = report(rid, repo, capsys)
    hb = part(out, "Hand-backs and fix rounds")
    assert "t3 → svc:coder: lint/type" in hb
    assert "red CI: e2e, smoke → svc:coder" in hb
    assert "finding AC-133.4 (not met, cycle 1) → svc:coder" in hb
    assert "tester: AC-133.2 untraced" in hb
    assert "merge conflict t4 with t2: re-planned" in hb
    assert "re-plan t4 → svc:architect" in hb


def test_no_hand_backs_says_none_ac_133_6(repo, capsys):
    """AC-133.6: none recorded → `none`."""
    rid = make_run()
    _, out, _ = report(rid, repo, capsys)
    assert part(out, "Hand-backs and fix rounds").strip() == "- none"


# ---------------- AC-133.7 ----------------

def test_only_accepted_deviations_are_listed_by_their_first_sentence_ac_133_7(repo, capsys):
    """AC-133.7: acceptable/accepted top-level items, first sentence; `not acceptable` and nested items left out."""
    rid = make_run()
    _, out, _ = report(rid, repo, capsys)
    dev = part(out, "Deviations the reviewer accepted")
    items = [ln for ln in dev.splitlines() if ln.startswith("- ")]
    assert items == ["- `tests/helper.py` is in no task's `files`.", "- The `_wait_e2e` pre-poll waits before the first poll."]


def test_long_deviations_are_cut_to_200_characters_ac_133_7(repo, capsys):
    """AC-133.7: at most 200 characters per item."""
    long = "x" * 400
    (repo / SPEC_DIR / "verification.md").write_text(f"## Deviations from the plan\n\n- {long} acceptable\n")
    rid = make_run()
    _, out, _ = report(rid, repo, capsys)
    item = [ln for ln in part(out, "Deviations the reviewer accepted").splitlines() if ln.startswith("- ")][0]
    assert len(item[2:]) <= 200


def test_deviations_without_items_or_file_ac_133_7(repo, capsys):
    """AC-133.7: `none listed` without accepted items, `no verification.md yet` without the file."""
    (repo / SPEC_DIR / "verification.md").write_text("# Verification\n\n## Deviations from the plan\n\nNone.\n")
    rid = make_run()
    _, out, _ = report(rid, repo, capsys)
    assert part(out, "Deviations the reviewer accepted").strip() == "- none listed"
    (repo / SPEC_DIR / "verification.md").unlink()
    _, out, _ = report(rid, repo, capsys)
    assert part(out, "Deviations the reviewer accepted").strip() == "- no verification.md yet"


# ---------------- AC-133.8 ----------------

def test_values_are_redacted_and_lists_are_capped_ac_133_8(repo, capsys):
    """AC-133.8: tokens and e-mail addresses are redacted; at most 10 lines per list, then `… and <n> more`."""
    token = "ghp_" + "A1b2C3d4" * 5
    rounds = [{"kind": "fix-round", "cause": "test", "task": f"t{i}"} for i in range(13)]
    secret = {"kind": "refused-test-diff", "file": "tests/t.py", "reason": f"token {token} by dev@example.com", "task": "t1"}
    rid = make_run(agents=[agent("svc:coder", *rounds, secret)])
    _, out, _ = report(rid, repo, capsys)
    assert token not in out and "dev@example.com" not in out
    hb = part(out, "Hand-backs and fix rounds")
    assert len([ln for ln in hb.splitlines() if ln.startswith("- ")]) == 11
    assert "- … and 3 more" in hb


def test_the_block_carries_no_prompts_or_diffs_ac_133_8(repo, capsys):
    """AC-133.8: fields beyond the documented ones (a prompt, a diff) never reach the block."""
    rid = make_run(prompt="SECRET PROMPT TEXT", diff="+++ b/x.py\n-old\n+new", **FULL)
    _, out, _ = report(rid, repo, capsys)
    assert "SECRET PROMPT TEXT" not in out and "+++ b/x.py" not in out


# ---------------- AC-133.9 ----------------

def _begun(repo):
    assert runs.main(["begin", "build", "--spec", "133", "--dir", str(repo)]) == 0
    return runs.current_run(repo)


@pytest.mark.parametrize("args, want", [
    (["sequential", "--reason", "no worktree"], {"mode": "sequential", "reason": "no worktree"}),
    (["parallel"], {"mode": "parallel", "reason": None}),
])
def test_the_execution_call_records_the_mode_ac_133_9(repo, capsys, args, want):
    """AC-133.9: `runs agent execution` sets the `execution` section, exit 0."""
    rid = _begun(repo)
    assert runs.main(["agent", "execution", *args, "--dir", str(repo)]) == 0
    assert runs.active(rid)["execution"] == want


def test_the_last_execution_call_wins_and_a_bad_mode_records_nothing_ac_133_9(repo, capsys):
    """AC-133.9: the last call wins; a bad mode exits 0 and changes nothing."""
    rid = _begun(repo)
    runs.main(["agent", "execution", "parallel", "--dir", str(repo)])
    runs.main(["agent", "execution", "sequential", "--reason", "probe failed", "--dir", str(repo)])
    assert runs.main(["agent", "execution", "sideways", "--dir", str(repo)]) == 0
    assert runs.active(rid)["execution"] == {"mode": "sequential", "reason": "probe failed"}


def test_build_records_the_execution_after_the_worktree_probe_ac_133_9():
    """AC-133.9: /component:build and the fallback reference name the call."""
    build = (ROOT / "plugins/component/commands/build.md").read_text()
    fallback = (ROOT / "plugins/component/references/build-worktree-fallback.md").read_text()
    assert structure.points_to("plugins/component/commands/build.md", "cplat platform runs") and "execution parallel" in build
    assert structure.points_to("plugins/component/references/build-worktree-fallback.md", "cplat platform runs")
    assert "execution sequential" in fallback


# ---------------- AC-133.10 to AC-133.12 ----------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "PR_BODY.md").write_text("## Summary\n\nDid it.\n")
    (tmp_path / SPEC_DIR).mkdir(parents=True)
    (tmp_path / SPEC_DIR / "verification.md").write_text(VERIFICATION)
    fake = Fake(tmp_path)
    monkeypatch.setattr(pr_open, "run", fake)
    return fake


def body(env):
    return (env.repo / ".git" / "PR_BODY.md").read_text()


def open_cmd(env, capsys, *extra):
    code = prmod.main(["open", "--title", "feat(api): add the thing", "--repo", str(env.repo), *extra])
    return code, capsys.readouterr().out


@pytest.mark.parametrize("allowed", [True, False])
def test_pr_open_appends_the_block_when_the_checkout_has_a_run_ac_133_10(env, capsys, monkeypatch, allowed):
    """AC-133.10: the block is appended before gh pr create, when the PR opens and when it ends ready."""
    rid = make_run(**FULL)
    monkeypatch.setattr(runs, "current_run", lambda repo: rid)
    if allowed:
        allow(env.repo, ["Bash(gh pr create *)"])
    seen = []
    orig = env.__call__

    def spy(cmd, **kw):
        if list(cmd)[:3] == ["gh", "pr", "create"]:
            seen.append(body(env))
        return orig(cmd, **kw)
    monkeypatch.setattr(pr_open, "run", spy)
    code, out = open_cmd(env, capsys, "--spec", "133")
    assert code == 0
    text = body(env)
    assert text.startswith("## Summary\n\nDid it.\n") and text.rstrip().endswith(END)
    assert text.count(START) == 1 and rid in text
    if allowed:
        assert seen and START in seen[0]
    else:
        assert "pr: ready" in out


def test_pr_open_without_a_run_leaves_the_body_byte_for_byte_ac_133_11(env, capsys, monkeypatch):
    """AC-133.11: no current run → body unchanged."""
    monkeypatch.setattr(runs, "current_run", lambda repo: None)
    before = body(env)
    open_cmd(env, capsys)
    assert body(env) == before


def test_pr_open_ignores_a_run_for_another_spec_ac_133_11(env, capsys, monkeypatch):
    """AC-133.11: a run whose spec is not the PR's --spec is ignored."""
    rid = make_run(spec="131-other", **FULL)
    monkeypatch.setattr(runs, "current_run", lambda repo: rid)
    before = body(env)
    open_cmd(env, capsys, "--spec", "133")
    assert body(env) == before


def test_a_failing_section_leaves_the_body_and_opens_the_pr_with_a_note_ac_133_11(env, capsys, monkeypatch):
    """AC-133.11: an exception while building the block → body unchanged, PR opens, one note line."""
    import runs_built

    def boom(*a, **kw):
        raise RuntimeError("ledger unreadable")
    monkeypatch.setattr(runs_built, "pr_section", boom)
    allow(env.repo, ["Bash(gh pr create *)"])
    before = body(env)
    code, out = open_cmd(env, capsys)
    assert code == 0 and body(env) == before
    assert "pr: opened" in out
    notes = [ln for ln in out.splitlines() if ln.startswith("note: how-this-was-built skipped:")]
    assert len(notes) == 1 and "ledger unreadable" in notes[0]


def test_running_pr_open_again_replaces_the_block_ac_133_12(env, capsys, monkeypatch):
    """AC-133.12: an existing marked block is replaced, not duplicated."""
    rid = make_run(**FULL)
    monkeypatch.setattr(runs, "current_run", lambda repo: rid)
    (env.repo / ".git" / "PR_BODY.md").write_text(f"## Summary\n\nDid it.\n\n{START}\nold block\n{END}\n\nTrailer.\n")
    open_cmd(env, capsys, "--spec", "133")
    text = body(env)
    assert text.count(START) == 1 and text.count(END) == 1
    assert "old block" not in text and "Trailer." in text and rid in text


# ---------------- AC-133.13 ----------------

def test_docs_name_the_report_the_execution_call_and_the_changelog_entry_ac_133_13():
    """AC-133.13: /platform:runs names `--pr`; /component:build names the call and the block; changelog has #338."""
    runs_md = (ROOT / "plugins/platform/commands/runs.md").read_text()
    build = (ROOT / "plugins/component/commands/build.md").read_text()
    assert "cplat platform runs report --pr <run-id>" in runs_md
    assert "runs agent execution" in build and "How this was built" in build
    import release_support
    release_support.entry(r"\(#338\)")                 # any section or fragment: the release moves it (#321)
