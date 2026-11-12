"""Spec 180 acceptance tests: `cplat platform rules rebaseline` raises the prompt baseline behind the eval gate (AC-180.5, AC-180.6).

Seams: a real git repo under tmp_path (register, one plugin, a `v1.0.0` tag) whose prompts are larger than the register's baseline;
the benchmark records are passed by replacing `evalgate._records`, as the spec 168 gate tests do. The CLI is
`rules_rebaseline.main(argv)`; its `--json` document is parsed, never its text."""
import json
import subprocess

import pytest
import yaml

import evalgate
from rules_support import REGISTER, Lazy, good_repo, put

rules_rebaseline = Lazy("rules_rebaseline")
promptrules = Lazy("promptrules")

BASELINE = 100
REASON = "the replan rule needs its reason clause"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, msg="change"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-s", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path):
    r = good_repo(tmp_path / "platform", baseline_bytes=BASELINE)
    put(r, ".claude-plugin/marketplace.json", json.dumps({"plugins": [{"name": "svc", "version": "1.0.0"}]}))
    put(r, "plugins/svc/.claude-plugin/plugin.json", json.dumps({"name": "svc", "version": "1.0.0"}))
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.name", "t")
    git(r, "config", "user.email", "t@t")
    commit(r, "base")
    git(r, "tag", "v1.0.0")
    git(r, "checkout", "-q", "-b", "feature/x")
    return r


def bench(workflow, commit_sha, outcome="done"):
    return {"kind": "benchmark", "outcome": outcome, "platform_version": "1.0.1", "run_id": f"r-{workflow}-{commit_sha[:4]}",
            "ended_at": "2026-11-07T10:00:00Z", "usage": {"totals": {"input_tokens": 1_000_000}},
            "benchmark": {"workflow": workflow, "plugins": {"commit": commit_sha, "dirty": False}}}


def records(monkeypatch, recs):
    monkeypatch.setattr(evalgate, "_records", lambda days: recs)


def passing(repo, monkeypatch):
    head = git(repo, "rev-parse", "HEAD")
    records(monkeypatch, [bench("quick-task", head), bench("build", head)])
    return [f"r-quick-task-{head[:4]}", f"r-build-{head[:4]}"]


def register(repo):
    return yaml.safe_load((repo / REGISTER).read_text())


def run(repo, capsys, reason=REASON, *extra):
    rc = rules_rebaseline.main(["--reason", reason, "--json", "--repo", str(repo), *extra])
    out = capsys.readouterr().out
    return rc, json.loads(out)


def current_bytes(repo):
    return promptrules.prompt_bytes(repo)


# ---------------- AC-180.5 ----------------

def test_a_passing_gate_raises_the_baseline_and_records_history_ac_180_5(repo, monkeypatch, capsys):  # AC-180.5
    ids = passing(repo, monkeypatch)
    total, head = current_bytes(repo), git(repo, "rev-parse", "HEAD")
    assert total > BASELINE
    rc, doc = run(repo, capsys)
    reg = register(repo)
    assert rc == 0 and doc["status"] == "raised" and doc["old"] == BASELINE and doc["new"] == total
    assert doc["reason"] == REASON and doc["benchmark_runs"] == ids and doc["failures"] == []
    assert reg["baseline"]["prompt_bytes"] == total and reg["baseline"]["commit"] == head
    [entry] = reg["baseline"]["history"]
    assert str(entry["date"]) and entry["old"] == BASELINE and entry["new"] == total
    assert entry["reason"] == REASON and entry["benchmark_runs"] == ids
    assert set(entry) == {"date", "old", "new", "reason", "benchmark_runs"}


def test_the_command_prints_the_old_and_new_count_ac_180_5(repo, monkeypatch, capsys):  # AC-180.5
    passing(repo, monkeypatch)
    total = current_bytes(repo)
    rc = rules_rebaseline.main(["--reason", REASON, "--repo", str(repo)])
    out = capsys.readouterr().out
    assert rc == 0 and str(BASELINE) in out and str(total) in out and "commit docs/rules/register.yml" in out


def test_the_module_api_takes_today_and_returns_the_outcome_ac_180_5(repo, monkeypatch):  # AC-180.5
    import datetime
    passing(repo, monkeypatch)
    out = rules_rebaseline.rebaseline(repo, REASON, today=datetime.date(2026, 11, 12))
    assert out.status == "raised" and str(register(repo)["baseline"]["history"][-1]["date"]) == "2026-11-12"


def test_a_second_raise_appends_the_newest_entry_last_ac_180_5(repo, monkeypatch, capsys):  # AC-180.5
    passing(repo, monkeypatch)
    assert run(repo, capsys)[0] == 0
    commit(repo, "raise")
    put(repo, "plugins/svc/commands/more.md", "---\ndescription: More\n---\n" + "Some more words to make the prompts larger.\n" * 20)
    commit(repo, "grow")
    passing(repo, monkeypatch)
    rc, doc = run(repo, capsys, "a second reason for growth")
    hist = register(repo)["baseline"]["history"]
    assert rc == 0 and len(hist) == 2 and hist[0]["reason"] == REASON and hist[1]["reason"] == "a second reason for growth"
    assert hist[1]["old"] == hist[0]["new"] and hist[1]["new"] == doc["new"]


def test_the_register_loader_reads_the_history_ac_180_5(repo, monkeypatch, capsys):  # AC-180.5
    ids = passing(repo, monkeypatch)
    run(repo, capsys)
    reg = promptrules.load_register(repo)
    [h] = reg.baseline_history
    assert (h.old, h.new, h.reason, h.benchmark_runs) == (BASELINE, current_bytes(repo), REASON, ids)
    assert reg.baseline_bytes_line == next(n for n, ln in enumerate((repo / REGISTER).read_text().splitlines(), 1) if "prompt_bytes:" in ln)
    text = (repo / REGISTER).read_text()
    assert promptrules.parse_baseline(text)[0] == current_bytes(repo)


@pytest.mark.parametrize("bad", [{"reason": "too short"}, {"old": 500, "new": 400}, {"benchmark_runs": []}, {"extra": 1}])
def test_a_malformed_history_entry_is_a_bad_entry_ac_180_5(repo, bad):  # AC-180.5
    entry = {"date": "2026-11-12", "old": 100, "new": 200, "reason": REASON, "benchmark_runs": ["r-1"], **bad}
    doc = yaml.safe_load((repo / REGISTER).read_text())
    doc["baseline"]["history"] = [entry]
    put(repo, REGISTER, yaml.safe_dump(doc, sort_keys=False))
    assert promptrules.load_register(repo).problems
    ok = {"date": "2026-11-12", "old": 100, "new": 200, "reason": REASON, "benchmark_runs": ["r-1"]}
    doc["baseline"]["history"] = [ok]
    put(repo, REGISTER, yaml.safe_dump(doc, sort_keys=False))
    assert promptrules.load_register(repo).problems == []


# ---------------- AC-180.6 ----------------

def unchanged(repo, capsys, reason=REASON):
    before = (repo / REGISTER).read_text()
    rc, doc = run(repo, capsys, reason)
    assert (repo / REGISTER).read_text() == before
    return rc, doc


def test_a_failing_gate_refuses_with_the_benchmark_command_ac_180_6(repo, monkeypatch, capsys):  # AC-180.6
    records(monkeypatch, [])
    rc, doc = unchanged(repo, capsys)
    assert rc == 1 and doc["status"] == "refused" and len(doc["failures"]) == 2
    assert any("cplat platform runs benchmark quick-task --plugins plugins --reset-first" in f for f in doc["failures"])
    assert any("cplat platform runs benchmark build --plugins plugins --reset-first" in f for f in doc["failures"])


def test_a_failed_benchmark_refuses_ac_180_6(repo, monkeypatch, capsys):  # AC-180.6
    head = git(repo, "rev-parse", "HEAD")
    records(monkeypatch, [bench("quick-task", head), bench("build", head, outcome="escalated")])
    rc, doc = unchanged(repo, capsys)
    assert rc == 1 and doc["status"] == "refused" and any("escalated" in f for f in doc["failures"])


def test_a_dirty_tree_refuses_and_names_the_path_ac_180_6(repo, monkeypatch, capsys):  # AC-180.6
    passing(repo, monkeypatch)
    put(repo, "plugins/svc/commands/demo.md", (repo / "plugins/svc/commands/demo.md").read_text() + "\nmore\n")
    rc = rules_rebaseline.main(["--reason", REASON, "--repo", str(repo)])
    cap = capsys.readouterr()
    assert rc == 1 and "plugins/svc/commands/demo.md" in cap.out + cap.err and register(repo)["baseline"]["prompt_bytes"] == BASELINE


@pytest.mark.parametrize("reason", ["", "two words", "  "])
def test_a_reason_under_three_words_refuses_ac_180_6(repo, monkeypatch, capsys, reason):  # AC-180.6
    passing(repo, monkeypatch)
    rc, doc = unchanged(repo, capsys, reason)
    assert rc == 1 and doc["status"] == "refused"


def test_prompts_within_the_baseline_need_nothing_ac_180_6(repo, monkeypatch, capsys):  # AC-180.6
    put(repo, REGISTER, (repo / REGISTER).read_text().replace(f"prompt_bytes: {BASELINE}", "prompt_bytes: 10000000"))
    commit(repo, "big baseline")
    records(monkeypatch, [])                                  # the gate is not asked
    rc, doc = unchanged(repo, capsys)
    assert rc == 0 and doc["status"] == "nothing" and doc["old"] == 10000000
    rc = rules_rebaseline.main(["--reason", REASON, "--repo", str(repo)])
    assert rc == 0 and "nothing needs raising" in capsys.readouterr().out
