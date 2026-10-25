"""Spec 093 acceptance tests, the prod evidence summary (`scripts/cplat/evidence.py`) and its use by `cplat promote … staging prod`:
AC-093.11 (what the summary says, in the dry run and in the PR body) and AC-093.12 (the warning line, the PR is still opened).

Seams: `evidence.gh`, `evidence.open_store`, `evidence.today` and `gitops.open_pr`. `evidence` is imported inside the tests: it does
not exist yet. Contract: design.md "Prod evidence"."""
import importlib
import json
import shutil
import subprocess
from datetime import date

import pytest

import core
import gitops
import promote
from test_gitops import commit, composed, gh, gitops_repo  # noqa: F401  (fixtures)

SVC = {"name": "shop-api", "repo": "acme/shop-api", "image": "ghcr.io/acme/shop-api"}
E = "a" * 40                         # the commit v1.4.0 points at
OTHER = "d" * 40
RELEASE = "e" * 40                   # a release-PR merge commit
PARENT = "f" * 40                    # its first parent: the build that ran
LINK = "https://github.com/acme/runs/blob/HEAD/runs/2026/10/24/{}.json"


def evidence_mod():
    return importlib.import_module("evidence")


def jq(expr, obj):
    expr = expr.strip()
    if expr.startswith(".") and expr[1:].isidentifier():
        return str(obj[expr[1:]])
    return subprocess.run([shutil.which("jq") or "jq", "-r", expr], input=json.dumps(obj), capture_output=True, text=True).stdout.strip()


class EvGh:
    """`gh` for the service repo: commits by ref (tags and shas), compare, and the open issues by label."""

    def __init__(self):
        self.commits: dict[str, dict] = {"v1.4.0": self.commit(E)}
        self.issues: dict[str, list[dict]] = {}
        self.fail_issues = False
        self.calls: list[list[str]] = []

    @staticmethod
    def commit(sha, parents=(), files=()):
        return {"sha": sha, "parents": [{"sha": p} for p in parents], "files": [{"filename": f} for f in files]}

    @staticmethod
    def _out(obj, args):
        for flag in ("--jq", "-q"):
            if flag in args:
                return jq(args[args.index(flag) + 1], obj)
        return json.dumps(obj)

    def __call__(self, args, *, cwd=None, check=True):
        self.calls.append(args)
        if args[:2] == ["issue", "list"]:
            if self.fail_issues:
                raise core.PlatformError("HTTP 502")
            return json.dumps(self.issues.get(args[args.index("--label") + 1], []))
        assert args[0] == "api", args
        path = next(a.lstrip("/").split("?")[0] for a in args[1:] if a.lstrip("/").startswith("repos/"))
        if "/compare/" in path:
            base, head = path.split("/compare/")[1].split("...")
            tip = next((c for c in self.commits.values() if c["sha"] == head), self.commit(head))
            return self._out({"status": "ahead", "files": tip["files"], "commits": [{"sha": head}]}, args)
        ref = path.split("/commits/")[1]
        by_sha = {c["sha"]: c for c in self.commits.values()}
        return self._out(self.commits.get(ref) or by_sha.get(ref) or self.commit(ref), args)


class FakeStore:
    def __init__(self, records: dict[str, dict]):
        self.records = records           # path -> record
        self.reads = []

    def read(self, days, deadline=None):
        self.reads.append(list(days))
        return [(p, json.dumps(r)) for p, r in self.records.items()]

    def read_file(self, path, deadline=None):
        return json.dumps(self.records[path]) if path in self.records else None


def dev_rec(rid, image, at="2026-10-24T14:02:00Z", outcome="passed", staging=None, repo="acme/shop-api"):
    smoke = {"env": "dev", "outcome": outcome, "passed": 3, "failed": 0, "skipped": 0, "total": 3, "retried": outcome == "passed-on-retry",
             "failing": [], "reason": None, "image": image, "at": at, "base_url": "http://x"}
    if staging:
        smoke["staging"] = staging
    return {"run_id": rid, "kind": "ship", "repo": repo, "ended_at": at, "outcome": "done", "smoke": smoke}


def stg(outcome, image, at="2026-10-24T14:20:00Z", failing=(), reason=None):
    total = 3
    return {"env": "staging", "outcome": outcome, "passed": total - len(failing), "failed": len(failing), "skipped": 0, "total": total,
            "retried": outcome == "passed-on-retry", "failing": list(failing), "reason": reason, "image": image, "at": at,
            "base_url": "http://y"}


@pytest.fixture()
def ev(monkeypatch):
    mod = evidence_mod()
    fake = EvGh()
    monkeypatch.setattr(mod, "gh", fake)
    monkeypatch.setattr(mod, "today", lambda: date(2026, 10, 25))
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")
    fake.records = {}
    monkeypatch.setattr(mod, "open_store", lambda slug: FakeStore(fake.records))
    return fake


def summary(staging_tag=f"sha-{E}", version="v1.4.0"):
    return evidence_mod().summary(SVC, version, staging_tag)


GREEN = {"runs/2026/10/24/r1.json": dev_rec("r1", f"sha-{E}", staging=stg("passed", f"sha-{E}"))}


# ---------------- AC-093.11: what the summary says ----------------

def test_the_summary_names_the_release_the_commits_and_both_smoke_outcomes_ac_093_11(ev):  # AC-093.11
    ev.records.update(GREEN)
    lines = summary().lines()
    assert lines[0] == "evidence for shop-api v1.4.0 (commit aaaaaaa):"
    assert f"- staging runs: commit aaaaaaa (sha-{E})" in lines
    assert f"- smoke (dev): passed 3/3, 2026-10-24 14:02 UTC, {LINK.format('r1')}" in lines
    assert f"- smoke (staging): passed 3/3, 2026-10-24 14:20 UTC, {LINK.format('r1')}" in lines
    assert "- open issues (smoke-failure, alert): none" in lines
    assert not any(ln.startswith("WARNING") for ln in lines)


def test_outcome_words_follow_the_contract_ac_093_11(ev):  # AC-093.11
    ev.records["runs/2026/10/24/r1.json"] = dev_rec("r1", f"sha-{E}", outcome="passed-on-retry",
                                                    staging=stg("red", f"sha-{E}", failing=["tests/t.py::a"]))
    lines = summary().lines()
    assert any(ln.startswith("- smoke (dev): passed on retry, 2026-10-24 14:02 UTC") for ln in lines)
    assert any(ln.startswith("- smoke (staging): red (1 failing), 2026-10-24 14:20 UTC") for ln in lines)


def test_a_timed_out_and_a_not_run_outcome_are_worded_ac_093_11(ev):  # AC-093.11
    ev.records["runs/2026/10/24/r1.json"] = dev_rec(
        "r1", f"sha-{E}", outcome="timed-out", staging=stg("not-run", f"sha-{E}", reason="no staging URL for shop-api"))
    lines = summary().lines()
    assert any(ln.startswith("- smoke (dev): red (timed out after 600s)") for ln in lines)
    assert any(ln.startswith("- smoke (staging): not run: no staging URL for shop-api") for ln in lines)


def test_the_newest_record_for_the_commit_wins_ac_093_11(ev):  # AC-093.11
    ev.records["runs/2026/10/20/old.json"] = dev_rec("old", f"sha-{E}", at="2026-10-20T10:00:00Z", staging=stg("red", f"sha-{E}", failing=["x"]))
    ev.records["runs/2026/10/24/new.json"] = dev_rec("new", f"sha-{E}", staging=stg("passed", f"sha-{E}"))
    lines = summary().lines()
    assert any(ln.startswith("- smoke (staging): passed 3/3") for ln in lines)


def test_records_of_other_builds_or_repos_are_ignored_ac_093_11(ev):  # AC-093.11
    ev.records["runs/2026/10/24/a.json"] = dev_rec("a", "sha-" + "9" * 40, staging=stg("passed", "sha-" + "9" * 40))
    ev.records["runs/2026/10/24/b.json"] = dev_rec("b", f"sha-{E}", repo="acme/other", staging=stg("passed", f"sha-{E}"))
    lines = summary().lines()
    assert "- smoke (dev): no record" in " ".join(lines) or any(ln.startswith("- smoke (dev): no record") for ln in lines)


def test_a_short_image_tag_in_the_record_matches_too_ac_093_11(ev):  # AC-093.11
    ev.records.update({"runs/2026/10/24/r1.json": dev_rec("r1", "sha-" + E[:7], staging=stg("passed", "sha-" + E[:7]))})
    assert any(ln.startswith("- smoke (dev): passed 3/3") for ln in summary().lines())


def test_open_issues_of_both_labels_are_counted_once_with_their_links_ac_093_11(ev):  # AC-093.11
    ev.records.update(GREEN)
    both = {"number": 5, "title": "t", "url": "https://github.com/acme/shop-api/issues/5"}
    ev.issues = {"smoke-failure": [both, {"number": 6, "title": "u", "url": "https://github.com/acme/shop-api/issues/6"}], "alert": [both]}
    lines = summary().lines()
    line = next(ln for ln in lines if ln.startswith("- open issues (smoke-failure, alert): "))
    assert line == ("- open issues (smoke-failure, alert): 2: https://github.com/acme/shop-api/issues/5, "
                    "https://github.com/acme/shop-api/issues/6")
    labels = [c[c.index("--label") + 1] for c in ev.calls if c[:2] == ["issue", "list"]]
    assert sorted(labels) == ["alert", "smoke-failure"]
    assert all("acme/shop-api" in c and "open" in c for c in ev.calls if c[:2] == ["issue", "list"])
    assert not any(ln.startswith("WARNING") for ln in lines)                     # issues alone never warn


def test_an_unreadable_issue_list_is_unknown_and_causes_no_warning_ac_093_11(ev):  # AC-093.11
    ev.records.update(GREEN)
    ev.fail_issues = True
    s = summary()
    assert any(ln.startswith("- open issues: unknown (") or ln.startswith("open issues: unknown (") for ln in s.lines())
    assert s.warning is None


def test_the_data_is_json_for_the_json_output_ac_093_11(ev):  # AC-093.11
    ev.records.update(GREEN)
    d = summary().data()
    json.dumps(d)
    assert d["service"] == "shop-api" and d["commit"] == E and d["staging_commit"] == E and d["warning"] is None
    assert {"dev", "staging", "issues", "version"} <= set(d)


# ---------------- AC-093.12: the warning ----------------

def test_a_staging_that_runs_another_commit_warns_first_ac_093_12(ev):  # AC-093.12
    ev.records.update(GREEN)
    lines = summary(staging_tag=f"sha-{OTHER}").lines()
    assert lines[0] == "WARNING: v1.4.0 of shop-api has no green staging smoke: staging runs ddddddd, not aaaaaaa"
    assert lines[1] == "evidence for shop-api v1.4.0 (commit aaaaaaa):"


def test_a_red_staging_smoke_warns_ac_093_12(ev):  # AC-093.12
    ev.records["runs/2026/10/24/r1.json"] = dev_rec("r1", f"sha-{E}", staging=stg("red", f"sha-{E}", failing=["x"]))
    assert summary().lines()[0] == "WARNING: v1.4.0 of shop-api has no green staging smoke: staging smoke red"


def test_a_staging_smoke_that_was_not_run_warns_with_the_reason_ac_093_12(ev):  # AC-093.12
    ev.records["runs/2026/10/24/r1.json"] = dev_rec("r1", f"sha-{E}", staging=stg("not-run", f"sha-{E}", reason="no staging URL for shop-api"))
    assert summary().lines()[0] == ("WARNING: v1.4.0 of shop-api has no green staging smoke: "
                                    "staging smoke not run: no staging URL for shop-api")


def test_a_release_without_a_staging_record_warns_ac_093_12(ev):  # AC-093.12
    ev.records["runs/2026/10/24/r1.json"] = dev_rec("r1", f"sha-{E}")
    s = summary()
    assert s.lines()[0] == "WARNING: v1.4.0 of shop-api has no green staging smoke: no staging smoke record"
    assert s.warning and "no staging smoke record" in s.warning


def test_passed_on_retry_in_staging_is_green_ac_093_12(ev):  # AC-093.12
    ev.records["runs/2026/10/24/r1.json"] = dev_rec("r1", f"sha-{E}", staging=stg("passed-on-retry", f"sha-{E}"))
    assert summary().warning is None


def test_no_run_store_means_no_record_and_a_warning_ac_093_12(ev, monkeypatch):  # AC-093.12
    monkeypatch.delenv("CPLAT_RUNS_REPO")
    s = summary()
    lines = s.lines()
    assert any(ln.startswith("- smoke (dev): no record (") for ln in lines)
    assert any(ln.startswith("- smoke (staging): no record (") for ln in lines)
    assert lines[0].startswith("WARNING: v1.4.0 of shop-api has no green staging smoke: ")


def test_an_unreachable_store_is_no_record_not_a_crash_ac_093_12(ev, monkeypatch):  # AC-093.12
    mod = evidence_mod()

    def boom(slug):
        raise RuntimeError("store down")
    monkeypatch.setattr(mod, "open_store", boom)
    s = summary()
    assert s.warning and any(ln.startswith("- smoke (staging): no record (") for ln in s.lines())


def test_summary_never_raises_even_when_gh_fails_everywhere_ac_093_12(monkeypatch):  # AC-093.12
    mod = evidence_mod()

    def boom(args, **kw):
        raise core.PlatformError("HTTP 500")
    monkeypatch.setattr(mod, "gh", boom)
    monkeypatch.setattr(mod, "open_store", lambda slug: (_ for _ in ()).throw(RuntimeError("down")))
    s = summary()
    assert isinstance(s.lines(), list) and s.lines() and s.warning


# ---------------- AC-093.11: the evidence commit of a release ----------------

def release_commit(ev, files):
    ev.commits["v1.4.0"] = EvGh.commit(RELEASE, parents=[PARENT, "9" * 40], files=files)


def test_a_release_pr_merge_is_looked_up_by_its_first_parent_ac_093_11(ev):  # AC-093.11
    release_commit(ev, ["CHANGELOG.md", "pyproject.toml"])
    ev.records["runs/2026/10/24/r1.json"] = dev_rec("r1", f"sha-{PARENT}", staging=stg("passed", f"sha-{PARENT}"))
    s = summary(staging_tag=f"sha-{PARENT}")
    lines = s.lines()
    assert s.evidence_commit == PARENT and s.commit == RELEASE and s.warning is None
    assert "- evidence commit: fffffff (the release commit only changes CHANGELOG.md, pyproject.toml)" in lines
    assert any(ln.startswith("- smoke (staging): passed 3/3") for ln in lines)


def test_a_merge_that_changes_other_files_is_looked_up_as_itself_ac_093_11(ev):  # AC-093.11
    release_commit(ev, ["CHANGELOG.md", "src/app.py"])
    ev.records["runs/2026/10/24/r1.json"] = dev_rec("r1", f"sha-{PARENT}", staging=stg("passed", f"sha-{PARENT}"))
    s = summary(staging_tag=f"sha-{RELEASE}")
    assert s.evidence_commit in (None, RELEASE) and s.warning and "no staging smoke record" in s.warning
    assert not any(ln.startswith("- evidence commit:") for ln in s.lines())


def test_a_plain_commit_has_no_evidence_commit_line_ac_093_11(ev):  # AC-093.11
    ev.records.update(GREEN)
    assert not any(ln.startswith("- evidence commit:") for ln in summary().lines())


# ---------------- promote … staging prod uses it ----------------

@pytest.fixture()
def at_staging(gitops_repo, gh, ev, capsys):
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "dev", "staging", "--repo-dir", str(gitops_repo)])
    commit(gitops_repo, "promote")
    capsys.readouterr()
    return gitops_repo


def test_a_dry_run_to_prod_shows_the_summary_before_the_report_ac_093_11(at_staging, capsys):  # AC-093.11
    assert promote.main(["todo-api", "staging", "prod", "--dry-run", "--repo-dir", str(at_staging)]) == 0
    out = capsys.readouterr().out
    assert "evidence for todo-api" in out
    assert out.index("evidence for todo-api") < out.index("promote todo-api: staging")


def test_without_green_evidence_the_dry_run_starts_with_a_warning_ac_093_12(at_staging, capsys):  # AC-093.12
    promote.main(["todo-api", "staging", "prod", "--dry-run", "--repo-dir", str(at_staging)])
    out = capsys.readouterr().out.splitlines()
    first = next(ln for ln in out if ln.strip())
    assert first.startswith("WARNING: ") and "has no green staging smoke" in first


def test_the_pr_body_carries_the_summary_and_the_pr_is_still_opened_ac_093_12(at_staging, monkeypatch, capsys):  # AC-093.12
    opened = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: opened.append((branch, title, body)) or "https://github.com/acme/g/pull/5")
    assert promote.main(["todo-api", "staging", "prod", "--pr", "--repo-dir", str(at_staging)]) == 0
    ((branch, title, body),) = opened
    assert "\n\n## Evidence\n\n" in body and "evidence for todo-api" in body and "WARNING: " in body
    assert "Production promotion" in body


def test_json_output_has_the_evidence_per_service_ac_093_11(at_staging, capsys):  # AC-093.11
    promote.main(["todo-api", "staging", "prod", "--dry-run", "--json", "--repo-dir", str(at_staging)])
    data = json.loads(capsys.readouterr().out)
    assert data["evidence"]["todo-api"]["service"] == "todo-api" and data["evidence"]["todo-api"]["warning"]


def test_promoting_to_staging_shows_no_evidence_ac_093_11(gitops_repo, gh, ev, capsys):  # AC-093.11
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "dev", "staging", "--dry-run", "--repo-dir", str(gitops_repo)])
    assert "evidence for" not in capsys.readouterr().out
