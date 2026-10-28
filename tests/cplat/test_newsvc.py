"""new-service: parsing, shape routing, and a real local render (no GitHub)."""
import subprocess
from pathlib import Path

import pytest

import core
import newsvc


def resolve(*argv, **kw):
    return newsvc.resolve([*argv, "--no-github", "--org", "acme", *kw.get("extra", [])])


def test_defaults_to_service_python_with_python_answers():
    r = resolve("my-api", "A", "thing")
    assert r["shape"] == "service-python"
    assert r["description"] == "A thing"
    assert r["data"]["module_name"] == "my_api" and r["data"]["python_version"] == "3.12"


@pytest.mark.parametrize("flags,shape", [(["--type", "website"], "web-nextjs"), (["--shape", "gitops-app"], "gitops-app"), (["--type", "library"], "library-python")])
def test_aliases(flags, shape):
    assert resolve("x1", "desc", *flags)["shape"] == shape


def test_flags_may_appear_anywhere():
    r = resolve("--type", "website", "my-web", "Frontend", "app")
    assert (r["name"], r["description"], r["shape"]) == ("my-web", "Frontend app", "web-nextjs")


def test_non_python_shapes_do_not_get_module_name_or_python_version():
    """Regression: module_name=my_saas turned the Go module path into `my_saas`."""
    for shape in ("service-go", "service-java", "web-nextjs", "gitops-app"):
        data = resolve("my-saas", "d", "--shape", shape)["data"]
        assert "module_name" not in data and "python_version" not in data, shape


@pytest.mark.parametrize("argv,msg", [
    (["Bad_Name", "d"], "invalid project name"),
    (["ok"], "description is required"),
    ([], "name is required"),
    (["ok", "d", "--web", "--shape", "gitops-app"], "`--web` is `--type website --lang typescript` in 5.0"),
    (["ok", "d", "--type", "nope"], "not a valid component type"),
])
def test_bad_input_has_a_clear_error(argv, msg):
    with pytest.raises(core.PlatformError, match=msg):
        resolve(*argv)


def test_errors_carry_a_hint():
    with pytest.raises(core.PlatformError) as e:
        resolve("Bad_Name", "d")
    assert e.value.hint


def test_app_is_ignored_for_non_deployable_shapes():
    r = resolve("g1", "d", "--shape", "gitops-app", "--system", "acme/g1")
    assert r["app"] is None and r["ignored_app"]
    assert resolve("s1", "d", "--system", "acme/g1")["app"] == "acme/g1"


def test_existing_nonempty_target_is_refused(tmp_path):
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "file").write_text("x")
    with pytest.raises(core.PlatformError, match="not empty"):
        resolve("taken", "d", extra=["--dir", str(tmp_path)])


def test_dry_run_makes_no_changes(tmp_path, capsys):
    assert newsvc.main(["dry-1", "d", "--type", "website", "--no-github", "--dry-run", "--dir", str(tmp_path)]) == 0
    assert not (tmp_path / "dry-1").exists()
    assert "dry run" in capsys.readouterr().out


@pytest.mark.slow
def test_real_local_render_of_each_shape(tmp_path):
    for shape in ("gitops-app", "service-go"):
        name = f"t-{shape}"
        newsvc.main([name, "desc", "--shape", shape, "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme", "--system", "acme/app-gitops"])
        repo = tmp_path / name
        answers = (repo / ".copier-answers.yml").read_text()
        assert f"_src_path: gh:ika100/sdlc-foundry/templates/{shape}" in answers  # stable, not a temp path
        assert core.read_stamp(repo)["shape"] == shape
        log = subprocess.run(["git", "log", "--format=%s"], cwd=repo, text=True, capture_output=True).stdout.splitlines()
        assert log == [f"chore: bootstrap from {shape} template"]
        assert subprocess.run(["bash", str(core.PLATFORM_ROOT / "scripts/detect-shape.sh"), str(repo)], text=True, capture_output=True).stdout.strip() == shape
    assert "module github.com/acme/t-service-go" in (tmp_path / "t-service-go" / "go.mod").read_text()
    assert not (tmp_path / "t-service-go" / ".platform-app.yml").exists() or "acme/app-gitops" in (tmp_path / "t-service-go" / ".platform-app.yml").read_text()


# ---------------- visibility and template options ----------------

def test_public_flag_is_shown_in_the_preview_and_used_for_the_github_repo(tmp_path, monkeypatch, capsys):
    import subprocess

    calls = []
    real_run = newsvc.run

    def fake_run(cmd, **kw):
        if cmd[0] == "gh":
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kw)

    monkeypatch.setattr(newsvc, "run", fake_run)
    monkeypatch.setattr(newsvc.core, "has_gh", lambda: True)
    assert newsvc.main(["pubsvc", "d", "--public", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme", "--dry-run"]) == 0
    assert "create PUBLIC GitHub repo acme/pubsvc" in capsys.readouterr().out
    assert newsvc.main(["pubsvc", "d", "--public", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"]) == 0
    create = next(c for c in calls if c[:3] == ["gh", "repo", "create"])
    assert "--public" in create and "--private" not in create


def test_private_stays_the_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(newsvc.core, "has_gh", lambda: True)
    assert newsvc.main(["privsvc", "d", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme", "--dry-run"]) == 0
    assert "create PRIVATE GitHub repo" in capsys.readouterr().out


def test_public_conflicts_are_rejected():
    with pytest.raises(core.PlatformError, match="conflicts"):
        newsvc.resolve(["x-svc", "d", "--public", "--visibility", "private"])
    with pytest.raises(core.PlatformError, match="needs a GitHub repository"):
        newsvc.resolve(["x-svc", "d", "--public", "--no-github"])


def test_data_sets_template_options_and_rejects_unknown_ones(tmp_path):
    req = newsvc.resolve(["opt-svc", "d", "--type", "service", "--lang", "java", "--data", "needs_observability=false", "--dir", str(tmp_path)])
    assert req["data"]["needs_observability"] == "false" and "needs_observability" in req["set_keys"]
    with pytest.raises(core.PlatformError) as e:
        newsvc.resolve(["opt-svc", "d", "--type", "service", "--lang", "java", "--data", "needs_everything=true"])
    assert "no option 'needs_everything'" in str(e.value) and "needs_observability" in (e.value.hint or "")
    with pytest.raises(core.PlatformError, match="KEY=VALUE"):
        newsvc.resolve(["opt-svc", "d", "--data", "oops"])


def test_next_steps_tell_the_agent_to_start_a_feature_without_waiting_for_ci():
    steps = newsvc._next_steps({"name": "svc-a", "shape": "service-python", "description": "Task API"})
    joined = "\n".join(steps)
    assert "/component:build <NNN>" in joined and "do not wait" in joined


# ---------------- spec 054: new repos protect main with their CI checks ----------------

def _gh_recorder(monkeypatch, fail_protection=False):
    import subprocess
    calls, real_run = [], newsvc.run

    def fake_run(cmd, **kw):
        if cmd[0] == "gh":
            calls.append(cmd)
            rc = 1 if fail_protection and "protection" in " ".join(cmd) else 0
            if rc and kw.get("check", True):
                raise core.PlatformError("HTTP 403")
            return subprocess.CompletedProcess(cmd, rc, "", "HTTP 403: Upgrade to GitHub Pro" if rc else "")
        return real_run(cmd, **kw)

    monkeypatch.setattr(newsvc, "run", fake_run)
    monkeypatch.setattr(newsvc.core, "has_gh", lambda: True)
    return calls


def test_new_repo_requires_its_ci_checks_on_main(tmp_path, monkeypatch, capsys):
    """AC-054.1: status checks only, listed as an outward step."""
    calls = _gh_recorder(monkeypatch)
    assert newsvc.main(["prot-svc", "d", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme", "--dry-run"]) == 0
    assert "[outward] protect main: require the CI checks" in capsys.readouterr().out
    assert newsvc.main(["prot-svc", "d", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"]) == 0
    prot = next(c for c in calls if "repos/acme/prot-svc/branches/main/protection" in c)
    checks = {c.split("=", 1)[1] for c in prot if c.startswith("required_status_checks[contexts][]=")}
    entry = next(s for s in core.registry.load() if s["id"] == "service-python")
    assert checks == set(entry["ci_checks"]) and "required_pull_request_reviews=null" in prot


def test_protection_failure_warns_and_still_succeeds(tmp_path, monkeypatch, capsys):
    """AC-054.2"""
    _gh_recorder(monkeypatch, fail_protection=True)
    assert newsvc.main(["prot-svc2", "d", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"]) == 0
    out = capsys.readouterr().out
    assert "could not protect main" in out and "gh api -X PUT repos/acme/prot-svc2/branches/main/protection" in out


def test_every_shape_lists_ci_checks_that_exist_in_its_workflow():
    """AC-054.1: required checks must match real job names, or PRs could never merge."""
    for s in core.registry.load():
        if s["status"] == "planned":
            continue
        ci = (core.PLATFORM_ROOT / "templates" / s["template"] / ".github" / "workflows" / "ci.yml").read_text()
        assert s.get("ci_checks"), s["id"]
        for name in s["ci_checks"]:
            assert f"name: {name}\n" in ci, f"{s['id']}: no job named '{name}'"


# ---------------- spec 062: dev runs every merged build ----------------

def test_a_new_gitops_app_allows_pin_prs_to_merge_themselves(tmp_path, monkeypatch, capsys):
    """AC-062.4: auto-merge on, and Actions may open pull requests."""
    calls = _gh_recorder(monkeypatch)
    assert newsvc.main(["pin-app", "d", "--shape", "gitops-app", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"]) == 0
    flat = [" ".join(c) for c in calls]
    assert any("-X PATCH repos/acme/pin-app" in c and "allow_auto_merge=true" in c for c in flat)
    assert any("repos/acme/pin-app/actions/permissions/workflow" in c and "can_approve_pull_request_reviews=true" in c for c in flat)
    assert "allows pin PRs" in capsys.readouterr().out


def test_settings_failure_warns_with_the_commands(tmp_path, monkeypatch, capsys):
    """AC-062.4"""
    import subprocess
    real = newsvc.run

    def fake(cmd, **kw):
        if cmd[0] == "gh":
            rc = 1 if "allow_auto_merge=true" in cmd else 0
            return subprocess.CompletedProcess(cmd, rc, "", "HTTP 403" if rc else "")
        return real(cmd, **kw)
    monkeypatch.setattr(newsvc, "run", fake)
    monkeypatch.setattr(newsvc.core, "has_gh", lambda: True)
    assert newsvc.main(["pin-app2", "d", "--shape", "gitops-app", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"]) == 0
    out = capsys.readouterr().out
    assert "auto-merge is not available on this plan, pin-dev merges itself" in out and "could not let Actions" not in out


def test_actions_permission_failure_names_the_command(tmp_path, monkeypatch, capsys):
    """AC-065.4: without permission for Actions to open PRs, pin-dev cannot work: warn with the exact command."""
    import subprocess
    real = newsvc.run

    def fake(cmd, **kw):
        if cmd[0] == "gh":
            rc = 1 if any("actions/permissions/workflow" in c for c in cmd) else 0
            return subprocess.CompletedProcess(cmd, rc, "", "HTTP 403" if rc else "")
        return real(cmd, **kw)
    monkeypatch.setattr(newsvc, "run", fake)
    monkeypatch.setattr(newsvc.core, "has_gh", lambda: True)
    assert newsvc.main(["pin-app3", "d", "--shape", "gitops-app", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"]) == 0
    out = capsys.readouterr().out
    assert "could not let Actions open pull requests" in out and "repos/acme/pin-app3/actions/permissions/workflow" in out


def test_free_plan_warning_says_merges_still_wait_for_ci(tmp_path, monkeypatch, capsys):
    """AC-065.4: an unprotected main is reported together with what still guards merges."""
    import subprocess
    real = newsvc.run

    def fake(cmd, **kw):
        if cmd[0] == "gh":
            rc = 1 if any("branches/main/protection" in c for c in cmd) else 0
            return subprocess.CompletedProcess(cmd, rc, "", "HTTP 403: Upgrade to GitHub Pro" if rc else "")
        return real(cmd, **kw)
    monkeypatch.setattr(newsvc, "run", fake)
    monkeypatch.setattr(newsvc.core, "has_gh", lambda: True)
    assert newsvc.main(["free-svc", "d", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"]) == 0
    out = capsys.readouterr().out
    assert "could not protect main" in out and "merge only after every check passed" in out


def test_a_linked_service_names_the_one_token_step(tmp_path, capsys):
    """AC-062.4: the only manual step, with the exact command."""
    assert newsvc.main(["pin-svc", "d", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme", "--system", "acme/shop"]) == 0
    out = capsys.readouterr().out
    assert "gh secret set GITOPS_TOKEN -R acme/pin-svc" in out and "acme/shop" in out and "Contents" in out
    assert newsvc.main(["nopin-svc", "d", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"]) == 0
    assert "GITOPS_TOKEN" not in capsys.readouterr().out
