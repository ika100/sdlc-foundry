"""Spec 126: the product Stop hook's cause with red evidence, and its precedence over an escalated repo's cause."""
import json
import os
import stat
import sys

import pytest

from test_appship_097 import World, w  # noqa: F401  (fixtures)
from test_appship_gate_126 import _no_session_env, begin, stop  # noqa: F401

GH_WRAP = """#!%(py)s
import os, sys
a = sys.argv[1:]
if a[:2] == ["pr", "view"] and "--json" in a and a[2] == "--json":
    print('{"url": "https://github.com/acme/shop-gitops/pull/5", "state": "OPEN"}')
elif a[:2] == ["pr", "checks"] and "--required" in a:
    print('[{"name": "lint", "bucket": "fail"}]')
else:
    os.execv(%(orig)r, [%(orig)r, *a])
"""


def red_required_check(w):
    orig = w.bin / "gh-orig"
    (w.bin / "gh").rename(orig)
    gh = w.bin / "gh"
    gh.write_text(GH_WRAP % {"py": sys.executable, "orig": str(orig)})
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)


def escalate_by_stopping(w, message="stuck"):
    stop(w)
    stop(w)
    stop(w, message=message)
    return w.state()


def test_ac_126_8_a_red_required_check_gives_the_cause_code(w, monkeypatch):  # AC-126.8 AC-126.7
    begin(w, monkeypatch)
    red_required_check(w)
    st = escalate_by_stopping(w)
    assert st["escalated"] and st["cause"] == "code"


@pytest.mark.parametrize("repo_cause", ["platform", "environment", "unknown"])
def test_ac_126_8_an_escalated_repo_does_not_override_the_no_progress_cause(w, monkeypatch, repo_cause):  # AC-126.8 AC-126.7
    begin(w, monkeypatch)
    w.edit(lambda st: st["repos"]["shop-lib"].update(state="escalated", cause=repo_cause, reason="x"))
    st = escalate_by_stopping(w)
    assert st["escalated"] and st["cause"] == "decision"


def test_ac_126_8_the_rule_cause_wins_over_an_escalated_repo_cause(w, monkeypatch):  # AC-126.8 AC-126.7
    begin(w, monkeypatch)
    red_required_check(w)
    w.edit(lambda st: st["repos"]["shop-lib"].update(state="escalated", cause="platform", reason="x"))
    st = escalate_by_stopping(w, "waiting for approval to push the branch")
    assert st["cause"] == "environment"
