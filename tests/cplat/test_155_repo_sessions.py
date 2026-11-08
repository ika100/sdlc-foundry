"""Spec 155 acceptance tests: each component repo of a system ship runs in its own headless session.

Seams: the system ship world of spec 097 (`test_appship_097.World`: real git on a local bare origin, fake `gh`); the session
process is `appship_proc.spawn` / `appship_proc.alive` (the conftest records spawns and reports them running; tests here
replace `alive`), the clock of `next --wait` is `test_143_shipwait.Clock`.
"""
import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import appship_proc
import appship_sched
import appship_state
import runs
import ship
import spec as specmod
from test_143_shipwait import Clock
from test_appship_097 import GITOPS, SLUG, SPEC, World, git

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(importlib.import_module("preflight"), "check_repo", lambda *a, **k: None)
    monkeypatch.setattr(ship, "argo_health", lambda *a, **k: "Synced/Healthy")
    return world


@pytest.fixture()
def tick(monkeypatch):
    return Clock(monkeypatch)


def plan(w, repos, **started):
    w.set_plan(repos)
    return w.started(**started)


def repo_spec(w, rid):
    want = f"{SLUG}:{SPEC}"
    return next(s for s in specmod.scan(w.clone(rid))[0] if s.meta.get("parent") == want)


DIAMOND = [
    (GITOPS, "gitops-app", [], ["AC-012.1"], False),
    ("shop-api", "service-python", [], ["AC-012.1"], False),
    ("shop-lib", "service-python", ["shop-api"], ["AC-012.3"], False),
    ("shop-web", "web-nextjs", ["shop-api"], ["AC-012.2"], False),
    ("shop-worker", "service-python", ["shop-lib", "shop-web"], ["AC-012.1"], False),
]


# ---------------- AC-155.1: cplat writes the repo spec and starts the repo's own session ----------------

def test_repo_start_writes_and_approves_the_repo_spec_from_the_plan_ac_155_1(w):  # AC-155.1
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    r = w.app("repo", "start", "shop-api")
    assert r.rc == 0, r.out
    sp = repo_spec(w, "shop-api")
    assert sp.status == "approved"
    assert "(system AC-012.1)" in sp.body
    clone = w.clone("shop-api")
    assert git(clone, "branch", "--show-current") == f"feature/{sp.id}"
    assert git(clone, "status", "--porcelain") == ""                      # committed: a resume is not refused
    assert git(clone, "log", "-1", "--format=%s") == f"docs(spec): {sp.id} from the system plan of {SPEC}"


def test_repo_start_starts_the_repos_headless_ship_and_keeps_its_process_ac_155_1(w):  # AC-155.1
    st = w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    r = w.app("repo", "start", "shop-api")
    sp = repo_spec(w, "shop-api")
    assert appship_proc.SPAWNED == [(str(w.clone("shop-api").absolute()), sp.id, str(w.gitops), st["run_id"], 1)]
    e = w.state()["repos"]["shop-api"]
    assert e["spec"] == sp.id and e["proc"]["pid"] == 4242 and e["proc"]["starts"] == 1
    assert "shop-api: ship session started (pid 4242, log " in r.out and "next: cplat system ship next --wait" in r.out


def test_a_resumed_repo_reuses_its_repo_spec_ac_155_1(w):  # AC-155.1
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    w.app("repo", "start", "shop-api")
    first = repo_spec(w, "shop-api").id
    w.edit(lambda st: st["repos"]["shop-api"].update(state="ready"))
    assert w.app("repo", "start", "shop-api").rc == 0
    assert [s.id for s in specmod.scan(w.clone("shop-api"))[0]] == [first]
    assert [s[1] for s in appship_proc.SPAWNED] == [first, first]


def test_the_gitops_entry_gets_no_session_ac_155_1(w):  # AC-155.1
    w.started()
    assert w.app("repo", "start", GITOPS).rc == 0
    assert appship_proc.SPAWNED == []


def test_a_plan_without_repo_criteria_escalates_with_the_replan_hint_ac_155_1(w):  # AC-155.1
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    r = w.app("repo", "start", "shop-worker")                             # acs [] in the default plan: no criteria
    assert r.rc == 1 and "re-plan it with /system:plan" in r.out
    e = w.state()["repos"]["shop-worker"]
    assert e["state"] == "escalated" and e["cause"] == "decision"
    assert appship_proc.SPAWNED == []


def test_a_session_that_cannot_start_escalates_the_repo_ac_155_1(w, monkeypatch):  # AC-155.1
    def broken(*a, **kw):
        raise OSError("no such file: cplat.py")
    monkeypatch.setattr(appship_proc, "spawn", broken)
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    r = w.app("repo", "start", "shop-api")
    assert r.rc == 1 and "could not start" in r.out
    assert w.state()["repos"]["shop-api"]["cause"] == "environment"


# ---------------- AC-155.2 / AC-155.9: independent repos at once, order kept, any shape of plan ----------------

def starts(w):
    return [s["id"] for s in w.app("next", "--json").json["start"]]


def test_independent_repos_start_together_up_to_max_ac_155_2(w):  # AC-155.2
    plan(w, DIAMOND, states={GITOPS: "passed", "shop-api": "passed"})
    assert sorted(starts(w)) == ["shop-lib", "shop-web"]
    for rid in starts(w):
        assert w.app("repo", "start", rid).rc == 0
    assert sorted(s[0].rsplit("/", 1)[-1] for s in appship_proc.SPAWNED) == ["shop-lib", "shop-web"]   # both before either ends


def test_max_1_runs_the_repos_one_at_a_time_ac_155_9(w):  # AC-155.9
    w.set_plan(DIAMOND)
    assert w.app("start", SPEC, "--context", "kind-shop", "--max", "1").rc == 0
    w.edit(lambda st: [st["repos"][r].update(state="passed") for r in (GITOPS, "shop-api")])
    assert len(starts(w)) == 1


def test_a_diamond_runs_its_levels_in_order_ac_155_9(w):  # AC-155.9
    plan(w, DIAMOND, states={GITOPS: "passed"})
    assert starts(w) == ["shop-api"]
    w.edit(lambda st: st["repos"]["shop-api"].update(state="passed"))
    assert sorted(starts(w)) == ["shop-lib", "shop-web"]
    w.edit(lambda st: st["repos"]["shop-lib"].update(state="passed"))
    assert starts(w) == ["shop-web"]                                       # shop-worker still waits for shop-web
    w.edit(lambda st: st["repos"]["shop-web"].update(state="passed"))
    assert starts(w) == ["shop-worker"]


def test_one_repo_alone_ships_in_its_own_session_ac_155_9(w):  # AC-155.9
    plan(w, [("shop-api", "service-python", [], ["AC-012.1"], False)])
    assert starts(w) == ["shop-api"]
    assert w.app("repo", "start", "shop-api").rc == 0
    assert len(appship_proc.SPAWNED) == 1


# ---------------- AC-155.3: the same ship as a standalone /component:ship ----------------

def test_the_session_runs_the_standalone_component_ship_command_ac_155_3(monkeypatch):  # AC-155.3
    monkeypatch.delenv("CPLAT_PLUGIN_DIRS", raising=False)
    assert appship_proc.command("003-labels") == [sys.executable, str(appship_proc.CPLAT), "headless", "/component:ship 003-labels"]
    monkeypatch.setenv("CPLAT_PLUGIN_DIRS", os.pathsep.join(["/p/system", "/p/component"]))
    assert appship_proc.command("003-labels")[3:] == ["--plugin-dir", "/p/system", "--plugin-dir", "/p/component", "/component:ship 003-labels"]


def test_the_component_ship_links_itself_from_the_environment_ac_155_3(w, monkeypatch):  # AC-155.3
    st = w.started()
    clone = w.clone("shop-api")
    from test_spec import make
    make(clone, status="approved")
    monkeypatch.setenv("CPLAT_SYSTEM_DIR", str(w.gitops))
    assert ship.main(["--repo", str(clone), "start", "007-price-alerts"]) == 0
    assert ship.load_state(clone)["product"]["run_id"] == st["run_id"]


def test_headless_hands_its_plugin_folders_to_the_repo_sessions_ac_155_3():  # AC-155.3
    text = (ROOT / "scripts" / "cplat" / "headless.py").read_text()
    assert 'os.environ["CPLAT_PLUGIN_DIRS"] = os.pathsep.join(dirs)' in text


def test_the_real_spawn_links_the_session_and_detaches_it_ac_155_3_ac_155_7(tmp_path, monkeypatch):  # AC-155.3, AC-155.7
    seen = {}

    class P:
        pid = 777

    def popen(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return P()
    monkeypatch.setattr(appship_proc.subprocess, "Popen", popen)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    clone = tmp_path / "shop-api"
    clone.mkdir()
    proc = appship_proc.REAL_SPAWN(clone, "003-x", tmp_path / "shop-gitops", "run-1")
    assert proc["pid"] == 777 and proc["starts"] == 1 and Path(proc["log"]).parent.is_dir()
    assert seen["cwd"] == clone and seen["start_new_session"] is True and seen["stdin"] == subprocess.DEVNULL
    assert seen["env"]["CPLAT_SYSTEM_DIR"] == str(tmp_path / "shop-gitops") and seen["env"]["CPLAT_RUN_PARENT"] == "run-1"
    assert seen["cmd"][-1] == "/component:ship 003-x"


def test_alive_is_false_for_a_finished_child_and_true_for_a_running_headless_ac_155_5(tmp_path):  # AC-155.5
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    time.sleep(0.3)
    assert appship_proc.REAL_ALIVE(done.pid) is False
    script = tmp_path / "headless"
    script.write_text("import time\ntime.sleep(5)\n")
    live = subprocess.Popen([sys.executable, str(script)])
    try:
        assert appship_proc.REAL_ALIVE(live.pid) is True
    finally:
        live.kill()
        live.wait()
    assert appship_proc.REAL_ALIVE(None) is False


# ---------------- AC-155.4 / AC-155.5 / AC-155.6: the wait ----------------

def running(w, rid, phase, **kw):
    ship.save_state(w.clone(rid), {"spec": repo_spec(w, rid).id, "phase": phase, "recorded": True, "run_id": f"r-{rid}", **kw})


def started_api(w):
    w.started(states={"shop-gitops": "passed", "shop-lib": "passed"})
    assert w.app("repo", "start", "shop-api").rc == 0


def test_a_session_that_ended_before_its_ship_is_started_once_more_then_escalates_ac_155_5(w, tick, monkeypatch):  # AC-155.5
    started_api(w)
    running(w, "shop-api", "build")
    monkeypatch.setattr(appship_proc, "alive", lambda pid: False)
    r = w.app("next", "--wait", "--timeout", "60")
    assert "shop-api: ship session started again" in r.out
    assert appship_proc.SPAWNED[-1][-1] == 2
    e = w.state()["repos"]["shop-api"]
    assert e["state"] == "escalated" and e["cause"] == "environment"
    assert "ended 2 times before its ship finished; see " in e["reason"] and e["proc"]["log"] in e["reason"]


def test_a_running_session_is_left_alone_while_its_ship_works_ac_155_5(w, tick):  # AC-155.5
    started_api(w)
    running(w, "shop-api", "build")
    r = w.app("next", "--wait", "--timeout", "60")
    assert r.rc == 2 and len(appship_proc.SPAWNED) == 1                  # TIMEOUT, no restart


def test_a_running_repo_without_a_session_gets_one_ac_155_5(w, tick):  # AC-155.5 (a run from before spec 155, resumed)
    started_api(w)
    w.edit(lambda st: st["repos"]["shop-api"].pop("proc"))
    running(w, "shop-api", "build")
    r = w.app("next", "--wait", "--timeout", "60")
    assert "shop-api: ship session started (pid 4242" in r.out


def test_a_finished_ship_is_recorded_whether_or_not_its_session_still_runs_ac_155_4(w, tick, monkeypatch):  # AC-155.4
    started_api(w)
    monkeypatch.setattr(appship_proc, "alive", lambda pid: False)
    sid = repo_spec(w, "shop-api").id
    w.ship_state("shop-api")
    st = ship.load_state(w.clone("shop-api"))
    st["spec"] = sid
    ship.save_state(w.clone("shop-api"), st)
    w.app("next", "--wait", "--timeout", "60")
    assert w.state()["repos"]["shop-api"]["state"] in appship_state.PASSED or w.state()["repos"]["shop-api"]["state"] == "escalated"
    assert len(appship_proc.SPAWNED) == 1                                 # a finished ship is never restarted


def test_an_escalated_repo_ship_escalates_the_repo_with_its_reason_ac_155_6(w, tick):  # AC-155.6
    started_api(w)
    running(w, "shop-api", "land", escalated="CI red after 2 rounds", cause="code")
    w.app("next", "--wait", "--timeout", "60")
    e = w.state()["repos"]["shop-api"]
    assert e["state"] == "escalated" and e["reason"] == "CI red after 2 rounds" and e["cause"] == "code"


def test_a_commit_in_a_running_repo_is_progress_for_the_stop_gate_ac_155_4(w):  # AC-155.4
    started_api(w)
    st = w.state()
    running(w, "shop-api", "build")
    before = appship_state._mark(w.gitops, st)
    clone = w.clone("shop-api")
    (clone / "x.py").write_text("x = 1\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "feat: x")
    assert appship_state._mark(w.gitops, st) != before
    running(w, "shop-api", "pr")
    assert appship_state._mark(w.gitops, st)["phase"].count("running pr") == 1


def test_a_linked_finished_ship_is_left_for_the_system_ship_to_archive_ac_155_4(w, capsys):  # AC-155.4
    started_api(w)
    running(w, "shop-api", "done", product={"dir": str(w.gitops), "run_id": "r"})
    capsys.readouterr()
    assert ship.main(["--repo", str(w.clone("shop-api")), "finish"]) == 0
    assert "belongs to the system ship" in capsys.readouterr().out
    assert ship.load_state(w.clone("shop-api")) is not None


# ---------------- AC-155.7: one budget, each token once ----------------

def test_the_repo_session_is_a_child_of_the_system_ship_run_ac_155_7(w, monkeypatch):  # AC-155.7
    started_api(w)
    parent = w.state()["run_id"]
    assert appship_proc.SPAWNED[0][3] == parent
    monkeypatch.setenv("CPLAT_RUN_PARENT", parent)
    import budget
    child = runs.start("headless", repo="acme/shop-api", mode="headless")
    assert runs.active(child)["parent"] == parent
    assert budget.root_of(child) == budget.root_of(parent)                # the system ship's ledger, not a new one


# ---------------- AC-155.8: merges stay one at a time ----------------

def test_the_merge_slot_is_untouched_ac_155_8():  # AC-155.8
    text = (ROOT / "scripts" / "cplat" / "appship_proc.py").read_text()
    assert "merge" not in text.lower().replace("merges", "")


# ---------------- AC-155.10: one path, documented ----------------

def test_the_command_file_has_no_subagent_per_repo_path_ac_155_10():  # AC-155.10
    text = (ROOT / "plugins" / "system" / "commands" / "ship.md").read_text()
    assert "one foreground subagent per repo" not in text
    assert "in its own session" in text and "spec 155" in text


def test_the_process_model_is_documented_with_an_adr_ac_155_10():  # AC-155.10
    agents = (ROOT / "docs" / "AGENTS.md").read_text()
    assert "spec 155" in agents
    adrs = list((ROOT / "docs" / "adr").glob("*-a-system-ships-repos-run-in-their-own-sessions.md"))
    assert adrs and "subagent" in adrs[0].read_text()


# ---------------- found by the first benchmark run: a finished repo session archived its ship ----------------

def test_a_ship_archived_by_its_own_session_is_still_recorded_ac_155_4(w, tick, monkeypatch):  # AC-155.4
    started_api(w)
    monkeypatch.setattr(appship_proc, "alive", lambda pid: False)
    sid = repo_spec(w, "shop-api").id
    w.ship_state("shop-api")
    st = ship.load_state(w.clone("shop-api"))
    st["spec"] = sid
    ship.save_state(w.clone("shop-api"), st)
    ship.finish(w.clone("shop-api"))                                      # what the supervisor did before the fix
    w.app("next", "--wait", "--timeout", "60")
    e = w.state()["repos"]["shop-api"]
    assert e["state"] == "passed" and e["spec"] == sid
    assert len(appship_proc.SPAWNED) == 1                                 # not started again


def test_the_supervisor_leaves_a_linked_ship_for_the_system_ship_ac_155_4():  # AC-155.4
    text = (ROOT / "scripts" / "cplat" / "supervisor.py").read_text()
    assert 'if st is not None and not st.get("product"):' in text


def test_result_leaves_the_ship_state_while_the_repos_session_still_runs_ac_155_6(w, tick):  # AC-155.6 (found by the benchmark)
    started_api(w)                                                        # the conftest reports the session as running
    running(w, "shop-api", "build", escalated="the acceptance test can never pass", cause="decision")
    w.app("next", "--wait", "--timeout", "60")
    assert w.state()["repos"]["shop-api"]["state"] == "escalated"
    assert ship.load_state(w.clone("shop-api")) is not None              # its supervisor still reads it


def test_result_archives_the_ship_once_the_session_has_ended_ac_155_6(w, tick, monkeypatch):  # AC-155.6
    started_api(w)
    monkeypatch.setattr(appship_proc, "alive", lambda pid: False)
    running(w, "shop-api", "build", escalated="the acceptance test can never pass", cause="decision")
    w.app("next", "--wait", "--timeout", "60")
    assert w.state()["repos"]["shop-api"]["state"] == "escalated"
    assert ship.load_state(w.clone("shop-api")) is None


def test_testers_assert_on_parsed_values_not_serialized_text():  # found by the benchmark
    for plugin in ("svc", "web", "svc-go", "svc-java"):
        text = (ROOT / "plugins" / plugin / "agents" / "tester.md").read_text()
        assert "Assert on parsed values, never on serialized text" in text, plugin
