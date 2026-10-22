"""update-service on a repo made by new-service, changelog helpers, doctor logic."""
import subprocess
from pathlib import Path

import pytest

import core
import doctor
import newsvc
import update


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    newsvc.main(["upd-go", "desc", "--type", "service-go", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])
    return tmp_path / "upd-go"


def test_update_restores_skeleton_keeps_project_files(repo):
    (repo / ".golangci.yml").write_text("# local tweak\n")            # skeleton file → must be overwritten
    (repo / "internal/server/server.go").write_text("// mine\n")      # project-owned → must survive
    (repo / ".platform-version").write_text("platform: 1.0.0\nshape: service-go\nref: main\n")
    git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "tweak")
    assert update.main(["--repo", str(repo), "--skip-tasks"]) == 0
    assert "tweak" not in (repo / ".golangci.yml").read_text()
    assert (repo / "internal/server/server.go").read_text() == "// mine\n"
    assert git(repo, "branch", "--show-current").startswith("chore/platform-update-")
    assert git(repo, "log", "-1", "--format=%s").startswith("chore: update skeleton from platform")
    assert "_src_path: gh:ika100/sdlc-foundry/templates/service-go" in (repo / ".copier-answers.yml").read_text()
    assert core.read_stamp(repo)["platform"] == core.platform_version()


def test_update_refuses_dirty_tree(repo):
    (repo / "x").write_text("dirty")
    with pytest.raises(core.PlatformError, match="uncommitted"):
        update.resolve(["--repo", str(repo)])


def test_update_requires_answers_file(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    with pytest.raises(core.PlatformError, match="copier-answers"):
        update.resolve(["--repo", str(tmp_path)])


def test_update_data_must_be_key_value(repo):
    with pytest.raises(core.PlatformError, match="KEY=VALUE"):
        update.resolve(["--repo", str(repo), "--data", "oops"])


def test_update_dry_run_changes_nothing(repo, capsys):
    head = git(repo, "rev-parse", "HEAD")
    assert update.main(["--repo", str(repo), "--dry-run"]) == 0
    assert git(repo, "rev-parse", "HEAD") == head and git(repo, "branch", "--show-current") == "main"
    assert "OVERWRITE" in capsys.readouterr().out


def test_changelog_between_selects_the_right_sections():
    text = core.changelog_between("1.0.1", "1.1.1")
    assert "[1.1.1]" in text and "[1.1.0]" in text and "[1.0.1]" not in text
    assert core.changelog_between(None, "1.0.0").count("## [") >= 1


def test_vtuple_orders_numerically():
    assert core.vtuple("1.10.0") > core.vtuple("1.9.9")


def test_doctor_flags_stale_plugins(monkeypatch):
    monkeypatch.setattr(doctor, "legacy_plugins", lambda: {})
    monkeypatch.setattr(doctor, "installed_plugins", lambda: {"shared": "0.3.1"})
    res = doctor.check_plugins()
    assert res[0]["status"] == doctor.WARN and "RESTART" in res[0]["fix"]


def test_doctor_kube_context_warns_when_not_local(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda t: "/usr/bin/kubectl")
    monkeypatch.setattr(doctor, "run", lambda *a, **k: type("P", (), {"stdout": "prod-eu-1\n", "returncode": 0})())
    assert doctor.check_kube()[0]["status"] == doctor.WARN
    monkeypatch.setattr(doctor, "run", lambda *a, **k: type("P", (), {"stdout": "k3d-todo-local\n", "returncode": 0})())
    assert doctor.check_kube()[0]["status"] == doctor.OK


def test_doctor_repo_stamp(repo):
    (repo / ".platform-version").write_text("platform: 0.9.0\nshape: service-go\nref: main\n")
    assert any(c["name"] == "repo platform version" and c["status"] == doctor.WARN for c in doctor.check_repo(repo))


def test_update_on_fresh_repo_is_a_noop_and_leaves_no_branch(repo):
    head = git(repo, "rev-parse", "HEAD")
    update.main(["--repo", str(repo), "--skip-tasks"])
    assert git(repo, "branch", "--show-current") == "main"
    assert git(repo, "branch", "--list", "chore/platform-update-*") == ""
    # the stamp is rewritten identically, so nothing differs and no commit is made
    assert git(repo, "rev-parse", "HEAD") == head


def test_shape_routing(repo, tmp_path):
    import shapecmd
    r = shapecmd.route(repo)
    assert r["shape"] == "service-go" and r["agents"]["coder"] == "svc-go:coder" and r["agents"]["architect"] == "svc:architect"
    assert r["agents"]["reviewer"] == "svc:reviewer"
    newsvc.main(["g-app", "d", "--gitops", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])
    g = shapecmd.route(tmp_path / "g-app")
    assert g["shape"] == "gitops-app" and "deployment" not in g["agents"] and "unsupported" in g


def test_python_service_routes_to_svc_with_migrations(tmp_path):
    import shapecmd
    newsvc.main(["py-svc", "d", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])
    r = shapecmd.route(tmp_path / "py-svc")
    assert r["agents"]["coder"] == "svc:coder" and r["agents"]["migrations"] == "svc:migrations"


def test_migrate_removes_k8s_dir_and_stamp_is_current(repo):
    (repo / "k8s" / "base").mkdir(parents=True)
    (repo / "k8s" / "base" / "deployment.yaml").write_text("kind: Deployment\n")
    git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1 k8s")
    update.main(["--repo", str(repo), "--skip-tasks", "--migrate"])
    assert not (repo / "k8s").exists()
    assert git(repo, "log", "-1", "--format=%s").startswith("chore: update skeleton")


def test_without_migrate_k8s_dir_is_left_alone(repo):
    (repo / "k8s").mkdir()
    (repo / "k8s" / "x.yaml").write_text("a: b\n")
    git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "k8s")
    (repo / ".platform-version").write_text("platform: 1.0.0\nshape: service-go\nref: main\n")
    git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "old stamp")
    update.main(["--repo", str(repo), "--skip-tasks"])
    assert (repo / "k8s" / "x.yaml").exists()


def test_second_update_the_same_day_gets_a_unique_branch(repo):
    base = update.branch_name()
    git(repo, "branch", base)                      # e.g. yesterday's merged update branch with today's name
    assert update.branch_name(repo) == base + "-2"
    git(repo, "branch", base + "-2")
    assert update.branch_name(repo) == base + "-3"


def test_doctor_detects_plugins_from_the_pre_rename_marketplace(monkeypatch):
    monkeypatch.setattr(doctor, "installed_plugins", lambda: {})
    monkeypatch.setattr(doctor, "legacy_plugins", lambda: {"svc": "2.1.0", "shared": "0.6.1"})
    res = doctor.check_plugins()
    assert len(res) == 1 and res[0]["status"] == doctor.WARN
    detail = res[0]["detail"] + " " + (res[0].get("fix") or "")
    assert "ika100-claude" in detail and "renamed" in detail
    assert "/plugin marketplace add ika100/sdlc-foundry" in detail
    assert "/plugin install shared@sdlc-foundry" in detail and "/plugin install svc@sdlc-foundry" in detail


def test_doctor_reports_legacy_and_current_installs_together(monkeypatch):
    monkeypatch.setattr(doctor, "installed_plugins", lambda: {"shared": "0.7.2"})
    monkeypatch.setattr(doctor, "legacy_plugins", lambda: {"svc": "2.1.0"})
    names = [c["name"] for c in doctor.check_plugins()]
    assert names[0] == "plugins (old marketplace)" and "plugins" in names


def test_update_does_not_add_starter_files_to_project_owned_paths(tmp_path):
    """An existing web app has its own UI and tests: an update must not re-create (or newly add) template starter files in app/ or tests/."""
    newsvc.main(["own-ui", "desc", "--web", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])
    repo = tmp_path / "own-ui"
    import shutil
    starter = ["app/globals.css", "app/not-found.tsx", "app/error.tsx", "app/icon.svg", "app/_components/site-header.tsx", "tests/layout.test.tsx"]
    shutil.rmtree(repo / "app/_components")
    for f in ("app/globals.css", "app/not-found.tsx", "app/error.tsx", "app/icon.svg", "tests/layout.test.tsx"):
        (repo / f).unlink()                              # this repo never had the starter UI (it predates it)
    (repo / "CLAUDE.md").write_text("# local edit\n")    # skeleton file: must be restored
    (repo / "app/page.tsx").write_text("export default function Page() { return null }\n")   # project-owned: must survive
    git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "own ui")

    assert update.main(["--repo", str(repo), "--skip-tasks", "--json"]) == 0

    for f in starter:
        assert not (repo / f).exists(), f"{f} was added to a project-owned path"
    assert not (repo / "app/_components").exists()       # empty directory tidied up
    assert (repo / "app/page.tsx").read_text().startswith("export default function Page")
    assert "local edit" not in (repo / "CLAUDE.md").read_text()
    assert core.read_stamp(repo)["platform"] == core.platform_version()


def test_project_owned_patterns_come_from_the_templates_own_list():
    patterns = update.project_owned_patterns("web-nextjs")
    assert "app/**" in patterns and "tests/**" in patterns
    assert update.project_owned_patterns("no-such-template") == []


def test_update_keeps_the_web_apps_own_dependencies(tmp_path):
    """package.json holds the project's dependencies (and Dependabot's bumps): like pom.xml, go.mod and pyproject.toml it is project-owned."""
    import json
    newsvc.main(["own-deps", "desc", "--web", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])
    repo = tmp_path / "own-deps"
    pkg = json.loads((repo / "package.json").read_text())
    pkg["dependencies"]["zod"] = "^3.23.0"                  # a dependency the project added
    pkg["devDependencies"]["typescript"] = "~6.0.3"         # a bump Dependabot merged
    (repo / "package.json").write_text(json.dumps(pkg, indent=2) + "\n")
    git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "own deps")
    update.main(["--repo", str(repo), "--skip-tasks", "--json"])
    after = json.loads((repo / "package.json").read_text())
    assert after["dependencies"]["zod"] == "^3.23.0" and after["devDependencies"]["typescript"] == "~6.0.3"


def test_every_template_protects_its_dependency_manifest():
    expected = {"service-python": "pyproject.toml", "library-python": "pyproject.toml", "service-java": "pom.xml", "service-go": "go.mod", "web-nextjs": "package.json"}
    for template, manifest in expected.items():
        assert manifest in update.project_owned_patterns(template), f"{template}: {manifest} would be overwritten by /shared:update-service"


# ---------------- spec 060: updates keep the project README and devbox recipes ----------------

def _commit(repo, msg):
    git(repo, "add", "-A"); git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


def test_update_keeps_the_readme_and_says_so(repo, capsys):
    """AC-060.1 AC-060.4: the README is untouched, not among the modified files, and the report names the template's version."""
    (repo / "README.md").write_text("# upd-go\n\nOur API docs.\n")
    (repo / ".platform-version").write_text("platform: 0.0.1\nshape: service-go\nref: main\n")   # unknown old ref
    _commit(repo, "own readme")
    assert update.main(["--repo", str(repo), "--skip-tasks"]) == 0
    out = capsys.readouterr().out
    assert (repo / "README.md").read_text() == "# upd-go\n\nOur API docs.\n"
    assert "README.md kept" in out and "templates/service-go/README.md.jinja" in out
    assert "MODIFIED" not in out or "README.md" not in out.split("MODIFIED", 1)[1].split("\n", 1)[0]


def _devbox(repo):
    import json
    return json.loads((repo / "devbox.json").read_text())


def _write_devbox(repo, data):
    import json
    (repo / "devbox.json").write_text(json.dumps(data, indent=2) + "\n")


def test_update_keeps_project_recipes_and_packages(repo, capsys):
    """AC-060.5 AC-060.7: project-only scripts, packages and env survive and are listed."""
    d = _devbox(repo)
    d["shell"]["scripts"]["bundle-check"] = "pnpm build && node scripts/bundle-check.mjs"
    d["packages"] = (d["packages"] + ["k6@latest"]) if isinstance(d["packages"], list) else {**d["packages"], "k6": "latest"}
    d.setdefault("env", {})["MY_FLAG"] = "1"
    _write_devbox(repo, d)
    _commit(repo, "own recipes")
    assert update.main(["--repo", str(repo), "--skip-tasks"]) == 0
    after, out = _devbox(repo), capsys.readouterr().out
    assert after["shell"]["scripts"]["bundle-check"] == "pnpm build && node scripts/bundle-check.mjs"
    assert "k6@latest" in after["packages"] or after["packages"].get("k6") == "latest"
    assert after["env"]["MY_FLAG"] == "1"
    assert "kept in devbox.json" in out and "bundle-check" in out and "k6" in out


def test_update_takes_the_templates_recipe_and_shows_the_old_line(repo, capsys):
    """AC-060.6 AC-060.7: a template recipe the project changed is replaced; the report shows the project's old line."""
    template_test = _devbox(repo)["shell"]["scripts"]["test"]
    d = _devbox(repo)
    d["shell"]["scripts"]["test"] = "go test ./... -count=1 -v"
    _write_devbox(repo, d)
    _commit(repo, "tweak test")
    assert update.main(["--repo", str(repo), "--skip-tasks"]) == 0
    out = capsys.readouterr().out
    assert _devbox(repo)["shell"]["scripts"]["test"] == template_test
    assert "replaced in devbox.json" in out and "go test ./... -count=1 -v" in out


@pytest.mark.parametrize("project, template, merged, kept, replaced", [
    ({"packages": ["go@1.22", "k6@latest"], "shell": {"scripts": {"a": "x", "mine": "y"}}},
     {"packages": ["go@1.23"], "shell": {"scripts": {"a": "x"}, "init_hook": ["t"]}},
     {"packages": ["go@1.23", "k6@latest"], "shell": {"scripts": {"a": "x", "mine": "y"}, "init_hook": ["t"]}},
     ["scripts mine", "packages k6@latest"], [("packages go", "go@1.22")]),
    ({"packages": {"go": "1.22", "k6": "latest"}, "env": {"A": "1", "B": "2"}},
     {"packages": {"go": "1.23"}, "env": {"A": "0"}},
     {"packages": {"go": "1.23", "k6": "latest"}, "env": {"A": "0", "B": "2"}},
     ["packages k6", "env B"], [("packages go", "1.22"), ("env A", "1")]),
])
def test_merge_devbox(project, template, merged, kept, replaced):
    """AC-060.5 AC-060.6: template entries win, project-only entries are kept, replaced entries keep the old value."""
    got, got_kept, got_replaced = update.merge_devbox(project, template)
    assert got == merged and got_kept == kept and got_replaced == replaced


def test_kept_recipes_do_not_reformat_the_templates_devbox_json(repo):
    """AC-060.5: kept entries are inserted; the template's aligned recipes stay byte-for-byte."""
    import json
    rendered = (repo / "devbox.json").read_text()
    d = json.loads(rendered)
    d["shell"]["scripts"]["bundle-check"] = "make bundle"
    _write_devbox(repo, d)
    _commit(repo, "own recipe")
    assert update.main(["--repo", str(repo), "--skip-tasks"]) == 0
    after = (repo / "devbox.json").read_text()
    assert json.loads(after)["shell"]["scripts"]["bundle-check"] == "make bundle"
    first = next(ln for ln in rendered.splitlines() if '"test":' in ln)
    assert first in after.splitlines()          # alignment kept


def test_update_that_brings_pin_dev_names_the_token_step(tmp_path, capsys):
    """AC-062.4: an existing linked service gets the job and the one manual step."""
    newsvc.main(["pin-upd", "d", "--type", "service-go", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme",
                 "--app", "acme/shop"])
    repo = tmp_path / "pin-upd"
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text(ci.read_text().split("\n  pin-dev:\n", 1)[0] + "\n")    # as before spec 062
    _commit(repo, "old ci")
    capsys.readouterr()
    assert update.main(["--repo", str(repo), "--skip-tasks"]) == 0
    out = capsys.readouterr().out
    assert "pin-dev:" in ci.read_text() and "gh secret set GITOPS_TOKEN -R" in out and "acme/shop" in out


def test_update_runs_in_a_git_worktree(tmp_path):
    """A worktree has a .git file, not a directory; update-service must still accept it."""
    import update
    main_repo = tmp_path / "svc"
    main_repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=main_repo, check=True)
    (main_repo / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-go\nproject_name: svc\n")
    subprocess.run(["git", "add", "-A"], cwd=main_repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], cwd=main_repo, check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "chore/x", str(wt)], cwd=main_repo, check=True)
    assert (wt / ".git").is_file()
    assert update.resolve(["--repo", str(wt), "--dry-run"])["shape"] == "service-go"
