"""Spec 136 AC-136.8: `cplat platform runs report --benchmarks` shows the journey per platform version and coordinator model:
per stage, part and journey the median working time and wall clock of done runs, the budget, the overrun, the median
person-wait, external wait and PR count, the previous version's median, the stages ranked by overrun; `--json` key `journey`."""
import pytest

import runs
from test_runs import clock, mem, store  # noqa: F401  (fixtures)
from test_runs_report import put, rec, report_json

STAGES = [("1.scaffold", 1, 2), ("1.cluster", 1, 2), ("1.spec", 1, 3), ("1.plan", 1, 2), ("1.build", 1, 10), ("1.pr-ci", 1, 3),
          ("1.deploy-dev", 1, 2), ("2.scaffold", 2, 2), ("2.spec", 2, 5), ("2.plan", 2, 3), ("2.build", 2, 12),
          ("2.pr-ci", 2, 3), ("2.deploy-dev", 2, 2), ("3.env-settings", 3, 2), ("3.staging-prod", 3, 8)]
PART_BUDGET = {1: 20, 2: 30, 3: 10}


def times(working, wall=None, person=0.0, external=0.0, prs=0):
    return {"wall_minutes": wall if wall is not None else working + person, "working_minutes": working,
            "person_wait_minutes": person, "external_wait_minutes": external, "prs": prs}


NOT_RUN = {"wall_minutes": None, "working_minutes": None, "person_wait_minutes": None, "external_wait_minutes": None, "prs": 0}


def journey(rid, *, version="5.9.1", model="opus", outcome="done", day=20, stages=None, parts=None, total=None):
    """A journey record; `stages` maps stage id → times() (missing stages are not run)."""
    stages = stages or {}
    st = [{"id": sid, "part": p, "status": "done" if sid in stages else "not run", "budget_minutes": b,
           "started_at": None, "ended_at": None, "extra_rounds": [], "pr_urls": [], **stages.get(sid, NOT_RUN)}
          for sid, p, b in STAGES]
    pt = [{"part": n, "status": "done" if (parts or {}).get(n) else "not run", "budget_minutes": PART_BUDGET[n],
           "extra_rounds": 0, "stages_sum_minutes": None, "overlap_minutes": None, **(parts or {}).get(n, NOT_RUN)}
          for n in (1, 2, 3)]
    tot = {"status": "done" if total else "not run", "budget_minutes": 60, "interim_minutes": 90, "stretch_minutes": 50,
           "extra_rounds": 0, **(total or NOT_RUN)}
    r = rec(rid, f"2026-10-{day}T12:00:00Z", kind="journey", outcome=outcome, repo=None,
            journey={"schema": 1, "task_version": 1, "coordinator_model": model, "stages": st, "parts": pt, "total": tot,
                     "waits": []})
    r["platform_version"] = version
    return r


def row(out, key, sid):
    return next(s for s in out["journey"][key]["stages"] if s["id"] == sid)


def test_per_stage_the_median_working_and_wall_of_done_runs_with_budget_overrun_and_waits_ac_136_8(store, clock, capsys):  # AC-136.8
    put(store, journey("a", stages={"2.build": times(16, wall=26, person=10, external=1, prs=1)}))
    put(store, journey("b", stages={"2.build": times(18, wall=19, person=1, external=3, prs=3)}))
    put(store, journey("c", stages={"2.build": times(14, wall=14, person=0, external=2, prs=1)}))
    put(store, journey("x", outcome="failed", stages={"2.build": times(90, wall=95, person=5, external=40, prs=9)}))
    out = report_json(capsys, "--benchmarks")
    g = out["journey"]["5.9.1 (opus)"]
    assert g["platform_version"] == "5.9.1" and g["coordinator_model"] == "opus"
    assert g["runs"] == 4 and g["done"] == 3 and g["outcomes"] == {"done": 3, "failed": 1}
    b = row(out, "5.9.1 (opus)", "2.build")
    assert b["runs"] == 3 and b["part"] == 2
    assert b["working_median"] == 16 and b["wall_median"] == 19                     # two separate columns, failed run left out
    assert b["budget_minutes"] == 12 and b["overrun_minutes"] == 4
    assert b["person_wait_median"] == 1 and b["external_wait_median"] == 2 and b["prs_median"] == 1


def test_parts_and_the_whole_journey_get_the_same_columns_ac_136_8(store, clock, capsys):  # AC-136.8
    put(store, journey("a", parts={1: times(30, wall=40, person=10, prs=4)}, total=times(100, wall=130, person=30, external=8, prs=20)))
    put(store, journey("b", parts={1: times(22, wall=22, prs=2)}, total=times(80, wall=90, person=10, external=4, prs=16)))
    out = report_json(capsys, "--benchmarks")
    g = out["journey"]["5.9.1 (opus)"]
    p1 = next(p for p in g["parts"] if p["part"] == 1)
    assert p1["working_median"] == 26 and p1["wall_median"] == 31 and p1["budget_minutes"] == 20 and p1["overrun_minutes"] == 6
    assert p1["person_wait_median"] == 5 and p1["prs_median"] == 3
    p2 = next(p for p in g["parts"] if p["part"] == 2)
    assert p2["runs"] == 0 and p2["working_median"] is None                          # part 2 never ran
    t = g["total"]
    assert t["working_median"] == 90 and t["wall_median"] == 110 and t["budget_minutes"] == 60 and t["overrun_minutes"] == 30
    assert t["person_wait_median"] == 20 and t["external_wait_median"] == 6 and t["prs_median"] == 18


def test_stages_are_ranked_by_median_overrun_largest_first_ac_136_8(store, clock, capsys):  # AC-136.8
    stages = {"1.scaffold": times(3), "1.build": times(17), "2.build": times(13), "3.staging-prod": times(15), "1.plan": times(1)}
    put(store, journey("a", stages=stages))
    out = report_json(capsys, "--benchmarks")
    ranked = [s["id"] for s in out["journey"]["5.9.1 (opus)"]["stages"]]
    assert ranked[:5] == ["1.build", "3.staging-prod", "1.scaffold", "2.build", "1.plan"]   # 7, 7, 1, 1, -1; ties in table order
    assert [s["overrun_minutes"] for s in out["journey"]["5.9.1 (opus)"]["stages"][:5]] == [7, 7, 1, 1, 0]
    assert len(ranked) == 15 and ranked[5:] == [sid for sid, _, _ in STAGES if sid not in stages]   # stages that never ran last


def test_the_previous_platform_versions_median_stands_next_to_it_ac_136_8(store, clock, capsys):  # AC-136.8
    put(store, journey("old", version="5.9.0", stages={"2.build": times(30, wall=40)}, total=times(200, wall=250)))
    put(store, journey("mid", version="5.9.1", stages={"2.build": times(20, wall=25)}, total=times(150, wall=160)))
    put(store, journey("new", version="5.10.0", stages={"2.build": times(15, wall=15)}, total=times(100, wall=110)))
    put(store, journey("other", version="5.9.2", model="sonnet", stages={"2.build": times(1)}))   # another model: never the previous
    out = report_json(capsys, "--benchmarks")
    new = out["journey"]["5.10.0 (opus)"]
    assert new["previous_version"] == "5.9.1"                                         # numeric, not text order
    assert row(out, "5.10.0 (opus)", "2.build")["previous"] == {"working_median": 20, "wall_median": 25}
    assert new["total"]["previous"] == {"working_median": 150, "wall_median": 160}
    assert out["journey"]["5.9.1 (opus)"]["previous_version"] == "5.9.0"
    assert out["journey"]["5.9.0 (opus)"]["previous_version"] is None
    assert row(out, "5.9.0 (opus)", "2.build")["previous"] is None


def test_each_coordinator_model_is_its_own_group_ac_136_8(store, clock, capsys):  # AC-136.8
    put(store, journey("o", model="opus", stages={"1.spec": times(4)}))
    put(store, journey("s", model="sonnet", stages={"1.spec": times(6)}))
    out = report_json(capsys, "--benchmarks")
    assert set(out["journey"]) == {"5.9.1 (opus)", "5.9.1 (sonnet)"}
    assert row(out, "5.9.1 (sonnet)", "1.spec")["working_median"] == 6


def test_a_stage_that_did_not_run_is_left_out_of_its_median_ac_136_8(store, clock, capsys):  # AC-136.8
    put(store, journey("a", stages={"1.cluster": times(4)}))
    put(store, journey("b", stages={}))
    out = report_json(capsys, "--benchmarks")
    c = row(out, "5.9.1 (opus)", "1.cluster")
    assert c["runs"] == 1 and c["working_median"] == 4


def test_the_existing_keys_are_unchanged_and_journey_is_added_ac_136_8(store, clock, capsys):  # AC-136.8
    put(store, journey("a", stages={"1.spec": times(4)}))
    out = report_json(capsys, "--benchmarks")
    assert list(out) == ["window", "price_tables", "benchmarks", "journey"]
    assert out["benchmarks"] == {} and out["price_tables"] == []                      # a journey is not a benchmark row


def test_the_text_report_has_the_journey_table_with_working_and_wall_columns_ac_136_8(store, clock, capsys):  # AC-136.8
    put(store, journey("old", version="5.9.0", stages={"2.build": times(30, wall=40)}, total=times(200, wall=250)))
    put(store, journey("a", stages={"2.build": times(16, wall=19, person=3, external=2, prs=1), "1.spec": times(2)},
                       total=times(100, wall=130)))
    assert runs.main(["report", "--benchmarks"]) == 0
    text = capsys.readouterr().out
    assert "Journey 5.9.1 (opus): 1 run(s), 1 done" in text
    header = next(line for line in text.splitlines() if "working" in line and "wall" in line)
    for column in ("stage", "working", "wall", "budget", "over", "person", "external", "PRs", "prev 5.9.0"):
        assert column in header, column
    lines = text.splitlines()
    build = next(i for i, line in enumerate(lines) if line.strip().startswith("2.build"))
    spec = next(i for i, line in enumerate(lines) if line.strip().startswith("1.spec"))
    assert build < spec                                                               # ranked by overrun
    assert "30" in lines[build] and "40" in lines[build]                              # the previous version's medians
    assert any(line.strip().startswith("journey") for line in lines)


def test_no_journey_record_says_so_ac_136_8(store, clock, capsys):  # AC-136.8
    assert runs.main(["report", "--benchmarks"]) == 0
    assert "Journey: none" in capsys.readouterr().out
    assert report_json(capsys, "--benchmarks")["journey"] == {}


def test_a_recorded_journey_shows_up_in_the_report_ac_136_8(store, clock, capsys):  # AC-136.8
    clock.set("2026-10-24T12:00:00Z")
    runs.main(["journey", "begin", "--model", "opus", "--at", "2026-10-24T10:00:00Z"])
    runs.main(["journey", "stage", "1.build", "start", "--at", "2026-10-24T10:00:00Z"])
    runs.main(["journey", "stage", "1.build", "end", "--at", "2026-10-24T10:14:00Z"])
    runs.main(["journey", "end", "--outcome", "done", "--at", "2026-10-24T10:14:00Z"])
    capsys.readouterr()
    out = report_json(capsys, "--benchmarks")
    (key,) = out["journey"]
    assert key.endswith("(opus)")
    b = row(out, key, "1.build")
    assert b["working_median"] == pytest.approx(14.0) and b["overrun_minutes"] == pytest.approx(4.0)
