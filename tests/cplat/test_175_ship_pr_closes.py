"""Spec 175 acceptance tests: the ship PR body closes the issues the work finishes (AC-175.4, AC-175.5).

`cplat component ship pr --title T --body-file F` fills `{{CLOSES}}` the way `cplat pr open` does (`pr_open.closes_for` and
`pr_open.fill_closes`, git and gh through the `pr_open.run` seam) from the ship run's spec `tracks` and the `Closes #N` of the
branch's commits; a body that would still hold the placeholder is refused before `devbox run ci` and before the push.
The fixtures are those of the spec 126 tests (`ship.gh`, `ship.run` and the staged body) plus the `cplat pr open` fake.
"""
import re

import pytest

import pr as prmod
import pr_open
import ship
from test_pr_open import Fake
from test_ship import repo  # noqa: F401  (fixture)
from test_ship_pr_126 import TITLE, world  # noqa: F401  (fixture)

SPEC_FILE = "docs/specs/007-price-alerts/spec.md"
COMMITS = "feat: alerts\n\nCloses #44\n"


@pytest.fixture()
def fake(world, monkeypatch):
    """git and gh as `pr_open` sees them: issues #30 and #44 open, #12 closed; the branch's commits say `Closes #44`."""
    f = Fake(world.repo)
    f.log = COMMITS
    f.open_issues = {"30", "44"}
    monkeypatch.setattr(pr_open, "run", f)
    return f


def tracks(world, value):
    p = world.repo / SPEC_FILE
    p.write_text(p.read_text().replace("tracks: [42]", f"tracks: {value}"))
    world.change("docs/guide.md")


def sent_body(world):
    [create] = world.gh.has("pr", "create")
    return open(create[create.index("--body-file") + 1]).read()


def closes_lines(text):
    return [ln for ln in text.splitlines() if ln.startswith("Closes #")]


def nothing_done(w):
    assert not [e for e in w.events if e[0] in ("ci", "push")]
    assert not w.gh.has("pr", "list") and not w.gh.has("pr", "create") and not w.gh.has("pr", "edit")


# ---------------- AC-175.4: the placeholder is filled ----------------

def test_the_placeholder_becomes_the_tracked_and_commit_issues_ascending_ac_175_4(world, fake):  # AC-175.4
    tracks(world, "[30, 12]")
    world.body.write_text("## Related issues\n\n{{CLOSES}}\n")  # interface: PR body placeholder cplat fills
    assert world.pr() == 0
    body = sent_body(world)
    assert "{{CLOSES}}" not in body
    assert closes_lines(body) == ["Closes #30", "Closes #44"]          # on their own lines, ascending, without the closed #12
    [(_, env_)] = [e for e in world.events if e[0] == "ci"]
    assert env_["PR_BODY"] == body                                       # the local check sees what CI will see


def test_the_lines_are_those_pr_open_writes_for_the_branch_ac_175_4(world, fake, capsys):  # AC-175.4
    tracks(world, "[30, 12]")
    code = prmod.main(["open", "--title", TITLE, "--spec", "007", "--repo", str(world.repo), "--no-pr", "--json"])
    assert code == 0
    import json
    want = json.loads(capsys.readouterr().out)["closes"]
    assert want == [30, 44]
    world.body.write_text("{{CLOSES}}\n")
    assert world.pr() == 0
    assert closes_lines(sent_body(world)) == [f"Closes #{n}" for n in want]


def test_no_open_issue_gives_na_ac_175_4(world, fake):  # AC-175.4
    fake.open_issues = set()
    tracks(world, "[30, 12]")
    world.body.write_text("## Related issues\n\n{{CLOSES}}\n")  # interface: PR body placeholder cplat fills
    assert world.pr() == 0
    body = sent_body(world)
    assert "{{CLOSES}}" not in body and closes_lines(body) == [] and re.search(r"^N/A$", body, re.M)


def test_without_a_spec_the_lines_come_from_the_commits_only_ac_175_4(world, fake):  # AC-175.4
    tracks(world, "[30, 12]")
    st = ship.load_state(world.repo)
    st["spec"] = ""
    ship.save_state(world.repo, st)
    world.body.write_text("{{CLOSES}}\n")
    assert world.pr() == 0
    assert closes_lines(sent_body(world)) == ["Closes #44"]


# ---------------- AC-175.5: a body that keeps the placeholder is refused ----------------

def refused(world, capsys, reason):
    """`cplat component ship pr` exits 2 with the ERROR line (and its reason) and the fix line on stderr."""
    import cplat
    rc = cplat.main(["component", "ship", "--repo", str(world.repo), "pr", "--title", TITLE, "--body-file", str(world.body)])
    err = capsys.readouterr().err.splitlines()
    assert rc == 2
    assert any(ln.startswith("ERROR: PR body still contains {{CLOSES}}: " + reason) for ln in err), err
    assert any(ln.startswith("  fix: ") for ln in err), err


def test_an_unreadable_spec_refuses_the_body_before_ci_and_push_ac_175_5(world, fake, capsys):  # AC-175.5
    tracks(world, "[abc]")                                               # a non-integer track: the spec cannot be read
    world.body.write_text("{{CLOSES}}\n")
    refused(world, capsys, "the ship run's spec")
    nothing_done(world)
    assert "{{CLOSES}}" in (world.repo / ".git" / "PR_BODY.md").read_text()      # the body file is not written


def test_a_missing_spec_refuses_the_body_ac_175_5(world, fake, capsys):  # AC-175.5
    (world.repo / SPEC_FILE).unlink()
    world.change("docs/guide.md")
    world.body.write_text("{{CLOSES}}\n")
    refused(world, capsys, "the ship run's spec")
    nothing_done(world)


def test_filling_that_leaves_the_placeholder_refuses_the_body_ac_175_5(world, fake, monkeypatch, capsys):  # AC-175.5
    monkeypatch.setattr(pr_open, "fill_closes", lambda text, kept: text)
    world.change("docs/guide.md")
    world.body.write_text("{{CLOSES}}\n")
    refused(world, capsys, "filling left the placeholder")
    nothing_done(world)


def test_an_open_pr_is_neither_created_nor_edited_for_a_refused_body_ac_175_5(world, fake, capsys):  # AC-175.5
    tracks(world, "[abc]")
    world.gh.open = [{"number": 7, "url": "https://github.com/acme/shop-api/pull/7", "title": "old", "labels": []}]
    world.body.write_text("{{CLOSES}}\n")
    refused(world, capsys, "the ship run's spec")
    nothing_done(world)
