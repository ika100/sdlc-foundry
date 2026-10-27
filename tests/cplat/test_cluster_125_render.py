"""Spec 125 acceptance tests, the renderer: the versions table and builder (AC-125.3), `cluster.yaml` validation (AC-125.2), the operator
applications (AC-125.3), the secret store (AC-125.4), the system applications (AC-125.5), the layout (AC-125.6) and the takeover names
(AC-125.14, renderer side).

Contract: design.md section 1 (versions table), 2 (cluster.yaml and its exact error lines), 3 (rendered layout). The cluster repo is a
shared Copier render of templates/cluster-gitops (cluster_fixtures)."""
import pytest
import yaml

from cluster_fixtures import (NAME, ORG, SERVER, base, cluster_repo, docs, platform_module, render, render_fails, render_ok, rendered,
                              write_cluster)
from resources_fixtures import comp, db, system
from system_fixtures import render5

ALLOWED_TOP = "cluster, owner, server, org, operators, secretStore, systems"


@pytest.fixture()
def repo(shared_renders, tmp_path):
    return cluster_repo(shared_renders, tmp_path)


def allowed_operators() -> str:
    ops = getattr(platform_module("render_125_names"), "OPERATORS")
    return ", ".join(sorted(ops))


# ---------------- AC-125.3: the versions table and the builder ----------------

def test_ac_125_3_table_pins_external_secrets_and_kyverno():  # AC-125.3
    ops = platform_module().OPERATORS
    keys = {"repo_url", "chart", "chart_version", "operator_version", "namespace", "release", "crd"}
    es, ky = ops["external-secrets"], ops["kyverno"]
    assert keys <= set(es) and keys <= set(ky)
    assert (es["chart_version"], es["operator_version"], es["namespace"], es["release"]) == ("2.12.0", "2.12.0", "external-secrets", "external-secrets")
    assert es["repo_url"] == "https://charts.external-secrets.io" and es["crd"] == "clustersecretstores.external-secrets.io"
    assert (ky["chart_version"], ky["namespace"], ky["release"]) == ("3.9.1", "kyverno", "kyverno")
    assert ky["repo_url"] == "https://kyverno.github.io/kyverno" and ky["crd"] == "namespacedvalidatingpolicies.policies.kyverno.io"
    assert ky["selector"] == "app.kubernetes.io/component=admission-controller,app.kubernetes.io/instance=kyverno"
    import re
    assert re.fullmatch(r"\d+\.\d+\.\d+", ky["operator_version"]), "the appVersion without a leading v"


def test_ac_125_3_the_operator_application_builder_equals_the_system_rendered_one(tmp_path):  # AC-125.3
    mod = platform_module()
    assert hasattr(mod, "operator_application"), "render.py has operator_application(name, server)"
    doc = system({"db": db()}, {"api": comp("api", ["db"])})
    p = render5(tmp_path, doc)
    assert p.returncode == 0, p.stderr
    sysdoc = yaml.safe_load((tmp_path / "operators" / "apps" / "cloudnative-pg.yaml").read_text())
    assert mod.operator_application("cloudnative-pg", SERVER) == sysdoc
    assert "finalizers" not in sysdoc["metadata"]
    assert sysdoc["metadata"]["name"] == "operator-cloudnative-pg"


def test_ac_125_3_external_secrets_and_kyverno_never_appear_in_a_system_operators_folder(tmp_path):  # AC-125.3
    assert "external-secrets" in platform_module().OPERATORS      # the rows exist ...
    doc = system({"db": db()}, {"api": comp("api", ["db"], secrets=[{"name": "api-auth", "generate": ["JWT_KEY"]}])})
    doc["environments"]["dev"]["policy"] = "audit"
    assert render5(tmp_path, doc).returncode == 0
    assert sorted(p.name for p in (tmp_path / "operators" / "apps").glob("*.yaml")) == ["cloudnative-pg.yaml"]     # ... but a system renders only its resource types' operators


def test_ac_125_3_each_listed_operator_is_one_pinned_application(repo):  # AC-125.3
    mod = platform_module()
    names = ["cloudnative-pg", "external-secrets", "kyverno"]
    out = render_ok(repo, base(operators=names))
    for n in names:
        app = yaml.safe_load(out[f"cluster/operators/{n}.yaml"])
        assert app == mod.operator_application(n, SERVER)
        assert app["metadata"]["name"] == f"operator-{n}" and app["metadata"]["namespace"] == "argocd"
        assert app["spec"]["source"]["targetRevision"] == mod.OPERATORS[n]["chart_version"]
        assert "finalizers" not in app["metadata"]


def test_ac_125_3_an_unlisted_operator_gets_no_application(repo):  # AC-125.3
    out = render_ok(repo, base(operators=["cloudnative-pg"]))
    assert sorted(k for k in out if k.startswith("cluster/operators/")) == ["cluster/operators/cloudnative-pg.yaml"]


def test_ac_125_3_an_operator_application_follows_the_server(repo):  # AC-125.3
    out = render_ok(repo, base(server="https://10.0.0.1:6443", operators=["cloudnative-pg"]))
    assert yaml.safe_load(out["cluster/operators/cloudnative-pg.yaml"])["spec"]["destination"]["server"] == "https://10.0.0.1:6443"
    assert yaml.safe_load(out["cluster/operators-root.yaml"])["spec"]["destination"]["server"] == "https://10.0.0.1:6443"


def test_ac_125_3_an_unknown_operator_fails_listing_the_allowed_names(repo):  # AC-125.3
    render_fails(repo, base(operators=["postgres"]), f"operators: 'postgres' is not an operator (allowed: {allowed_operators()})")


def test_ac_125_3_the_allowed_names_include_the_two_new_operators(repo):  # AC-125.3
    p = render(repo, base(operators=["nope"]))
    assert "external-secrets" in p.stderr and "kyverno" in p.stderr and "cloudnative-pg" in p.stderr and "seaweedfs" in p.stderr


def test_ac_125_3_a_duplicate_operator_fails(repo):  # AC-125.3
    render_fails(repo, base(operators=["kyverno", "kyverno"]), "operators: 'kyverno' is listed twice")


def test_ac_125_3_operators_must_be_a_list_of_names(repo):  # AC-125.3
    render_fails(repo, base(operators="cloudnative-pg"), "operators must be a list of operator names")


# ---------------- AC-125.2: cluster.yaml ----------------

def test_ac_125_2_an_unknown_key_fails_naming_it(repo):  # AC-125.2
    render_fails(repo, base(bogus=1), f"unknown key 'bogus' (allowed: {ALLOWED_TOP})")


@pytest.mark.parametrize("doc,message", [
    ({"owner": ORG}, "cluster is required"),
    ({"cluster": NAME}, "owner is required: a non-empty string"),
    ({"cluster": NAME, "owner": ""}, "owner is required: a non-empty string"),
    ({"cluster": NAME, "owner": 7}, "owner is required: a non-empty string"),
    ({"cluster": "Home_1", "owner": ORG}, "cluster: 'Home_1' must be a lowercase DNS label of at most 40 characters"),
    ({"cluster": "x" * 41, "owner": ORG}, f"cluster: '{'x' * 41}' must be a lowercase DNS label of at most 40 characters"),
    (base(server="not a url"), "server must be an http(s) URL"),
    (base(server=3), "server must be an http(s) URL"),
    (base(org=3), "org must be a GitHub owner name"),
])
def test_ac_125_2_a_missing_required_key_or_a_wrong_type_fails_with_one_line(repo, doc, message):  # AC-125.2
    render_fails(repo, doc, message)


def test_ac_125_2_a_file_that_is_not_a_mapping_fails(repo):  # AC-125.2
    render_fails(repo, "- a\n- b\n", "must be a mapping with cluster and owner")
    p = render(repo, "a: [unclosed\n")
    assert p.returncode == 1 and p.stderr.startswith("ERROR: cluster.yaml: is not valid YAML (") and len(p.stderr.strip().splitlines()) == 1


def test_ac_125_2_the_org_must_be_the_owner_of_the_repo(repo):  # AC-125.2
    p = render(repo, base(org="elsewhere"))
    assert p.returncode == 1
    assert p.stderr.startswith(f"ERROR: cluster.yaml: org: must be {ORG}, the owner of this repo (Argo CD reads this repo and every system with one credential for https://github.com/{ORG})")


def test_ac_125_2_the_server_defaults_to_the_in_cluster_api(repo):  # AC-125.2
    out = render_ok(repo, base(operators=["cloudnative-pg"], systems={"todo": {"repo": f"{ORG}/todo-gitops"}}))
    for f in ("cluster/operators/cloudnative-pg.yaml", "cluster/systems/todo.yaml", "cluster/operators-root.yaml", "cluster/systems-root.yaml"):
        assert yaml.safe_load(out[f])["spec"]["destination"]["server"] == SERVER


def test_ac_125_2_render_with_an_unchanged_cluster_yaml_changes_no_file(repo):  # AC-125.2
    doc = base(operators=["cloudnative-pg", "external-secrets"], systems={"todo": {"repo": f"{ORG}/todo-gitops"}})
    first = render_ok(repo, doc)
    p = render(repo, doc)
    assert p.returncode == 0 and "rendered (0 file(s) changed)" in p.stdout, p.stdout + p.stderr
    assert rendered(repo) == first


def test_ac_125_2_render_reports_the_files_it_changed_and_check_reports_drift(repo):  # AC-125.2
    write_cluster(repo, base(operators=["cloudnative-pg"]))
    p = render(repo)
    assert p.returncode == 0 and "file(s) changed)" in p.stdout and "rendered (0 file(s) changed)" not in p.stdout
    ok = render(repo, None, "--check")
    assert ok.returncode == 0 and ok.stdout.strip() == "OK: up to date"
    (repo / "cluster" / "operators" / "cloudnative-pg.yaml").write_text("tampered: true\n")
    bad = render(repo, None, "--check")
    assert bad.returncode == 1
    assert "ERROR: rendered files are out of date — run `devbox run render`:" in bad.stderr + bad.stdout
    assert "  cluster/operators/cloudnative-pg.yaml" in bad.stderr + bad.stdout


def test_ac_125_2_name_crds_and_systems_flags(repo):  # AC-125.2
    write_cluster(repo, base(operators=["cloudnative-pg", "external-secrets"], systems={"todo": {"repo": f"{ORG}/todo-gitops"}, "ai-ops": {"repo": f"{ORG}/ai"}}))
    assert render(repo, None, "--name").stdout.strip() == NAME
    ops = platform_module().OPERATORS
    assert render(repo, None, "--crds").stdout.splitlines() == [f"cloudnative-pg {ops['cloudnative-pg']['crd']}", f"external-secrets {ops['external-secrets']['crd']}"]
    assert render(repo, None, "--systems").stdout.splitlines() == [f"todo {ORG}/todo-gitops", f"ai-ops {ORG}/ai"]


# ---------------- AC-125.4: the secret store ----------------

def test_ac_125_4_external_secrets_renders_the_default_store_with_its_supporting_objects(repo):  # AC-125.4
    out = render_ok(repo, base(operators=["external-secrets"]))
    ds = docs(out["cluster/operators/secret-store.yaml"])
    assert [d["kind"] for d in ds] == ["Namespace", "ServiceAccount", "Role", "RoleBinding", "ClusterSecretStore"]
    assert [d["metadata"]["name"] for d in ds] == ["secrets-store", "eso-store", "eso-store", "eso-store", "platform-secrets"]
    store = ds[-1]
    assert store["apiVersion"] == "external-secrets.io/v1"
    assert store["metadata"]["annotations"] == {"argocd.argoproj.io/sync-wave": "1", "argocd.argoproj.io/sync-options": "SkipDryRunOnMissingResource=true"}
    assert store["spec"]["provider"] == {"kubernetes": {"remoteNamespace": "secrets-store",
                                                         "server": {"caProvider": {"type": "ConfigMap", "name": "kube-root-ca.crt", "namespace": "secrets-store", "key": "ca.crt"}},
                                                         "auth": {"serviceAccount": {"name": "eso-store", "namespace": "secrets-store"}}}}
    rules = ds[2]["rules"]
    assert any("secrets" in r["resources"] and {"get", "list", "watch"} <= set(r["verbs"]) for r in rules)
    assert any("selfsubjectrulesreviews" in r["resources"] and "create" in r["verbs"] for r in rules)


def test_ac_125_4_a_named_store_with_a_custom_provider_renders_only_the_store(repo):  # AC-125.4
    prov = {"vault": {"server": "https://vault.example.com", "path": "secret", "version": "v2"}}
    out = render_ok(repo, base(operators=["external-secrets"], secretStore={"name": "vault-store", "provider": prov}))
    ds = docs(out["cluster/operators/secret-store.yaml"])
    assert [d["kind"] for d in ds] == ["ClusterSecretStore"]
    assert ds[0]["metadata"]["name"] == "vault-store" and ds[0]["spec"]["provider"] == prov


def test_ac_125_4_no_store_without_external_secrets(repo):  # AC-125.4
    out = render_ok(repo, base(operators=["cloudnative-pg"]))
    assert "cluster/operators/secret-store.yaml" not in out


def test_ac_125_4_a_store_without_external_secrets_fails_naming_both_keys(repo):  # AC-125.4
    render_fails(repo, base(operators=["cloudnative-pg"], secretStore={"name": "x"}), "secretStore needs external-secrets in operators")


@pytest.mark.parametrize("store,message", [
    ("platform-secrets", "secretStore must be a mapping with name and provider"),
    ({"nme": "x"}, "secretStore: unknown key 'nme' (allowed: name, provider)"),
    ({"name": "Bad_Name"}, "secretStore.name: 'Bad_Name' must be a lowercase DNS name"),
    ({"provider": {"a": {}, "b": {}}}, "secretStore.provider must be a mapping with exactly one provider, e.g. {vault: {...}}"),
    ({"provider": "vault"}, "secretStore.provider must be a mapping with exactly one provider, e.g. {vault: {...}}"),
])
def test_ac_125_4_a_bad_secret_store_fails_with_one_line(repo, store, message):  # AC-125.4
    render_fails(repo, base(operators=["external-secrets"], secretStore=store), message)


# ---------------- AC-125.5: the systems ----------------

def test_ac_125_5_each_system_gets_one_application_syncing_bootstrap(repo):  # AC-125.5
    out = render_ok(repo, base(systems={"todo": {"repo": f"{ORG}/todo-gitops"}, "ai-ops": {"repo": f"{ORG}/ai-ops-gitops"}}))
    assert sorted(k for k in out if k.startswith("cluster/systems/")) == ["cluster/systems/ai-ops.yaml", "cluster/systems/todo.yaml"]
    assert yaml.safe_load(out["cluster/systems/todo.yaml"]) == {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": "system-todo", "namespace": "argocd",
                     "labels": {"app.kubernetes.io/managed-by": "cluster-gitops", "app.kubernetes.io/component": "system"}},
        "spec": {"project": "default",
                 "source": {"repoURL": f"https://github.com/{ORG}/todo-gitops", "targetRevision": "main", "path": "bootstrap"},
                 "destination": {"server": SERVER, "namespace": "argocd"},
                 "syncPolicy": {"automated": {"prune": True, "selfHeal": True}}}}


def test_ac_125_5_no_application_has_a_resources_finalizer(repo):  # AC-125.5
    out = render_ok(repo, base(operators=["cloudnative-pg", "external-secrets", "kyverno"], systems={"todo": {"repo": f"{ORG}/todo-gitops"}}))
    for path, text in out.items():
        for d in docs(text) if path.endswith(".yaml") and "kustomization" not in path else []:
            assert "finalizers" not in (d.get("metadata") or {}), path


@pytest.mark.parametrize("systems,message", [
    ({"Todo_X": {"repo": f"{ORG}/x"}}, "systems.Todo_X: the name must be a lowercase DNS label"),
    ({"todo": {"repo": f"{ORG}/x"}, "ai": {"repo": f"{ORG}/x"}}, f"systems.ai: repo '{ORG}/x' is already registered as systems.todo"),
    ({"todo": {"repo": "other/x"}}, f"systems.todo: repo 'other/x' is outside org '{ORG}' (Argo CD reads only https://github.com/{ORG})"),
    ({"todo": {"repo": "justaname"}}, "systems.todo: repo 'justaname' must be <owner>/<name>"),
    ({"todo": {}}, "systems.todo: repo is required (<owner>/<name>)"),
    ({"todo": {"repo": f"{ORG}/x", "branch": "dev"}}, "systems.todo: unknown key 'branch' (allowed: repo)"),
    ({"todo": f"{ORG}/x"}, "systems.todo must be {repo: <owner>/<name>}"),
    (["todo"], "systems must be a mapping of system names to {repo: <owner>/<name>}"),
])
def test_ac_125_5_a_bad_system_entry_fails_naming_it(repo, systems, message):  # AC-125.5
    render_fails(repo, base(systems=systems), message)


def test_ac_125_5_systems_null_is_no_systems(repo):  # AC-125.5
    out = render_ok(repo, "cluster: home\nowner: acme\nsystems:\n")
    assert "cluster/systems/.gitkeep" in out


# ---------------- AC-125.6: the layout ----------------

def test_ac_125_6_the_layout_of_operators_systems_and_their_roots(repo):  # AC-125.6
    out = render_ok(repo, base(operators=["cloudnative-pg", "external-secrets"], systems={"todo": {"repo": f"{ORG}/todo-gitops"}}))
    assert sorted(out) == ["cluster/kustomization.yaml", "cluster/operators-root.yaml", "cluster/operators/cloudnative-pg.yaml",
                           "cluster/operators/external-secrets.yaml", "cluster/operators/secret-store.yaml", "cluster/systems-root.yaml",
                           "cluster/systems/todo.yaml"]
    url = f"https://github.com/{ORG}/{NAME}"
    assert yaml.safe_load(out["cluster/operators-root.yaml"]) == {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": "platform-operators", "namespace": "argocd"},
        "spec": {"project": "default", "source": {"repoURL": url, "targetRevision": "main", "path": "cluster/operators"},
                 "destination": {"server": SERVER, "namespace": "argocd"},
                 "syncPolicy": {"automated": {"prune": True, "selfHeal": True},
                                "retry": {"limit": 10, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "5m"}}}}}
    assert yaml.safe_load(out["cluster/systems-root.yaml"]) == {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": "platform-systems", "namespace": "argocd"},
        "spec": {"project": "default", "source": {"repoURL": url, "targetRevision": "main", "path": "cluster/systems"},
                 "destination": {"server": SERVER, "namespace": "argocd"}, "syncPolicy": {"automated": {"prune": True, "selfHeal": True}}}}
    assert yaml.safe_load(out["cluster/kustomization.yaml"]) == {
        "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
        "resources": ["operators-root.yaml", "systems-root.yaml", "operators/cloudnative-pg.yaml", "operators/external-secrets.yaml",
                      "operators/secret-store.yaml", "systems/todo.yaml"]}


def test_ac_125_6_a_cluster_without_systems_or_operators_still_renders_both_roots(repo):  # AC-125.6
    out = render_ok(repo, base())
    assert sorted(out) == ["cluster/kustomization.yaml", "cluster/operators-root.yaml", "cluster/operators/.gitkeep",
                           "cluster/systems-root.yaml", "cluster/systems/.gitkeep"]
    assert out["cluster/operators/.gitkeep"] == "" and out["cluster/systems/.gitkeep"] == ""


def test_ac_125_6_a_gitkeep_exists_only_in_an_empty_folder(repo):  # AC-125.6
    out = render_ok(repo, base(operators=["kyverno"]))
    assert "cluster/operators/.gitkeep" not in out and "cluster/systems/.gitkeep" in out
    out = render_ok(repo, base(systems={"todo": {"repo": f"{ORG}/t"}}))
    assert "cluster/systems/.gitkeep" not in out and "cluster/operators/.gitkeep" in out


def test_ac_125_6_a_file_the_render_does_not_own_is_stale(repo):  # AC-125.6
    render_ok(repo, base(operators=["kyverno"]))
    stray = repo / "cluster" / "operators" / "old.yaml"
    stray.write_text("kind: ConfigMap\n")
    check = render(repo, None, "--check")
    assert check.returncode == 1 and "cluster/operators/old.yaml (stale)" in check.stderr + check.stdout
    assert render(repo).returncode == 0 and not stray.exists()


def test_ac_125_6_the_operators_follow_the_order_of_cluster_yaml(repo):  # AC-125.6
    out = render_ok(repo, base(operators=["kyverno", "cloudnative-pg"]))
    assert yaml.safe_load(out["cluster/kustomization.yaml"])["resources"][2:] == ["operators/kyverno.yaml", "operators/cloudnative-pg.yaml"]


# ---------------- AC-125.14: takeover keeps the names (renderer side) ----------------

def test_ac_125_14_the_roots_and_operator_applications_have_the_names_a_system_installed_them_under(repo, tmp_path):  # AC-125.14
    sysdir = tmp_path / "system"
    sysdir.mkdir()
    doc = system({"db": db()}, {"api": comp("api", ["db"])})
    assert render5(sysdir, doc).returncode == 0
    system_root = yaml.safe_load((sysdir / "operators" / "root.yaml").read_text())
    system_app = yaml.safe_load((sysdir / "operators" / "apps" / "cloudnative-pg.yaml").read_text())
    out = render_ok(repo, base(operators=["cloudnative-pg"]))
    cluster_root = yaml.safe_load(out["cluster/operators-root.yaml"])
    assert cluster_root["metadata"] == system_root["metadata"] == {"name": "platform-operators", "namespace": "argocd"}
    assert yaml.safe_load(out["cluster/operators/cloudnative-pg.yaml"]) == system_app
