"""Spec 086: /shared:update-service keeps the repo's companions (ci-extra, permission entries, notes file) and lists what it replaced.

Every test fakes `update.render_baseline`: CI checkouts may have no tags. The "baseline" is a second render of the current
template that a test edits to look like the template at the repo's previous platform version.
"""
import json
import subprocess

import pytest

import update

NAME = "upd-go"
STEP = "if grep -qs '\"ci-extra\"[[:space:]]*:' devbox.json; then devbox run ci-extra; fi"
OLD_CI = "devbox run quality && devbox run test && devbox run security"


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


def commit(repo, msg="own changes"):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


def render(new_service, parent):
    new_service([NAME, "desc", "--type", "service", "--lang", "go", "--no-github", "--skip-tasks", "--dir", str(parent), "--org", "acme"])
    return parent / NAME


def rd(repo):
    return json.loads((repo / "devbox.json").read_text())


def wd(repo, d):
    (repo / "devbox.json").write_text(json.dumps(d, indent=2) + "\n")


def rs(repo):
    return json.loads((repo / ".claude" / "settings.json").read_text())


def ws(repo, d):
    (repo / ".claude" / "settings.json").write_text(json.dumps(d, indent=2) + "\n")


def edit_devbox(repo, **scripts):
    d = rd(repo)
    d["shell"]["scripts"].update(scripts)
    wd(repo, d)


@pytest.fixture()
def pair(tmp_path, new_service):
    """(repo, baseline): both are the current template; the repo carries an old platform stamp."""
    repo, base = render(new_service, tmp_path / "repo"), render(new_service, tmp_path / "base")
    (repo / ".platform-version").write_text("platform: 4.4.0\nshape: service-go\nref: main\n")
    commit(repo, "old stamp")
    return repo, base


def go(repo, monkeypatch, capsys, baseline, *extra):
    """Run the update with `baseline` as the render of the previous version (None: it cannot be rendered); returns its --json."""
    monkeypatch.setattr(update, "render_baseline", lambda *a, **k: baseline)
    capsys.readouterr()
    assert update.main(["--repo", str(repo), "--skip-tasks", "--json", "--migrate", *extra]) == 0
    return json.loads(capsys.readouterr().out)


def lost(out, **match):
    return [e for e in out["lost"] if all(e.get(k) == v for k, v in match.items())]


# ---------------- ci-extra survives (AC-086.4) ----------------

def test_update_leaves_ci_extra_alone_and_ci_still_ends_with_it(pair, monkeypatch, capsys):  # AC-086.4
    repo, base = pair
    for r in (repo, base):
        edit_devbox(r, ci=OLD_CI)                                  # both old: no ci-extra step yet
    edit_devbox(repo, **{"ci-extra": "devbox run chart-lint", "chart-lint": "helm lint charts"})
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    scripts = rd(repo)["shell"]["scripts"]
    assert scripts["ci-extra"] == "devbox run chart-lint" and scripts["ci"].endswith(" && " + STEP)
    assert not [r for r in out["devbox"]["replaced"] if "ci-extra" in r["entry"]]
    assert out["devbox"]["moved_to_ci_extra"] == [] and out["lost"] == []


# ---------------- gates move into ci-extra (AC-086.6) ----------------

def test_gates_of_the_old_ci_move_into_a_new_ci_extra(pair, monkeypatch, capsys):  # AC-086.6
    repo, base = pair
    edit_devbox(base, ci=OLD_CI)
    edit_devbox(repo, ci=OLD_CI + " && devbox run chart-lint && devbox run helm-docs", **{"chart-lint": "helm lint", "helm-docs": "helm-docs"})
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    scripts = rd(repo)["shell"]["scripts"]
    assert scripts["ci-extra"] == "devbox run chart-lint && devbox run helm-docs" and scripts["ci"].endswith(STEP)
    assert out["devbox"]["moved_to_ci_extra"] == ["chart-lint", "helm-docs"] and out["devbox"]["dropped_gates"] == []
    assert "moved to ci-extra: chart-lint, helm-docs" in out["did"]
    assert out["lost"] == []                                     # moving loses nothing; `ci` is not a replaced recipe


def test_an_existing_ci_extra_is_not_changed_and_the_dropped_gates_are_named(pair, monkeypatch, capsys):  # AC-086.6
    repo, base = pair
    edit_devbox(base, ci=OLD_CI)
    edit_devbox(repo, ci=OLD_CI + " && devbox run chart-lint", **{"ci-extra": "devbox run helm-docs", "chart-lint": "helm lint"})
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    assert rd(repo)["shell"]["scripts"]["ci-extra"] == "devbox run helm-docs"
    assert out["devbox"]["dropped_gates"] == ["chart-lint"] and out["devbox"]["moved_to_ci_extra"] == []
    line = next(s for s in out["next"] if "dropped from ci" in s)
    assert "chart-lint" in line and '"ci-extra": "devbox run helm-docs && devbox run chart-lint"' in line
    assert [e["entry"] for e in lost(out, kind="gate")] == ["chart-lint"]          # AC-086.13


def test_a_gate_the_platform_removed_from_ci_is_not_moved(pair, monkeypatch, capsys):  # AC-086.6
    repo, base = pair
    edit_devbox(base, ci=OLD_CI + " && devbox run legacy", legacy="true")          # the old template ran it
    edit_devbox(repo, ci=OLD_CI + " && devbox run legacy", legacy="true")
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    assert "ci-extra" not in rd(repo)["shell"]["scripts"] and out["devbox"]["moved_to_ci_extra"] == []


def test_without_a_baseline_every_missing_gate_is_moved(pair, monkeypatch, capsys):  # AC-086.6
    repo, _ = pair
    edit_devbox(repo, ci=OLD_CI + " && devbox run legacy", legacy="true")
    commit(repo)
    out = go(repo, monkeypatch, capsys, None)
    assert rd(repo)["shell"]["scripts"]["ci-extra"] == "devbox run legacy"
    assert out["baseline"] is None and out["devbox"]["moved_to_ci_extra"] == ["legacy"]


# ---------------- permissions (AC-086.10, .11) ----------------

def test_the_repos_permission_entries_survive(pair, monkeypatch, capsys):  # AC-086.10
    repo, base = pair
    for r in (repo, base):
        s = rs(r)
        s["permissions"]["allow"].remove("Bash(cplat *)")          # an older template had fewer entries
        ws(r, s)
    s = rs(repo)
    s["permissions"]["allow"].append("Bash(helm *)")
    s["permissions"].setdefault("ask", []).append("Bash(terraform apply *)")
    s["permissions"].setdefault("deny", []).append("Bash(rm -rf /*)")
    ws(repo, s)
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    p = rs(repo)["permissions"]
    assert "Bash(cplat *)" in p["allow"] and "Bash(helm *)" in p["allow"]
    assert "Bash(terraform apply *)" in p["ask"] and "Bash(rm -rf /*)" in p["deny"]
    assert {(k["list"], k["entry"]) for k in out["settings"]["kept"]} == {("allow", "Bash(helm *)"), ("ask", "Bash(terraform apply *)"), ("deny", "Bash(rm -rf /*)")}
    assert any(d.startswith("kept in .claude/settings.json:") and "allow Bash(helm *)" in d for d in out["did"])
    assert out["lost"] == []                                       # kept entries are not losses


def test_an_entry_the_platform_removed_goes_even_if_the_repo_has_it(pair, monkeypatch, capsys):  # AC-086.11
    repo, base = pair
    for r in (repo, base):
        s = rs(r)
        s["permissions"]["allow"].append("Bash(oldtool *)")
        ws(r, s)
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    assert "Bash(oldtool *)" not in rs(repo)["permissions"]["allow"]
    assert out["settings"]["removed_by_platform"] == [{"list": "allow", "entry": "Bash(oldtool *)"}]
    assert any(d.startswith("removed by the platform from .claude/settings.json:") for d in out["did"])
    assert out["lost"] == []                                       # the repo did not add it


def test_without_a_baseline_every_entry_is_kept(pair, monkeypatch, capsys):  # AC-086.11
    repo, _ = pair
    s = rs(repo)
    s["permissions"]["allow"].append("Bash(oldtool *)")
    ws(repo, s)
    commit(repo)
    go(repo, monkeypatch, capsys, None)
    assert "Bash(oldtool *)" in rs(repo)["permissions"]["allow"]


# ---------------- what is replaced, and where it belongs (AC-086.12, .13) ----------------

def test_replaced_settings_and_skeleton_files_say_where_the_addition_belongs(pair, monkeypatch, capsys):  # AC-086.12
    repo, base = pair
    s = rs(repo)
    s["worktree"] = {"baseRef": "main"}
    ws(repo, s)
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(ci.read_text() + "\n  chart-lint:\n    runs-on: ubuntu-latest\n    steps:\n      - run: helm lint\n")
    (repo / "CLAUDE.md").write_text((repo / "CLAUDE.md").read_text() + "\nOur own rule.\n")
    (repo / ".golangci.yml").write_text("# my lint config\n")
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    assert rs(repo)["worktree"] == {"baseRef": "head"} and "chart-lint" not in ci.read_text()
    s_ = lost(out, kind="setting")
    assert [e["entry"] for e in s_] == ["worktree"] and s_[0]["file"] == ".claude/settings.json"
    assert "only your own permission entries" in s_[0]["where"]
    f = {e["file"]: e["where"] for e in lost(out, kind="file")}
    assert set(f) == {".github/workflows/ci.yml", "CLAUDE.md", ".golangci.yml"}
    assert "ci-extra" in f[".github/workflows/ci.yml"] and "workflow file of your own" in f[".github/workflows/ci.yml"]
    assert ".claude/project-notes.md" in f["CLAUDE.md"]
    assert "git checkout HEAD~1 -- .golangci.yml" in f[".golangci.yml"] and "/shared:report-issue" in f[".golangci.yml"]
    assert any(s.startswith("replaced .github/workflows/ci.yml: the template's version wins;") for s in out["next"])
    assert not any("review MODIFIED" in s for s in out["next"])


def test_a_replaced_recipe_is_listed_with_its_old_line(pair, monkeypatch, capsys):  # AC-086.13
    repo, base = pair
    edit_devbox(repo, test="go test ./... -v")
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    e = lost(out, kind="recipe")
    assert [x["entry"] for x in e] == ["scripts test"] and e[0]["was"] == "go test ./... -v" and e[0]["file"] == "devbox.json"
    assert out["baseline"] == "4.4.0"


def test_template_changes_the_repo_never_touched_are_not_losses(pair, monkeypatch, capsys):  # AC-086.13
    repo, base = pair
    for r in (repo, base):                                          # the old template had other lint config and an older test line
        (r / ".golangci.yml").write_text("# old lint config\n")
        edit_devbox(r, test="go test ./...")
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    assert ".golangci.yml" in out["modified"] and "# old lint config" not in (repo / ".golangci.yml").read_text()
    assert out["lost"] == [] and out["devbox"]["replaced"] == []


def test_without_a_baseline_every_difference_counts_as_a_loss(pair, monkeypatch, capsys):  # AC-086.13
    repo, _ = pair
    (repo / ".golangci.yml").write_text("# old lint config\n")
    commit(repo)
    out = go(repo, monkeypatch, capsys, None)
    assert out["baseline"] is None and [e["file"] for e in lost(out, kind="file")] == [".golangci.yml"]


def test_a_noop_update_renders_no_baseline_and_emits_no_lost_list(tmp_path, monkeypatch, capsys, new_service):  # AC-086.13
    repo = render(new_service, tmp_path)

    def boom(*a, **k):
        raise AssertionError("a no-op update must not render a baseline")
    monkeypatch.setattr(update, "render_baseline", boom)
    capsys.readouterr()
    assert update.main(["--repo", str(repo), "--skip-tasks", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "lost" not in out and "nothing changed" in " ".join(out["did"])


# ---------------- repo-owned files stay (AC-086.14, .16) ----------------

def test_a_workflow_the_template_does_not_ship_is_untouched(pair, monkeypatch, capsys):  # AC-086.14
    repo, base = pair
    own = repo / ".github" / "workflows" / "chart-lint.yml"
    own.write_text("name: chart-lint\non: pull_request\njobs: {}\n")
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    assert own.read_text().startswith("name: chart-lint")
    path = ".github/workflows/chart-lint.yml"
    assert path not in out["modified"] and path not in [e["file"] for e in out["lost"]] and "lost" in out


def test_the_notes_file_is_never_changed_and_claude_md_loads_it(pair, monkeypatch, capsys):  # AC-086.16
    repo, base = pair
    notes = repo / ".claude" / "project-notes.md"
    notes.write_text("We deploy to eu-west only.\n")
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    assert notes.read_text() == "We deploy to eu-west only.\n"
    assert ".claude/project-notes.md" not in out["modified"] and ".claude/project-notes.md" not in out["changed"]
    assert "@.claude/project-notes.md" in (repo / "CLAUDE.md").read_text()


def test_a_repo_without_the_notes_file_gets_a_working_claude_md_and_no_new_file(pair, monkeypatch, capsys):  # AC-086.16
    repo, base = pair
    notes = repo / ".claude" / "project-notes.md"
    if notes.exists():
        notes.unlink()
        commit(repo, "no notes")
    out = go(repo, monkeypatch, capsys, base)
    assert not notes.exists() and "@.claude/project-notes.md" in (repo / "CLAUDE.md").read_text()
    assert out["lost"] == [] or all(e["file"] != ".claude/project-notes.md" for e in out["lost"])
