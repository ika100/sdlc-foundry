"""Spec 157 acceptance tests (AC-157.6, AC-157.7): the component ship and the system ship put the summary block on top of the PRs
they open, and the commands and the changelog say so.

Seams: the spec 126 ship world (`ship.gh`, staged body, recorded `devbox run ci`), the spec 097 system ship world and the spec 144
joint world for the gitops and entry PRs; a fake `gh` on PATH for issue titles.
"""
import os
import re
import stat

import pytest

import appship
import core
import ship
import test_appship_097 as t97
from test_144_joint_pr import JointWorld
from test_ship import repo  # noqa: F401  (fixture)
from test_ship_pr_126 import BODY, PR_URL, TITLE, world  # noqa: F401  (fixture)
from waiting import with_prelude

START, END = "<!-- cplat:summary -->", "<!-- /cplat:summary -->"
HOW_START = "<!-- cplat:how-built -->"
ROOT = core.PLATFORM_ROOT


@pytest.fixture(autouse=True)
def fake_gh(tmp_path, monkeypatch):
    """`gh issue view N` prints `Issue N title`; no other gh call is reachable from the summary."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(with_prelude('#!/bin/sh\nif [ "$1" = issue ] && [ "$2" = view ]; then\n  echo "Issue ${3#\\#} title"\n  exit 0\nfi\nexit 1\n'))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


def assert_block(text, original, spec_title, spec_no, criteria):
    lines = text.splitlines()
    assert lines[0] == START and lines[1] == "**Summary**" and lines[6] == END and lines[7] == "", lines[:8]
    for label, line in zip(["Changed", "Why", "Review", "Risks and follow-ups"], lines[2:6]):
        assert line.startswith(f"- **{label}:** "), line
    assert re.fullmatch(rf"- \*\*Changed:\*\* {re.escape(spec_title)} \({criteria} criteria of spec {spec_no}, \d+ files\)", lines[2]), lines[2]
    assert text.split(END + "\n\n", 1)[1] == original
    assert HOW_START not in text                  # spec 133 non-goal: no "How this was built" block in these PRs


def sent_body(w):
    [create] = w.gh.has("pr", "create")
    return open(create[create.index("--body-file") + 1]).read()


# ---------------- AC-157.6: the component ship ----------------

def test_a_new_ship_pr_starts_with_the_block_ac_157_6(world):  # AC-157.6
    world.change("docs/guide.md")
    assert world.pr() == 0
    assert_block(sent_body(world), BODY, "Price alerts", "007", 2)
    [(_, env)] = [e for e in world.events if e[0] == "ci"]
    assert env["PR_BODY"].startswith(START)           # the local check sees what CI will see


def test_an_existing_ship_pr_gets_the_block_by_an_edit_ac_157_6(world):  # AC-157.6
    world.change("docs/guide.md")
    world.gh.open = [{"number": 7, "url": PR_URL, "title": TITLE, "labels": [], "isDraft": False}]
    assert world.pr() == 0
    [edit] = world.gh.has("pr", "edit", "--body-file")
    text = open(edit[edit.index("--body-file") + 1]).read()
    assert_block(text, BODY, "Price alerts", "007", 2)
    assert not world.gh.has("pr", "create")


def test_a_ship_pr_that_already_has_a_block_gets_it_replaced_ac_157_6(world):  # AC-157.6
    world.change("docs/guide.md")
    world.body.write_text(f"{START}\nstale\n{END}\n\n{BODY}")
    assert world.pr() == 0
    text = sent_body(world)
    assert text.count(START) == 1 and "stale" not in text


# ---------------- AC-157.6: the system ship ----------------

@pytest.fixture()
def sysworld(tmp_path, monkeypatch, capsys):
    return t97.World(tmp_path, monkeypatch, capsys)


def created(w):
    [create] = w.made("pr", "create")
    return create[create.index("--body") + 1]


def test_a_gitops_pr_starts_with_the_block_of_the_system_spec_ac_157_6(sysworld):  # AC-157.6
    appship.open_pr(sysworld.gitops, "feature/x", "feat(shop): gitops change", "## Summary\n\nDid it.\n", spec=t97.SPEC)
    assert_block(created(sysworld), "## Summary\n\nDid it.\n", "Shop", "012", 3)


def test_the_system_spec_is_the_spec_of_a_gitops_pr_without_its_own_ac_157_6(sysworld):  # AC-157.6
    # the gitops repo holds only the system spec: the block names it, not a fallback to the PR title
    appship.open_pr(sysworld.gitops, "feature/x", "feat(shop): gitops change", "body\n", spec=t97.SPEC)
    assert "gitops change" not in created(sysworld).splitlines()[2]


def test_an_open_gitops_pr_is_reused_not_edited_ac_157_6(sysworld):  # AC-157.6
    sysworld.add_pr(5)
    appship.open_pr(sysworld.gitops, "feature/x", "feat(shop): gitops change", "body\n", spec=t97.SPEC)
    assert sysworld.made("pr", "create") == [] and sysworld.made("pr", "edit") == []


def _boom(monkeypatch):
    import pr_summary

    def boom(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(pr_summary, "render", boom)


def test_a_failing_summary_leaves_the_ship_body_unchanged_with_a_note_ac_157_5(world, capsys, monkeypatch):  # AC-157.5
    world.change("docs/guide.md")
    _boom(monkeypatch)
    assert world.pr() == 0
    assert sent_body(world) == BODY
    [(_, env)] = [e for e in world.events if e[0] == "ci"]
    assert env["PR_BODY"] == BODY
    out = capsys.readouterr()
    assert [ln for ln in (out.out + out.err).splitlines() if ln.startswith("note: summary skipped:")]


def test_a_failing_summary_leaves_the_gitops_body_unchanged_with_a_note_ac_157_5(sysworld, capsys, monkeypatch):  # AC-157.5
    _boom(monkeypatch)
    appship.open_pr(sysworld.gitops, "feature/x", "feat(shop): gitops change", "## Summary\n\nDid it.\n", spec=t97.SPEC)
    assert created(sysworld) == "## Summary\n\nDid it.\n"
    out = capsys.readouterr()
    assert [ln for ln in (out.out + out.err).splitlines() if ln.startswith("note: summary skipped:")]


def _run_without_test_diffs(monkeypatch, spec):
    import runs
    from test_runs_built_133 import agent, make_run
    findings = [{"kind": "finding", "criterion": "AC-157.1", "task": None, "severity": "not met", "pass": "first", "cycle": 1, "tasks": ["t1"]}]
    rid = make_run(spec=spec, agents=[agent("svc:reviewer", *findings, {"kind": "fix-round", "cause": "test", "task": "t1"})])
    monkeypatch.setattr(runs, "current_run", lambda repo: rid)


def test_a_current_run_adds_no_how_built_block_to_a_ship_pr_ac_157_6(world, monkeypatch):  # AC-157.6
    _run_without_test_diffs(monkeypatch, "007")
    world.change("docs/guide.md")
    assert world.pr() == 0
    text = sent_body(world)
    assert text.startswith(START) and HOW_START not in text


def test_a_current_run_adds_no_how_built_block_to_a_gitops_pr_ac_157_6(sysworld, monkeypatch):  # AC-157.6
    _run_without_test_diffs(monkeypatch, "012")
    appship.open_pr(sysworld.gitops, "feature/x", "feat(shop): gitops change", "## Summary\n\nDid it.\n", spec=t97.SPEC)
    text = created(sysworld)
    assert text.startswith(START) and HOW_START not in text


def test_the_entry_pr_starts_with_the_block_ac_157_6(tmp_path, monkeypatch, capsys):  # AC-157.6
    j = JointWorld(tmp_path, monkeypatch, capsys)
    j.started()
    assert j.app("repo", "start", t97.GITOPS).rc == 0
    wt = j.common / "cplat-app-ship" / f"{t97.SPEC}-entry"
    (wt / "x.yaml").write_text("x: 1\n")
    t97.git(wt, "add", "-A")
    t97.git(wt, "commit", "-qm", "feat(compose): x")
    r = j.app("entry", "pr", t97.GITOPS, "--title", "feat(compose): x")
    assert r.rc == 0, r.out
    create = j.made("pr", "create")[-1]
    body = create[create.index("--body") + 1]
    assert body.startswith(START + "\n**Summary**\n") and "## Operations of the plan" in body
    assert body.count(START) == 1 and HOW_START not in body
    assert "Shop (" in body.splitlines()[2] and "criteria of spec 012" in body.splitlines()[2]


# ---------------- AC-157.7: the docs ----------------

COMMANDS = ["plugins/component/commands/build.md", "plugins/component/commands/ship.md", "plugins/system/references/ship-loop.md"]


@pytest.mark.parametrize("path", COMMANDS)
def test_the_command_says_cplat_adds_the_summary_to_the_pr_body_ac_157_7(path):  # AC-157.7
    # a structural mention (cplat, summary, PR body on one line), not a pinned sentence
    text = (ROOT / path).read_text()
    lines = [ln for ln in text.splitlines() if re.search(r"(?i)\bsummary\b", ln) and "cplat" in ln.lower() and re.search(r"(?i)\bbody\b", ln)]
    assert lines, f"{path} does not say that cplat adds a summary at the top of the PR body"


def _paragraphs(path):
    return re.split(r"\n\s*\n", (ROOT / path).read_text())


@pytest.mark.parametrize("path", COMMANDS)
def test_the_command_puts_the_summary_at_the_top_ac_157_7(path):  # AC-157.7
    # structural words (cplat, summary, body, a "top" word in one paragraph), not a pinned sentence
    assert [p for p in _paragraphs(path) if re.search(r"(?i)\bsummary\b", p) and "cplat" in p.lower() and re.search(r"(?i)\bbody\b", p)
            and re.search(r"(?i)\b(top|start|starts|beginning|first|head)\b", p)], f"{path} does not say the summary goes at the top"


@pytest.mark.parametrize("path", COMMANDS)
def test_the_command_says_the_orchestrator_writes_no_summary_ac_157_7(path):  # AC-157.7
    # structural words (orchestrator, summary, a negation in one paragraph), not a pinned sentence
    assert [p for p in _paragraphs(path) if re.search(r"(?i)\bsummary\b", p) and re.search(r"(?i)\borchestrator\b", p)
            and re.search(r"(?i)\b(no|not|never|none|don't|doesn't)\b", p)], f"{path} does not say the orchestrator writes no summary"


def test_the_changelog_has_an_entry_for_568_ac_157_7():  # AC-157.7
    # a fragment until the release, then a paragraph of docs/CHANGELOG.md
    frags = [f.read_text() for f in (ROOT / "docs" / "changelog.d").glob("*.md") if f.name != "README.md"]
    released = (ROOT / "docs" / "CHANGELOG.md").read_text().split("\n\n")
    assert [e for e in frags + released if "#568" in e], "no changelog entry names #568"
