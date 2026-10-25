"""Spec 070: unattended `claude -p` runs that resume an unfinished ship run, respect a quiet window, and report."""
import datetime as dt
import json
import stat
import subprocess

import pytest

import core
import headless
import ship
from test_spec import make


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    r = tmp_path / "shop-api"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / ".claude").mkdir()
    (r / ".claude" / "settings.json").write_text("{}")
    make(r, status="approved")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(headless, "notify", lambda *a: None)
    return r


def fake_claude(tmp_path, monkeypatch, script: str):
    """A stand-in for `claude` that runs `script` (bash) in the repo; it counts its runs in runs.txt."""
    exe = tmp_path / "claude"
    exe.write_text("#!/bin/bash\necho run >> runs.txt\n" + script + "\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CPLAT_CLAUDE", str(exe))


def runs(repo):
    f = repo / "runs.txt"
    return len(f.read_text().splitlines()) if f.is_file() else 0


def set_state(repo, **kw):
    f = ship.state_path(repo)
    st = json.loads(f.read_text())
    st.update(kw)
    f.write_text(json.dumps(st))


def test_the_command_is_unattended_with_the_repo_allowlist(repo, capsys):
    """AC-070.5: claude -p in acceptEdits mode: edits in the repo and allowlisted tools run, everything else is refused, nothing prompts."""
    assert headless.main(["/svc:ship", "7", "--repo", str(repo), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("claude -p '/svc:ship 7' --permission-mode acceptEdits")


def test_a_repo_without_an_allowlist_is_refused(repo):
    (repo / ".claude" / "settings.json").unlink()
    with pytest.raises(core.PlatformError, match="permission allowlist"):
        headless.main(["/svc:ship 7", "--repo", str(repo)])


def test_an_unfinished_ship_run_is_resumed_in_a_fresh_session(repo, tmp_path, monkeypatch, capsys):
    """AC-070.2: a session that ends with the run unfinished is followed by another until the run is done."""
    ship.start(repo, "7", True)
    # first run gets to land, second finishes
    fake_claude(tmp_path, monkeypatch, f"""n=$(wc -l < runs.txt)
f=$(git rev-parse --git-common-dir)/cplat-ship.json
if [ "$n" -ge 2 ]; then sed -i.bak 's/"phase": "[a-z]*"/"phase": "done"/' "$f"; else sed -i.bak 's/"phase": "[a-z]*"/"phase": "land"/' "$f"; fi""")
    assert headless.main(["/svc:ship 7", "--repo", str(repo)]) == 0
    assert runs(repo) == 2
    out = capsys.readouterr().out
    assert "resuming" in out and "HEADLESS shop-api: shipped 007-price-alerts" in out
    summary = (tmp_path / "cache" / "sdlc-foundry" / "headless" / "shop-api" / "summary.log").read_text()
    assert "shipped 007-price-alerts" in summary


def test_an_escalated_run_is_not_resumed_and_says_why(repo, tmp_path, monkeypatch, capsys):
    """AC-070.2 AC-070.4: escalation ends the loop with a non-zero exit and the reason in the report."""
    ship.start(repo, "7", True)
    set_state(repo, phase="land", escalated="merge conflict in alerts.go")
    fake_claude(tmp_path, monkeypatch, "true")
    assert headless.main(["/svc:ship 7", "--repo", str(repo)]) == 1
    assert runs(repo) == 1
    assert "needs you: 007-price-alerts escalated in phase land: merge conflict" in capsys.readouterr().out


def test_runs_are_capped(repo, tmp_path, monkeypatch, capsys):
    """AC-070.2: a run that never finishes (but keeps committing) stops after --max-runs sessions."""
    ship.start(repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "git -c user.name=t -c user.email=t@t commit -q --allow-empty -m step")
    assert headless.main(["/svc:ship 7", "--repo", str(repo), "--max-runs", "3"]) == 1
    assert runs(repo) == 3 and "stopped after 3 runs" in capsys.readouterr().out


def test_two_idle_sessions_stop_the_loop_and_escalate(repo, tmp_path, monkeypatch, capsys):
    """AC-080.2: sessions that change nothing (same phase, HEAD, fix rounds, state) stop after two, not --max-runs."""
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    ship.start(repo, "7", True)
    fake_claude(tmp_path, monkeypatch, "true")
    assert headless.main(["/svc:ship 7", "--repo", str(repo), "--max-runs", "6"]) == 1
    out = capsys.readouterr().out
    assert runs(repo) == 2 and "no progress" in out
    assert "no progress" in ship.load_state(repo)["escalated"]


def test_a_plain_prompt_without_ship_state_runs_once(repo, tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, "true")
    assert headless.main(["/svc:fix-bug the price is wrong", "--repo", str(repo)]) == 0
    assert runs(repo) == 1


@pytest.mark.parametrize("window, at, left", [
    ("23:30-07:00", dt.datetime(2026, 10, 22, 23, 45), 7 * 3600 + 15 * 60),
    ("23:30-07:00", dt.datetime(2026, 10, 22, 6, 0), 3600),
    ("23:30-07:00", dt.datetime(2026, 10, 22, 12, 0), 0),
    ("12:00-13:00", dt.datetime(2026, 10, 22, 12, 30), 1800),
])
def test_quiet_window(window, at, left):
    """AC-070.3: windows may wrap midnight."""
    assert headless.seconds_left_in_window(headless.parse_window(window), at) == left


def test_no_session_starts_inside_the_quiet_window(repo, tmp_path, monkeypatch, capsys):
    """AC-070.3: --no-wait exits with 3; without it the run waits for the window to end, then starts."""
    fake_claude(tmp_path, monkeypatch, "true")
    t = {"now": dt.datetime(2026, 10, 22, 23, 45)}
    monkeypatch.setattr(headless, "clock", lambda: t["now"])
    assert headless.main(["/svc:ship 7", "--repo", str(repo), "--quiet", "23:30-07:00", "--no-wait"]) == 3
    assert runs(repo) == 0
    waited = []
    monkeypatch.setattr(headless, "sleep", lambda s: (waited.append(s), t.__setitem__("now", t["now"] + dt.timedelta(seconds=s))))
    assert headless.main(["/svc:ship 7", "--repo", str(repo), "--quiet", "23:30-07:00"]) == 0
    assert waited == [7 * 3600 + 15 * 60] and runs(repo) == 1
