"""Specs 073, 074 and 075: scanners agree locally and in CI, CI runs once per change, `devbox run ci` is CI's gate."""
import json
import re
import shutil
import subprocess

import pytest
import yaml

import core
from test_spec_driven import IDS, claude_md, template

ROOT = core.PLATFORM_ROOT
GIBBERISH = "detect_secrets.filters.gibberish.should_exclude_secret"


def devbox(shape):
    t = template(shape)
    f = t / "devbox.json" if (t / "devbox.json").is_file() else t / "devbox.json.jinja"
    text = f.read_text()
    return text, re.findall(r'"([a-z0-9-]+)@([^"]+)"', text.split('"shell"', 1)[0])


def recipe(shape, name):
    m = re.search(rf'^\s*"{re.escape(name)}":\s*"(.*)",?$', devbox(shape)[0], re.M)
    assert m, f"{shape}: no {name} recipe"
    return m.group(1)


def workflow(shape):
    """ci.yml as YAML; templates that render every file escape GitHub expressions, which are undone here."""
    text = (template(shape) / ".github" / "workflows" / "ci.yml").read_text()
    if yaml.safe_load((template(shape) / "copier.yml").read_text()).get("_templates_suffix", ".jinja") == "":
        text = text.replace("{{ '{{' }}", "{{").replace("{{ '}}' }}", "}}")
    return yaml.safe_load(text)


# ---------------- spec 073 ----------------

def test_scanners_are_pinned_to_one_version_everywhere():
    """AC-073.1: detect-secrets and trivy are never @latest, and every template pins the same version."""
    versions: dict[str, set[str]] = {"detect-secrets": set(), "trivy": set()}
    for shape in IDS:
        pkgs = dict(devbox(shape)[1])
        assert "detect-secrets" in pkgs, shape
        for tool in versions:
            if tool in pkgs:
                assert pkgs[tool] != "latest", f"{shape}: {tool}@latest"
                versions[tool].add(pkgs[tool])
    assert all(len(v) == 1 for v in versions.values()), versions


@pytest.mark.parametrize("shape", IDS)
def test_baselines_keep_the_standard_filters_and_no_gibberish(shape):
    """AC-073.2: the pragma filter and the heuristics are on; the machine-dependent gibberish filter is not."""
    base = json.loads((template(shape) / ".secrets.baseline.json").read_text())
    paths = {f["path"] for f in base["filters_used"]}
    assert "detect_secrets.filters.allowlist.is_line_allowlisted" in paths
    assert {"detect_secrets.filters.heuristic.is_sequential_string", "detect_secrets.filters.heuristic.is_likely_id_string",
            "detect_secrets.filters.heuristic.is_templated_secret"} <= paths
    assert GIBBERISH not in paths and base["results"] == {}


@pytest.mark.skipif(not shutil.which("detect-secrets-hook"), reason="detect-secrets is not on PATH (devbox shell has it)")
def test_the_pragma_works_with_the_template_baseline(tmp_path):
    """AC-073.2: a line marked `pragma: allowlist secret` passes the hook CI runs; an unmarked one fails."""
    shutil.copy(template("service-go") / ".secrets.baseline.json", tmp_path / ".secrets.baseline.json")
    (tmp_path / "a.py").write_text('password = "hunter2xyzQ9"  # pragma: allowlist secret\n')
    hook = ["detect-secrets-hook", "--baseline", ".secrets.baseline.json", "a.py"]
    assert subprocess.run(hook, cwd=tmp_path, capture_output=True).returncode == 0
    (tmp_path / "a.py").write_text('password = "hunter2xyzQ9"\n')
    assert subprocess.run(hook, cwd=tmp_path, capture_output=True).returncode != 0


@pytest.mark.parametrize("shape", IDS)
def test_secrets_baseline_recipe_refreshes_with_fixed_flags(shape):
    """AC-073.3: one recipe refreshes the baseline (keeping audits), without gibberish; agents are told to use it."""
    cmd = recipe(shape, "secrets-baseline")
    fresh, refresh = cmd.split("; ")
    assert fresh.startswith("grep -qs is_line_allowlisted .secrets.baseline.json || detect-secrets scan")   # repairs a broken one
    assert refresh.startswith("detect-secrets scan --baseline .secrets.baseline.json")                          # keeps audits
    assert all(f"--disable-filter {GIBBERISH}" in c for c in (fresh, refresh))
    scan = recipe(shape, "secrets-scan")
    assert "uv run" not in scan                                   # the pinned devbox binary, not a second copy
    assert f"--disable-filter {GIBBERISH}" in scan                # a hook that rewrites the baseline must not add it back
    assert "`secrets-baseline`" in claude_md(shape)
    assert "devbox run secrets-baseline" in (ROOT / "plugins" / "shared" / "agents" / "security.md").read_text()


# ---------------- spec 074 ----------------

@pytest.mark.parametrize("shape", IDS)
def test_ci_runs_once_per_change(shape):
    """AC-074.1: push only for main (and release tags); branches run as their pull request; superseded PR runs cancel."""
    wf = workflow(shape)
    on = wf[True]                                  # YAML 1.1 reads `on` as true
    assert on["push"]["branches"] == ["main"]
    assert on["push"].get("tags", ["v*.*.*"]) == ["v*.*.*"]
    assert on["pull_request"]["branches"] == ["main"]
    assert "pull_request" in wf["concurrency"]["cancel-in-progress"]


def test_runner_guide_recommends_a_persistent_docker_volume():
    """AC-074.2: the build cache is a dind volume per runner set, not a registry cache."""
    text = " ".join((ROOT / "docs" / "self-hosted-runners.md").read_text().split())
    assert "persistent dind `/var/lib/docker` volume per runner set" in text and "type=registry" in text


# ---------------- spec 075 ----------------

@pytest.mark.parametrize("shape", IDS)
def test_devbox_ci_runs_the_workflow_gates_in_job_order(shape):
    """AC-075.1: `devbox run ci` chains exactly the `devbox run` steps of ci.yml's jobs, in order."""
    gates: list[str] = []
    for job in workflow(shape)["jobs"].values():
        for step in job.get("steps", []):
            m = re.fullmatch(r"devbox run ([\w-]+)", str(step.get("run", "")).strip())
            if m and m.group(1) not in gates:
                gates.append(m.group(1))
    assert gates, shape

    def real(name):   # `quality` that is only `devbox run validate` is the same gate as `validate`
        m = re.fullmatch(r"devbox run ([\w-]+)", recipe(shape, name))
        return real(m.group(1)) if m else name
    chained = re.findall(r"devbox run ([\w-]+)", recipe(shape, "ci"))
    assert [real(g) for g in chained] == [real(g) for g in gates]


def test_shape_check_requires_the_new_recipes():
    """AC-075.1 AC-073.3: the shape contract names ci and secrets-baseline."""
    import shapes
    assert {"ci", "secrets-baseline"} <= set(shapes.CORE_RECIPES)
    assert shapes.check_contract(core.registry.load()) == []


def test_build_and_ship_run_devbox_ci_before_pushing():
    """AC-075.3: the commands run the CI gate once on the final tree."""
    build = (ROOT / "plugins" / "svc" / "commands" / "build.md").read_text()
    ship = (ROOT / "plugins" / "svc" / "commands" / "ship.md").read_text()
    phase3 = build.split("## Phase 3", 1)[1].split("## Phase 4", 1)[0]
    assert "devbox run ci" in phase3 and "devbox run ci" in ship
