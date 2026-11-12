"""Spec 179 acceptance tests: a reviewer finding on a loose smoke test is fixed by the build, not asked of the person (AC-179.9, #616).

Seams: `cplat platform runs agent smoke` (the spec 089 agent signals, fixtures of test_runs_agents.py); the PR block of
`cplat platform runs report --pr` (fixtures of test_runs_built_133.py); the build and reviewer prompts. Contract: design.md section 5.
"""
import re
from pathlib import Path

from test_runs import clock, mem, store, stored, rgh, queued  # noqa: F401  (fixtures)
from test_runs_agents import agent, begin, end, events, started  # noqa: F401  (helpers)
from test_runs_agents import repo  # noqa: F401  (fixture)
from test_runs_built_133 import agent as built_agent, make_run, part, report  # noqa: F401  (helpers)
from test_runs_built_133 import repo as built_repo  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
SMOKE_FILE = "tests/smoke/test_home_smoke.py"
FINDING = "the locator also matches the header navigation, so the test passes without the feature"


def test_a_smoke_finding_is_recorded_on_the_testers_entry_ac_179_9(repo, store, capsys):  # AC-179.9
    begin(repo)
    capsys.readouterr()
    assert agent(repo, "smoke", SMOKE_FILE, "--finding", FINDING) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""                                            # silent, like every agent signal
    rec = end(repo, store)
    (ev,) = events(rec, "svc-go:tester", "smoke")
    assert ev["test"] == SMOKE_FILE and ev["finding"] == FINDING and ev["kind"] == "smoke"


def test_two_smoke_findings_are_two_events_ac_179_9(repo, store):  # AC-179.9
    begin(repo)
    agent(repo, "smoke", SMOKE_FILE, "--finding", FINDING)
    agent(repo, "smoke", "tests/smoke/test_other_smoke.py", "--finding", "the text is a prefix of the footer")
    rec = end(repo, store)
    assert sorted(e["test"] for e in events(rec, "svc-go:tester", "smoke")) == [SMOKE_FILE, "tests/smoke/test_other_smoke.py"]


def test_the_pr_block_lists_the_smoke_file_and_the_finding_ac_179_9(built_repo, capsys):  # AC-179.9
    run = make_run(agents=[built_agent("svc:tester", {"kind": "smoke", "test": SMOKE_FILE, "finding": FINDING})])
    block = part(report(run, built_repo, capsys)[1], "Hand-backs and fix rounds")
    assert f"smoke test tightened {SMOKE_FILE}: {FINDING}" in block


# ---------------- the prompts ----------------

def read(rel):
    return (ROOT / rel).read_text()


def phase4():
    return read("plugins/component/commands/build.md").split("## Phase 4")[1].split("\n## Phase ")[0]


def test_the_reviewer_reports_a_loose_smoke_test_as_a_smoke_line_not_a_failure_ac_179_9():  # AC-179.9
    text = read("plugins/svc/agents/reviewer.md")
    assert "SMOKE: <test file> — <finding" in text
    line = next(ln for ln in text.splitlines() if "SMOKE:" in ln)
    assert re.search(r"not a `?NOT MET`?|never .*NOT MET|no `?NOT MET`?|does not make", text)
    assert "locator" in text and "without the feature" in text, line


def test_the_build_hands_a_smoke_finding_to_the_tester_in_the_fix_round_without_asking_ac_179_9():  # AC-179.9
    p4 = phase4()
    assert "SMOKE" in p4 and "tester" in p4 and "Tighten only" in p4 and "Change no other test" in p4
    assert "cplat platform runs agent smoke" in p4 and "--finding" in p4
    assert re.search(r"never ask|not ask|without asking|no question", p4)
    assert "TEST LOOSER" in p4                                                     # a finding on a frozen test keeps its rule
    assert "AC-179.4" in p4 or "build-tighten.md" in p4
