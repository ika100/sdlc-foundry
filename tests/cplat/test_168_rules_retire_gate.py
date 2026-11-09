"""Spec 168 acceptance tests: `cplat platform pr-check` applies the eval gate to a change that retires or removes register entries
(AC-168.7), and its `rules` rule.

Seams: a real git repo under tmp_path shaped like the platform repo (marketplace, one plugin, a register, a `v1.0.0` tag, a feature
branch); the benchmark records are passed by replacing `evalgate._records` (the contract says it is looked up at call time)."""
import json
import subprocess

import pytest
import yaml

import evalgate
import house_rules
from rules_support import ENTRIES, GOOD_ENTRIES, PROMPT, R1, R2, Lazy, e, entries_text, good_repo, put

rules_retire = Lazy("rules_retire")

BODY_PATH = "plugins/svc/commands/demo.md"
RETIRED = dict(retired="2026-11-10", reason="a cplat command now refuses it", enforced_by="cplat pr wait")
KEY = f"{PROMPT}#"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, msg="change"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-s", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path):
    r = good_repo(tmp_path / "platform")
    put(r, ".claude-plugin/marketplace.json", json.dumps({"plugins": [{"name": "svc", "version": "1.0.0"}]}))
    put(r, "plugins/svc/.claude-plugin/plugin.json", json.dumps({"name": "svc", "version": "1.0.0"}))
    put(r, "docs/changelog.d/README.md", "fragments\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.name", "t")
    git(r, "config", "user.email", "t@t")
    commit(r, "base")
    git(r, "tag", "v1.0.0")
    git(r, "checkout", "-q", "-b", "feature/x")
    return r


SENTENCES = {"R1": R1, "R2": f"- {R2}"}


def retire(repo, *ids, drop=(), extra=()):
    """Head: the entries `ids` are retired, `drop` are deleted, `extra` are added; the prompt loses their sentences."""
    items = []
    for item in GOOD_ENTRIES:
        if item["id"] in (*ids, *drop):
            put(repo, PROMPT, (repo / PROMPT).read_text().replace(SENTENCES[item["id"]] + "\n", ""))
        if item["id"] in drop:
            continue
        items.append(e(item["id"], item["text"], "retired", **RETIRED) if item["id"] in ids else item)
    put(repo, ENTRIES, entries_text([*items, *extra]))
    return commit(repo, "retire")


def bench(workflow, commit_sha, outcome="done", tokens=1_000_000):
    return {"kind": "benchmark", "outcome": outcome, "platform_version": "1.0.1", "run_id": f"r-{workflow}-{commit_sha[:4]}",
            "ended_at": "2026-11-07T10:00:00Z", "usage": {"totals": {"input_tokens": tokens}},
            "benchmark": {"workflow": workflow, "plugins": {"commit": commit_sha, "dirty": False}}}


def records(monkeypatch, recs):
    monkeypatch.setattr(evalgate, "_records", lambda days: recs)


def passing(repo, monkeypatch):
    head = git(repo, "rev-parse", "HEAD")
    records(monkeypatch, [bench("quick-task", head), bench("build", head)])
    return [f"r-quick-task-{head[:4]}", f"r-build-{head[:4]}"]


def problems(repo, fix=False):
    return rules_retire.check(repo, "main", fix=fix)


RUN_IT = "cplat platform runs benchmark {} --plugins plugins --reset-first"


# ---------------- the gate applies when entries are retired or removed ----------------

def test_a_retirement_without_a_benchmark_fails_with_the_gate_failures_and_commands_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, "R2")
    records(monkeypatch, [])
    assert problems(repo) == [
        f"rules-retired: 1 register entry retired or removed ({KEY}R2); {w}: no benchmark ran with these prompts; run `{RUN_IT.format(w)}`"
        for w in ("quick-task", "build")]


def test_several_retirements_are_named_in_one_count_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, "R1", "R2")
    records(monkeypatch, [])
    got = problems(repo)
    assert len(got) == 2 and all(p.startswith(f"rules-retired: 2 register entries retired or removed ({KEY}R1, {KEY}R2); ") for p in got)


def test_a_failed_benchmark_fails_the_gate_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, "R2")
    head = git(repo, "rev-parse", "HEAD")
    records(monkeypatch, [bench("quick-task", head, outcome="escalated"), bench("build", head)])
    [p] = problems(repo)
    assert p.startswith("rules-retired: 1 register entry retired or removed") and "ended escalated" in p
    assert RUN_IT.format("quick-task") in p


def test_a_benchmark_of_another_plugin_tree_does_not_pass_ac_168_7(repo, monkeypatch):  # AC-168.7
    before = git(repo, "rev-parse", "HEAD")
    retire(repo, "R2")                                                # the prompt lost a sentence: another plugins/ tree
    records(monkeypatch, [bench("quick-task", before), bench("build", before)])
    assert len(problems(repo)) == 2


def test_a_removed_entry_or_a_deleted_register_file_needs_the_gate_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, drop=("R2",))
    records(monkeypatch, [])
    assert all(f"1 register entry retired or removed ({KEY}R2)" in p for p in problems(repo))
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-q", "-b", "feature/y")
    git(repo, "rm", "-q", "-r", "plugins/svc/commands", "docs/rules/plugins")
    commit(repo, "remove the prompt")
    assert all(f"3 register entries retired or removed ({KEY}R1, {KEY}R2, {KEY}R3)" in p for p in problems(repo))


def test_an_entry_added_already_retired_counts_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, extra=[e("R4", "never poll for a PR in a shell loop", "retired", **RETIRED)])
    records(monkeypatch, [])
    assert all(f"1 register entry retired or removed ({KEY}R4)" in p for p in problems(repo))


def test_a_reword_a_new_entry_and_a_reclass_need_no_benchmark_ac_168_7(repo, monkeypatch):  # AC-168.7
    monkeypatch.setattr(evalgate, "_records", lambda days: pytest.fail("the store was read"))
    items = [e("R1", "Always run the tests", "practice", source="#476"), e("R2", "Never skip the lint step", "not a rule"),
             *GOOD_ENTRIES[2:], e("R4", "Never poll for a PR in a loop", "practice")]
    put(repo, ENTRIES, entries_text(items))
    commit(repo)
    assert problems(repo) == []


def test_an_entry_retired_before_the_change_needs_no_benchmark_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, "R2")
    git(repo, "checkout", "-q", "-b", "feature/next")
    git(repo, "branch", "-f", "main", "feature/x")
    put(repo, "docs/changelog.d/1-x.fixed.md", "x\n")
    commit(repo)
    monkeypatch.setattr(evalgate, "_records", lambda days: pytest.fail("the store was read"))
    assert problems(repo) == []


# ---------------- the benchmark run ids ----------------

def test_a_passing_gate_still_needs_the_run_ids_on_the_retired_entry_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, "R2")
    ids = passing(repo, monkeypatch)
    [p] = problems(repo)
    assert p.startswith(f"rules-retired: {KEY}R2 records no passing benchmark run; add benchmark_runs: [")
    assert p.endswith("(or run pr-check with --fix)") and all(i in p for i in ids)


def test_run_ids_on_the_entry_pass_and_a_missing_one_does_not_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, "R2")
    ids = passing(repo, monkeypatch)                                   # a register-only commit changes no plugins/ tree
    for listed, expected in ((ids, 0), (ids[:1], 1)):
        items = [GOOD_ENTRIES[0], e("R2", "Never skip the lint step", "retired", **RETIRED, benchmark_runs=listed), GOOD_ENTRIES[2]]
        put(repo, ENTRIES, entries_text(items))
        commit(repo, "ids")
        assert len(problems(repo)) == expected, listed


def test_a_removed_entry_needs_no_run_ids_when_the_gate_passes_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, drop=("R2",))
    passing(repo, monkeypatch)
    assert problems(repo) == []


def test_fix_writes_the_run_ids_of_the_passing_gate_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, "R1", "R2")
    ids = passing(repo, monkeypatch)
    assert problems(repo, fix=True) == []
    text = (repo / ENTRIES).read_text()
    assert text.count("    benchmark_runs: [") == 2                  # indented like the `id:` key
    rules = yaml.safe_load(text)["rules"]
    assert sorted(rules[0]["benchmark_runs"]) == sorted(ids) and sorted(rules[1]["benchmark_runs"]) == sorted(ids)
    assert "benchmark_runs" not in rules[2]
    assert problems(repo) == []                                      # the fixed register passes without --fix


def test_fix_does_not_hide_a_failing_gate_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, "R2")
    records(monkeypatch, [])
    assert len(problems(repo, fix=True)) == 2 and "benchmark_runs" not in (repo / ENTRIES).read_text()


def test_without_a_run_store_the_problem_names_the_missing_setting_ac_168_7(repo):  # AC-168.7
    retire(repo, "R2")
    [p] = problems(repo)
    assert p.startswith("rules-retired:") and "CPLAT_RUNS_REPO" in p


# ---------------- pr-check ----------------

def pr_check(repo, **kw):
    return house_rules.check(repo, title="fix(cplat): retire a rule", body="", labels=[], base="main", fix=kw.pop("fix", False),
                             rules=kw.pop("rules", house_rules.RULES))


def test_pr_check_runs_the_rule_and_prints_its_problems_ac_168_7(repo, monkeypatch, capsys):  # AC-168.7
    assert "rules" in house_rules.RULES and "rules-retired" in house_rules.RULES
    assert "rules-retired" not in house_rules.PR_OPEN_RULES and "rules" not in house_rules.PR_OPEN_RULES
    retire(repo, "R2")
    records(monkeypatch, [])
    _, got = pr_check(repo, rules=("rules-retired",))
    assert len(got) == 2 and all(p.startswith("rules-retired: 1 register entry retired or removed") for p in got)
    rc = house_rules.main(["--repo", str(repo), "--base", "main", "--title", "fix(cplat): retire a rule"])
    out = capsys.readouterr().out
    assert rc == 1 and out.count("ERROR: rules-retired: 1 register entry retired or removed") == 2


def test_pr_check_passes_a_clean_branch_and_names_the_two_new_rules_ac_168_7(repo, capsys):  # AC-168.7
    put(repo, "scripts/a.py", "x = 1\n")
    put(repo, "docs/changelog.d/150-a.added.md", "**A change (spec 150).** Text.\n")
    commit(repo)
    rc = house_rules.main(["--repo", str(repo), "--base", "main", "--title", "feat(cplat): a change"])
    assert capsys.readouterr().out == ("OK: the house rules pass (pr-title, spec-required, changelog fragment, validate, dco, links, "
                                       "rules, rules-retired)\n")
    assert rc == 0


def test_pr_check_reports_a_rule_problem_with_file_line_and_kind_ac_168_7(repo):  # AC-168.7
    text = (repo / PROMPT).read_text() + "\nNever merge on a red build, because the base then breaks.\n"
    put(repo, PROMPT, text)
    commit(repo)
    line = next(n for n, ln in enumerate(text.splitlines(), 1) if "Never merge on a red build" in ln)
    _, got = pr_check(repo, rules=("rules",))
    assert got == [f"rules: {PROMPT}:{line}: no-entry: rule sentence has no register entry"]


def test_pr_check_lists_at_most_ten_rule_problems_ac_168_7(repo):  # AC-168.7
    extra = "".join(f"\nNever merge on build {n}, because the base then breaks.\n" for n in range(13))
    put(repo, PROMPT, (repo / PROMPT).read_text() + extra)
    commit(repo)
    _, got = pr_check(repo, rules=("rules",))
    assert len(got) == 11 and all(p.startswith(f"rules: {PROMPT}:") and ": no-entry: " in p for p in got[:10])
    assert got[10] == "rules: … and 3 more (run cplat platform rules check)"


def test_pr_check_skips_both_rules_without_a_register_ac_168_7(repo):  # AC-168.7
    assert "rules" in house_rules.RULES
    git(repo, "rm", "-q", "-r", "docs/rules")
    commit(repo, "no register")
    assert pr_check(repo, rules=("rules", "rules-retired"))[1] == []


def test_the_gate_helper_returns_failures_and_the_passing_run_ids_ac_168_7(repo, monkeypatch):  # AC-168.7
    retire(repo, "R2")
    head = git(repo, "rev-parse", "HEAD")
    tree = evalgate.plugins_tree(repo, "HEAD")
    kw = dict(head_tree=tree, tree_of=lambda c: evalgate.plugins_tree(repo, c), baseline_version="1.0.0")
    fails, ids = evalgate.verdict_runs([bench("quick-task", head), bench("build", head, outcome="failed")], **kw)
    assert len(fails) == 1 and fails[0].startswith("build:") and ids == {"quick-task": f"r-quick-task-{head[:4]}"}
    fails, ids = evalgate.verdict_runs([bench("quick-task", head), bench("build", head)], **kw)
    assert fails == [] and ids == {"quick-task": f"r-quick-task-{head[:4]}", "build": f"r-build-{head[:4]}"}
    assert evalgate.verdict([bench("quick-task", head), bench("build", head)], **kw) == []
    fails, ids = evalgate.verdict_runs([bench("quick-task", head)], workflows=("quick-task",), **kw)
    assert fails == [] and list(ids) == ["quick-task"]
