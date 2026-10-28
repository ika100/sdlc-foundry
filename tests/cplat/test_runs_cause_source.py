"""Spec 088 (amendment 2026-10-26): `runs.finish` records `cause_source` and the matching rule (AC-088.15 to AC-088.17)."""
import pytest

import runs
import ship
from test_autoissue import clk, tr, ai  # noqa: F401  (fixtures)
from test_runs import clock, mem, one_run, store, stored  # noqa: F401  (fixtures, helpers)
from test_ship import git, repo  # noqa: F401  (fixtures)


def escalated(store, reason, cause=None):
    esc = {"reason": reason} if cause is None else {"reason": reason, "cause": cause}
    one_run("ship", "escalated", escalation=esc)
    return stored(store)[-1]["escalation"]


@pytest.mark.parametrize("reason, cause, rule", [
    ("waiting for approval to create the branch", "environment", "git-action-awaits-approval"),
    ("stopped: working tree is dirty", "environment", "dirty-working-tree"),
    ("acceptance test contradicts AC-012.3", "decision", "spec-test-conflict"),
    ("left for the user to review", "decision", "left-for-review"),
])
def test_a_record_without_a_cause_is_classified_by_rule(store, reason, cause, rule):
    """AC-088.15 AC-088.16: no cause: `cause` is the rule's cause, `cause_source` is `rule`, `rule` names it; the field order is fixed."""
    esc = escalated(store, reason)
    assert esc == {"reason": reason, "cause": cause, "cause_source": "rule", "rule": rule}
    assert list(esc) == ["reason", "cause", "cause_source", "rule"]


def test_an_unknown_cause_passed_explicitly_is_classified_too(store):
    """AC-088.15: `unknown` passed as the cause counts as not stated."""
    esc = escalated(store, "commit needs permission", "unknown")
    assert (esc["cause"], esc["cause_source"], esc["rule"]) == ("environment", "rule", "git-action-awaits-approval")


def test_a_record_without_a_matching_rule_has_cause_source_none(store):
    """AC-088.15: no match: cause `unknown`, `cause_source` `none`, no `rule` key."""
    esc = escalated(store, "needs a decision on rate limits")
    assert esc == {"reason": "needs a decision on rate limits", "cause": "unknown", "cause_source": "none"}


def test_a_git_word_alone_is_not_classified(store):
    """AC-088.17: a reason that only mentions a git word stays `unknown`."""
    esc = escalated(store, "tests fail after commit 1a2b3c")
    assert (esc["cause"], esc["cause_source"]) == ("unknown", "none") and "rule" not in esc


@pytest.mark.parametrize("cause", ["platform", "code", "decision", "environment"])
def test_a_stated_cause_has_cause_source_given(store, cause):
    """AC-088.15 AC-088.17: a stated allowed cause is recorded as stated with `cause_source` `given`, even when a rule would match."""
    esc = escalated(store, "working tree is dirty", cause)
    assert esc == {"reason": "working tree is dirty", "cause": cause, "cause_source": "given"}


def test_a_stated_code_cause_beats_the_dirty_tree_rule(store):
    """AC-088.17: reason `working tree is dirty` with `--cause code` is recorded as `code` with `cause_source` `given`."""
    esc = escalated(store, "working tree is dirty", "code")
    assert (esc["cause"], esc["cause_source"]) == ("code", "given") and "rule" not in esc


def test_runs_end_escalated_without_cause_is_classified(repo, store):
    """AC-088.15: the `/svc:build` path (`cplat runs end --outcome escalated --reason`) is classified by the same rules."""
    d = ["--dir", str(repo)]
    runs.main(["begin", "build", "--spec", "007-price-alerts", *d])
    runs.main(["end", "--outcome", "escalated", "--reason", "build left open for review", *d])
    (r,) = stored(store)
    assert r["escalation"] == {"reason": "build left open for review", "cause": "decision", "cause_source": "rule", "rule": "left-for-review"}


def test_ship_escalate_without_cause_records_the_classified_cause(repo, store):
    """AC-088.15 AC-088.16: the ship record carries the rule's cause while the ship state keeps the stated cause (`unknown`)."""
    ship.start(repo, "7", True)
    assert ship.main(["--repo", str(repo), "escalate", "waiting for approval to create the branch"]) == 0
    (r,) = stored(store)
    assert r["escalation"] == {"reason": "waiting for approval to create the branch", "cause": "environment",
                               "cause_source": "rule", "rule": "git-action-awaits-approval"}
    assert ship.load_state(repo)["cause"] == "unknown"


@pytest.mark.parametrize("reason", ["waiting for approval to create the branch", "working tree is dirty", "spec/test conflict",
                                    "build left open for review"])
def test_a_classified_escalation_is_never_filed(repo, tr, store, reason):
    """AC-088.17 AC-088.2: no rule yields `platform`, so the tracker is never called and nothing is filed."""
    ship.start(repo, "7", True)
    assert ship.main(["--repo", str(repo), "escalate", reason]) == 0
    (r,) = stored(store)
    assert tr.calls == [] and r["filed"] == [] and r["escalation"]["cause"] != "platform"
    assert r["escalation"]["cause_source"] == "rule"                                        # classified, yet never filed
