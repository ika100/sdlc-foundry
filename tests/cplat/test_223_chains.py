"""Spec 223 acceptance tests: `cplat platform runs report` groups runs into chains (AC-223.7 to AC-223.9).

Records go through the in-memory run store of the spec 087 tests; the report window is `--since 7` (2026-10-17 to 2026-10-24)."""
import json

import pytest

import runs
from test_runs import clock, mem, store  # noqa: F401  (fixtures)
from test_runs_report import put, rec


def run_rec(rid, outcome, cost, *, spec="131", repo="acme/a", started="2026-10-20T01:00:00Z", ended=None, parent=None, kind="ship",
            complete=True, issue=None, **extra):
    totals = {"calls": 1, "cost_usd": cost, "cost_complete": complete}
    return rec(rid, ended or started.replace("T01", "T09").replace("T02", "T09"), kind=kind, outcome=outcome, repo=repo, spec=spec,
               started_at=started, parent=parent, issue=issue, usage={"totals": totals}, **extra)


def feed(store, *records):
    for r in records:
        put(store, r)


def report_json(capsys):
    assert runs.main(["report", "--json", "--since", "7"]) == 0
    return json.loads(capsys.readouterr().out)


def chains_block(capsys):
    assert runs.main(["report", "--since", "7"]) == 0
    lines = capsys.readouterr().out.splitlines()
    start = lines.index("Chains:")
    block = []
    for ln in lines[start + 1:]:
        if not ln.startswith("  "):
            break
        block.append(ln.strip())
    return block


def item(data, ident="131", repo="acme/a"):
    [one] = [i for i in data["chains"]["items"] if i["id"] == ident and i["repo"] == repo]
    return one


def spec_131(store, child_cost=0.0):
    feed(store,
         run_rec("s1", "escalated", 4.0, started="2026-10-20T01:00:00Z"),
         run_rec("s2", "abandoned", 1.5, started="2026-10-20T02:00:00Z"),
         run_rec("s3", "done", 2.0, started="2026-10-21T01:00:00Z", ended="2026-10-21T09:00:00Z"),
         run_rec("c1", "done", child_cost, kind="fix", started="2026-10-21T02:00:00Z", ended="2026-10-21T08:00:00Z", parent="s3"),
         run_rec("h1", "done", 9.0, kind="headless", started="2026-10-21T01:00:00Z", ended="2026-10-21T09:30:00Z", command="/component:ship 131"))


# ---------------- AC-223.7: one chain ----------------

def test_a_chain_shows_attempts_cost_and_the_share_outside_the_success_ac_223_7(store, capsys):  # AC-223.7
    spec_131(store)
    block = chains_block(capsys)
    [line] = [ln for ln in block if ln.startswith("acme/a spec 131:")]
    for part in ("3 attempts", "1 escalation", "1 abandon", "0 failed", "attempts to done: 3", "chain cost $7.50", "successful run $2.00",
                 "spent outside the successful run: 73%"):
        assert part in line, line
    assert "1 escalations" not in line and "1 abandons" not in line


def test_the_json_item_of_the_chain_ac_223_7(store, capsys):  # AC-223.7
    spec_131(store)
    one = item(report_json(capsys))
    assert one["kind"] == "spec" and one["attempts"] == 3 and one["escalations"] == 1 and one["abandons"] == 1 and one["failed"] == 0
    assert one["done"] is True and one["attempts_to_done"] == 3 and one["partial"] is False
    assert one["cost_usd"] == pytest.approx(7.5) and one["cost_complete"] is True
    assert one["successful_cost_usd"] == pytest.approx(2.0) and one["outside_pct"] == 73
    assert {"s1", "s2", "s3", "c1"} <= set(one["run_ids"]) and "h1" not in one["run_ids"]     # headless is not part of a chain


def test_a_child_record_adds_its_cost_once_and_is_no_attempt_ac_223_7(store, capsys):  # AC-223.7
    spec_131(store, child_cost=1.0)
    one = item(report_json(capsys))
    assert one["attempts"] == 3 and one["cost_usd"] == pytest.approx(8.5) and one["successful_cost_usd"] == pytest.approx(3.0)
    assert one["outside_pct"] == 65


def test_a_failed_attempt_is_counted_apart_ac_223_7(store, capsys):  # AC-223.7
    feed(store, run_rec("f1", "failed", 1.0, spec="140", started="2026-10-20T01:00:00Z"),
         run_rec("f2", "done", 1.0, spec="140", started="2026-10-21T01:00:00Z", ended="2026-10-21T09:00:00Z"))
    one = item(report_json(capsys), "140")
    assert one["attempts"] == 2 and one["failed"] == 1 and one["escalations"] == 0 and one["attempts_to_done"] == 2
    [line] = [ln for ln in chains_block(capsys) if ln.startswith("acme/a spec 140:")]
    assert "1 failed" in line and "0 escalations" in line


def test_the_same_spec_in_two_repos_is_two_chains_ac_223_7(store, capsys):  # AC-223.7
    feed(store, run_rec("a1", "done", 1.0, repo="acme/a"), run_rec("b1", "done", 2.0, repo="acme/b"))
    items = report_json(capsys)["chains"]["items"]
    assert sorted((i["repo"], i["id"]) for i in items) == [("acme/a", "131"), ("acme/b", "131")]


# ---------------- AC-223.8: the summary ----------------

def mixed(store):
    spec_131(store)
    feed(store,
         run_rec("d1", "done", 3.0, spec="132", started="2026-10-22T01:00:00Z", ended="2026-10-22T09:00:00Z"),
         run_rec("o1", "escalated", 1.2, spec="133", started="2026-10-22T01:00:00Z"),
         run_rec("i1", "escalated", 0.8, spec=None, issue={"number": 42}, started="2026-10-22T01:00:00Z"))


def test_the_text_summary_per_delivered_item_ac_223_8(store, capsys):  # AC-223.8
    mixed(store)
    block = chains_block(capsys)
    assert any(ln.startswith("acme/a issue 42:") and "not done" in ln for ln in block)
    [summary] = [ln for ln in block if ln.startswith("done 2, not done 2")]
    assert "median attempts to done: 2" in summary
    assert "cost per delivered item: $5.25 (median successful run $2.50)" in summary
    assert "spend of chains not done: $2.00" in summary


def test_the_json_chains_summary_and_the_old_keys_ac_223_8(store, capsys):  # AC-223.8
    mixed(store)
    data = report_json(capsys)
    chains = data["chains"]
    assert {"items", "done", "open", "median_attempts_to_done", "cost_per_delivered", "median_successful_cost", "open_spend"} <= set(chains)
    assert chains["done"] == 2 and chains["open"] == 2 and len(chains["items"]) == 4
    assert chains["median_attempts_to_done"] == 2
    assert chains["cost_per_delivered"] == pytest.approx(5.25) and chains["median_successful_cost"] == pytest.approx(2.5)
    assert chains["open_spend"] == pytest.approx(2.0)
    assert {"window", "runs", "pr_wait", "phases", "causes", "escalations", "reruns", "filed", "usage", "unattended_ships"} <= set(data)


# ---------------- AC-223.9: unknown cost, partial chains, unchained records ----------------

def test_an_unreadable_cost_is_unknown_never_zero_ac_223_9(store, capsys):  # AC-223.9
    feed(store, run_rec("u1", "escalated", 1.2, spec="140", started="2026-10-20T01:00:00Z"),
         run_rec("u2", "done", None, spec="140", started="2026-10-21T01:00:00Z", ended="2026-10-21T09:00:00Z", complete=False))
    data = report_json(capsys)
    one = item(data, "140")
    assert one["cost_complete"] is False and one["cost_usd"] == pytest.approx(1.2) and one["outside_pct"] is None
    assert data["chains"]["cost_per_delivered"] is None and data["chains"]["done"] == 1
    [line] = [ln for ln in chains_block(capsys) if ln.startswith("acme/a spec 140:")]
    assert "chain cost >= $1.20 +unknown" in line and "$0.00" not in line


def test_a_chain_begun_before_the_window_is_partial_ac_223_9(store, capsys):  # AC-223.9
    feed(store, run_rec("p1", "done", 1.0, spec="150", started="2026-10-05T01:00:00Z", ended="2026-10-20T09:00:00Z"),
         run_rec("p2", "done", 1.0, spec="151", started="2026-10-20T01:00:00Z"))
    data = report_json(capsys)
    assert item(data, "150")["partial"] is True and item(data, "151")["partial"] is False
    [line] = [ln for ln in chains_block(capsys) if ln.startswith("acme/a spec 150:")]
    assert "partial" in line
    assert "partial" not in next(ln for ln in chains_block(capsys) if ln.startswith("acme/a spec 151:"))


def test_records_without_spec_or_issue_are_unchained_ac_223_9(store, capsys):  # AC-223.9
    feed(store, run_rec("n1", "done", 1.0, spec=None), run_rec("n2", "escalated", 1.0, spec=None, kind="build"))
    data = report_json(capsys)
    assert data["chains"]["items"] == [] and data["chains"]["unchained"] == 2
    assert runs.main(["report", "--since", "7"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "Chains: none" in lines and "  unchained: 2" in lines
