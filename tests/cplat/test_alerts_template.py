"""Spec 092: the gitops-app template carries the alert poll: a 15-minute workflow on the self-hosted runner only, a hand-started dry
run, the state artifact, `scripts/alert-poll.sh` and the lgtm Prometheus port. Static checks of the template, a generated repo,
and the script run against a fake platform and a fake `uv`."""
import fnmatch
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from test_gitops import gh, gitops_repo  # noqa: F401  (fixtures)

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "gitops-app"
WORKFLOW = TEMPLATE / ".github" / "workflows" / "alerts.yml"
SCRIPT = TEMPLATE / "scripts" / "alert-poll.sh"
SKIP_NOTE = "alert poll skipped: needs the self-hosted runner (set the CI_RUNNER variable)"


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def triggers(wf):
    return wf.get("on", wf.get(True))


def expr(text):
    """`${{ x }}` -> `x`."""
    return re.sub(r"^\$\{\{\s*(.*?)\s*\}\}$", r"\1", str(text).strip())


# ---------------- AC-092.1 the scheduled poll ----------------

def test_the_workflow_runs_every_15_minutes_and_can_be_started_by_hand():
    """AC-092.1: cron `*/15 * * * *` plus workflow_dispatch with a boolean dry_run input."""
    on = triggers(workflow())
    assert on["schedule"] == [{"cron": "*/15 * * * *"}]
    assert on["workflow_dispatch"]["inputs"]["dry_run"]["type"] == "boolean"


def test_the_poll_runs_the_devbox_recipe_with_the_tokens_it_needs():
    """AC-092.1: the poll step runs `devbox run alert-poll` with the workflow token, ALERTS_TOKEN and the dry-run switch."""
    wf = workflow()
    (poll,) = [s for s in wf["jobs"]["poll"]["steps"] if s.get("run")]
    assert poll["run"].strip() == "devbox run alert-poll"
    assert {"GH_TOKEN", "ALERTS_TOKEN", "ALERTS_QUERY_AUTHORIZATION", "ALERTS_PROMETHEUS_URL", "ALERTS_DRY_RUN"} <= set(poll["env"])
    assert wf["permissions"]["issues"] == "write" and wf["permissions"]["actions"] == "read"


def test_the_poll_state_is_carried_between_runs_as_an_artifact_except_in_a_dry_run():
    """AC-092.17 AC-092.18: `.alert-poll/state.json` is uploaded as `alert-poll-state` for 3 days, never from a dry run."""
    steps = workflow()["jobs"]["poll"]["steps"]
    (up,) = [s for s in steps if "upload-artifact" in s.get("uses", "")]
    assert re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", up["uses"])
    assert up["with"]["name"] == "alert-poll-state" and up["with"]["path"] == ".alert-poll/state.json" and up["with"]["retention-days"] == 3
    assert "!inputs.dry_run" in expr(up["if"])
    assert workflow()["concurrency"]["group"] == "alert-poll"


def test_the_workflow_actions_are_pinned_by_sha():
    """AC-092.1: every `uses:` is a full commit SHA (the platform's pinned-actions check)."""
    uses = [s["uses"] for s in workflow()["jobs"]["poll"]["steps"] if "uses" in s]
    assert uses and all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in uses)


def test_a_generated_gitops_repo_has_the_poll(gitops_repo, gh):  # noqa: F811
    """AC-092.1: a freshly generated gitops-app repo has the workflow, the script, the recipe and the ignore rule."""
    assert (gitops_repo / ".github/workflows/alerts.yml").read_text() == WORKFLOW.read_text()
    assert (gitops_repo / "scripts/alert-poll.sh").is_file()
    assert json.loads((gitops_repo / "devbox.json").read_text())["shell"]["scripts"]["alert-poll"] == "bash scripts/alert-poll.sh"
    assert ".alert-poll/" in (gitops_repo / ".gitignore").read_text().splitlines()


def test_update_service_delivers_the_poll_to_existing_repos():
    """AC-092.1: neither the workflow nor the script is project-owned, so `/shared:update-service` adds them."""
    assert WORKFLOW.is_file() and SCRIPT.is_file()
    skip = yaml.safe_load((TEMPLATE / "copier.yml").read_text())["_skip_if_exists"]
    for path in (".github/workflows/alerts.yml", "scripts/alert-poll.sh", "devbox.json"):
        assert not any(fnmatch.fnmatch(path, pattern) for pattern in skip), path


def test_the_devbox_recipe_exists():
    """AC-092.1: `alert-poll` is a devbox recipe of the template."""
    assert json.loads((TEMPLATE / "devbox.json").read_text())["shell"]["scripts"]["alert-poll"] == "bash scripts/alert-poll.sh"


# ---------------- AC-092.3 only the self-hosted runner ----------------

def test_the_poll_never_runs_on_a_github_hosted_runner():
    """AC-092.3: runs-on is the CI_RUNNER variable, the job is skipped without it, and no hosted label appears anywhere in the file."""
    wf = workflow()
    job = wf["jobs"]["poll"]
    assert expr(job["runs-on"]) == "vars.CI_RUNNER" and expr(job["if"]) == "vars.CI_RUNNER != ''"
    text = WORKFLOW.read_text()
    assert not re.search(r"ubuntu-|macos-|windows-", text) and len(wf["jobs"]) == 1


def test_without_a_runner_the_run_and_the_job_say_the_poll_needs_the_self_hosted_runner():
    """AC-092.3: the run name and the job name are the explanation on GitHub's summary page."""
    wf = workflow()
    assert SKIP_NOTE in wf["run-name"] and SKIP_NOTE in wf["jobs"]["poll"]["name"]
    assert "vars.CI_RUNNER" in wf["run-name"] and "vars.CI_RUNNER" in wf["jobs"]["poll"]["name"]


# ---------------- AC-092.19 Prometheus in the local lgtm stack ----------------

def test_the_local_lgtm_stack_exposes_prometheus_on_9090():
    """AC-092.19: the lgtm Deployment and Service of `cluster-up` carry a `prometheus` port 9090 for the poll."""
    text = (TEMPLATE / "scripts" / "local-cluster.sh").read_text()
    assert re.search(r"name:\s*prometheus,\s*containerPort:\s*9090", text)
    assert re.search(r"name:\s*prometheus,\s*port:\s*9090,\s*targetPort:\s*prometheus", text)


# ---------------- AC-092.1 / AC-092.18 alert-poll.sh ----------------

@pytest.fixture()
def sh(tmp_path):
    """Run alert-poll.sh in a scratch repo with a fake `uv` that records its arguments and a fake platform checkout."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$UV_LOG"\n')
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    work = tmp_path / "repo"
    work.mkdir()

    def run(*, platform_has_alerts, dry_run=False):
        platform = tmp_path / "platform"
        (platform / "scripts" / "cplat").mkdir(parents=True, exist_ok=True)
        (platform / "scripts" / "cplat" / "cplat.py").write_text("")
        if platform_has_alerts:
            (platform / "scripts" / "cplat" / "alerts.py").write_text("")
        summary, log = tmp_path / "summary.md", tmp_path / "uv.log"
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ALERTS_PLATFORM": str(platform), "UV_LOG": str(log),
               "GITHUB_STEP_SUMMARY": str(summary), "ALERTS_DRY_RUN": "1" if dry_run else ""}
        p = subprocess.run(["bash", str(SCRIPT)], cwd=work, env=env, capture_output=True, text=True, timeout=60)
        return p, platform, (log.read_text() if log.exists() else None), (summary.read_text() if summary.exists() else "")

    return run


def test_the_script_runs_the_alert_poll_of_the_platform_it_is_pinned_to(sh):
    """AC-092.1: `uv run <platform>/scripts/cplat/cplat.py alerts poll --repo-dir .`, without --dry-run by default."""
    p, platform, log, _ = sh(platform_has_alerts=True)
    assert p.returncode == 0, p.stderr
    assert log and f"run --quiet {platform}/scripts/cplat/cplat.py alerts poll --repo-dir ." in log.strip() and "--dry-run" not in log


def test_a_hand_started_dry_run_reaches_the_command(sh):
    """AC-092.18: ALERTS_DRY_RUN=1 (the dry_run input) becomes `--dry-run`."""
    p, _, log, _ = sh(platform_has_alerts=True, dry_run=True)
    assert p.returncode == 0 and log and "alerts poll --repo-dir . --dry-run" in log


def test_a_platform_without_the_alert_poll_is_a_green_run_that_says_to_update(sh):
    """AC-092.1: a repo pinned to a platform older than spec 092 exits 0 and tells the operator to run /shared:update-service."""
    p, _, log, summary = sh(platform_has_alerts=False)
    msg = "has no alert poll (spec 092); run /shared:update-service"
    assert p.returncode == 0 and log is None and msg in p.stdout and msg in summary
