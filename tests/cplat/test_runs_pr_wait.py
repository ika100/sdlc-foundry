"""Spec 087 (amendment 2026-10-26): the `pr_wait` section of a `pr-wait` record (AC-087.24)."""
import subprocess

import pytest

import core
import pr as prmod
import ship
from test_runs import clock, mem, rgh, store, stored, to_land  # noqa: F401  (fixtures)
from test_ship import check, gh, repo  # noqa: F401  (fixtures)
from test_tags_and_wait import fake  # noqa: F401  (fixture)

URL = "https://github.com/acme/other/pull/5"
MAVEN = "[ERROR] Failed to read artifact descriptor for org.apache.maven.shared:maven-shared-utils:jar:3.4.2"
TOKEN = "ghp_abc123abc123abc123abc123abc123"


def one(store):
    (r,) = stored(store)
    assert r["kind"] == "pr-wait"
    return r


def test_ac_087_24_green_without_merge(repo, fake, store):  # AC-087.24
    fake.checks = [[check("quality", "pending")], [check("quality", "pass")]]
    assert prmod.wait(repo, URL, False, 600, 10, 300)[0]
    r = one(store)
    assert r["outcome"] == "done" and r["pr_wait"] == {"result": "green"}


def test_ac_087_24_merged_after_green_with_merge(repo, fake, store):  # AC-087.24
    fake.checks = [[check("quality", "pass")]]
    assert prmod.wait(repo, URL, True, 600, 10, 300)[0]
    r = one(store)
    assert r["outcome"] == "done" and r["pr_wait"] == {"result": "merged"}


def test_ac_087_24_merged_when_already_merged(repo, fake, store):  # AC-087.24
    fake.state = "MERGED"
    assert prmod.wait(repo, URL, False, 600, 10, 300)[0]
    r = one(store)
    assert r["outcome"] == "done" and r["pr_wait"] == {"result": "merged"}


def test_ac_087_24_red_lists_the_sorted_failing_checks(repo, fake, store):  # AC-087.24
    fake.checks = [[check("test", "fail"), check("lint", "fail"), check("build", "pass")]]
    assert not prmod.wait(repo, URL, False, 600, 10, 300)[0]
    r = one(store)
    assert r["outcome"] == "failed" and r["pr_wait"] == {"result": "red", "checks": ["lint", "test"]}


def test_ac_087_24_budget_refused_lists_the_failing_checks(repo, fake, store, monkeypatch):  # AC-087.24
    monkeypatch.setattr(ship.budget, "allow_rerun", lambda run_id: False)
    fake.logs["42"] = [MAVEN]
    fake.checks = [[check("java", "fail")]]
    assert not prmod.wait(repo, URL, False, 600, 10, 300)[0]
    r = one(store)
    assert r["outcome"] == "failed" and r["pr_wait"] == {"result": "budget-refused", "checks": ["java"]}


def test_ac_087_24_timeout_lists_the_pending_checks(repo, fake, store):  # AC-087.24
    fake.checks = [[check("slow", "pending"), check("fast", "pass"), check("also-slow", "pending")]]
    with pytest.raises(core.PlatformError):
        prmod.wait(repo, URL, False, 30, 10, 300)
    r = one(store)
    assert r["outcome"] == "failed" and r["pr_wait"] == {"result": "timeout", "checks": ["also-slow", "slow"]}


def test_ac_087_24_no_checks_within_the_grace_period(repo, fake, store):  # AC-087.24
    fake.checks = [[]]
    with pytest.raises(core.PlatformError):
        prmod.wait(repo, URL, False, 3600, 10, 300)
    r = one(store)
    assert r["outcome"] == "failed" and r["pr_wait"] == {"result": "no-checks"}


def test_ac_087_24_closed_without_merging(repo, fake, store):  # AC-087.24
    fake.state = "CLOSED"
    fake.checks = [[check("test", "pass")]]
    with pytest.raises(core.PlatformError):
        prmod.wait(repo, URL, False, 30, 10, 300)
    r = one(store)
    assert r["outcome"] == "failed" and r["pr_wait"] == {"result": "closed"}


def test_ac_087_24_merge_failed_when_the_merge_is_refused(repo, fake, store, monkeypatch):  # AC-087.24
    monkeypatch.setattr(prmod, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Pull request is not mergeable"))
    fake.checks = [[check("test", "pass")]]
    with pytest.raises(core.PlatformError):
        prmod.wait(repo, URL, True, 600, 10, 300)
    r = one(store)
    assert r["outcome"] == "failed" and r["pr_wait"] == {"result": "merge-failed"}


def test_ac_087_24_error_from_gh_keeps_the_first_line_redacted(repo, fake, store, monkeypatch):  # AC-087.24
    def boom(args, *, cwd, check=True):
        raise core.PlatformError(f"\ngh: HTTP 502: Bad Gateway GH_TOKEN={TOKEN}\nsecond line")
    monkeypatch.setattr(ship, "gh", boom)
    with pytest.raises(core.PlatformError):
        prmod.wait(repo, URL, False, 600, 10, 300)
    r = one(store)
    assert r["outcome"] == "failed" and r["pr_wait"]["result"] == "error"
    msg = r["pr_wait"]["message"]
    assert msg.startswith("gh: HTTP 502: Bad Gateway") and TOKEN not in msg and "\n" not in msg and "second line" not in msg
    assert set(r["pr_wait"]) == {"result", "message"}


def test_ac_087_24_error_when_gh_is_missing(repo, fake, store, monkeypatch):  # AC-087.24
    def missing(args, *, cwd, check=True):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(ship, "gh", missing)
    with pytest.raises(FileNotFoundError):
        prmod.wait(repo, URL, False, 600, 10, 300)
    r = one(store)
    assert r["outcome"] == "failed" and r["pr_wait"]["result"] == "error" and r["pr_wait"]["message"]


def test_ac_087_24_an_interrupt_is_an_error_named_interrupted(repo, fake, store, monkeypatch):  # AC-087.24
    def stop(args, *, cwd, check=True):
        raise KeyboardInterrupt()
    monkeypatch.setattr(ship, "gh", stop)
    with pytest.raises(KeyboardInterrupt):
        prmod.wait(repo, URL, False, 600, 10, 300)
    assert one(store)["pr_wait"] == {"result": "error", "message": "interrupted"}


def test_ac_087_24_an_exception_without_text_uses_its_class_name(repo, fake, store, monkeypatch):  # AC-087.24
    def crash(args, *, cwd, check=True):
        raise RuntimeError()
    monkeypatch.setattr(ship, "gh", crash)
    with pytest.raises(RuntimeError):
        prmod.wait(repo, URL, False, 600, 10, 300)
    assert one(store)["pr_wait"] == {"result": "error", "message": "RuntimeError"}


def test_ac_087_24_a_wait_inside_a_ship_run_records_no_section(repo, rgh, store):  # AC-087.24 (non-goal: attached waits record nothing new)
    to_land(repo, rgh, merge=False)
    rgh.checks = [[check("test", "fail")]]
    assert not prmod.wait(repo, URL, False, 600, 10, 300)[0]
    assert stored(store) == []
