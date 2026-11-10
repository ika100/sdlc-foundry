"""Spec 131 acceptance tests: `/system:ship` gets the preflight and the scaled budget parts (design.md "Run allowlist and
preflight" > "/system:ship repos started later", "Budgets" > ledger parts).

The world is the one of test_appship_097.py (a local origin, fake `gh`, `kubectl`, `devbox`); a thin `gh` wrapper in front of it
answers `gh auth status` and `gh api repos/...` and hands everything else to the world's `gh`. The settings layers are replaced
through `preflight.layers`.
"""
import importlib
import json
import os
import stat

import pytest

import runs
from test_appship_097 import SPEC, GITOPS, w  # noqa: F401  (fixtures, constants)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

WRAPPER = '''#!/bin/sh
if [ "$1" = "auth" ]; then
  [ "$FAKE_GH_AUTH" = "fail" ] && exit 1
  exit 0
fi
if [ "$1" = "api" ]; then
  case "$*" in
    *permissions.push*) [ "$FAKE_GH_PUSH" = "false" ] && echo false || echo true ;;
    *) echo "[]" ;;
  esac
  exit 0
fi
exec "%(real)s" "$@"
'''


@pytest.fixture()
def pre(w, tmp_path, monkeypatch):  # noqa: F811
    """The preflight of a clone passes: committed allowlist, no deny rule, push access, a gh wrapper."""
    wrapper_dir = tmp_path / "wrapper-bin"
    wrapper_dir.mkdir()
    gh = wrapper_dir / "gh"
    gh.write_text(WRAPPER % {"real": w.bin / "gh"})
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{wrapper_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("FAKE_GH_AUTH", raising=False)
    monkeypatch.delenv("FAKE_GH_PUSH", raising=False)
    user = tmp_path / "user.json"
    user.write_text("{}")

    def arm():
        monkeypatch.setattr(importlib.import_module("preflight"), "layers", lambda r=None: [
            ("managed", tmp_path / "none.json"), ("user", user), ("project", r / ".claude" / "settings.json"),
            ("local", r / ".claude" / "settings.local.json")])
    real_app = w.app

    def app(*args, **kw):
        arm()                                # imports preflight: a missing module fails the test, not its fixture
        return real_app(*args, **kw)
    w.app = app
    for rid in ("shop-lib", "shop-api", "shop-worker", "shop-web"):
        c = w.clone(rid)
        (c / ".claude").mkdir(exist_ok=True)
        (c / ".claude" / "settings.json").write_text('{"permissions": {"allow": ["Bash(devbox run *)", "Bash(cplat *)", "Read(~/.claude/plugins/**)"]}}\n')
        (c / ".gitignore").write_text(".claude/settings.local.json\n")     # as a generated repo ignores it
        w_git(c, "add", "-A")
        w_git(c, "commit", "-qm", "allowlist")
    w.user = user
    return w


def w_git(repo, *args):
    import subprocess
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


READY = {"shop-gitops": "passed", "shop-lib": "passed"}


def ledgers():
    d = runs.state_dir() / "budgets"
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.is_dir() else []


# ---------------- AC-131.13: one budget part per repo of the plan ----------------

def test_a_product_ship_gets_a_placeholder_part_per_repo_of_the_plan(w):  # AC-131.13
    w.started()
    (ledger,) = ledgers()
    keys = set(ledger["parts"])
    for rid in ("shop-lib", "shop-api", "shop-worker", "shop-web"):
        assert f"acme/{rid}:*" in keys, keys
    for key in (k for k in keys if k.endswith(":*")):
        assert ledger["parts"][key]["limits"] == {"minutes": 180, "invocations": 60, "reruns": 6, "cost": 15}
    assert ledger["limits"]["invocations"] >= 4 * 60 and ledger["limits"]["cost"] >= 4 * 15


def test_the_parts_are_summed_into_the_limits(w):  # AC-131.13
    w.started()
    (ledger,) = ledgers()
    for limit in ("minutes", "invocations", "cost", "reruns"):
        assert ledger["limits"][limit] == sum(p["limits"][limit] for p in ledger["parts"].values())


# ---------------- AC-131.8: the session allowlist covers every feature branch ----------------

def test_the_system_ship_allowlist_covers_feature_branches():  # AC-131.8
    rules = importlib.import_module("preflight").run_allowlist("/system:ship", ["feature/*"])
    assert "Bash(git switch -c feature/*)" in rules and "Bash(git push -u origin feature/*)" in rules


# ---------------- AC-131.11: the preflight of a repo at `repo start` ----------------

def test_a_repo_that_passes_the_preflight_starts(pre):  # AC-131.11
    pre.started(states=READY)
    r = pre.app("repo", "start", "shop-api")
    assert r.rc == 0 and pre.state()["repos"]["shop-api"]["state"] == "running"


def test_a_repo_with_an_ask_rule_on_git_push_is_escalated_and_not_started(pre):  # AC-131.11
    pre.started(states=READY)
    clone = pre.clone("shop-api")
    (clone / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {"ask": ["Bash(git push:*)"]}}))
    r = pre.app("repo", "start", "shop-api")
    assert r.rc == 1
    line = next(ln for ln in r.out.splitlines() if ln.startswith("preflight failed: "))
    assert line.startswith("preflight failed: blocked-by-settings: ") and 'ask rule "Bash(git push:*)" in local settings' in line
    repo = pre.state()["repos"]["shop-api"]
    assert repo["state"] == "escalated" and repo["reason"] == "preflight failed: blocked-by-settings" and repo["cause"] == "environment"
    assert not (clone / ".git" / "cplat-ship.json").exists()


def test_a_repo_without_push_access_is_escalated(pre, monkeypatch):  # AC-131.11
    pre.started(states=READY)
    monkeypatch.setenv("FAKE_GH_PUSH", "false")
    r = pre.app("repo", "start", "shop-api")
    assert r.rc == 1 and "preflight failed: no-push-access: " in r.out
    repo = pre.state()["repos"]["shop-api"]
    assert repo["state"] == "escalated" and repo["reason"] == "preflight failed: no-push-access" and repo["cause"] == "environment"


def test_a_repo_without_a_committed_allowlist_is_escalated(pre):  # AC-131.11
    pre.started(states=READY)
    clone = pre.clone("shop-api")
    w_git(clone, "rm", "-q", ".claude/settings.json")
    w_git(clone, "commit", "-qm", "drop")
    r = pre.app("repo", "start", "shop-api")
    assert r.rc == 1 and "preflight failed: no-repo-allowlist: " in r.out
    assert pre.state()["repos"]["shop-api"]["reason"] == "preflight failed: no-repo-allowlist"


def test_the_gitops_entry_is_not_checked_here(pre, monkeypatch):  # AC-131.11
    pre.started()
    monkeypatch.setenv("FAKE_GH_PUSH", "false")
    r = pre.app("repo", "start", GITOPS)
    assert r.rc == 0 and "preflight failed" not in r.out
