"""Spec 125 acceptance tests, `cplat cluster new|add|remove` (AC-125.1 creation, AC-125.7, AC-125.8).

Contract: design.md section 7. Everything runs through `cplat.main`; `gh` is a PATH stub that serves fixture system repos and records
calls, git pushes to a local bare `origin`. A missing noun, module or flag fails the test, never the collection."""
import pytest

import cplat
from cluster_fixtures import ORG, base, cluster_repo, git, git_repo, render_ok, stubs, sys_doc, system_repo
from system_fixtures import files

TODO = f"{ORG}/todo-gitops"


def run(*argv, capsys):
    try:
        rc = cplat.main(["cluster", *map(str, argv)])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


@pytest.fixture()
def world(shared_renders, tmp_path, monkeypatch):
    repo = cluster_repo(shared_renders, tmp_path / "w")
    s = stubs(tmp_path, monkeypatch)
    system_repo(s["fixtures"], TODO, sys_doc("todo"))
    s["repo"] = repo
    return s


def committed(world, tmp_path, doc=None, text=None):
    repo = world["repo"]
    if doc is not None:
        render_ok(repo, doc)
    if text is not None:
        (repo / "cluster.yaml").write_text(text)
        render_ok(repo, text)
    world["remote"] = git_repo(repo, tmp_path)
    return repo


def branches(repo):
    return git(repo, "branch", "--list", "--all").split()


def gh_calls(world):
    return world["gh_log"].read_text().splitlines()


# ---------------- AC-125.1: cluster new ----------------

def test_ac_125_1_new_creates_a_private_repo_from_the_cluster_template(tmp_path, monkeypatch, capsys):  # AC-125.1
    s = stubs(tmp_path, monkeypatch)
    (tmp_path / "out").mkdir()
    rc, out, err = run("new", "demo", "--org", ORG, "--dir", tmp_path / "out", "--skip-tasks", capsys=capsys)
    assert rc == 0, out + err
    create = next(c for c in gh_calls({"gh_log": s["gh_log"]}) if c.startswith("repo create"))
    assert f"{ORG}/demo" in create and "--private" in create and "--public" not in create
    import yaml
    doc = yaml.safe_load((tmp_path / "out" / "demo" / "cluster.yaml").read_text())
    assert doc["cluster"] == "demo" and doc["owner"] == ORG and not doc.get("systems") and not doc.get("operators")
    assert f"New cluster repo: {ORG}/demo" in out
    steps = [ln for ln in out.splitlines() if "cluster.yaml" in ln or "SYSTEMS_TOKEN" in ln or "/cluster:add" in ln or "devbox run bootstrap" in ln]
    assert len(steps) >= 4 and out.index("SYSTEMS_TOKEN") < out.index("/cluster:add") < out.index("devbox run bootstrap")
    assert f"gh secret set SYSTEMS_TOKEN -R {ORG}/demo" in out


def test_ac_125_1_new_public_flag_and_dry_run(tmp_path, monkeypatch, capsys):  # AC-125.1
    s = stubs(tmp_path, monkeypatch)
    (tmp_path / "out").mkdir()
    rc, out, err = run("new", "demo", "--org", ORG, "--public", "--dir", tmp_path / "out", "--dry-run", capsys=capsys)
    assert rc == 0, out + err
    assert "PUBLIC" in out and f"New cluster repo: {ORG}/demo" in out
    assert not (tmp_path / "out" / "demo").exists()
    assert not any(c.startswith("repo create") for c in gh_calls({"gh_log": s["gh_log"]}))


@pytest.mark.parametrize("name", ["Bad_Name", "1cluster", "trailing-", "x" * 41, "UPPER"])
def test_ac_125_1_new_a_bad_name_changes_nothing_and_names_the_reason(tmp_path, monkeypatch, capsys, name):  # AC-125.1
    s = stubs(tmp_path, monkeypatch)
    rc, out, err = run("new", name, "--org", ORG, "--dir", tmp_path / "out", "--skip-tasks", capsys=capsys)
    assert rc == 1
    assert f"invalid cluster name '{name}'" in err
    assert "lowercase letters, digits and hyphens, at most 40 characters, starting with a letter and not ending with a hyphen" in err
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())
    assert not any(c.startswith("repo create") for c in gh_calls({"gh_log": s["gh_log"]}))


def test_ac_125_1_new_an_existing_repo_changes_nothing(tmp_path, monkeypatch, capsys):  # AC-125.1
    s = stubs(tmp_path, monkeypatch)
    monkeypatch.setenv("GH_EXISTING", f"{ORG}/demo")
    rc, out, err = run("new", "demo", "--org", ORG, "--dir", tmp_path / "out", "--skip-tasks", capsys=capsys)
    assert rc == 1 and f"GitHub repository {ORG}/demo already exists" in err and "choose another name" in err
    assert not (tmp_path / "out" / "demo").exists()
    assert not any(c.startswith("repo create") for c in gh_calls({"gh_log": s["gh_log"]}))


# ---------------- AC-125.7: cluster add ----------------

def test_ac_125_7_add_reads_the_name_adds_the_entry_renders_and_opens_one_pr(world, tmp_path, monkeypatch, capsys):  # AC-125.7
    repo = committed(world, tmp_path, text="# the cluster (keep this comment)\ncluster: home\nowner: acme\nsystems: {}\n")
    monkeypatch.chdir(repo)
    rc, out, err = run("add", TODO, "--repo-dir", repo, capsys=capsys)
    assert rc == 0, out + err
    assert "https://github.com/acme/home/pull/7" in out
    assert f"merge it: Argo CD then syncs {TODO}'s bootstrap/; the CI check names any operator the system still needs" in out
    assert "cluster/add-todo" in branches(repo)
    git(repo, "checkout", "-q", "cluster/add-todo")
    text = (repo / "cluster.yaml").read_text()
    assert "# the cluster (keep this comment)" in text
    import yaml
    assert yaml.safe_load(text)["systems"] == {"todo": {"repo": TODO}}
    assert (repo / "cluster" / "systems" / "todo.yaml").exists() and not (repo / "cluster" / "systems" / ".gitkeep").exists()
    msg = git(repo, "log", "-1", "--format=%B")
    assert msg.startswith("feat(cluster): install todo from acme/todo-gitops") and "Signed-off-by:" in msg
    assert "cluster/add-todo" in git(repo, "ls-remote", "--heads", "origin")
    assert sum(c.startswith("pr create") for c in gh_calls(world)) == 1


@pytest.mark.parametrize("dry", [False, True], ids=["run", "dry-run"])
def test_add_a_system_that_would_install_operators_itself_stops_before_any_change(world, tmp_path, capsys, dry):  # #263
    system_repo(world["fixtures"], f"{ORG}/self-gitops", sys_doc("self", owner_envs=()))
    repo = committed(world, tmp_path, base())
    before = (repo / "cluster.yaml").read_text()
    rc, out, err = run("add", f"{ORG}/self-gitops", "--repo-dir", repo, *(["--dry-run"] if dry else []), capsys=capsys)
    assert rc == 1, out + err
    assert "self (acme/self-gitops) fails this cluster's check, nothing was changed" in err
    assert f"self (dev): would install operators itself: set environments.dev.operators: owner in {ORG}/self-gitops" in err
    assert (repo / "cluster.yaml").read_text() == before and git(repo, "status", "--porcelain") == ""
    assert "cluster/add-self" not in branches(repo) and not any(c.startswith("pr create") for c in gh_calls(world))


def test_add_a_system_that_needs_an_operator_the_cluster_lacks_stops(world, tmp_path, capsys):  # #263
    system_repo(world["fixtures"], f"{ORG}/db-gitops", sys_doc("db", db_resource=True))
    repo = committed(world, tmp_path, base())
    rc, out, err = run("add", f"{ORG}/db-gitops", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "needs cloudnative-pg, which cluster.yaml does not list in operators" in err, out + err
    assert not any(c.startswith("pr create") for c in gh_calls(world))


def test_add_dry_run_of_a_fitting_system_says_it_was_checked(world, tmp_path, capsys):  # #263
    repo = committed(world, tmp_path, base())
    rc, out, err = run("add", TODO, "--repo-dir", repo, "--dry-run", capsys=capsys)
    assert rc == 0, out + err
    assert "checked todo against this cluster (scripts/check.py): no problems" in out


def test_ac_125_7_add_with_name_uses_it(world, tmp_path, monkeypatch, capsys):  # AC-125.7
    system_repo(world["fixtures"], f"{ORG}/multi-gitops", sys_doc("a"), extra_systems={"b": sys_doc("b")})
    repo = committed(world, tmp_path, base())
    rc, out, err = run("add", f"{ORG}/multi-gitops", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and f"{ORG}/multi-gitops holds several systems (a, b): pass --name" in err
    rc, out, err = run("add", f"{ORG}/multi-gitops", "--name", "b", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, out + err
    assert "cluster/add-b" in branches(repo)


def test_ac_125_7_add_a_name_that_is_not_in_the_repo_fails(world, tmp_path, capsys):  # AC-125.7
    repo = committed(world, tmp_path, base())
    rc, out, err = run("add", TODO, "--name", "nope", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and f"{TODO} has no applications/nope/system.yaml on main" in err


def test_ac_125_7_add_a_repo_without_system_yaml_changes_nothing(world, tmp_path, capsys):  # AC-125.7
    (world["fixtures"] / "acme__plain").mkdir()
    (world["fixtures"] / "acme__plain" / "README.md").write_text("x")
    (world["fixtures"] / "acme__plain" / "applications").mkdir()
    repo = committed(world, tmp_path, base())
    before = files(repo)
    rc, out, err = run("add", f"{ORG}/plain", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and f"{ORG}/plain is not a system's gitops repo: no applications/<system>/system.yaml on main" in err
    assert files(repo) == before and "cluster/add-plain" not in branches(repo)


def test_ac_125_7_add_a_repo_that_cannot_be_read_changes_nothing(world, tmp_path, capsys):  # AC-125.7
    repo = committed(world, tmp_path, base())
    before = files(repo)
    rc, out, err = run("add", f"{ORG}/ghost", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and f"cannot read {ORG}/ghost: " in err and "check the name and that your gh login can read it" in err
    assert files(repo) == before and not any(c.startswith("pr create") for c in gh_calls(world))


def test_ac_125_7_add_an_already_listed_system_changes_nothing(world, tmp_path, capsys):  # AC-125.7
    repo = committed(world, tmp_path, base(systems={"todo": {"repo": TODO}}))
    before = files(repo)
    rc, out, err = run("add", TODO, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and f"todo is already registered (systems.todo: {TODO})" in err
    assert files(repo) == before and not any(c.startswith("pr create") for c in gh_calls(world))


def test_ac_125_7_add_a_repo_outside_the_org_fails(world, tmp_path, capsys):  # AC-125.7
    system_repo(world["fixtures"], "other/todo-gitops", sys_doc("todo"))
    repo = committed(world, tmp_path, base())
    rc, out, err = run("add", "other/todo-gitops", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and f"other/todo-gitops is outside org '{ORG}'" in err


def test_ac_125_7_add_outside_a_cluster_repo_fails(tmp_path, monkeypatch, capsys):  # AC-125.7
    stubs(tmp_path, monkeypatch)
    rc, out, err = run("add", TODO, "--repo-dir", tmp_path, capsys=capsys)
    assert rc == 1 and f"not a cluster repo: {tmp_path} has no cluster.yaml" in err
    assert "run it in the cluster repo (/cluster:new creates one)" in err


def test_ac_125_7_add_needs_a_clean_tree(world, tmp_path, capsys):  # AC-125.7
    repo = committed(world, tmp_path, base())
    (repo / "scratch.txt").write_text("x")
    rc, out, err = run("add", TODO, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "the working tree has uncommitted changes" in err


def test_ac_125_7_a_render_failure_restores_cluster_yaml(world, tmp_path, capsys):  # AC-125.7
    repo = committed(world, tmp_path, base(operators=["cloudnative-pg"]))
    (repo / "scripts" / "render.py").write_text("import sys\nprint('ERROR: cluster.yaml: boom', file=sys.stderr)\nsys.exit(1)\n")
    git(repo, "commit", "-qam", "break the renderer")
    before = (repo / "cluster.yaml").read_text()
    rc, out, err = run("add", TODO, "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "boom" in err
    assert (repo / "cluster.yaml").read_text() == before and git(repo, "status", "--porcelain").strip() == ""


# ---------------- AC-125.8: cluster remove ----------------

def test_ac_125_8_remove_deletes_the_entry_and_its_application_in_one_pr(world, tmp_path, capsys):  # AC-125.8
    repo = committed(world, tmp_path, base(systems={"todo": {"repo": TODO}}))
    assert (repo / "cluster" / "systems" / "todo.yaml").exists()
    rc, out, err = run("remove", "todo", "--repo-dir", repo, capsys=capsys)
    assert rc == 0, out + err
    assert "cluster/remove-todo" in branches(repo)
    git(repo, "checkout", "-q", "cluster/remove-todo")
    import yaml
    assert not (yaml.safe_load((repo / "cluster.yaml").read_text()).get("systems"))
    assert not (repo / "cluster" / "systems" / "todo.yaml").exists() and (repo / "cluster" / "systems" / ".gitkeep").exists()
    msg = git(repo, "log", "-1", "--format=%B")
    assert msg.startswith("feat(cluster): remove todo") and "Signed-off-by:" in msg
    assert sum(c.startswith("pr create") for c in gh_calls(world)) == 1


def test_ac_125_8_remove_says_that_everything_stays_in_the_cluster(world, tmp_path, capsys):  # AC-125.8
    repo = committed(world, tmp_path, base(systems={"todo": {"repo": TODO}}))
    rc, out, err = run("remove", "todo", "--repo-dir", repo, capsys=capsys)
    assert rc == 0
    assert ("kept in the cluster: the namespaces todo-dev, todo-staging, todo-prod, the Argo CD application todo-root and everything it created, "
            "and all data stay until a human deletes them (system-todo has no resources finalizer, so merging deletes nothing)") in out


def test_ac_125_8_remove_dry_run_still_prints_the_notice_and_changes_nothing(world, tmp_path, capsys):  # AC-125.8
    repo = committed(world, tmp_path, base(systems={"todo": {"repo": TODO}}))
    before = files(repo)
    rc, out, err = run("remove", "todo", "--repo-dir", repo, "--dry-run", capsys=capsys)
    assert rc == 0 and "kept in the cluster:" in out
    assert files(repo) == before and not any(c.startswith("pr create") for c in gh_calls(world))


def test_ac_125_8_remove_an_unknown_name_lists_the_registered_systems(world, tmp_path, capsys):  # AC-125.8
    repo = committed(world, tmp_path, base(systems={"todo": {"repo": TODO}, "ai-ops": {"repo": f"{ORG}/ai"}}))
    before = files(repo)
    rc, out, err = run("remove", "nope", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "unknown system 'nope' (registered: todo, ai-ops)" in err
    assert files(repo) == before


def test_ac_125_8_remove_from_a_cluster_without_systems_says_none(world, tmp_path, capsys):  # AC-125.8
    repo = committed(world, tmp_path, base())
    rc, out, err = run("remove", "todo", "--repo-dir", repo, capsys=capsys)
    assert rc == 1 and "unknown system 'todo' (registered: none)" in err
