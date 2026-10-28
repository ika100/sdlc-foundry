"""Spec 125 acceptance tests, `devbox run check` (scripts/check.py): the operator gaps (AC-125.10), `operators: owner` and unreadable
repos (AC-125.11), the release warning and the success lines (AC-125.12), and `check.py --urls` (AC-125.15).

Contract: design.md section 4. The system repos are fixture directories served by a `gh` stub on PATH (`gh repo clone <repo> <tmp> --
--depth 1 --branch main`); the cluster repo is a shared Copier render of templates/cluster-gitops."""
import re

import pytest

from cluster_fixtures import ORG, base, cluster_repo, render_ok, script, stubs, sys_doc, system_repo, write_cluster

ALPHA = f"{ORG}/alpha-gitops"


@pytest.fixture()
def world(shared_renders, tmp_path, monkeypatch):
    repo = cluster_repo(shared_renders, tmp_path)
    s = stubs(tmp_path, monkeypatch)
    (repo / ".platform-version").write_text("platform: 5.1.0\n")
    return repo, s


def register(repo, operators=(), **systems):
    write_cluster(repo, base(operators=list(operators), systems={n: {"repo": slug} for n, slug in systems.items()} or {}))
    render_ok(repo, repo.joinpath("cluster.yaml").read_text())


def check(repo, *args):
    p = script(repo, "check.py", *args)
    return p, p.stdout + p.stderr


def lines(text):
    return text.strip().splitlines()


# ---------------- AC-125.10: operator gaps ----------------

def test_ac_125_10_no_systems_is_ok_without_a_token_or_the_network(world):  # AC-125.10
    repo, s = world
    register(repo)
    p, out = check(repo)
    assert p.returncode == 0 and lines(p.stdout) == ["OK: no systems registered"], out
    assert s["gh_log"].read_text() == "", "no gh call without systems"


def test_ac_125_10_a_database_needs_cloudnative_pg_in_every_environment(world):  # AC-125.10
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha", db_resource=True))
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 1, out
    for env in ("dev", "staging", "prod"):
        assert f"ERROR: alpha ({env}): needs cloudnative-pg, which cluster.yaml does not list in operators" in out
    assert re.search(r"^FAILED: \d+ problem\(s\)$", lines(p.stdout + p.stderr)[-1]), out
    assert "kyverno" not in out


def test_ac_125_10_secrets_need_external_secrets(world):  # AC-125.10
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha", secrets=True))
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 1
    for env in ("dev", "staging", "prod"):
        assert f"ERROR: alpha ({env}): needs external-secrets, which cluster.yaml does not list in operators" in out


def test_ac_125_10_an_external_resource_needs_external_secrets(world):  # AC-125.10
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha", external_db=True))
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 1 and "ERROR: alpha (dev): needs external-secrets, which cluster.yaml does not list in operators" in out


def test_ac_125_10_an_in_cluster_bucket_needs_seaweedfs_and_external_secrets(world):  # AC-125.10
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha", bucket=True))
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 1
    assert "ERROR: alpha (dev): needs seaweedfs, which cluster.yaml does not list in operators" in out
    assert "ERROR: alpha (dev): needs external-secrets, which cluster.yaml does not list in operators" in out


def test_ac_125_10_a_policy_environment_needs_kyverno_only_there(world):  # AC-125.10
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha", policy=True))
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 1 and "ERROR: alpha (dev): needs kyverno, which cluster.yaml does not list in operators" in out
    assert "alpha (staging): needs kyverno" not in out and "alpha (prod): needs kyverno" not in out


def test_ac_125_10_one_line_per_gap_naming_system_environment_and_operator(world):  # AC-125.10
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha", db_resource=True, secrets=True, policy=True))
    register(repo, ["external-secrets"], alpha=ALPHA)
    p, out = check(repo)
    gaps = [ln for ln in lines(out) if " needs " in ln and ln.startswith("ERROR: alpha (")]
    assert "ERROR: alpha (dev): needs kyverno, which cluster.yaml does not list in operators" in gaps
    assert all(re.fullmatch(r"ERROR: alpha \((dev|staging|prod)\): needs [a-z-]+, which cluster.yaml does not list in operators", g) for g in gaps)
    assert not any("external-secrets" in g for g in gaps)
    assert sum("cloudnative-pg" in g for g in gaps) == 3


def test_ac_125_10_a_system_that_does_not_load_fails_naming_the_repo(world):  # AC-125.10
    repo, s = world
    d = system_repo(s["fixtures"], ALPHA, sys_doc("alpha"))
    (d / "applications" / "alpha" / "system.yaml").write_text("system: alpha\nowner: acme\nbogus: true\n")
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 1 and f"ERROR: alpha: {ALPHA} does not render with this cluster's platform release 5.1.0:" in out


def test_ac_125_10_a_repo_without_system_yaml_fails_naming_the_reason(world):  # AC-125.10
    repo, s = world
    d = system_repo(s["fixtures"], ALPHA)
    (d / "README.md").write_text("not a system\n")
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 1 and f"ERROR: alpha: {ALPHA} has no applications/alpha/system.yaml on main" in out


def test_ac_125_10_every_system_of_a_repo_is_checked(world):  # AC-125.10
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha"), extra_systems={"beta": sys_doc("beta", db_resource=True)})
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 1 and "ERROR: beta (dev): needs cloudnative-pg" in out


# ---------------- AC-125.11: operators owner and unreadable repos ----------------

def test_ac_125_11_an_environment_without_operators_owner_fails_with_the_edit(world):  # AC-125.11
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha", owner_envs=("dev", "prod")))
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 1
    assert f"ERROR: alpha (staging): would install operators itself: set environments.staging.operators: owner in {ALPHA}" in out
    assert "alpha (dev): would install" not in out and "alpha (prod): would install" not in out


def test_ac_125_11_an_unreadable_repo_fails_naming_the_repo_and_the_token(world):  # AC-125.11
    repo, s = world
    register(repo, [], alpha=ALPHA)           # no fixture: the gh stub cannot clone it
    p, out = check(repo)
    assert p.returncode == 1
    line = next(ln for ln in lines(out) if ln.startswith("ERROR: alpha: cannot read"))
    assert line.startswith(f"ERROR: alpha: cannot read {ALPHA} (main): ")
    assert "Contents: read" in line and "SYSTEMS_TOKEN" in line and "gh auth login" in line
    assert "GraphQL: Could not resolve to a Repository" in line


def test_ac_125_11_a_failing_check_prints_the_problem_count(world):  # AC-125.11
    repo, s = world
    register(repo, [], alpha=ALPHA)
    p, out = check(repo)
    assert lines(out)[-1] == "FAILED: 1 problem(s)"


# ---------------- AC-125.12: warning and success ----------------

def test_ac_125_12_a_different_platform_release_warns_without_failing(world):  # AC-125.12
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha"), release="5.0.0")
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 0, out
    assert "WARNING: alpha is on platform 5.0.0, this cluster repo on 5.1.0" in out


def test_ac_125_12_the_release_falls_back_to_the_recorded_commit(world):  # AC-125.12
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha"), release=None, commit="v5.0.0")
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 0 and "WARNING: alpha is on platform 5.0.0, this cluster repo on 5.1.0" in out


def test_ac_125_12_an_unknown_release_warns(world):  # AC-125.12
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha"), release=None)
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 0 and "release unknown" in out and "WARNING: alpha" in out


def test_ac_125_12_the_same_release_has_no_warning(world):  # AC-125.12
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha"), release="5.1.0")
    register(repo, alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 0 and "WARNING" not in out


def test_ac_125_12_all_systems_passing_prints_one_line_each_with_its_operators_and_exits_0(world):  # AC-125.12
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha", db_resource=True, secrets=True))
    system_repo(s["fixtures"], f"{ORG}/beta-gitops", sys_doc("beta"))
    register(repo, ["cloudnative-pg", "external-secrets"], alpha=ALPHA, beta=f"{ORG}/beta-gitops")
    p, out = check(repo)
    assert p.returncode == 0, out
    assert lines(p.stdout) == [f"OK: alpha {ALPHA} needs: cloudnative-pg, external-secrets", f"OK: beta {ORG}/beta-gitops needs: none"]


def test_ac_125_12_a_listed_but_unneeded_operator_is_not_an_error(world):  # AC-125.12
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha"))
    register(repo, ["cloudnative-pg", "kyverno"], alpha=ALPHA)
    p, out = check(repo)
    assert p.returncode == 0 and f"OK: alpha {ALPHA} needs: none" in out


# ---------------- AC-125.15: --urls ----------------

def test_ac_125_15_urls_prints_one_line_per_hostname(world):  # AC-125.15
    repo, s = world
    system_repo(s["fixtures"], ALPHA, sys_doc("alpha"), hostnames={"alpha": ["api.alpha-dev.localhost"]})
    register(repo, alpha=ALPHA)
    p, out = check(repo, "--urls")
    assert p.returncode == 0 and lines(p.stdout) == ["alpha api.alpha-dev.localhost"], out


def test_ac_125_15_urls_exits_0_and_warns_on_stderr_for_an_unreadable_repo(world):  # AC-125.15
    repo, s = world
    register(repo, [], alpha=ALPHA)
    p, out = check(repo, "--urls")
    assert p.returncode == 0 and p.stdout.strip() == ""
    assert f"WARNING: alpha: cannot read {ALPHA}" in p.stderr
