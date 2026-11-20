"""Spec 157 acceptance tests (AC-157.1 to AC-157.5): `pr_summary` renders a four-line summary block from records and
`cplat pr open` puts it at the top of the PR body.

Seams: a real git repository for the facts (spec, fragment, files against the base branch), a fake `gh` on PATH for issue titles,
the run store of spec 133 (`runs.start`, `runs.current_run`) and the `cplat pr open` fake (`pr_open.run`). The values are parsed
out of the block, never matched against the whole text.
"""
import os
import stat
import subprocess

import pytest

import pr as prmod
import pr_open
import runs
import runs_built
from test_runs_built_133 import agent, make_run
from waiting import with_prelude

START, END = "<!-- cplat:summary -->", "<!-- /cplat:summary -->"
HOW_START, HOW_END = "<!-- cplat:how-built -->", "<!-- /cplat:how-built -->"
LABELS = ["Changed", "Why", "Review", "Risks and follow-ups"]
TITLE = "feat(api): add the thing"
ORIGINAL = "## Summary\n\nDid it.\n"

SPEC = """---
spec_id: 157-thing
title: Thing title
status: building
priority: P1
shape: platform
---

# 157 — Thing title

## Problem

Reviewers cannot tell quickly. SECRET-PROBLEM-TEXT.

## Stories

As a reviewer, I want five lines, so that I know what to review first. More words that are not part of the clause.
**Repos:** the platform.

As a maintainer, I want text from records, so that it cannot be embellished.

## Acceptance criteria

- **AC-157.1** Given a body, when opened, then a block.
- **AC-157.2** Given a spec, when rendered, then a title.
- ~~**AC-157.3**~~ withdrawn: not needed.

## Open questions

None.
"""

NO_STORIES = SPEC.split("## Stories")[0] + "## Acceptance criteria\n\n- **AC-157.1** Given a body, when opened, then a block.\n"

VERIFICATION = """# Verification — 157 Thing

**Result:** pass

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-157.1 | met | `t` | `x.py:1` | |
| AC-157.2 | partial | `t` | `x.py:2` | |

## Deviations from the plan

1. **A helper is in no task's files.** Acceptable.
2. **The pre-poll waits first.** Accepted: it avoids a false no-checks.
3. **A rename of the module.** Not acceptable as is.

## Follow-ups

- **Cache the lookups.** Needs a design. Later.
- Add a retry for the
  mail call. Rest of it.
- none
- Fourth one.
"""

FINDINGS = [
    {"kind": "finding", "criterion": "AC-157.1", "task": None, "severity": "not met", "pass": "first", "cycle": 1, "tasks": ["t1"]},
    {"kind": "finding", "criterion": "AC-157.2", "task": None, "severity": "partial", "pass": "first", "cycle": 1, "tasks": ["t1"]},
    {"kind": "finding", "criterion": "AC-157.2", "task": None, "severity": "deviation", "pass": "first", "cycle": 1, "tasks": ["t1"]},
]
FIX_ROUND = {"kind": "fix-round", "cause": "test", "task": "t1"}


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(repo), *args], check=True, capture_output=True)


def make_repo(tmp_path, *, spec_text=SPEC, verification=VERIFICATION, changelog_dir=False, fragment=None, files=("a.py", "b.py")):
    """A repo on main (spec, verification, optional changelog folder) and a feature branch that adds `files` and a fragment."""
    r = tmp_path / "app"
    r.mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    (r / "README.md").write_text("app\n")
    if spec_text is not None:
        d = r / "docs" / "specs" / "157-thing"
        d.mkdir(parents=True)
        (d / "spec.md").write_text(spec_text)
        if verification is not None:
            (d / "verification.md").write_text(verification)
    if changelog_dir or fragment:
        (r / "docs" / "changelog.d").mkdir(parents=True)
        (r / "docs" / "changelog.d" / "README.md").write_text("# fragments\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    git(r, "checkout", "-qb", "feature/157-thing")
    for f in files:
        (r / f).write_text(f)
    if fragment:
        (r / "docs" / "changelog.d" / "157-thing.added.md").write_text(fragment)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "work")
    return r


@pytest.fixture(autouse=True)
def fake_gh(tmp_path, monkeypatch):
    """`gh issue view N` prints `Issue N title`; issue 99 fails. Nothing else of gh is reachable."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(with_prelude('#!/bin/sh\nif [ "$1" = issue ] && [ "$2" = view ]; then\n  n="${3#\\#}"\n'
                               '  [ "$n" = 99 ] && exit 1\n  echo "Issue $n title"\n  exit 0\nfi\nexit 1\n'))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


@pytest.fixture(autouse=True)
def no_run(monkeypatch):
    monkeypatch.setattr(runs, "current_run", lambda repo: None)


def render(repo, *, body=ORIGINAL, title=TITLE, spec="157", base="main"):
    import pr_summary
    return pr_summary.render(repo, body=body, title=title, spec=spec, base=base)


def fields(block):
    """The block as {label: value}; asserts the AC-157.1 shape on the way."""
    lines = block.splitlines()
    assert lines[0] == START and lines[1] == "**Summary**" and lines[-1] == END and len(lines) == 7, block
    out = {}
    for label, line in zip(LABELS, lines[2:6]):
        assert line.startswith(f"- **{label}:** "), line
        out[label] = line[len(f"- **{label}:** "):]
    return out


def with_run(monkeypatch, *events, spec="157"):
    rid = make_run(spec=spec, agents=[agent("svc:reviewer", *events)])
    monkeypatch.setattr(runs, "current_run", lambda repo: rid)
    return rid


# ---------------- AC-157.1: the block and its place ----------------

def test_the_block_has_the_marker_heading_and_four_bullets_ac_157_1(tmp_path):  # AC-157.1
    block = render(make_repo(tmp_path))
    assert block.endswith("\n") and list(fields(block)) == LABELS


def test_apply_puts_the_block_on_top_with_one_blank_line_ac_157_1():  # AC-157.1
    import pr_summary
    block = f"{START}\n**Summary**\n- a\n{END}\n"
    assert pr_summary.apply(ORIGINAL, block) == block + "\n" + ORIGINAL
    assert pr_summary.apply("\n\n" + ORIGINAL, block) == block + "\n" + ORIGINAL
    assert pr_summary.apply("", block).strip() == block.strip()


def test_apply_replaces_every_earlier_block_never_adds_a_second_ac_157_1():  # AC-157.1
    import pr_summary
    block = f"{START}\n**Summary**\n- new\n{END}\n"
    old = f"{START}\nold one\n{END}\n\n{ORIGINAL}\n{START}\nold two\n{END}\n\nTail.\n"
    out = pr_summary.apply(old, block)
    assert out.count(START) == 1 and out.count(END) == 1 and out.startswith(block)
    assert "old one" not in out and "old two" not in out
    assert "Did it." in out and "Tail." in out


@pytest.fixture
def popen(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / "c.py").write_text("c")       # not committed yet: `pr open` is about to commit it
    (repo / ".git" / "PR_BODY.md").write_text(ORIGINAL)
    f = pr_open_fake(repo, monkeypatch)
    return f


def pr_open_fake(repo, monkeypatch):
    from test_pr_open import Fake
    f = Fake(repo)
    f.origin = False                      # the base is `main` in this real repo
    monkeypatch.setattr(pr_open, "run", f)
    return f


def open_cmd(f, capsys, *extra):
    code = prmod.main(["open", "--title", TITLE, "--repo", str(f.repo), "--spec", "157", *extra])
    return code, capsys.readouterr().out


def sent(f):
    return (f.repo / ".git" / "PR_BODY.md").read_text()


@pytest.mark.parametrize("with_a_run", [False, True])
def test_pr_open_body_starts_with_the_block_and_keeps_the_rest_ac_157_1(popen, capsys, monkeypatch, with_a_run):  # AC-157.1
    if with_a_run:
        with_run(monkeypatch, *FINDINGS, FIX_ROUND)
    code, out = open_cmd(popen, capsys)
    assert code == 0 and "pr: ready" in out
    text = sent(popen)
    head, sep, rest = text.partition(END + "\n")
    assert sep and head.count(START) == 1 and text.startswith(START + "\n**Summary**\n")
    fields(head + END + "\n")
    assert rest.startswith("\n" + ORIGINAL)
    if with_a_run:
        assert rest.count(HOW_START) == 1 and rest.rstrip().endswith(HOW_END)
        section = runs_built.pr_section(popen.repo, "157")
        assert section and section.strip() in rest          # spec 133's block, unchanged content
    else:
        assert HOW_START not in text


def test_pr_open_replaces_a_summary_block_the_body_already_has_ac_157_1(popen, capsys):  # AC-157.1
    (popen.repo / ".git" / "PR_BODY.md").write_text(f"{START}\nstale\n{END}\n\n{ORIGINAL}")
    assert open_cmd(popen, capsys)[0] == 0
    text = sent(popen)
    assert text.count(START) == 1 and "stale" not in text and "Did it." in text
    open_cmd(popen, capsys)                                    # again: still one
    assert sent(popen).count(START) == 1


# ---------------- AC-157.2: Changed ----------------

def test_changed_is_the_spec_title_with_criteria_and_files_ac_157_2(tmp_path):  # AC-157.2
    f = fields(render(make_repo(tmp_path)))
    assert f["Changed"] == "Thing title (2 criteria of spec 157, 2 files)"


def test_a_component_repo_without_a_changelog_folder_never_falls_back_to_the_title_ac_157_2(tmp_path):  # AC-157.2
    r = make_repo(tmp_path)
    assert not (r / "docs" / "changelog.d").exists()
    assert "add the thing" not in fields(render(r))["Changed"]


def test_the_spec_title_wins_over_a_fragment_ac_157_2(tmp_path):  # AC-157.2
    r = make_repo(tmp_path, fragment="**A fragment sentence (#568).** More.\n")
    f = fields(render(r))
    assert f["Changed"].startswith("Thing title (2 criteria of spec 157, ")


def test_the_fragments_first_sentence_without_emphasis_is_next_ac_157_2(tmp_path):  # AC-157.2
    r = make_repo(tmp_path, fragment="**A _fragment_ sentence (#568).** More words follow.\n")
    f = fields(render(r, spec=None))
    assert f["Changed"] == "A fragment sentence (#568). (3 files)"


def test_the_pr_title_is_the_last_fallback_ac_157_2(tmp_path):  # AC-157.2
    f = fields(render(make_repo(tmp_path), spec=None))
    assert f["Changed"] == f"{TITLE} (2 files)"


def test_files_are_counted_against_the_base_branch_ac_157_2(tmp_path):  # AC-157.2
    f = fields(render(make_repo(tmp_path, files=("a.py", "b.py", "c.py", "d.py")), spec=None))
    assert f["Changed"].endswith("(4 files)")


def test_pr_open_counts_the_files_it_is_about_to_commit_ac_157_2(popen, capsys):  # AC-157.2
    open_cmd(popen, capsys)
    assert "- **Changed:** Thing title (2 criteria of spec 157, 3 files)" in sent(popen).splitlines()


def test_an_unknown_spec_is_a_failure_not_a_title_fallback_ac_157_2(tmp_path):  # AC-157.2
    r = make_repo(tmp_path)
    with pytest.raises(Exception):
        render(r, spec="999")


# ---------------- AC-157.3: Why ----------------

def test_why_is_the_so_that_clause_of_the_first_story_ac_157_3(tmp_path):  # AC-157.3
    block = render(make_repo(tmp_path))
    assert fields(block)["Why"] == "so that I know what to review first."
    assert "SECRET-PROBLEM-TEXT" not in block and "embellished" not in block


def test_why_lists_the_closing_references_with_issue_titles_ac_157_3(tmp_path):  # AC-157.3
    r = make_repo(tmp_path, spec_text=NO_STORIES)
    body = "## Related issues\n\nCloses #44\nFixes #45\n"
    assert fields(render(r, body=body))["Why"] == "Closes #44: Issue 44 title; Closes #45: Issue 45 title"


def test_at_most_three_references_then_and_n_more_ac_157_3(tmp_path):  # AC-157.3
    r = make_repo(tmp_path)
    body = "\n".join(f"Closes #{n}" for n in (44, 45, 46, 47, 48))
    why = fields(render(r, spec=None, body=body))["Why"]
    assert why == "Closes #44: Issue 44 title; Closes #45: Issue 45 title; Closes #46: Issue 46 title; … and 2 more"


def test_a_reference_whose_title_cannot_be_read_is_still_named_ac_157_3(tmp_path):  # AC-157.3
    assert fields(render(make_repo(tmp_path), spec=None, body="Closes #99\n"))["Why"] == "Closes #99"


def test_the_story_comes_before_the_references_ac_157_3(tmp_path):  # AC-157.3
    why = fields(render(make_repo(tmp_path), body="Closes #44\n"))["Why"]
    assert why.startswith("so that") and "Closes" not in why


def test_without_story_or_reference_why_is_not_recorded_ac_157_3(tmp_path):  # AC-157.3
    r = make_repo(tmp_path, spec_text=NO_STORIES)
    assert fields(render(r))["Why"] == "not recorded"
    assert fields(render(make_repo(tmp_path / "x"), spec=None))["Why"] == "not recorded"


# ---------------- AC-157.4: Review and Risks and follow-ups ----------------

def test_review_counts_findings_fixes_and_deviations_ac_157_4(tmp_path, monkeypatch):  # AC-157.4
    with_run(monkeypatch, *FINDINGS, FIX_ROUND)
    review = fields(render(make_repo(tmp_path)))["Review"]
    # AC-157.1 (not met) reads `met` after a fix round; AC-157.2 (partial) still reads `partial`
    assert review == "verification pass; 3 reviewer findings (1 not met, 1 partial, 1 deviation), 1 fixed in fix rounds, 2 accepted as deviations"


def test_nothing_counts_as_fixed_without_a_fix_round_ac_157_4(tmp_path, monkeypatch):  # AC-157.4
    with_run(monkeypatch, *FINDINGS)
    assert ", 0 fixed in fix rounds, " in fields(render(make_repo(tmp_path)))["Review"]


def test_a_run_without_findings_reads_none_ac_157_4(tmp_path, monkeypatch):  # AC-157.4
    with_run(monkeypatch, FIX_ROUND)
    assert fields(render(make_repo(tmp_path)))["Review"] == \
        "verification pass; 0 reviewer findings (none), 0 fixed in fix rounds, 2 accepted as deviations"


def test_without_a_run_the_findings_are_not_recorded_ac_157_4(tmp_path):  # AC-157.4
    assert fields(render(make_repo(tmp_path)))["Review"] == "verification pass; findings not recorded"


def test_a_run_of_another_spec_is_not_used_ac_157_4(tmp_path, monkeypatch):  # AC-157.4
    with_run(monkeypatch, *FINDINGS, spec="12")
    assert fields(render(make_repo(tmp_path)))["Review"] == "verification pass; findings not recorded"


@pytest.mark.parametrize("result, want", [("fail", "fail"), ("pass", "pass")])
def test_the_verification_state_is_read_from_the_result_line_ac_157_4(tmp_path, result, want):  # AC-157.4
    r = make_repo(tmp_path, verification=VERIFICATION.replace("**Result:** pass", f"**Result:** {result}"))
    assert fields(render(r))["Review"].startswith(f"verification {want}; ")


def test_without_a_verification_file_the_state_is_not_yet_ac_157_4(tmp_path):  # AC-157.4
    assert fields(render(make_repo(tmp_path, verification=None)))["Review"] == "verification not yet; findings not recorded"


def test_risks_lists_deviations_then_follow_ups_at_most_three_ac_157_4(tmp_path):  # AC-157.4
    risks = fields(render(make_repo(tmp_path)))["Risks and follow-ups"]
    assert risks == "A helper is in no task's files.; The pre-poll waits first.; Cache the lookups.; … and 2 more"


def test_a_follow_up_runs_over_its_continuation_lines_and_none_is_skipped_ac_157_4(tmp_path):  # AC-157.4
    only = "# V\n\n**Result:** pass\n\n## Follow-ups\n\n- Add a retry for the\n  mail call. Rest of it.\n- none\n"
    risks = fields(render(make_repo(tmp_path, verification=only)))["Risks and follow-ups"]
    assert risks == "Add a retry for the mail call."


def test_risks_are_none_recorded_without_items_ac_157_4(tmp_path):  # AC-157.4
    assert fields(render(make_repo(tmp_path, verification="# V\n\n**Result:** pass\n")))["Risks and follow-ups"] == "none recorded"
    assert fields(render(make_repo(tmp_path / "y", verification=None)))["Risks and follow-ups"] == "none recorded"


# ---------------- AC-157.5: redaction, bounds, failure ----------------

def test_values_pass_the_redaction_ac_157_5(tmp_path):  # AC-157.5
    token = "ghp_" + "A1b2C3d4" * 5
    risky = VERIFICATION.replace("Needs a design.", f"Token {token} by dev@example.com.")
    risky = risky.replace("**Cache the lookups.**", f"**Rotate {token} for dev@example.com.**")
    r = make_repo(tmp_path, spec_text=SPEC.replace("Thing title", f"Title {token}", 1), verification=risky)
    block = render(r)
    assert token not in block and "dev@example.com" not in block and "<github-token>" in block


def test_no_value_can_close_the_block_ac_157_5(tmp_path):  # AC-157.5
    r = make_repo(tmp_path, spec_text=SPEC.replace("Thing title", "Title --> and <!-- inside", 1))
    block = render(r)
    fields(block)                                  # still exactly one block shape
    assert block.count("<!--") == 2 and block.count("-->") == 2      # the START and END markers, nothing else
    assert not any("<!--" in ln or "-->" in ln for ln in block.splitlines()[1:-1])


def test_a_long_line_is_cut_to_300_characters_with_an_ellipsis_ac_157_5(tmp_path):  # AC-157.5
    r = make_repo(tmp_path, spec_text=SPEC.replace("Thing title", "word " * 100, 1))
    lines = render(r).splitlines()
    assert all(len(ln) <= 300 for ln in lines)
    assert lines[2].endswith("…") and len(lines[2]) == 300


def test_free_text_of_the_orchestrators_body_does_not_reach_the_block_ac_157_5(tmp_path):  # AC-157.5
    body = "## Summary\n\nORCHESTRATOR-FREE-TEXT written by an agent.\n\nCloses #44\n"
    for spec in ("157", None):
        block = render(make_repo(tmp_path / str(spec)), body=body, spec=spec)
        assert "ORCHESTRATOR-FREE-TEXT" not in block and "written by an agent" not in block


def test_no_prompt_or_diff_of_the_run_reaches_the_block_ac_157_5(tmp_path, monkeypatch):  # AC-157.5
    rid = make_run(spec="157", prompt="SECRET PROMPT TEXT", diff="+++ b/x.py\n-old\n+new", agents=[agent("svc:reviewer", *FINDINGS)])
    monkeypatch.setattr(runs, "current_run", lambda repo: rid)
    block = render(make_repo(tmp_path))
    assert "SECRET PROMPT TEXT" not in block and "+++ b/x.py" not in block


def test_add_returns_the_body_unchanged_and_a_note_on_failure_ac_157_5(tmp_path):  # AC-157.5
    import pr_summary
    r = make_repo(tmp_path)
    body, note = pr_summary.add(r, ORIGINAL, title=TITLE, spec="999", base="main")
    assert body == ORIGINAL and note.startswith("note: summary skipped: ") and "\n" not in note and len(note) <= 200
    body, note = pr_summary.add(r, ORIGINAL, title=TITLE, spec="157", base="main")
    assert note is None and body.startswith(START) and body.endswith(ORIGINAL)


def test_pr_open_with_a_failing_summary_opens_the_pr_with_one_extra_line_ac_157_5(popen, capsys, monkeypatch):  # AC-157.5
    code, plain = open_cmd(popen, capsys)
    (popen.repo / ".git" / "PR_BODY.md").write_text(ORIGINAL)
    popen.dirty, popen.ahead = True, 0

    def boom(*a, **kw):
        raise RuntimeError("boom")
    import pr_summary
    monkeypatch.setattr(pr_summary, "render", boom)
    code2, out = open_cmd(popen, capsys)
    assert code2 == code == 0
    assert sent(popen) == ORIGINAL
    notes = [ln for ln in out.splitlines() if ln.startswith("note: summary skipped: ")]
    assert len(notes) == 1 and "boom" in notes[0]
    assert [ln for ln in out.splitlines() if ln not in notes] == plain.splitlines()
