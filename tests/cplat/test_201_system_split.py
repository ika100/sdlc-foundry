"""Spec 201 acceptance tests, the system repo: `environments.<env>.cluster` and the split form (AC-201.3, AC-201.4, AC-201.5).

Contract: design.md section 1. The renderer of templates/gitops-app runs as a script in a hand-built checkout (system_fixtures);
the model is read with `model.load_dir`."""
import copy
import subprocess
import sys

import pytest
import yaml

from resources_fixtures import comp, db, system
from support_201 import ENVS, NO_FINALIZER, docs_of
from system_fixtures import ROOT, generated, render5, write_system

FIN = [NO_FINALIZER]
SPLIT_KEYS = {"dev": "local", "staging": "local", "prod": "home"}
APP = "applications/shop"


def shop(clusters=SPLIT_KEYS) -> dict:
    doc = system({"db": db()}, {"api": comp("api", ["db"])})
    for env, c in (clusters or {}).items():
        doc["environments"][env]["cluster"] = c
    return doc


def split(tmp_path, clusters=SPLIT_KEYS):
    p = render5(tmp_path, shop(clusters))
    assert p.returncode == 0, p.stdout + p.stderr
    return generated(tmp_path)


def plain(tmp_path):
    p = render5(tmp_path, shop(None))
    assert p.returncode == 0, p.stdout + p.stderr
    return generated(tmp_path)


# ---------------- AC-201.3 / AC-201.5: the split form ----------------

def test_ac_201_3_a_system_with_cluster_keys_renders_one_applicationset_file_per_environment(tmp_path):  # AC-201.3
    files = split(tmp_path)
    for env in ENVS:
        names = [d["metadata"]["name"] for d in docs_of(files[f"{APP}/applicationset-{env}.yaml"])]
        assert names == [f"shop-{env}", f"shop-addons-{env}", f"shop-policies-{env}"], env


def test_ac_201_5_every_applicationset_keeps_its_applications_when_it_is_deleted(tmp_path):  # AC-201.5
    files = split(tmp_path)
    for env in ENVS:
        for d in docs_of(files[f"{APP}/applicationset-{env}.yaml"]):
            assert d["kind"] == "ApplicationSet" and d["spec"]["syncPolicy"] == {"preserveResourcesOnDeletion": True}, d["metadata"]["name"]


def test_ac_201_3_the_split_documents_are_the_one_file_documents_of_that_environment(tmp_path):  # AC-201.3
    whole = docs_of(split(tmp_path / "a")[f"{APP}/applicationset.yaml"])
    files = split(tmp_path / "b")
    for env in ENVS:
        want = []
        for d in whole:
            if d["metadata"]["name"].endswith(f"-{env}"):
                d = copy.deepcopy(d)
                d["spec"]["syncPolicy"] = {"preserveResourcesOnDeletion": True}
                want.append(d)
        assert docs_of(files[f"{APP}/applicationset-{env}.yaml"]) == want, env


def test_ac_201_3_applicationset_yaml_stays_byte_identical_to_the_render_without_cluster_keys(tmp_path):  # AC-201.3
    assert split(tmp_path / "a")[f"{APP}/applicationset.yaml"] == plain(tmp_path / "b")[f"{APP}/applicationset.yaml"]


def test_ac_201_5_each_environment_gets_a_root_with_a_resources_finalizer(tmp_path):  # AC-201.5
    files = split(tmp_path)
    url = yaml.safe_load(files["bootstrap/shop-root.yaml"])["spec"]["source"]["repoURL"]
    for env in ENVS:
        got = yaml.safe_load(files[f"bootstrap/environments/shop-{env}.yaml"])
        assert got == {
            "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
            "metadata": {"name": f"shop-{env}-root", "namespace": "argocd", "finalizers": FIN},
            "spec": {"project": "default",
                     "source": {"repoURL": url, "targetRevision": "main", "path": "applications/shop",
                                "directory": {"include": f"applicationset-{env}.yaml"}},
                     "destination": {"server": "https://kubernetes.default.svc", "namespace": "argocd"},
                     "syncPolicy": {"automated": {"prune": True, "selfHeal": True}}}}, env


def test_ac_201_5_the_systems_root_gains_the_finalizer_after_its_namespace_and_changes_nothing_else(tmp_path):  # AC-201.5
    got = yaml.safe_load(split(tmp_path / "a")["bootstrap/shop-root.yaml"])
    want = yaml.safe_load(plain(tmp_path / "b")["bootstrap/shop-root.yaml"])
    assert list(got["metadata"]) == ["name", "namespace", "finalizers"] and got["metadata"]["finalizers"] == FIN
    got["metadata"].pop("finalizers")
    assert got == want


def test_ac_201_3_every_other_rendered_file_is_the_same_in_split_form(tmp_path):  # AC-201.3
    a, b = split(tmp_path / "a"), plain(tmp_path / "b")
    extra = {k for k in a if k not in b}
    assert extra == {f"{APP}/applicationset-{e}.yaml" for e in ENVS} | {f"bootstrap/environments/shop-{e}.yaml" for e in ENVS}
    assert {k: v for k, v in a.items() if k in b and k != "bootstrap/shop-root.yaml"} == {k: v for k, v in b.items() if k != "bootstrap/shop-root.yaml"}


# ---------------- AC-201.4: a system without cluster keys renders as before ----------------

def test_ac_201_4_a_system_without_cluster_keys_renders_no_split_file_and_no_finalizer(tmp_path):  # AC-201.4
    files = plain(tmp_path)
    assert not [k for k in files if "environments/" in k or "applicationset-" in k]
    assert "finalizers" not in files["bootstrap/shop-root.yaml"]
    assert all("preserveResourcesOnDeletion" not in t for t in files.values())


def test_ac_201_4_a_second_render_changes_nothing(tmp_path):  # AC-201.4
    first = split(tmp_path)
    assert render5(tmp_path, shop()).returncode == 0
    assert generated(tmp_path) == first


# ---------------- the three error lines ----------------

def render_error(tmp_path, doc, *, answers: str | None = None) -> str:
    if answers:
        (tmp_path / ".copier-answers.yml").write_text(answers)
    p = render5(tmp_path, doc)
    assert p.returncode == 1, f"expected a failed render, got {p.returncode}: {p.stdout}{p.stderr}"
    assert generated(tmp_path) == {}, "a failed render must not write files"
    return p.stderr


@pytest.mark.parametrize("value", ["Bad_1", "x" * 41, 3, ""])
def test_ac_201_3_a_cluster_name_that_is_not_a_dns_label_fails(tmp_path, value):  # AC-201.3
    doc = shop({"dev": value, "staging": "local", "prod": "home"})
    assert f"environments.dev.cluster: '{value}' must be a lowercase DNS label of at most 40 characters" in render_error(tmp_path, doc)


@pytest.mark.parametrize("keys, missing, other", [
    ({"dev": "local"}, "staging", "dev"),
    ({"prod": "home"}, "dev", "prod"),
    ({"dev": "local", "staging": "local"}, "prod", "dev"),
])
def test_ac_201_3_once_one_environment_sets_a_cluster_all_three_must(tmp_path, keys, missing, other):  # AC-201.3
    err = render_error(tmp_path, shop(keys))
    assert f"environments.{missing}.cluster is required once another environment sets one (environments.{other}.cluster: {keys[other]})" in err


def test_ac_201_3_a_split_system_needs_the_in_cluster_destination(tmp_path):  # AC-201.3
    err = render_error(tmp_path, shop(), answers="cluster_server: https://10.0.0.5:6443\n")
    assert "environments.dev.cluster needs cluster_server https://kubernetes.default.svc (each cluster's own Argo CD deploys in-cluster), not https://10.0.0.5:6443" in err


def test_ac_201_4_a_system_without_cluster_keys_may_keep_another_destination(tmp_path):  # AC-201.4
    (tmp_path / ".copier-answers.yml").write_text("cluster_server: https://10.0.0.5:6443\n")
    p = render5(tmp_path, shop(None))
    assert p.returncode == 0, p.stderr
    assert "https://10.0.0.5:6443" in generated(tmp_path)["bootstrap/shop-root.yaml"]


# ---------------- model ----------------

def test_ac_201_9_the_model_carries_the_cluster_of_each_environment(tmp_path):  # AC-201.9
    import model
    d = write_system(tmp_path, shop())
    envs = {e.name: e.cluster for e in model.load_dir(d).environments}
    assert envs == SPLIT_KEYS


def test_ac_201_9_an_environment_without_a_cluster_key_has_none(tmp_path):  # AC-201.9
    import model
    d = write_system(tmp_path, shop(None))
    assert {e.name: e.cluster for e in model.load_dir(d).environments} == {"dev": None, "staging": None, "prod": None}


def test_ac_201_3_the_cluster_template_copy_is_the_same_renderer():  # AC-201.3
    a = (ROOT / "templates" / "gitops-app" / "scripts" / "render.py").read_bytes()
    assert (ROOT / "templates" / "cluster-gitops" / "scripts" / "system_render.py").read_bytes() == a
    assert b"preserveResourcesOnDeletion" in a and b"resources-finalizer.argocd.argoproj.io" in a
    p = subprocess.run([sys.executable, "scripts/sync-template-copies.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
