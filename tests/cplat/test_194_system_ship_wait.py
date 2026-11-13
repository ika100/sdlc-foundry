"""Spec 194 acceptance tests: a system ship `next --wait` returns before the Bash limit (AC-194.1 to AC-194.4).

Seams: the system ship world of spec 097 / 143 (`World`, `running`, the scripted clock `tick` whose `script` applies one change per
sleep) and the clone's ship state written with `ship.save_state`. The CLI is called as `appship.main` so that stdout and stderr stay
apart (`--json` keeps stdout to the action). The prompt rule is tested by structure (spec 168): the prompt names the command and the
register entry of source `spec 194` quotes it.
"""
import importlib
import json
import re

import pytest

import appship
import appship_proc
import ship
from prompts186_support import ROOT, collapsed, prompt, sourced
from test_143_shipwait import GITOPS, World, running, tick  # noqa: F401  (fixtures)
from test_155_repo_sessions import running as running_session, started_api
from test_appship_097 import git

T = 60
WAIT_LINE = f"WAIT: repos still running, progress in the last {T}s; run the same wait again"
STATES = {GITOPS: "passed", "shop-lib": "passed", "shop-api": "running", "shop-worker": "passed"}


@pytest.fixture()
def sw(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(ship, "argo_health", lambda *a, **k: "Synced/Healthy")
    return world


def call(sw, capsys, *args):
    """`next ...` as `appship.main`; returns (rc, stdout lines, stderr lines)."""
    capsys.readouterr()
    rc = appship.main(["--repo", str(sw.gitops), "next", *args])
    cap = capsys.readouterr()
    return rc, cap.out.splitlines(), cap.err.splitlines()


def keeps_moving(sw, tick, n=200):
    """A new phase of shop-api at every sleep: progress all through the call."""
    tick.script = [(lambda k=k: running(sw, "shop-api", f"p{k}")) for k in range(1, n)]


# ---------------- AC-194.1: the call ends within T + 10 s ----------------

def test_a_wait_with_constant_progress_ends_at_its_timeout_ac_194_1(sw, tick, capsys):  # AC-194.1
    sw.started(states=STATES)
    running(sw, "shop-api", "p0")
    keeps_moving(sw, tick)
    rc, _, _ = call(sw, capsys, "--wait", "--timeout", str(T))
    assert rc == 0 and T <= tick.slept <= T + 10


def test_the_default_timeout_bounds_the_call_at_550_seconds_ac_194_1(sw, tick, capsys):  # AC-194.1
    sw.started(states=STATES)
    running(sw, "shop-api", "p0")
    keeps_moving(sw, tick)
    rc, _, _ = call(sw, capsys, "--wait")
    assert rc == 0 and 540 <= tick.slept <= 550


def test_a_wait_without_progress_ends_within_its_timeout_plus_ten_ac_194_1(sw, tick, capsys):  # AC-194.1
    sw.started(states=STATES)
    running(sw, "shop-api", "build")
    rc, _, _ = call(sw, capsys, "--wait", "--timeout", str(T))
    assert rc == 2 and T <= tick.slept <= T + 10


def test_a_repo_that_ends_is_recorded_at_the_first_poll_after_its_result_ac_194_1(sw, tick, capsys):  # AC-194.1
    sw.started(states=STATES)
    running(sw, "shop-api", "p0")
    noop = lambda: None  # noqa: E731
    seen = []

    def ends():
        sw.ship_state("shop-api")
        seen.append(tick.slept)
    tick.script = [noop] * 3 + [ends]
    rc, out, _ = call(sw, capsys, "--wait", "--timeout", str(T))
    assert rc == 0 and "action: start" in out and tick.slept == seen[0] == 40      # recorded at the next poll, not at the deadline
    assert sw.state()["repos"]["shop-api"]["state"] == "passed"


# ---------------- AC-194.2: progress, the timeout runs out -> WAIT, exit 0 ----------------

def test_progress_then_timeout_prints_the_wait_action_and_one_wait_line_ac_194_2(sw, tick, capsys):  # AC-194.2
    sw.started(states=STATES)
    running(sw, "shop-api", "p0")
    keeps_moving(sw, tick)
    rc, out, _ = call(sw, capsys, "--wait", "--timeout", str(T))
    assert rc == 0
    assert out[-1] == WAIT_LINE and [ln for ln in out if ln.startswith("WAIT:")] == [WAIT_LINE]
    assert not any(ln.startswith("TIMEOUT:") for ln in out)
    _, nxt, _ = call(sw, capsys)                                       # the wait action as `next` prints it
    assert nxt[0] == "action: wait" and out[-1 - len(nxt):-1] == nxt


def test_with_json_stdout_holds_only_the_wait_action_and_stderr_the_wait_line_ac_194_2(sw, tick, capsys):  # AC-194.2
    sw.started(states=STATES)
    running(sw, "shop-api", "p0")
    keeps_moving(sw, tick)
    rc, out, err = call(sw, capsys, "--wait", "--timeout", str(T), "--json")
    assert rc == 0
    action = json.loads("\n".join(out))                                 # nothing but the JSON
    _, nxt, _ = call(sw, capsys, "--json")
    assert action == json.loads("\n".join(nxt)) and action["action"] == "wait"
    assert err[-1] == WAIT_LINE and [ln for ln in err if ln.startswith("WAIT:")] == [WAIT_LINE]
    assert not any("WAIT:" in ln for ln in out)


def test_the_wait_line_names_the_timeout_as_a_whole_number_ac_194_2(sw, tick, capsys):  # AC-194.2
    sw.started(states=STATES)
    running(sw, "shop-api", "p0")
    keeps_moving(sw, tick)
    rc, out, _ = call(sw, capsys, "--wait", "--timeout", "30.5")
    assert rc == 0 and out[-1] == "WAIT: repos still running, progress in the last 30s; run the same wait again"


@pytest.fixture()
def ws(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(importlib.import_module("preflight"), "check_repo", lambda *a, **k: None)
    monkeypatch.setattr(ship, "argo_health", lambda *a, **k: "Synced/Healthy")
    return world


def test_a_new_commit_in_the_clone_is_progress_ac_194_2(ws, tick, capsys):  # AC-194.2
    started_api(ws)
    running_session(ws, "shop-api", "build")                            # the phase stays the same, only HEAD moves
    tick.script = [lambda: None, lambda: git(ws.clone("shop-api"), "commit", "--allow-empty", "-q", "-m", "work")]
    rc, out, _ = call(ws, capsys, "--wait", "--timeout", str(T))
    assert rc == 0 and out[-1] == WAIT_LINE and T <= tick.slept <= T + 10


def test_a_session_started_again_is_progress_ac_194_2(ws, tick, capsys, monkeypatch):  # AC-194.2 (AC-155.5)
    started_api(ws)
    running_session(ws, "shop-api", "build")
    up = {"alive": True}
    monkeypatch.setattr(appship_proc, "alive", lambda pid: up["alive"])
    tick.script = [lambda: up.update(alive=False), lambda: up.update(alive=True)]   # the session ends once, is started again
    rc, out, err = call(ws, capsys, "--wait", "--timeout", str(T))
    assert "shop-api: ship session started again" in "\n".join(out + err)
    assert rc == 0 and out[-1] == WAIT_LINE and T <= tick.slept <= T + 10


# ---------------- AC-194.3: no progress -> TIMEOUT, exit 2 ----------------

def test_no_progress_for_the_whole_call_keeps_the_timeout_lines_and_exit_2_ac_194_3(sw, tick, capsys):  # AC-194.3
    sw.started(states=STATES)
    running(sw, "shop-api", "build")
    rc, out, err = call(sw, capsys, "--wait", "--timeout", str(T))
    lines = out + err
    first = next(ln for ln in lines if ln.startswith("TIMEOUT:"))
    assert rc == 2 and first == f"TIMEOUT: action still wait, no repo made progress for {T}s; running: shop-api (build)"
    assert lines[lines.index(first) + 1].startswith("run the same")
    assert not any(ln.startswith("WAIT:") for ln in lines)


def test_progress_before_the_end_of_the_call_is_not_a_timeout_ac_194_3(sw, tick, capsys):  # AC-194.3
    sw.started(states=STATES)
    running(sw, "shop-api", "build")
    tick.script = [lambda: running(sw, "shop-api", "verify")]           # one change early in the call, then nothing
    rc, out, err = call(sw, capsys, "--wait", "--timeout", str(T))
    assert rc == 0 and not any(ln.startswith("TIMEOUT:") for ln in out + err)


# ---------------- AC-194.4: the /system:ship prompt and its register entry ----------------

PATH = "plugins/system/commands/ship.md"


def wait_rule():
    text = prompt(PATH)
    start = text.index("`action: wait`")
    return collapsed(text[start:text.index("\n- `action:", start + 1)])


def test_the_system_ship_prompt_runs_a_wait_again_and_escalates_after_three_timeouts_in_a_row_ac_194_4():  # AC-194.4
    rule = wait_rule()
    assert "next --wait" in rule and "TIMEOUT:" in rule and "WAIT:" in rule
    assert re.search(r"three\b.*\bin a row", rule) and "--cause environment" in rule
    assert "at most twice" not in rule                                  # the old counting rule is replaced


def test_the_changed_rule_has_a_register_entry_quoting_the_prompt_ac_194_4():  # AC-194.4
    found = sourced(PATH, "spec 194")
    assert found and all(e["class"] == "practice" for e in found)
    assert any("three" in e["text"] and "TIMEOUT" in e["text"] for e in found)


def test_the_rule_register_checks_and_the_prompt_stays_within_its_size_ac_194_4():  # AC-194.4
    import rulescheck
    assert sourced(PATH, "spec 194")
    result = rulescheck.check(ROOT)
    assert result.ok, [f"{f.file}:{f.line} {f.kind}" for f in result.failures][:5]
