"""Spec 095: `cplat deps findings|patch|report` -- the patch loop against a real temporary git repo and a fake `devbox`.

The fake world keeps a uv.lock, a list of advisories and the gates' results. `deps.devbox` and `deps.shape_of` are the seams of design.md;
git is real, so commits, the soft reset and the byte-exact revert are checked on a real repository."""
import json
import re
import subprocess
from pathlib import Path

import pytest

import core

SECURITY_LOG = "pip-audit: found {n} known vulnerabilities"
CI = ("devbox run quality && devbox run test && devbox run security && "
      "if grep -qs '\"ci-extra\"[[:space:]]*:' devbox.json; then devbox run ci-extra; fi")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


class World:
    """A service-python repo whose security gate is red while an advisory still applies to a locked version."""

    def __init__(self, repo, monkeypatch, *, shape="service-python", packages=None, ci_extra=False):
        import deps
        self.deps, self.repo, self.shape = deps, repo, shape
        self.lock = dict(packages or {"requests": "2.31.0", "urllib3": "1.26.5", "idna": "3.6", "certifi": "2024.1.1"})
        self.adv = {}              # package -> [(advisory id, fixed version or None)]
        self.reveal = {}           # package bumped -> [(other package, (advisory id, fixed))] that apply once it is bumped
        self.fail_gate = None      # "quality" | "test" | "ci-extra": red once any bump happened
        self.bump_rc = {}          # package -> exit code of deps-bump
        self.touch_pyproject = False
        self.report_override = None
        self.findings_rc = 0
        self.bumped = False
        self.other_red = False     # the security gate is red for a non-dependency reason (bandit, secrets)
        self.calls = []
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.name", "t")
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "commit.gpgsign", "false")
        scripts = {"quality": "devbox run lint", "test": "pytest", "security": "devbox run audit", "audit": "pip-audit", "ci": CI,
                   "deps-findings": "bash scripts/deps.sh findings", "deps-bump": "bash scripts/deps.sh bump"}
        if ci_extra:
            scripts["ci-extra"] = "echo extra"
        (repo / "devbox.json").write_text(json.dumps({"packages": [], "shell": {"scripts": scripts}}, indent=2))
        (repo / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0"\ndependencies = ["requests>=2"]\n')
        (repo / "tests").mkdir()
        (repo / "tests" / "test_acceptance.py").write_text("def test_a():  # AC-001.1\n    assert True\n")
        (repo / "notes.txt").write_text("notes\n")
        self.write_lock()
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")
        monkeypatch.setattr(deps, "devbox", self.devbox)
        monkeypatch.setattr(deps, "shape_of", lambda r: self.shape)

    def write_lock(self):
        (self.repo / "uv.lock").write_text("".join(f'[[package]]\nname = "{n}"\nversion = "{v}"\n\n' for n, v in self.lock.items()))

    def vulnerable(self):
        return [(p, i, f) for p, v in self.lock.items() for i, f in self.adv.get(p, []) if f is None or vkey(v) < vkey(f)]

    def report(self):
        if self.report_override is not None:
            return self.report_override
        deps = []
        for p, v in self.lock.items():
            vulns = [{"id": i, "fix_versions": [f] if f else [], "aliases": []} for q, i, f in self.vulnerable() if q == p]
            deps.append({"name": p, "version": v, "vulns": vulns})
        deps.append({"name": "app", "skip_reason": "not on PyPI"})
        return json.dumps({"dependencies": deps})

    def devbox(self, repo, args, timeout=None):
        args = list(args)
        if args[:1] == ["run"]:
            args = args[1:]
        self.calls.append(args)
        name = args[0]

        def cp(rc, out="", err=""):
            return subprocess.CompletedProcess(args, rc, out, err)
        if name == "deps-findings":
            if self.findings_rc:
                return cp(self.findings_rc, "", "pip-audit: no network")
            Path(args[1]).write_text(self.report())
            return cp(0)
        if name == "deps-bump":
            pkg, ver = args[1], args[2]
            if pkg not in self.lock:
                return cp(2, "", f"deps-bump: {pkg} is not a dependency of this repo")
            if self.bump_rc.get(pkg):
                return cp(self.bump_rc[pkg], "", f"resolution conflict for {pkg}\nno solution found")
            self.lock[pkg], self.bumped = ver, True
            self.write_lock()
            if self.touch_pyproject:
                with open(self.repo / "pyproject.toml", "a") as f:
                    f.write(f'\n[tool.uv]\nconstraint-dependencies = ["{pkg}>={ver}"]\n')
            for other, adv in self.reveal.get(pkg, []):
                self.adv.setdefault(other, []).append(adv)
            return cp(0)
        if name == "security":
            bad = self.vulnerable()
            if self.other_red and not bad:
                return cp(1, "bandit: 1 issue found", "")
            return cp(1, SECURITY_LOG.format(n=len(bad)), "") if bad else cp(0, "No known vulnerabilities found")
        if name == self.fail_gate and self.bumped:
            if name == "test":
                return cp(1, "collected 9 items\n" + "".join(f"FAILED tests/test_app.py::test_case{i} - AssertionError\n" for i in range(7)))
            return cp(1, f"{name} log line 1\n{name} exploded after the bump\n")
        return cp(0, f"{name} ok")

    def gate_steps(self):
        return [c[0] for c in self.calls if c[0] in ("quality", "test", "security", "ci-extra")]

    def bump_calls(self):
        return [tuple(c[1:3]) for c in self.calls if c[0] == "deps-bump"]

    def head(self):
        return git(self.repo, "rev-parse", "HEAD")

    def run(self, capsys, *argv):
        capsys.readouterr()
        try:
            rc = self.deps.main([*argv, "--dir", str(self.repo)])
        except core.PlatformError as e:
            rc = 1
            print(f"error: {e}")
        return rc, capsys.readouterr().out

    def patch(self, capsys):
        return self.run(capsys, "patch")

    def state(self):
        return json.loads((self.repo / ".git" / "cplat-deps.json").read_text())


@pytest.fixture()
def make(tmp_path, monkeypatch):
    n = [0]

    def factory(**kw):
        n[0] += 1
        return World(tmp_path / f"repo{n[0]}", monkeypatch, **kw)
    return factory


def one_advisory(w, pkg="urllib3", adv=("GHSA-1", "1.26.18")):
    w.adv[pkg] = [adv]
    return w


# ---------------- AC-095.12: the red gate is handled by bumping ----------------

def test_cplat_registers_the_deps_command():  # AC-095.12
    import cplat
    assert cplat.COMMANDS["deps"] == "deps"


def test_patch_bumps_to_the_lowest_fixed_version_reruns_the_gates_and_continues(make, capsys):  # AC-095.12
    w = one_advisory(make())
    rc, out = w.patch(capsys)
    assert rc == 0, out
    assert w.bump_calls() == [("urllib3", "1.26.18")]
    assert w.gate_steps() == ["quality", "test", "security"]  # ci-extra only runs when the repo defines it
    assert 'name = "urllib3"\nversion = "1.26.18"' in (w.repo / "uv.lock").read_text()
    assert "PATCHED: urllib3 1.26.5 -> 1.26.18 (GHSA-1, UNRATED)" in out
    assert "GREEN: every gate passed after patch round 1 of 2" in out
    assert "ESCALATE" not in out


def test_patch_runs_ci_extra_when_the_repo_defines_it(make, capsys):  # AC-095.12
    w = one_advisory(make(ci_extra=True))
    rc, _ = w.patch(capsys)
    assert rc == 0 and w.gate_steps() == ["quality", "test", "security", "ci-extra"]


def test_patch_takes_the_highest_of_the_lowest_fixes_so_one_bump_fixes_every_advisory(make, capsys):  # AC-095.12
    w = make()
    w.adv["urllib3"] = [("GHSA-1", "1.26.18"), ("PYSEC-2", "1.26.19")]
    rc, out = w.patch(capsys)
    assert rc == 0 and w.bump_calls() == [("urllib3", "1.26.19")]
    assert "(GHSA-1, PYSEC-2, UNRATED)" in out


def test_findings_text_json_and_the_clean_message(make, capsys):  # AC-095.2 AC-095.12
    w = make()
    w.adv["urllib3"] = [("GHSA-1", "1.26.18")]
    w.adv["certifi"] = [("PYSEC-X", None)]
    rc, out = w.run(capsys, "findings")
    assert rc == 0
    assert "urllib3 1.26.5 -> 1.26.18 GHSA-1 UNRATED transitive" in out
    assert "certifi 2024.1.1 -> no fix released PYSEC-X UNRATED transitive" in out
    rc, out = w.run(capsys, "findings", "--json")
    data = json.loads(out)
    assert rc == 0 and {d["package"]: d["fixed"] for d in data} == {"certifi": None, "urllib3": "1.26.18"}
    assert {"package", "installed", "fixed", "advisories", "severity", "transitive", "major", "kind"} <= set(data[0])
    w.adv.clear()
    rc, out = w.run(capsys, "findings")
    assert rc == 0 and "no dependency finding turns the security gate red" in out


# ---------------- AC-095.3: the contract with the repo's recipes ----------------

def test_findings_fails_when_the_repo_has_no_deps_findings_recipe(make, capsys):  # AC-095.3
    w = make()
    cfg = json.loads((w.repo / "devbox.json").read_text())
    del cfg["shell"]["scripts"]["deps-findings"]
    (w.repo / "devbox.json").write_text(json.dumps(cfg))
    rc, out = w.run(capsys, "findings")
    assert rc == 1 and "deps-findings" in out and w.calls == []
    rc, out = w.patch(capsys)
    assert rc == 1 and w.bump_calls() == []


def test_findings_reports_a_failing_scanner_with_its_last_line(make, capsys):  # AC-095.3
    w = one_advisory(make())
    w.findings_rc = 1
    rc, out = w.run(capsys, "findings")
    assert rc == 1 and "deps-findings failed: pip-audit: no network" in out


# ---------------- AC-095.4: own commits, PR section ----------------

def test_each_bump_is_its_own_signed_commit_touching_only_dependency_files(make, capsys):  # AC-095.4
    w = make()
    w.adv["urllib3"] = [("GHSA-1", "1.26.18"), ("PYSEC-2", "1.26.19")]
    w.adv["idna"] = [("PYSEC-2024-60", "3.7")]
    (w.repo / "notes.txt").write_text("staged change\n")
    git(w.repo, "add", "notes.txt")
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 0, out
    subjects = git(w.repo, "log", "--format=%s", f"{pre}..HEAD").splitlines()
    assert sorted(subjects) == ["fix(deps): bump idna 3.6 -> 3.7 (PYSEC-2024-60)",
                                "fix(deps): bump urllib3 1.26.5 -> 1.26.19 (GHSA-1, PYSEC-2)"]
    for sha in git(w.repo, "rev-list", f"{pre}..HEAD").splitlines():
        assert git(w.repo, "show", "--name-only", "--format=", sha).splitlines() == ["uv.lock"]
        assert "Signed-off-by:" in git(w.repo, "show", "-s", "--format=%B", sha)
    assert git(w.repo, "diff", "--cached", "--name-only").splitlines() == ["notes.txt"]  # other staged changes stay staged


def test_patch_refuses_uncommitted_dependency_files(make, capsys):  # AC-095.4
    w = one_advisory(make())
    (w.repo / "uv.lock").write_text((w.repo / "uv.lock").read_text() + "# hand edit\n")
    rc, out = w.patch(capsys)
    assert rc == 1 and "uv.lock has uncommitted changes" in out and w.bump_calls() == []


def test_report_lists_the_patched_bumps_as_a_table(make, capsys):  # AC-095.4
    w = make()
    w.adv["idna"] = [("PYSEC-2024-60", "3.7")]
    w.adv["urllib3"] = [("GHSA-34jh-p97f-mpxf", "2.2.2")]
    assert w.patch(capsys)[0] == 0
    rc, out = w.run(capsys, "report")
    assert rc == 0
    lines = [ln.rstrip() for ln in out.splitlines()]
    assert lines[0] == "## Dependency patches"
    assert "Bumped automatically because the security gate was red (spec 095)." in lines
    assert "| Package | From | To | Advisory | Severity | Note |" in lines
    assert "| idna | 3.6 | 3.7 | PYSEC-2024-60 | UNRATED | |" in lines
    assert "| urllib3 | 1.26.5 | 2.2.2 | GHSA-34jh-p97f-mpxf | UNRATED | major bump |" in lines  # AC-095.17


def test_report_replaces_or_appends_the_section_in_a_body_file(make, capsys, tmp_path):  # AC-095.4
    w = one_advisory(make())
    assert w.patch(capsys)[0] == 0
    body = tmp_path / "body.md"
    body.write_text("## Summary\nx\n\n## Dependency patches\nold table\n\n## Checklist\n- [x] done\n")
    assert w.run(capsys, "report", "--body-file", str(body))[0] == 0
    text = body.read_text()
    assert "old table" not in text and "| urllib3 | 1.26.5 | 1.26.18 | GHSA-1 | UNRATED | |" in text
    assert "## Summary\nx" in text and "## Checklist\n- [x] done" in text and text.count("## Dependency patches") == 1
    body.write_text("## Summary\nx\n")
    assert w.run(capsys, "report", "--body-file", str(body))[0] == 0
    assert body.read_text().startswith("## Summary\nx\n") and "## Dependency patches" in body.read_text()


def test_report_without_bumps_prints_nothing_and_writes_nothing(make, capsys, tmp_path):  # AC-095.4
    w = make()
    body = tmp_path / "body.md"
    body.write_text("## Summary\nx\n")
    rc, out = w.run(capsys, "report", "--body-file", str(body))
    assert rc == 0 and out.strip() == "" and body.read_text() == "## Summary\nx\n"


# ---------------- AC-095.17: major bumps ----------------

def test_a_major_bump_with_green_gates_is_kept_and_marked(make, capsys):  # AC-095.17
    w = one_advisory(make(), adv=("GHSA-34jh-p97f-mpxf", "2.2.2"))
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 0, out
    assert "PATCHED: urllib3 1.26.5 -> 2.2.2 (GHSA-34jh-p97f-mpxf, UNRATED) major bump" in out
    assert w.head() != pre and git(w.repo, "log", "-1", "--format=%s").startswith("fix(deps): bump urllib3 1.26.5 -> 2.2.2")


def test_a_major_bump_with_a_red_gate_is_reverted_like_any_other(make, capsys):  # AC-095.17 AC-095.6
    w = one_advisory(make(), adv=("GHSA-34jh-p97f-mpxf", "2.2.2"))
    w.fail_gate = "test"
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 3 and w.head() == pre and "ESCALATE: bump reverted: urllib3 1.26.5 -> 2.2.2 turned test red" in out


# ---------------- AC-095.6: red gate after a bump -> exact revert ----------------

@pytest.mark.parametrize("gate", ["quality", "test", "ci-extra"])
def test_a_red_gate_reverts_the_bump_byte_for_byte_and_escalates(make, capsys, gate):  # AC-095.6
    w = one_advisory(make(ci_extra=gate == "ci-extra"))
    w.touch_pyproject = True
    w.fail_gate = gate
    (w.repo / "notes.txt").write_text("unrelated unstaged edit\n")
    before = {f: (w.repo / f).read_bytes() for f in ("uv.lock", "pyproject.toml")}
    acceptance = (w.repo / "tests" / "test_acceptance.py").read_bytes()
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 3, out
    first, second = out.splitlines()[:2]
    assert first.startswith(f"ESCALATE: bump reverted: urllib3 1.26.5 -> 1.26.18 turned {gate} red: ")
    assert second == "CAUSE: code"
    assert w.head() == pre
    assert {f: (w.repo / f).read_bytes() for f in before} == before
    assert git(w.repo, "diff", pre, "--", "uv.lock", "pyproject.toml") == ""
    assert git(w.repo, "status", "--porcelain", "--", "uv.lock", "pyproject.toml") == ""
    assert (w.repo / "tests" / "test_acceptance.py").read_bytes() == acceptance
    assert (w.repo / "notes.txt").read_text() == "unrelated unstaged edit\n"  # cplat touches no other file
    assert any(ln.startswith("  ") and gate in ln for ln in out.splitlines()[2:])  # the log tail, indented two spaces


def test_the_reason_names_at_most_five_failing_tests(make, capsys):  # AC-095.6
    w = one_advisory(make())
    w.fail_gate = "test"
    rc, out = w.patch(capsys)
    reason = out.splitlines()[0]
    assert rc == 3 and reason.count("tests/test_app.py::test_case") == 5 and "test_case4" in reason and "test_case5" not in reason


def test_a_failing_recipe_reverts_the_whole_round(make, capsys):  # AC-095.6
    w = make()
    w.adv["idna"] = [("PYSEC-2024-60", "3.7")]
    w.adv["urllib3"] = [("GHSA-1", "1.26.18")]
    w.bump_rc["urllib3"] = 1  # idna is bumped (and committed) first, then urllib3 fails
    before = (w.repo / "uv.lock").read_bytes()
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 3, out
    assert out.splitlines()[0].startswith("ESCALATE: bump failed: urllib3 1.26.5 -> 1.26.18 (GHSA-1): ")
    assert "no solution found" in out.splitlines()[0] and out.splitlines()[1] == "CAUSE: code"
    assert w.head() == pre and (w.repo / "uv.lock").read_bytes() == before
    assert w.gate_steps() == []


def test_a_bump_that_reveals_an_unfixable_finding_is_reverted(make, capsys):  # AC-095.6
    w = one_advisory(make())
    w.reveal["urllib3"] = [("idna", ("PYSEC-NOFIX", None))]
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 3 and w.head() == pre
    assert out.splitlines()[0].startswith("ESCALATE: bump reverted: urllib3 1.26.5 -> 1.26.18 turned security red")


# ---------------- AC-095.13: no fix -> nothing changes, escalate ----------------

def test_a_finding_without_a_fix_escalates_and_changes_nothing(make, capsys):  # AC-095.13
    w = one_advisory(make())
    w.adv["certifi"] = [("PYSEC-X", None)]
    pre, before = w.head(), (w.repo / "uv.lock").read_bytes()
    rc, out = w.patch(capsys)
    assert rc == 3, out
    assert out.splitlines()[0] == "ESCALATE: no fix released: certifi 2024.1.1 (PYSEC-X)"
    assert out.splitlines()[1] == "CAUSE: decision"
    assert w.bump_calls() == [] and w.head() == pre and (w.repo / "uv.lock").read_bytes() == before  # not even the fixable one


def test_a_go_toolchain_finding_escalates_with_the_devbox_hint(make, capsys):  # AC-095.13 AC-095.16
    w = make(shape="service-go")
    w.report_override = (Path(__file__).parent / "fixtures" / "deps" / "govulncheck.jsonl").read_text()
    (w.repo / "go.mod").write_text("module m\n\ngo 1.22\n\nrequire golang.org/x/net v0.20.0\n")
    git(w.repo, "add", "-A")
    git(w.repo, "commit", "-qm", "go")
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 3 and w.bump_calls() == [] and w.head() == pre
    assert "toolchain finding: stdlib go1.22.1 -> go1.22.5 (GO-2024-0001): bump go in devbox.json" in out
    assert out.splitlines()[1] == "CAUSE: decision"


# ---------------- AC-095.14: at most 2 patch rounds ----------------

def test_another_fixable_finding_after_the_first_patch_is_a_second_round(make, capsys):  # AC-095.14
    w = one_advisory(make())
    w.reveal["urllib3"] = [("idna", ("PYSEC-2024-60", "3.7"))]
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 0, out
    assert w.bump_calls() == [("urllib3", "1.26.18"), ("idna", "3.7")]
    assert w.gate_steps() == ["quality", "test", "security"] * 2
    assert "PATCHED: urllib3 1.26.5 -> 1.26.18" in out and "PATCHED: idna 3.6 -> 3.7" in out
    assert "GREEN: every gate passed after patch round 2 of 2" in out
    assert len(git(w.repo, "rev-list", f"{pre}..HEAD").splitlines()) == 2
    assert w.state()["rounds"] == 2


def test_a_third_round_escalates_listing_the_open_findings(make, capsys):  # AC-095.14
    w = one_advisory(make())
    w.adv["certifi"] = []
    w.reveal["urllib3"] = [("idna", ("PYSEC-2024-60", "3.7"))]
    w.reveal["idna"] = [("certifi", ("PYSEC-C", "2025.1.1"))]
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 3, out
    assert out.splitlines()[0] == "ESCALATE: patch rounds exhausted (2 of 2): still open: certifi 2024.1.1 -> 2025.1.1 (PYSEC-C)"
    assert out.splitlines()[1] == "CAUSE: decision"
    assert w.bump_calls() == [("urllib3", "1.26.18"), ("idna", "3.7")]
    assert len(git(w.repo, "rev-list", f"{pre}..HEAD").splitlines()) == 2  # the bumps of rounds 1 and 2 each fixed their own finding: kept
    calls = len(w.calls)
    rc, out = w.patch(capsys)  # the same run asks again: no third round
    assert rc == 3 and "patch rounds exhausted (2 of 2)" in out and w.bump_calls() == [("urllib3", "1.26.18"), ("idna", "3.7")]
    assert not [c for c in w.calls[calls:] if c[0] == "deps-bump"]


def test_a_new_run_key_starts_with_fresh_rounds(make, capsys):  # AC-095.14
    w = one_advisory(make())
    w.adv["certifi"] = []
    w.reveal["urllib3"] = [("idna", ("PYSEC-2024-60", "3.7"))]
    w.reveal["idna"] = [("certifi", ("PYSEC-C", "2025.1.1"))]
    assert w.patch(capsys)[0] == 3
    git(w.repo, "checkout", "-q", "-b", "feature/other")  # no run pointer: the key is the branch
    rc, out = w.patch(capsys)
    assert rc == 0, out
    assert ("certifi", "2025.1.1") in w.bump_calls() and "patch round 1 of 2" in out


# ---------------- AC-095.16: not ours ----------------

def test_gitops_app_never_bumps(make, capsys):  # AC-095.16
    w = make(shape="gitops-app")
    rc, out = w.patch(capsys)
    assert rc == 4 and "NOT A DEPENDENCY FINDING: gitops-app repos never bump dependencies (spec 095)" in out
    assert w.calls == []


def test_a_red_gate_without_a_dependency_finding_is_left_to_the_security_agent(make, capsys):  # AC-095.16
    w = make()  # bandit, secrets or a scanner error: the dependency report is clean
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 4 and "NOT A DEPENDENCY FINDING: the security gate is red for another reason" in out
    assert w.bump_calls() == [] and w.head() == pre and w.gate_steps() == []


# ---------------- AC-095.11: the run record's `patches` section ----------------

def start_run(w):
    import runs
    rid = runs.start("build", repo="acme/app", spec="095-x")
    (w.repo / ".git" / "cplat-run.json").write_text(json.dumps({"run_id": rid}))
    return runs, rid


def test_a_patch_is_recorded_once_per_package(make, capsys):  # AC-095.11
    w = make()
    w.adv["urllib3"] = [("GHSA-34jh-p97f-mpxf", "2.2.2")]
    runs, rid = start_run(w)
    assert w.patch(capsys)[0] == 0
    assert runs.active(rid)["patches"] == [{"id": "urllib3", "package": "urllib3", "from": "1.26.5", "to": "2.2.2",
                                            "advisory": "GHSA-34jh-p97f-mpxf", "severity": "UNRATED", "major": True,
                                            "outcome": "patched", "round": 1}]


def test_a_reverted_bump_and_a_no_fix_finding_are_recorded(make, capsys):  # AC-095.11
    w = one_advisory(make())
    w.fail_gate = "test"
    runs, rid = start_run(w)
    assert w.patch(capsys)[0] == 3
    [entry] = runs.active(rid)["patches"]
    assert entry["package"] == "urllib3" and entry["outcome"] == "reverted" and entry["to"] == "1.26.18" and entry["from"] == "1.26.5"
    w2 = one_advisory(make(), pkg="certifi", adv=("PYSEC-X", None))
    runs, rid = start_run(w2)
    assert w2.patch(capsys)[0] == 3
    [entry] = runs.active(rid)["patches"]
    assert entry["outcome"] == "no-fix" and entry["to"] is None and entry["advisory"] == "PYSEC-X" and entry["from"] == "2024.1.1"


def test_a_package_has_one_entry_holding_its_last_state(make, capsys):  # AC-095.11
    w = one_advisory(make())
    w.reveal["urllib3"] = [("idna", ("PYSEC-2024-60", "3.7"))]
    runs, rid = start_run(w)
    assert w.patch(capsys)[0] == 0
    assert sorted(e["package"] for e in runs.active(rid)["patches"]) == ["idna", "urllib3"]
    assert {e["package"]: e["round"] for e in runs.active(rid)["patches"]} == {"urllib3": 1, "idna": 2}


def test_without_a_run_record_the_patch_proceeds(make, capsys):  # AC-095.11
    w = one_advisory(make())
    rc, out = w.patch(capsys)
    assert rc == 0 and "GREEN" in out


# ---------------- AC-095.15: a patch in `land` ----------------

def test_report_update_pr_edits_the_ships_pr_body(make, capsys, monkeypatch, tmp_path):  # AC-095.15
    w = one_advisory(make())
    assert w.patch(capsys)[0] == 0
    (w.repo / ".git" / "cplat-ship.json").write_text(json.dumps({"pr": 42, "phase": "land", "run_id": None}))
    body = tmp_path / "PR_BODY.md"
    body.write_text("## Summary\nx\n")
    seen = []
    real = core.run

    def fake_run(cmd, **kw):
        if cmd[0] == "gh":
            seen.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real(cmd, **kw)
    monkeypatch.setattr(core, "run", fake_run)
    rc, out = w.run(capsys, "report", "--body-file", str(body), "--update-pr")
    assert rc == 0, out
    assert seen == [["gh", "pr", "edit", "42", "--body-file", str(body)]]
    assert "| urllib3 | 1.26.5 | 1.26.18 | GHSA-1 | UNRATED | |" in body.read_text()


def test_report_update_pr_without_a_pr_is_a_no_op_and_a_gh_failure_is_exit_1(make, capsys, monkeypatch, tmp_path):  # AC-095.15
    w = one_advisory(make())
    assert w.patch(capsys)[0] == 0
    body = tmp_path / "PR_BODY.md"
    body.write_text("## Summary\nx\n")
    real = core.run
    calls = []

    def fake_run(cmd, **kw):
        if cmd[0] == "gh":
            calls.append(cmd)
            if kw.get("check", True):
                raise core.PlatformError("`gh pr edit` failed (exit 1): boom")
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        return real(cmd, **kw)
    monkeypatch.setattr(core, "run", fake_run)
    assert w.run(capsys, "report", "--body-file", str(body), "--update-pr")[0] == 0 and calls == []
    (w.repo / ".git" / "cplat-ship.json").write_text(json.dumps({"pr": 7}))
    assert w.run(capsys, "report", "--body-file", str(body), "--update-pr")[0] == 1 and calls


def test_a_red_pr_check_counts_in_the_existing_fix_round_limit():  # AC-095.15
    """No ship.py change is needed: `cplat ship land` already counts every red PR check as one of the 3 CI fix rounds."""
    import ship
    src = (Path(ship.__file__)).read_text()
    assert 'st["fix_rounds"] = st.get("fix_rounds", 0) + 1' in src


def test_a_good_bump_is_kept_when_only_a_non_dependency_check_stays_red(make, capsys):  # AC-095.12
    w = one_advisory(make())
    w.other_red = True
    pre = w.head()
    rc, out = w.patch(capsys)
    assert rc == 4 and "PATCHED: urllib3 1.26.5 -> 1.26.18" in out and "NOT A DEPENDENCY FINDING" in out
    assert w.lock["urllib3"] == "1.26.18" and w.head() != pre and "reverted" not in out
