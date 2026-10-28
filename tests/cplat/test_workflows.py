"""Every CI workflow re-checks a pull request when its title is edited (otherwise a fixed title can never turn green)."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = [ROOT / ".github/workflows/ci.yml", *sorted(ROOT.glob("templates/*/.github/workflows/ci.yml"))]


def render(path: Path) -> dict:
    """Template workflows are Jinja files: undo the escapes for the GitHub expressions, drop other Jinja statements."""
    text = path.read_text()
    text = text.replace("{{ '{{' }}", "${{").replace("{{ '}}' }}", "}}")
    text = re.sub(r"\{%-?.*?-?%\}", "", text)
    text = re.sub(r"(?<!\$)\{\{.*?\}\}", "x", text)   # {{ var }} but not ${{ github expression }}
    return yaml.safe_load(text)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: str(p.relative_to(ROOT)))
def test_title_edits_trigger_the_title_check_without_cancelling_the_build(path):
    wf = render(path)
    on = wf.get("on", wf.get(True))
    assert "edited" in on["pull_request"]["types"], "pr-title would never re-run after a title fix"
    group = wf["concurrency"]["group"]
    assert "github.event.action == 'edited'" in group, "an edit would cancel the running build"
    assert "pr-title" in wf["jobs"]


# ---------------- spec 055: one pin per action across the platform and the templates ----------------

import subprocess as _sp
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[2]


def _check(*paths):
    return _sp.run([_sys.executable, str(_ROOT / "scripts" / "pin-actions.py"), "--check", *map(str, paths)], capture_output=True, text=True, cwd=_ROOT)


def test_platform_and_templates_pin_each_action_to_one_commit():
    """AC-055.1"""
    out = _check()
    assert out.returncode == 0, out.stderr


def test_two_commits_for_one_action_fail_the_check(tmp_path):
    """AC-055.1"""
    for i, sha in enumerate(("a" * 40, "b" * 40)):
        wf = tmp_path / f"r{i}" / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(f"permissions: {{}}\njobs:\n  x:\n    steps:\n      - uses: actions/checkout@{sha} # v{i}\n")
    out = _check(tmp_path)
    assert out.returncode == 1 and "actions/checkout is pinned to 2 different commits" in out.stderr


def test_dependabot_updates_the_template_actions_with_the_platform():
    """AC-055.2: one grouped github-actions update covers / and every template, so pins move together."""
    import yaml as _yaml
    cfg = _yaml.safe_load((_ROOT / ".github" / "dependabot.yml").read_text())
    gha = [u for u in cfg["updates"] if u["package-ecosystem"] == "github-actions"]
    assert len(gha) == 1
    dirs = set(gha[0].get("directories") or [gha[0].get("directory")])
    assert "/" in dirs and {f"/templates/{t.name}" for t in (_ROOT / "templates").iterdir() if (t / ".github" / "workflows").is_dir()} <= dirs


def test_the_fix_moves_template_pins_to_the_platform_pins(tmp_path):
    """Dependabot bumps only /.github/workflows; `pin-actions.py` (the fix the check names) aligns the templates."""
    new, old = "a" * 40, "b" * 40
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(f"permissions: {{}}\njobs:\n  x:\n    steps:\n      - uses: actions/checkout@{new} # v7.0.1\n")
    tpl = tmp_path / "templates" / "t" / ".github" / "workflows" / "ci.yml"
    tpl.parent.mkdir(parents=True)
    tpl.write_text(f"permissions: {{}}\njobs:\n  x:\n    steps:\n      - uses: actions/checkout@{old} # v4\n        with: {{fetch-depth: 0}}\n")
    script = str(_ROOT / "scripts" / "pin-actions.py")
    out = _sp.run([_sys.executable, script], capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert "aligned 1 reference(s)" in out.stdout
    assert f"      - uses: actions/checkout@{new} # v7.0.1\n        with: {{fetch-depth: 0}}\n" in tpl.read_text()
    check = _sp.run([_sys.executable, script, "--check"], capture_output=True, text=True, cwd=tmp_path)
    assert check.returncode == 0, check.stderr
