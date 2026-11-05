"""Spec 136: a journey run records every stage with wall-clock, working, person-wait and external-wait minutes, its PRs and
extra rounds (AC-136.1); parts are spans over overlapping stages (AC-136.2); person and external waits (AC-136.3).
Driven through `cplat platform runs journey …` with a fake clock and an in-memory run store."""
import subprocess

import pytest

import core
import runs
from core import PlatformError
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

STAGE_IDS = ["1.scaffold", "1.cluster", "1.spec", "1.plan", "1.build", "1.pr-ci", "1.deploy-dev",
             "2.scaffold", "2.spec", "2.plan", "2.build", "2.pr-ci", "2.deploy-dev",
             "3.env-settings", "3.staging-prod"]
TIME_FIELDS = ("started_at", "ended_at", "wall_minutes", "working_minutes", "person_wait_minutes", "external_wait_minutes",
               "budget_minutes", "prs", "extra_rounds")


def j(*args):
    return runs.main(["journey", *args])


def at(hm: str) -> list[str]:
    return ["--at", f"2026-10-24T{hm}:00Z"]


def stage(sid, start, end):
    j("stage", sid, "start", *at(start))
    j("stage", sid, "end", *at(end))


def journey_record(s):
    recs = [r for r in stored(s) if r.get("kind") == "journey"]
    assert len(recs) == 1, recs
    return recs[0]


def by_id(rec):
    return {st["id"]: st for st in rec["journey"]["stages"]}


def part(rec, n):
    return next(p for p in rec["journey"]["parts"] if p["part"] == n)


def test_a_finished_journey_lists_every_stage_with_its_time_fields_prs_and_rounds_ac_136_1(store, clock):  # AC-136.1
    clock.set("2026-10-24T12:00:00Z")
    assert j("begin", "--task-version", "2", "--model", "opus", *at("10:00")) == 0
    stage("1.scaffold", "10:00", "10:03")
    j("pr", "https://github.com/acme/demo-gitops/pull/1", "--stage", "1.scaffold")
    j("pr", "https://github.com/acme/demo-gitops/pull/1", "--stage", "1.scaffold")       # the same PR counts once
    j("pr", "https://github.com/acme/demo-api/pull/1", "--stage", "1.scaffold")
    j("round", "ci-rerun", "--cause", "environment", "--stage", "1.scaffold", "--note", "runner queue")
    assert j("end", "--outcome", "done", *at("10:05")) == 0
    rec = journey_record(store)
    assert rec["outcome"] == "done"
    jr = rec["journey"]
    assert jr["task_version"] == 2 and jr["coordinator_model"] == "opus"
    assert [st["id"] for st in jr["stages"]] == STAGE_IDS
    sc = by_id(rec)["1.scaffold"]
    for field in TIME_FIELDS + ("part", "status"):
        assert field in sc, field
    assert sc["part"] == 1 and sc["status"] == "done"
    assert sc["started_at"] == "2026-10-24T10:00:00Z" and sc["ended_at"] == "2026-10-24T10:03:00Z"
    assert sc["wall_minutes"] == 3.0 and sc["working_minutes"] == 3.0
    assert sc["person_wait_minutes"] == 0.0 and sc["external_wait_minutes"] == 0.0
    assert sc["budget_minutes"] == 2 and sc["prs"] == 2
    assert sc["extra_rounds"] == [{"kind": "ci-rerun", "cause": "environment", "note": "runner queue"}]


def test_every_stage_carries_the_budget_of_the_spec_table_ac_136_1(store, clock):  # AC-136.1
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    j("end", "--outcome", "abandoned", *at("10:01"))
    budgets = {sid: st["budget_minutes"] for sid, st in by_id(journey_record(store)).items()}
    assert budgets == {"1.scaffold": 2, "1.cluster": 2, "1.spec": 3, "1.plan": 2, "1.build": 10, "1.pr-ci": 3,
                       "1.deploy-dev": 2, "2.scaffold": 2, "2.spec": 5, "2.plan": 3, "2.build": 12, "2.pr-ci": 3,
                       "2.deploy-dev": 2, "3.env-settings": 2, "3.staging-prod": 8}


def test_parts_and_the_journey_get_the_same_time_fields_ac_136_1(store, clock):  # AC-136.1
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    stage("1.scaffold", "10:00", "10:02")
    j("pr", "https://github.com/acme/a/pull/1", "--stage", "1.scaffold")
    j("round", "fix-round", "--cause", "code", "--stage", "1.scaffold")
    stage("1.spec", "10:02", "10:05")
    j("end", "--outcome", "done", *at("10:06"))
    rec = journey_record(store)
    p1, total = part(rec, 1), rec["journey"]["total"]
    for section in (p1, total):
        for field in TIME_FIELDS + ("status",):
            assert field in section, field
    assert p1["budget_minutes"] == 20 and p1["wall_minutes"] == 5.0 and p1["working_minutes"] == 5.0
    assert p1["prs"] == 1 and p1["extra_rounds"] == 1
    assert total["budget_minutes"] == 60 and total["interim_minutes"] == 90 and total["stretch_minutes"] == 50
    assert total["wall_minutes"] == 5.0 and total["prs"] == 1 and total["extra_rounds"] == 1


def test_a_stage_that_never_started_is_not_run_never_zero_minutes_ac_136_1(store, clock):  # AC-136.1
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    stage("1.scaffold", "10:00", "10:02")
    j("end", "--outcome", "done", *at("10:03"))
    rec = journey_record(store)
    plan = by_id(rec)["1.plan"]
    assert plan["status"] == "not run"
    for field in ("started_at", "ended_at", "wall_minutes", "working_minutes", "person_wait_minutes", "external_wait_minutes"):
        assert plan[field] is None, field
    p2 = part(rec, 2)
    assert p2["status"] == "not run" and p2["working_minutes"] is None and p2["wall_minutes"] is None


def test_a_journey_that_stops_keeps_its_open_stage_as_stopped_at_the_end_ac_136_1(store, clock):  # AC-136.1
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    j("stage", "1.build", "start", *at("10:00"))
    j("end", "--outcome", "escalated", "--reason", "red CI", *at("10:07"))
    rec = journey_record(store)
    build = by_id(rec)["1.build"]
    assert rec["outcome"] == "escalated"
    assert build["status"] == "stopped" and build["ended_at"] == "2026-10-24T10:07:00Z" and build["wall_minutes"] == 7.0


def test_every_extra_round_has_a_kind_and_a_cause_ac_136_1(store, clock):  # AC-136.1
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    j("stage", "1.spec", "start", *at("10:00"))
    with pytest.raises(SystemExit):
        j("round", "fix-round")                                        # no --cause
    with pytest.raises(PlatformError):
        j("round", "fix-round", "--cause", "bad-luck")                 # not a cause
    with pytest.raises(PlatformError):
        j("round", "coffee", "--cause", "code")                        # not a kind of extra round
    for kind in ("fix-round", "ci-rerun", "escalation", "resumed-session", "reworked-spec", "reworked-plan"):
        assert j("round", kind, "--cause", "platform") == 0             # the open stage, by default
    j("end", "--outcome", "done", *at("10:04"))
    rounds = by_id(journey_record(store))["1.spec"]["extra_rounds"]
    assert [r["kind"] for r in rounds] == ["fix-round", "ci-rerun", "escalation", "resumed-session", "reworked-spec",
                                           "reworked-plan"]
    assert all(r["cause"] == "platform" for r in rounds)


def test_journey_verbs_need_an_open_journey_and_only_one_is_open_ac_136_1(store, clock):  # AC-136.1
    with pytest.raises(PlatformError, match="journey begin"):
        j("stage", "1.spec", "start")
    j("begin")
    with pytest.raises(PlatformError, match="abandoned"):
        j("begin")
    with pytest.raises(PlatformError, match="1.nope"):
        j("stage", "1.nope", "start")
    with pytest.raises(PlatformError, match="not started"):
        j("stage", "1.plan", "end")
    j("end", "--outcome", "abandoned")
    assert journey_record(store)["outcome"] == "abandoned"


def test_show_prints_the_stages_so_far_ac_136_1(store, clock, capsys):  # AC-136.1
    clock.set("2026-10-24T10:10:00Z")
    j("begin", *at("10:00"))
    stage("1.scaffold", "10:00", "10:03")
    capsys.readouterr()
    assert j("show") == 0
    out = capsys.readouterr().out
    assert "1.scaffold" in out and "1.plan" in out and "not run" in out
    assert j("show", "--json") == 0
    import json
    data = json.loads(capsys.readouterr().out)
    assert data["stages"][0]["id"] == "1.scaffold" and data["stages"][0]["working_minutes"] == 3.0


def test_a_part_is_the_span_of_overlapping_stages_and_less_than_their_sum_by_the_overlap_ac_136_2(store, clock):  # AC-136.2
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    stage("1.scaffold", "10:00", "10:03")      # 3
    stage("1.cluster", "10:01", "10:03")       # 2, alongside scaffold
    stage("1.spec", "10:02", "10:06")          # 4, starts before scaffold ends
    j("end", "--outcome", "done", *at("10:06"))
    p1 = part(journey_record(store), 1)
    assert p1["started_at"] == "2026-10-24T10:00:00Z" and p1["ended_at"] == "2026-10-24T10:06:00Z"
    assert p1["working_minutes"] == 6.0 and p1["wall_minutes"] == 6.0
    assert p1["stages_sum_minutes"] == 9.0 and p1["overlap_minutes"] == 3.0
    assert p1["working_minutes"] == p1["stages_sum_minutes"] - p1["overlap_minutes"]


def test_a_part_subtracts_the_person_waits_inside_its_span_once_ac_136_2(store, clock):  # AC-136.2
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    stage("1.scaffold", "10:00", "10:03")
    stage("1.spec", "10:01", "10:06")
    j("wait", "person", "start", "--reason", "question", *at("10:02"))   # inside both stages
    j("wait", "person", "end", *at("10:04"))
    j("end", "--outcome", "done", *at("10:06"))
    rec = journey_record(store)
    sc, sp, p1 = by_id(rec)["1.scaffold"], by_id(rec)["1.spec"], part(rec, 1)
    assert sc["person_wait_minutes"] == 1.0 and sc["working_minutes"] == 2.0
    assert sp["person_wait_minutes"] == 2.0 and sp["working_minutes"] == 3.0
    assert p1["wall_minutes"] == 6.0 and p1["person_wait_minutes"] == 2.0 and p1["working_minutes"] == 4.0   # counted once
    assert p1["stages_sum_minutes"] == 5.0 and p1["overlap_minutes"] == 1.0
    assert p1["working_minutes"] < p1["stages_sum_minutes"]


def test_a_person_wait_is_left_out_of_working_time_and_an_external_wait_is_kept_ac_136_3(store, clock):  # AC-136.3
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    j("stage", "1.build", "start", *at("10:00"))
    j("wait", "person", "start", "--reason", "a question", *at("10:05"))
    j("wait", "person", "end", *at("10:15"))
    j("wait", "external", "start", "--reason", "GitHub rate limit", *at("10:20"))
    j("wait", "external", "end", *at("10:25"))
    j("stage", "1.build", "end", *at("10:30"))
    j("end", "--outcome", "done", *at("10:30"))
    rec = journey_record(store)
    b = by_id(rec)["1.build"]
    assert b["person_wait_minutes"] == 10.0 and b["external_wait_minutes"] == 5.0
    assert b["wall_minutes"] == 30.0 and b["working_minutes"] == 20.0         # wall includes both; working excludes the 10 only
    total = rec["journey"]["total"]
    assert total["person_wait_minutes"] == 10.0 and total["external_wait_minutes"] == 5.0 and total["working_minutes"] == 20.0
    kinds = sorted(w["kind"] for w in rec["journey"]["waits"])
    assert kinds == ["external", "person"]


def test_a_wait_measured_afterwards_is_added_with_its_minutes_ac_136_3(store, clock):  # AC-136.3
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    stage("2.build", "10:00", "10:30")
    j("wait", "person", "add", "--minutes", "10", *at("10:05"), "--reason", "plan approval")
    j("wait", "external", "add", "--minutes", "5", *at("10:20"))
    j("end", "--outcome", "done", *at("10:30"))
    b = by_id(journey_record(store))["2.build"]
    assert (b["wall_minutes"], b["working_minutes"], b["person_wait_minutes"], b["external_wait_minutes"]) == (30.0, 20.0, 10.0, 5.0)


def test_a_minute_that_is_both_waits_counts_as_person_wait_only_ac_136_3(store, clock):  # AC-136.3
    clock.set("2026-10-24T12:00:00Z")
    j("begin", *at("10:00"))
    stage("1.pr-ci", "10:00", "10:20")
    j("wait", "person", "add", "--minutes", "10", *at("10:00"))
    j("wait", "external", "add", "--minutes", "10", *at("10:05"))     # 5 of them overlap the person wait
    j("end", "--outcome", "done", *at("10:20"))
    b = by_id(journey_record(store))["1.pr-ci"]
    assert b["person_wait_minutes"] == 10.0 and b["external_wait_minutes"] == 5.0 and b["working_minutes"] == 10.0


def test_a_github_rate_limit_wait_of_cplat_is_an_external_wait_of_the_open_journey_ac_136_3(store, clock):  # AC-136.3
    clock.set("2026-10-24T10:00:00Z")
    j("begin", *at("10:00"))
    j("stage", "1.pr-ci", "start", *at("10:00"))
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 1, "", "GraphQL: API rate limit exceeded for user")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(core.subprocess, "run", fake_run)
        mp.setattr(core, "_rate_limit_wait", lambda kind: 300.0)
        mp.setattr(core, "sleep", lambda s: clock.tick(s))
        assert core.run(["gh", "pr", "list"]).stdout == "ok"
    clock.set("2026-10-24T10:10:00Z")
    j("stage", "1.pr-ci", "end")
    j("end", "--outcome", "done")
    rec = journey_record(store)
    waits = [w for w in rec["journey"]["waits"] if w["kind"] == "external"]
    assert len(waits) == 1 and "rate limit" in waits[0]["reason"]
    assert waits[0]["started_at"] == "2026-10-24T10:00:00Z" and waits[0]["ended_at"] == "2026-10-24T10:05:00Z"
    b = by_id(rec)["1.pr-ci"]
    assert b["external_wait_minutes"] == 5.0 and b["working_minutes"] == 10.0 and b["person_wait_minutes"] == 0.0


def test_a_rate_limit_wait_without_a_journey_changes_nothing_ac_136_3(store, clock):  # AC-136.3
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if len(calls) == 1 else 0, "", "API rate limit exceeded" if len(calls) == 1 else "")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(core.subprocess, "run", fake_run)
        mp.setattr(core, "_rate_limit_wait", lambda kind: 60.0)
        mp.setattr(core, "sleep", lambda s: None)
        assert core.run(["gh", "api", "user"]).returncode == 0
    assert [r for r in stored(store) if r.get("kind") == "journey"] == []
