"""Spec 112: shared renders and sharding make the cplat test job fast without making it weaker (AC-112.1 to AC-112.15).

Every import of the new modules happens inside a test, so each test fails on its own while the behaviour is missing.
Measurements (AC-112.1, .3, .7, .9, .12) are checked here by their code-checkable parts; the numbers go in the pull request.
"""
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import core

ROOT = core.PLATFORM_ROOT
TESTS = ROOT / "tests" / "cplat"
CI = ROOT / ".github" / "workflows" / "ci.yml"
CHECK = ROOT / "scripts" / "check-shards.py"


# ---------------------------------------------------------------- helpers

def ci():
    return yaml.safe_load(CI.read_text())


def steps_text(job):
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def make_project(tmp_path, files=3, per_file=5, failing=None):
    """A scratch pytest project with `files * per_file` trivial tests, using only our sharding plugin."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text('pytest_plugins = ["sharding"]\n')
    for f in range(files):
        body = ""
        for t in range(per_file):
            n = f"test_{f:02d}_{t:02d}"
            body += f"def {n}():\n    assert {n != failing!r}\n\n"
        (tmp_path / f"test_f{f}.py").write_text(body)
    return tmp_path


def run_pytest(cwd, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST")}
    env["PYTHONPATH"] = str(TESTS)
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=300)


def all_ids(project):
    r = run_pytest(project, "--collect-only", "-q")
    assert r.returncode == 0, r.stdout + r.stderr
    return sorted(line for line in r.stdout.splitlines() if "::" in line)


def shard_run(project, i, n, *extra):
    report = project / f"shard-{i}.json"
    r = run_pytest(project, "-q", "--shard", f"{i}/{n}", "--shard-report", str(report), *extra)
    return r, report


def expected(ids, i, n):
    return [x for k, x in enumerate(sorted(ids)) if k % n == i - 1]


def report(shard, total, collected, ran):
    return {"shard": shard, "total": total, "collected": collected, "ran": ran}


def check(tmp_path, *reports):
    paths = []
    for k, rep in enumerate(reports):
        p = tmp_path / f"r{k}.json"
        p.write_text(rep if isinstance(rep, str) else json.dumps(rep))
        paths.append(str(p))
    r = subprocess.run([sys.executable, str(CHECK), *paths], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


def good_reports(n=4, tests=("a::1", "a::2", "a::3", "a::4", "a::5")):
    ids = sorted(tests)
    return [report(i, n, ids, expected(ids, i, n)) for i in range(1, n + 1)]


# ---------------------------------------------------------------- SharedRenders (AC-112.2, .6, .8, .5)

def fake_build(counter, files=None):
    def build(workdir):
        counter.append(1)
        repo = workdir / "svc"
        repo.mkdir()
        (repo / "README.md").write_text("rendered\n")
        (repo / "sub").mkdir()
        (repo / "sub" / "f.txt").write_text("one\n")
        (repo / "link").symlink_to("README.md")
        return repo
    return build


def test_every_test_gets_its_own_copy_and_the_render_stays_as_rendered_ac_112_2(tmp_path):  # AC-112.2
    from shared_render import SharedRenders
    sr = SharedRenders(tmp_path / "root")
    (tmp_path / "root").mkdir()
    built = []
    a = sr.copy("k", fake_build(built), tmp_path / "a")
    (a / "README.md").write_text("changed\n")
    (a / "sub" / "f.txt").unlink()
    (a / "new.txt").write_text("x")
    b = sr.copy("k", fake_build(built), tmp_path / "b")
    assert a != b
    assert (b / "README.md").read_text() == "rendered\n"
    assert (b / "sub" / "f.txt").read_text() == "one\n"
    assert not (b / "new.txt").exists()
    assert (b / "link").is_symlink()
    assert built == [1]


def test_copy_destination_rules_ac_112_2(tmp_path):  # AC-112.2
    from shared_render import SharedRenders
    (tmp_path / "root").mkdir()
    sr = SharedRenders(tmp_path / "root")
    built = []
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sr.copy("k", fake_build(built), empty) == empty
    assert (empty / "README.md").is_file()
    taken = tmp_path / "taken"
    taken.mkdir()
    (taken / "x").write_text("x")
    with pytest.raises(FileExistsError):
        sr.copy("k", fake_build(built), taken)
    assert (taken / "x").read_text() == "x"


def test_a_render_happens_once_per_key_and_process_ac_112_8(tmp_path):  # AC-112.8
    from shared_render import SharedRenders
    (tmp_path / "root").mkdir()
    sr = SharedRenders(tmp_path / "root")
    one, two = [], []
    for n in range(5):
        sr.copy("one", fake_build(one), tmp_path / f"o{n}")
    sr.copy("two", fake_build(two), tmp_path / "t")
    assert (len(one), len(two)) == (1, 1)
    assert sr.builds == {"one": 1, "two": 1}


def test_a_new_shared_renders_builds_again_never_reusing_an_earlier_run_ac_112_5(tmp_path):  # AC-112.5
    from shared_render import SharedRenders
    built = []
    for run in ("run1", "run2"):
        (tmp_path / run).mkdir()
        SharedRenders(tmp_path / run).copy("k", fake_build(built), tmp_path / f"{run}-copy")
    assert built == [1, 1]


def test_the_session_cache_lives_only_in_the_runs_basetemp_ac_112_5(shared_renders, tmp_path_factory):  # AC-112.5
    root = Path(shared_renders.root) if hasattr(shared_renders, "root") else None
    base = tmp_path_factory.getbasetemp().resolve()
    if root is not None:
        assert base in root.resolve().parents
    text = (TESTS / "shared_render.py").read_text() + (TESTS / "conftest.py").read_text()
    assert "cache_dir" not in text and ".pytest_cache" not in text and "getcachedir" not in text
    assert "actions/cache" not in CI.read_text()


def test_a_failed_render_errors_every_dependent_with_its_message_ac_112_6(tmp_path):  # AC-112.6
    from shared_render import RenderFailed, SharedRenders
    (tmp_path / "root").mkdir()
    sr = SharedRenders(tmp_path / "root")
    calls = []

    def bad(workdir):
        calls.append(1)
        print("line one of output")
        raise RuntimeError("template broke")

    msgs = []
    for n in range(3):
        with pytest.raises(RenderFailed) as e:
            sr.copy("bad-key", bad, tmp_path / f"d{n}")
        msgs.append(str(e.value))
    assert len(set(msgs)) == 1
    assert msgs[0].startswith("shared render 'bad-key' failed: RuntimeError: template broke")
    assert "line one of output" in msgs[0]
    assert calls == [1]
    assert sr.builds == {"bad-key": 1}
    assert not (tmp_path / "d0").exists()


def test_systemexit_and_a_non_directory_result_are_failures_ac_112_6(tmp_path, capsys):  # AC-112.6
    from shared_render import RenderFailed, SharedRenders
    (tmp_path / "root").mkdir()
    sr = SharedRenders(tmp_path / "root")

    def exits(workdir):
        print("noisy")
        raise SystemExit(2)

    with pytest.raises(RenderFailed, match=r"shared render 'x' failed: SystemExit"):
        sr.copy("x", exits, tmp_path / "d1")
    with pytest.raises(RenderFailed, match=r"shared render 'y' failed"):
        sr.copy("y", lambda w: w / "missing", tmp_path / "d2")
    assert "noisy" not in capsys.readouterr().out


def test_render_failure_message_keeps_only_the_last_20_output_lines_ac_112_6(tmp_path):  # AC-112.6
    from shared_render import RenderFailed, SharedRenders
    (tmp_path / "root").mkdir()
    sr = SharedRenders(tmp_path / "root")

    def noisy(workdir):
        for n in range(50):
            print(f"out-{n}")
        raise ValueError("boom")

    with pytest.raises(RenderFailed) as e:
        sr.copy("n", noisy, tmp_path / "d")
    msg = str(e.value)
    assert "out-49" in msg and "out-30" in msg and "out-29" not in msg


def test_service_key_ac_112_2():  # AC-112.2
    from shared_render import service_key
    key, name, rest = service_key(["svc", "desc", "--no-github", "--dir", "/x/y"])
    assert name == "svc"
    assert rest == ["svc", "desc", "--no-github"]
    assert key == shlex.join(rest)
    assert service_key(["svc", "--dir", "/other", "--web"])[0] == "svc --web"
    for bad in (["svc", "d"], ["svc", "d", "--dry-run", "--dir", "/x"]):
        with pytest.raises(ValueError):
            service_key(bad)


# ---------------------------------------------------------------- the new_service fixture (AC-112.2, .4, .8)

ARGV = ["shared-probe-svc", "probe", "--no-github", "--skip-tasks"]


def test_new_service_gives_private_copies_of_one_render_ac_112_2(new_service, shared_renders, tmp_path):  # AC-112.2
    a = new_service([*ARGV, "--dir", str(tmp_path / "a")])
    b = new_service([*ARGV, "--dir", str(tmp_path / "b")])
    assert a == tmp_path / "a" / "shared-probe-svc" and b == tmp_path / "b" / "shared-probe-svc"
    assert (a / ".git").is_dir() and (b / ".git").is_dir()
    marker = a / "README.md"
    original = marker.read_text()
    marker.write_text("changed")
    (a / "extra").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=a, check=True, capture_output=True)
    assert (b / "README.md").read_text() == original
    assert not (b / "extra").exists()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=b, capture_output=True, text=True).stdout
    assert status.strip() == ""
    assert sum(shared_renders.builds.values()) >= 1
    assert all(v == 1 for v in shared_renders.builds.values())  # AC-112.8


def test_new_service_matches_what_newsvc_renders_ac_112_4(new_service, tmp_path):  # AC-112.4
    import newsvc
    copy = new_service([*ARGV, "--dir", str(tmp_path / "copy")])
    assert newsvc.main([*ARGV, "--dir", str(tmp_path / "direct")]) == 0
    direct = tmp_path / "direct" / "shared-probe-svc"

    def files(p):
        return sorted(str(f.relative_to(p)) for f in p.rglob("*") if ".git" not in f.relative_to(p).parts and f.is_file())

    assert files(copy) == files(direct)
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=copy, capture_output=True, text=True).stdout.strip()
    assert branch == "main"


def test_new_service_refuses_argv_it_cannot_share_ac_112_4(new_service, tmp_path):  # AC-112.4
    with pytest.raises(ValueError):
        new_service([*ARGV])
    with pytest.raises(ValueError):
        new_service([*ARGV, "--dry-run", "--dir", str(tmp_path)])


RENDER_SUBJECT = {
    "test_newsvc.py": None,
    "test_java_database.py": None,
}
MIGRATED = ["test_gitops.py", "fleet_world.py", "test_update_lost.py", "test_update_doctor.py", "test_rename_migration.py",
            "test_smoke_091_templates.py", "test_generated_repos.py", "test_alerts_render.py", "test_staging_093_setting.py"]


def test_render_subject_tests_still_render_from_the_template_ac_112_4():  # AC-112.4
    for name in RENDER_SUBJECT:
        text = (TESTS / name).read_text()
        assert "newsvc.main" in text, name
        assert "new_service" not in text and "shared_renders" not in text, name
    ci_extra = (TESTS / "test_ci_extra.py").read_text()
    assert "new_service" not in ci_extra
    assert "newsvc.main" in (TESTS / "test_spec_driven.py").read_text()
    assert "new_service" not in (TESTS / "test_spec_driven.py").read_text()
    # the dry-run tests of test_newsvc.py render nothing and keep calling the real thing
    assert "--dry-run" in (TESTS / "test_newsvc.py").read_text()


def test_the_render_tests_of_the_smoke_091_file_keep_newsvc_main_ac_112_4():  # AC-112.4
    text = (TESTS / "test_smoke_091_templates.py").read_text()
    start = text.index("def test_a_fresh_web_repo_has_the_playwright_scaffold_by_default_ac_091_16")
    nxt = text.find("\ndef test_", start + 10)
    body = text[start: nxt if nxt != -1 else len(text)]
    assert "newsvc.main" in body and "new_service" not in body


def test_tests_that_only_need_a_rendered_repo_get_a_shared_copy_ac_112_7():  # AC-112.7
    for name in MIGRATED:
        text = (TESTS / name).read_text()
        assert "new_service" in text or "shared_renders" in text, f"{name} does not use the shared renders"
        assert "newsvc.main" not in text, f"{name} still renders per test"


# ---------------------------------------------------------------- sharding (AC-112.1, .10, .11, .12, .15)

def test_shards_partition_the_suite_ac_112_10(tmp_path):  # AC-112.10
    project = make_project(tmp_path)
    ids = all_ids(project)
    assert len(ids) == 15
    ran = []
    for i in range(1, 5):
        r, rep = shard_run(project, i, 4)
        assert r.returncode == 0, r.stdout + r.stderr
        data = json.loads(rep.read_text(encoding="utf-8"))
        assert data["shard"] == i and data["total"] == 4
        assert data["collected"] == ids
        assert data["ran"] == expected(ids, i, 4)
        assert f"shard {i}/4: {len(expected(ids, i, 4))} of 15 tests" in r.stdout
        ran += data["ran"]
    assert sorted(ran) == ids and len(ran) == len(set(ran))  # AC-112.1: the union is the suite


def test_a_new_test_file_lands_in_a_shard_without_any_list_ac_112_11(tmp_path):  # AC-112.11
    project = make_project(tmp_path)
    before = all_ids(project)
    (project / "test_brand_new.py").write_text("def test_added():\n    assert True\n")
    ids = all_ids(project)
    assert len(ids) == len(before) + 1
    seen = []
    for i in range(1, 5):
        r, rep = shard_run(project, i, 4)
        assert r.returncode == 0, r.stdout + r.stderr
        seen += json.loads(rep.read_text())["ran"]
    assert "test_brand_new.py::test_added" in seen
    assert sorted(seen) == ids
    text = steps_text(ci()["jobs"]["platform-tests"])
    assert not re.search(r"test_\w+\.py", text)  # no file list in the job


def test_shards_are_balanced_and_spread_each_file_ac_112_12(tmp_path):  # AC-112.12
    project = make_project(tmp_path, files=2, per_file=22)
    ids = all_ids(project)
    sizes = [len(expected(ids, i, 4)) for i in range(1, 5)]
    assert max(sizes) - min(sizes) <= 1
    for i in range(1, 5):
        r, rep = shard_run(project, i, 4)
        ran = json.loads(rep.read_text())["ran"]
        assert len(ran) == sizes[i - 1]
        assert {x.split("::")[0] for x in ran} == {"test_f0.py", "test_f1.py"}


def test_a_failing_test_fails_its_shard_and_is_named_but_not_the_others_ac_112_13(tmp_path):  # AC-112.13
    project = make_project(tmp_path, failing="test_01_02")
    ids = all_ids(project)
    victim = next(x for x in ids if x.endswith("test_01_02"))
    owner = next(i for i in range(1, 5) if victim in expected(ids, i, 4))
    for i in range(1, 5):
        r, rep = shard_run(project, i, 4)
        assert json.loads(rep.read_text())["ran"] == expected(ids, i, 4)  # the report is written even on failure
        if i == owner:
            assert r.returncode == 1 and "test_01_02" in r.stdout
        else:
            assert r.returncode == 0, r.stdout


def test_shard_option_validation_ac_112_15(tmp_path):  # AC-112.15
    project = make_project(tmp_path, files=1, per_file=2)
    for bad in ("0/4", "5/4", "a/b", "2", "1/0", "-1/4"):
        r = run_pytest(project, "-q", "--shard", bad)
        assert r.returncode == 4, (bad, r.stdout, r.stderr)
        assert f"--shard must be I/N with 1 <= I <= N, got {bad}" in r.stdout + r.stderr
    r = run_pytest(project, "-q", "--shard-report", str(project / "r.json"))
    assert r.returncode == 4
    assert "--shard-report needs --shard" in r.stdout + r.stderr


def test_without_shard_everything_runs_and_nothing_is_written_ac_112_15(tmp_path):  # AC-112.15
    project = make_project(tmp_path)
    r = run_pytest(project, "-q")
    assert r.returncode == 0 and "15 passed" in r.stdout
    assert not list(project.glob("*.json"))
    assert "shard" not in r.stdout


def test_xdist_run_selects_and_reports_like_a_serial_one_ac_112_10(tmp_path):  # AC-112.10
    project = make_project(tmp_path)
    ids = all_ids(project)
    r, rep = shard_run(project, 2, 4, "-n", "2")
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(rep.read_text())
    assert data["collected"] == ids
    assert data["ran"] == expected(ids, 2, 4)


def test_relative_report_path_is_relative_to_the_start_directory_ac_112_10(tmp_path):  # AC-112.10
    project = make_project(tmp_path, files=1, per_file=3)
    r = run_pytest(project, "-q", "--shard", "1/2", "--shard-report", "out.json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((project / "out.json").read_text())["shard"] == 1


def test_the_real_suite_conftest_offers_the_shard_options_ac_112_15(tmp_path):  # AC-112.15
    out = tmp_path / "r.json"
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "tests/cplat/test_naming.py", "-q",
                        "--collect-only", "--shard", "1/3", "--shard-report", str(out)],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(out.read_text())
    assert data["shard"] == 1 and data["total"] == 3
    assert data["collected"] and data["collected"] == sorted(data["collected"])


def test_no_skip_xfail_or_deselect_is_added_by_the_new_support_code_ac_112_1():  # AC-112.1
    for name in ("shared_render.py", "sharding.py"):
        text = (TESTS / name).read_text()
        for word in ("pytest.skip", "importorskip", "xfail", "skipif"):
            assert word not in text, (name, word)


def test_reverse_order_and_single_file_runs_need_no_shared_state_ac_112_3(tmp_path):  # AC-112.3
    from shared_render import SharedRenders
    outcomes = []
    for order in itertools.permutations(["x", "y"]):
        root = tmp_path / ("-".join(order))
        root.mkdir()
        sr = SharedRenders(root)
        for key in order:
            repo = sr.copy(key, fake_build([]), root / f"copy-{key}")
            outcomes.append((key, (repo / "README.md").read_text()))
    assert set(outcomes) == {("x", "rendered\n"), ("y", "rendered\n")}


# ---------------------------------------------------------------- scripts/check-shards.py (AC-112.10)

def test_check_shards_accepts_a_complete_run_ac_112_10(tmp_path):  # AC-112.10
    code, out = check(tmp_path, *good_reports())
    assert code == 0, out
    assert out.strip() == "OK: 5 tests ran in exactly one of 4 shards"


def test_check_shards_names_a_test_that_ran_nowhere_ac_112_10(tmp_path):  # AC-112.10
    reps = good_reports()
    reps[2]["ran"] = reps[2]["ran"][1:]
    lost = good_reports()[2]["ran"][0]
    code, out = check(tmp_path, *reps)
    assert code == 1
    assert f"{lost}: ran in no shard" in out
    assert "ERROR: 1 finding(s)" in out


def test_check_shards_names_a_test_that_ran_twice_ac_112_10(tmp_path):  # AC-112.10
    reps = good_reports()
    reps[3]["ran"] = reps[3]["ran"] + ["a::1"]
    code, out = check(tmp_path, *reps)
    assert code == 1
    assert "a::1: ran in shards 1, 4" in out
    assert "ERROR: 1 finding(s)" in out


def test_check_shards_flags_a_test_that_was_not_collected_ac_112_10(tmp_path):  # AC-112.10
    reps = good_reports()
    reps[0]["ran"] = reps[0]["ran"] + ["zzz::ghost"]
    code, out = check(tmp_path, *reps)
    assert code == 1 and "zzz::ghost: ran in shard 1 but was not collected" in out


def test_check_shards_flags_missing_and_duplicate_reports_ac_112_10(tmp_path):  # AC-112.10
    reps = good_reports()
    code, out = check(tmp_path, *reps[:3])
    assert code == 1 and "missing report for shard 4/4" in out
    code, out = check(tmp_path, *reps, reps[1])
    assert code == 1 and "duplicate report for shard 2/4" in out


def test_check_shards_flags_disagreeing_reports_ac_112_10(tmp_path):  # AC-112.10
    reps = good_reports()
    reps[1]["total"] = 3
    code, out = check(tmp_path, *reps)
    assert code == 1 and "shard reports disagree on the total (4 vs 3)" in out or "(3 vs 4)" in out
    reps = good_reports()
    reps[1]["collected"] = reps[1]["collected"][:-1]
    code, out = check(tmp_path, *reps)
    assert code == 1 and "shard reports disagree on the collected tests" in out


def test_check_shards_flags_workers_that_collected_differently_ac_112_10(tmp_path):  # AC-112.10
    reps = good_reports()
    reps[2]["collected"] = None
    code, out = check(tmp_path, *reps)
    assert code == 1 and "shard 3/4: collection differed between workers" in out


def test_check_shards_exit_2_for_bad_input_ac_112_10(tmp_path):  # AC-112.10
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
    code, out = check(tmp_path, "not json at all")
    assert code == 2 and "r0.json" in out
    code, out = check(tmp_path, {"unexpected": True})
    assert code == 2 and "r0.json" in out
    r = subprocess.run([sys.executable, str(CHECK), str(tmp_path / "nope.json")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "nope.json" in r.stdout + r.stderr


# ---------------------------------------------------------------- ci.yml (AC-112.9, .10, .12, .13, .14, .15)

def test_ci_runs_the_cplat_tests_in_four_shards_ac_112_10():  # AC-112.10
    job = ci()["jobs"]["platform-tests"]
    assert job["name"] == "cplat unit + integration tests (shard ${{ matrix.shard }}/4)"
    assert job["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    text = steps_text(job)
    assert "pytest tests/cplat -q -n auto --shard ${{ matrix.shard }}/4 --shard-report shard-${{ matrix.shard }}.json" in text
    assert job["needs"] == "changes" and job["if"] == "needs.changes.outputs.code == 'true'"  # AC-112.9: starts at once


def test_ci_failure_in_one_shard_does_not_cancel_the_others_ac_112_13():  # AC-112.13
    job = ci()["jobs"]["platform-tests"]
    assert job["strategy"]["fail-fast"] is False
    text = steps_text(job)
    assert " -x" not in text and "--maxfail" not in text and "-p no:terminal" not in text


def test_ci_uploads_each_shard_report_even_when_the_shard_fails_ac_112_10():  # AC-112.10
    job = ci()["jobs"]["platform-tests"]
    up = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert up["if"] == "always()"
    assert up["with"]["name"] == "cplat-shard-${{ matrix.shard }}"
    assert up["with"]["path"] == "shard-${{ matrix.shard }}.json"
    assert up["with"]["retention-days"] == 1
    assert up["with"]["if-no-files-found"] == "ignore"


def test_ci_checks_shard_coverage_in_every_run_ac_112_10():  # AC-112.10
    job = ci()["jobs"]["platform-tests-cover"]
    assert job["name"] == "cplat shards cover the suite"
    assert job["needs"] == ["changes", "platform-tests"]
    assert job["if"] == "always() && needs.changes.outputs.code == 'true'"
    down = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/download-artifact@"))
    assert down["with"]["pattern"] == "cplat-shard-*"
    assert down["with"]["merge-multiple"] is True
    assert down["with"]["path"] == "shards"
    assert "python3 scripts/check-shards.py shards/*.json" in steps_text(job)


def test_ci_success_needs_every_shard_result_ac_112_14():  # AC-112.14
    doc = ci()
    needs = doc["jobs"]["ci-success"]["needs"]
    assert "platform-tests" in needs and "platform-tests-cover" in needs
    assert needs.index("platform-tests-cover") < needs.index("smoke-test-templates")
    assert needs[-2:] == ["spec-required", "pr-title"]
    run = steps_text(doc["jobs"]["ci-success"])
    assert 'any(. == "failure" or . == "cancelled")' in run


def test_local_ci_runs_the_suite_unsharded_ac_112_15():  # AC-112.15
    text = (ROOT / "scripts" / "ci-local.sh").read_text()
    assert "pytest tests/cplat" in text and "--shard" not in text


def test_the_pytest_command_text_ac_084_1_still_holds_ac_112_10():  # AC-112.10
    text = CI.read_text()
    assert "pytest tests/cplat -q -n auto" in text
