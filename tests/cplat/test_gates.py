"""Spec 081: gate tools are pinned and bumped; doctor and adopt report gates that cannot fail."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import bump_template_pins as bump  # noqa: E402
import core  # noqa: E402
import doctor  # noqa: E402
import gates  # noqa: E402

ROOT = core.PLATFORM_ROOT
STANDARD = ["detect_secrets.filters.allowlist.is_line_allowlisted", "detect_secrets.filters.heuristic.is_sequential_string"]


def test_every_gate_tool_in_the_templates_is_pinned():
    """AC-081.1: no gate tool is @latest in any template."""
    for f in (ROOT / "templates").glob("*/devbox.json*"):
        for name, version in re.findall(r'"([a-z0-9-]+)@([^"]+)"', f.read_text()):
            if name in bump.GATE_TOOLS:
                assert version != "latest", f"{f.parent.name}: {name}@latest"


def test_bump_raises_gate_pins_within_their_line(tmp_path, monkeypatch):
    """AC-081.1: minor/patch only; a 0.x tool stays in its 0.minor; an unresolvable one is a note, not a guess."""
    t = tmp_path / "service-x"
    t.mkdir()
    (t / "devbox.json").write_text('{"packages": ["ruff@0.16.1", "maven@3.9.1", "git@latest", "trivy@0.74.0", "mypy@2.0.0"]}')
    asked = []

    def fake(name, line):
        asked.append((name, line))
        return {"ruff": "0.16.10", "maven": "3.9.16", "trivy": "0.74.0"}.get(name)
    monkeypatch.setattr(bump, "resolve", fake)
    changes, notes = bump.bump_devbox(tmp_path)
    text = (t / "devbox.json").read_text()
    assert '"ruff@0.16.10"' in text and '"maven@3.9.16"' in text and '"git@latest"' in text
    assert ("ruff", "0.16") in asked and ("maven", "3") in asked and not any(n == "git" for n, _ in asked)
    assert changes == ["service-x: ruff 0.16.1 -> 0.16.10", "service-x: maven 3.9.1 -> 3.9.16"]
    assert notes == ["service-x: could not resolve mypy@2"]


def make_repo(tmp_path, *, filters, ci_recipe, workflow_runs, packages=("detect-secrets@1.5.0",)):
    r = tmp_path / "svc"
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / "devbox.json").write_text(json.dumps({"packages": list(packages), "shell": {"scripts": {
        "quality": "devbox run lint", "lint": "ruff check", "test": "pytest", "security": "devbox run secrets-scan",
        "secrets-scan": "detect-secrets-hook", "secrets-baseline": "detect-secrets scan", **({"ci": ci_recipe} if ci_recipe else {})}}}))
    (r / ".secrets.baseline.json").write_text(json.dumps({"filters_used": [{"path": p} for p in filters], "results": {}}))
    jobs = {g: {"steps": [{"run": f"devbox run {g}"}]} for g in workflow_runs}
    (r / ".github" / "workflows" / "ci.yml").write_text(json.dumps({"jobs": jobs}))
    return r


def by_name(results):
    return {c["name"]: c for c in results}


def test_doctor_passes_real_gates(tmp_path):
    """AC-081.2: standard baseline, pinned scanner, ci = the workflow's gates → all ok."""
    r = make_repo(tmp_path, filters=STANDARD, ci_recipe="devbox run quality && devbox run test && devbox run security",
                  workflow_runs=["quality", "test", "security"])
    res = by_name(gates.check_gates(r))
    assert all(c["status"] == "ok" for c in res.values()), res


def test_doctor_flags_gates_that_cannot_fail(tmp_path):
    """AC-081.2: no standard filters, @latest scanner, missing recipe, ci that skips a gate → each named with a fix."""
    r = make_repo(tmp_path, filters=["detect_secrets.filters.common.is_baseline_file"], ci_recipe="devbox run quality",
                  workflow_runs=["quality", "test"], packages=("detect-secrets@latest",))
    res = by_name(gates.check_gates(r))
    assert res["gate secrets baseline"]["status"] == "fail" and "secrets-baseline" in res["gate secrets baseline"]["fix"]
    assert res["gate detect-secrets pinned"]["status"] == "fail"
    assert res["gate ci = CI workflow"]["status"] == "warn"
    assert res["gate CI jobs"]["detail"] == "no CI job runs `devbox run security`"


def test_the_gibberish_filter_is_flagged(tmp_path):
    r = make_repo(tmp_path, filters=[*STANDARD, gates.GIBBERISH], ci_recipe="devbox run quality",
                  workflow_runs=["quality"])
    assert by_name(gates.check_gates(r))["gate secrets baseline"]["status"] == "fail"


def test_doctor_runs_the_gate_checks(tmp_path, monkeypatch):
    """AC-081.2: `cplat doctor` includes the gates section for a repo with devbox.json."""
    r = make_repo(tmp_path, filters=STANDARD, ci_recipe="devbox run quality", workflow_runs=["quality"])
    for name in ("check_tools", "check_gh", "check_docker", "check_kube", "check_plugins", "check_platform_source", "check_repo"):
        monkeypatch.setattr(doctor, name, lambda *a: [])
    assert any(c["name"].startswith("gate ") for c in doctor.run_checks(r))


@pytest.mark.skipif(not shutil.which("uvx") and not shutil.which("copier"), reason="adopt renders a template with copier")
def test_adopt_reports_missing_ci_gates(tmp_path):
    """AC-081.3: an adopted repo whose CI runs no template gate is told which ones, and nothing is rewritten."""
    import adopt
    r = tmp_path / "legacy"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/acme/legacy.git"], cwd=r, check=True)
    (r / "README.md").write_text("# legacy\n\nA legacy service.\n")
    (r / ".github" / "workflows").mkdir(parents=True)
    ci = "on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
    (r / ".github" / "workflows" / "ci.yml").write_text(ci)
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], cwd=r, check=True)
    rep = adopt.execute(adopt.resolve(["--type", "service-python", "--repo", str(r), "--data", "module_name=legacy"]))
    assert rep.data["ci_gaps"] == ["quality", "test", "security"]
    assert any("runs no `devbox run quality`" in s for s in rep.next_steps)
    assert (r / ".github" / "workflows" / "ci.yml").read_text() == ci


def test_platform_repo_skips_the_template_gate_checks(tmp_path):
    """#231: a repo with `shape: platform` has no template; recipes and CI jobs are ok, not applicable, no /platform:update."""
    r = make_repo(tmp_path, filters=STANDARD, ci_recipe=None, workflow_runs=["quality"])
    scripts = json.loads((r / "devbox.json").read_text())
    del scripts["shell"]["scripts"]["secrets-baseline"]
    (r / "devbox.json").write_text(json.dumps(scripts))
    before = by_name(gates.check_gates(r))
    assert before["gate recipes"]["status"] == "warn" and before["gate CI jobs"]["status"] == "warn"
    (r / ".platform-settings.yml").write_text("shape: platform\n")
    res = by_name(gates.check_gates(r))
    for name in ("gate recipes", "gate CI jobs"):
        assert res[name]["status"] == "ok" and "not applicable" in res[name]["detail"] and res[name]["fix"] is None
