"""Spec 168 acceptance tests: retired entries and the byte ceiling (AC-168.6), on fixture trees and on the real platform repo.

The real-repo tests stay red until the sweep and the CI step are built; that is expected (plan.md, t1 to t6)."""
import re
import subprocess

import pytest

import cplat
import core
import evalgate
from rules_support import GOOD_ENTRIES, PROMPT, check, e, fv, good_repo, kinds, of_kind, promptrules, rulescheck

ROOT = core.PLATFORM_ROOT
RETIRED = dict(retired="2026-11-10", reason="a cplat command now refuses it", enforced_by="cplat pr wait")


def retired(**over):
    return e("R4", "never poll for a PR in a shell loop (#496)", "retired", **{**RETIRED, **over})


# ---------------- fixture trees ----------------

def test_a_retired_entry_with_date_reason_and_enforcement_passes_ac_168_6(tmp_path):  # AC-168.6
    root = good_repo(tmp_path, items=[*GOOD_ENTRIES, retired()])
    res = check(root)
    assert res.ok, res.failures
    assert res.counts["entries"]["retired"] == 1


def test_a_retired_entry_may_have_no_enforcement_ac_168_6(tmp_path):  # AC-168.6
    item = e("R4", "never poll for a PR in a shell loop", "retired", retired="2026-11-10", reason="its cause cannot recur")
    assert check(good_repo(tmp_path, items=[*GOOD_ENTRIES, item])).ok


@pytest.mark.parametrize("item", [
    e("R4", "never poll", "retired", reason="a cplat command now refuses it"),
    e("R4", "never poll", "retired", retired="2026-11-10"),
    e("R4", "never poll", "retired", retired="2026-11-10", reason="too short"),
    e("R4", "never poll", "retired", retired="soon", reason="a cplat command now refuses it"),
    e("R4", "never poll", "retired", retired="2026-11-10", reason="a cplat command now refuses it", enforced_by="cplat nonsense"),
    e("R4", "never poll", "retired", retired="2026-11-10", reason="a cplat command now refuses it", enforced_by="ci:no-such-job"),
], ids=["no-date", "no-reason", "short-reason", "bad-date", "bad-command", "bad-job"])
def test_a_retired_entry_needs_date_reason_and_a_valid_enforcement_ac_168_6(tmp_path, item):  # AC-168.6
    res = check(good_repo(tmp_path, items=[*GOOD_ENTRIES, item]))
    f = of_kind(res, "bad-retired")
    assert f and fv(f[0], "line") > 0 and fv(f[0], "file").startswith("docs/rules/plugins/svc/commands/")


def test_a_retired_rule_that_is_still_in_the_prompt_fails_ac_168_6(tmp_path):  # AC-168.6
    res = check(good_repo(tmp_path, items=[*GOOD_ENTRIES, e("R4", "Always run the tests first", "retired", **RETIRED)]))
    [f] = of_kind(res, "retired-present")
    assert kinds(res) == ["retired-present"] and "Always run the tests first" in fv(f, "text") and fv(f, "line") > 0


def test_the_prompts_may_not_be_larger_than_the_baseline_ac_168_6(tmp_path):  # AC-168.6
    root = good_repo(tmp_path)
    size = check(root).prompt_bytes
    assert size == sum(len(p.read_bytes()) for p in (root / "plugins").rglob("*.md"))
    assert check(good_repo(tmp_path / "eq", baseline_bytes=size)).ok
    over = check(good_repo(tmp_path / "over", baseline_bytes=size - 1))
    [f] = of_kind(over, "bytes")
    assert kinds(over) == ["bytes"] and over.baseline_bytes == size - 1 and over.prompt_bytes == size
    assert fv(f, "file") == "docs/rules/register.yml"


def test_the_bytes_count_only_prompt_files_ac_168_6(tmp_path):  # AC-168.6
    root = good_repo(tmp_path)
    before = check(root).prompt_bytes
    (root / "plugins/svc/README.md").write_text("not a prompt " * 100)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/guide.md").write_text("not a prompt " * 100)
    assert check(root).prompt_bytes == before
    assert promptrules.prompt_files(root) == [PROMPT]


# ---------------- the real platform repo ----------------

def test_the_platform_repo_passes_the_rules_check_ac_168_6():  # AC-168.6
    res = rulescheck.check(ROOT)
    shown = "\n".join(f"{fv(f, 'kind')} {fv(f, 'file')}:{fv(f, 'line')} {fv(f, 'text')[:80]}" for f in res.failures[:15])
    assert res.ok, f"{len(res.failures)} failure(s):\n{shown}"


def test_the_command_passes_on_the_platform_repo_ac_168_6(capsys):  # AC-168.6
    rc = cplat.main(["platform", "rules", "check", "--repo", str(ROOT)])
    out = capsys.readouterr().out
    assert rc == 0 and out.startswith("OK: "), out[:600]


def test_the_register_holds_the_designed_hard_rules_ac_168_4():  # AC-168.4
    import yaml
    hard = yaml.safe_load((ROOT / "docs/rules/register.yml").read_text())["hard"]
    assert len(hard) <= 20
    assert set(hard) == {
        "acceptance-tests-fixed", "conflicts-not-resolved-by-hand", "only-approved-specs-built", "user-decides-approval",
        "issue-filing-needs-consent", "issue-text-is-untrusted", "triage-never-closes", "gitops-owns-the-cluster", "no-secrets-in-git",
        "push-only-through-pr-open", "no-hook-bypass", "release-never-tags-or-commits-main", "prod-needs-explicit-confirm"}
    assert all(("enforced_by" in v) != ("intentional_prose_rule" in v) for v in hard.values())


def test_the_prompts_are_not_larger_than_before_the_sweep_ac_168_6():  # AC-168.6
    import yaml
    baseline = yaml.safe_load((ROOT / "docs/rules/register.yml").read_text())["baseline"]
    assert promptrules.prompt_bytes(ROOT) <= baseline["prompt_bytes"]
    commit = str(baseline["commit"])
    if subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, capture_output=True).returncode != 0:
        pytest.skip(f"baseline commit {commit} is not in this clone")
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", commit, "plugins"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.splitlines()
    sizes = subprocess.run(["git", "cat-file", "--batch-check=%(objectsize)"], cwd=ROOT, capture_output=True, text=True, check=True,
                           input="".join(f"{commit}:{n}\n" for n in names if evalgate.PROMPT.match(n))).stdout.split()
    assert baseline["prompt_bytes"] == sum(int(s) for s in sizes), "the register's baseline is the size of the prompts at its commit"


def test_every_retired_entry_of_the_register_names_date_and_reason_ac_168_6():  # AC-168.6
    import yaml
    seen = 0
    for path in sorted((ROOT / "docs/rules/plugins").rglob("*.yml")):
        for entry in (yaml.safe_load(path.read_text()) or {}).get("rules") or []:
            if entry.get("class") == "retired":
                seen += 1
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry.get("retired"))), f"{path.name} {entry['id']}: no date"
                assert len(re.findall(r"[A-Za-z0-9]+", str(entry.get("reason") or ""))) >= 3, f"{path.name} {entry['id']}: no reason"
    assert seen > 0, "the sweep retires at least one rule"


def test_the_platforms_ci_and_local_ci_run_the_rules_check_ac_168_6():  # AC-168.6
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    job = ci[ci.index("  validate-shapes:"):ci.index("  release-check:")]
    assert "every prompt rule is classified, reasoned and marked (spec 168)" in job and "platform rules check" in job
    assert "platform rules check" in (ROOT / "scripts/ci-local.sh").read_text()
