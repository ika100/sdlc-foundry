"""Spec 088 (amendment 2026-10-26): the pure rule table that classifies an escalation by its reason (AC-088.15 to AC-088.17, AC-088.21)."""
import pytest

from retro_world import Lazy

er = Lazy("escalation_rules")

ALLOWED = ("platform", "code", "decision", "environment")


def rule_of(reason):
    r = er.classify(reason)
    return None if r is None else (r.cause, r.name)


@pytest.mark.parametrize("reason", ["waiting for approval to create the branch", "commit needs permission", "needs user confirmation to push"])
def test_a_git_action_awaiting_approval_is_environment(reason):
    """AC-088.16 AC-088.15: a wait for an approval, a permission or a confirmation of a git action is `environment`, by a named rule."""
    assert rule_of(reason) == ("environment", "git-action-awaits-approval")
    res = er.resolve(None, reason)
    assert (res.cause, res.source, res.rule) == ("environment", "rule", "git-action-awaits-approval")
    assert er.message(res) == "classified as environment by rule git-action-awaits-approval"


@pytest.mark.parametrize("reason", ["stopped: working tree is dirty", "uncommitted changes in the working tree"])
def test_a_dirty_working_tree_is_environment(reason):
    """AC-088.16: a dirty working tree is `environment`."""
    assert rule_of(reason) == ("environment", "dirty-working-tree")


@pytest.mark.parametrize("reason", ["acceptance test contradicts AC-012.3", "spec/test conflict"])
def test_a_spec_test_conflict_is_decision(reason):
    """AC-088.16: an acceptance test that contradicts a spec rule or criterion is `decision`."""
    assert rule_of(reason) == ("decision", "spec-test-conflict")


@pytest.mark.parametrize("reason", ["build left open for review", "left for the user to review"])
def test_a_build_left_open_for_review_is_decision(reason):
    """AC-088.16: a build left open for review is `decision`."""
    assert rule_of(reason) == ("decision", "left-for-review")


def test_the_decision_rules_win_over_a_git_action_in_the_same_reason():
    """AC-088.16: the two decision rules come first, because a review handoff or a conflict can mention a git action too."""
    assert rule_of("branch left for the user to review and approve") == ("decision", "left-for-review")


def test_rules_match_case_insensitively():
    """AC-088.15: the reason is matched case-insensitively."""
    assert rule_of("WAITING FOR APPROVAL TO CREATE THE BRANCH") == ("environment", "git-action-awaits-approval")
    assert rule_of("Working Tree Is DIRTY") == ("environment", "dirty-working-tree")
    assert rule_of("SPEC/TEST CONFLICT") == ("decision", "spec-test-conflict")
    assert rule_of("Build LEFT open for REVIEW") == ("decision", "left-for-review")


def test_a_reason_without_a_match_stays_unknown_with_source_none():
    """AC-088.15: no match: the cause stays `unknown` and the source is `none`; there is no message line."""
    res = er.resolve(None, "needs a decision on rate limits")
    assert (res.cause, res.source, res.rule) == ("unknown", "none", None)
    assert er.message(res) is None
    assert er.classify("") is None and er.classify(None) is None and er.classify(42) is None


@pytest.mark.parametrize("reason", ["tests fail after commit 1a2b3c", "git push failed"])
def test_a_git_word_alone_stays_unknown(reason):
    """AC-088.17: a reason that only mentions a git word, without a wait, a dirty tree, a conflict or a review, stays `unknown`."""
    assert er.classify(reason) is None
    res = er.resolve(None, reason)
    assert (res.cause, res.source) == ("unknown", "none")


def test_a_stated_cause_always_wins():
    """AC-088.17 AC-088.15: `working tree is dirty` with a stated `code` is `code`, source `given`; every allowed cause is `given`."""
    res = er.resolve("code", "working tree is dirty")
    assert (res.cause, res.source, res.rule) == ("code", "given", None)
    for cause in ALLOWED:
        res = er.resolve(cause, "waiting for approval to create the branch")
        assert (res.cause, res.source, res.rule) == (cause, "given", None)
        assert er.message(res) is None


@pytest.mark.parametrize("stated", [None, "", "unknown", "bogus", "Platform "])
def test_an_unstated_or_unknown_cause_goes_through_the_rules(stated):
    """AC-088.15: `None`, `unknown` and any value outside the four allowed causes count as not stated."""
    res = er.resolve(stated, "commit needs permission")
    assert (res.cause, res.source, res.rule) == ("environment", "rule", "git-action-awaits-approval")


def test_no_rule_yields_platform():
    """AC-088.17: no rule yields `platform`, so a classified escalation is never filed."""
    assert er.RULES and all(r.cause in ("environment", "decision") for r in er.RULES)
    assert [r.name for r in er.RULES] == ["spec-test-conflict", "left-for-review", "git-action-awaits-approval", "dirty-working-tree"]
    samples = ["waiting for approval to create the branch", "working tree is dirty", "spec/test conflict", "left for the user to review",
               "platform failure: copier render fails", "the platform is broken"]
    assert all(er.resolve(None, s).cause != "platform" for s in samples)


def test_effective_classifies_an_older_unknown_record_without_cause_source():
    """AC-088.21: a stored `unknown` without `cause_source` is classified with the current rules when read."""
    res = er.effective({"reason": "waiting for approval to create the branch", "cause": "unknown"})
    assert (res.cause, res.source, res.rule) == ("environment", "rule", "git-action-awaits-approval")
    res = er.effective({"reason": "needs a decision on rate limits", "cause": "unknown"})
    assert (res.cause, res.source) == ("unknown", "none")
    res = er.effective({"reason": "working tree is dirty"})                              # no cause at all
    assert (res.cause, res.source) == ("environment", "rule")
    res = er.effective({"reason": "spec/test conflict", "cause": "unknown", "cause_source": "none"})   # written under an older table
    assert (res.cause, res.source, res.rule) == ("decision", "rule", "spec-test-conflict")


def test_effective_keeps_a_stored_allowed_cause():
    """AC-088.21 AC-088.17: a stored allowed cause is taken as it is, whatever the reason says."""
    res = er.effective({"reason": "working tree is dirty", "cause": "code"})
    assert (res.cause, res.source, res.rule) == ("code", "given", None)
    res = er.effective({"reason": "x", "cause": "platform", "cause_source": "given"})
    assert (res.cause, res.source) == ("platform", "given")
    res = er.effective({"reason": "commit needs permission", "cause": "environment", "cause_source": "rule", "rule": "git-action-awaits-approval"})
    assert (res.cause, res.source, res.rule) == ("environment", "rule", "git-action-awaits-approval")


@pytest.mark.parametrize("esc", [{}, {"reason": None, "cause": 5}, {"reason": 7}, {"cause": ["x"], "reason": ["y"]}])
def test_effective_tolerates_a_malformed_escalation(esc):
    """AC-088.21: missing or non-string fields never raise; the result is `unknown`."""
    res = er.effective(esc)
    assert (res.cause, res.source) == ("unknown", "none")
