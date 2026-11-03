"""Spec 134: the e2e workflow decides per pull request and runs three parts; the upgrade e2e decides on the PR's base (AC-134.1, .4, .6)."""
import re

import yaml

from system_fixtures import ROOT

WF = ROOT / ".github" / "workflows"


def workflow(name: str) -> dict:
    return yaml.safe_load((WF / name).read_text())


def triggers(wf: dict) -> dict:
    return wf.get("on") or wf.get(True)      # YAML 1.1 reads the key `on` as True


def test_the_e2e_workflow_has_no_pr_path_filter_and_a_decide_job_ac_134_1():  # AC-134.1
    wf = workflow("e2e.yml")
    on = triggers(wf)
    assert {"pull_request", "schedule", "workflow_dispatch"} <= set(on)
    assert not (on["pull_request"] or {}).get("paths")
    decide = wf["jobs"]["decide"]
    assert decide["name"] == "does this change need the cluster e2e" and decide["timeout-minutes"] == 2
    assert decide["outputs"]["run"] == "${{ steps.needs.outputs.run }}"
    checkout = next(s for s in decide["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0
    step = next(s for s in decide["steps"] if s.get("id") == "needs")
    assert step["env"]["BASE"] == "${{ github.event.pull_request.base.sha }}"
    assert re.search(r'scripts/e2e-scope\.py --base "\$BASE" \| tee -a "\$GITHUB_OUTPUT"', step["run"])


def test_every_cluster_job_needs_decide_and_runs_on_true_or_a_schedule_ac_134_1():  # AC-134.1
    jobs = workflow("e2e.yml")["jobs"]
    others = {k: j for k, j in jobs.items() if k != "decide"}
    assert set(others) == {"e2e", "e2e-cluster"}
    for name, job in others.items():
        needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
        assert "decide" in needs, name
        cond = job["if"]
        assert "needs.decide.outputs.run == 'true'" in cond and "github.event_name == 'schedule'" in cond \
            and "github.event_name == 'workflow_dispatch'" in cond, (name, cond)


def test_the_e2e_job_is_three_parts_on_a_pr_and_all_otherwise_ac_134_6():  # AC-134.6
    job = workflow("e2e.yml")["jobs"]["e2e"]
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"]["part"] == \
        """${{ fromJSON(github.event_name == 'pull_request' && '["core","scaling","backups"]' || '["all"]') }}"""
    assert job["name"] == "e2e ${{ matrix.part }} (render → build → k3d → Gateway)"
    assert job["timeout-minutes"] == "${{ matrix.part == 'all' && 90 || 45 }}"
    run = next(s for s in job["steps"] if "tests/e2e/run.sh" in s.get("run", ""))
    assert run["env"]["E2E_PART"] == "${{ matrix.part }}" and run["run"].strip() == "bash tests/e2e/run.sh"


def test_the_cluster_job_is_unchanged_but_for_decide_ac_134_6():  # AC-134.6
    job = workflow("e2e.yml")["jobs"]["e2e-cluster"]
    assert job["name"] == "e2e cluster (two systems, one operator)" and job["timeout-minutes"] == 20
    assert any("bash tests/e2e/cluster.sh" in s.get("run", "") for s in job["steps"])
    assert "strategy" not in job


def test_the_upgrade_e2e_decides_on_the_pull_requests_base_ac_134_4():  # AC-134.4
    wf = workflow("e2e-upgrade.yml")
    step = next(s for s in wf["jobs"]["decide"]["steps"] if s.get("id") == "needs")
    assert step["env"]["BASE"] == "${{ github.event.pull_request.base.sha }}"
    # an empty BASE (push, schedule, dispatch) keeps release-check.py's default base, the latest tag
    assert re.search(r'release-check\.py needs-upgrade-e2e \$\{BASE:\+--base "\$BASE"\} \| tee -a "\$GITHUB_OUTPUT"', step["run"])
    assert "push" in triggers(wf)
