"""Spec 185 acceptance tests: the suite time is measured per shard in CI (AC-185.7) and reported by the weekly retro (AC-185.8).

Seams (design.md): the shard report keys `wall_s` and `slowest` (tests/cplat/sharding.py), `scripts/check-shards.py --timing-out`,
the `platform-tests-cover` job of ci.yml, and `retro_suite.section/render/unavailable/fetch`. No test reaches GitHub: `fetch` is
replaced by a fake that returns the runs of the test.
"""
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import cplat
from retro_world import WEEK, Lazy, tracker  # noqa: F401  (fixture)
from test_fast_suite_112 import CHECK, ROOT, ci, good_reports, make_project, run_pytest, shard_run, steps_text
from test_retro_cli import world  # noqa: F401  (fixture)
from test_runs import clock, mem, store  # noqa: F401  (fixtures of `world`)

retro_suite = Lazy("retro_suite")


# ---------------- AC-185.7: the shard report ----------------

@pytest.mark.parametrize("failing", [None, "test_00_01"], ids=["green", "red"])
def test_a_shard_report_holds_the_wall_time_and_the_slowest_tests_ac_185_7(tmp_path, failing):  # AC-185.7
    project = make_project(tmp_path, files=4, per_file=5, failing=failing)       # 20 tests
    r, report = shard_run(project, 1, 1)
    assert (r.returncode == 1) == (failing is not None), r.stdout + r.stderr
    data = json.loads(report.read_text())
    assert isinstance(data["wall_s"], (int, float)) and data["wall_s"] >= 0
    slowest = data["slowest"]
    assert len(slowest) == 15 and {s["id"] for s in slowest} <= set(data["ran"])
    assert all(isinstance(s["id"], str) and isinstance(s["s"], (int, float)) and s["s"] >= 0 for s in slowest)
    order = [(-s["s"], s["id"]) for s in slowest]
    assert order == sorted(order), "slowest first, ties by id"
    assert all(round(s["s"], 2) == s["s"] for s in slowest) and round(data["wall_s"], 2) == data["wall_s"]


BUSY = ("import time\nimport pytest\n\n"
        "def busy(seconds):\n    end = time.monotonic() + seconds\n    while time.monotonic() < end:\n        pass\n\n"
        "@pytest.fixture()\ndef slow_both():\n    busy(0.3)\n    yield\n    busy(0.3)\n\n"
        "def test_quick():\n    assert True\n\n"
        "def test_setup_and_teardown(slow_both):\n    assert True\n")


def test_a_tests_seconds_are_setup_call_and_teardown_together_ac_185_7(tmp_path):  # AC-185.7
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text('pytest_plugins = ["sharding"]\n')
    (tmp_path / "test_busy.py").write_text(BUSY)
    r, report = shard_run(tmp_path, 1, 1)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(report.read_text())
    first, second = data["slowest"]
    assert first["id"] == "test_busy.py::test_setup_and_teardown" and first["s"] >= 0.55, data      # 0.3 setup + 0.3 teardown, call ~0
    assert second["id"] == "test_busy.py::test_quick" and second["s"] < 0.3, data
    assert data["wall_s"] >= first["s"]


def test_a_shard_with_few_tests_lists_them_all_ac_185_7(tmp_path):  # AC-185.7
    project = make_project(tmp_path, files=1, per_file=3)
    _, report = shard_run(project, 1, 1)
    assert len(json.loads(report.read_text())["slowest"]) == 3


# ---------------- AC-185.7: check-shards.py ----------------

def timed(i, wall, slowest=()):
    return {**good_reports()[i - 1], "wall_s": wall, "slowest": [{"id": t, "s": s} for t, s in slowest]}


def run_check(tmp_path, reports, *extra):
    paths = []
    for k, rep in enumerate(reports):
        p = tmp_path / f"r{k}.json"
        p.write_text(rep if isinstance(rep, str) else json.dumps(rep))
        paths.append(str(p))
    r = subprocess.run([sys.executable, str(CHECK), *extra, *paths], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout


def four_timed():
    tests = [(f"tests/cplat/test_x.py::t{n:02d}", float(n)) for n in range(1, 21)]
    return [timed(1, 70.2, tests[0:5]), timed(2, 75.1, tests[5:10]), timed(3, 68.0, tests[10:15]), timed(4, 71.3, tests[15:20])]


def test_check_shards_prints_the_suite_time_and_the_slowest_tests_ac_185_7(tmp_path):  # AC-185.7
    rc, out = run_check(tmp_path, four_timed())
    assert rc == 0, out
    lines = out.splitlines()
    assert "suite time: 284.6 s over 4 shards (slowest shard 75.1 s)" in lines
    i = lines.index("slowest tests:")
    rows = lines[i + 1:]
    assert len(rows) == 15
    assert rows[0] == "  20.0 s  tests/cplat/test_x.py::t20" and rows[-1] == "  6.0 s  tests/cplat/test_x.py::t06"


def test_a_report_without_timing_still_passes_the_coverage_check_ac_185_7(tmp_path):  # AC-185.7
    rc, out = run_check(tmp_path, good_reports())
    assert rc == 0 and "suite time" not in out, out


def test_a_report_with_timing_still_passes_the_coverage_check_ac_185_7(tmp_path):  # AC-185.7
    rc, out = run_check(tmp_path, four_timed())
    assert rc == 0 and out.splitlines()[0].startswith("OK: "), out
    assert any(ln.startswith("suite time: ") for ln in out.splitlines()), out


def test_some_reports_without_timing_make_the_suite_time_unavailable_ac_185_7(tmp_path):  # AC-185.7
    reports = four_timed()
    del reports[1]["wall_s"], reports[1]["slowest"]
    rc, out = run_check(tmp_path, reports)
    assert rc == 0 and "suite time: not available: shard 2 has no timing" in out.splitlines(), out


@pytest.mark.parametrize("bad", [{"wall_s": "fast"}, {"slowest": "x"}, {"slowest": [{"id": 1, "s": 2.0}]}, {"slowest": [{"id": "a", "s": "b"}]}],
                         ids=["wall-type", "slowest-type", "id-type", "s-type"])
def test_a_timing_field_of_the_wrong_type_is_not_a_shard_report_ac_185_7(tmp_path, bad):  # AC-185.7
    reports = four_timed()
    reports[0].update(bad)
    rc, out = run_check(tmp_path, reports)
    assert rc == 2 and "not a shard report" in out, out


def test_the_exit_code_depends_on_coverage_alone_ac_185_7(tmp_path):  # AC-185.7
    reports = four_timed()
    reports[0]["ran"] = []
    rc, out = run_check(tmp_path, reports)
    assert rc == 1 and "suite time: 284.6 s over 4 shards" in out, out


def test_timing_out_writes_the_numbers_for_the_artifact_ac_185_7(tmp_path, monkeypatch):  # AC-185.7
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "777")
    out_file = tmp_path / "suite-time.json"
    rc, out = run_check(tmp_path, four_timed(), "--timing-out", str(out_file))
    assert rc == 0, out
    data = json.loads(out_file.read_text())
    assert data["schema"] == 1 and data["suite_s"] == 284.6 and data["slowest_shard_s"] == 75.1
    assert data["shards"] == {"1": 70.2, "2": 75.1, "3": 68.0, "4": 71.3}
    assert len(data["slowest"]) == 15 and data["slowest"][0] == {"id": "tests/cplat/test_x.py::t20", "s": 20.0}
    assert data["sha"] == "abc123" and data["run_id"] == "777"


def test_timing_out_writes_nothing_without_full_timing_ac_185_7(tmp_path):  # AC-185.7
    out_file = tmp_path / "suite-time.json"
    rc, _ = run_check(tmp_path, good_reports(), "--timing-out", str(out_file))
    assert rc == 0 and not out_file.exists()


def test_ci_checks_and_keeps_the_suite_time_on_main_for_35_days_ac_185_7():  # AC-185.7
    job = ci()["jobs"]["platform-tests-cover"]
    assert "scripts/check-shards.py --timing-out suite-time.json shards/*.json" in steps_text(job)
    up = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@") and s["with"]["name"] == "cplat-suite-time")
    assert up["with"]["path"] == "suite-time.json" and up["with"]["retention-days"] == 35
    assert up["with"]["if-no-files-found"] == "ignore"
    assert "github.event_name == 'push'" in up["if"] and "refs/heads/main" in up["if"] and "always()" in up["if"]
    shard_up = next(s for s in ci()["jobs"]["platform-tests"]["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert shard_up["with"]["retention-days"] == 1


# ---------------- AC-185.8: the retro section ----------------

def suite_run(rid, created, suite_s, shard_s, slowest):
    return {"run_id": rid, "created_at": created,
            "data": {"schema": 1, "suite_s": suite_s, "slowest_shard_s": shard_s, "shards": {"1": shard_s},
                     "slowest": [{"id": t, "s": s} for t, s in slowest], "sha": None, "run_id": rid}}


def retro_runs():
    return [
        suite_run("1", "2026-10-19T08:00:00Z", 100.0, 50.0, [("t::x", 10.0), ("t::many00", 1.0)]),
        suite_run("2", "2026-10-22T08:00:00Z", 300.0, 70.0, [("t::x", 20.0)]),
        suite_run("3", "2026-10-25T23:59:59Z", 200.0, 60.0, [("t::x", 30.0), ("t::y", 50.0)]),
        suite_run("4", "2026-10-14T08:00:00Z", 400.0, 90.0, [("t::z", 99.0)]),        # W42
        suite_run("5", "2026-10-26T00:00:00Z", 999.0, 99.0, [("t::late", 99.0)]),     # W44: not in the window
    ]


def test_the_section_has_a_row_per_week_the_retro_week_first_ac_185_8():  # AC-185.8
    sec = retro_suite.section(WEEK, retro_runs())
    assert [w["week"] for w in sec["weeks"]] == ["2026-W43", "2026-W42", "2026-W41", "2026-W40"]
    assert sec["weeks"][0] == {"week": "2026-W43", "runs": 3, "median_suite_s": 200.0, "median_slowest_shard_s": 60.0}
    assert sec["weeks"][1]["runs"] == 1 and sec["weeks"][1]["median_suite_s"] == 400.0
    assert [w["runs"] for w in sec["weeks"][2:]] == [0, 0] and sec["unavailable"] is None


def test_the_slowest_tests_are_the_retro_weeks_by_median_seconds_ac_185_8():  # AC-185.8
    sec = retro_suite.section(WEEK, retro_runs())
    assert sec["slowest"][0] == {"id": "t::y", "median_s": 50.0, "runs": 1}
    assert {"id": "t::x", "median_s": 20.0, "runs": 3} in sec["slowest"]
    assert "t::z" not in {t["id"] for t in sec["slowest"]} and "t::late" not in {t["id"] for t in sec["slowest"]}


def test_at_most_fifteen_slowest_tests_ordered_by_median_then_id_ac_185_8():  # AC-185.8
    many = [(f"t::n{i:02d}", float(i)) for i in range(1, 21)]
    sec = retro_suite.section(WEEK, [suite_run("1", "2026-10-20T08:00:00Z", 10.0, 5.0, many)])
    assert [t["id"] for t in sec["slowest"]] == [f"t::n{i:02d}" for i in range(20, 5, -1)]


def test_the_rendered_section_has_the_table_and_the_numbered_tests_ac_185_8():  # AC-185.8
    text = retro_suite.render(retro_suite.section(WEEK, retro_runs()))
    lines = text.splitlines()
    assert lines[0] == "## Test suite time"
    assert "| 2026-W43 | 3 | 200.0 s | 60.0 s |" in lines
    assert "| 2026-W42 | 1 | 400.0 s | 90.0 s |" in lines
    assert any(re.fullmatch(r"\| 2026-W41 \| no data \|.*", ln) for ln in lines), text
    assert "Slowest tests of 2026-W43 (median over runs):" in lines
    assert "  1. 50.0 s  t::y (1 runs)" in lines and "  2. 20.0 s  t::x (3 runs)" in lines


def test_a_retro_week_without_runs_says_no_data_ac_185_8():  # AC-185.8
    text = retro_suite.render(retro_suite.section(WEEK, []))
    assert "Slowest tests of 2026-W43: no data" in text.splitlines()
    assert len([ln for ln in text.splitlines() if "no data" in ln]) >= 5, text


def test_unreadable_data_is_not_available_with_the_reason_ac_185_8():  # AC-185.8
    sec = retro_suite.unavailable("artifact download refused")
    assert sec["unavailable"] == "artifact download refused"
    assert retro_suite.render(sec).splitlines()[:2] == ["## Test suite time", "not available: artifact download refused"]


def test_no_test_reaches_github_through_fetch_ac_185_8():  # AC-185.8
    assert retro_suite.fetch("ika100/sdlc-foundry", dt.date(2026, 9, 28)) == []     # the conftest fake: "no runs"
    assert retro_suite.ARTIFACT == "cplat-suite-time" and retro_suite.TOP == 15


def artifact(run_id, created, branch="main", expired=False):
    return {"id": int(run_id) * 10, "name": "cplat-suite-time", "expired": expired, "created_at": created,
            "workflow_run": {"id": int(run_id), "head_branch": branch}}


def fake_gh(monkeypatch, artifacts, *, fail=None):
    """Replaces `retro_github.gh`: the artifact list as one `gh api --paginate` page, and a `suite-time.json` per `run download`."""
    import retro_github
    calls = []

    def gh(args, *, input=None, timeout=30.0):
        calls.append(list(args))
        if fail:
            return 1, "", fail
        if args[0] == "api":
            assert "cplat-suite-time" in " ".join(args)
            return 0, json.dumps({"total_count": len(artifacts), "artifacts": artifacts}), ""
        assert args[:2] == ["run", "download"]
        run_id = args[2]
        target = Path(args[args.index("-D") + 1])
        target.mkdir(parents=True, exist_ok=True)
        (target / "suite-time.json").write_text(json.dumps(suite_run(run_id, "x", 1.0, 1.0, [])["data"]))
        return 0, "", ""

    monkeypatch.setattr(retro_github, "gh", gh)
    return calls


def test_fetch_keeps_only_non_expired_main_artifacts_since_the_date_ac_185_8(monkeypatch):  # AC-185.8
    calls = fake_gh(monkeypatch, [
        artifact("11", "2026-10-20T08:00:00Z"),
        artifact("12", "2026-10-21T08:00:00Z", branch="feature/x"),
        artifact("13", "2026-10-22T08:00:00Z", expired=True),
        artifact("14", "2026-09-27T23:59:59Z"),                      # the day before `since`
        artifact("15", "2026-09-28T00:00:00Z"),                      # on `since`
    ])
    got = retro_suite.REAL_FETCH("ika100/sdlc-foundry", dt.date(2026, 9, 28))
    assert sorted(g["run_id"] for g in got) == ["11", "15"]
    by_id = {g["run_id"]: g for g in got}
    assert by_id["11"]["created_at"] == "2026-10-20T08:00:00Z" and by_id["11"]["data"]["run_id"] == "11"
    assert [c[2] for c in calls if c[:2] == ["run", "download"]] in (["11", "15"], ["15", "11"])
    assert all("-R" in c and "ika100/sdlc-foundry" in c for c in calls if c[:2] == ["run", "download"])


def test_fetch_raises_with_the_reason_when_github_fails_ac_185_8(monkeypatch):  # AC-185.8
    fake_gh(monkeypatch, [], fail="HTTP 403: rate limited")
    with pytest.raises(retro_suite.SuiteTimeError, match="rate limited"):
        retro_suite.REAL_FETCH("ika100/sdlc-foundry", dt.date(2026, 9, 28))


def retro_json(capsys, *argv):
    assert cplat.main(["platform", "retro", *argv]) == 0
    return capsys.readouterr().out


def test_the_retro_report_holds_the_section_and_fetches_the_four_week_window_ac_185_8(world, monkeypatch, capsys):  # AC-185.8
    seen = []
    import retro_suite as real
    monkeypatch.setattr(real, "fetch", lambda repo, since: seen.append((repo, since)) or retro_runs())
    report = json.loads(retro_json(capsys, "--json"))
    assert seen and seen[0][1] == dt.date(2026, 9, 28), seen
    assert report["suite_time"]["weeks"][0] == {"week": "2026-W43", "runs": 3, "median_suite_s": 200.0, "median_slowest_shard_s": 60.0}
    text = retro_json(capsys)
    assert "## Test suite time" in text and "| 2026-W43 | 3 | 200.0 s | 60.0 s |" in text


@pytest.mark.parametrize("exc", ["suite", "other"])
def test_a_failing_fetch_gives_not_available_and_does_not_fail_the_retro_ac_185_8(world, monkeypatch, capsys, exc):  # AC-185.8
    import retro_suite as real

    def boom(repo, since):
        raise real.SuiteTimeError("rate limited") if exc == "suite" else RuntimeError("rate limited")

    monkeypatch.setattr(real, "fetch", boom)
    report = json.loads(retro_json(capsys, "--json"))
    assert "rate limited" in report["suite_time"]["unavailable"]
    assert "not available: " in retro_json(capsys)
