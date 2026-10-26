"""Spec 088: `cplat ship escalate` files platform failures, the crash hook of `cplat.main`, and `runs.current`."""
import json

import pytest

import cplat
import core
import runs
import ship
from test_autoissue import PLATFORM_REPO, SIG_LINE, TOKEN, Clock, FakeTracker, boom, clk, tr, ai  # noqa: F401  (fixtures)
from test_runs import MemStore, attach, followups, stored  # noqa: F401  (helpers)
from test_runs import clock as run_clock, mem, store  # noqa: F401  (fixtures)
from test_ship import git, repo  # noqa: F401  (fixtures)

ALLOWED = ("platform", "code", "decision", "environment")


def escalate(repo, *args):
    return ship.main(["--repo", str(repo), "escalate", *args])


def started(repo):
    ship.start(repo, "7", True)
    return repo


# ---------------- AC-088.1 platform escalation files ----------------

def test_a_platform_escalation_files_one_issue_and_prints_its_url(repo, tr, capsys):
    """AC-088.1: exactly one new issue; the output has `<url> new` and no /shared:report-issue offer."""
    started(repo)
    assert escalate(repo, "copier render fails on the Dockerfile", "--cause", "platform") == 0
    out = capsys.readouterr().out
    assert len(tr.created()) == 1 and not tr.commented()
    ((_, target, title, body, labels),) = tr.created()
    assert target == PLATFORM_REPO and title == "[auto] copier render fails on the Dockerfile" and "auto-filed" in labels
    assert f"issue: https://github.com/{PLATFORM_REPO}/issues/1 new" in out.splitlines()
    assert "/shared:report-issue" not in out and "escalated (copier render fails on the Dockerfile)" in out
    assert len(SIG_LINE.findall(body)) == 1


def test_the_same_platform_failure_again_is_a_plus_one(repo, tr, capsys):
    """AC-088.1 AC-088.7: the second escalation adds one comment and prints `<issue url> +1`."""
    for _ in range(2):
        started(repo)
        assert escalate(repo, "copier render fails on the Dockerfile", "--cause", "platform") == 0
    out = capsys.readouterr().out
    assert len(tr.created()) == 1 and len(tr.commented()) == 1 and "Occurrence 2" in tr.commented()[0][3]
    assert f"issue: https://github.com/{PLATFORM_REPO}/issues/1 +1" in out.splitlines()


def test_the_reason_command_and_phase_make_the_signature(repo, tr):
    """AC-088.1 AC-088.5: the same reason with another command or phase is another issue; volatile parts are not."""
    started(repo)
    escalate(repo, "render fails after 12s on PR #5", "--cause", "platform", "--command", "cplat new-service")
    started(repo)
    escalate(repo, "render fails after 90s on PR #8", "--cause", "platform", "--command", "cplat new-service")
    started(repo)
    escalate(repo, "render fails after 90s on PR #8", "--cause", "platform", "--command", "cplat update-service")
    assert len(tr.created()) == 2 and len(tr.commented()) == 1
    assert "- command: `cplat new-service`" in tr.created()[0][3]


def test_the_escalate_options_carry_command_and_evidence(repo, tr, tmp_path):
    """AC-088.1 AC-088.10: --command and --evidence-file (and `-` for stdin) end up in the issue."""
    started(repo)
    log = tmp_path / "log.txt"
    log.write_text("step 1\nFAIL TestPriceAlert\n")
    escalate(repo, "gate fails", "--cause", "platform", "--command", "devbox run ci", "--evidence-file", str(log))
    body = tr.created()[0][3]
    assert "- command: `devbox run ci`" in body and "FAIL TestPriceAlert" in body and "- phase: `plan`" in body or "- phase:" in body
    started(repo)
    escalate(repo, "gate fails differently", "--cause", "platform", "--evidence-file", str(tmp_path / "missing.txt"))
    assert "(none)" in tr.created()[1][3] and "- command: `/svc:ship`" in tr.created()[1][3]


def test_stdin_is_read_for_evidence_dash(repo, tr, monkeypatch):
    """AC-088.1: `--evidence-file -` reads stdin."""
    import io
    started(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin: boom\n"))
    escalate(repo, "gate fails", "--cause", "platform", "--evidence-file", "-")
    assert "from stdin: boom" in tr.created()[0][3]


def test_the_filing_is_part_of_the_escalated_record(repo, tr, store):
    """AC-088.1 AC-088.11: the escalated run record carries cause platform, the reason and the filed entry."""
    started(repo)
    escalate(repo, "copier render fails", "--cause", "platform")
    (r,) = stored(store)
    assert r["outcome"] == "escalated" and r["escalation"] == {"reason": "copier render fails", "cause": "platform", "cause_source": "given"}
    (f,) = r["filed"]
    assert f["result"] == "new" and f["url"] == f"https://github.com/{PLATFORM_REPO}/issues/1" and f["signature"].startswith("platform:")
    assert r["run_id"] in tr.created()[0][3]


def test_the_stop_gate_names_the_cause_flag(repo, capsys):
    """AC-088.1: the gate's escalate hint tells the orchestrator to state the cause."""
    started(repo)
    res = ship.gate(repo, {}, 3, run_tests=False)
    assert res["decision"] == "block" and "--cause <platform|code|decision|environment>" in res["reason"]


# ---------------- AC-088.2 other causes file nothing ----------------

@pytest.mark.parametrize("cause", ["code", "decision", "environment"])
def test_other_causes_are_only_recorded(repo, tr, store, capsys, cause):
    """AC-088.2: nothing is filed anywhere; the run record carries cause and reason."""
    started(repo)
    assert escalate(repo, "needs the user", "--cause", cause) == 0
    out = capsys.readouterr().out
    assert tr.calls == [] and "issue:" not in out and "report-issue" not in out
    (r,) = stored(store)
    assert r["escalation"] == {"reason": "needs the user", "cause": cause, "cause_source": "given"} and r["filed"] == []


# ---------------- AC-088.3 missing or unknown cause ----------------

def test_a_missing_cause_is_unknown_and_the_output_lists_the_allowed_ones(repo, tr, store, capsys):
    """AC-088.3: no `--cause`: unknown, nothing filed, message says missing and lists platform, code, decision, environment."""
    started(repo)
    assert escalate(repo, "why") == 0
    out = capsys.readouterr().out
    assert tr.calls == [] and "missing" in out and all(c in out for c in ALLOWED)
    (r,) = stored(store)
    assert r["escalation"] == {"reason": "why", "cause": "unknown", "cause_source": "none"} and r["filed"] == []


@pytest.mark.parametrize("value", ["bogus", "unknown", "Platform "])
def test_an_unknown_cause_is_unknown_and_not_an_argparse_error(repo, tr, store, capsys, value):
    """AC-088.3: any other value is stored as unknown with the same list; the exit status is 0."""
    started(repo)
    assert escalate(repo, "why", "--cause", value) == 0
    out = capsys.readouterr().out
    assert tr.calls == [] and all(c in out for c in ALLOWED) and ship.load_state(repo)["cause"] == "unknown"
    (r,) = stored(store)
    assert r["escalation"]["cause"] == "unknown"


def test_escalate_in_python_coerces_the_cause(repo, tr):
    """AC-088.3: `escalate(repo, reason, cause=None)` and a bad cause both store unknown; report gets the message."""
    started(repo)
    report = []
    assert ship.escalate(repo, "why", None, report=report)["cause"] == "unknown"
    assert any("missing" in ln for ln in report) and ship.ESCALATION_CAUSES == ALLOWED
    started(repo)
    assert ship.escalate(repo, "why", "nonsense")["cause"] == "unknown" and tr.calls == []


# ---------------- AC-088.9 / .11 / .12 / .13 / .14 through the escalation ----------------

def test_the_consumer_repo_spec_and_branch_never_reach_the_issue(repo, tr, store, capsys):
    """AC-088.9: repo acme/shop-api, spec 007-price-alerts and branch feature/007-price-alerts become placeholders."""
    started(repo)
    reason = f"render of acme/shop-api for 007-price-alerts on feature/007-price-alerts fails {TOKEN}"
    escalate(repo, reason, "--cause", "platform", "--command", "cplat ship pr --spec 007-price-alerts")
    ((_, _r, title, body, _l),) = tr.created()
    for leak in ("acme/shop-api", "007-price-alerts", "feature/007", TOKEN):
        assert leak not in title + body, leak
    assert "<repo>" in title and "<spec>" in title and "<branch>" in title
    assert "acme/shop-api" not in capsys.readouterr().out.split("issue:")[0].replace("ship 007-price-alerts", "")


def test_the_same_failure_in_two_repos_is_one_issue(repo, tr, tmp_path):
    """AC-088.9 AC-088.5: repo, spec and branch names are not part of the signature."""
    started(repo)
    escalate(repo, "render of acme/shop-api for 007-price-alerts fails", "--cause", "platform")
    ai_sig = tr.created()[0][3]
    assert "Signature: platform:" in ai_sig
    started(repo)
    escalate(repo, "render of acme/billing for 031-invoices fails", "--cause", "platform")
    assert len(tr.created()) == 1 and len(tr.commented()) == 1


def test_a_failing_filing_does_not_change_the_escalation(repo, tr, store, capsys, ai):
    """AC-088.12: same exit status, `not filed: <reason>` in the output, the escalation recorded, the filing pending."""
    tr.error = ai.TrackerError("gh is not logged in")
    started(repo)
    assert escalate(repo, "copier render fails", "--cause", "platform") == 0
    out = capsys.readouterr().out
    assert "escalated (copier render fails)" in out and "not filed: gh is not logged in" in out
    (r,) = stored(store)
    assert r["outcome"] == "escalated" and r["filed"][0]["result"] == "pending" and runs.pending_count() == 1
    assert ship.load_state(repo)["cause"] == "platform"


def test_a_crashing_tracker_module_cannot_stop_an_escalation(repo, monkeypatch, capsys, ai):
    """AC-088.12: even an unexpected exception inside filing leaves exit status 0."""
    monkeypatch.setattr(ai, "tracker", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    started(repo)
    assert escalate(repo, "copier render fails", "--cause", "platform") == 0
    assert "escalated" in capsys.readouterr().out


def test_the_pending_escalation_filing_is_flushed_later(repo, tr, store, ai):
    """AC-088.12: a flush after the network is back files it, with the run id in the issue."""
    tr.error = ai.TrackerError("no network")
    started(repo)
    escalate(repo, "copier render fails", "--cause", "platform")
    rid = stored(store)[0]["run_id"]
    tr.error = None
    runs.flush()
    assert len(tr.created()) == 1 and rid in tr.created()[0][3] and followups(store)[0]["result"] == "new"


def test_off_prints_the_draft_and_the_hint_for_an_escalation(repo, tr, store, capsys, monkeypatch):
    """AC-088.13: CPLAT_AUTO_ISSUES=off: nothing sent; the draft and the /shared:report-issue hint are printed."""
    monkeypatch.setenv("CPLAT_AUTO_ISSUES", "off")
    started(repo)
    assert escalate(repo, "copier render fails", "--cause", "platform") == 0
    out = capsys.readouterr().out
    assert tr.calls == [] and "Draft issue for" in out and "[auto] copier render fails" in out and "/shared:report-issue" in out
    assert stored(store)[0]["filed"] == []


def test_the_feedback_repo_receives_the_escalation_issue(repo, tr, monkeypatch, capsys):
    """AC-088.13: CPLAT_FEEDBACK_REPO."""
    monkeypatch.setenv("CPLAT_FEEDBACK_REPO", "me/fork")
    started(repo)
    escalate(repo, "copier render fails", "--cause", "platform")
    assert tr.created()[0][1] == "me/fork" and "https://github.com/me/fork/issues/1 new" in capsys.readouterr().out


def test_the_cap_warns_in_the_escalation_output(repo, tr, store, capsys):
    """AC-088.14: the 11th distinct platform failure is kept pending and the output warns; exit status 0."""
    for n in range(10):
        started(repo)
        escalate(repo, f"failure {'x' * n}", "--cause", "platform")
    capsys.readouterr()
    started(repo)
    assert escalate(repo, "failure of another kind", "--cause", "platform") == 0
    out = capsys.readouterr().out
    assert "cap of 10 new issues per 24 h reached" in out and len(tr.created()) == 10 and runs.pending_count() == 1


# ---------------- AC-088.4 crashes ----------------

def crash_in(monkeypatch, exc=None):
    import status

    def failing(argv):
        raise (exc or boom("ship.py", "land", RuntimeError("kaboom 12")))
    monkeypatch.setattr(status, "main", failing)


def test_a_crash_inside_a_recorded_run_is_filed_at_once(repo, tr, store, monkeypatch, capsys):
    """AC-088.4: filed as platform with exception type and traceback; exit 70; no report-issue hint; the run record has it."""
    started(repo)
    monkeypatch.chdir(repo)
    crash_in(monkeypatch)
    assert cplat.main(["status"]) == 70
    err = capsys.readouterr().err
    assert "unexpected failure" in err and f"issue: https://github.com/{PLATFORM_REPO}/issues/1 new" in err.splitlines()
    assert "/shared:report-issue" not in err
    ((_, target, title, body, labels),) = tr.created()
    assert target == PLATFORM_REPO and title.startswith("[auto] cplat status crashed: RuntimeError: kaboom") and "bug" in labels
    assert "RuntimeError" in body and "Traceback" in body and "kaboom" in body
    assert "- command: `cplat status`" in body and len(SIG_LINE.findall(body)) == 1
    rid = runs.current(repo)
    assert rid and rid in body
    runs.finish(rid, "abandoned")
    assert stored(store)[0]["filed"][0]["result"] == "new"


def test_the_crash_evidence_is_the_last_20_trace_lines(ai, tmp_path):
    """AC-088.4."""
    def deep(n):
        if n == 0:
            raise ValueError("deep " + "y" * 50)
        deep(n - 1)
    try:
        deep(40)
    except ValueError as e:
        d = ai.crash_draft(["ship", "land"], e, "r-1", tmp_path)
    assert d.reason == "cplat ship land crashed: ValueError: deep " + "y" * 50
    lines = d.evidence.splitlines()
    assert 1 <= len(lines) <= 20 and "ValueError" in d.evidence and d.kind == "platform" and d.run_id == "r-1"


def test_the_same_crash_again_is_a_plus_one(repo, tr, monkeypatch, capsys):
    """AC-088.4 AC-088.5: another message and number, same type, command and frame: +1."""
    started(repo)
    monkeypatch.chdir(repo)
    crash_in(monkeypatch, boom("ship.py", "land", RuntimeError("one 1")))
    cplat.main(["status"])
    crash_in(monkeypatch, boom("ship.py", "land", RuntimeError("two 22")))
    cplat.main(["status"])
    assert len(tr.created()) == 1 and len(tr.commented()) == 1
    assert capsys.readouterr().err.count(" +1") == 1


def test_a_crash_outside_a_recorded_run_files_nothing_and_keeps_the_hint(tmp_path, tr, monkeypatch, capsys):
    """AC-088.4: a manual command in a plain directory prints the /shared:report-issue hint as today."""
    monkeypatch.chdir(tmp_path)
    crash_in(monkeypatch)
    assert cplat.main(["status"]) == 70
    err = capsys.readouterr().err
    assert tr.calls == [] and "unexpected failure" in err and "/shared:report-issue" in err and "issue:" not in err


def test_a_crash_in_a_repo_without_an_active_run_files_nothing(repo, tr, monkeypatch, capsys):
    """AC-088.4: a repo with a ship state whose run is not active (here: escalated) is not a recorded run."""
    started(repo)
    escalate(repo, "stopped", "--cause", "code")
    monkeypatch.chdir(repo)
    crash_in(monkeypatch)
    assert cplat.main(["status"]) == 70
    assert tr.calls == [] and "/shared:report-issue" in capsys.readouterr().err


def test_an_error_with_a_hint_is_not_a_crash(repo, tr, monkeypatch, capsys):
    """AC-088.4: a PlatformError is reported with its hint and files nothing, also inside a run."""
    import status
    started(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(status, "main", lambda argv: (_ for _ in ()).throw(core.PlatformError("nope", hint="do this")))
    assert cplat.main(["status"]) == 1
    assert tr.calls == [] and "fix: do this" in capsys.readouterr().err


def test_a_failing_crash_hook_falls_back_to_the_hint(repo, tr, ai, monkeypatch, capsys):
    """AC-088.4: the hook never changes the exit code (70) and falls back to today's hint."""
    started(repo)
    monkeypatch.chdir(repo)
    crash_in(monkeypatch)
    monkeypatch.setattr(ai, "file_crash", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("hook broke")))
    assert cplat.main(["status"]) == 70
    assert "/shared:report-issue" in capsys.readouterr().err


def test_a_crash_with_filing_off_prints_the_draft_and_the_hint(repo, tr, monkeypatch, capsys):
    """AC-088.4 AC-088.13: off: nothing sent, the hint is part of the lines."""
    monkeypatch.setenv("CPLAT_AUTO_ISSUES", "off")
    started(repo)
    monkeypatch.chdir(repo)
    crash_in(monkeypatch)
    assert cplat.main(["status"]) == 70
    err = capsys.readouterr().err
    assert tr.calls == [] and "/shared:report-issue" in err and "Draft issue for" in err


def test_debug_reraises_after_the_filing(repo, tr, monkeypatch):
    """AC-088.4: CPLAT_DEBUG still re-raises, after the issue was filed."""
    started(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CPLAT_DEBUG", "1")
    crash_in(monkeypatch)
    with pytest.raises(RuntimeError):
        cplat.main(["status"])
    assert len(tr.created()) == 1


# ---------------- AC-088.4 runs.current ----------------

def test_current_finds_the_ships_active_run(repo):
    """AC-088.4: inside a ship run, `runs.current(repo)` is its run id."""
    started(repo)
    rid = ship.load_state(repo)["run_id"]
    assert rid and runs.current(repo) == rid and runs.active(rid) is not None


def test_current_is_none_without_an_active_record(repo, tmp_path):
    """AC-088.4: no run, a plain directory, a finished or an escalated run."""
    assert runs.current(tmp_path) is None and runs.current(repo) is None
    started(repo)
    escalate(repo, "stopped", "--cause", "code")
    assert runs.current(repo) is None


def test_current_follows_the_run_parent(tmp_path, monkeypatch):
    """AC-088.4: $CPLAT_RUN_PARENT counts when its record is active, and not otherwise."""
    rid = runs.start("headless", repo="acme/x")
    monkeypatch.setenv("CPLAT_RUN_PARENT", rid)
    assert runs.current(tmp_path) == rid
    runs.finish(rid, "done")
    assert runs.current(tmp_path) is None
    monkeypatch.setenv("CPLAT_RUN_PARENT", "no-such-run")
    assert runs.current(tmp_path) is None


def test_current_follows_the_runs_begin_pointer(repo, capsys):
    """AC-088.4: a run begun with `cplat runs begin` is a recorded run."""
    assert runs.main(["begin", "build", "--dir", str(repo)]) == 0
    rid = runs.current(repo)
    assert rid and runs.active(rid)["kind"] == "build"


# ---------------- AC-088.8 / .12 the suppressed note on a retry ----------------

def test_a_retry_that_ends_suppressed_notes_the_issue(ai, tr, store, monkeypatch):
    """AC-088.8 AC-088.12: the follow-up line carries `suppressed by #<n>`."""
    from test_autoissue import mkdraft
    monkeypatch.setenv("CPLAT_RUNS_REPO", store.slug)
    rid = runs.start("ship", repo="acme/shop-api")
    d = mkdraft(ai, run_id=rid)
    tr.error = ai.TrackerError("no network")
    ai.file(d, run_id=rid)
    runs.finish(rid, "escalated", escalation={"reason": "r", "cause": "platform"})
    tr.error = None
    wf = tr.add(body=f"Signature: {d.signature}", state="closed", closed_at="2026-10-20T00:00:00Z", labels=["wontfix"])
    runs.flush()
    (f,) = followups(store)
    assert f["result"] == "suppressed" and f["note"] == f"suppressed by #{wf.number}"
