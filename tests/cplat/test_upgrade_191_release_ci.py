"""Spec 191 acceptance tests, the tags, decisions and gate of `scripts/release-check.py` (AC-191.4 to AC-191.7), the workflows and the e2e
script structure (AC-191.4 to AC-191.7), and the documents (AC-191.8).

Contract: design.md "`scripts/release-check.py`", "Workflows", "`tests/e2e/upgrade.sh`", "`tests/e2e/lib/upgrade-system.sh`". The release
check runs in a throwaway copy of the platform repository (as the spec 121 tests do), `gh` for the gate is a script on PATH. Workflows and
scripts that need a cluster are only read. The criterion ids sit in the test names and comments."""
import json
import os
import re
import stat
import subprocess
import sys

import pytest
import yaml

from system_fixtures import ROOT, git
from waiting import with_prelude
from test_upgrade_121_ops import GH_CHECKS, KEDA_LINE, KEDA_PATCH, CNPG_PATCH, changelog_with, mini_platform, release_world, run_script, workflow

E2E = "e2e upgrade (previous release → candidate)"
RENDER = "upgrade render check"
OLDEST = "e2e upgrade (oldest supported release → candidate)"
DRILL = "e2e upgrade drill (Postgres 16 → 17)"


def candidate(tmp_path, tags=("v5.3.0",), extra_tags=()):
    """A platform copy: every tag on the base commit, then one candidate commit on top (no tag at HEAD)."""
    root = mini_platform(tmp_path)
    git(root, "tag", "-d", "v5.3.0")
    for t in (*tags, *extra_tags):
        git(root, "tag", t)
    (root / "docs" / "note.md").write_text("candidate\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "candidate")
    return root


def from_tag(root, which):
    rc, out = run_script(root, "release-check.py", "from-tag", which)
    return rc, (out.strip().splitlines() or [""])[-1]


# ---------------- AC-191.5: the tag rules ----------------

def test_from_tag_previous_is_the_newest_release_tag_not_at_head_ac_191_5(tmp_path):  # AC-191.5
    root = candidate(tmp_path, tags=("v5.0.1", "v5.2.0", "v5.3.0"))
    assert from_tag(root, "previous") == (0, "v5.3.0")
    git(root, "tag", "v5.4.0")      # points at HEAD: that is the candidate itself
    assert from_tag(root, "previous") == (0, "v5.3.0")


def test_from_tag_previous_without_a_tag_fails_naming_the_series_ac_191_5(tmp_path):  # AC-191.5
    root = candidate(tmp_path, tags=())
    assert from_tag(root, "previous") == (1, "ERROR: no previous release tag found (v5.0.*)")


def test_from_tag_oldest_is_the_newest_patch_of_the_first_minor_of_the_major_ac_191_5(tmp_path):  # AC-191.5
    root = candidate(tmp_path, tags=("v5.0.1", "v5.0.3", "v5.0.2", "v5.1.0", "v5.3.0"))
    assert from_tag(root, "oldest") == (0, "v5.0.3")


def test_from_tag_oldest_skips_when_the_major_has_no_first_minor_release_ac_191_5(tmp_path):  # AC-191.5
    root = candidate(tmp_path, tags=("v4.0.9", "v5.1.0", "v5.3.0"))
    rc, line = from_tag(root, "oldest")
    assert rc == 0 and re.fullmatch(r"skipped: no v(X|5)\.0\.\* release tag", line), line


def test_from_tag_oldest_skips_when_it_is_the_previous_release_ac_191_5(tmp_path):  # AC-191.5
    root = candidate(tmp_path, tags=("v5.0.2",))
    assert from_tag(root, "oldest") == (0, "skipped: v5.0.2 is the previous release")


def test_the_candidate_major_is_the_one_of_a_newer_release_heading_ac_191_5(tmp_path):  # AC-191.5
    root = candidate(tmp_path, tags=("v5.0.4", "v5.3.0"))
    (root / "docs" / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [6.0.0] — 2026-11-20\n\nmajor\n\n## [5.3.0] — 2026-10-27\n\nthe base\n")
    git(root, "commit", "-qam", "release pull request")
    rc, line = from_tag(root, "oldest")
    assert rc == 0 and line.startswith("skipped: ") and "v5.0.4" not in line and re.search(r"v(6|X)\.0\.", line), line


# ---------------- AC-191.4 / AC-191.7: the three decisions ----------------

def decisions(root) -> list[str]:
    rc, out = run_script(root, "release-check.py", "needs-upgrade-e2e", "--base", "v5.3.0")
    assert rc == 0, out
    return out.strip().splitlines()


def touch(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text((p.read_text() if p.is_file() else "") + "\n# changed\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "touch")


def test_nothing_changed_prints_three_false_lines_with_run_last_ac_191_4(tmp_path):  # AC-191.4
    assert decisions(mini_platform(tmp_path)) == ["render=false", "drill=false", "run=false"]


RENDER_FILES = ["templates/gitops-app/README.md", "scripts/cplat/update.py", "scripts/cplat/versions.py", "scripts/upgrade-render-check.py",
                "tests/e2e/lib/upgrade-system.sh", "scripts/release-check.py", ".github/workflows/e2e-upgrade.yml"]


@pytest.mark.parametrize("rel", RENDER_FILES)
def test_the_render_check_runs_for_the_files_it_reads_ac_191_4(tmp_path, rel):  # AC-191.4
    root = mini_platform(tmp_path)
    touch(root, rel)
    assert decisions(root)[0] == "render=true"


def test_the_render_check_runs_for_a_new_release_heading_ac_191_4(tmp_path):  # AC-191.4
    root = mini_platform(tmp_path)
    (root / "docs" / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [5.4.0] — 2026-10-28\n\nx\n\n## [5.3.0] — 2026-10-27\n\nthe base\n")
    git(root, "commit", "-qam", "heading")
    assert decisions(root)[:2] == ["render=true", "drill=false"]


def test_the_render_check_does_not_run_for_a_docs_only_change_ac_191_4(tmp_path):  # AC-191.4
    root = mini_platform(tmp_path)
    touch(root, "docs/other.md")
    assert decisions(root) == ["render=false", "drill=false", "run=false"]


DRILL_FILES = ["scripts/cplat/upgrade.py", "scripts/cplat/upgradeverify.py", "scripts/cplat/dbbackup.py", "scripts/cplat/backupstate.py", "tests/e2e/upgrade-drill.sh"]


@pytest.mark.parametrize("rel", DRILL_FILES)
def test_the_drill_runs_for_the_resource_upgrade_and_backup_code_and_its_own_steps_ac_191_7(tmp_path, rel):  # AC-191.7
    root = mini_platform(tmp_path)
    touch(root, rel)
    assert decisions(root)[1] == "drill=true"


def test_a_change_to_the_drill_steps_alone_does_not_run_the_update_part_ac_191_7(tmp_path):  # AC-191.7
    root = mini_platform(tmp_path)
    touch(root, "tests/e2e/upgrade-drill.sh")
    assert decisions(root) == ["render=false", "drill=true", "run=false"]


def test_the_drill_runs_for_a_changed_database_row_and_not_for_another_row_ac_191_7(tmp_path):  # AC-191.7
    pg = 'POSTGRES_IMAGES[16] = POSTGRES_IMAGES[16].replace("16.15", "16.16")'
    for tag, patch, line, want in (("pg", pg, "- `postgres 16` 16.15 → 16.16", "drill=true"), ("cnpg", CNPG_PATCH, "- `operator cloudnative-pg` 0.29.1 → 0.30.0 **(major)**", "drill=true"),
                                   ("keda", KEDA_PATCH, KEDA_LINE, "drill=false")):
        root = release_world(tmp_path / tag, patch, changelog_with(line))
        assert decisions(root)[1] == want, tag


# ---------------- AC-191.6: the gate requires the e2e and the render check, and nothing else ----------------

def gate(tmp_path, runs, sha="abc1234", api=None):
    root = mini_platform(tmp_path)
    bin_dir = tmp_path / "ghbin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(with_prelude(GH_CHECKS.replace("{python}", sys.executable)))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    data = tmp_path / "checkruns.json"
    data.write_text(json.dumps({"runs": {"total_count": len(runs), "check_runs": runs}, **(api or {})}))
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_CHECKRUNS": str(data), "GITHUB_REPOSITORY": "acme/platform", "GH_TOKEN": "x"}
    rc, out = run_script(root, "release-check.py", "gate", sha, env=env)
    return rc, out.splitlines()


def ok(name, conclusion="success"):
    return {"name": name, "conclusion": conclusion}


def test_the_gate_passes_with_both_green_and_ignores_the_oldest_and_drill_jobs_ac_191_6(tmp_path):  # AC-191.6
    runs = [ok(E2E), ok(RENDER), ok(OLDEST, "failure"), ok(DRILL, "failure")]
    rc, lines = gate(tmp_path, runs)
    assert rc == 0, lines
    assert "OK: abc1234 has a green upgrade e2e" in lines and "OK: abc1234 has a green upgrade render check" in lines, lines


@pytest.mark.parametrize("runs, bad, good", [
    ([ok(E2E)], "upgrade render check (none)", "upgrade e2e"),
    ([ok(RENDER)], "upgrade e2e (none)", "upgrade render check"),
    ([ok(E2E), ok(RENDER, "failure")], "upgrade render check (failure)", "upgrade e2e"),
    ([ok(E2E, "skipped"), ok(RENDER)], "upgrade e2e (skipped)", "upgrade render check"),
], ids=["no-render-check", "no-e2e", "red-render-check", "skipped-e2e"])
def test_the_gate_refuses_a_tag_missing_either_check_ac_191_6(tmp_path, runs, bad, good):  # AC-191.6
    rc, lines = gate(tmp_path, runs)
    assert rc == 1, lines
    assert f"ERROR: abc1234 has no green {bad}: do not tag it" in lines, lines
    assert f"OK: abc1234 has a green {good}" in lines, lines


def head_api(tree="t1", e2e="success", render="success"):
    p = "repos/acme/platform/commits/"
    return {p + "abc1234/pulls": [{"number": 7, "head": {"sha": "def5678"}}],
            p + "abc1234": {"commit": {"tree": {"sha": "t1"}}}, p + "def5678": {"commit": {"tree": {"sha": tree}}},
            p + "def5678/check-runs": {"check_runs": [ok(E2E, e2e), ok(RENDER, render)]}}


def test_the_gate_takes_both_checks_from_the_pull_requests_head_with_the_same_tree_ac_191_6(tmp_path):  # AC-191.6
    rc, lines = gate(tmp_path, [], api=head_api())
    assert rc == 0, lines
    for label in ("upgrade e2e", "upgrade render check"):
        assert f"OK: abc1234 has a green {label} on def5678, the head of its pull request with the same tree" in lines, lines


@pytest.mark.parametrize("kw, bad", [({"render": "failure"}, "upgrade render check"), ({"e2e": "failure"}, "upgrade e2e"),
                                    ({"tree": "t2"}, "upgrade render check")], ids=["red-render-head", "red-e2e-head", "other-tree"])
def test_the_gate_refuses_a_head_that_lacks_either_check_ac_191_6(tmp_path, kw, bad):  # AC-191.6
    rc, lines = gate(tmp_path, [], api=head_api(**kw))
    assert rc == 1 and any(ln.startswith(f"ERROR: abc1234 has no green {bad} (") for ln in lines), lines
    other = "upgrade e2e" if bad == "upgrade render check" else "upgrade render check"
    if "tree" not in kw:      # the other check is judged on its own: green on the head
        assert f"OK: abc1234 has a green {other} on def5678, the head of its pull request with the same tree" in lines, lines
    assert any(ln.startswith(f"ERROR: abc1234 has no green {other} (") or ln.startswith(f"OK: abc1234 has a green {other}") for ln in lines), lines


# ---------------- the workflows (AC-191.4 .. AC-191.7) ----------------

def on_of(wf):
    return wf.get("on") or wf.get(True)


def needs_of(job):
    n = job.get("needs", [])
    return n if isinstance(n, list) else [n]


def runs_of(job):
    return " ".join(s.get("run", "") for s in job["steps"])


def test_the_render_job_runs_the_comparison_within_five_minutes_ac_191_4():  # AC-191.4
    wf = workflow("e2e-upgrade.yml")
    job = next((j for j in wf["jobs"].values() if j.get("name") == RENDER), None)
    assert job is not None, f"a job named {RENDER!r}"
    assert job["timeout-minutes"] == 5 and "decide" in needs_of(job)
    assert re.search(r"needs\.decide\.outputs\.render", job["if"]) and "schedule" in job["if"] and "workflow_dispatch" in job["if"]
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0
    assert re.search(r"scripts/upgrade-render-check\.py", runs_of(job)) and re.search(r"\bcopier\b", runs_of(job))
    assert "render" in wf["jobs"]["decide"]["outputs"] or any("render" in k for k in wf["jobs"]["decide"]["outputs"])


def test_the_workflow_triggers_cover_the_template_and_the_check_itself_ac_191_4():  # AC-191.4
    on = on_of(workflow("e2e-upgrade.yml"))
    for event in ("pull_request", "push"):
        assert {"templates/gitops-app/**", "scripts/upgrade-render-check.py"} <= set(on[event]["paths"]), event
    assert set(on) >= {"pull_request", "push", "schedule", "workflow_dispatch"}


def test_the_previous_release_job_is_the_platform_update_part_with_a_45_minute_limit_ac_191_6():  # AC-191.6
    wf = workflow("e2e-upgrade.yml")
    job = next((j for j in wf["jobs"].values() if j.get("name") == E2E), None)
    assert job is not None and job["timeout-minutes"] == 45
    assert re.search(r"needs\.decide\.outputs\.run", job["if"]) and "schedule" in job["if"] and "workflow_dispatch" in job["if"]
    assert re.search(r"bash tests/e2e/upgrade\.sh", runs_of(job)) and "E2E_UPGRADE_DRILL" not in json.dumps(job)


def test_the_oldest_release_job_runs_nightly_and_on_dispatch_only_and_skips_cleanly_ac_191_5():  # AC-191.5
    wf = workflow("e2e-upgrade.yml")
    job = next((j for j in wf["jobs"].values() if j.get("name") == OLDEST), None)
    assert job is not None, f"a job named {OLDEST!r}"
    cond = job["if"]
    assert "schedule" in cond and "workflow_dispatch" in cond and "pull_request" not in cond and "outputs.run" not in cond
    runs = runs_of(job)
    assert "from-tag oldest" in runs and "skipped:" in runs and re.search(r"E2E_UPGRADE_FROM=", runs) and re.search(r"bash tests/e2e/upgrade\.sh", runs)


def test_the_release_gate_names_neither_the_oldest_nor_the_drill_job_ac_191_5():  # AC-191.5
    text = (ROOT / "scripts" / "release-check.py").read_text()
    assert RENDER in text, "the gate requires the render check"
    assert OLDEST not in text and DRILL not in text


DRILL_PATHS = {"scripts/cplat/upgrade.py", "scripts/cplat/upgradeverify.py", "scripts/cplat/dbbackup.py", "scripts/cplat/backupstate.py",
               "templates/gitops-app/scripts/render.py", "tests/e2e/upgrade-drill.sh", ".github/workflows/e2e-upgrade-drill.yml"}


def test_the_drill_workflow_has_the_designed_triggers_and_permissions_ac_191_7():  # AC-191.7
    wf = workflow("e2e-upgrade-drill.yml")
    on = on_of(wf)
    assert set(on) >= {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert set(on["pull_request"]["paths"]) == DRILL_PATHS and set(on["push"]["paths"]) == DRILL_PATHS and on["push"]["branches"] == ["main"]
    assert on["schedule"] == [{"cron": "17 4 * * *"}] and wf["permissions"] == {"contents": "read"}
    assert wf["concurrency"]["group"].startswith("e2e-upgrade-drill-")


def test_the_drill_job_runs_the_drill_after_a_decide_job_with_a_75_minute_limit_ac_191_7():  # AC-191.7
    jobs = workflow("e2e-upgrade-drill.yml")["jobs"]
    assert jobs["decide"]["timeout-minutes"] == 2 and "release-check.py needs-upgrade-e2e" in runs_of(jobs["decide"]) and "drill" in jobs["decide"]["outputs"]
    job = next((j for j in jobs.values() if j.get("name") == DRILL), None)
    assert job is not None and job["timeout-minutes"] == 75 and "decide" in needs_of(job)
    assert re.search(r"needs\.decide\.outputs\.drill", job["if"]) and "schedule" in job["if"] and "workflow_dispatch" in job["if"]
    assert re.search(r"E2E_UPGRADE_DRILL=1 bash tests/e2e/upgrade\.sh", runs_of(job))
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0


def test_no_job_of_the_upgrade_workflow_is_the_drill_ac_191_7():  # AC-191.7
    jobs = workflow("e2e-upgrade.yml")["jobs"]
    assert not [j for j in jobs.values() if "drill" in j.get("name", "").lower()]
    assert (ROOT / ".github" / "workflows" / "e2e-upgrade-drill.yml").is_file()


# ---------------- the scripts (AC-191.2, AC-191.6, AC-191.7) ----------------

def read(rel):
    p = ROOT / rel
    assert p.is_file(), f"{rel} exists"
    return p.read_text()


def code(text):
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_the_builder_creates_and_updates_the_system_without_a_cluster_ac_191_6():  # AC-191.6
    t = read("tests/e2e/lib/upgrade-system.sh")
    for needle in ("upg_types", "upg_create", "upg_update", "FROM_TYPES", "UPG_NOTHING_CHANGED", "worktree add", "system new", "resource add",
                   "platform update", "--skip-tasks", "upg-api", "postgres", "--version 16", "BASH_SOURCE", "8098", "k3d-upg-local-registry:5112"):
        assert needle in t, f"upgrade-system.sh lacks {needle!r}"
    assert re.search(r"\bcreate\b", t) and re.search(r"\bupdate\b", t)
    assert not re.search(r"\bdocker\b|\bk3d\b(?!-)|local-cluster\.sh|\bkubectl\b", code(t)), "the builder starts no container or cluster"
    assert subprocess.run(["bash", "-n", str(ROOT / "tests/e2e/lib/upgrade-system.sh")]).returncode == 0


def test_the_update_script_runs_the_update_part_and_sources_the_builder_ac_191_6():  # AC-191.6
    t = read("tests/e2e/upgrade.sh")
    for needle in ("lib/upgrade-system.sh", "release-check.py", "from-tag previous", "E2E_UPGRADE_DRILL", "upgrade-drill.sh", "UPGRADE E2E OK", "AC-191.6", "AC-191.7"):
        assert needle in t, f"upgrade.sh lacks {needle!r}"
    assert "resource add backups" not in t and "--to 17" not in t, "the backups and the major upgrade belong to the drill"
    assert re.search(r"E2E_UPGRADE_DRILL[^\n]*\n?[^\n]*upgrade-drill\.sh", t), "the drill is sourced only behind E2E_UPGRADE_DRILL"
    # the checks of the update part stay in the script that always runs (not in the drill-only file), read together with the builder
    for needle in ("read_data", "instance verify", "doctor", "--dry-run=server"):
        assert needle in t, f"upgrade.sh (outside the drill-only file) lacks the check {needle!r}"
    assert subprocess.run(["bash", "-n", str(ROOT / "tests/e2e/upgrade.sh")]).returncode == 0


def test_the_drill_script_holds_the_guard_and_the_major_steps_ac_191_7():  # AC-191.7
    t = read("tests/e2e/upgrade-drill.sh")
    for needle in ("resource add backups", "resource upgrade postgres --to 17", "AC-121.25", "AC-191.7", "verified", "majorVersion"):
        assert needle in t, f"upgrade-drill.sh lacks {needle!r}"
    assert subprocess.run(["bash", "-n", str(ROOT / "tests/e2e/upgrade-drill.sh")]).returncode == 0


# ---------------- AC-191.8: the documents ----------------

def test_contributing_names_the_four_jobs_the_gate_and_how_to_run_them_ac_191_8():  # AC-191.8
    t = read("CONTRIBUTING.md")
    for needle in (E2E, RENDER, OLDEST, DRILL, "Upgrade step:", "uv run scripts/upgrade-render-check.py", "bash tests/e2e/upgrade.sh",
                   "from-tag oldest", "E2E_UPGRADE_DRILL=1 bash tests/e2e/upgrade.sh"):
        assert needle in t, f"CONTRIBUTING.md lacks {needle!r}"
    assert re.search(r"(?i)release gate", t)
    # when each job runs: the sentence that names a job also says nightly / pull request / dispatch
    for job, words in ((RENDER, r"(?i)pull request|push"), (E2E, r"(?i)pull request|push"), (OLDEST, r"(?i)night|schedule"), (DRILL, r"(?i)night|schedule")):
        around = [t[max(0, m.start() - 400):m.end() + 400] for m in re.finditer(re.escape(job), t)]
        assert any(re.search(words, a) for a in around), f"CONTRIBUTING.md does not say when {job!r} runs"
        assert any(re.search(r"(?i)dispatch|manual", a) for a in around if job in (OLDEST, DRILL)) or job in (RENDER, E2E), job


def test_an_adr_records_the_split_and_amends_adr_069_ac_191_8():  # AC-191.8
    adrs = sorted((ROOT / "docs" / "adr").glob("*upgrade-tests-split*"))
    assert len(adrs) == 1, "one ADR for the split of the upgrade tests"
    assert adrs[0].name in read("docs/adr/README.md")
    amended = read("docs/adr/069-one-versions-table-pins-everything-and-every-release-proves-the-upgrade.md")
    assert re.search(r"Amended by", amended) and adrs[0].name in amended


def test_a_changelog_fragment_lists_the_change_ac_191_8():  # AC-191.8
    # a "changed" fragment until the release, then a paragraph of docs/CHANGELOG.md
    frags = [f.read_text() for f in (ROOT / "docs" / "changelog.d").glob("191-*.changed.md")]
    released = (ROOT / "docs" / "CHANGELOG.md").read_text().split("\n\n")
    hits = [e for e in frags + released if "upgrade render check" in e and "#400" in e]
    assert hits, "no changelog entry names the upgrade render check and #400"
