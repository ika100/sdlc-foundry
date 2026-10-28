"""Spec-driven bootstrap (ADR-024, ADR-026): every template seeds the spec index and the rule; bootstrap output leads with the spec."""
import re

import pytest
import yaml

import core
import newapp
import newsvc

ROOT = core.PLATFORM_ROOT
# a cluster repo holds no feature specs (scripts/shapes.py NO_FEATURE_SPECS, spec 125): every other shape seeds them
SHAPES = [s for s in core.registry.load() if s["status"] != "planned" and s["id"] != "cluster-gitops"]
IDS = [s["id"] for s in SHAPES]


def template(shape_id):
    return ROOT / "templates" / next(s["template"] for s in SHAPES if s["id"] == shape_id)


def claude_md(shape_id):
    t = template(shape_id)
    return next(p for p in (t / "CLAUDE.md", t / "CLAUDE.md.jinja") if p.is_file()).read_text()


@pytest.mark.parametrize("shape", IDS)
def test_template_seeds_plan_dir_and_the_spec_first_rule(shape):
    t = template(shape)
    assert (t / "docs" / "plan").is_dir()
    text = claude_md(shape)
    assert "### Spec first" in text
    assert ("/system:spec <description>" if shape == "gitops-app" else "/component:spec <description>") in text
    assert "plan-feature" not in text and "build-feature --" not in text


@pytest.mark.parametrize("shape", [i for i in IDS if i != "gitops-app"])
def test_service_like_templates_seed_the_generated_spec_index(shape, tmp_path):
    import spec
    backlog = (template(shape) / "docs" / "backlog.md").read_text()
    assert "STORY-" not in backlog and "{{" not in backlog
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "backlog.md").write_text(backlog)
    assert spec.write_index(tmp_path).read_text() == backlog  # the seed is exactly what `cplat spec index` writes


@pytest.mark.parametrize("shape", [i for i in IDS if i != "gitops-app"])
def test_templates_never_overwrite_the_project_spec(shape):
    cfg = yaml.safe_load((template(shape) / "copier.yml").read_text())
    assert "docs/backlog.md" in cfg["_skip_if_exists"] and "docs/plan/**" in cfg["_skip_if_exists"]


def test_gitops_app_keeps_plans_project_owned():
    assert "docs/plan/**" in yaml.safe_load((template("gitops-app") / "copier.yml").read_text())["_skip_if_exists"]


@pytest.mark.parametrize("shape", [i for i in IDS if i != "gitops-app"])
def test_bootstrap_leads_with_the_plan_not_a_bare_build(shape):
    steps = newsvc._next_steps({"name": "x-svc", "shape": shape, "description": "Task API"})
    order = [next(i for i, s in enumerate(steps) if s.startswith(p)) for p in ('/component:spec "Task API"', "/component:plan <NNN>", "/component:build <NNN>")]
    assert order == sorted(order)
    assert not any(re.search(r"build-feature|plan-feature", s) for s in steps)


def test_gitops_bootstrap_points_to_the_product_plan():
    steps = newsvc._next_steps({"name": "shop", "shape": "gitops-app", "description": "Shop"})
    assert any(s.startswith('/system:spec "') for s in steps)


def test_new_app_ends_with_the_product_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(newapp.newsvc, "execute", lambda req: (req["target"].mkdir(parents=True), core.Report(title="x"))[1])
    manifest = tmp_path / "app.yml"
    manifest.write_text(yaml.safe_dump({"system": "shop", "owner": "acme", "components": [{"name": "shop-api", "description": "API", "type": "service", "lang": "python"}]}))
    assert newapp.main([str(manifest), "--no-github", "--org", "acme", "--dir", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert 'and run /system:spec "<first feature of the system>"' in out and "/system:ship <NNN>" in out


PLUGIN = ROOT / "plugins" / "svc"


def test_the_old_commands_are_gone_and_nothing_points_to_them():
    """svc 3.0 (ADR-026) replaced plan-feature and build-feature; no command, agent, template or script may still name them."""
    assert not (PLUGIN / "commands" / "build-feature.md").exists() and not (PLUGIN / "commands" / "plan-feature.md").exists()
    assert sorted(p.stem for p in (ROOT / "plugins" / "app" / "commands").glob("*.md")) == ["build", "plan", "ship", "spec", "specs"]  # tombstones (5.0)
    stale = [str(p.relative_to(ROOT)) for d in ("plugins", "templates", "scripts") for p in (ROOT / d).rglob("*")
             if p.is_file() and p.suffix in {".md", ".jinja", ".py", ".json"} and "__pycache__" not in p.parts
             and re.search(r"/svc:(plan-feature|build-feature)|/app:(build-feature|run-plan|plans)\b", p.read_text(errors="ignore"))]
    assert stale == []


def test_plans_cover_the_criteria_of_their_spec():
    """ADR-026 replaced ADR-024's `stories:` link: plans cite criteria (`covers`) and record the spec they came from."""
    plan = (PLUGIN / "skills" / "spec-format" / "references" / "plan.md").read_text()
    assert "covers:" in plan and "spec_hash:" in plan
    assert "AC-<NNN>.<n>" in (PLUGIN / "agents" / "product-manager.md").read_text()


# ---------------- spec contract in every template (STORY-041) ----------------

SPEC_FILES = ["docs/specs/README.md", "scripts/spec-check.sh", ".github/workflows/specs.yml"]


def _as_rendered(shape_id, rel):
    """The file as the template writes it: templates without a suffix render every file, so GitHub expressions are escaped there."""
    text = (template(shape_id) / rel).read_text()
    if yaml.safe_load((template(shape_id) / "copier.yml").read_text()).get("_templates_suffix", ".jinja") == "":
        text = text.replace("${{ '{{' }}", "${{").replace("{{ '}}' }}", "}}")
        assert "{{" not in text.replace("${{", "").replace("}}", "") and "{%" not in text and "{#" not in text, f"{shape_id} renders {rel}"
    return text


@pytest.mark.parametrize("rel", SPEC_FILES)
def test_every_template_ships_the_same_spec_files(rel):
    # the gitops-app's README names the system commands (/system:spec), the others the component commands
    copies = {_as_rendered(s, rel) for s in IDS if not (rel == "docs/specs/README.md" and s == "gitops-app")}
    assert len(copies) == 1, f"{rel} differs between templates"
    text = copies.pop()
    assert "{%" not in text and "{#" not in text


def test_the_spec_workflow_warns_and_uses_pinned_actions():
    wf = yaml.safe_load((template("service-python") / ".github" / "workflows" / "specs.yml").read_text())
    steps = wf["jobs"]["spec-check"]["steps"]
    assert all(re.search(r"@[0-9a-f]{40}$", s["uses"]) for s in steps if "uses" in s)
    assert steps[-1]["run"] == "bash scripts/spec-check.sh" and wf["permissions"] == {"contents": "read"}


def test_spec_check_script_uses_the_repos_platform_version_and_warns_by_default():
    sh = (template("service-go") / "scripts" / "spec-check.sh").read_text()
    assert "sed -n 's/^ref: *//p' .platform-version" in sh and "spec ci" in sh and "SPEC_CHECK_STRICT" in sh
    assert "|| true; } | head -1" in sh  # a repo without .platform-version must not end the script under pipefail


@pytest.mark.parametrize("shape", IDS)
def test_specs_are_project_owned_and_checkable_locally(shape):
    t = template(shape)
    assert "docs/specs/**" in yaml.safe_load((t / "copier.yml").read_text())["_skip_if_exists"]
    devbox = next(p for p in (t / "devbox.json", t / "devbox.json.jinja") if p.is_file()).read_text()
    assert '"spec-check":' in devbox and "bash scripts/spec-check.sh" in devbox


SPEC_MD = """---
spec_id: 001-ping
title: Ping
status: building
priority: P1
---

## Acceptance criteria

- **AC-001.1** Given the service, when GET /ping, then 200.
- **AC-001.2** Given the service, when POST /ping, then 405.
"""


@pytest.mark.skipif(not __import__("shutil").which("uv"), reason="needs uv")
def test_spec_check_script_warns_then_fails_strict_then_passes(tmp_path):
    import subprocess
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "spec-check.sh").write_text((template("service-python") / "scripts" / "spec-check.sh").read_text())
    (tmp_path / "docs" / "specs" / "001-ping").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "001-ping" / "spec.md").write_text(SPEC_MD)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ping.py").write_text("def test_get():  # AC-001.1\n    pass\n")

    def check(strict=False):
        env = {**__import__("os").environ, "SPEC_CHECK_PLATFORM": str(ROOT), "SPEC_CHECK_STRICT": "1" if strict else ""}
        return subprocess.run(["bash", "scripts/spec-check.sh"], cwd=tmp_path, env=env, capture_output=True, text=True)

    warn = check()  # no .platform-version: the script must still run (pipefail regression)
    assert warn.returncode == 0 and "::warning" in warn.stdout and "AC-001.2 is not named by any test" in warn.stdout
    assert check(strict=True).returncode == 1
    (tmp_path / "tests" / "test_ping.py").write_text("def test_get():  # AC-001.1\n    pass\ndef test_post():  # AC-001.2\n    pass\n")
    ok = check(strict=True)
    assert ok.returncode == 0 and "0 problem(s)" in ok.stdout


# ---------------- spec 044: parallel coders build on the feature branch ----------------

import json as _json


def _settings(shape):
    t = template(shape) / ".claude"
    raw = next(p for p in (t / "settings.json", t / "settings.json.jinja") if p.is_file()).read_text()
    return _json.loads(re.sub(r"\{%.*?%\}|\{\{.*?\}\}", "x", raw))


@pytest.mark.parametrize("shape", IDS)
def test_subagent_worktrees_branch_from_head(shape):
    """AC-044.1 AC-044.2: the orchestrator's HEAD (the feature branch) is the base of every coder worktree."""
    assert _settings(shape).get("worktree", {}).get("baseRef") == "head"


def test_the_shape_contract_requires_the_worktree_base():
    """AC-044.2: a template without the setting fails `shapes.py check`."""
    import shapes
    assert 'worktree.baseRef' in (ROOT / "scripts" / "shapes.py").read_text()
    assert not [e for e in shapes.check_contract(shapes.load()) if "baseRef" in e]


# ---------------- spec 049: spec documents do not break the Python lint ----------------

@pytest.mark.parametrize("shape", ["service-python", "library-python"])
def test_python_templates_exclude_docs_from_ruff(shape):
    """AC-049.2"""
    text = (template(shape) / "pyproject.toml").read_text()
    ruff = text.split("[tool.ruff]", 1)[1].split("\n[", 1)[0]
    assert re.search(r'extend-exclude\s*=\s*\[[^\]]*"docs"', ruff)


@pytest.mark.slow
@pytest.mark.skipif(not __import__("shutil").which("uv"), reason="needs uv")
def test_unformatted_python_in_a_design_doc_passes_ruff(tmp_path):
    """AC-049.1"""
    import subprocess
    dest = tmp_path / "svc"
    subprocess.run(["uv", "tool", "run", "--from", "copier", "copier", "copy", str(template("service-python")), str(dest), "--defaults",
                    "--trust", "--skip-tasks", "--data", "project_name=svc", "--data", "module_name=svc", "--data", "description=x"],
                   check=True, capture_output=True)
    (dest / "docs" / "specs" / "001-x").mkdir(parents=True)
    (dest / "docs" / "specs" / "001-x" / "design.md").write_text("# D\n\n```python\ndef f( a ):\n  return {'a':a}\n```\n")
    for cmd in (["uvx", "ruff", "check", "."], ["uvx", "ruff", "format", "--check", "."]):
        out = subprocess.run(cmd, cwd=dest, capture_output=True, text=True)
        assert out.returncode == 0, out.stdout + out.stderr


# ---------------- spec 057: spec-check says what happened ----------------

def _spec_check_offline(tmp_path, ref):
    """Run spec-check.sh with a fake git that 'fetches' a platform without spec checks."""
    import os
    import subprocess
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "docs" / "specs").mkdir(parents=True)
    (repo / "scripts" / "spec-check.sh").write_text((template("service-go") / "scripts" / "spec-check.sh").read_text())
    if ref:
        (repo / ".platform-version").write_text(f"platform: 1.0.0\nshape: service-go\nref: {ref}\n")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "git").write_text('#!/bin/sh\n# fake: init/remote/fetch/checkout succeed and leave an empty platform checkout\n'
                              'if [ "$1" = -C ]; then mkdir -p "$2/scripts/cplat"; touch "$2/scripts/cplat/cplat.py"; mkdir -p "$2/.git"; fi\nexit 0\n')
    (fake / "git").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SPEC_CHECK")}
    env |= {"PATH": f"{fake}:{os.environ['PATH']}", "XDG_CACHE_HOME": str(tmp_path / "cache")}
    return subprocess.run(["bash", "scripts/spec-check.sh"], cwd=repo, env=env, capture_output=True, text=True)


def test_spec_check_on_main_without_checks_says_skipped(tmp_path):
    """AC-057.1"""
    out = _spec_check_offline(tmp_path, "main")
    assert out.returncode == 0
    assert out.stdout.strip().splitlines() == ["spec-check: the platform has no spec checks yet; skipped"]


def test_spec_check_on_an_old_tag_says_it_predates_and_uses_main(tmp_path):
    """AC-057.2"""
    out = _spec_check_offline(tmp_path, "v1.0.0")
    lines = out.stdout.strip().splitlines()
    assert out.returncode == 0
    assert lines[0] == "spec-check: platform v1.0.0 predates spec checks (ADR-026); using main"
    assert lines[1] == "spec-check: the platform has no spec checks yet; skipped"


# ---------------- spec 060: skeleton updates keep the project README ----------------

@pytest.mark.parametrize("shape", IDS)
def test_readme_is_seeded_but_project_owned(shape):
    """AC-060.2: a new repo still gets the template's README; AC-060.1: an update skips it."""
    t = template(shape)
    assert (t / "README.md.jinja").is_file() or (t / "README.md").is_file()
    assert "README.md" in yaml.safe_load((t / "copier.yml").read_text())["_skip_if_exists"]


def test_the_shape_contract_requires_a_project_owned_readme(tmp_path, monkeypatch):
    """AC-060.3: a template that lets updates overwrite README.md fails `shapes.py check`."""
    import shutil

    import shapes
    entry = next(s for s in shapes.load() if s["id"] == "service-go")
    shutil.copytree(ROOT / "templates" / entry["template"], tmp_path / "templates" / entry["template"])
    for extra in ("scripts", "plugins"):   # the contract also reads detection and plugin files
        shutil.copytree(ROOT / extra, tmp_path / extra, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "shapes.yml", tmp_path / "shapes.yml")
    monkeypatch.setattr(shapes, "ROOT", tmp_path)
    before = set(shapes.check_contract([entry]))
    cfg = tmp_path / "templates" / entry["template"] / "copier.yml"
    cfg.write_text(re.sub(r"^  - README\.md\b.*\n", "", cfg.read_text(), flags=re.M))
    new = set(shapes.check_contract([entry])) - before
    assert any("README.md" in e for e in new), new


# ---------------- spec 062: dev runs every merged build ----------------

DEPLOYABLE = [s["id"] for s in SHAPES if s.get("deployable") and s["id"] != "gitops-app"]


@pytest.mark.parametrize("shape", DEPLOYABLE)
def test_every_merge_to_main_asks_the_gitops_app_to_pin_dev(shape, tmp_path):
    """AC-062.1 AC-062.4: the rendered CI has a pin-dev job after the image is published, on main only, never red without a token."""
    newsvc.main([f"pin-{shape}", "d", "--shape", shape, "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme",
                 "--system", "acme/shop"])
    wf = yaml.safe_load((tmp_path / f"pin-{shape}" / ".github" / "workflows" / "ci.yml").read_text())
    job = wf["jobs"]["pin-dev"]
    assert job["needs"] == "docker-publish" and "refs/heads/main" in job["if"] and "tags" not in job["if"]
    run = "\n".join(s.get("run", "") for s in job["steps"])
    assert "repos/$app/dispatches" in run and "event_type=pin-dev" in run and "sha-${GITHUB_SHA}\"" in run   # spec 078
    assert ".platform-app.yml" in run and "::notice::" in run and "gh secret set GITOPS_TOKEN" in run
    assert "secrets.GITOPS_TOKEN" in str(job["steps"])
    assert job["name"] not in (next(s for s in SHAPES if s["id"] == shape).get("ci_checks") or [])   # never a required check


def test_the_shape_contract_requires_the_pin_dev_job(tmp_path, monkeypatch):
    """AC-062.4: a deployable template without the job fails `shapes.py check`."""
    import shutil

    import shapes
    entry = next(s for s in shapes.load() if s["id"] == "service-go")
    shutil.copytree(ROOT / "templates" / entry["template"], tmp_path / "templates" / entry["template"])
    for extra in ("scripts", "plugins"):
        shutil.copytree(ROOT / extra, tmp_path / extra, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "shapes.yml", tmp_path / "shapes.yml")
    monkeypatch.setattr(shapes, "ROOT", tmp_path)
    before = set(shapes.check_contract([entry]))
    ci = tmp_path / "templates" / entry["template"] / ".github" / "workflows" / "ci.yml"
    ci.write_text(ci.read_text().split("\n  pin-dev:\n", 1)[0] + "\n")
    new = set(shapes.check_contract([entry])) - before
    assert any("pin-dev" in e for e in new), new
