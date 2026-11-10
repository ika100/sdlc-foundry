"""Spec 172: `cplat platform rules check` fails an instruction with a condition clause classed `not a rule` (AC-172.8).

Seam: the spec 168 fixture tree (`rules_support`): one prompt, its register file; `rulescheck.check` and the CLI. `instruction` is
the pure function of `promptrules` (design, section 6).
"""
import json

import pytest

import cplat
from rules_support import GOOD_ENTRIES, GOOD_BODY, PROMPT, e, fv, good_repo, kinds, line_of, of_kind, promptrules, check

READ = "Read the design only when the brief lacks a fact."
MERGE = "Merge the pull request, unless the user said not to merge."
STATE = "The check runs only when a spec is building."


def tree(tmp_path, sentence, cls="not a rule"):
    entry = e("R4", sentence.rstrip("."), cls)
    return good_repo(tmp_path, GOOD_BODY + "\n" + sentence + "\n", [*GOOD_ENTRIES, entry])


@pytest.mark.parametrize("sentence", [READ, MERGE])
def test_an_instruction_with_a_condition_classed_not_a_rule_fails_ac_172_8(tmp_path, sentence):  # AC-172.8
    root = tree(tmp_path, sentence)
    res = check(root)
    [f] = of_kind(res, "hidden-rule")
    assert not res.ok and kinds(res) == ["hidden-rule"]
    assert fv(f, "file") == PROMPT and fv(f, "line") == line_of(root, PROMPT, sentence) and sentence in fv(f, "text")
    message = fv(f, "message")
    assert "practice" in message and "purpose" in message and "R4" in message


def test_a_statement_of_fact_with_a_condition_passes_as_not_a_rule_ac_172_8(tmp_path):  # AC-172.8
    res = check(tree(tmp_path, STATE))
    assert res.ok and res.failures == []


def test_the_cli_fails_with_the_finding_in_text_and_json_ac_172_8(tmp_path, capsys):  # AC-172.8
    root = tree(tmp_path, READ)
    line = line_of(root, PROMPT, READ)
    rc = cplat.main(["platform", "rules", "check", "--repo", str(root)])
    out = capsys.readouterr().out
    assert rc == 1 and f"FAIL hidden-rule {PROMPT}:{line}: " in out and f'"{READ}"' in out
    rc = cplat.main(["platform", "rules", "check", "--repo", str(root), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1 and doc["ok"] is False
    [f] = [x for x in doc["failures"] if x["kind"] == "hidden-rule"]
    assert f["file"] == PROMPT and f["line"] == line and f["text"] == READ


@pytest.mark.parametrize("sentence,expected", [
    (READ, True), (MERGE, True), (STATE, False),
    ("The coder tells you when it stops, unless it is done.", True),                       # you / your
    ("Your report names each test, except the passing ones.", True),
    ("If the base is red, merge it only when CI is green.", True),                        # a leading `If …,` clause is skipped
    ("When the plan changes, rebase the branch unless it is pushed.", True),
    ("**Note:** Use the lock file only when it exists.", True),                           # emphasis and a label are skipped
    ("- Run `cplat quiet ci` only if the tree is clean.", True),                          # a list marker is skipped
    ("The gate passes unless a test fails.", False),
    ("A merge happens only when the checks are green.", False),
])
def test_what_reads_as_an_instruction_ac_172_8(sentence, expected):  # AC-172.8
    assert promptrules.instruction(sentence) is expected


def test_the_verb_list_is_the_one_of_the_design_ac_172_8():  # AC-172.8
    verbs = set(promptrules.IMPERATIVES)
    assert {"read", "merge", "aim", "run", "use", "write", "don't", "re-run"} <= verbs and "the" not in verbs
