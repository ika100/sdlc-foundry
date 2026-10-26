"""Spec 103 review fixes: spec files are mandatory, reuse is anchored to the merge base, run counts, final-gate misses."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import runs
import ship
from test_validate import by_name, compare, env, git, mapped_change, plan, section, vrun, write  # noqa: F401  (fixtures)
from test_runs_usage_bench import world  # noqa: F401  (fixture)
from usage_support import projects  # noqa: F401  (fixture)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

PLUGINS = Path(__file__).resolve().parents[2] / "plugins" / "component"


def test_every_file_under_docs_specs_is_mandatory_category_spec(env, capsys):
    """AC-103.3: plan.md and design.md under docs/specs are spec files, not documentation."""
    for name in ("plan.md", "design.md"):
        write(env.repo, {f"docs/specs/900-x/{name}": (env.repo / f"docs/specs/900-x/{name}").read_text() + "\nx\n"
                         if (env.repo / f"docs/specs/900-x/{name}").exists() else "x\n"})
    c = by_name(plan(capsys))
    assert c["test"]["rule"] == "mandatory:spec" and c["test"]["targets"] is None and c["security"]["decision"] == "run"


def test_a_rebase_onto_a_moved_base_does_not_reuse_an_earlier_pass(env, capsys):
    """AC-103.6: the merge base is part of the reuse hash."""
    mapped_change(env)
    git(env.repo, "commit", "-qam", "change")
    assert vrun() == 0
    assert by_name(plan(capsys))["test"]["decision"] == "reused"
    git(env.repo, "switch", "-q", "main")
    write(env.repo, {"other.txt": "x\n"})
    git(env.repo, "add", "-A")
    git(env.repo, "commit", "-qm", "main moves")
    git(env.repo, "switch", "-q", "work")
    git(env.repo, "rebase", "-q", "main")
    assert by_name(plan(capsys))["test"]["decision"] == "run"


def test_a_head_change_does_not_reuse_a_whole_suite_check(env, capsys):
    """AC-103.6: a full-suite check also hashes HEAD."""
    write(env.repo, {"Dockerfile": "FROM python\n"})
    git(env.repo, "add", "-A")
    git(env.repo, "commit", "-qm", "docker")
    assert vrun() == 0
    assert by_name(plan(capsys))["test"]["decision"] == "reused"
    git(env.repo, "commit", "-q", "--allow-empty", "-m", "empty")
    assert by_name(plan(capsys))["test"]["decision"] == "run"


def test_run_prints_counts_and_records_checks_after_a_red_one_as_not_started(env, capsys):
    """AC-103.7: counts at the end; checks that never started are `not started`, never `run`."""
    mapped_change(env)
    env.mp.setenv("DEVBOX_FAIL", "test")
    capsys.readouterr()
    assert vrun() == 1
    out = capsys.readouterr().out
    assert "not started 2" in out and "run 2" in out
    v = section(env)
    names = {c["name"]: c["decision"] for c in v["checks"]}
    assert names["acceptance"] == "not started" and names["security"] == "not started" and names["test"] == "run"
    assert v["counts"] == {"run": 2, "reused": 0, "skipped": 0, "not started": 2}


def test_green_run_prints_counts(env, capsys):
    """AC-103.7: run N, reused N, skipped N."""
    mapped_change(env)
    capsys.readouterr()
    assert vrun() == 0
    assert "run 4, reused 0, skipped 0" in capsys.readouterr().out


def test_build_and_ship_pass_full_and_record_final_results():
    """AC-103.9 / AC-103.10: the commands take --full and record failed final-gate checks."""
    build, shipmd = [(PLUGINS / "commands" / n).read_text() for n in ("build.md", "ship.md")]
    assert "`--full`" in build and "cplat validate run" in build and "cplat validate final --check" in build
    assert "`--full`" in shipmd
    red = next(line for line in build.splitlines() if line.startswith("2. **Red**"))
    assert "cplat validate final --check" in red   # the first red final gate records its misses too


def test_ship_land_records_a_red_ci_check_as_a_miss_when_the_loop_skipped_it(env, monkeypatch):
    """AC-103.10: a red `test (pytest + coverage)` job is a miss for the rule that skipped `test`; an unmapped job records nothing."""
    write(env.repo, {"README.md": "# demo\nmore\n"})
    assert vrun() == 0
    monkeypatch.setattr(ship, "require_state", lambda repo: {"pr": "u/1", "run_id": env.rid})
    monkeypatch.setattr(ship, "gh", lambda *a, **k: '{"state": "OPEN"}')
    monkeypatch.setattr(ship, "save_state", lambda *a, **k: None)
    monkeypatch.setattr(ship, "failure_logs", lambda *a, **k: [])
    failed = [{"name": "test (pytest + coverage)"}, {"name": "some other job"}]
    monkeypatch.setattr(ship, "wait_checks", lambda *a, **k: ("red", failed, failed))
    ok, _ = ship.land(env.repo, timeout=1, interval=1)
    assert not ok
    assert section(env)["misses"] == [{"check": "test", "rule": "docs-only"}] or \
        {"check": "test", "rule": "docs-only"} in section(env)["misses"]
    assert all(m["check"] in ("test", "acceptance") for m in section(env)["misses"])


def test_final_gate_rerun_that_times_out_is_noted_and_no_miss(env, monkeypatch):
    """The per-check rerun after a red final gate has a timeout; hitting it records `timed out` and no miss."""
    import validate
    write(env.repo, {"README.md": "# demo\nmore\n"})
    assert vrun() == 0

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("devbox", 1)
    monkeypatch.setattr(validate.subprocess, "run", boom)
    validate.record_final_gate(env.repo)
    v = section(env)
    assert v["misses"] == [] and any(c.get("final") == "timed out" for c in v["checks"])


def test_compare_validation_with_no_recorded_checks_fails(compare, store, monkeypatch, capsys):  # noqa: F811
    """Deviation 2: a change-aware pass that recorded no validation exits non-zero."""
    real = runs.set_section
    monkeypatch.setattr(runs, "set_section", lambda rid, name, value: None if name == "validation" else real(rid, name, value))
    assert runs.main(["benchmark", "quick-task", "--compare-validation"]) != 0
    assert "no validation recorded" in capsys.readouterr().out
