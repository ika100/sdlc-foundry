"""Spec 141: an approved system plan asks no new questions. A repo spec written from the plan takes the suggested answers,
records them under `## Decisions taken during the ship`, and the system ship's report, its run record and the repo's PR
show them."""
from pathlib import Path

import appship_report
import ship
import spec
from test_ship import gh, git, repo  # noqa: F401  (pytest fixtures)

ROOT = Path(__file__).resolve().parents[2]
BODY = """# 001 — Create and list tasks

## Acceptance criteria

- **AC-001.1** Given …

## Decisions taken during the ship

- Title length counts characters, not bytes? → yes (suggested)
- An empty due_date ("") is rejected with 422? → reject (suggested)

## Changelog

- 2026-11-05 created
"""


def test_the_decisions_section_is_parsed_ac_141_1():  # AC-141.1
    assert spec.decisions(BODY) == ['Title length counts characters, not bytes? → yes (suggested)',
                                    'An empty due_date ("") is rejected with 422? → reject (suggested)']
    assert spec.decisions("# 001\n\n## Changelog\n\n- created\n") == []


def test_the_final_report_lists_the_decisions_and_the_run_record_counts_them_ac_141_3():  # AC-141.3
    st = {"spec": "002-tasks", "repos": {
        "task-api": {"state": "passed", "spec": "002-tasks-in-postgres", "decisions": ["labels? → Title, Due date (suggested)"]},
        "task-web": {"state": "passed", "spec": "001-board", "decisions": []}}}
    out = "\n".join(appship_report.final_report(st, "Tasks"))
    assert "Decisions taken for you" in out
    assert "- task-api (002-tasks-in-postgres): labels? → Title, Due date (suggested)" in out
    assert appship_report.decision_count(st) == 1
    assert "Decisions taken for you" not in "\n".join(appship_report.final_report({"spec": "x", "repos": {}}, "X"))


def test_the_repo_pr_gets_one_comment_with_the_decisions_ac_141_5(repo, gh, monkeypatch):  # noqa: F811  AC-141.5
    calls = []
    real = ship.gh

    def fake(args, *, cwd, check=True):
        calls.append(args)
        if args[:2] == ["pr", "comment"]:
            return ""
        return real(args, cwd=cwd, check=check)
    monkeypatch.setattr(ship, "gh", fake)
    monkeypatch.setattr(ship, "nothing_to_merge", lambda _repo: False)
    ship.start(repo, "7", True)
    sp = spec.find(repo, "7")
    f = sp.dir / "spec.md"
    f.write_text(f.read_text().replace("## Changelog", "## Decisions taken during the ship\n\n- Unicode length? → characters (suggested)\n\n## Changelog", 1))
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    body = repo / ".git" / "PR_BODY.md"
    body.write_text("## Summary\n")
    st = ship.open_pr(repo, "feat(alerts): price alerts", body)
    comments = [c for c in calls if c[:2] == ["pr", "comment"]]
    assert len(comments) == 1 and "Unicode length? → characters (suggested)" in comments[0][-1] and st["decisions_posted"]
    ship.open_pr(repo, "feat(alerts): price alerts", body)          # the PR exists now: no second comment
    assert len([c for c in calls if c[:2] == ["pr", "comment"]]) == 1


def test_a_repo_spec_without_decisions_posts_no_comment_ac_141_5(repo, gh, monkeypatch):  # noqa: F811  AC-141.5
    monkeypatch.setattr(ship, "nothing_to_merge", lambda _repo: False)
    ship.start(repo, "7", True)
    git(repo, "checkout", "-qb", "feature/007-price-alerts")
    body = repo / ".git" / "PR_BODY.md"
    body.write_text("## Summary\n")
    ship.open_pr(repo, "feat(alerts): price alerts", body)
    assert not [c for c in gh.calls if c[:2] == ["pr", "comment"]]


def test_the_unattended_rules_take_suggested_answers_and_stop_only_without_one_ac_141_1_ac_141_2():  # AC-141.1, AC-141.2
    # spec 155: a system ship writes each repo spec from the plan's criteria (spec 147) with cplat, so no repo spec of a
    # system ship has questions to answer; the unattended answering path (section D.3) is gone, nothing is invented
    d = (ROOT / "plugins/component/references/spec-from-plan.md").read_text()
    assert "When run unattended by `/system:ship`" not in d and "writes and approves a repo's spec itself" in d
    sys_ship = (ROOT / "plugins/system/commands/ship.md").read_text()
    assert "Never answer a repo spec's questions." in sys_ship and "writes and approves the repo spec from the plan" in sys_ship


def test_the_product_manager_prefers_the_system_specs_answers_ac_141_4():  # AC-141.4
    pm = (ROOT / "plugins/svc/agents/product-manager.md").read_text()
    assert "Prefer the system spec's answers and conventions" in pm and "spec 141" in pm


def test_the_decision_count_is_written_to_the_run_record_ac_141_3():  # AC-141.3
    src = (ROOT / "scripts/cplat/appship.py").read_text()
    assert 'runs.set_section(st.get("run_id"), "decisions", appship_report.decision_count(st))' in src
