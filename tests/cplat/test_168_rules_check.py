"""Spec 168 acceptance tests: `cplat platform rules check` on small fixture trees (AC-168.1 to AC-168.5).

Seam: a tree under tmp_path with plugin prompts, `docs/rules/` (the register) and workflows; `rulescheck.check(root, only=…)` and
the CLI `cplat platform rules check [--json] [--repo DIR]`. The contract is design.md, section Contract."""
import json
import re

import pytest

import cplat
from rules_support import (ENTRIES, GOOD_BODY, GOOD_ENTRIES, HARD, PROMPT, PROSE, R1, R3, REGISTER, STATEMENT, add_prompt, check, e,
                           entries_text, fv, good_repo, kinds, line_of, of_kind, promptrules, put)

REG_FILE = ENTRIES


def cli(capsys, root, *extra):
    rc = cplat.main(["platform", "rules", "check", "--repo", str(root), *extra])
    out = capsys.readouterr()
    return rc, out.out, out.err


def only(res, kind):
    [f] = of_kind(res, kind)
    return f


def with_extra(tmp_path, extra, items=None, **kw):
    """The good tree plus `extra` at the end of the prompt."""
    return good_repo(tmp_path, GOOD_BODY + "\n" + extra, items, **kw)


def with_entry(tmp_path, extra, *entry):
    return with_extra(tmp_path, extra, [*GOOD_ENTRIES, *entry])


# ---------------- AC-168.1 every rule sentence has exactly one entry ----------------

def test_a_classified_reasoned_marked_prompt_passes_ac_168_1(tmp_path):  # AC-168.1
    res = check(good_repo(tmp_path))
    assert res.ok and res.failures == []
    assert res.counts["rule_sentences"] == 3 and res.counts["hard_rules"] == 1
    assert res.counts["entries"]["hard"] == 1 and res.counts["entries"]["practice"] == 1 and res.counts["entries"]["experience"] == 1


def test_a_rule_sentence_without_an_entry_fails_with_file_line_and_text_ac_168_1(tmp_path):  # AC-168.1
    root = with_extra(tmp_path, "Never merge on a red build, because the base then breaks.\n")
    res = check(root)
    f = only(res, "no-entry")
    assert not res.ok and kinds(res) == ["no-entry"]
    assert fv(f, "file") == PROMPT and fv(f, "line") == line_of(root, PROMPT, "Never merge on a red build")
    assert "Never merge on a red build, because the base then breaks." in fv(f, "text")


def test_an_entry_whose_text_no_longer_occurs_is_stale_ac_168_1(tmp_path):  # AC-168.1
    items = [e("R1", "Always run the unit tests first", "practice"), *GOOD_ENTRIES[1:]]
    root = good_repo(tmp_path, items=items)
    res = check(root)
    stale = only(res, "stale-entry")
    assert fv(stale, "file") == REG_FILE and fv(stale, "line") == line_of(root, REG_FILE, "id: R1")
    assert fv(stale, "text") == "Always run the unit tests first"
    assert kinds(res) == ["no-entry", "stale-entry"]            # and the sentence the entry no longer matches has none


def test_an_entry_of_a_prompt_that_is_gone_is_stale_ac_168_1(tmp_path):  # AC-168.1
    root = good_repo(tmp_path)
    put(root, "docs/rules/plugins/svc/commands/gone.yml", entries_text([e("R1", "Always do the thing", "practice")]))
    f = only(check(root), "stale-entry")
    assert fv(f, "file") == "docs/rules/plugins/svc/commands/gone.yml" and fv(f, "line") == 2


def test_two_entries_for_one_sentence_are_ambiguous_ac_168_1(tmp_path):  # AC-168.1
    root = good_repo(tmp_path, items=[*GOOD_ENTRIES, e("R4", "run the tests first", "practice")])
    f = only(check(root), "ambiguous-entry")
    assert fv(f, "line") > 0 and "Always run the tests first" in fv(f, "text")


def test_an_entry_matches_a_sentence_across_a_line_break_ac_168_1(tmp_path):  # AC-168.1
    body = "Always run the\ntests first, because a red suite hides every later failure.\n"
    root = good_repo(tmp_path, body, [GOOD_ENTRIES[0]], hard={})
    assert check(root).ok


@pytest.mark.parametrize("sentence", [
    "Never reuse a branch.", "Always rebase first.", "You must sign off.", "Do not edit the lock file.", "Don't edit the lock file.",
    "Don’t edit the lock file.", "Only approved specs are built.", "Unless it is red, merge it.", "Except for docs, wait for CI.",
    "DO NOT edit the lock file.", "never reuse a branch."])
def test_every_rule_word_makes_a_rule_sentence_ac_168_1(tmp_path, sentence):  # AC-168.1
    root = with_extra(tmp_path, sentence + "\n")
    f = only(check(root), "no-entry")
    assert fv(f, "line") == line_of(root, PROMPT, sentence) and sentence in fv(f, "text")


@pytest.mark.parametrize("line", ["## Only the changed files", "| Always | the coder |", "> Never mind the noise.",
                                  "* Never reuse a branch.", "+ Never reuse a branch.", "1. Never reuse a branch.", "2) Never reuse a branch."])
def test_headings_rows_quotes_and_items_are_scanned_ac_168_1(tmp_path, line):  # AC-168.1
    root = with_extra(tmp_path, line + "\n")
    f = only(check(root), "no-entry")
    assert fv(f, "line") == line_of(root, PROMPT, line)


def test_words_that_only_contain_a_rule_word_and_masked_code_are_no_rule_ac_168_1(tmp_path):  # AC-168.1
    body = GOOD_BODY + ("\nNevertheless the mustard stays; alwaysish and exceptional things are fine.\n\nRun `never` now.\n"
                        "\n- Run `git push --force` and `cplat spec check` today.\n")
    assert check(good_repo(tmp_path, body)).ok


def test_frontmatter_code_blocks_comments_and_non_prompts_are_not_scanned_ac_168_1(tmp_path):  # AC-168.1
    root = good_repo(tmp_path)
    put(root, "plugins/svc/commands/other.md",
        "---\ndescription: Never mind, only for tests\n---\nYou are another.\n\n" + STATEMENT + "\n\n"
        "```bash\nnever run this; always skip\n```\n\n~~~\nDo not read this\n~~~\n\n<!-- never, always -->\n\n"
        "<!--\nmust not count\n-->\n")
    put(root, "plugins/svc/README.md", "Never edit this; it is not a prompt.\n")
    put(root, "docs/guide.md", "Always read this.\n")
    put(root, "plugins/svc/commands/notes.txt", "never\n")
    res = check(root)
    assert res.ok and res.counts["rule_sentences"] == 3


def test_a_sentence_ends_at_a_period_and_not_before_a_lowercase_word_ac_168_1(tmp_path):  # AC-168.1
    body = ("Run the suite first.\nNever skip the lint, because CI refuses it.\n\n"
            "Use the linter, e.g. ruff, never plain flake8, because it is slower.\n")
    root = good_repo(tmp_path, body, [e("R1", "Never skip the lint", "practice"), e("R2", "never plain flake8", "practice")], hard={})
    assert check(root).ok
    root2 = good_repo(tmp_path / "b", body, [], hard={})
    lines = sorted(fv(f, "line") for f in of_kind(check(root2), "no-entry"))
    assert lines == [line_of(root2, PROMPT, "Never skip the lint"), line_of(root2, PROMPT, "Use the linter")]


def test_a_class_not_a_rule_needs_no_reason_ac_168_1(tmp_path):  # AC-168.1
    root = with_entry(tmp_path, "Lint fixes only.\n", e("R4", "Lint fixes only", "not a rule"))
    assert check(root).ok


def test_a_retired_entry_never_matches_a_sentence_ac_168_1(tmp_path):  # AC-168.1
    retired = e("R4", "Never merge on a red build", "retired", retired="2026-11-10", reason="a cplat command now refuses it")
    root = with_entry(tmp_path, "Never merge on a red build, because the base then breaks.\n", retired)
    assert kinds(check(root)) == ["no-entry", "retired-present"]


def test_a_missing_register_fails_ac_168_1(tmp_path, capsys):  # AC-168.1
    root = good_repo(tmp_path)
    (root / REGISTER).unlink()
    f = only(check(root), "no-register")
    assert fv(f, "line") == 0
    assert cli(capsys, root)[0] == 1


@pytest.mark.parametrize("items", [
    [e("R1", "Always run the tests first", "maybe")],
    [e("R1", "Always run the tests first"), e("R1", "Never skip the lint step")],
    [e("R1", "Always run the tests first", color="red")],
    [e("R1", "Always run the tests first", hard="issue-filing-needs-consent")],
    [e("R1", "Always run the tests first", retired="2026-11-10")],
    [e("R1", "Always run the tests first", source="issue five")],
    [e("R1", "Always run the tests first", benchmark_runs=["r-1"])],
    [e("first", "Always run the tests first")],
    [{"id": "R1", "class": "practice"}],
], ids=["unknown-class", "duplicate-id", "unknown-key", "hard-key-on-practice", "retired-key-on-practice", "bad-source",
        "benchmark-on-practice", "bad-id", "no-text"])
def test_a_schema_violation_is_a_bad_entry_ac_168_1(tmp_path, items):  # AC-168.1
    root = good_repo(tmp_path, items=items)
    f = of_kind(check(root), "bad-entry")
    assert f and fv(f[0], "file") == REG_FILE and fv(f[0], "line") > 0


def test_an_entry_with_an_enforcement_on_a_hard_rule_is_a_bad_entry_ac_168_1(tmp_path):  # AC-168.1
    items = [*GOOD_ENTRIES[:2], e("R3", "never file an issue without the user's OK", "hard", hard="issue-filing-needs-consent",
                                  enforced_by="ci:dco")]
    assert "bad-entry" in kinds(check(good_repo(tmp_path, items=items)))


def test_unreadable_yaml_and_a_register_file_without_a_prompt_path_are_bad_entries_ac_168_1(tmp_path):  # AC-168.1
    root = good_repo(tmp_path)
    put(root, ENTRIES, "rules: [\n  - id: R1\n")
    assert fv(only(check(root), "bad-entry"), "file") == REG_FILE
    root2 = good_repo(tmp_path / "b")
    put(root2, "docs/rules/plugins/svc/notes/x.yml", entries_text([e("R1", "Always do it", "practice")]))
    assert fv(only(check(root2), "bad-entry"), "file") == "docs/rules/plugins/svc/notes/x.yml"


def test_the_text_output_has_one_line_per_failure_and_an_ok_line_ac_168_1(tmp_path, capsys):  # AC-168.1
    root = good_repo(tmp_path)
    rc, out, _ = cli(capsys, root)
    assert rc == 0 and re.fullmatch(r"OK: 3 rule sentences classified, 1 hard rules; \d+ prompt targets resolve; \d+ interface pins; prompts \d+ bytes \(baseline 10000000\)\n", out), out
    root2 = with_extra(tmp_path / "b", "Never merge on a red build, because the base then breaks.\n")
    rc, out, _ = cli(capsys, root2)
    line = line_of(root2, PROMPT, "Never merge on a red build")
    assert rc == 1
    assert out.splitlines() == [f'FAIL no-entry {PROMPT}:{line}: rule sentence has no register entry: '
                                '"Never merge on a red build, because the base then breaks."',
                                "1 failure(s); see docs/rules/README.md"]


def test_the_json_output_carries_ok_failures_counts_and_bytes_ac_168_1(tmp_path, capsys):  # AC-168.1
    root = with_extra(tmp_path, "Never merge on a red build, because the base then breaks.\n")
    rc, out, _ = cli(capsys, root, "--json")
    doc = json.loads(out)
    assert rc == 1 and doc["ok"] is False and doc["baseline_bytes"] == 10_000_000 and doc["prompt_bytes"] > 0
    [f] = doc["failures"]
    assert set(f) == {"kind", "file", "line", "text", "message"} and f["kind"] == "no-entry" and f["file"] == PROMPT
    assert doc["counts"]["rule_sentences"] == 4 and doc["counts"]["hard_rules"] == 1
    assert set(doc["counts"]["entries"]) >= {"hard", "practice", "experience"}
    rc, out, _ = cli(capsys, good_repo(tmp_path / "b"), "--json")
    assert rc == 0 and json.loads(out)["ok"] is True and json.loads(out)["failures"] == []


def test_a_usage_error_exits_2_and_the_command_is_listed_ac_168_1(tmp_path, capsys):  # AC-168.1
    try:
        rc = cplat.main(["platform", "rules", "check", "--repo", str(good_repo(tmp_path)), "--no-such-option"])
    except SystemExit as exc:
        rc = exc.code
    capsys.readouterr()
    assert rc == 2
    assert "platform rules check" in cplat.__doc__


def test_only_limits_the_per_file_checks_and_skips_the_global_ones_ac_168_1(tmp_path, capsys):  # AC-168.1
    root = good_repo(tmp_path, baseline_bytes=1)                                    # the bytes check would fail
    add_prompt(root, "plugins/svc/commands/broken.md", "Never merge on a red build, because the base then breaks.\n", None)
    add_prompt(root, "plugins/svc/agents/fine.md", "Always run the tests first, because a red suite hides every later failure.\n",
               [e("R1", "Always run the tests first", "practice")])
    whole = check(root)
    assert "bytes" in kinds(whole) and "no-entry" in kinds(whole)
    assert check(root, only=["plugins/svc/commands/demo.md", "plugins/svc/agents"]).ok
    one = check(root, only=["plugins/svc/commands/broken.md"])
    assert kinds(one) == ["no-entry"] and fv(one.failures[0], "file") == "plugins/svc/commands/broken.md"
    rc, out, _ = cli(capsys, root, "--only", "plugins/svc/agents", "--only", "plugins/svc/commands/demo.md")
    assert rc == 0 and out.startswith("OK:")
    rc, out, _ = cli(capsys, root, "--only", "plugins/svc/commands/broken.md")
    assert rc == 1 and "no-entry" in out and "bytes" not in out


# ---------------- AC-168.2 a reason of at least 3 words ----------------

def reasoned(tmp_path, sentence, cls="practice", extra=None):
    """The good tree with one more sentence, entered as `cls`; returns (root, result)."""
    if cls == "hard":
        entry = e("R4", "Never reuse a branch", "hard", hard="issue-filing-needs-consent")
        sentence = "**Hard rule:** " + sentence
    else:
        entry = e("R4", "reuse a branch", cls, **(extra or {}))
    root = with_entry(tmp_path, sentence + "\n", entry)
    return root, check(root)


@pytest.mark.parametrize("cls", ["hard", "practice", "experience"])
def test_a_rule_without_a_reason_fails_with_file_and_line_ac_168_2(tmp_path, cls):  # AC-168.2
    extra = {"source": "#478"} if cls == "experience" else None
    root, res = reasoned(tmp_path, "Never reuse a branch.", cls, extra)
    f = only(res, "no-reason")
    assert kinds(res) == ["no-reason"] and fv(f, "file") == PROMPT and fv(f, "line") == line_of(root, PROMPT, "Never reuse a branch")


@pytest.mark.parametrize("word", ["so that", "because", "since", "otherwise", "Because", "SINCE"])
def test_each_reason_word_introduces_a_reason_ac_168_2(tmp_path, word):  # AC-168.2
    _, res = reasoned(tmp_path, f"Never reuse a branch, {word} a stale base breaks the merge.")
    assert res.ok, res.failures


@pytest.mark.parametrize("clause", ["because it fails.", "because #496 and spec 048 ADR-017.", "so that ADR-017 spec 048 #496.",
                                    "because of #496.", "since it works.", "because it fails (#496).", "because [x](../../../docs/a/b/c.md).",
                                    "because [the guide](../../../docs/a/b/c.md)."])
def test_a_reason_of_fewer_than_three_words_besides_references_is_short_ac_168_2(tmp_path, clause):  # AC-168.2
    root, res = reasoned(tmp_path, f"Never reuse a branch, {clause}")
    f = only(res, "short-reason")
    assert kinds(res) == ["short-reason"] and fv(f, "line") == line_of(root, PROMPT, "Never reuse a branch")


@pytest.mark.parametrize("clause", ["because it fails often.", "because it fails often (#496).", "since a stale base breaks (spec 048, ADR-017).",
                                    "because the base breaks, so that nobody waits."])
def test_three_words_besides_references_are_a_reason_ac_168_2(tmp_path, clause):  # AC-168.2
    assert reasoned(tmp_path, f"Never reuse a branch, {clause}")[1].ok


@pytest.mark.parametrize("sentence", [
    "Never reuse a branch. Because a stale base breaks the merge, this holds.",       # the reason is another sentence of a paragraph
    "Never reuse a branch with `because a stale base breaks`.",                        # the reason word is inside a code span
    "Never reuse a branch, becausefoo is bar baz qux.",                                # not a whole word
])
def test_only_a_reason_in_the_rule_sentence_itself_counts_in_a_paragraph_ac_168_2(tmp_path, sentence):  # AC-168.2
    res = reasoned(tmp_path, sentence)[1]
    assert kinds(res) == ["no-reason"]


@pytest.mark.parametrize("block", [
    "- Never reuse a branch.\n  Since a stale base breaks, the merge fails.",           # a second sentence of the item
    "- Never reuse a branch when work\n  continues, since a stale base breaks the merge.",   # a continuation line of the item
    "| Never reuse a branch | because a stale base breaks the merge |",                  # the table row
    "## Never reuse a branch because a stale base breaks the merge",                     # the heading
])
def test_a_list_item_row_or_heading_is_one_scope_ac_168_2(tmp_path, block):  # AC-168.2
    assert reasoned(tmp_path, block)[1].ok


# ---------------- AC-168.3 a practice states its purpose, not a condition ----------------

CONDITIONS = [
    "Run the tester only when new internals appear, because untested internals break later.",
    "Run the tester only if new internals appear, because untested internals break later.",
    "Always run the tester unless the change is docs-only, because untested internals break later.",
    "Always run the tester except for docs changes, because untested internals break later.",
]


@pytest.mark.parametrize("cls", ["practice", "experience"])
@pytest.mark.parametrize("sentence", CONDITIONS)
def test_a_practice_with_a_condition_clause_must_state_its_purpose_ac_168_3(tmp_path, cls, sentence):  # AC-168.3
    entry = e("R4", sentence.split(",")[0], cls, **({"source": "#478"} if cls == "experience" else {}))
    root = with_entry(tmp_path, sentence + "\n", entry)
    res = check(root)
    f = only(res, "condition")
    assert kinds(res) == ["condition"] and fv(f, "file") == PROMPT and fv(f, "line") == line_of(root, PROMPT, sentence[:20])
    assert "state the purpose instead" in fv(f, "message")


@pytest.mark.parametrize("condition", ["unless the user agrees", "only when the user agrees", "except for the user"])
def test_a_hard_rule_may_keep_a_condition_clause_ac_168_3(tmp_path, condition):  # AC-168.3
    _, res = reasoned(tmp_path, f"Never reuse a branch {condition}, because a stale base breaks the merge.", "hard")
    assert res.ok, res.failures


def test_only_without_when_or_if_is_no_condition_and_a_non_rule_may_have_one_ac_168_3(tmp_path):  # AC-168.3
    sentence = "Run only the changed tests, because the full suite takes too long."
    assert check(with_entry(tmp_path, sentence + "\n", e("R4", "Run only the changed tests", "practice"))).ok
    root = with_entry(tmp_path / "b", "Lint fixes except docs.\n", e("R4", "Lint fixes except docs", "not a rule"))
    assert check(root).ok


# ---------------- AC-168.4 a hard rule names its enforcement ----------------

def hard_tree(tmp_path, table, entry_hard="the-key"):
    items = [e("R3", "never file an issue without the user's OK", "hard", hard=entry_hard), *GOOD_ENTRIES[:2]]
    return good_repo(tmp_path, items=items, hard=table)


@pytest.mark.parametrize("by", ["cplat spec test-diff", "cplat component build merge", "cplat issue triage", "cplat resource restore",  # interface: enforcement keys the rules check resolves
                                "cplat platform pr-check", "cplat platform rules check", "cplat pr open", "ci:security", "ci:dco",
                                "ci:tmpl-build"])
def test_a_cplat_command_or_ci_job_is_an_enforcement_ac_168_4(tmp_path, by):  # AC-168.4
    res = check(hard_tree(tmp_path, {"the-key": {"enforced_by": by, "source": "spec 048"}}))
    assert res.ok, res.failures


@pytest.mark.parametrize("by", ["cplat nonsense", "cplat platform nonsense", "cplat component nonsense", "ci:no-such-job", "run it by hand"])
def test_an_enforcement_that_names_no_command_or_job_is_bad_ac_168_4(tmp_path, by):  # AC-168.4
    root = hard_tree(tmp_path, {"the-key": {"enforced_by": by}})
    res = check(root)
    f = only(res, "bad-enforcement")
    assert kinds(res) == ["bad-enforcement"] and fv(f, "file") == REGISTER and fv(f, "line") > 0


def test_an_intentional_prose_rule_needs_three_words_ac_168_4(tmp_path):  # AC-168.4
    assert check(hard_tree(tmp_path, {"the-key": {"intentional_prose_rule": "no tool can see"}})).ok
    for n, table in enumerate(({"the-key": {"source": "ADR-033"}}, {"the-key": {"intentional_prose_rule": "not possible"}})):
        res = check(hard_tree(tmp_path / str(n), table))
        assert kinds(res) == ["no-enforcement"] and fv(res.failures[0], "file") == REGISTER


def test_a_hard_entry_must_name_a_key_of_the_table_ac_168_4(tmp_path):  # AC-168.4
    root = hard_tree(tmp_path, {"the-key": {"intentional_prose_rule": PROSE}}, entry_hard="no-such-key")
    res = check(root)
    f = only(res, "unknown-hard")
    assert fv(f, "file") == REG_FILE and fv(f, "line") == line_of(root, REG_FILE, "id: R3")


def test_a_practice_enforcement_is_checked_too_ac_168_4(tmp_path):  # AC-168.4
    ok = [e("R1", "Always run the tests first", "practice", enforced_by="ci:dco"), *GOOD_ENTRIES[1:]]
    assert check(good_repo(tmp_path, items=ok)).ok
    bad = [e("R1", "Always run the tests first", "practice", enforced_by="ci:nope"), *GOOD_ENTRIES[1:]]
    root = good_repo(tmp_path / "b", items=bad)
    f = only(check(root), "bad-enforcement")
    assert fv(f, "file") == REG_FILE and fv(f, "line") == line_of(root, REG_FILE, "id: R1")


def test_at_most_twenty_distinct_hard_rules_ac_168_4(tmp_path):  # AC-168.4
    def table(n):
        return {f"rule-{i}": {"intentional_prose_rule": PROSE} for i in range(n)} | HARD
    assert check(good_repo(tmp_path / "a", hard=table(19))).ok                      # 19 + the one the entry uses = 20
    res = check(good_repo(tmp_path / "b", hard=table(20)))
    f = only(res, "too-many-hard")
    assert fv(f, "file") == REGISTER and fv(f, "line") > 0 and res.counts["hard_rules"] == 21


def test_a_hard_rule_repeated_in_several_prompts_counts_once_ac_168_4(tmp_path):  # AC-168.4
    root = good_repo(tmp_path)
    add_prompt(root, "plugins/svc/agents/other.md", R3 + "\n", [e("R1", "never file an issue without the user's OK", "hard",
                                                                  hard="issue-filing-needs-consent")])
    res = check(root)
    assert res.ok, res.failures
    assert res.counts["hard_rules"] == 1 and res.counts["entries"]["hard"] == 2


# ---------------- AC-168.5 the marker and the statement ----------------

def test_a_hard_rule_without_the_marker_fails_ac_168_5(tmp_path):  # AC-168.5
    body = GOOD_BODY.replace("**Hard rule:** ", "")
    root = good_repo(tmp_path, body)
    f = only(check(root), "no-marker")
    assert fv(f, "file") == PROMPT and fv(f, "line") == line_of(root, PROMPT, "never file an issue")  # interface: fixture rule text the check locates


def test_a_marker_on_a_rule_that_is_not_hard_fails_ac_168_5(tmp_path):  # AC-168.5
    body = GOOD_BODY.replace("Always run", "**Hard rule:** Always run")
    root = good_repo(tmp_path, body)
    res = check(root)
    f = only(res, "stray-marker")
    assert kinds(res) == ["stray-marker"] and fv(f, "line") == line_of(root, PROMPT, "Always run the tests")


def test_a_marker_on_a_sentence_without_any_entry_is_stray_ac_168_5(tmp_path):  # AC-168.5
    root = with_extra(tmp_path, "**Hard rule:** this sentence has no rule word.\n")
    f = only(check(root), "stray-marker")
    assert fv(f, "line") == line_of(root, PROMPT, "this sentence has no rule word")


@pytest.mark.parametrize("rel", ["plugins/svc/commands/demo.md", "plugins/svc/agents/helper.md"])
def test_an_agent_or_command_without_the_statement_fails_ac_168_5(tmp_path, rel):  # AC-168.5
    root = good_repo(tmp_path)
    add_prompt(root, rel, "Plain text.\n", None, statement=False)
    f = [f for f in of_kind(check(root), "no-statement") if fv(f, "file") == rel]
    assert len(f) == 1


def test_a_changed_statement_is_no_statement_ac_168_5(tmp_path):  # AC-168.5
    root = good_repo(tmp_path)
    p = root / PROMPT
    p.write_text(p.read_text().replace(STATEMENT, "Hard rules are never departed from."))
    assert [fv(f, "file") for f in of_kind(check(root), "no-statement")] == [PROMPT]


def test_references_skills_and_tombstones_need_no_statement_ac_168_5(tmp_path):  # AC-168.5
    root = good_repo(tmp_path)
    put(root, "plugins/svc/references/guide.md", "---\ndescription: g\n---\nA reference.\n")
    put(root, "plugins/svc/skills/x/SKILL.md", "---\nname: x\n---\nA skill.\n")
    put(root, "plugins/svc/commands/old.md", "---\ndescription: Moved in 5.0\nmoved-to: /svc:demo\n---\nMoved to `/svc:demo`.\n")
    assert check(root).ok


def test_the_statement_may_wrap_lines_but_stands_once_ac_168_5(tmp_path):  # AC-168.5
    root = good_repo(tmp_path)
    p = root / PROMPT
    p.write_text(p.read_text().replace("Any other rule", "Any\nother   rule"))
    assert check(root).ok
    p.write_text(p.read_text() + "\n" + STATEMENT + "\n")
    f = only(check(root), "repeated-statement")
    assert fv(f, "file") == PROMPT


def test_prompt_scanning_primitives_follow_the_contract_ac_168_5():  # AC-168.5
    assert promptrules.MARKER == "**Hard rule:**" and promptrules.STATEMENT == STATEMENT
    found = promptrules.sentences(PROMPT, prompt_with(GOOD_BODY))
    assert [s.text for s in found if s.rule] == [R1, "Never skip the lint step, since the CI lint job refuses it otherwise.", R3]
    assert all(s.file == PROMPT and s.line > 0 for s in found)
    assert promptrules.is_tombstone("---\nmoved-to: /a:b\n---\nx\n") and not promptrules.is_tombstone("---\nname: a\n---\nx\n")
    assert promptrules.entries_path("plugins/a/b.md") == "docs/rules/plugins/a/b.yml"


def prompt_with(body):
    return "---\ndescription: Demo\n---\nYou are the demo.\n\n" + STATEMENT + "\n\n" + body

