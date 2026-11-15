"""Spec 201 acceptance tests, `cplat cluster promote <cluster>` (AC-201.8): one PR that moves a later cluster to what the cluster
listed before it runs, only when that cluster is healthy and its smoke tests are green.

Contract: design.md section 7. The cluster repo is a git repo with a bare origin; gh, git and kubectl are PATH stubs or real, kubectl
answers per context (support_201.kube_stub), the system repos are fixtures served by the `gh` stub, and the smoke run of a component
is replaced at `upgradeverify.run_component_smoke` (the seam design.md names)."""
import subprocess

import pytest

import cplat
import upgradeverify
from cluster_fixtures import cluster_repo, git, git_repo, stubs
from support_201 import HOME, KEPT, LOCAL, multi, setup, split_doc, split_repo, todo, user_settings

EDGE = "edge"
LOCAL_CTX = "k3d-local"
HOME_CTX = "k3d-home"
APPS_OK = {"operator-cloudnative-pg": "Synced Healthy"}


def keep(repo, release):
    d = repo / ".platform" / "releases" / release
    d.mkdir(parents=True, exist_ok=True)
    (d / "render.py").write_text(KEPT)


def world(shared_renders, tmp_path, monkeypatch, *, clusters=(LOCAL, HOME), later=None, apps=None, smoke=(True, "3 passed")):
    """Cluster repo on release 5.1.0; `later` maps a later cluster to the release it is pinned to (a renderer is kept for each)."""
    monkeypatch.delenv("CPLAT_HEADLESS", raising=False)
    monkeypatch.delenv("CPLAT_UNIT", raising=False)
    repo = cluster_repo(shared_renders, tmp_path / "w")
    s = stubs(tmp_path, monkeypatch)
    split_repo(s["fixtures"], split_doc())
    from support_201 import kube_stub
    state = {c: {"apps": apps if apps is not None else APPS_OK} for c in (LOCAL_CTX, HOME_CTX)}
    log = kube_stub(tmp_path, monkeypatch, reachable=(LOCAL_CTX, HOME_CTX), state=state)
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}, home: {HOME_CTX}}}\n")
    setup(repo, multi(clusters=clusters, operators=["cloudnative-pg"], systems=todo()))
    (repo / ".platform-version").write_text("platform: 5.1.0\n")
    for cluster, release in (later or {}).items():
        (repo / "clusters" / cluster / "release.yaml").write_text(f"platform: {release}\n")
        keep(repo, release)
    p = subprocess.run(["uv", "run", "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    git_repo(repo, tmp_path)
    calls = []
    if smoke is not None:
        monkeypatch.setattr(upgradeverify, "run_component_smoke", lambda m, comp, env, dirs: calls.append((comp.name, env, dict(dirs))) or smoke)
    return repo, s, log, calls


def promote(repo, capsys, cluster=HOME, *args):
    code = cplat.main(["cluster", "promote", cluster, "--repo-dir", str(repo), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def branches(repo):
    return [b.strip().lstrip("* ") for b in git(repo, "branch", "--format=%(refname:short)").splitlines()]


def pr_creates(s):
    return [ln for ln in s["gh_log"].read_text().splitlines() if ln.startswith("pr create")]


def changed(repo, branch):
    return {ln.split("\t", 1)[1] for ln in git(repo, "diff", "--name-status", f"main..{branch}").splitlines()}


# ---------------- the pull request ----------------

def test_ac_201_8_promote_opens_one_pr_that_moves_the_cluster_to_what_the_cluster_before_it_runs(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"})
    code, out, err = promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")
    assert code == 0, out + err
    assert "https://github.com/acme/home/pull/7" in out
    assert "next: merge it; Argo CD on home then runs what local runs. Wait with: cplat cluster wait home --refresh" in out
    assert len(pr_creates(s)) == 1
    branch = "cluster/promote-home-5.1.0"
    assert branch in branches(repo)
    files = changed(repo, branch)
    assert "clusters/home/release.yaml" in files, "the cluster pins no release any more: it runs this repo's"
    assert any(f.startswith("cluster/home/") for f in files) and any(f.startswith(".platform/releases/4.12.0/") for f in files)
    assert all(f == "clusters/home/release.yaml" or f.startswith(("cluster/home/", ".platform/releases/4.12.0/")) for f in files), files
    msg = git(repo, "log", "-1", "--format=%B", branch)
    assert msg.splitlines()[0] == "feat(cluster): promote home to platform 5.1.0 (what local runs)" and "Signed-off-by:" in msg


def test_ac_201_8_the_pr_leaves_the_rest_of_the_repo_alone(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, _, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"})
    local_before = {p: (repo / p).read_bytes() for p in ("cluster/local/operators-root.yaml", "cluster.yaml", ".platform-version")}
    assert promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")[0] == 0
    git(repo, "checkout", "-q", "cluster/promote-home-5.1.0")
    assert {p: (repo / p).read_bytes() for p in local_before} == local_before
    assert not (repo / "clusters/home/release.yaml").exists() and not (repo / ".platform/releases/4.12.0").exists()


def test_ac_201_8_the_smoke_tests_of_the_environments_on_the_cluster_before_run(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, _, _, calls = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"})
    assert promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")[0] == 0
    assert sorted((c, e) for c, e, _ in calls) == [("api", "dev"), ("api", "staging")], "local runs dev and staging"
    assert all(d.get("api") == str(tmp_path) for _, _, d in calls)


def test_ac_201_8_the_gates_read_the_cluster_before_in_its_own_context(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, _, log, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"})
    assert promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")[0] == 0
    calls = [ln for ln in log.read_text().splitlines() if "operator-cloudnative-pg" in ln or "applications" in ln]
    assert calls and all(f"--context {LOCAL_CTX}" in ln for ln in calls) and not any("config current-context" in ln for ln in log.read_text().splitlines())


def test_ac_201_8_with_three_clusters_the_third_is_promoted_to_what_the_second_runs(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, calls = world(shared_renders, tmp_path, monkeypatch, clusters=(LOCAL, HOME, EDGE), later={HOME: "4.12.0", EDGE: "4.0.0"})
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}, home: {HOME_CTX}, edge: k3d-edge}}\n")
    code, out, err = promote(repo, capsys, EDGE, "--component-dir", f"api={tmp_path}")
    assert code == 0, out + err
    branch = "cluster/promote-edge-4.12.0"
    assert branch in branches(repo)
    files = changed(repo, branch)
    assert "clusters/edge/release.yaml" in files and any(f.startswith(".platform/releases/4.0.0/") for f in files)
    assert all(f == "clusters/edge/release.yaml" or f.startswith(("cluster/edge/", ".platform/releases/4.0.0/")) for f in files), files
    git(repo, "checkout", "-q", branch)
    assert (repo / "clusters/edge/release.yaml").read_text().strip().endswith("platform: 4.12.0")
    assert (repo / ".platform/releases/4.12.0").is_dir(), "home still runs it"
    assert sorted({e for _, e, _ in calls}) == ["prod"], "the gates read home (prod), not local"


# ---------------- no PR ----------------

def test_ac_201_8_an_operator_that_is_not_healthy_stops_the_promotion_naming_it(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"}, apps={"operator-cloudnative-pg": "OutOfSync Degraded"})
    code, out, err = promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")
    assert code == 1
    assert "NOT PROMOTED: local is not ready:" in out and "  operator-cloudnative-pg: OutOfSync, Degraded" in out
    assert "cluster/promote-home-5.1.0" not in branches(repo) and pr_creates(s) == []


def test_ac_201_8_an_operator_application_that_is_missing_stops_the_promotion(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"}, apps={})
    code, out, _ = promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")
    assert code == 1 and "NOT PROMOTED: local is not ready:" in out and "operator-cloudnative-pg" in out and pr_creates(s) == []


def test_ac_201_8_a_red_smoke_test_stops_the_promotion_naming_the_component_and_environment(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"}, smoke=(False, "1 failed: GET /health"))
    code, out, _ = promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")
    assert code == 1 and "NOT PROMOTED: local is not ready:" in out
    assert "  smoke api (dev): 1 failed: GET /health" in out and "  smoke api (staging): 1 failed: GET /health" in out
    assert "cluster/promote-home-5.1.0" not in branches(repo) and pr_creates(s) == []


def test_ac_201_8_a_component_without_a_checkout_is_a_failure(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"}, smoke=None)    # the real smoke runner
    code, out, err = promote(repo, capsys, HOME)
    assert code == 1 and "NOT PROMOTED: local is not ready:" in out
    assert "no checkout of api; pass --component-dir api=<dir>" in out
    assert "cluster/promote-home-5.1.0" not in branches(repo)


def test_ac_201_8_when_the_cluster_already_runs_what_the_one_before_runs_no_pr_is_opened(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, calls = world(shared_renders, tmp_path, monkeypatch)
    code, out, err = promote(repo, capsys, HOME)
    assert code == 0, out + err
    assert "home already runs what local runs (platform 5.1.0); no pull request" in out
    assert pr_creates(s) == [] and "cluster/promote-home-5.1.0" not in branches(repo) and calls == []


def test_ac_201_8_the_dry_run_plans_and_changes_nothing(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"})
    code, out, err = promote(repo, capsys, HOME, "--dry-run", "--component-dir", f"api={tmp_path}")
    assert code == 0, out + err
    assert "5.1.0" in out and pr_creates(s) == [] and "cluster/promote-home-5.1.0" not in branches(repo)
    assert git(repo, "status", "--porcelain").strip() == ""


def test_ac_201_8_a_cluster_whose_predecessor_cannot_be_reached_is_not_promoted(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"})
    user_settings(tmp_path, monkeypatch, None)
    code, out, err = promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")
    assert code != 0 and "cluster local" in err and "no kube context is known" in err
    assert pr_creates(s) == [] and "cluster/promote-home-5.1.0" not in branches(repo)


def test_ac_201_8_an_explicit_context_names_the_cluster_before(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, log, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"})
    user_settings(tmp_path, monkeypatch, None)
    code, out, err = promote(repo, capsys, HOME, "--context", LOCAL_CTX, "--component-dir", f"api={tmp_path}")
    assert code == 0, out + err
    assert len(pr_creates(s)) == 1


# ---------------- who may promote, and what ----------------

def test_ac_201_8_the_first_cluster_is_not_promoted(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch)
    code, out, err = promote(repo, capsys, LOCAL)
    assert code != 0 and "local is the first cluster: it takes each /platform:update directly, so there is nothing to promote" in err
    assert pr_creates(s) == []


def test_ac_201_8_an_unknown_cluster_lists_the_clusters(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, _, _, _ = world(shared_renders, tmp_path, monkeypatch)
    code, _, err = promote(repo, capsys, "mars")
    assert code != 0 and "unknown cluster 'mars' (clusters: local, home)" in err


def test_ac_201_8_a_repo_with_one_cluster_has_nothing_to_promote(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo = cluster_repo(shared_renders, tmp_path / "w")
    stubs(tmp_path, monkeypatch)
    monkeypatch.delenv("CPLAT_HEADLESS", raising=False)
    monkeypatch.delenv("CPLAT_UNIT", raising=False)
    from cluster_fixtures import base, render_ok
    render_ok(repo, base())
    git_repo(repo, tmp_path)
    code, _, err = promote(repo, capsys, HOME)
    assert code != 0 and "this cluster repo has one cluster; there is nothing to promote" in err


@pytest.mark.parametrize("var", ["CPLAT_HEADLESS", "CPLAT_UNIT"])
def test_ac_201_8_no_ship_update_or_engine_run_opens_a_promotion(shared_renders, tmp_path, monkeypatch, capsys, var):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"})
    monkeypatch.setenv(var, "1")
    code, out, err = promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")
    assert code != 0
    assert "a promotion is opened by a person, never by a ship, update or engine run" in err
    assert "run /cluster:promote home yourself" in err
    assert pr_creates(s) == [] and "cluster/promote-home-5.1.0" not in branches(repo)


def test_ac_201_8_an_unclean_tree_is_refused_before_anything_else(shared_renders, tmp_path, monkeypatch, capsys):  # AC-201.8
    repo, s, _, _ = world(shared_renders, tmp_path, monkeypatch, later={HOME: "4.12.0"})
    (repo / "stray.txt").write_text("x")
    code, _, err = promote(repo, capsys, HOME, "--component-dir", f"api={tmp_path}")
    assert code != 0 and err.startswith("ERROR: ") and pr_creates(s) == []
