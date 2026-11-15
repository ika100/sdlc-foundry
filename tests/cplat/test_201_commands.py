"""Spec 201 acceptance tests, the commands that act on one environment find its cluster (AC-201.9): `kube_contexts`, the resolver
(scripts/cplat/envcluster.py), `system wait --env`, `cluster wait <cluster>`, `system status`, the resource commands and
`system restore`.

Contract: design.md section 8. kubectl is a PATH stub that answers per `--context` and logs every call, the personal settings file is
under a private XDG_CONFIG_HOME, and the commands run through `cplat.main`. The current kube context is a trap: the stub answers
`the-wrong-current-context` and the tests assert that no command asks for it."""
import subprocess

import pytest
import yaml

import cplat
import settings
from core import PlatformError
from cluster_fixtures import base, cluster_repo, git_repo, render_ok, soft, stubs
from backup_fixtures import bdoc, clock, make_repo  # noqa: F401  (clock: a fixture, no real sleeps)
from support_201 import HOME, LOCAL, kube_calls, kube_stub, multi, setup, user_settings
from system_fixtures import git

LOCAL_CTX, HOME_CTX = "ctx-local", "ctx-home"
BOTH = f"kube_contexts: {{local: {LOCAL_CTX}, home: {HOME_CTX}}}\n"
SPLIT = {"dev": LOCAL, "staging": LOCAL, "prod": HOME}


BACKUP = {"to": "backups"}
ALL_ENVS = {"dev": BACKUP, "staging": BACKUP, "prod": BACKUP}


def shop_repo(tmp_path, clusters=SPLIT):
    """A committed gitops checkout of system `shop` (a backed-up database `orders-db`, rendered without cluster keys, which the
    renderer of today accepts); the `cluster` keys are added to system.yaml afterwards, and the model reads them."""
    repo = make_repo(tmp_path / "shop-gitops", bdoc(dbb=ALL_ENVS, envb=ALL_ENVS))
    if clusters:
        f = repo / "applications" / "shop" / "system.yaml"
        doc = yaml.safe_load(f.read_text())
        for env, c in clusters.items():
            doc["environments"][env]["cluster"] = c
        f.write_text(yaml.safe_dump(doc, sort_keys=False))
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "assign the environments to clusters")
    return repo


def load_model(repo):
    import model
    return model.load_dir(repo / "applications" / "shop")


@pytest.fixture()
def wait_clock(monkeypatch):
    t = {"now": 1000.0}

    def now():
        t["now"] += 50
        return t["now"]
    monkeypatch.setattr("waits.now", now)
    monkeypatch.setattr("waits.sleep", lambda s: None)


@pytest.fixture()
def world(tmp_path, monkeypatch, clock):
    stubs(tmp_path, monkeypatch)
    log = kube_stub(tmp_path, monkeypatch, reachable=(LOCAL_CTX, HOME_CTX))
    user_settings(tmp_path, monkeypatch, BOTH)
    return shop_repo(tmp_path), log


def run(argv, capsys):
    code = cplat.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def contexts_of(log):
    out = []
    for ln in kube_calls(log):
        words = ln.split()
        out.append(words[words.index("--context") + 1] if "--context" in words else None)
    return out


def never_current(log):
    return not any("config current-context" in ln for ln in kube_calls(log))


# ---------------- settings: kube_contexts ----------------

def test_ac_201_9_kube_contexts_come_from_the_user_file_and_the_project_file_wins_per_key(tmp_path, monkeypatch):  # AC-201.9
    user_settings(tmp_path, monkeypatch, "kube_contexts: {local: user-local, home: user-home}\n")
    repo = tmp_path / "r"
    repo.mkdir()
    assert settings.kube_contexts(repo) == {"local": "user-local", "home": "user-home"}
    (repo / ".platform-settings.yml").write_text("kube_contexts: {home: project-home}\n")
    assert settings.kube_contexts(repo) == {"local": "user-local", "home": "project-home"}


def test_ac_201_9_no_kube_contexts_is_an_empty_record(tmp_path, monkeypatch):  # AC-201.9
    user_settings(tmp_path, monkeypatch, None)
    assert settings.kube_contexts(tmp_path) == {}


@pytest.mark.parametrize("text", ["kube_contexts: [a, b]\n", "kube_contexts: {home: ''}\n", "kube_contexts: {home: 3}\n"])
def test_ac_201_9_a_kube_contexts_value_that_is_not_a_context_name_is_refused(tmp_path, monkeypatch, text):  # AC-201.9
    f = user_settings(tmp_path, monkeypatch, text)
    with pytest.raises(PlatformError, match="kube_contexts must map cluster names to kube context names") as e:
        settings.kube_contexts(tmp_path)
    assert str(f) in str(e.value)


# ---------------- the resolver ----------------

def test_ac_201_9_the_model_knows_the_cluster_of_each_environment(world):  # AC-201.9
    import envcluster
    repo, _ = world
    m = load_model(repo)
    assert [envcluster.cluster_of(m, e) for e in ("dev", "staging", "prod")] == [LOCAL, LOCAL, HOME]
    assert envcluster.spread(m) is True


def test_ac_201_9_a_system_on_one_cluster_is_not_spread(tmp_path):  # AC-201.9
    import envcluster
    for clusters in (None, {"dev": LOCAL, "staging": LOCAL, "prod": LOCAL}):
        m = load_model(shop_repo(tmp_path / str(bool(clusters)), clusters))
        assert envcluster.spread(m) is False


def test_ac_201_9_a_known_reachable_context_is_used(world):  # AC-201.9
    import envcluster
    repo, log = world
    assert envcluster.cluster_context(repo, HOME, None, "environment prod of shop") == HOME_CTX
    assert set(contexts_of(log)) == {HOME_CTX} and never_current(log)
    assert any("get applications" in ln for ln in kube_calls(log)), "reachability is one read of the applications"


def test_ac_201_9_an_explicit_context_wins_over_the_record(world, tmp_path, monkeypatch):  # AC-201.9
    import envcluster
    repo, log = world
    kube_stub(tmp_path, monkeypatch, reachable=(LOCAL_CTX, HOME_CTX, "other"))
    assert envcluster.cluster_context(repo, HOME, "other", "environment prod of shop") == "other"


def test_ac_201_9_no_known_context_stops_naming_the_environment_the_cluster_and_the_fix(world, tmp_path, monkeypatch):  # AC-201.9
    import envcluster
    repo, log = world
    f = user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}}}\n")
    with pytest.raises(PlatformError) as e:
        envcluster.cluster_context(repo, HOME, None, "environment prod of shop")
    assert str(e.value) == "environment prod of shop runs on cluster home, and no kube context is known for it"
    hint = e.value.hint or ""
    assert "pass --context" in hint and "kube_contexts: {home: " in hint and str(f) in hint and "credentials stay in your kubeconfig" in hint
    assert kube_calls(log) == [] and never_current(log)


def test_ac_201_9_an_unreachable_context_stops_naming_where_it_came_from(world, tmp_path, monkeypatch):  # AC-201.9
    import envcluster
    repo, log = world
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}, home: dead-ctx}}\n")
    with pytest.raises(PlatformError) as e:
        envcluster.cluster_context(repo, HOME, None, "environment prod of shop")
    assert str(e.value) == ("environment prod of shop runs on cluster home, whose kube context dead-ctx (user settings) does not answer: "
                            "Unable to connect to the server: dial tcp 10.0.0.5:6443: no route to host")
    assert never_current(log)


def test_ac_201_9_the_project_settings_are_named_as_the_source(world):  # AC-201.9
    import envcluster
    repo, _ = world
    (repo / ".platform-settings.yml").write_text("kube_contexts: {home: dead-ctx}\n")
    with pytest.raises(PlatformError, match=r"kube context dead-ctx \(project settings\) does not answer"):
        envcluster.cluster_context(repo, HOME, None, "environment prod of shop")


def test_ac_201_9_env_context_follows_the_environments_cluster_only_for_a_spread_system(world, tmp_path):  # AC-201.9
    import envcluster
    repo, log = world
    m = load_model(repo)
    assert envcluster.env_context(repo, m, "prod", None) == HOME_CTX
    assert envcluster.env_context(repo, m, "dev", None) == LOCAL_CTX
    assert envcluster.env_context(repo, m, "prod", "mine") == "mine"
    one = load_model(shop_repo(tmp_path / "one", None))
    assert envcluster.env_context(repo, one, "prod", None) is None, "today's choice of kube context stays"
    assert never_current(log)


# ---------------- system wait ----------------

def wait_argv(repo, *more):
    return ["system", "wait", "--env", "prod", "--revision", git(repo, "rev-parse", "HEAD").strip(), "--timeout", "30", "--interval", "1",
            "--repo-dir", str(repo), *more]


def test_ac_201_9_system_wait_uses_the_context_of_the_cluster_that_runs_the_environment(world, wait_clock, capsys):  # AC-201.9
    repo, log = world
    run(wait_argv(repo), capsys)
    seen = contexts_of(log)
    assert seen and set(seen) == {HOME_CTX}, seen
    assert never_current(log)
    log.write_text("")
    run(wait_argv(repo)[:3] + ["dev"] + wait_argv(repo)[4:], capsys)
    assert set(contexts_of(log)) == {LOCAL_CTX}


def test_ac_201_9_system_wait_stops_before_acting_when_it_cannot_tell_or_reach_the_cluster(world, wait_clock, capsys, tmp_path, monkeypatch):  # AC-201.9
    repo, log = world
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}}}\n")
    code, out, err = run(wait_argv(repo), capsys)
    assert code != 0 and "environment prod of shop runs on cluster home, and no kube context is known for it" in err
    assert kube_calls(log) == []
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}, home: dead-ctx}}\n")
    code, out, err = run(wait_argv(repo), capsys)
    assert code != 0 and "whose kube context dead-ctx (user settings) does not answer" in err
    assert all("get applications -o name" in ln for ln in kube_calls(log)), "only the reachability read, nothing else"


def test_ac_201_9_an_explicit_context_wins_in_system_wait(world, wait_clock, capsys, monkeypatch, tmp_path):  # AC-201.9
    repo, log = world
    kube_stub(tmp_path, monkeypatch, reachable=(LOCAL_CTX, HOME_CTX, "mine"))
    run(wait_argv(repo, "--context", "mine"), capsys)
    assert set(contexts_of(log)) == {"mine"}


def test_ac_201_4_a_system_on_one_cluster_keeps_the_configured_context(tmp_path, monkeypatch, wait_clock, capsys):  # AC-201.4
    stubs(tmp_path, monkeypatch)
    log = kube_stub(tmp_path, monkeypatch, reachable=("only-ctx",))
    user_settings(tmp_path, monkeypatch, None)
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "only-ctx")
    repo = shop_repo(tmp_path, None)
    run(wait_argv(repo), capsys)
    seen = contexts_of(log)
    assert seen and set(seen) == {"only-ctx"}


# ---------------- cluster wait ----------------

@pytest.fixture()
def crepo(shared_renders, tmp_path, monkeypatch, clock):
    stubs(tmp_path, monkeypatch)
    log = kube_stub(tmp_path, monkeypatch, reachable=(LOCAL_CTX, HOME_CTX))
    user_settings(tmp_path, monkeypatch, BOTH)
    repo = cluster_repo(shared_renders, tmp_path / "c")
    setup(repo, multi())
    subprocess.run(["uv", "run", "scripts/render.py"], cwd=repo, capture_output=True, text=True)    # not asserted: the tests show what is missing
    soft(git_repo, repo, tmp_path)
    return repo, log


def cluster_wait(repo, capsys, *names, more=()):
    return run(["cluster", "wait", *names, "--timeout", "30", "--interval", "1", "--repo-dir", str(repo), *more], capsys)


def test_ac_201_9_cluster_wait_waits_on_the_named_clusters_roots_in_its_context(crepo, wait_clock, capsys):  # AC-201.9
    repo, log = crepo
    cluster_wait(repo, capsys, HOME)
    seen = contexts_of(log)
    assert seen and set(seen) == {HOME_CTX} and never_current(log)


def test_ac_201_9_cluster_wait_needs_the_name_of_the_cluster_in_a_repo_with_clusters(crepo, wait_clock, capsys):  # AC-201.9
    repo, log = crepo
    code, _, err = cluster_wait(repo, capsys)
    assert code != 0 and "name the cluster to wait for: cplat cluster wait <cluster> (clusters: local, home)" in err
    code, _, err = cluster_wait(repo, capsys, "mars")
    assert code != 0 and "unknown cluster 'mars' (clusters: local, home)" in err
    assert kube_calls(log) == []


def test_ac_201_9_cluster_wait_fails_the_same_way_without_a_context(crepo, wait_clock, capsys, tmp_path, monkeypatch):  # AC-201.9
    repo, log = crepo
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}}}\n")
    code, _, err = cluster_wait(repo, capsys, HOME)
    assert code != 0 and "cluster home" in err and "no kube context is known for it" in err
    assert kube_calls(log) == []


def test_ac_201_4_cluster_wait_in_a_repo_without_clusters_keeps_working_without_a_name(shared_renders, tmp_path, monkeypatch, wait_clock, capsys):  # AC-201.4
    stubs(tmp_path, monkeypatch)
    log = kube_stub(tmp_path, monkeypatch, reachable=("only-ctx",))
    user_settings(tmp_path, monkeypatch, None)
    repo = cluster_repo(shared_renders, tmp_path / "c")
    render_ok(repo, base())
    git_repo(repo, tmp_path)
    cluster_wait(repo, capsys, more=("--context", "only-ctx"))
    assert set(contexts_of(log)) == {"only-ctx"}


# ---------------- system status ----------------

def test_ac_201_9_status_shows_an_environment_whose_cluster_cannot_be_reached_as_unreachable(world, capsys, tmp_path, monkeypatch):  # AC-201.9
    repo, log = world
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}, home: dead-ctx}}\n")
    code, out, err = run(["system", "status", "--repo-dir", str(repo)], capsys)
    assert code == 1, out + err
    assert "unreachable: home" in out and "unreachable: local" not in out
    assert "dev" in out and "staging" in out, "the reachable environments are still shown"


def test_ac_201_9_status_shows_an_environment_whose_cluster_has_no_context_as_unreachable(world, capsys, tmp_path, monkeypatch):  # AC-201.9
    repo, _ = world
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}}}\n")
    code, out, _ = run(["system", "status", "--repo-dir", str(repo)], capsys)
    assert code == 1 and "unreachable: home" in out


def test_ac_201_9_status_reads_each_environment_from_its_own_cluster(world, capsys):  # AC-201.9
    repo, log = world
    code, out, err = run(["system", "status", "--repo-dir", str(repo)], capsys)
    assert code == 0, out + err
    assert "unreachable" not in out
    assert {LOCAL_CTX, HOME_CTX} <= set(contexts_of(log)) and never_current(log)


def test_ac_201_9_status_with_an_explicit_context_for_an_environment_uses_it(world, capsys, tmp_path, monkeypatch):  # AC-201.9
    repo, log = world
    user_settings(tmp_path, monkeypatch, None)
    code, out, _ = run(["system", "status", "--repo-dir", str(repo), "--context", f"prod={HOME_CTX}", "--context", f"dev={LOCAL_CTX}",
                        "--context", f"staging={LOCAL_CTX}"], capsys)
    assert code == 0 and "unreachable" not in out


# ---------------- resource commands and system restore ----------------

COMMANDS = {
    "backup": ["resource", "backup", "orders-db", "--env", "prod"],
    "restore": ["resource", "restore", "orders-db", "--env", "prod", "--to", "latest"],
    "query": ["resource", "query", "orders-db", "select 1", "--env", "prod"],
    "upgrade": ["resource", "upgrade", "orders-db", "--env", "prod", "--verify"],
    "system-restore": ["system", "restore", "prod"],
}


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_ac_201_9_the_command_stops_before_acting_when_the_context_is_unknown(world, capsys, tmp_path, monkeypatch, name):  # AC-201.9
    repo, log = world
    user_settings(tmp_path, monkeypatch, f"kube_contexts: {{local: {LOCAL_CTX}}}\n")
    code, out, err = run([*COMMANDS[name], "--repo-dir", str(repo)], capsys)
    assert code != 0, out
    assert "runs on cluster home" in out + err and "environment prod" in out + err and "kube_contexts" in out + err, out + err
    assert kube_calls(log) == [], "not one kubectl call before the error"


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_ac_201_9_the_command_uses_the_context_of_the_environments_cluster(world, capsys, name):  # AC-201.9
    repo, log = world
    run([*COMMANDS[name], "--repo-dir", str(repo)], capsys)
    seen = contexts_of(log)
    assert seen, "the command reached the cluster"
    assert HOME_CTX in seen and LOCAL_CTX not in seen and None not in seen, seen
    assert never_current(log)


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_ac_201_9_an_explicit_context_wins_in_every_command(world, capsys, tmp_path, monkeypatch, name):  # AC-201.9
    repo, log = world
    kube_stub(tmp_path, monkeypatch, reachable=(LOCAL_CTX, HOME_CTX, "mine"))
    run([*COMMANDS[name], "--repo-dir", str(repo), "--context", "mine" if name != "upgrade" else "prod=mine"], capsys)
    seen = contexts_of(log)
    assert "mine" in seen and HOME_CTX not in seen and LOCAL_CTX not in seen, seen


# ---------------- the two commands that run inside a component repo ----------------

def component_world(tmp_path, monkeypatch, contexts=BOTH):
    """A clone of component `acme/api` linked to the gitops system `todo` (dev and staging on local, prod on home), read through the
    `gh` stub; kubectl answers per context and logs every call."""
    from support_201 import split_doc, split_repo
    s = stubs(tmp_path, monkeypatch)
    split_repo(s["fixtures"], split_doc())
    log = kube_stub(tmp_path, monkeypatch, reachable=(LOCAL_CTX, HOME_CTX))
    user_settings(tmp_path, monkeypatch, contexts)
    repo = tmp_path / "api"
    repo.mkdir()
    (repo / ".platform-app.yml").write_text("gitops:\n  - acme/todo-gitops\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "https://github.com/acme/api.git")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo, log


def verify_prod(repo, capsys, monkeypatch):
    class Red:
        outcome, ok, env, base_url, digest, tests = "not-run", False, "prod", None, None, []

        def section(self):
            return {"env": "prod", "outcome": "not-run"}

        def lines(self):
            return ["smoke: not run"]

    monkeypatch.setattr("smoke.run_smoke", lambda *a, **kw: Red())
    monkeypatch.setattr("smoke.record", lambda *a, **kw: None)
    return run(["instance", "verify", "prod", "--repo", str(repo)], capsys)


def test_ac_201_9_instance_verify_uses_the_context_of_the_environments_cluster(tmp_path, monkeypatch, capsys):  # AC-201.9
    repo, log = component_world(tmp_path, monkeypatch)
    verify_prod(repo, capsys, monkeypatch)
    seen = contexts_of(log)
    assert seen, "verifying prod reached the cluster that runs it"
    assert set(seen) == {HOME_CTX}, seen
    assert never_current(log)


def test_ac_201_9_instance_verify_stops_before_any_kubectl_call_when_no_context_is_known(tmp_path, monkeypatch, capsys):  # AC-201.9
    repo, log = component_world(tmp_path, monkeypatch, contexts=f"kube_contexts: {{local: {LOCAL_CTX}}}\n")
    code, out, err = verify_prod(repo, capsys, monkeypatch)
    assert code != 0 and "runs on cluster home, and no kube context is known for it" in out + err, out + err
    assert kube_calls(log) == []


def deploy_world(tmp_path, monkeypatch, contexts=BOTH):
    """`component ship deploy` of a landed ship: the pin PR is merged, main CI is green, Argo CD answers from the stub."""
    import json
    import ship
    repo, log = component_world(tmp_path, monkeypatch, contexts)
    sha = "a" * 40
    ship.save_state(repo, {"spec": "001-x", "phase": "deploy", "merge": True, "branch": "feature/001-x", "started": "2026-11-05T08:00:00",
                           "recorded": False, "run_id": "r1", "shape": "service", "merge_sha": sha})
    t = {"now": 1000.0}

    def now():
        t["now"] += 30
        return t["now"]
    monkeypatch.setattr(ship, "now", now)
    monkeypatch.setattr(ship, "sleep", lambda s: None)
    monkeypatch.setattr(ship, "main_ci", lambda repo, sha: ("green", []))
    monkeypatch.setattr(ship, "merge_gitops", lambda *a, **kw: (True, []))
    monkeypatch.setattr(ship, "_smoke_step", lambda *a, **kw: (True, ["smoke stubbed"]))
    monkeypatch.setattr(ship, "_smoke_not_run", lambda *a, **kw: (True, ["smoke stubbed"]))
    real_gh = ship.gh
    merged = json.dumps([{"number": 3, "state": "MERGED", "url": "https://github.com/acme/todo-gitops/pull/3"}])
    monkeypatch.setattr(ship, "gh", lambda args, **kw: merged if args[:2] == ["pr", "list"] else real_gh(args, **kw))
    import shapecmd
    monkeypatch.setattr(shapecmd, "route", lambda repo: {"deployable": True, "shape": "service"})
    return repo, log


def test_ac_201_9_ship_deploy_waits_on_the_cluster_that_runs_dev(tmp_path, monkeypatch, capsys):  # AC-201.9
    repo, log = deploy_world(tmp_path, monkeypatch)
    run(["component", "ship", "--repo", str(repo), "deploy", "--timeout", "60"], capsys)
    seen = contexts_of(log)
    assert seen, "the deploy wait asked the cluster that runs dev"
    assert set(seen) == {LOCAL_CTX}, seen
    assert never_current(log)


def test_ac_201_9_ship_deploy_stops_before_any_kubectl_call_when_no_context_is_known(tmp_path, monkeypatch, capsys):  # AC-201.9
    repo, log = deploy_world(tmp_path, monkeypatch, contexts=f"kube_contexts: {{home: {HOME_CTX}}}\n")
    code, out, err = run(["component", "ship", "--repo", str(repo), "deploy", "--timeout", "60"], capsys)
    assert code != 0 and "runs on cluster local, and no kube context is known for it" in out + err, out + err
    assert kube_calls(log) == []


def test_ac_201_9_the_module_exists_with_the_contract_functions():  # AC-201.9
    import envcluster
    for name in ("cluster_of", "spread", "cluster_context", "env_context"):
        assert callable(getattr(envcluster, name)), name
