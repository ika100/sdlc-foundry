"""Spec 108 acceptance tests: AC-108.11, the benchmark workflow `fix-rounds` (two passes, summaries on and off). Contract: design.md,
"Benchmark `cplat platform runs benchmark fix-rounds`". No real Claude run: the module's headless run, `_children` and the usage are
replaced, as in the spec 099/103/107 benchmark tests."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import core
import runs
import runs_bench
import runs_usage
from core import PlatformError
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_runs_usage_bench import benchmark_records, tasks, world  # noqa: F401  (fixtures)
from usage_support import projects, stored_records  # noqa: F401

BENCH = core.PLATFORM_ROOT / "scripts" / "cplat" / "benchmark"


def counts(i=0, o=0, cost=0.0):
    return {"input": i, "output": o, "cache_read": 0, "cache_write": 0, "cost_usd": cost}


# the usage window of each pass: coder and quality calls are the fixing agents, the reviewer's calls are not
USAGE = [
    {"totals": counts(5000, 1000, 0.50),
     "by_role": {"svc:coder": counts(1000, 200, 0.12), "shared:quality": counts(300, 100, 0.03), "component:reviewer": counts(99999, 1, 9.0)}},
    {"totals": counts(7000, 1400, 0.84), "by_role": {"svc:coder": counts(2000, 400, 0.24), "svc:tester": counts(50000, 1, 5.0)}},
]


def child(n, rounds, gates=None):
    events = [{"id": f"fix-round:{i + 1}", "kind": "fix-round", "cause": "test", "task": None} for i in range(rounds)]
    return {"run_id": f"child-{n}", "kind": "build", "gates": gates or {"test": "passed", "lint": "passed"},
            "agents": [{"id": "svc:coder|go|sonnet", "agent": "svc:coder", "events": events},
                       {"id": "svc:tester|go|sonnet", "agent": "svc:tester", "events": [{"id": "fix-round:99", "kind": "tester"}]}]}


@pytest.fixture()
def bench(world, monkeypatch):  # noqa: F811
    """Two headless sessions: what the clone looked like at each, and the child build records / usage each one produced."""
    import headless
    inner = headless.main
    seen = SimpleNamespace(sessions=[], plan=[{"rounds": 1, "exit": 0, "gates": None}, {"rounds": 3, "exit": 0, "gates": None}],
                           children={}, passes=0)

    def fake(argv):
        clone = Path(argv[argv.index("--repo") + 1])
        settings = clone / ".platform-settings.yml"
        seen.sessions.append({"prompt": argv[-1], "settings": settings.read_text() if settings.exists() else None,
                              "spec": sorted(str(p.relative_to(clone)) for p in clone.glob("docs/specs/901-*/spec.md")),
                              "max_runs": argv[argv.index("--max-runs") + 1]})
        code = inner(argv)
        plan = seen.plan[seen.passes]
        seen.passes += 1
        seen.children[f"child-{seen.passes}"] = child(seen.passes, plan["rounds"], plan["gates"])
        return plan["exit"] or code
    monkeypatch.setattr(headless, "main", fake)
    monkeypatch.setattr(runs_bench, "_children", lambda rid: dict(seen.children))

    def for_run(rec, *, ended_at, **kw):
        return {**USAGE[max(seen.passes, 1) - 1], "price_table": "test-prices"}
    monkeypatch.setattr(runs_usage, "for_run", for_run)
    world.seen = seen
    return world


def test_the_fix_rounds_workflow_is_a_fixed_task_with_a_seed_ac_108_11():  # AC-108.11
    t = tasks()["workflows"]["fix-rounds"]
    assert t["task_version"] == 1 and t["prompt"] == "/component:build 901" and t["max_runs"] == 2 and t["max_minutes"] == 90
    assert t["seed"] == "seeds/fix-rounds.json" and "spec_file" not in t
    assert runs_bench.EXPECTED["fix-rounds"] == "open"


def test_the_seed_starts_a_finished_build_with_one_failing_test_and_one_lint_finding_ac_108_11():  # AC-108.11
    seed = json.loads((BENCH / "seeds" / "fix-rounds.json").read_text())
    assert seed["name"] and all(isinstance(k, str) and isinstance(v, str) for k, v in seed["files"].items()), "arm-shaped, strings only"
    files = seed["files"]
    (spec,) = [k for k in files if k.startswith("docs/specs/901-") and k.endswith("/spec.md")]
    plan = spec.replace("spec.md", "plan.md")
    assert "status: approved" in files[spec] and "AC-901.1" in files[spec]
    assert plan in files and "done: true" in files[plan]
    assert any(k.startswith("tests/") and "AC-901.1" in v for k, v in files.items()), "the tagged acceptance test"
    assert any(k.startswith("src/") for k in files), "the pinned sample is changed so that one test fails"
    assert ".platform-settings.yml" not in files, "only the pass without summaries adds the setting"
    assert "F401" in json.dumps(files) or "import " in json.dumps(files)


def test_two_passes_run_the_same_build_with_the_setting_added_in_the_second_ac_108_11(bench, store):  # AC-108.11
    assert runs.main(["benchmark", "fix-rounds"]) == 0
    on, off = bench.seen.sessions
    assert on["prompt"] == off["prompt"] == "/component:build 901" and on["max_runs"] == "2"
    assert on["settings"] is None and off["settings"] == "failure_summary: off\n"
    assert len(on["spec"]) == 1 and on["spec"] == off["spec"], "the seed (spec 901) is in the clone in both passes"
    pushes = [c for c in bench.log if "push" in c and "--force" not in c]
    assert len(pushes) == 2, "the seed goes to main before each pass"


def test_both_passes_are_reported_and_recorded_ac_108_11(bench, store, capsys):  # AC-108.11
    assert runs.main(["benchmark", "fix-rounds"]) == 0
    out = capsys.readouterr().out
    assert "  summaries on: done, fix rounds 1, fixing agents 1600 tokens est. USD 0.15, total 6000 tokens est. USD 0.50" in out.splitlines()
    assert "  summaries off: done, fix rounds 3, fixing agents 2400 tokens est. USD 0.24, total 8400 tokens est. USD 0.84" in out.splitlines()
    assert out.index("benchmark fix-rounds v1") < out.index("summaries on:") < out.index("summaries off:")
    (r,) = benchmark_records(store)
    cmp = r["benchmark"]["summary_compare"]
    assert cmp["verdict"] is None and len(cmp["passes"]) == 2
    on, off = cmp["passes"]
    assert (on["outcome"], on["fix_rounds"], on["gates_failed"]) == ("done", 1, [])
    assert (off["outcome"], off["fix_rounds"], off["gates_failed"]) == ("done", 3, [])
    assert on["fixing"]["tokens"] == 1600 and on["total"]["tokens"] == 6000 and off["fixing"]["tokens"] == 2400
    assert float(on["fixing"]["cost_usd"]) == pytest.approx(0.15) and float(off["total"]["cost_usd"]) == pytest.approx(0.84)
    assert r["benchmark"]["workflow"] == "fix-rounds" and r["benchmark"]["task_version"] == 1


def test_equal_fix_rounds_are_no_failure_and_there_is_no_savings_target_ac_108_11(bench, store, capsys):  # AC-108.11
    bench.seen.plan[0]["rounds"] = bench.seen.plan[1]["rounds"] = 2
    assert runs.main(["benchmark", "fix-rounds"]) == 0
    assert "  summaries: " not in capsys.readouterr().out


@pytest.mark.parametrize("name,plan_on,plan_off,reason", [
    ("not-done", {"rounds": 1, "exit": 1, "gates": None}, {"rounds": 1, "exit": 0, "gates": None}, "summaries pass not done"),
    ("gate", {"rounds": 1, "exit": 0, "gates": {"test": "failed", "lint": "passed"}}, {"rounds": 1, "exit": 0, "gates": None},
     "gate failed with summaries: test"),
    ("more-rounds", {"rounds": 3, "exit": 0, "gates": None}, {"rounds": 1, "exit": 0, "gates": None},
     "more fix rounds with summaries (3) than without (1)"),
])
def test_the_exit_is_non_zero_only_for_the_three_conditions_and_the_record_is_written_ac_108_11(bench, store, capsys, name, plan_on,
                                                                                               plan_off, reason):  # AC-108.11
    bench.seen.plan[:] = [plan_on, plan_off]
    assert runs.main(["benchmark", "fix-rounds"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert f"  summaries: {reason}" in out
    assert any(ln.startswith("  summaries on: ") for ln in out) and any(ln.startswith("  summaries off: ") for ln in out), "both passes ran"
    (r,) = benchmark_records(store)
    assert r["benchmark"]["summary_compare"]["verdict"] == reason and len(r["benchmark"]["summary_compare"]["passes"]) == 2


@pytest.mark.parametrize("extra", [["--compare-validation"], ["--arm", "__first__"]])
def test_the_arm_and_the_validation_comparison_are_refused_for_fix_rounds_ac_108_11(bench, store, capsys, extra):  # AC-108.11
    extra = [sorted((BENCH / "arms").glob("*.json"))[0].stem if a == "__first__" else a for a in extra]
    with pytest.raises((PlatformError, SystemExit)) as e:
        runs.main(["benchmark", "fix-rounds", *extra])
    said = str(e.value) + capsys.readouterr().err
    assert "fix-rounds" in said and "invalid choice" not in said
    assert bench.headless_calls == [] and benchmark_records(store) == []
