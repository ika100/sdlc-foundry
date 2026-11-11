"""Spec 184 acceptance tests: one ship at a time per repo (AC-184.8).

Seams: `run_slot.held` / `holders` / `total` (design.md, Contract, "Repo slots") with a real second process as the holder (a flock is
held by an open file of that process, so only a process can hold it against this one), `run_slot.sleep` (replaced: the first poll ends
the holder), and `headless.main` with the bash fake `claude` of `test_headless`. Nothing waits for real time.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

import pytest

import core
import dispatch_state
import headless
import runs
from support_184 import Holders
from test_headless import fake_claude, repo as base_repo, runs as legacy_runs  # noqa: F401  (fixture, helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

SLUG = "acme/shop-api"


@pytest.fixture(autouse=True)
def not_inside_a_run(monkeypatch):
    monkeypatch.delenv("CPLAT_SLOT", raising=False)


@pytest.fixture()
def repo(base_repo):
    subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{SLUG}.git"], cwd=base_repo, check=True)
    return base_repo


def locks():
    return dispatch_state.state_root() / "locks"


@pytest.fixture()
def holders(tmp_path):
    h = Holders(tmp_path)
    yield h
    h.close()


def ends_the_holder_on_the_first_poll(monkeypatch, run_slot, holder, polls, extra=None):
    def sleeper(seconds):
        polls.append(seconds)
        if extra:
            extra()
        holder.end()
    monkeypatch.setattr(run_slot, "sleep", sleeper)


# ---------------- run_slot ----------------

def test_a_second_run_prints_who_holds_the_slot_and_starts_after_the_holder_ends_ac_184_8(repo, holders, monkeypatch):  # AC-184.8
    import run_slot
    holder = holders.start(repo)
    polls, said = [], []
    ends_the_holder_on_the_first_poll(monkeypatch, run_slot, holder, polls)
    with run_slot.held(repo, "/component:ship 183", say=said.append) as slot:
        assert slot == 1
        info = json.loads((locks() / "acme__shop-api.slot-1.json").read_text())
        assert info["command"] == "/component:ship 183" and info["pid"] == os.getpid()
        assert os.environ["CPLAT_SLOT"] == f"{SLUG}#1"
    assert len(said) == 1 and polls == [run_slot.POLL_SECONDS] and run_slot.POLL_SECONDS <= 60
    assert re.fullmatch(rf"waiting for a slot: held by /component:ship 182 \(pid {holder.pid}, since \d{{4}}-\d\d-\d\d \d\d:\d\d, "
                        rf"{re.escape(str(repo.resolve()))}\)", said[0]), said
    assert not (locks() / "acme__shop-api.slot-1.json").exists() and "CPLAT_SLOT" not in os.environ


def test_no_wait_raises_with_the_holder_named_ac_184_8(repo, holders):  # AC-184.8
    import run_slot
    holder = holders.start(repo)
    with pytest.raises(run_slot.SlotBusy) as e:
        with run_slot.held(repo, "/component:ship 183", wait=False):
            pytest.fail("the slot was free")
    assert re.fullmatch(rf"slot busy: held by /component:ship 182 \(pid {holder.pid}, since \d{{4}}-\d\d-\d\d \d\d:\d\d, "
                        rf"{re.escape(str(repo.resolve()))}\)", str(e.value))
    assert isinstance(e.value, core.PlatformError)


def test_the_live_holders_are_listed_with_their_command_and_no_unit_ac_184_8(repo, holders):  # AC-184.8
    import run_slot
    holder = holders.start(repo, "/component:ship 182")
    (h,) = run_slot.holders(SLUG)
    assert (h.command, h.pid, h.slot, h.unit, h.checkout) == ("/component:ship 182", holder.pid, 1, None, str(repo.resolve()))
    holder.end()
    assert run_slot.holders(SLUG) == []


def test_a_slot_whose_process_is_gone_is_freed_with_a_line_ac_184_8(repo):  # AC-184.8
    import run_slot
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    locks().mkdir(parents=True, exist_ok=True)
    (locks() / "acme__shop-api.slot-1.json").write_text(json.dumps(
        {"command": "/component:ship 99", "pid": dead.pid, "since": "2026-11-11 09:00", "checkout": "/tmp/x", "unit": None}))
    assert run_slot.holders(SLUG) == []
    said = []
    with run_slot.held(repo, "/component:ship 100", say=said.append) as slot:
        assert slot == 1
    assert said == [f"freed a stale slot of /component:ship 99 (pid {dead.pid} gone)"]


def test_the_pool_is_the_slots_of_the_dispatch_policy_else_one_ac_184_8(repo, holders):  # AC-184.8
    import run_slot
    assert run_slot.total(repo) == 1
    (repo / ".platform").mkdir()
    (repo / ".platform" / "dispatch.yml").write_text("slots: 2\nbudget:\n  tokens_per_day: 1000\n")
    assert run_slot.total(repo) == 2
    first = holders.start(repo, "/component:ship 1")
    second = holders.start(repo, "/component:ship 2")                                 # the second one is admitted
    assert sorted(h.slot for h in run_slot.holders(SLUG)) == [1, 2]
    with pytest.raises(run_slot.SlotBusy):
        run_slot.held(repo, "/component:ship 3", wait=False).__enter__()
    first.end()
    second.end()
    (repo / ".platform" / "dispatch.yml").write_text("slots: [broken\n")
    assert run_slot.total(repo) == 1
    dispatch_state.set_slots(SLUG, 3)                                                # the dispatcher's steering override
    (repo / ".platform" / "dispatch.yml").write_text("slots: 2\nbudget:\n  tokens_per_day: 1000\n")
    assert run_slot.total(repo) == 3


def test_every_worktree_and_clone_of_the_repo_shares_the_slots_ac_184_8(repo, holders, tmp_path):  # AC-184.8
    import run_slot
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"], cwd=repo, check=True)
    other = tmp_path / "second-checkout"
    subprocess.run(["git", "worktree", "add", "-q", str(other), "-b", "other"], cwd=repo, check=True)
    holder = holders.start(repo)
    with pytest.raises(run_slot.SlotBusy, match=re.escape(f"pid {holder.pid}")) as e:
        run_slot.held(other, "/component:ship 183", wait=False).__enter__()
    assert str(repo.resolve()) in str(e.value)
    clone = tmp_path / "separate-clone"                                              # a clone with the same origin shares them too
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True)
    subprocess.run(["git", "remote", "set-url", "origin", f"https://github.com/{SLUG}.git"], cwd=clone, check=True)
    with pytest.raises(run_slot.SlotBusy, match=re.escape(f"pid {holder.pid}")) as e2:
        run_slot.held(clone, "/component:ship 184", wait=False).__enter__()
    assert str(repo.resolve()) in str(e2.value)


def test_a_run_inside_a_run_takes_no_slot_and_prints_nothing_ac_184_8(repo, holders, monkeypatch):  # AC-184.8
    import run_slot
    holders.start(repo)
    monkeypatch.setenv("CPLAT_SLOT", f"{SLUG}#1")
    said = []
    with run_slot.held(repo, "/component:ship 183", wait=False, say=said.append) as slot:
        assert slot is None
    assert said == []


# ---------------- cplat headless ----------------

FIX = "/svc:fix-bug the price is wrong"


def run_fix(repo, *args):
    return headless.main([FIX, "--repo", str(repo), *args])


def test_a_second_headless_run_starts_no_session_until_the_holder_ends_ac_184_8(repo, holders, tmp_path, monkeypatch, capsys):  # AC-184.8
    import run_slot
    holder = holders.start(repo)
    fake_claude(tmp_path, monkeypatch, f'echo "$CPLAT_SLOT" > {tmp_path}/slot-env.txt; ls "{locks()}" > {tmp_path}/locks-seen.txt')
    seen = []
    ends_the_holder_on_the_first_poll(monkeypatch, run_slot, holder, [], extra=lambda: seen.append(legacy_runs(repo)))
    assert run_fix(repo) == 0
    assert seen == [0]                                               # nothing had started while it waited
    out = capsys.readouterr().out
    assert re.search(rf"^waiting for a slot: held by /component:ship 182 \(pid {holder.pid}, since .+, {re.escape(str(repo.resolve()))}\)$", out, re.M)
    assert legacy_runs(repo) == 1
    assert (tmp_path / "slot-env.txt").read_text().strip() == f"{SLUG}#1"            # the session sees the slot
    assert "acme__shop-api.slot-1.json" in (tmp_path / "locks-seen.txt").read_text()   # and it is held while the session runs
    assert run_slot.holders(SLUG) == []                                              # freed after the run


def test_no_wait_exits_1_with_slot_busy_and_starts_nothing_ac_184_8(repo, holders, tmp_path, monkeypatch, capsys, store):  # AC-184.8
    holder = holders.start(repo)
    fake_claude(tmp_path, monkeypatch, "true")
    assert run_fix(repo, "--no-wait") == 1
    out = capsys.readouterr().out
    assert re.search(rf"^slot busy: held by /component:ship 182 \(pid {holder.pid}, since .+, {re.escape(str(repo.resolve()))}\)$", out, re.M)
    assert legacy_runs(repo) == 0 and stored(store) == []
    assert not (runs.state_dir() / "budgets").is_dir() or not list((runs.state_dir() / "budgets").glob("*.json"))


def test_the_dry_run_takes_no_slot_and_waits_for_none_ac_184_8(repo, holders, capsys):  # AC-184.8
    import run_slot
    holder = holders.start(repo)
    assert run_fix(repo, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "waiting for a slot" not in out and "slot busy" not in out
    assert [h.pid for h in run_slot.holders(SLUG)] == [holder.pid]


def test_a_stale_slot_is_freed_by_a_headless_run_with_the_line_ac_184_8(repo, tmp_path, monkeypatch, capsys):  # AC-184.8
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    locks().mkdir(parents=True, exist_ok=True)
    (locks() / "acme__shop-api.slot-1.json").write_text(json.dumps(
        {"command": "/component:ship 99", "pid": dead.pid, "since": "2026-11-11 09:00", "checkout": "/tmp/x", "unit": None}))
    fake_claude(tmp_path, monkeypatch, "true")
    assert run_fix(repo) == 0
    assert f"freed a stale slot of /component:ship 99 (pid {dead.pid} gone)" in capsys.readouterr().out.splitlines()


def test_the_time_spent_waiting_for_a_slot_is_not_budget_time_ac_184_8(repo, holders, tmp_path, monkeypatch, clock, capsys):  # AC-184.8
    import run_slot
    now = {"t": dt.datetime(2026, 11, 11, 10, 0)}
    monkeypatch.setattr(headless, "clock", lambda: now["t"])
    holder = holders.start(repo)
    fake_claude(tmp_path, monkeypatch, "true")

    def three_hours():
        now["t"] += dt.timedelta(hours=3)
        clock.tick(3 * 3600)
    ends_the_holder_on_the_first_poll(monkeypatch, run_slot, holder, [], extra=three_hours)
    assert run_fix(repo, "--max-minutes", "10", "--budget", "minutes=10") == 0
    assert "time budget" not in capsys.readouterr().out and legacy_runs(repo) == 1
