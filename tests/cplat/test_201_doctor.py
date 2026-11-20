"""Spec 201 acceptance tests, `/platform:doctor` in a cluster repo with clusters (AC-201.10): the Kubernetes version, the Argo CD version
and the gateway of each cluster, and one warning per item that differs.

Contract: design.md section 9. kubectl is a PATH stub that answers per `--context` (support_201.kube_stub); `doctor.check_repo` runs for
real on a Copier render of templates/cluster-gitops."""
import pytest

import doctor
from cluster_fixtures import base, cluster_repo, git_repo, render_ok, soft, stubs
from support_201 import HOME, LOCAL, kube_stub, multi, run_render, todo, user_settings

LOCAL_CTX, HOME_CTX = "ctx-local", "ctx-home"
CTL = "traefik.io/gateway-controller"
FIX = "upgrade it outside the platform (a cluster prerequisite)"


def cluster_state(k8s="1.31.4", argo="2.13.1", bundle="v1.2.0", controller=CTL, apps=None):
    return {"k8s": k8s, "argo": argo, "bundle": bundle, "gateway": [controller], "apps": apps or {}}


@pytest.fixture()
def world(shared_renders, tmp_path, monkeypatch):
    repo = cluster_repo(shared_renders, tmp_path / "w")
    stubs(tmp_path, monkeypatch)
    run_render(repo, multi(operators=["cloudnative-pg", "external-secrets"], systems=todo()))    # not asserted: the tests show what is missing
    soft(git_repo, repo, tmp_path)
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}, home: {HOME_CTX}}}\n")

    def kube(local=None, home=None, reachable=(LOCAL_CTX, HOME_CTX)):
        return kube_stub(tmp_path, monkeypatch, reachable=reachable,
                         state={LOCAL_CTX: local or cluster_state(), HOME_CTX: home or cluster_state()})
    return repo, kube


def rows(repo, contexts=None):
    found = doctor.check_repo(repo, contexts) if contexts else doctor.check_repo(repo)
    return {c["name"]: c for c in found}


def differing(r):
    return {n: c for n, c in r.items() if n.startswith("clusters differ")}


def test_ac_201_10_each_cluster_shows_its_kubernetes_argo_cd_and_gateway(world):  # AC-201.10
    repo, kube = world
    kube(local=cluster_state("1.31.4", "2.13.1", "v1.2.0"), home=cluster_state("1.31.4", "2.13.1", "v1.2.0"))
    r = rows(repo)
    for c in (LOCAL, HOME):
        assert (r[f"kubernetes ({c})"]["status"], r[f"kubernetes ({c})"]["detail"]) == ("ok", "1.31.4")
        assert (r[f"argo cd ({c})"]["status"], r[f"argo cd ({c})"]["detail"]) == ("ok", "2.13.1")
        assert (r[f"gateway ({c})"]["status"], r[f"gateway ({c})"]["detail"]) == ("ok", f"{CTL} (Gateway API v1.2.0)")


def test_ac_201_10_clusters_that_agree_get_no_warning(world):  # AC-201.10
    repo, kube = world
    kube()
    assert differing(rows(repo)) == {}


def test_ac_201_10_each_cluster_shows_the_checks_of_the_single_cluster_doctor(world):  # AC-201.10
    repo, kube = world
    kube()
    names = set(rows(repo))
    for c in (LOCAL, HOME):
        assert {f"operator cloudnative-pg ({c})", f"operator external-secrets ({c})"} <= names
    assert "system todo (local)" in names


def test_ac_201_10_a_different_kubernetes_minor_is_one_warning_naming_each_value(world):  # AC-201.10
    repo, kube = world
    kube(local=cluster_state(k8s="1.31.4"), home=cluster_state(k8s="1.30.2"))
    d = differing(rows(repo))
    assert set(d) == {"clusters differ: kubernetes"}
    row = d["clusters differ: kubernetes"]
    assert row["status"] == "warn" and row["detail"] == "local 1.31.4, home 1.30.2" and row["fix"] == FIX


def test_ac_201_10_a_patch_difference_is_shown_but_not_warned_about(world):  # AC-201.10
    repo, kube = world
    kube(local=cluster_state(k8s="1.31.4", argo="2.13.1"), home=cluster_state(k8s="1.31.2", argo="2.13.9"))
    r = rows(repo)
    assert r["kubernetes (home)"]["detail"] == "1.31.2" and r["argo cd (home)"]["detail"] == "2.13.9"
    assert differing(r) == {}


def test_ac_201_10_a_different_argo_cd_minor_is_one_warning(world):  # AC-201.10
    repo, kube = world
    kube(local=cluster_state(argo="2.13.1"), home=cluster_state(argo="2.12.9"))
    d = differing(rows(repo))
    assert set(d) == {"clusters differ: argo cd"}
    assert d["clusters differ: argo cd"]["detail"] == "local 2.13.1, home 2.12.9" and d["clusters differ: argo cd"]["fix"] == FIX


def test_ac_201_10_a_different_gateway_version_is_one_warning_with_the_exact_values(world):  # AC-201.10
    repo, kube = world
    kube(local=cluster_state(bundle="v1.2.0"), home=cluster_state(bundle="v1.1.0"))
    d = differing(rows(repo))
    assert set(d) == {"clusters differ: gateway"}
    assert d["clusters differ: gateway"]["detail"] == f"local {CTL} (Gateway API v1.2.0), home {CTL} (Gateway API v1.1.0)"
    assert d["clusters differ: gateway"]["status"] == "warn"


def test_ac_201_10_a_different_gateway_provider_is_one_warning(world):  # AC-201.10
    repo, kube = world
    kube(local=cluster_state(), home=cluster_state(controller="gateway.envoyproxy.io/gatewayclass-controller"))
    d = differing(rows(repo))
    assert set(d) == {"clusters differ: gateway"}
    assert "gateway.envoyproxy.io/gatewayclass-controller" in d["clusters differ: gateway"]["detail"] and CTL in d["clusters differ: gateway"]["detail"]


def test_ac_201_10_every_item_that_differs_gets_its_own_warning(world):  # AC-201.10
    repo, kube = world
    kube(local=cluster_state("1.31.4", "2.13.1", "v1.2.0"), home=cluster_state("1.30.2", "2.12.9", "v1.1.0"))
    assert set(differing(rows(repo))) == {"clusters differ: kubernetes", "clusters differ: argo cd", "clusters differ: gateway"}


def test_ac_201_10_a_cluster_it_cannot_reach_is_one_warning_and_the_others_are_still_shown(world, tmp_path, monkeypatch):  # AC-201.10
    repo, kube = world
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}, home: dead-ctx}}\n")
    kube(reachable=(LOCAL_CTX,))
    r = rows(repo)
    row = r["cluster home"]
    assert row["status"] == "warn"
    assert row["detail"] == "cannot reach cluster home through context dead-ctx: Unable to connect to the server: dial tcp 10.0.0.5:6443: no route to host"
    assert row["fix"].startswith("add kube_contexts: {home: ") and "--context home=<ctx>" in row["fix"]
    assert "kubernetes (local)" in r and not [n for n in r if n.endswith("(home)")], "the unreachable cluster's other rows are skipped"
    assert differing(r) == {}, "one reachable cluster has nothing to compare with"


def test_ac_201_10_a_cluster_without_a_known_context_is_one_warning(world, tmp_path, monkeypatch):  # AC-201.10
    repo, kube = world
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}}}\n")
    kube()
    row = rows(repo)["cluster home"]
    assert row["status"] == "warn" and row["detail"] == "no kube context known for cluster home"
    assert row["fix"].startswith("add kube_contexts: {home: ") and "--context home=<ctx>" in row["fix"]


def test_ac_201_10_the_reachable_clusters_are_still_compared_when_a_third_is_not(shared_renders, tmp_path, monkeypatch):  # AC-201.10
    repo = cluster_repo(shared_renders, tmp_path / "w")
    stubs(tmp_path, monkeypatch)
    run_render(repo, multi(clusters=(LOCAL, HOME, "edge"), operators=["cloudnative-pg"]))
    soft(git_repo, repo, tmp_path)
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}, home: {HOME_CTX}, edge: dead-ctx}}\n")
    kube_stub(tmp_path, monkeypatch, reachable=(LOCAL_CTX, HOME_CTX),
              state={LOCAL_CTX: cluster_state(k8s="1.31.4"), HOME_CTX: cluster_state(k8s="1.30.2")})
    r = rows(repo)
    assert r["cluster edge"]["status"] == "warn" and "dead-ctx" in r["cluster edge"]["detail"]
    assert r["clusters differ: kubernetes"]["detail"] == "local 1.31.4, home 1.30.2"


def test_ac_201_10_contexts_passed_on_the_command_line_name_the_clusters(world, tmp_path, monkeypatch):  # AC-201.10
    repo, kube = world
    user_settings(tmp_path, monkeypatch, None)
    kube(local=cluster_state(k8s="1.31.4"), home=cluster_state(k8s="1.30.2"))
    r = rows(repo, {LOCAL: LOCAL_CTX, HOME: HOME_CTX})
    assert r["kubernetes (home)"]["detail"] == "1.30.2" and r["clusters differ: kubernetes"]["detail"] == "local 1.31.4, home 1.30.2"


def test_ac_201_4_a_repo_without_clusters_gets_the_rows_of_before(shared_renders, tmp_path, monkeypatch):  # AC-201.4
    repo = cluster_repo(shared_renders, tmp_path / "w")
    stubs(tmp_path, monkeypatch)
    render_ok(repo, base(operators=["cloudnative-pg"]))
    git_repo(repo, tmp_path)
    user_settings(tmp_path, monkeypatch, None)
    kube_stub(tmp_path, monkeypatch, reachable=(LOCAL_CTX,), state={LOCAL_CTX: cluster_state()})
    r = rows(repo)
    assert "operator cloudnative-pg" in r
    assert not [n for n in r if n.startswith(("clusters differ", "kubernetes (", "argo cd (", "gateway ("))]
