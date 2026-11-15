"""Spec 201 acceptance tests, the cluster renderer: several clusters in one repo (AC-201.1), per-cluster exceptions (AC-201.2),
system placement (AC-201.3), a repo without `clusters` unchanged (AC-201.4), moved environments (AC-201.5) and a later cluster kept
at its release (AC-201.7, renderer side).

Contract: design.md sections 2 and 3. The cluster repo is a shared Copier render of templates/cluster-gitops (cluster_fixtures);
`scripts/render.py` runs as a script, like `devbox run render`."""
import json
import re

import pytest
import yaml

from cluster_fixtures import ORG, base, cluster_repo, platform_module, render, render_ok, rendered, script
from support_201 import (KEPT, HOME, LOCAL, NO_FINALIZER, SERVER, TODO_REPO, UNKNOWN_KEYS, docs_of, fails, load, multi, render_clusters,
                         pin_release, run_render, setup, stdout_lines, system_app, todo, tree)

OPS = ["cloudnative-pg", "external-secrets"]
SHARED_STORE = {"name": "shared-store", "provider": {"fake": {"data": []}}}
VAULT = {"name": "vault-secrets", "provider": {"vault": {"server": "https://vault.example", "path": "secret"}}}


@pytest.fixture()
def repo(shared_renders, tmp_path):
    return cluster_repo(shared_renders, tmp_path)


def relative(files: dict[str, str], cluster: str) -> dict[str, str]:
    return {k.removeprefix(f"cluster/{cluster}/"): v for k, v in files.items()}


def allowed_operators() -> str:
    return ", ".join(sorted(platform_module("render_201_names").OPERATORS))


# ---------------- AC-201.1: one tree per listed cluster ----------------

def test_ac_201_1_each_listed_cluster_gets_its_own_tree_with_the_layout_of_a_single_cluster(repo):  # AC-201.1
    render_clusters(repo, multi(operators=OPS))
    files = rendered(repo)
    for c in (LOCAL, HOME):
        want = {f"cluster/{c}/{n}" for n in ("operators-root.yaml", "systems-root.yaml", "kustomization.yaml", "operators/cloudnative-pg.yaml",
                                              "operators/external-secrets.yaml", "operators/secret-store.yaml", "systems/.gitkeep")}
        assert {k for k in files if k.startswith(f"cluster/{c}/")} == want
    assert not [k for k in files if not k.startswith((f"cluster/{LOCAL}/", f"cluster/{HOME}/"))], "no tree outside the cluster directories"


def test_ac_201_1_each_cluster_root_points_at_its_own_tree(repo):  # AC-201.1
    render_clusters(repo, multi(operators=OPS, systems=todo()))
    for c in (LOCAL, HOME):
        ops, systems = load(repo, f"cluster/{c}/operators-root.yaml"), load(repo, f"cluster/{c}/systems-root.yaml")
        assert (ops["metadata"]["name"], ops["spec"]["source"]["path"]) == ("platform-operators", f"cluster/{c}/operators")
        assert (systems["metadata"]["name"], systems["spec"]["source"]["path"]) == ("platform-systems", f"cluster/{c}/systems")
        kust = load(repo, f"cluster/{c}/kustomization.yaml")
        assert "operators-root.yaml" in kust["resources"] and "systems-root.yaml" in kust["resources"]
        assert all(not r.startswith("cluster/") for r in kust["resources"]), "the manifests are relative to the tree"


def test_ac_201_1_operators_and_the_secret_store_appear_the_same_in_each_tree(repo):  # AC-201.1
    render_clusters(repo, multi(operators=OPS, secretStore=SHARED_STORE))
    files = rendered(repo)
    a, b = relative(tree_of(files, LOCAL), LOCAL), relative(tree_of(files, HOME), HOME)
    for name in ("operators/cloudnative-pg.yaml", "operators/external-secrets.yaml", "operators/secret-store.yaml", "operators-root.yaml"):
        assert a[name] == b[name], name
    store = docs_of(a["operators/secret-store.yaml"])[-1]
    assert store["kind"] == "ClusterSecretStore" and store["metadata"]["name"] == "shared-store"


def tree_of(files: dict[str, str], c: str) -> dict[str, str]:
    return {k: v for k, v in files.items() if k.startswith(f"cluster/{c}/")}


def test_ac_201_1_a_second_render_changes_no_file(repo):  # AC-201.1
    render_clusters(repo, multi(operators=OPS, systems=todo()))
    before = rendered(repo)
    p = render(repo, None)
    assert p.returncode == 0 and stdout_lines(p)[-1] == "rendered (0 file(s) changed)", p.stdout + p.stderr
    assert rendered(repo) == before
    check = script(repo, "render.py", "--check")
    assert check.returncode == 0 and check.stdout.strip() == "OK: up to date", check.stdout + check.stderr


def test_ac_201_1_check_reports_a_stale_file_in_a_cluster_tree(repo):  # AC-201.1
    render_clusters(repo, multi(operators=OPS))
    (repo / "cluster" / HOME / "operators" / "stray.yaml").write_text("kind: ConfigMap\n")
    p = script(repo, "render.py", "--check")
    assert p.returncode == 1 and "cluster/home/operators/stray.yaml" in p.stdout + p.stderr


def test_ac_201_1_a_cluster_directory_may_hold_only_comments_or_nothing(repo):  # AC-201.1
    render_clusters(repo, multi(), {LOCAL: "# no exceptions\n", HOME: None})
    assert tree(repo, LOCAL) and tree(repo, HOME)


@pytest.mark.parametrize("override, message", [
    ({"bogus": 1}, f"unknown key 'bogus' (allowed: {UNKNOWN_KEYS})"),
    ({"clusters": "local"}, "clusters must be a list of cluster names"),
    ({"clusters": [LOCAL, 3]}, "clusters must be a list of cluster names"),
    ({"clusters": []}, "clusters must list at least one cluster, or be left out"),
    ({"clusters": ["Bad_Name", HOME]}, "clusters: 'Bad_Name' must be a lowercase DNS label of at most 40 characters"),
    ({"clusters": [LOCAL, "x" * 41]}, f"clusters: '{'x' * 41}' must be a lowercase DNS label of at most 40 characters"),
    ({"clusters": [LOCAL, LOCAL]}, "clusters: 'local' is listed twice"),
    ({"server": 3}, "server must be an http(s) URL"),
    ({"owner": ""}, "owner is required: a non-empty string"),
])
def test_ac_201_1_a_bad_cluster_yaml_fails_with_one_line_naming_it(repo, override, message):  # AC-201.1
    doc = {**multi(), **override}
    fails(repo, doc, message)


def test_ac_201_1_a_missing_required_key_fails(repo):  # AC-201.1
    doc = multi()
    del doc["cluster"]
    fails(repo, doc, "cluster is required")


def test_ac_201_1_a_listed_cluster_without_its_directory_fails(repo):  # AC-201.1
    fails(repo, multi(), "clusters: 'home' has no clusters/home/cluster.yaml (create it; empty when the cluster has no exceptions)", listed=[LOCAL])


def test_ac_201_1_a_cluster_directory_that_is_not_listed_fails(repo):  # AC-201.1
    setup(repo, multi())
    (repo / "clusters" / "edge").mkdir()
    (repo / "clusters" / "edge" / "cluster.yaml").write_text("")
    before = rendered(repo)
    p = render(repo, None)
    assert p.returncode == 1 and rendered(repo) == before
    lines = p.stderr.strip().splitlines()
    assert len(lines) == 1 and re.fullmatch(r"ERROR: \S+: clusters/edge/ belongs to no cluster in clusters \(listed: local, home\)", lines[0]), p.stderr


def test_ac_201_1_a_cluster_directory_in_a_repo_without_clusters_fails(repo):  # AC-201.1
    (repo / "clusters" / "edge").mkdir(parents=True)
    (repo / "clusters" / "edge" / "cluster.yaml").write_text("")
    before = rendered(repo)
    p = render(repo, base())
    assert p.returncode == 1 and rendered(repo) == before
    lines = p.stderr.strip().splitlines()
    assert len(lines) == 1 and re.fullmatch(r"ERROR: \S+: clusters/edge/ belongs to no cluster in clusters \(listed: none\)", lines[0]), p.stderr


def test_ac_201_1_the_template_documents_clusters_and_changes_no_default_render(repo):  # AC-201.1
    text = (repo / "cluster.yaml").read_text()
    assert "clusters" in text and "environments" in text, "cluster.yaml documents clusters and systems.<s>.environments"
    assert "clusters" not in (yaml.safe_load(text) or {}), "in comments only: the default render is unchanged"


# ---------------- AC-201.2: exceptions ----------------

def exception_run(repo, exceptions, **more):
    return run_render(repo, multi(operators=["cloudnative-pg", "external-secrets"], **more), exceptions)


def test_ac_201_2_an_operator_exception_changes_only_that_clusters_tree_and_prints_one_line(repo):  # AC-201.2
    render_clusters(repo, multi(operators=OPS))
    before = rendered(repo)
    p = exception_run(repo, {HOME: {"operators": {"kyverno": True}}})
    assert p.returncode == 0, p.stderr
    after = rendered(repo)
    assert tree_of(after, LOCAL) == tree_of(before, LOCAL), "the other cluster's tree is untouched"
    assert "cluster/home/operators/kyverno.yaml" in after and "cluster/local/operators/kyverno.yaml" not in after
    assert "EXCEPTION: cluster home: operator kyverno: installed (shared: not installed)" in stdout_lines(p)


def test_ac_201_2_an_operator_left_out_on_one_cluster_is_gone_from_its_tree_only(repo):  # AC-201.2
    p = exception_run(repo, {HOME: {"operators": {"cloudnative-pg": False}}})
    assert p.returncode == 0, p.stderr
    files = rendered(repo)
    assert "cluster/local/operators/cloudnative-pg.yaml" in files and "cluster/home/operators/cloudnative-pg.yaml" not in files
    assert "EXCEPTION: cluster home: operator cloudnative-pg: not installed (shared: installed)" in stdout_lines(p)


def test_ac_201_2_a_server_exception_moves_that_clusters_applications(repo):  # AC-201.2
    p = exception_run(repo, {HOME: {"server": "https://10.0.0.5:6443"}})
    assert p.returncode == 0, p.stderr
    assert f"EXCEPTION: cluster home: server: https://10.0.0.5:6443 (shared: {SERVER})" in stdout_lines(p)
    home, local = load(repo, "cluster/home/operators/cloudnative-pg.yaml"), load(repo, "cluster/local/operators/cloudnative-pg.yaml")
    assert home["spec"]["destination"]["server"] == "https://10.0.0.5:6443" and local["spec"]["destination"]["server"] == SERVER


def test_ac_201_2_a_secret_store_exception_changes_only_that_stores_file(repo):  # AC-201.2
    render_clusters(repo, multi(operators=OPS, secretStore=SHARED_STORE))
    before = rendered(repo)
    p = run_render(repo, multi(operators=OPS, secretStore=SHARED_STORE), {HOME: {"secretStore": VAULT}})
    assert p.returncode == 0, p.stderr
    after = rendered(repo)
    assert tree_of(after, LOCAL) == tree_of(before, LOCAL)
    changed = {k for k in after if after[k] != before.get(k)}
    assert changed == {"cluster/home/operators/secret-store.yaml"}
    assert docs_of(after["cluster/home/operators/secret-store.yaml"])[-1]["metadata"]["name"] == "vault-secrets"
    assert "EXCEPTION: cluster home: secretStore: name vault-secrets, provider vault (shared: name shared-store, provider fake)" in stdout_lines(p)


def test_ac_201_2_the_exception_lines_come_before_the_summary_and_repeat_when_nothing_changed(repo):  # AC-201.2
    exceptions = {HOME: {"operators": {"kyverno": True}}, LOCAL: {"server": "https://10.0.0.9:6443"}}
    first = exception_run(repo, exceptions)
    second = render(repo, None)
    for p in (first, second):
        lines = stdout_lines(p)
        marks = [i for i, ln in enumerate(lines) if ln.startswith("EXCEPTION: ")]
        assert len(marks) == 2 and lines[-1].startswith("rendered (") and max(marks) < len(lines) - 1
    assert stdout_lines(second)[-1] == "rendered (0 file(s) changed)"
    assert [ln for ln in stdout_lines(first) if ln.startswith("EXCEPTION: ")][0].startswith("EXCEPTION: cluster local: "), "clusters in list order"


def test_ac_201_2_no_exception_prints_no_exception_line(repo):  # AC-201.2
    p = exception_run(repo, None)
    assert p.returncode == 0 and not [ln for ln in stdout_lines(p) if ln.startswith("EXCEPTION")]


@pytest.mark.parametrize("exception, message", [
    ({"systems": {}}, "'systems' is not a shared setting a cluster can override (allowed: operators, secretStore, server)"),
    ({"owner": "x"}, "'owner' is not a shared setting a cluster can override (allowed: operators, secretStore, server)"),
    ({"operators": ["kyverno"]}, "operators must map operator names to true or false"),
    ({"operators": {"kyverno": "yes"}}, "operators must map operator names to true or false"),
    ({"operators": {"cloudnative-pg": True}}, "operators.cloudnative-pg: true is the shared value (cluster.yaml operators); remove it"),
    ({"operators": {"kyverno": False}}, "operators.kyverno: false is the shared value (cluster.yaml operators); remove it"),
    ({"server": "not a url"}, "server must be an http(s) URL"),
])
def test_ac_201_2_a_bad_exception_fails_with_one_line_naming_the_file(repo, exception, message):  # AC-201.2
    fails(repo, multi(operators=["cloudnative-pg"]), message, file="clusters/home/cluster.yaml", exceptions={HOME: exception})


def test_ac_201_2_an_unknown_operator_in_an_exception_fails_listing_the_allowed_names(repo):  # AC-201.2
    fails(repo, multi(), f"operators.postgres: 'postgres' is not an operator (allowed: {allowed_operators()})",
          file="clusters/home/cluster.yaml", exceptions={HOME: {"operators": {"postgres": True}}})


def test_ac_201_2_a_secret_store_needs_external_secrets_on_that_cluster(repo):  # AC-201.2
    fails(repo, multi(operators=["cloudnative-pg"]), "secretStore needs external-secrets installed on cluster home",
          file="clusters/home/cluster.yaml", exceptions={HOME: {"secretStore": VAULT}})


def test_ac_201_2_an_exception_file_that_is_not_yaml_or_not_a_mapping_fails(repo):  # AC-201.2
    setup(repo, multi(), {HOME: "a: [unclosed\n"})
    p = render(repo, None)
    assert p.returncode == 1 and re.fullmatch(r"ERROR: clusters/home/cluster.yaml: is not valid YAML \(.*\)\n?", p.stderr)
    fails(repo, multi(), "must be a mapping of exceptions (operators, secretStore, server)", file="clusters/home/cluster.yaml",
          exceptions={HOME: "- a\n- b\n"})


# ---------------- AC-201.3: placement of a system ----------------

def system_apps(repo):
    return {c: system_app(repo, c) for c in (LOCAL, HOME)}


def test_ac_201_3_a_system_with_environments_gets_one_application_per_cluster_that_syncs_only_its_environments(repo):  # AC-201.3
    render_clusters(repo, multi(systems=todo()))
    apps = system_apps(repo)
    for c, pattern in ((LOCAL, "{*-dev.yaml,*-staging.yaml}"), (HOME, "*-prod.yaml")):
        app = apps[c]
        assert app["metadata"]["name"] == "system-todo" and app["metadata"]["namespace"] == "argocd"
        src = app["spec"]["source"]
        assert src["repoURL"] == f"https://github.com/{TODO_REPO}" and src["targetRevision"] == "main"
        assert src["path"] == "bootstrap/environments" and src["directory"] == {"include": pattern}
        assert app["spec"]["destination"] == {"server": SERVER, "namespace": "argocd"}
        assert app["spec"]["syncPolicy"]["automated"] == {"prune": True, "selfHeal": True, "allowEmpty": True}


def test_ac_201_3_no_rendered_document_has_a_resources_finalizer(repo):  # AC-201.3
    render_clusters(repo, multi(operators=OPS, systems=todo()))
    for path, text in rendered(repo).items():
        assert NO_FINALIZER not in text and "finalizers" not in text, path


def test_ac_201_3_a_cluster_that_runs_none_of_the_environments_still_gets_an_application_that_selects_nothing(repo):  # AC-201.3
    render_clusters(repo, multi(clusters=(LOCAL, HOME, "edge"), systems=todo()))
    app = system_app(repo, "edge")
    assert app["spec"]["source"]["path"] == "bootstrap/environments" and app["spec"]["source"]["directory"] == {"exclude": "*"}
    assert app["spec"]["syncPolicy"]["automated"]["allowEmpty"] is True


def test_ac_201_3_a_system_without_environments_runs_on_the_first_cluster_only(repo):  # AC-201.3
    render_clusters(repo, multi(systems=todo(None)))
    app = system_app(repo, LOCAL)
    assert app["spec"]["source"]["path"] == "bootstrap" and "directory" not in app["spec"]["source"]
    assert app["spec"]["source"]["repoURL"] == f"https://github.com/{TODO_REPO}" and app["spec"]["source"]["targetRevision"] == "main"
    assert not (repo / "cluster" / HOME / "systems" / "todo.yaml").exists()
    assert "finalizers" not in (repo / "cluster" / LOCAL / "systems" / "todo.yaml").read_text()


def test_ac_201_3_the_system_applications_are_listed_in_the_trees_kustomization(repo):  # AC-201.3
    render_clusters(repo, multi(systems=todo()))
    for c in (LOCAL, HOME):
        assert "systems/todo.yaml" in load(repo, f"cluster/{c}/kustomization.yaml")["resources"]


@pytest.mark.parametrize("systems, message", [
    ({"Bad_Name": {"repo": f"{ORG}/x"}}, "systems.Bad_Name: the name must be a lowercase DNS label"),
    ({"a": {"repo": TODO_REPO}, "b": {"repo": TODO_REPO}}, f"systems.b: repo '{TODO_REPO}' is already registered as systems.a"),
    ({"todo": {"repo": "other/todo-gitops"}}, "systems.todo: repo 'other/todo-gitops' is outside org 'acme' (Argo CD reads only https://github.com/acme)"),
    ({"todo": {"repo": TODO_REPO, "environments": {"qa": LOCAL}}}, "systems.todo.environments: 'qa' is not an environment (allowed: dev, staging, prod)"),
    ({"todo": {"repo": TODO_REPO, "environments": {"dev": "edge"}}}, "systems.todo.environments.dev: cluster 'edge' is not listed in clusters (listed: local, home)"),
    ({"todo": {"repo": TODO_REPO, "environments": [LOCAL]}}, "systems.todo.environments must map dev, staging and prod to listed clusters"),
    ({"todo": {"repo": TODO_REPO, "branch": "x"}}, "systems.todo: unknown key 'branch' (allowed: repo, environments)"),
])
def test_ac_201_3_a_bad_system_entry_fails_naming_the_entry(repo, systems, message):  # AC-201.3
    fails(repo, multi(systems=systems), message)


def test_ac_201_3_environments_in_a_repo_without_clusters_name_no_listed_cluster(repo):  # AC-201.3
    setup(repo, base(systems={"todo": {"repo": TODO_REPO, "environments": {"dev": LOCAL}}}))
    p = render(repo, None)
    assert p.returncode == 1
    assert p.stderr.strip().splitlines() == ["ERROR: cluster.yaml: systems.todo.environments.dev: cluster 'local' is not listed in clusters (listed: none)"]


def test_ac_201_3_an_entry_may_assign_only_some_environments(repo):  # AC-201.3
    render_clusters(repo, multi(systems=todo({"dev": LOCAL, "staging": LOCAL})))
    assert system_app(repo, HOME)["spec"]["source"]["directory"] == {"exclude": "*"}


# ---------------- AC-201.4: a repo without clusters is unchanged ----------------

def test_ac_201_4_a_repo_without_clusters_keeps_the_single_tree(repo):  # AC-201.4
    render_ok(repo, base(operators=["cloudnative-pg"], systems={"todo": {"repo": TODO_REPO}}))
    files = rendered(repo)
    assert {"cluster/operators-root.yaml", "cluster/systems-root.yaml", "cluster/operators/cloudnative-pg.yaml", "cluster/systems/todo.yaml"} <= set(files)
    assert load(repo, "cluster/systems/todo.yaml")["spec"]["source"]["path"] == "bootstrap"
    assert not (repo / "clusters").exists()


def test_ac_201_4_the_new_listing_flags_name_the_one_cluster_of_a_repo_without_clusters(repo):  # AC-201.4
    render_ok(repo, base(operators=["cloudnative-pg"], systems={"todo": {"repo": TODO_REPO}}))
    p = script(repo, "render.py", "--clusters")
    assert p.returncode == 0 and p.stdout.strip() == "", p.stdout + p.stderr
    t = script(repo, "render.py", "--trees")
    assert t.returncode == 0 and stdout_lines(t) == ["home cluster"], t.stdout + t.stderr
    e = script(repo, "render.py", "--envs", "home")
    assert e.returncode == 0 and sorted(stdout_lines(e)) == ["todo dev", "todo prod", "todo staging"], e.stdout + e.stderr
    c = script(repo, "render.py", "--crds")
    assert c.returncode == 0 and stdout_lines(c) == ["cloudnative-pg clusters.postgresql.cnpg.io"], c.stdout + c.stderr


# ---------------- AC-201.5: a moved environment ----------------

MOVED = "MOVED: todo {env}: cluster {old} -> {new}; nothing is copied, and its namespace todo-{env} and data stay on {old} until a person deletes them"


def moved(p) -> list[str]:
    return [ln for ln in stdout_lines(p) if ln.startswith("MOVED: ")]


def test_ac_201_5_an_environment_moved_off_the_first_cluster_prints_one_line(repo):  # AC-201.5
    render_clusters(repo, multi(systems=todo(None)))
    p = run_render(repo, multi(systems=todo()))
    assert p.returncode == 0, p.stderr
    assert moved(p) == [MOVED.format(env="prod", old=LOCAL, new=HOME)]


def test_ac_201_5_a_move_between_split_assignments_prints_one_line(repo):  # AC-201.5
    render_clusters(repo, multi(systems=todo()))
    p = run_render(repo, multi(systems=todo({"dev": LOCAL, "staging": HOME, "prod": HOME})))
    assert moved(p) == [MOVED.format(env="staging", old=LOCAL, new=HOME)]
    p = run_render(repo, multi(systems=todo({"dev": LOCAL, "staging": LOCAL, "prod": LOCAL})))
    assert sorted(moved(p)) == sorted([MOVED.format(env="staging", old=HOME, new=LOCAL), MOVED.format(env="prod", old=HOME, new=LOCAL)])


def test_ac_201_5_the_one_cluster_tree_counts_as_the_first_cluster(repo):  # AC-201.5
    render_ok(repo, base(systems={"todo": {"repo": TODO_REPO}}))
    p = run_render(repo, multi(systems=todo()))
    assert p.returncode == 0, p.stdout + p.stderr
    assert moved(p) == [MOVED.format(env="prod", old=LOCAL, new=HOME)]


def test_ac_201_5_nothing_moved_prints_no_line_and_a_second_render_prints_none(repo):  # AC-201.5
    first = run_render(repo, multi(systems=todo()))
    assert first.returncode == 0 and moved(first) == []
    render_clusters(repo, multi(systems=todo({"dev": LOCAL, "staging": LOCAL, "prod": LOCAL})))
    second = render(repo, None)
    assert moved(second) == []


def test_ac_201_5_the_old_cluster_keeps_no_application_for_the_environment_and_deletes_nothing_itself(repo):  # AC-201.5
    render_clusters(repo, multi(systems=todo()))
    run_render(repo, multi(systems=todo({"dev": LOCAL, "staging": LOCAL, "prod": LOCAL})))
    app = system_app(repo, LOCAL)
    assert app["spec"]["source"]["directory"] == {"include": "{*-dev.yaml,*-staging.yaml,*-prod.yaml}"}
    assert NO_FINALIZER not in (repo / "cluster" / LOCAL / "systems" / "todo.yaml").read_text()
    assert system_app(repo, HOME)["spec"]["source"]["directory"] == {"exclude": "*"}


# ---------------- AC-201.7: a later cluster stays at its release ----------------

def test_ac_201_7_a_later_cluster_renders_with_the_kept_renderer_of_its_release(repo):  # AC-201.7
    setup(repo, multi(operators=OPS, systems=todo()))
    pin_release(repo)
    p = render(repo, None)
    assert p.returncode == 0, p.stdout + p.stderr
    files = rendered(repo)
    assert tree_of(files, HOME) == {"cluster/home/operators-root.yaml": "kept: cluster/home by 4.12.0\n"}
    assert "cluster/local/operators/cloudnative-pg.yaml" in files, "the first cluster renders with this release"
    spec = json.loads((repo / ".platform" / "releases" / "4.12.0" / "stdin.json").read_text())
    assert spec["version"] == 1 and spec["tree"] == "cluster/home" and spec["operators"] == OPS and spec["server"] == SERVER
    assert spec["repo_url"] == f"https://github.com/{ORG}/home" and spec["store"] is None
    assert spec["systems"] == [{"name": "todo", "repo": TODO_REPO, "environments": ["prod"]}]


def test_ac_201_7_render_prints_one_behind_line_per_later_cluster_and_exits_0(repo):  # AC-201.7
    setup(repo, multi(systems=todo()))
    pin_release(repo)
    p = render(repo, None)
    assert p.returncode == 0
    assert [ln for ln in stdout_lines(p) if ln.startswith("BEHIND: ")] == [
        "BEHIND: cluster home runs platform 4.12.0, cluster local runs 5.1.0; promote it with /cluster:promote home"]
    again = render(repo, None)
    assert again.returncode == 0 and len([ln for ln in stdout_lines(again) if ln.startswith("BEHIND: ")]) == 1


def test_ac_201_7_a_cluster_on_the_same_release_is_not_behind_and_needs_no_kept_renderer(repo):  # AC-201.7
    setup(repo, multi(operators=OPS))
    pin_release(repo, later="5.1.0", kept=False)
    p = render(repo, None)
    assert p.returncode == 0, p.stdout + p.stderr
    assert not [ln for ln in stdout_lines(p) if ln.startswith("BEHIND")]
    assert "cluster/home/operators/cloudnative-pg.yaml" in rendered(repo)


def test_ac_201_7_the_first_cluster_may_not_pin_a_release(repo):  # AC-201.7
    setup(repo, multi())
    (repo / ".platform-version").write_text("platform: 5.1.0\n")
    (repo / "clusters" / LOCAL / "release.yaml").write_text("platform: 4.12.0\n")
    p = render(repo, None)
    assert p.returncode == 1
    assert p.stderr.strip().splitlines() == ["ERROR: clusters/local/release.yaml: the first cluster runs this repo's release 5.1.0; delete this file"]


def test_ac_201_7_a_malformed_release_file_fails(repo):  # AC-201.7
    setup(repo, multi())
    (repo / ".platform-version").write_text("platform: 5.1.0\n")
    (repo / "clusters" / HOME / "release.yaml").write_text("platform: latest\n")
    p = render(repo, None)
    assert p.returncode == 1
    assert p.stderr.strip().splitlines() == ["ERROR: clusters/home/release.yaml: must be {platform: <x.y.z>}"]


def test_ac_201_7_a_release_whose_renderer_is_not_kept_fails_naming_the_promotion(repo):  # AC-201.7
    setup(repo, multi())
    pin_release(repo, kept=False)
    before = rendered(repo)
    p = render(repo, None)
    assert p.returncode == 1 and rendered(repo) == before
    assert re.fullmatch(r"ERROR: \S+: platform 4\.12\.0 is not kept in \.platform/releases/4\.12\.0/; promote the cluster: /cluster:promote home\n?", p.stderr), p.stderr


def test_ac_201_7_a_failing_kept_renderer_is_reported_with_its_cluster_and_release(repo):  # AC-201.7
    setup(repo, multi())
    pin_release(repo)
    (repo / ".platform" / "releases" / "4.12.0" / "render.py").write_text("import sys\nprint('boom', file=sys.stderr)\nsys.exit(1)\n")
    p = render(repo, None)
    assert p.returncode == 1 and "cluster home (platform 4.12.0): boom" in p.stderr


def test_ac_201_7_render_never_touches_the_kept_renderers(repo):  # AC-201.7
    setup(repo, multi())
    pin_release(repo)
    kept = repo / ".platform" / "releases" / "4.12.0" / "render.py"
    assert render(repo, None).returncode == 0
    assert kept.read_text() == KEPT


# ---------------- flags the other scripts use (design section 3) ----------------

def test_ac_201_1_the_listing_flags_follow_the_assignment(repo):  # AC-201.1
    render_clusters(repo, multi(systems=todo()))
    assert stdout_lines(script(repo, "render.py", "--clusters")) == [LOCAL, HOME]
    assert stdout_lines(script(repo, "render.py", "--trees")) == ["local cluster/local", "home cluster/home"]
    assert sorted(stdout_lines(script(repo, "render.py", "--envs", LOCAL))) == ["todo dev", "todo staging"]
    assert stdout_lines(script(repo, "render.py", "--envs", HOME)) == ["todo prod"]
    assert stdout_lines(script(repo, "render.py", "--systems")) == [f"todo {TODO_REPO}"]


def test_ac_201_1_a_system_without_environments_runs_all_three_on_the_first_cluster(repo):  # AC-201.1
    render_clusters(repo, multi(systems=todo(None)))
    assert sorted(stdout_lines(script(repo, "render.py", "--envs", LOCAL))) == ["todo dev", "todo prod", "todo staging"]
    assert stdout_lines(script(repo, "render.py", "--envs", HOME)) == []


def test_ac_201_1_the_crds_of_a_cluster_follow_its_effective_operators(repo):  # AC-201.1
    ops = platform_module("render_201_crds").OPERATORS
    setup(repo, multi(), {HOME: {"operators": {"kyverno": True}}})
    assert render(repo, None).returncode == 0
    local = stdout_lines(script(repo, "render.py", "--crds", LOCAL))
    home = stdout_lines(script(repo, "render.py", "--crds", HOME))
    assert local == [f"cloudnative-pg {ops['cloudnative-pg']['crd']}"]
    assert home == [f"cloudnative-pg {ops['cloudnative-pg']['crd']}", f"kyverno {ops['kyverno']['crd']}"]


def test_ac_201_1_crds_without_a_name_in_a_repo_with_clusters_exits_2(repo):  # AC-201.1
    render_clusters(repo, multi())
    p = script(repo, "render.py", "--crds")
    assert p.returncode == 2 and p.stderr.strip() == "ERROR: name the cluster: --crds <cluster> (clusters: local, home)"


def test_ac_201_1_effective_describes_each_cluster_as_json(repo):  # AC-201.1
    setup(repo, multi(operators=OPS, systems=todo()), {HOME: {"server": "https://10.0.0.5:6443"}})
    (repo / ".platform-version").write_text("platform: 5.1.0\n")
    assert render(repo, None).returncode == 0
    p = script(repo, "render.py", "--effective")
    assert p.returncode == 0, p.stderr
    eff = json.loads(p.stdout)
    assert eff["release"] == "5.1.0"
    local, home = eff["clusters"]
    assert [local["name"], local["first"], local["tree"], local["server"], local["release"]] == [LOCAL, True, "cluster/local", SERVER, "5.1.0"]
    assert [home["name"], home["first"], home["tree"], home["server"]] == [HOME, False, "cluster/home", "https://10.0.0.5:6443"]
    assert local["operators"] == OPS and home["operators"] == OPS
    assert local["exceptions"] == [] and home["exceptions"] == [f"cluster home: server: https://10.0.0.5:6443 (shared: {SERVER})"]
    assert local["systems"] == [{"name": "todo", "repo": TODO_REPO, "environments": ["dev", "staging"]}]
    assert home["systems"] == [{"name": "todo", "repo": TODO_REPO, "environments": ["prod"]}]


def test_ac_201_4_effective_of_a_repo_without_clusters_has_one_entry_named_after_the_cluster(repo):  # AC-201.4
    render_ok(repo, base(operators=["cloudnative-pg"], systems={"todo": {"repo": TODO_REPO}}))
    eff = json.loads(script(repo, "render.py", "--effective").stdout)
    assert [(c["name"], c["tree"], c["first"]) for c in eff["clusters"]] == [("home", "cluster", True)]
    assert eff["clusters"][0]["systems"] == [{"name": "todo", "repo": TODO_REPO, "environments": None}]


def test_ac_201_7_render_cluster_is_a_stable_json_interface(repo):  # AC-201.7
    spec = {"version": 1, "tree": "cluster/home", "repo_url": f"https://github.com/{ORG}/home", "server": SERVER, "operators": ["cloudnative-pg"],
            "store": None, "systems": [{"name": "todo", "repo": TODO_REPO, "environments": ["prod"]}]}
    import subprocess
    import sys
    p = subprocess.run([sys.executable, "scripts/render.py", "--render-cluster"], cwd=repo, input=json.dumps(spec), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    files = json.loads(p.stdout)["files"]
    assert {"cluster/home/operators-root.yaml", "cluster/home/systems-root.yaml", "cluster/home/operators/cloudnative-pg.yaml",
            "cluster/home/systems/todo.yaml", "cluster/home/kustomization.yaml"} <= set(files)
    app = yaml.safe_load(files["cluster/home/systems/todo.yaml"])
    assert app["spec"]["source"]["directory"] == {"include": "*-prod.yaml"}
