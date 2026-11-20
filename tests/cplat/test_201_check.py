"""Spec 201 acceptance tests, `devbox run check` (scripts/check.py) in a cluster repo with clusters: the operators each cluster needs
(AC-201.2), the assignment of every environment (AC-201.3), the release gate for systems on several clusters (AC-201.4) and the
exception and behind lines (AC-201.2, AC-201.7).

Contract: design.md section 4. The system repos are fixture directories served by a `gh` stub on PATH; the cluster repo is a shared
Copier render of templates/cluster-gitops."""
import pytest

from cluster_fixtures import ORG, cluster_repo, script, stubs
from support_201 import HOME, LOCAL, SPLIT, TODO_REPO, multi, pin_release, setup, split_doc, split_repo, stdout_lines, todo

ALL_LOCAL = {"dev": LOCAL, "staging": LOCAL, "prod": LOCAL}


@pytest.fixture()
def world(shared_renders, tmp_path, monkeypatch):
    repo = cluster_repo(shared_renders, tmp_path)
    s = stubs(tmp_path, monkeypatch)
    (repo / ".platform-version").write_text("platform: 5.1.0\n")
    return repo, s


def register(repo, systems, exceptions=None, operators=("cloudnative-pg",)):
    setup(repo, multi(operators=operators, systems=systems), exceptions)
    p = script(repo, "render.py")
    assert p.returncode == 0, p.stdout + p.stderr


def check(repo):
    p = script(repo, "check.py")
    return p, p.stdout + p.stderr


# ---------------- AC-201.2: operators per cluster ----------------

def test_ac_201_2_an_operator_missing_on_the_cluster_that_runs_the_environment_fails(world):  # AC-201.2
    repo, s = world
    split_repo(s["fixtures"], split_doc(db_resource=True))
    register(repo, todo(), {HOME: {"operators": {"cloudnative-pg": False}}})
    p, out = check(repo)
    assert p.returncode == 1, out
    assert "ERROR: todo (prod): needs cloudnative-pg, which cluster home does not install" in out
    assert "todo (dev)" not in out and "todo (staging)" not in out, "dev and staging run on local, which installs it"


def test_ac_201_2_the_exception_line_is_printed_before_the_checks(world):  # AC-201.2
    repo, s = world
    split_repo(s["fixtures"], split_doc(db_resource=True))
    register(repo, todo(), {HOME: {"operators": {"cloudnative-pg": False}}})
    p, _ = check(repo)
    assert stdout_lines(p)[0] == "EXCEPTION: cluster home: operator cloudnative-pg: not installed (shared: installed)", p.stdout


def test_ac_201_2_an_operator_missing_on_a_cluster_that_runs_no_such_environment_does_not_fail(world):  # AC-201.2
    repo, s = world
    split_repo(s["fixtures"], split_doc(cluster_keys=ALL_LOCAL, db_resource=True))
    register(repo, todo(ALL_LOCAL), {HOME: {"operators": {"cloudnative-pg": False}}})
    p, out = check(repo)
    assert p.returncode == 0, out
    assert "ERROR" not in out


def test_ac_201_2_a_system_without_environments_is_checked_against_the_first_cluster(world):  # AC-201.2
    repo, s = world
    split_repo(s["fixtures"], split_doc(cluster_keys=None, db_resource=True), roots=False)
    register(repo, todo(None), {LOCAL: {"operators": {"cloudnative-pg": False}}}, operators=("cloudnative-pg", "external-secrets"))
    p, out = check(repo)
    assert p.returncode == 1
    for env in ("dev", "staging", "prod"):
        assert f"ERROR: todo ({env}): needs cloudnative-pg, which cluster local does not install" in out


def test_ac_201_2_an_operator_left_out_on_every_cluster_fails_on_each_one(world):  # AC-201.2
    repo, s = world
    split_repo(s["fixtures"], split_doc(db_resource=True))
    register(repo, todo(), {LOCAL: {"operators": {"cloudnative-pg": False}}, HOME: {"operators": {"cloudnative-pg": False}}}, operators=("cloudnative-pg",))
    p, out = check(repo)
    assert p.returncode == 1 and "needs cloudnative-pg, which cluster local does not install" in out and "cluster home does not install" in out


# ---------------- AC-201.3: every environment is assigned ----------------

def test_ac_201_3_an_environment_the_system_declares_but_the_assignment_leaves_out_fails(world):  # AC-201.3
    repo, s = world
    split_repo(s["fixtures"], split_doc())
    register(repo, todo({"dev": LOCAL, "staging": LOCAL}))
    p, out = check(repo)
    assert p.returncode == 1
    assert f"ERROR: todo (prod): {TODO_REPO} declares prod, which systems.todo.environments in cluster.yaml leaves out; assign it to a cluster" in out


def test_ac_201_3_a_consistent_assignment_passes(world):  # AC-201.3
    repo, s = world
    split_repo(s["fixtures"], split_doc())
    register(repo, todo())
    p, out = check(repo)
    assert p.returncode == 0 and "ERROR" not in out and "FAILED" not in out, out


def test_ac_201_3_a_system_repo_that_sets_another_cluster_fails_naming_both(world):  # AC-201.3
    repo, s = world
    split_repo(s["fixtures"], split_doc(cluster_keys={"dev": LOCAL, "staging": LOCAL, "prod": LOCAL}))
    register(repo, todo())
    p, out = check(repo)
    assert p.returncode == 1
    assert f"ERROR: todo (prod): cluster.yaml runs it on home, but {TODO_REPO} sets environments.prod.cluster: local; set it to home in {TODO_REPO}" in out
    assert "todo (dev)" not in out and "todo (staging)" not in out


def test_ac_201_3_a_system_repo_that_sets_no_cluster_names_nothing(world):  # AC-201.3
    repo, s = world
    split_repo(s["fixtures"], split_doc(cluster_keys=None), roots=False)
    register(repo, todo())
    p, out = check(repo)
    assert p.returncode == 1
    for env, c in SPLIT.items():
        assert f"ERROR: todo ({env}): cluster.yaml runs it on {c}, but {TODO_REPO} sets environments.{env}.cluster: nothing; set it to {c} in {TODO_REPO}" in out


def test_ac_201_3_a_missing_environment_root_on_main_fails_naming_the_file(world):  # AC-201.3
    repo, s = world
    split_repo(s["fixtures"], split_doc(), roots=False)
    register(repo, todo())
    p, out = check(repo)
    assert p.returncode == 1
    for env in ("dev", "staging", "prod"):
        assert f"ERROR: todo: {TODO_REPO} has no bootstrap/environments/todo-{env}.yaml on main; run devbox run render in {TODO_REPO} and merge it" in out


# ---------------- AC-201.4: only an updated system repo can be split ----------------

@pytest.mark.parametrize("release, shown", [("4.0.0", "4.0.0"), (None, "unknown")])
def test_ac_201_4_a_system_on_several_clusters_with_an_earlier_release_fails_naming_the_step(world, release, shown):  # AC-201.4
    repo, s = world
    split_repo(s["fixtures"], split_doc(cluster_keys=None), release=release, roots=False)
    register(repo, todo())
    p, out = check(repo)
    assert p.returncode == 1
    assert (f"ERROR: todo runs on clusters local, home, but {TODO_REPO} is on platform {shown}, older than this cluster repo (5.1.0); "
            f"run /platform:update in {TODO_REPO} first") in out
    assert "bootstrap/environments" not in out, "the release gate ends the system's checks"


def test_ac_201_4_a_system_on_one_cluster_with_an_earlier_release_still_passes(world):  # AC-201.4
    repo, s = world
    split_repo(s["fixtures"], split_doc(cluster_keys=None), release="4.0.0", roots=False)
    register(repo, todo(None))
    p, out = check(repo)
    assert p.returncode == 0 and "ERROR" not in out, out


# ---------------- AC-201.7: behind lines ----------------

def test_ac_201_7_check_prints_one_behind_line_per_later_cluster_and_exits_0(world):  # AC-201.7
    repo, _ = world
    setup(repo, multi())
    pin_release(repo)
    p, out = check(repo)
    assert p.returncode == 0, out
    assert stdout_lines(p) == ["BEHIND: cluster home runs platform 4.12.0, cluster local runs 5.1.0; promote it with /cluster:promote home",
                               "OK: no systems registered"]


def test_ac_201_2_check_prints_the_exception_lines_even_without_systems(world):  # AC-201.2
    repo, _ = world
    setup(repo, multi(), {HOME: {"server": "https://10.0.0.5:6443"}})
    p, out = check(repo)
    assert p.returncode == 0, out
    assert stdout_lines(p) == ["EXCEPTION: cluster home: server: https://10.0.0.5:6443 (shared: https://kubernetes.default.svc)",
                               "OK: no systems registered"]


def test_ac_201_4_a_repo_without_clusters_keeps_its_messages(world):  # AC-201.4
    repo, s = world
    from cluster_fixtures import base, render_ok, sys_doc, system_repo
    system_repo(s["fixtures"], f"{ORG}/alpha-gitops", sys_doc("alpha", db_resource=True))
    render_ok(repo, base(systems={"alpha": {"repo": f"{ORG}/alpha-gitops"}}))
    p, out = check(repo)
    assert p.returncode == 1
    assert "ERROR: alpha (dev): needs cloudnative-pg, which cluster.yaml does not list in operators" in out
    assert "EXCEPTION" not in out and "BEHIND" not in out
