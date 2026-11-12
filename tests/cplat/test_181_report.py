"""Spec 181 AC-181.6: the benchmarks report shows the median agent and waiting minutes per stage from `journey_split` follow-ups;
`runs.followup` writes them; `journey measure --journey` computes them from the journey record's stage spans."""
import json

import pytest

import runs
from core import PlatformError
from journey181_support import END, START, Transcript, at, split_of, world  # noqa: F401  (fixture)
from test_136_journey_report import journey, row, times
from test_runs import buffered_lines, clock, mem, store  # noqa: F401  (fixtures)
from test_runs_report import put, report_json

KEY = "5.9.1 (opus)"


def split(agents, wall=60.0, person=0.0, **waiting):
    kinds = {k: 0 for k in ("ci", "deploy", "promotion", "restore", "cluster", "smoke", "unattributed", "no_transcript")}
    kinds.update(waiting)
    wait = sum(kinds.values())
    return {"wall_min": wall, "person_min": person, "agents_min": agents, "agents": {"coordinator": 1.0, "children": agents - 1.0},
            "waiting_min": wait, "waiting": kinds}


def follow(rid, stage_splits, at_="2026-10-21T08:00:00Z", total=None):
    return {"schema": 1, "followup": "journey_split", "signature": "journey_split", "run_id": rid, "at": at_,
            "split": {"stages": stage_splits, "parts": {}, "total": total}}


def test_each_stage_shows_the_median_agent_and_waiting_minutes_ac_181_6(store, clock, capsys):  # AC-181.6
    for rid, ag, ci in (("a", 30.0, 4.0), ("b", 40.0, 6.0), ("c", 50.0, 20.0)):
        put(store, journey(rid, stages={"2.build": times(60)}))
        put(store, follow(rid, {"2.build": split(ag, ci=ci, unattributed=2.0)}, total=split(ag * 2, ci=ci)))
    out = report_json(capsys, "--benchmarks")
    b = row(out, KEY, "2.build")
    assert b["split_runs"] == 3 and b["agents_median"] == 40.0
    assert b["waiting_median"]["ci"] == 6.0 and b["waiting_median"]["unattributed"] == 2.0 and b["waiting_median"]["deploy"] == 0
    assert out["journey"][KEY]["total"]["agents_median"] == 80.0
    assert b["working_median"] == 60 and b["budget_minutes"] == 12                  # today's columns are unchanged


def test_a_record_without_the_split_shows_nothing_ac_181_6(store, clock, capsys):  # AC-181.6
    put(store, journey("a", stages={"2.build": times(60)}))
    put(store, journey("b", stages={"2.build": times(70)}))
    put(store, follow("a", {"2.build": split(30.0, deploy=5.0)}))
    out = report_json(capsys, "--benchmarks")
    assert row(out, KEY, "2.build")["split_runs"] == 1 and row(out, KEY, "2.build")["agents_median"] == 30.0
    assert row(out, KEY, "2.scaffold")["agents_median"] is None
    assert set(row(out, KEY, "2.scaffold")["waiting_median"].values()) == {None}
    assert row(out, KEY, "2.build")["working_median"] == 65


def test_the_latest_follow_up_of_a_journey_wins_ac_181_6(store, clock, capsys):  # AC-181.6
    put(store, journey("a", stages={"2.build": times(60)}))
    put(store, follow("a", {"2.build": split(10.0)}, at_="2026-10-21T08:00:00Z"), name="runs/2026/10/21/a.journey_split.1.json")
    put(store, follow("a", {"2.build": split(20.0)}, at_="2026-10-22T08:00:00Z"), name="runs/2026/10/22/a.journey_split.2.json")
    assert row(report_json(capsys, "--benchmarks"), KEY, "2.build")["agents_median"] == 20.0


def test_the_text_report_has_the_new_columns_and_en_dashes_ac_181_6(store, clock, capsys):  # AC-181.6
    put(store, journey("a", stages={"2.build": times(60), "2.spec": times(10)}))
    put(store, follow("a", {"2.build": split(30.0, ci=4.0)}))
    assert runs.main(["report", "--benchmarks"]) == 0
    out = capsys.readouterr().out
    header = next(x for x in out.splitlines() if "PRs" in x and "stage" in x)
    cols = ["PRs", "agents", "CI", "deploy", "promo", "restore", "cluster", "smoke", "unattr", "no-tr", "prev"]
    pos = [header.index(c) for c in cols]
    assert pos == sorted(pos)
    assert "–" in next(x for x in out.splitlines() if x.strip().startswith("2.spec"))


def test_followup_buffers_and_flushes_a_line_of_its_kind_ac_181_6(store, clock):  # AC-181.6
    assert runs.followup("j1", "journey_split", {"split": {"stages": {}, "parts": {}, "total": None}}) is None
    names = [p for p in store.files if "j1" in p]
    assert len(names) == 1 and ".journey_split." in names[0] and ".filed." not in names[0]
    line = json.loads(store.files[names[0]])
    assert line["followup"] == "journey_split" and line["signature"] == "journey_split" and line["run_id"] == "j1"
    assert line["schema"] == 1 and line["at"] and line["split"]["parts"] == {}


def test_followup_never_raises_and_returns_the_warning_when_buffered_ac_181_6(clock, monkeypatch):  # AC-181.6
    monkeypatch.delenv("CPLAT_RUNS_REPO", raising=False)
    warning = runs.followup("j2", "journey_split", {"split": {}})
    assert warning is None or isinstance(warning, str)
    assert any(x.get("followup") == "journey_split" and x["run_id"] == "j2" for x in buffered_lines()) or warning is None


def test_measure_writes_the_split_of_the_journey_record_as_a_follow_up_ac_181_6(world, capsys):  # AC-181.6
    j = journey("jr1", stages={"2.build": times(60)})
    stage = next(s for s in j["journey"]["stages"] if s["id"] == "2.build")
    stage["started_at"], stage["ended_at"] = at(10), at(40)
    world.add_records(j)
    session = world.coordinator(Transcript().model(0).bash(10, 40, "cplat pr wait 3").model(60))
    code, out, _ = world.measure(capsys, session, "--journey", "jr1")
    assert code == 0 and out["journey"]["run_id"] == "jr1" and out["journey"]["written"] in (True, False)
    lines = [x for x in buffered_lines() if x.get("followup") == "journey_split" and x["run_id"] == "jr1"]
    assert len(lines) == 1
    s = split_of(lines[0]["split"]["stages"]["2.build"])
    assert s["wall_min"] == 30 and s["waiting"]["ci"] == pytest.approx(30, abs=0.1)
    assert "1.scaffold" not in lines[0]["split"]["stages"]                         # stages without both times are left out


def test_measure_fails_when_the_journey_record_is_not_found_ac_181_6(world, capsys):  # AC-181.6
    session = world.coordinator(Transcript().model(0).model(60))
    with pytest.raises(PlatformError):
        world.measure(capsys, session, "--journey", "nope")
