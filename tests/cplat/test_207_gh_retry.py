"""Spec 207 acceptance tests: AC-207.7, a gh login that reports "not logged in" is tried again 15 and 30 seconds later.

`gh` is a stub that fails `auth status` a set number of times (FAKE_GH_AUTH_FAILS); the waits are recorded through
`preflight.sleep`, never slept.
"""
import platform

import pytest

from pf207_support import Env, Seams, mod
from units131_support import SPEC_ID

HOST = "github.com"
KEYCHAIN = "; if gh is logged in, unlock the login keychain"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = Env(tmp_path, monkeypatch)
    e.seams = Seams(tmp_path, monkeypatch)
    return e


def run_check(env):
    env.seams.sleeps()
    env.arm()
    return mod("preflight").check(env.repo, "/component:ship", [SPEC_ID])


def test_a_login_that_answers_on_the_second_try_passes_after_15_seconds_ac_207_7(env, monkeypatch, capsys):  # AC-207.7
    monkeypatch.setenv("FAKE_GH_AUTH_FAILS", "1")
    assert run_check(env) is None
    assert env.seams.waits == [15] and env.auth_calls() == 2
    assert "preflight: gh login answered on try 2" in capsys.readouterr().out.splitlines()


def test_a_login_that_answers_on_the_third_try_passes_after_15_and_30_seconds_ac_207_7(env, monkeypatch, capsys):  # AC-207.7
    monkeypatch.setenv("FAKE_GH_AUTH_FAILS", "2")
    assert run_check(env) is None
    assert env.seams.waits == [15, 30] and env.auth_calls() == 3
    assert "preflight: gh login answered on try 3" in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize("system, suffix", [("Linux", ""), ("Darwin", KEYCHAIN)])
def test_three_failures_fail_gh_auth_after_45_seconds_ac_207_7(env, monkeypatch, capsys, system, suffix):  # AC-207.7
    monkeypatch.setenv("FAKE_GH_AUTH_FAILS", "9")
    monkeypatch.setattr(platform, "system", lambda: system)
    f = run_check(env)
    assert f.category == "gh-auth"
    assert f.line() == (f"preflight failed: gh-auth: gh is not logged in for {HOST} (3 tries over 45 s): "
                        f"gh auth login --hostname {HOST}{suffix}")
    assert f.reason() == "preflight failed: gh-auth"
    assert env.seams.waits == [15, 30] and sum(env.seams.waits) == 45 and env.auth_calls() == 3
    assert "gh login answered" not in capsys.readouterr().out


def test_the_host_of_the_origin_is_named_ac_207_7(env, monkeypatch):  # AC-207.7
    from units131_support import git
    git(env.repo, "remote", "set-url", "origin", "https://ghe.example.test/acme/shop-api.git")
    monkeypatch.setenv("FAKE_GH_AUTH_FAILS", "9")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    f = run_check(env)
    assert f.detail == ("gh is not logged in for ghe.example.test (3 tries over 45 s): "
                        "gh auth login --hostname ghe.example.test")


def test_a_dropped_network_is_not_retried_as_a_missing_login_ac_207_7(env, monkeypatch):  # AC-207.7
    monkeypatch.setenv("FAKE_GH_AUTH", "offline")
    f = run_check(env)
    assert f.category == "gh-auth"
    assert f.detail == (f"could not reach {HOST} to check the gh login (error connecting to api.github.com): "
                        "check the network, then run again")
    assert env.seams.waits == [] and env.auth_calls() == 1        # one call: the network error is final
    assert mod("preflight").GH_LOGIN_WAITS == (15, 30)
