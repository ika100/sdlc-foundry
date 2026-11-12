"""Spec 180 acceptance tests: `cplat platform pr-check` rule `rules-baseline` (AC-180.7).

Seam: a real git repo under tmp_path with a register, a `main` base and a feature branch; the rule is `rules_baseline.check(repo,
base, notes)` and the CLI `house_rules.main(...)`."""
import json
import subprocess

import pytest

import house_rules
from rules_support import HARD, REGISTER, Lazy, good_repo, put, register_text

rules_baseline = Lazy("rules_baseline")

OLD, NEW = 100_000, 200_000
REASON = "the replan rule needs its reason clause"
RUNS = ["r-quick-1", "r-build-2"]


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, msg="change"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-s", "--allow-empty", "-m", msg)


def reg(baseline, history=None, hard_tail=True):
    hist = ""
    if history:
        hist = "  history:\n" + "".join(
            f'    - date: "{h["date"]}"\n      old: {h["old"]}\n      new: {h["new"]}\n      reason: "{h["reason"]}"\n'
            f'      benchmark_runs: [{", ".join(h["benchmark_runs"])}]\n' for h in history)
    full = register_text(HARD if hard_tail else {}, baseline)
    hard = full[full.index("hard:"):]
    return f'schema: 1\nbaseline:\n  commit: abc1234\n  prompt_bytes: {baseline}\n{hist}{hard}'


def entry(old=OLD, new=NEW, reason=REASON, runs=RUNS):
    return {"date": "2026-11-12", "old": old, "new": new, "reason": reason, "benchmark_runs": runs}


@pytest.fixture()
def repo(tmp_path):
    r = good_repo(tmp_path / "platform", baseline_bytes=OLD)
    put(r, REGISTER, reg(OLD))
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.name", "t")
    git(r, "config", "user.email", "t@t")
    commit(r, "base")
    git(r, "checkout", "-q", "-b", "feature/x")
    return r


def head_register(repo, text):
    put(repo, REGISTER, text)
    commit(repo)


def line_of_bytes(repo):
    return next(n for n, ln in enumerate((repo / REGISTER).read_text().splitlines(), 1) if "prompt_bytes:" in ln)


def run_rule(repo):
    notes: list[str] = []
    return rules_baseline.check(repo, "main", notes), notes


def test_a_raise_with_a_matching_history_entry_passes_and_shows_the_entry_ac_180_7(repo):  # AC-180.7
    head_register(repo, reg(NEW, [entry()]))
    problems, notes = run_rule(repo)
    assert problems == []
    [note] = notes
    assert note == f"rules-baseline: prompt baseline {OLD} → {NEW} bytes; reason: {REASON}; benchmark runs: r-quick-1, r-build-2"


def test_a_hand_edit_without_a_history_entry_fails_naming_the_register_line_ac_180_7(repo):  # AC-180.7
    head_register(repo, reg(NEW))
    problems, notes = run_rule(repo)
    assert problems == [f"rules-baseline: docs/rules/register.yml:{line_of_bytes(repo)}: the baseline rose from {OLD} to {NEW} bytes "
                        "with no history entry; raise it with cplat platform rules rebaseline --reason \"<why>\", not by hand"]
    assert notes == []


def test_an_entry_that_the_base_already_had_is_no_new_entry_ac_180_7(repo):  # AC-180.7
    git(repo, "checkout", "-q", "main")
    put(repo, REGISTER, reg(OLD, [entry(50_000, OLD)]))
    commit(repo, "base history")
    git(repo, "checkout", "-q", "-b", "feature/y")
    head_register(repo, reg(NEW, [entry(50_000, OLD)]))
    problems, _ = run_rule(repo)
    assert len(problems) == 1 and "no history entry" in problems[0]


def test_a_newest_entry_that_differs_from_the_baseline_fails_ac_180_7(repo):  # AC-180.7
    head_register(repo, reg(NEW, [entry(new=150_000)]))
    problems, _ = run_rule(repo)
    assert problems == [f"rules-baseline: docs/rules/register.yml:{line_of_bytes(repo)}: the newest history entry raises to 150000 bytes, "
                        f"the baseline says {NEW}"]


def test_no_raise_no_finding_and_no_note_ac_180_7(repo):  # AC-180.7
    for text in (reg(OLD), reg(OLD - 10)):
        head_register(repo, text)
        assert run_rule(repo) == ([], [])


def test_a_missing_register_at_head_or_base_skips_the_rule_ac_180_7(repo):  # AC-180.7
    git(repo, "rm", "-q", REGISTER)
    commit(repo, "no register")
    assert run_rule(repo) == ([], [])


def test_the_rule_is_part_of_pr_check_after_rules_retired_ac_180_7():  # AC-180.7
    rules = list(house_rules.RULES)
    assert "rules-baseline" in rules and rules.index("rules-baseline") == rules.index("rules-retired") + 1


def pr_ready(repo):
    """The base also carries what the other house rules read, so that only the register differs on the feature branch."""
    git(repo, "checkout", "-q", "main")
    put(repo, ".claude-plugin/marketplace.json", json.dumps({"plugins": [{"name": "svc", "version": "1.0.0"}]}))
    put(repo, "plugins/svc/.claude-plugin/plugin.json", json.dumps({"name": "svc", "version": "1.0.0"}))
    put(repo, "docs/changelog.d/README.md", "fragments\n")
    commit(repo, "scaffold")
    git(repo, "checkout", "-q", "-b", "feature/z")
    put(repo, "scripts/a.py", "x = 1\n")
    put(repo, "docs/changelog.d/150-a.added.md", "**A change (spec 150).** Text.\n")


def test_pr_check_shows_the_notes_in_json_and_the_ok_line_names_the_rule_ac_180_7(repo, capsys):  # AC-180.7
    pr_ready(repo)
    head_register(repo, reg(NEW, [entry()]))
    args = ["--repo", str(repo), "--base", "main", "--title", "feat(cplat): a change"]
    rc = house_rules.main([*args, "--json"])
    doc = json.loads(capsys.readouterr().out)
    note = f"rules-baseline: prompt baseline {OLD} → {NEW} bytes; reason: {REASON}; benchmark runs: r-quick-1, r-build-2"
    assert rc == 0 and doc["notes"] == [note]
    rc = house_rules.main(args)
    assert rc == 0 and capsys.readouterr().out.endswith("rules, rules-retired, rules-baseline)\n")


def test_pr_check_fails_a_hand_edited_raise_ac_180_7(repo, capsys):  # AC-180.7
    pr_ready(repo)
    head_register(repo, reg(NEW))
    rc = house_rules.main(["--repo", str(repo), "--base", "main", "--title", "feat(cplat): a change"])
    out = capsys.readouterr().out
    assert rc == 1 and f"ERROR: rules-baseline: docs/rules/register.yml:{line_of_bytes(repo)}: the baseline rose" in out
