"""Journey 20, J20-1: `cplat next` lost its runs and github sources to the 20 s limit. The run store read asked its day
chunks one after another (11 calls for 30 days), both sources read the store each, and the github source built a row,
with a `gh` PR lookup, for every run of every repo before keeping the system's."""
from __future__ import annotations

import datetime as dt
import json
import threading

import pytest

import runlist
import runs_store
from autonomy_support import ago, run_record, store  # noqa: F401  (fixture)


def fake_graphql(monkeypatch, *, fail_on: str | None = None):
    """gh api graphql: one record per asked day directory. The first two calls meet at a barrier, which breaks (and the
    read fails) when they are asked one after the other."""
    seen = {"calls": 0}
    lock = threading.Lock()
    meet = threading.Barrier(2, timeout=10)

    def gh(args, *, input=None, timeout=10.0):
        query = next(a for a in args if a.startswith("query="))
        paths = [part.split('"')[0] for part in query.split("HEAD:")[1:]]
        with lock:
            seen["calls"] += 1
            first_two = seen["calls"] <= 2
        if first_two:
            meet.wait()
        if fail_on and any(fail_on in p for p in paths):
            return 1, "", "HTTP 502: Bad Gateway"
        data = {f"d{n}": {"entries": [{"name": "r.json", "object": {"text": p}}]} for n, p in enumerate(paths)}
        return 0, json.dumps({"data": {"repository": data}}), ""
    monkeypatch.setattr(runs_store, "gh", gh)
    return seen


def days(n: int) -> list[dt.date]:
    start = dt.date(2026, 11, 1)
    return [start + dt.timedelta(days=i) for i in range(n)]


def test_a_month_of_the_store_is_asked_in_parallel_and_returned_in_day_order(monkeypatch):
    seen = fake_graphql(monkeypatch)
    out = runs_store.GitHubStore("acme/runs").read(days(31))
    assert [text for _, text in out] == [f"runs/{d:%Y/%m/%d}" for d in days(31)]
    assert seen["calls"] == 11


def test_one_failing_chunk_still_makes_the_store_unreachable(monkeypatch):
    fake_graphql(monkeypatch, fail_on="2026/11/20")
    with pytest.raises(runs_store.StoreUnreachable):
        runs_store.GitHubStore("acme/runs").read(days(31))


def counting_reads(store, monkeypatch):  # noqa: F811
    reads: list[int] = []
    real = store.read

    def read(days, deadline=None, prefix="runs"):
        reads.append(len(days))
        return real(days, deadline, prefix)
    monkeypatch.setattr(store, "read", read)
    return reads


def test_inside_shared_reads_two_threads_read_each_day_once(store, monkeypatch):  # noqa: F811
    store.add_run(run_record())
    reads = counting_reads(store, monkeypatch)
    rows: list[int] = []
    with runlist.shared_reads():
        threads = [threading.Thread(target=lambda: rows.append(len(runlist.collect(30)["runs"]))) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        runlist.collect(7)
    assert reads == [31] and rows == [1, 1]


def test_outside_shared_reads_every_call_reads_the_store_and_sees_new_runs(store, monkeypatch):  # noqa: F811
    reads = counting_reads(store, monkeypatch)
    with runlist.shared_reads():
        runlist.collect(30)
    store.add_run(run_record())
    assert len(runlist.collect(30)["runs"]) == 1 and len(reads) == 2


def test_the_smoke_evidence_of_every_cell_shares_the_read_of_the_runs(store, monkeypatch):  # noqa: F811
    import evidence
    reads = counting_reads(store, monkeypatch)
    with runlist.shared_reads():
        runlist.collect(30)
        evidence._records("acme/shop-api", {"sha-abc1234"}, 30)
        evidence._records("acme/shop-web", {"sha-def5678"}, 30)
    assert reads == [31]


def test_runs_of_other_repos_get_no_row_and_no_pr_lookup(store, monkeypatch):  # noqa: F811
    store.add_run(run_record(run_id="20261026T091500Z-aaaaaaa1", repo="acme/shop-api", spec="001-a", pr=None,
                             actor={"type": "person"}, ended_at=None, phases=[{"name": "build", "started_at": ago(minutes=5)}]))
    store.add_run(run_record(run_id="20261026T091500Z-bbbbbbb2", repo="other/thing", spec="002-b", pr=None,
                             actor={"type": "person"}, ended_at=None, phases=[{"name": "build", "started_at": ago(minutes=5)}]))
    asked: list[str] = []
    monkeypatch.setattr(runlist, "lookup_pr", lambda repo, branch, state="all": asked.append(repo))
    found = runlist.collect(30, repos={"acme/shop-api", "acme/shop-gitops"})["runs"]
    assert [r["repo"] for r in found] == ["acme/shop-api"] and "other/thing" not in asked

