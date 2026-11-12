"""Spec 184 verification findings, as regression tests: a stopping pause is no invocation in the legacy loop (AC-184.3), and a
command chained with `&` or redirected is never allowed verbatim (AC-184.10)."""
import datetime as dt

import pytest

import envprefix
import headless
import ship
from test_184_pause import (NOW, T, invocations, legacy_script, limit_message, one_task_per_unit,  # noqa: F401  (fixtures, helpers)
                            lines_of)
from test_headless import fake_claude, repo as legacy_repo, runs as legacy_runs  # noqa: F401  (fixture, helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)


def test_a_legacy_pause_that_stops_the_run_carries_no_invocation_ac_184_3(legacy_repo, tmp_path, monkeypatch, T, store, capsys):  # AC-184.3
    ship.start(legacy_repo, "7", True)
    fake_claude(tmp_path, monkeypatch, legacy_script([limit_message(NOW + dt.timedelta(hours=7)), "done"]))
    assert headless.main(["/svc:ship 7", "--repo", str(legacy_repo)]) == 1
    assert any("environment pause" in ln for ln in lines_of(capsys))
    assert invocations() == 0


@pytest.mark.parametrize("cmd", ["FOO=1 devbox run test & rm -rf x", "FOO=1 devbox run test > out.txt", "FOO=1 devbox run test < in.txt"])
def test_a_background_or_redirected_command_is_not_allowed_ac_184_10(cmd):  # AC-184.10
    assert envprefix.verdict(cmd) is not None
