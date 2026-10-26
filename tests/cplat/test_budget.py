"""Spec 102 acceptance tests: one budget per run tree, safe-point stops, no-progress stops, recovery snapshot, verified stages.

The contract is design.md: module `scripts/cplat/budget.py` (`main(argv)`, `root_of`, `check`, `allow_rerun`, `attempt`,
`snapshot`), CLI `cplat budget show|gate|attempt|stage|resume`, `--budget KEY=VALUE` on the root commands, the ledger under
`runs.state_dir()/budgets/`, and the record section `budget`. The module does not exist yet, so `budget` is imported inside
the tests (through the `budget` fixture) and every test fails until the code is there.

Assumptions beyond the design text (kept in one place):
- `budget.main(argv)` runs in the current directory (the tests `chdir` into the repo); `show --json` prints
  `{"limits": {...}, "used": {...}, "root": <run_id>, "key": ...}`, `off` is `null`, an unknown cost is `"unknown"`.
- A limit is used up when used >= limit; `budget.check(run_id, point)` returns the limit name or None;
  `budget.allow_rerun(run_id)` returns a bool; `budget.attempt(...)` returns the stop reason text or None.
- Cost is read through `runs_usage.for_run`, which the tests replace; minutes come from `runs.utcnow` (the `clock` fixture).
- The `resume` text has one line per stage that starts with the stage name and contains `skip` or `run` (+ the reason).
- The recovery snapshot is JSON with the keys `stage`, `excerpt`, `changed_files`, `criteria`, `attempts`.
"""
import json
import os
import stat
import subprocess
import sys

import pytest

import cplat
import core
import headless
import runs
import ship
from test_headless import fake_claude, repo as hl_repo, set_state  # noqa: F401  (fixture)
from test_runs import buffered_lines, clock, drop_tracks, mem, store, stored  # noqa: F401  (fixtures)
from test_appship_097 import w  # noqa: F401  (fixture)
from test_ship import check, git, gh, repo, to_land  # noqa: F401  (fixtures)
from test_ship_checks import gh as checks_gh, running  # noqa: F401  (fixture)

ROOT = core.PLATFORM_ROOT
CPLAT = ROOT / "scripts" / "cplat" / "cplat.py"
DEFAULTS = {"minutes": 180, "invocations": 60, "reruns": 6, "cost": 15}
TOKEN = "ghp_" + "a1B2c3D4e5F6" * 3


@pytest.fixture()
def budget():
    import budget as module
    return module


class Usage:
    """What `runs_usage.for_run` says about the run tree's cost (spec 099): a number, or incomplete."""

    def __init__(self):
        self.cost = 0.0
        self.complete = True


@pytest.fixture()
def usage(monkeypatch):
    import runs_usage
    u = Usage()

    def for_run(rec, *, ended_at=None, **kw):
        totals = {"calls": 1, "failed_calls": 0, "input": 1, "output": 1, "cache_read": 0, "cache_write": 0,
                  "cost_usd": u.cost, "cost_complete": u.complete, "models_without_price": [] if u.complete else ["x"]}
        return {"sessions": ["s"], "price_table": "2026-10-25", "incomplete": None if u.complete else "no price",
                "totals": totals, "by_phase": {}, "by_role": {}, "by_model": {}}

    monkeypatch.setattr(runs_usage, "for_run", for_run)
    return u


def start_ship(repo, *opts):
    assert ship.main(["--repo", str(repo), "start", "7", *opts]) == 0
    return ship.load_state(repo)["run_id"]


def show(budget, capsys):
    capsys.readouterr()
    assert budget.main(["show", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def ledgers():
    d = runs.state_dir() / "budgets"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def ledger():
    (f,) = ledgers()
    return json.loads(f.read_text())


@pytest.fixture()
def here(repo, monkeypatch):
    monkeypatch.chdir(repo)
    return repo


# ---------------- AC-102.1 defaults and options ----------------

def test_a_ship_starts_with_the_default_limits_and_shows_all_four(here, gh, budget, capsys):
    """AC-102.1: without options a ship gets 180 min / 60 invocations / 6 reruns / $15 and the start output lists all four."""
    assert ship.main(["--repo", str(here), "start", "7"]) == 0
    out = capsys.readouterr().out.lower()
    for word, value in (("minutes", "180"), ("invocations", "60"), ("reruns", "6"), ("cost", "15")):
        assert word in out and value in out
    assert show(budget, capsys)["limits"] == DEFAULTS


def test_budget_options_replace_limits_and_off_is_shown_as_off(here, gh, budget, capsys):
    """AC-102.1: `--budget KEY=VALUE` replaces that limit; `cost=off` is not enforced and shown as `off`."""
    assert ship.main(["--repo", str(here), "start", "7", "--budget", "minutes=45", "--budget", "cost=off"]) == 0
    assert "off" in capsys.readouterr().out
    assert show(budget, capsys)["limits"] == {"minutes": 45, "invocations": 60, "reruns": 6, "cost": None}
    assert budget.main(["show"]) == 0
    assert "off" in capsys.readouterr().out


def test_a_cost_limit_that_is_off_never_stops_the_run(here, gh, budget, usage, capsys):
    """AC-102.1: an `off` limit is not enforced, however much is spent."""
    rid = start_ship(here, "--budget", "cost=off")
    usage.cost = 10_000.0
    assert budget.check(rid, "session") is None


def test_a_build_started_by_hand_takes_budget_options(here, budget, capsys):
    """AC-102.1: `cplat runs begin build --budget minutes=45` opens a root budget with that limit."""
    assert runs.main(["begin", "build", "--spec", "007-price-alerts", "--dir", str(here), "--budget", "minutes=45"]) == 0
    assert show(budget, capsys)["limits"]["minutes"] == 45


def test_headless_multiplies_the_ship_defaults_by_the_specs_in_the_prompt(hl_repo, tmp_path, monkeypatch):
    """AC-102.1: `/svc:ship 102 103` is two ships: 360 / 120 / 12 / $30, and a bare `/svc:ship 7` counts as one."""
    drop_tracks(hl_repo)
    fake_claude(tmp_path, monkeypatch, f'"{sys.executable}" "{CPLAT}" budget show --json > shown.json')
    assert headless.main(["/svc:ship 102 103", "--repo", str(hl_repo)]) == 0
    shown = json.loads((hl_repo / "shown.json").read_text())
    assert shown["limits"] == {"minutes": 360, "invocations": 120, "reruns": 12, "cost": 30}


def test_headless_budget_option_applies_after_multiplying(hl_repo, tmp_path, monkeypatch):
    """AC-102.1: `--budget cost=20` on a two-spec headless run replaces the multiplied $30."""
    fake_claude(tmp_path, monkeypatch, f'"{sys.executable}" "{CPLAT}" budget show --json > shown.json')
    assert headless.main(["/svc:ship 102 103", "--repo", str(hl_repo), "--budget", "cost=20"]) == 0
    assert json.loads((hl_repo / "shown.json").read_text())["limits"]["cost"] == 20


# ---------------- AC-102.2 one budget per run tree ----------------

def test_a_ship_under_headless_uses_the_headless_ledger(hl_repo, tmp_path, monkeypatch):
    """AC-102.2: the ship a headless session starts does not open a ledger; `budget show` names the headless run as root."""
    drop_tracks(hl_repo)
    fake_claude(tmp_path, monkeypatch, f'"{sys.executable}" "{CPLAT}" ship --repo . start 7 >/dev/null && '
                                       f'"{sys.executable}" "{CPLAT}" budget show --json > shown.json && '
                                       f'"{sys.executable}" "{CPLAT}" ship --repo . phase done >/dev/null')
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo)]) == 0
    (h,) = [r for r in buffered_lines() if r["kind"] == "headless"]
    shown = json.loads((hl_repo / "shown.json").read_text())
    assert shown["root"] == h["run_id"]
    assert shown["limits"] == DEFAULTS                     # one spec in the prompt: not fresh limits, the root's
    assert len(ledgers()) == 1


def test_a_build_attached_to_a_ship_opens_no_ledger(here, gh, budget, capsys):
    """AC-102.2: `runs begin build` inside a ship run counts against the ship's ledger."""
    rid = start_ship(here)
    assert runs.main(["begin", "build", "--spec", "007-price-alerts", "--dir", str(here)]) == 0
    assert len(ledgers()) == 1 and show(budget, capsys)["root"] == rid


def test_budget_of_a_child_run_is_found_through_its_parent(here, gh, budget, monkeypatch):
    """AC-102.2: `budget.root_of` follows `parent` through the active records up to the run without a parent."""
    root = runs.start("headless", repo="acme/shop-api")
    child = runs.start("ship", repo="acme/shop-api", parent=root)
    grand = runs.start("build", repo="acme/shop-api", parent=child)
    assert budget.root_of(grand) == root and budget.root_of(child) == root and budget.root_of(root) == root


def test_a_product_ship_shares_its_budget_with_the_repo_ships(w, budget, capsys, monkeypatch):
    """AC-102.2 AC-102.1: the product ship's limits are the ship defaults times its repos; a repo ship opens no ledger of its own."""
    from test_appship_097 import REPO_SPEC
    from test_spec import make
    st = w.started()
    (f,) = ledgers()
    data = json.loads(f.read_text())
    n = data["limits"]["minutes"] // 180
    assert data["limits"]["minutes"] == 180 * n and n in (4, 5)
    assert data["limits"] == {"minutes": 180 * n, "invocations": 60 * n, "reruns": 6 * n, "cost": 15 * n}
    clone = w.clone("shop-api")
    make(clone, status="approved")
    assert ship.main(["--repo", str(clone), "start", REPO_SPEC, "--product", str(w.gitops)]) == 0
    assert len(ledgers()) == 1
    monkeypatch.chdir(clone)
    assert show(budget, capsys)["root"] == st["run_id"]


# ---------------- AC-102.3 safe points, nothing is killed ----------------

def test_the_check_returns_the_exhausted_limit(here, gh, budget, clock, usage):
    """AC-102.3: at a safe point `check` is None while within the limits and names the limit once it is used up."""
    rid = start_ship(here, "--budget", "minutes=10")
    assert budget.check(rid, "session") is None
    clock.tick(11 * 60)
    assert budget.check(rid, "session") == "minutes"


def test_cost_over_the_limit_is_the_exhausted_limit(here, gh, budget, usage):
    """AC-102.3: the estimated cost counts against the cost limit."""
    rid = start_ship(here)
    usage.cost = 14.0
    assert budget.check(rid, "session") is None
    usage.cost = 15.5
    assert budget.check(rid, "session") == "cost"


def test_ci_reruns_are_counted_and_refused_when_used_up(here, gh, budget):
    """AC-102.3: `allow_rerun` is asked before a CI rerun; with reruns=1 the second one is refused."""
    rid = start_ship(here, "--budget", "reruns=1")
    assert budget.allow_rerun(rid) is True
    assert budget.allow_rerun(rid) is False


def test_a_refused_ci_rerun_ends_the_wait_red_and_escalates_the_ship(here, checks_gh, budget, store):
    """AC-102.3: `ship land` asks the budget before a rerun; a refusal is a red result `budget exhausted: reruns`, no rerun, cause decision."""
    to_land(here, checks_gh)
    rid = ship.load_state(here)["run_id"]
    assert ship.main(["--repo", str(here), "start", "7", "--budget", "reruns=0"]) == 0
    checks_gh.checks = [[running("quality")]]
    checks_gh.run_status["42"] = ["completed"]
    ok, lines = ship.land(here, timeout=3600, interval=20)
    assert not ok and lines[0] == "budget exhausted: reruns"
    assert not any(c[:2] == ["run", "rerun"] for c in checks_gh.calls)
    st = ship.load_state(here)
    assert st["escalated"] == "budget exhausted: reruns" and st["cause"] == "decision" and st["run_id"] == rid
    (r,) = stored(store)
    assert r["budget"]["limit"] == "reruns" and r["outcome"] == "escalated"


def test_the_gate_hook_exits_2_for_a_subagent_when_the_budget_is_used_up(here, gh, budget, clock, capsys):
    """AC-102.3: `cplat budget gate --invocation` allows a subagent (exit 0) and refuses it (exit 2, reason on stderr) when used up."""
    start_ship(here, "--budget", "minutes=10")
    assert budget.main(["gate", "--invocation"]) == 0
    clock.tick(11 * 60)
    capsys.readouterr()
    assert budget.main(["gate", "--invocation"]) == 2
    assert "budget exhausted: minutes" in capsys.readouterr().err


def test_subagents_count_as_invocations(here, gh, budget, capsys):
    """AC-102.3: each allowed subagent is an invocation; with invocations=3 the gate refuses before a tenth."""
    start_ship(here, "--budget", "invocations=3")
    codes = [budget.main(["gate", "--invocation"]) for _ in range(10)]
    assert set(codes) == {0, 2} and codes.index(2) >= 1 and codes.count(0) <= 3
    assert codes[codes.index(2):] == [2] * (10 - codes.index(2))
    assert "budget exhausted: invocations" in capsys.readouterr().err


def test_the_gate_outside_a_run_allows(budget, capsys):
    """AC-102.3: with no run (no budget) the gate never blocks a subagent."""
    assert budget.main(["gate", "--invocation"]) == 0


def test_the_pre_tool_use_hook_gates_task_and_agent():
    """AC-102.3: the shared plugin registers a PreToolUse hook on Task/Agent that runs `cplat budget gate --invocation`."""
    hooks = json.loads((ROOT / "plugins" / "shared" / "hooks" / "hooks.json").read_text())["hooks"]
    entries = hooks["PreToolUse"]
    matching = [e for e in entries if "Task" in e.get("matcher", "") and "Agent" in e.get("matcher", "")]
    assert matching
    commands = [h["command"] for e in matching for h in e["hooks"]]
    assert any("budget gate --invocation" in c for c in commands)


def test_cplat_knows_budget():
    """AC-102.3: the command is registered and documented."""
    assert cplat.COMMANDS["budget"] == "budget" and "cplat.py budget" in cplat.__doc__


def test_headless_starts_no_session_after_the_budget_is_used_up(hl_repo, tmp_path, monkeypatch, capsys):
    """AC-102.3 AC-102.7: the running session finishes; the next one is not started; stop reason `budget`, outcome escalated, exit 1."""
    ship.start(hl_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "git -c user.name=t -c user.email=t@t commit -q --allow-empty -m step; echo finished >> done.txt")
    rc = headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--max-runs", "5", "--budget", "invocations=1"])
    out = capsys.readouterr().out
    assert rc == 1 and "budget exhausted: invocations" in out
    assert (hl_repo / "runs.txt").read_text().count("run") == 1          # no second session
    assert (hl_repo / "done.txt").read_text() == "finished\n"             # the running one was not killed
    (h,) = [r for r in buffered_lines() if r["kind"] == "headless"]
    assert (h["stop_reason"], h["outcome"]) == ("budget", "escalated")
    assert h["budget"]["limit"] == "invocations"


def test_max_runs_still_stops_headless_under_a_budget(hl_repo, tmp_path, monkeypatch, capsys):
    """AC-102.7: `--max-runs` stays and applies together with the budget; the default budget does not hide it."""
    ship.start(hl_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "git -c user.name=t -c user.email=t@t commit -q --allow-empty -m step")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--max-runs", "2"]) == 1
    assert "stopped after 2 runs" in capsys.readouterr().out
    (h,) = [r for r in buffered_lines() if r["kind"] == "headless"]
    assert h["stop_reason"] == "out of runs" and h["budget"]["limits"] == DEFAULTS


def test_a_budget_result_line_maps_to_the_budget_stop_reason():
    """AC-102.7: `stop_of` maps `budget exhausted: <limit>` to stop reason `budget`, outcome escalated."""
    assert headless.stop_of("budget exhausted: cost", 1) == ("budget", "escalated")
    assert headless.stop_of("needs you: x escalated in phase land: budget exhausted: minutes", 1)[0] == "budget"


# ---------------- AC-102.4 / AC-102.8 the stop and its record ----------------

def test_a_ship_stopped_by_the_budget_is_escalated_with_the_decision_cause(here, gh, budget, clock, usage, store):
    """AC-102.3 AC-102.4: at the end of a phase a used-up budget escalates the ship: reason `budget exhausted: minutes`, cause decision."""
    start_ship(here, "--budget", "minutes=10")
    clock.tick(11 * 60)
    try:
        ship.set_phase(here, "pr")
    except core.PlatformError:
        pass
    st = ship.load_state(here)
    assert st["escalated"] == "budget exhausted: minutes" and st["cause"] == "decision"
    (r,) = stored(store)
    assert r["outcome"] == "escalated" and r["escalation"] == {"reason": "budget exhausted: minutes", "cause": "decision", "cause_source": "given"}


def test_the_record_holds_the_budget_section(here, gh, budget, clock, usage, store):
    """AC-102.4 AC-102.8: the run record has `budget` (limits, used, limit, phase); outcome is not done; mandatory gates are `not run`."""
    start_ship(here, "--budget", "minutes=10")
    usage.cost = 2.5
    clock.tick(11 * 60)
    try:
        ship.set_phase(here, "pr")
    except core.PlatformError:
        pass
    (r,) = stored(store)
    b = r["budget"]
    assert b["limits"] == {"minutes": 10, "invocations": 60, "reruns": 6, "cost": 15}
    assert set(b["used"]) == {"minutes", "invocations", "reruns", "cost"} and b["used"]["minutes"] >= 10 and b["used"]["cost"] == 2.5
    assert b["limit"] == "minutes" and b["phase"]
    assert r["outcome"] != "done"
    assert r["gates"] == {"acceptance": "not run", "security": "not run"}


# ---------------- AC-102.5 unknown cost ----------------

def test_an_incomplete_cost_is_shown_as_unknown_not_zero(here, gh, budget, usage, capsys):
    """AC-102.5: `cost_complete` false: `show` prints `unknown` and the JSON has the string, never 0."""
    start_ship(here)
    usage.complete = False
    assert show(budget, capsys)["used"]["cost"] == "unknown"
    assert budget.main(["show"]) == 0
    assert "unknown" in capsys.readouterr().out


def test_an_unknown_cost_cannot_stop_a_run_but_time_still_does(here, gh, budget, clock, usage):
    """AC-102.5: with an unknown cost the cost limit is not checked; minutes are still enforced."""
    rid = start_ship(here, "--budget", "cost=0.01", "--budget", "minutes=10")
    usage.complete = False
    usage.cost = 99.0
    assert budget.check(rid, "session") is None
    clock.tick(11 * 60)
    assert budget.check(rid, "session") == "minutes"


def test_the_record_of_an_unknown_cost_says_unknown(here, gh, budget, clock, usage, store):
    """AC-102.5: the stop record shows `unknown` for the cost."""
    start_ship(here, "--budget", "minutes=10")
    usage.complete = False
    clock.tick(11 * 60)
    try:
        ship.set_phase(here, "pr")
    except core.PlatformError:
        pass
    (r,) = stored(store)
    assert r["budget"]["used"]["cost"] == "unknown"


# ---------------- AC-102.6 resume continues ----------------

def test_a_resumed_run_continues_usage_and_notes_a_changed_limit(here, gh, budget, clock, usage, store, capsys):
    """AC-102.6: after an escalation the same spec continues the ledger (nothing resets); a new value is the only change, noted in `changes`."""
    start_ship(here)
    for _ in range(3):
        assert budget.main(["gate", "--invocation"]) == 0
    clock.tick(30 * 60)
    before = show(budget, capsys)["used"]
    assert before["minutes"] >= 30 and before["invocations"] >= 3
    ship.escalate(here, "needs a decision", cause="decision")
    start_ship(here)
    after = show(budget, capsys)
    assert after["limits"] == DEFAULTS
    assert after["used"]["minutes"] >= before["minutes"] and after["used"]["invocations"] >= before["invocations"]
    assert len(ledgers()) == 1 and ledger()["changes"] == []
    start_ship(here, "--budget", "cost=40")
    assert show(budget, capsys)["limits"]["cost"] == 40 and len(ledgers()) == 1
    (change,) = ledger()["changes"]
    assert (change["limit"], change["from"], change["to"]) == ("cost", 15, 40) and change["at"]


# ---------------- AC-102.9 no progress ----------------

ERR = "{ts} FAIL TestPriceAlert at {path}/alerts_test.go:{line}: want 3 got 4 (run {hexid})"


def err(i):
    return ERR.format(ts=f"2026-10-25T10:0{i}:00Z", path=f"/tmp/pytest-{i}0/work{i}", line=40 + i, hexid=f"deadbeef{i}{i}c0")


def test_three_equivalent_failures_without_progress_stop_the_run(here, gh, budget):
    """AC-102.9: failures that differ only by timestamp, path, line number and hex id are equivalent; the third stops with `no progress: ci`."""
    start_ship(here)
    assert budget.attempt(here, "ci", err(1), 2) is None
    reason = budget.attempt(here, "ci", err(2), 2)     # boundary corrected per AC-102.9 (2, not 3)
    assert reason and reason.startswith("no progress: ci")
    assert "2" in reason and "FAIL TestPriceAlert" in reason and "want 3 got 4" in reason
    for noise in ("deadbeef", "/tmp/pytest", "alerts_test.go:4", "2026-10-25"):
        assert noise not in reason


def test_progress_starts_the_count_again(here, gh, budget):
    """AC-102.9: fewer failing checks between attempts is progress; the run is not stopped."""
    start_ship(here)
    # boundary corrected per AC-102.9 (2, not 3): every attempt has fewer failures than the one before
    got = [budget.attempt(here, "ci", err(1), 4), budget.attempt(here, "ci", err(2), 3),
           budget.attempt(here, "ci", err(3), 2), budget.attempt(here, "ci", err(4), 1)]
    assert got == [None, None, None, None]


def test_failures_that_are_not_equivalent_do_not_stop_the_run(here, gh, budget):
    """AC-102.9: a different error text (not just noise) is not the same failure."""
    start_ship(here)
    got = [budget.attempt(here, "ci", e, 2) for e in ("FAIL TestA expected 1", "FAIL TestB expected 1", "FAIL TestC expected 1")]
    assert got == [None, None, None]


def test_the_attempt_command_exits_3_and_escalates_with_the_reason(here, gh, budget, capsys):
    """AC-102.9: `cplat budget attempt` exits 0, 0, then 3 with the reason; the ship run is escalated `no progress: <stage>`."""
    start_ship(here)
    capsys.readouterr()
    args = ["attempt", "tests", "--failing", "2", "--names", "TestPriceAlert,TestRate"]
    codes = [budget.main([*args, "--error", err(i)]) for i in (1, 2)]   # boundary corrected per AC-102.9 (2, not 3)
    assert codes == [0, 3]
    assert "no progress: tests" in capsys.readouterr().out + ship.load_state(here)["escalated"]
    assert ship.load_state(here)["escalated"].startswith("no progress: tests")


def test_the_attempt_command_reads_the_error_from_a_file_and_names_progress(here, gh, budget):
    """AC-102.9: `--error-file` works; a smaller `--failing` count between attempts is progress."""
    start_ship(here)
    f = here / "err.txt"
    codes = []
    for n in (4, 3, 2, 1):                 # boundary corrected per AC-102.9 (2, not 3)
        f.write_text(err(n))
        codes.append(budget.main(["attempt", "tests", "--failing", str(n), "--error-file", str(f)]))
    assert codes == [0, 0, 0, 0]


# ---------------- AC-102.10 recovery snapshot ----------------

def snapshot_file(repo):
    return repo / ".git" / "cplat-recovery.json"


def test_the_snapshot_holds_stage_excerpt_files_criteria_and_attempts(here, gh, budget):
    """AC-102.10: stage, redacted excerpt (last 40 lines), changed files, AC ids, earlier attempts; no full log."""
    start_ship(here)
    git(here, "checkout", "-qB", "feature/007-price-alerts")   # setup: `ship start` may already have created it
    (here / "alerts.go").write_text("package alerts\n")
    (here / "alerts_test.go").write_text("// covers AC-007.2\n")
    budget.attempt(here, "ci", err(1), 2)
    budget.attempt(here, "ci", err(2), 2)
    log = "\n".join(f"LOGROW-{i:04d} step" for i in range(100)) + f"\nGH_TOKEN={TOKEN}\nFAIL TestPriceAlert AC-007.1 broke\n"
    budget.snapshot(here, "ci", log, ["AC-007.3"])
    data = json.loads(snapshot_file(here).read_text())
    text = json.dumps(data)
    assert data["stage"] == "ci"
    assert "FAIL TestPriceAlert" in data["excerpt"] and "LOGROW-0099" in data["excerpt"] and "LOGROW-0010" not in text
    assert "alerts.go" in json.dumps(data["changed_files"]) and "alerts_test.go" in json.dumps(data["changed_files"])
    assert {"AC-007.1", "AC-007.3"} <= set(data["criteria"]) and "AC-007.2" in text
    assert "attempts" in data and "2" in json.dumps(data["attempts"]) and "FAIL TestPriceAlert" in json.dumps(data["attempts"])


def test_the_snapshot_redacts_secrets(here, gh, budget):
    """AC-102.10: a token in the failure is redacted as in spec 087."""
    start_ship(here)
    budget.snapshot(here, "ci", f"curl failed\nGH_TOKEN={TOKEN}\nAuthorization: Bearer abcdefghijklmnop1234567890\n", [])
    text = snapshot_file(here).read_text()
    assert TOKEN not in text and "abcdefghijklmnop1234567890" not in text and "<redacted>" in text


def test_an_escalation_writes_a_snapshot_that_never_reaches_the_run_record(here, gh, budget, store):
    """AC-102.10: every `ship.escalate` leaves a local snapshot; the run record in the store holds none of it."""
    start_ship(here)
    ship.escalate(here, "merge conflict in alerts.go", cause="code", evidence=f"CONFLICT alerts.go GH_TOKEN={TOKEN}")
    assert snapshot_file(here).is_file() and TOKEN not in snapshot_file(here).read_text()
    (r,) = stored(store)
    blob = json.dumps(r)
    assert "recovery" not in blob and "CONFLICT alerts.go" not in blob and "excerpt" not in blob
    assert all("recovery" not in p for p in store.files)


# ---------------- AC-102.11 / AC-102.12 verified stages and resume ----------------

def decisions(out):
    got = {}
    for line in out.splitlines():
        word = line.strip().split(":", 1)[0].split(" ", 1)[0].strip()
        if word in ("acceptance", "quality", "tests", "security", "verify", "image", "ci"):
            got[word] = line
    return got


def resume(budget, capsys):
    capsys.readouterr()
    assert budget.main(["resume"]) == 0
    return capsys.readouterr().out


def commit(repo, name="more.txt"):
    (repo / name).write_text(name)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", f"add {name}")


def test_a_passed_stage_on_the_same_head_and_inputs_is_skipped(here, gh, budget, capsys):
    """AC-102.11: only a passed result recorded for the current HEAD and inputs is skipped; stages never recorded run (missing)."""
    start_ship(here)
    assert budget.main(["stage", "acceptance", "passed"]) == 0
    got = decisions(resume(budget, capsys))
    assert "skip" in got["acceptance"] and "skip" not in got["tests"]
    assert "run" in got["tests"] and "missing" in got["tests"]


def test_a_new_commit_makes_a_passed_stage_stale(here, gh, budget, capsys):
    """AC-102.11 AC-102.12: HEAD changed since the pass: the stage runs again (stale)."""
    start_ship(here)
    budget.main(["stage", "acceptance", "passed"])
    commit(here)
    line = decisions(resume(budget, capsys))["acceptance"]
    assert "run" in line and "skip" not in line and "stale" in line


def test_changed_inputs_make_a_passed_stage_run_again(here, gh, budget, capsys):
    """AC-102.11: the working tree changed after the pass (same HEAD): the stage runs again."""
    start_ship(here)
    budget.main(["stage", "tests", "passed"])
    (here / "README.md").write_text("changed after the pass\n")
    line = decisions(resume(budget, capsys))["tests"]
    assert "run" in line and "skip" not in line


def test_a_failed_stage_runs_again(here, gh, budget, capsys):
    """AC-102.12: a failed result is not a pass."""
    start_ship(here)
    budget.main(["stage", "security", "failed"])
    line = decisions(resume(budget, capsys))["security"]
    assert "run" in line and "skip" not in line and "failed" in line


def test_a_skipped_stage_is_never_read_as_a_pass(here, gh, budget, capsys):
    """AC-102.12: a stage recorded as skipped runs again."""
    start_ship(here)
    budget.main(["stage", "quality", "passed"])
    f = ship.state_path(here)
    st = json.loads(f.read_text())
    st["stages"]["quality"]["result"] = "skipped"
    f.write_text(json.dumps(st))
    line = decisions(resume(budget, capsys))["quality"]
    assert "run" in line and "skip" not in line.replace("skipped", "") and "skipped" in line


def test_an_unreadable_stage_result_runs_again(here, gh, budget, capsys):
    """AC-102.12: a malformed stage entry counts as not passed (unreadable); resume does not crash."""
    start_ship(here)
    budget.main(["stage", "verify", "passed"])
    f = ship.state_path(here)
    st = json.loads(f.read_text())
    st["stages"]["verify"] = "garbage"
    f.write_text(json.dumps(st))
    line = decisions(resume(budget, capsys))["verify"]
    assert "run" in line and "skip" not in line and "unreadable" in line


def test_runs_gate_records_a_verified_stage(here, gh, budget, capsys):
    """AC-102.11: `cplat runs gate acceptance passed` records the stage for HEAD + inputs, so resume skips it."""
    start_ship(here)
    runs.main(["begin", "build", "--spec", "007-price-alerts", "--dir", str(here)])
    assert runs.main(["gate", "acceptance", "passed", "--dir", str(here)]) == 0
    assert "skip" in decisions(resume(budget, capsys))["acceptance"]


def test_resume_starts_with_the_snapshot_and_the_failing_stage(here, gh, budget, capsys):
    """AC-102.11: with a recovery snapshot, resume names its stage and excerpt first and runs the failing stage."""
    start_ship(here)
    budget.main(["stage", "acceptance", "passed"])
    budget.snapshot(here, "ci", "step 1\nFAIL TestPriceAlert\nexit status 1\n", ["AC-007.1"])
    out = resume(budget, capsys)
    assert "FAIL TestPriceAlert" in out
    assert out.index("FAIL TestPriceAlert") < out.index(decisions(out)["acceptance"])
    assert "run" in decisions(out)["ci"] and "skip" not in decisions(out)["ci"]
    assert "skip" in decisions(out)["acceptance"]


def test_nothing_is_skipped_without_any_recorded_result(here, gh, budget, capsys):
    """AC-102.12: no stage results at all: every stage runs, none is read as passed."""
    start_ship(here)
    got = decisions(resume(budget, capsys))
    assert set(got) == {"acceptance", "quality", "tests", "security", "verify", "image", "ci"}
    assert all("skip" not in line and "missing" in line for line in got.values())


# ---------------- review fixes ----------------

def snapshot_of(repo):
    return json.loads((repo / ".git" / "cplat-recovery.json").read_text())


def test_a_budget_stopped_ship_restarted_through_headless_continues_the_same_ledger(hl_repo, tmp_path, monkeypatch, clock, usage):
    """AC-102.6 AC-102.7: one ledger key per work: the ship's stop and a later `cplat headless "/svc:ship 7"` share the ledger."""
    assert ship.main(["--repo", str(hl_repo), "start", "7", "--budget", "minutes=10"]) == 0
    clock.tick(11 * 60)
    with pytest.raises(core.PlatformError):
        ship.set_phase(hl_repo, "pr")
    fake_claude(tmp_path, monkeypatch, "true")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo)]) == 1
    assert len(ledgers()) == 1 and ledger()["limits"]["minutes"] == 10 and ledger()["key"].endswith(":007-price-alerts")


def test_headless_and_runs_begin_print_the_limits_at_start(hl_repo, tmp_path, monkeypatch, capsys, budget):
    """AC-102.1: `cplat headless` and `cplat runs begin build` print the same limits line as `ship start`."""
    fake_claude(tmp_path, monkeypatch, "true")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo)]) == 0
    assert "budget: minutes 180, invocations 60, reruns 6, cost $15" in capsys.readouterr().out
    assert runs.main(["begin", "build", "--spec", "007-price-alerts", "--dir", str(hl_repo), "--budget", "minutes=45"]) == 0
    assert "budget: minutes 45," in capsys.readouterr().out


def test_a_headless_budget_stop_is_an_escalation_with_the_decision_cause(hl_repo, tmp_path, monkeypatch):
    """AC-102.4: the headless record of a budget stop has escalation cause decision and the reason."""
    ship.start(hl_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "git -c user.name=t -c user.email=t@t commit -q --allow-empty -m step")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--max-runs", "5", "--budget", "invocations=1"]) == 1
    (h,) = [r for r in buffered_lines() if r["kind"] == "headless"]
    assert h["escalation"] == {"reason": "budget exhausted: invocations", "cause": "decision", "cause_source": "given"}


def test_unreadable_usage_is_an_unknown_cost_never_zero(here, gh, budget, monkeypatch, capsys):
    """AC-102.5: no usage at all (None) or one without totals makes the cost `unknown`."""
    import runs_usage
    start_ship(here)
    for answer in (None, {"sessions": []}, {"totals": None}):
        monkeypatch.setattr(runs_usage, "for_run", lambda rec, answer=answer, **kw: answer)
        assert show(budget, capsys)["used"]["cost"] == "unknown"


def test_runs_end_escalated_writes_a_snapshot(here, gh, budget):
    """AC-102.10: `cplat runs end --outcome escalated` leaves the local recovery snapshot."""
    assert runs.main(["begin", "build", "--spec", "007-price-alerts", "--dir", str(here)]) == 0
    assert runs.main(["end", "--outcome", "escalated", "--reason", "need a human", "--cause", "decision", "--dir", str(here)]) == 0
    assert "need a human" in snapshot_of(here)["excerpt"]


def test_an_app_ship_escalation_writes_a_snapshot(w, budget):
    """AC-102.10: `cplat app-ship escalate` leaves the recovery snapshot in the gitops-app clone."""
    w.started()
    assert w.app("escalate", "a repo spec asks a question", "--cause", "decision").rc == 0
    assert "a repo spec asks a question" in snapshot_of(w.gitops)["excerpt"]


def test_headless_stops_write_a_snapshot(hl_repo, tmp_path, monkeypatch):
    """AC-102.10: budget, max-runs, max-minutes and no-progress stops of headless each leave the snapshot."""
    gitdir = hl_repo / ".git" / "cplat-recovery.json"
    fake_claude(tmp_path, monkeypatch, "true")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--budget", "invocations=0"]) == 1
    assert "budget exhausted: invocations" in snapshot_of(hl_repo)["excerpt"]
    gitdir.unlink()
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--max-minutes", "1"]) == 1
    assert "time budget" in snapshot_of(hl_repo)["excerpt"]
    gitdir.unlink()
    ship.start(hl_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "git -c user.name=t -c user.email=t@t commit -q --allow-empty -m step")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--max-runs", "1", "--budget", "invocations=60"]) == 1
    assert "stopped after 1 runs" in snapshot_of(hl_repo)["excerpt"]
    gitdir.unlink()
    fake_claude(tmp_path, monkeypatch, "true")
    assert headless.main(["/svc:ship 7", "--repo", str(hl_repo), "--budget", "invocations=60"]) == 1
    assert "no progress" in snapshot_of(hl_repo)["excerpt"]


def test_the_hook_blocks_only_on_a_real_refusal(tmp_path):
    """AC-102.3: a gate that exits 2 without `budget exhausted`, or fails any other way, does not block a subagent."""
    cmd = json.loads((ROOT / "plugins" / "shared" / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    (tmp_path / "bin").mkdir()

    def hook(body):
        f = tmp_path / "bin" / "cplat"
        f.write_text("#!/bin/sh\n" + body + "\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(tmp_path), "CPLAT_RUN_PARENT": "x"}
        return subprocess.run(["bash", "-c", cmd], env=env, cwd=tmp_path, capture_output=True, text=True)
    assert hook("echo 'usage: cplat budget' >&2; exit 2").returncode == 0
    assert hook("exit 1").returncode == 0
    refused = hook("echo 'budget exhausted: minutes' >&2; exit 2")
    assert refused.returncode == 2 and "budget exhausted: minutes" in refused.stderr


def test_idle_time_between_a_stop_and_the_resume_is_not_counted(here, gh, budget, clock, usage):
    """AC-102.6: the minutes used up to the stop are carried; the clock restarts at the resume."""
    rid = start_ship(here)
    key = budget.find(rid)[1]["key"]
    clock.tick(30 * 60)
    budget.stop(rid, "minutes", "phase end", "build")
    clock.tick(600 * 60)
    new = runs.start("ship", repo="x")
    budget.open_root(new, key)
    assert 30 <= budget.used_of(budget.find(new)[1], cost=False)["minutes"] < 31


def test_durations_do_not_make_failures_differ(budget):
    """AC-102.9: `in 3.21s` and `in 4.07s` are the same pytest summary."""
    assert budget.normalise("== 1 failed, 5 passed in 3.21s ==") == budget.normalise("== 1 failed, 5 passed in 4.07s ==")
    assert budget.normalise("took 15ms") == budget.normalise("took 230 ms")
