"""Spec 203 acceptance tests: the ship hand-off resolves, records and passes the kube context (AC-203.1, AC-203.2).

Seams (design.md): `shipcontext.resolve(repo, given, recorded) -> (name, source)`, `shipcontext.contexts()` (the kubeconfig's
context names; replaced here, nothing calls `kubectl`), `ship_handoff.spawn(..., context=)` through the fake detached process of
`ship200_support.Procs`, `ship.main` as the CLI. No real `cplat headless`, `kubectl`, `gh` or `claude` runs.
"""
import pytest

import ship
from ship200_support import detach, headless_line, interactive, procs  # noqa: F401
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_ship import repo  # noqa: F401  (fixture)

NONE_LINE = "context: none (dev is not checked; pass --context <kube-context>)"


def shipcontext():
    try:
        import shipcontext as module
    except ModuleNotFoundError:
        pytest.fail("scripts/cplat/shipcontext.py does not exist yet (plan task t3: resolve, contexts, line)")
    return module


@pytest.fixture()
def world(monkeypatch, tmp_path):
    """An interactive session with no kube context from any source; the kubeconfig lists `contexts`."""
    interactive(monkeypatch)
    for name in ("CPLAT_KUBE_CONTEXT", "KUBE_CONTEXT"):
        monkeypatch.setenv(name, "x")
        monkeypatch.delenv(name)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))

    def configure(*names, env=None):
        for k, v in (env or {}).items():
            monkeypatch.setenv(k, v)
        monkeypatch.setattr(shipcontext(), "contexts", lambda: set(names))
    return configure


def project_settings(repo, text):
    (repo / ".platform-settings.yml").write_text(text)


def user_settings(tmp_path, text):
    f = tmp_path / "xdg-config" / "sdlc-foundry" / "settings.yml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)


def lines_after_headless(out):
    lines = out.splitlines()
    i = next(n for n, ln in enumerate(lines) if ln.startswith("headless: pid "))
    return lines[i + 1] if i + 1 < len(lines) else None


# ---------------- AC-203.1: the context order, the state, the process, the line ----------------

def test_the_explicit_context_wins_and_reaches_state_process_and_output_ac_203_1(repo, procs, world, capsys):  # AC-203.1
    p = procs()
    world("lan", "other", env={"CPLAT_KUBE_CONTEXT": "other", "KUBE_CONTEXT": "other"})
    rc, out, err = detach(capsys, repo, "--context", "lan")
    assert rc == 0, out + err
    assert p.last["env"]["CPLAT_KUBE_CONTEXT"] == "lan"          # replaced, not dropped
    st = ship.load_state(repo)
    assert st["context"]["name"] == "lan"
    assert headless_line(out) and lines_after_headless(out) == "context: lan (--context)"


@pytest.mark.parametrize("env,name,source", [
    ({"CPLAT_KUBE_CONTEXT": "from-cplat", "KUBE_CONTEXT": "from-kube"}, "from-cplat", "CPLAT_KUBE_CONTEXT"),
    ({"KUBE_CONTEXT": "from-kube"}, "from-kube", "KUBE_CONTEXT"),
    ({"CPLAT_KUBE_CONTEXT": "   ", "KUBE_CONTEXT": "from-kube"}, "from-kube", "KUBE_CONTEXT"),
], ids=["cplat-before-kube", "kube", "blank-is-skipped"])
def test_the_calling_sessions_environment_gives_the_context_ac_203_1(repo, procs, world, capsys, env, name, source):  # AC-203.1
    p = procs()
    world(env=env)
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    assert p.last["env"]["CPLAT_KUBE_CONTEXT"] == name
    assert ship.load_state(repo)["context"]["name"] == name
    assert lines_after_headless(out) == f"context: {name} ({source})"


def test_the_settings_files_give_the_context_project_before_user_ac_203_1(repo, procs, world, capsys, tmp_path):  # AC-203.1
    p = procs()
    world()
    user_settings(tmp_path, "kube_context: from-user\n")
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    assert p.last["env"]["CPLAT_KUBE_CONTEXT"] == "from-user"
    assert lines_after_headless(out) == "context: from-user (kube_context in the user settings)"
    project_settings(repo, "kube_context: from-project\n")
    p.live.clear()                                          # the first process ended: a new run starts
    st = ship.load_state(repo)
    st.pop("context", None)
    ship.save_state(repo, st)
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    assert p.last["env"]["CPLAT_KUBE_CONTEXT"] == "from-project"
    assert lines_after_headless(out) == "context: from-project (kube_context in the project settings)"


def test_the_session_environment_goes_before_the_settings_ac_203_1(repo, procs, world, capsys):  # AC-203.1
    p = procs()
    world(env={"KUBE_CONTEXT": "from-env"})
    project_settings(repo, "kube_context: from-project\n")
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    assert p.last["env"]["CPLAT_KUBE_CONTEXT"] == "from-env"


def test_resolve_follows_the_order_of_the_contract_ac_203_1(repo, world, tmp_path, monkeypatch):  # AC-203.1
    sc = shipcontext()
    world("lan")
    assert sc.resolve(repo, "lan", None) == ("lan", "--context")
    assert sc.resolve(repo, None, None) == (None, None)
    monkeypatch.setenv("KUBE_CONTEXT", "k")
    assert sc.resolve(repo, None, None) == ("k", "KUBE_CONTEXT")
    monkeypatch.setenv("CPLAT_KUBE_CONTEXT", "c")
    assert sc.resolve(repo, None, None) == ("c", "CPLAT_KUBE_CONTEXT")
    assert sc.resolve(repo, "lan", None) == ("lan", "--context")


def test_the_local_cluster_of_the_linked_system_is_the_last_source_ac_203_1(repo, world, monkeypatch):  # AC-203.1
    import smoke
    sc = shipcontext()
    (repo / ".platform-app.yml").write_text("gitops_apps:\n  - acme/shop-gitops\n")
    monkeypatch.setattr(smoke, "_app_dirs", lambda slug, repo_dir: (["shop"], ""))
    world("k3d-shop-local", "unrelated")
    assert sc.resolve(repo, None, None) == ("k3d-shop-local", "local cluster of shop")
    world("unrelated")                                      # the kubeconfig does not have it: no guess, not the current context
    assert sc.resolve(repo, None, None) == (None, None)
    world("k3d-shop-local")
    monkeypatch.setenv("KUBE_CONTEXT", "k")
    assert sc.resolve(repo, None, None) == ("k", "KUBE_CONTEXT")


def test_the_headless_deploy_takes_the_recorded_context_ac_203_1(repo, procs, world, capsys):  # AC-203.1
    """The recorded context is in the state the headless `ship deploy` reads (tested with the whole deploy in test_203_context_deploy.py)."""
    procs()
    world("lan")
    assert detach(capsys, repo, "--context", "lan")[0] == 0
    st = ship.load_state(repo)
    assert st["context"] == {"name": "lan", "source": "--context"}


# ---------------- AC-203.2: restarts, no context, unknown context ----------------

def test_a_restart_gets_the_recorded_context_without_being_told_ac_203_2(repo, procs, world, capsys, monkeypatch):  # AC-203.2
    p = procs()
    world("lan", "other")
    assert detach(capsys, repo, "--context", "lan")[0] == 0
    p.live.clear()                                          # the process ended: the next --detach starts another
    rc, out, err = detach(capsys, repo)                     # no --context, no environment, no settings
    assert rc == 0, out + err
    assert len(p.spawned) == 2
    assert p.last["env"]["CPLAT_KUBE_CONTEXT"] == "lan"
    assert lines_after_headless(out) == "context: lan (recorded at the hand-off)"
    assert ship.load_state(repo)["context"]["name"] == "lan"


def test_a_restart_with_another_explicit_context_replaces_it_ac_203_2(repo, procs, world, capsys):  # AC-203.2
    p = procs()
    world("lan", "other")
    assert detach(capsys, repo, "--context", "lan")[0] == 0
    p.live.clear()
    rc, out, err = detach(capsys, repo, "--context", "other")
    assert rc == 0, out + err
    assert p.last["env"]["CPLAT_KUBE_CONTEXT"] == "other"
    assert ship.load_state(repo)["context"]["name"] == "other"
    assert lines_after_headless(out) == "context: other (--context)"


def test_a_live_process_is_reused_and_the_line_still_names_the_context_ac_203_2(repo, procs, world, capsys):  # AC-203.2
    p = procs()
    world("lan")
    assert detach(capsys, repo, "--context", "lan")[0] == 0
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    assert len(p.spawned) == 1
    assert lines_after_headless(out) == "context: lan (recorded at the hand-off)"


def test_without_any_context_the_hand_off_starts_and_says_so_ac_203_2(repo, procs, world, capsys):  # AC-203.2
    p = procs()
    world("lan")                                            # a kubeconfig with contexts is no source
    rc, out, err = detach(capsys, repo)
    assert rc == 0, out + err
    assert len(p.spawned) == 1
    assert "CPLAT_KUBE_CONTEXT" not in p.last["env"]
    assert lines_after_headless(out) == NONE_LINE
    st = ship.load_state(repo)
    assert st["context"]["name"] is None


def test_an_unknown_explicit_context_exits_with_one_line_and_starts_nothing_ac_203_2(repo, procs, world, capsys):  # AC-203.2
    p = procs()
    world("lan")
    rc, out, err = detach(capsys, repo, "--context", "nope")
    assert rc != 0
    assert len(err.strip().splitlines()) == 1 and "nope" in err
    assert p.spawned == [] and "headless:" not in out
    assert ship.load_state(repo) is None
