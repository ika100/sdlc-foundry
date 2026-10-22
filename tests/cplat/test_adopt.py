"""Spec 071: adopting a repo that was not created from a template."""
import json
import subprocess

import pytest

import adopt
import core
import shapecmd


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def legacy(tmp_path):
    """A Python repo with its own README, CI, devbox recipe, .gitignore and app code, but no platform files."""
    r = tmp_path / "stock-manager"
    (r / "app" / "src").mkdir(parents=True)
    (r / ".github" / "workflows").mkdir(parents=True)
    git(tmp_path, "init", "-q", "-b", "main", str(r))
    (r / "README.md").write_text("# Stock Manager\n\nA personal stock-picking satellite next to an ETF.\n")
    (r / ".github" / "workflows" / "ci.yml").write_text("name: ci  # mine\n")
    (r / ".gitignore").write_text(".venv/\n")
    (r / "devbox.json").write_text(json.dumps({"packages": ["python@3.13"], "shell": {"scripts": {"test": "uv run pytest app/tests"}}}))
    (r / "app" / "src" / "main.py").write_text("print('hi')\n")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    git(r, "remote", "add", "origin", "git@github.com:acme/stock-manager.git")
    return r


@pytest.mark.slow
def test_adopt_adds_what_is_missing_and_never_overwrites(legacy, capsys):
    """AC-071.1 AC-071.2: platform files are added; existing files are kept; devbox.json keeps the repo's recipes."""
    assert adopt.main(["--type", "service-python", "--repo", str(legacy)]) == 0
    out = capsys.readouterr().out
    assert git(legacy, "rev-parse", "--abbrev-ref", "HEAD") == "chore/adopt-platform"
    assert (legacy / "CLAUDE.md").is_file() and (legacy / ".claude" / "settings.json").is_file()
    assert (legacy / "README.md").read_text().startswith("# Stock Manager")            # kept
    assert (legacy / ".github" / "workflows" / "ci.yml").read_text() == "name: ci  # mine\n"
    assert "ci.yml" in out and "differ from the template" in out
    box = json.loads((legacy / "devbox.json").read_text())
    assert box["shell"]["scripts"]["test"] == "uv run pytest app/tests"                 # yours win
    assert "quality" in box["shell"]["scripts"]                                         # missing recipes added
    assert ".venv/" in (legacy / ".gitignore").read_text() and "added by cplat adopt" in (legacy / ".gitignore").read_text()
    assert not (legacy / "src").exists() and not (legacy / "tests").exists()             # no starter code
    assert git(legacy, "status", "--porcelain") == ""


@pytest.mark.slow
def test_an_adopted_repo_is_a_platform_repo(legacy):
    """AC-071.3: answers come from the repo; shape detection, the version stamp and update-service work afterwards."""
    adopt.main(["--type", "service-python", "--repo", str(legacy), "--data", "module_name=stockmanager"])
    answers = (legacy / ".copier-answers.yml").read_text()
    assert "_src_path: gh:ika100/sdlc-foundry/templates/service-python" in answers
    assert "project_name: stock-manager" in answers and "github_org: acme" in answers and "module_name: stockmanager" in answers
    assert "A personal stock-picking satellite next to an ETF" in answers
    assert shapecmd.route(legacy)["shape"] == "service-python"
    assert core.read_stamp(legacy)["shape"] == "service-python"
    import update
    req = update.resolve(["--repo", str(legacy), "--dry-run"])
    assert req["shape"] == "service-python"


def test_adopt_refuses_repos_that_already_have_answers(legacy):
    (legacy / ".copier-answers.yml").write_text("_src_path: x\n")
    with pytest.raises(core.PlatformError, match="already has a .copier-answers.yml"):
        adopt.main(["--type", "service-python", "--repo", str(legacy), "--dry-run"])


def test_adopt_refuses_an_unknown_shape(legacy):
    with pytest.raises(core.PlatformError, match="unknown shape"):
        adopt.main(["--type", "cobol", "--repo", str(legacy), "--dry-run"])


def test_dry_run_changes_nothing(legacy, capsys):
    """AC-071.4: --dry-run lists the plan and touches nothing."""
    assert adopt.main(["--type", "service-python", "--repo", str(legacy), "--dry-run"]) == 0
    assert "dry run" in capsys.readouterr().out
    assert git(legacy, "status", "--porcelain") == "" and git(legacy, "rev-parse", "--abbrev-ref", "HEAD") == "main"
