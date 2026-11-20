"""Spec 206 acceptance tests: the refused (deny) rules of an unattended run are checked against a sample of commands the run
needs and a sample it must refuse, before the first session (AC-206.1 to AC-206.7).

The checks live in scripts/cplat/denyrules.py and run first in `preflight.check`; the fake world is the one of spec 131.
"""
import importlib

import pytest

from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import BRANCH, World

DEFAULTS = ["main", "master", "trunk", "develop"]
BRANCHES = [BRANCH, "feature/x"]          # the component ship branch, the system ship branch

# The refused rules as spec 131 wrote them (before spec 206): a hand-written copy, so a change of the generator cannot hide a fault.
OLD = ["Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push * --force*)", "Bash(git push * -f*)",
       "Bash(git push * +*)", "Bash(git push * {d})", "Bash(git push * {d}:*{d}*)", "Bash(git push * {d}:refs*)",
       "Bash(git push * *:{d})", "Bash(git push * *:refs/heads/{d})",
       "Bash(gh pr merge*)", "Bash(gh api *merge*)",
       "Bash(cplat pr wait *--merge*)",
       "Bash(git rm -f*)", "Bash(git rm --force*)", "Bash(git rm -rf*)", "Bash(git rm -fr*)",
       "Bash(git rm * -f*)", "Bash(git rm * --force*)", "Bash(git rm * -rf*)", "Bash(git rm * -fr*)"]


def old(d="main"):
    return [r.format(d=d) for r in OLD]


def dr():
    return importlib.import_module("denyrules")


def pf():
    return importlib.import_module("preflight")


def must_allow(d, b):
    D, B = d, b
    return [f"git push -u origin {B}", f"git push origin {B}", "git push origin feature/x-fix", f"git push origin feature/{D}-page",
            f"git push --follow-tags origin {B}", "git push origin v1.2.0", f"git fetch origin {D} && git push origin {B}",
            f"gh pr create --base {D} --head {B} --title t --body-file .pr-body.md", "cplat pr wait 7",
            "cplat pr wait 7 -R acme/shop-api", "gh api repos/acme/x/pulls/7 --jq .mergeable",
            """gh api graphql -f query='{repository(owner:"acme",name:"x"){pullRequest(number:7){mergeStateStatus}}}'""",
            "git switch -c feature/x-force-field", "git rm tests/test_x.py", "git rm -r --cached build"]


def must_refuse(d, b):
    D, B = d, b
    return [f"git push origin {D}", f"git push -u origin {D}", f"git push origin HEAD:{D}", f"git push origin {D}:{D}",
            f"git push origin {B}:refs/heads/{D}", f"GIT_TRACE=1 git push origin {D}", f"git status && git push origin {D}",
            f"git push --force origin {B}", f"git push -f origin {B}", f"git push origin {B} --force-with-lease",
            f"git push origin +{B}", "gh pr merge 7 --squash", "gh api repos/acme/x/pulls/7/merge -X PUT",
            """gh api graphql -f query='mutation{mergePullRequest(input:{pullRequestId:"x"}){clientMutationId}}'""",
            "cplat pr wait 7 --merge", "git rm -f x", "git rm -rf src"]


# ---------------- the samples ----------------

def test_the_samples_are_the_ones_of_the_spec_ac_206_1():  # AC-206.1
    assert dr().must_allow("main", BRANCH) == must_allow("main", BRANCH)
    assert dr().must_allow("trunk", "feature/x") == must_allow("trunk", "feature/x")


def test_the_must_refuse_sample_is_the_one_of_the_spec_ac_206_2():  # AC-206.2
    assert dr().must_refuse("main", BRANCH) == must_refuse("main", BRANCH)
    assert dr().must_refuse("develop", "feature/x") == must_refuse("develop", "feature/x")


# ---------------- AC-206.7 (CI): the generated rules against both samples, every default and ship branch ----------------

@pytest.mark.parametrize("default", DEFAULTS)
@pytest.mark.parametrize("branch", BRANCHES)
def test_no_generated_rule_refuses_a_command_the_run_needs_ac_206_7(default, branch):  # AC-206.1 AC-206.7
    rules = dr().refused_rules(default)
    for command in dr().must_allow(default, branch):
        for rule in rules:
            assert not dr().refuses(rule, command), f'rule {rule} refuses "{command}" (default {default}, branch {branch})'


@pytest.mark.parametrize("default", DEFAULTS)
@pytest.mark.parametrize("branch", BRANCHES)
def test_every_command_the_run_must_not_run_is_refused_ac_206_7(default, branch):  # AC-206.2 AC-206.7
    rules = dr().refused_rules(default)
    for command in dr().must_refuse(default, branch):
        assert any(dr().refuses(r, command) for r in rules), f'no rule refuses "{command}" (default {default}, branch {branch})'


@pytest.mark.parametrize("default", DEFAULTS)
def test_the_whole_check_passes_for_the_generated_rules_ac_206_7(default):  # AC-206.7
    assert dr().problem(dr().refused_rules(default), default, BRANCHES) is None


def test_an_over_matching_rule_fails_with_its_name_and_the_command_ac_206_7():  # AC-206.7
    rules = dr().refused_rules("main") + ["Bash(git push * feature/*)"]
    msg = dr().problem(rules, "main", [BRANCH])
    assert msg is not None and "Bash(git push * feature/*)" in msg and '"git push -u origin feature/007-price-alerts"' in msg


def test_an_under_matching_set_fails_with_the_command_ac_206_7():  # AC-206.7
    rules = [r for r in dr().refused_rules("main") if r != "Bash(cplat pr wait *--merge*)"]
    msg = dr().problem(rules, "main", [BRANCH])
    assert msg is not None and '"cplat pr wait 7 --merge"' in msg


# ---------------- AC-206.3: matching as Claude Code does ----------------

@pytest.mark.parametrize("rule, command, expected", [
    ("Bash(git push * main)", "git push origin main", True),
    ("Bash(git push * main)", "git push --tags origin main", True),            # * matches spaces
    ("Bash(git push * main)", "git push origin main-fix", False),
    ("Bash(gh pr merge*)", "gh pr merge 7 --squash", True),
    ("Bash(cplat pr wait *)", "cplat pr wait", True),                           # a trailing " *" also matches the bare command
    ("Bash(cplat pr wait:*)", "cplat pr wait", True),                           # so does ":*"
    ("Bash(cplat pr wait:*)", "cplat pr wait 7", True),
    ("Bash(cplat pr wait:*)", "cplat pr waiter", False),
    ("Bash(git push * main)", "GIT_TRACE=1 git push origin main", True),       # past a leading assignment
    ("Bash(git push * main)", "A=1 B=2 git push origin main", True),
    ("Bash(git push * main)", "timeout 30 git push origin main", True),        # and the wrappers
    ("Bash(git push * main)", "time git push origin main", True),
    ("Bash(git push * main)", "nice -n 5 git push origin main", True),
    ("Bash(git push * main)", "nohup git push origin main", True),
    ("Bash(git push * main)", "stdbuf -o0 git push origin main", True),
    ("Bash(git push * main)", "FOO=1 timeout 5 nohup git push origin main", True),
    ("Bash(git push * main)", "git status && git push origin main", True),     # a compound command matches by any part
    ("Bash(git push * main)", "git status || git push origin main", True),
    ("Bash(git push * main)", "git status; git push origin main", True),
    ("Bash(git push * main)", "git log | git push origin main", True),
    ("Bash(git push * main)", "git status && git fetch origin", False),
    ("Bash(git push * main)", "echo hi", False),
    ("Bash(git push * main)", "Read(foo)", False),
    ("Read(**)", "git push origin main", False),                                # a rule that is not a Bash rule matches nothing
    ("Bash", "anything at all", True),
    ("Bash(*)", "anything at all", True),
])
def test_a_rule_matches_a_command_as_claude_code_does_ac_206_3(rule, command, expected):  # AC-206.3
    assert dr().refuses(rule, command) is expected


def test_the_matcher_is_exported_with_the_old_name_unchanged_for_the_rules_ac_206_3():  # AC-206.3
    assert pf().refused_rules is dr().refused_rules


# ---------------- AC-206.6: the generated rules ----------------

def test_the_merge_rules_replace_the_loose_gh_api_rule_ac_206_6():  # AC-206.6
    rules = dr().refused_rules("main")
    expected = old("main")
    i = expected.index("Bash(gh api *merge*)")
    assert rules == expected[:i] + ["Bash(gh api */pulls/*/merge*)", "Bash(gh api */merges*)", "Bash(gh api *mutation*merge*)"] + expected[i + 1:]


@pytest.mark.parametrize("command", [
    "gh api repos/acme/x/pulls/7 --jq .mergeable",
    """gh api graphql -f query='{repository(owner:"acme",name:"x"){pullRequest(number:7){mergeStateStatus}}}'""",
])
def test_a_read_of_the_merge_state_is_not_refused_ac_206_6(command):  # AC-206.6
    assert not any(dr().refuses(r, command) for r in dr().refused_rules("main"))


def test_every_merge_command_is_still_refused_ac_206_6():  # AC-206.6
    merges = [c for c in must_refuse("main", BRANCH) if "merge" in c or "--merge" in c]
    assert len(merges) == 4
    for command in merges:
        assert any(dr().refuses(r, command) for r in dr().refused_rules("main")), command


# ---------------- AC-206.4, AC-206.5: the run stops before the first session ----------------

@pytest.fixture()
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=False)


def inject(w, rules=None, default=None):
    """Replace the refused rules (and the default branch) the run gets."""
    import preflight
    if rules is not None:
        w.mp.setattr(preflight, "refused_rules", lambda d, _r=rules: list(_r))
    if default is not None:
        w.mp.setattr(preflight, "default_branch", lambda repo: default)


def deny_line(capsys):
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("preflight failed: ")]
    assert len(lines) == 1, out
    return out, lines[0]


def assert_stopped(w, store, out):
    assert w.sessions() == []
    assert "HEADLESS shop-api: preflight failed: deny-rules" in out
    rec = stored(store)[-1]
    assert rec["escalation"]["reason"] == "preflight failed: deny-rules"
    assert rec["budget"]["used"]["invocations"] == 0 and rec["budget"]["used"]["cost"] == 0


@pytest.mark.parametrize("prompt, branch", [(None, BRANCH), ("/system:ship 7", "feature/x")])
def test_a_rule_that_refuses_a_needed_command_stops_the_run_ac_206_4(w, store, capsys, prompt, branch):  # AC-206.1 AC-206.4
    inject(w, ["Bash(git push * feature/*)"])
    assert w.run(prompt=prompt) == 1
    out, line = deny_line(capsys)
    cmd = f"git push -u origin {branch}"
    assert line == (f'preflight failed: deny-rules: Bash(git push * feature/*) refuses "{cmd}", which the run needs; '
                    f'use: remove the rule')
    assert_stopped(w, store, out)


def test_the_old_gh_api_rule_is_named_with_its_correction_ac_206_4(w, store, capsys):  # AC-206.4
    inject(w, dr().refused_rules("main") + ["Bash(gh api *merge*)"])
    assert w.run() == 1
    out, line = deny_line(capsys)
    assert line == ('preflight failed: deny-rules: Bash(gh api *merge*) refuses "gh api repos/acme/x/pulls/7 --jq .mergeable", '
                    'which the run needs; use: Bash(gh api * merge*)')
    assert_stopped(w, store, out)


def test_where_no_single_rule_is_right_the_line_says_remove_the_rule_ac_206_4(w, store, capsys):  # AC-206.4
    inject(w, old("main"))
    assert w.run() == 1
    out, line = deny_line(capsys)
    assert line == ('preflight failed: deny-rules: Bash(gh api *merge*) refuses "gh api repos/acme/x/pulls/7 --jq .mergeable", '
                    'which the run needs; use: remove the rule')
    assert_stopped(w, store, out)


def test_the_correction_passes_the_whole_sample_ac_206_4():  # AC-206.4
    rules = dr().refused_rules("main") + ["Bash(gh api *merge*)"]
    fixed = dr().correction("Bash(gh api *merge*)", rules, "main", [BRANCH])
    assert fixed == "Bash(gh api * merge*)"
    swapped = [fixed if r == "Bash(gh api *merge*)" else r for r in rules]
    assert dr().problem(swapped, "main", [BRANCH]) is None


def test_a_rule_without_a_correction_gives_none_ac_206_4():  # AC-206.4
    assert dr().correction("Bash(gh api *merge*)", old("main"), "main", [BRANCH]) is None
    assert dr().problem(old("main"), "main", [BRANCH]).endswith("use: remove the rule")


def test_a_missing_refusal_stops_the_run_ac_206_5(w, store, capsys):  # AC-206.2 AC-206.5
    inject(w, [r for r in dr().refused_rules("main") if r != "Bash(git push * main)"])
    assert w.run() == 1
    out, line = deny_line(capsys)
    assert line == 'preflight failed: deny-rules: no rule refuses "git push origin main"; add: Bash(git push * main)'
    assert_stopped(w, store, out)


def test_a_missing_refusal_with_no_generated_rule_adds_the_command_itself_ac_206_5():  # AC-206.5
    msg = dr().problem(["Bash(gh pr merge*)"], "main", [BRANCH])
    assert msg == 'no rule refuses "git push origin main"; add: Bash(git push * main)'
    rules = [r for r in dr().refused_rules("main") if "gh pr merge" not in r]
    assert dr().problem(rules, "main", [BRANCH]) == 'no rule refuses "gh pr merge 7 --squash"; add: Bash(gh pr merge*)'


@pytest.mark.parametrize("name", ["release (old)", "a*b", "x)", "a,b", "two words", "tab\tname"])
def test_a_default_branch_a_rule_cannot_guard_stops_the_run_ac_206_5(w, store, capsys, name):  # AC-206.5
    inject(w, default=name)
    assert w.run() == 1
    out, line = deny_line(capsys)
    assert line == f'preflight failed: deny-rules: default branch "{name}" cannot be guarded by a rule'
    assert_stopped(w, store, out)


def test_the_unguardable_default_branch_wins_over_every_other_finding_ac_206_5():  # AC-206.5
    assert dr().problem(["Bash(git push * feature/*)"], "a*b", [BRANCH]) == 'default branch "a*b" cannot be guarded by a rule'


def test_the_deny_check_runs_before_the_other_preflight_checks_ac_206_4(w, store, capsys):  # AC-206.4
    w.mp.setenv("FAKE_GH_AUTH", "fail")
    (w.repo / ".claude" / "settings.json").unlink()
    inject(w, ["Bash(git push * feature/*)"])
    assert w.run() == 1
    _, line = deny_line(capsys)
    assert line.startswith("preflight failed: deny-rules: ")
