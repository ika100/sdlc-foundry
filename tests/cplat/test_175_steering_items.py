"""Spec 175 acceptance tests: steering items name a spec or an issue without guessing (AC-175.1 to AC-175.3).

`cplat dispatch skip|prioritize|resume <item>` is driven through the dispatcher world of spec 167 (fake gh, a real git clone).
Success prints one line and changes the state; a refused item exits 2, prints one `ERROR:` line on stderr, nothing on stdout, and
leaves `state.json` byte for byte as it was.
"""
import re
from pathlib import Path

from dispatch_world import world  # noqa: F401  (fixture)

DOCS = Path(__file__).resolve().parents[2] / "docs" / "dispatch.md"
ID = "154-price-alerts"


def raw_state(world):
    f = world.dispatch_dir() / "state.json"
    return f.read_bytes() if f.is_file() else None


def refused(world, *argv):
    """Run a steering command that must be refused: exit 2, one ERROR line, nothing on stdout, state unchanged."""
    before = raw_state(world)
    r = world.run(*argv)
    assert r.rc == 2, r
    assert r.out == "", r
    [line] = [ln for ln in r.err.splitlines() if ln.strip()]
    assert line.startswith("ERROR: "), r
    assert raw_state(world) == before
    return line


# ---------------- AC-175.1: a spec number names the spec ----------------

def test_skip_prioritize_resume_act_on_the_spec_when_no_issue_is_open_ac_175_1(world):  # AC-175.1
    world.policy(sources=["specs"])
    world.spec(154, "price-alerts")
    r = world.run("skip", "154", "--reason", "r")
    assert (r.rc, r.out.strip()) == (0, f"skipped: spec {ID} (reason: r)"), r
    st = world.state()["steering"]
    assert "spec-154" in st["skipped"]
    assert not [k for k in st["skipped"] if k.startswith("issue-")]
    r = world.run("prioritize", "154")
    assert (r.rc, r.out.strip()) == (0, f"prioritized: spec {ID}"), r
    assert "spec-154" in world.state()["steering"]["pinned"]
    r = world.run("resume", "154")
    assert (r.rc, r.out.strip()) == (0, f"resumed: spec {ID}"), r
    assert "spec-154" not in world.state()["steering"]["skipped"]


def test_a_bare_number_matches_a_spec_by_its_value_ac_175_1(world):  # AC-175.1
    world.policy(sources=["specs"])
    world.spec(54, "price-alerts")
    r = world.run("prioritize", "54")
    assert (r.rc, r.out.strip()) == (0, "prioritized: spec 054-price-alerts"), r


def test_a_zero_padded_number_always_names_the_spec_never_an_issue_ac_175_1(world):  # AC-175.1
    world.policy(sources=["specs"])
    world.spec(54, "price-alerts")
    world.issue(54)
    r = world.run("prioritize", "054")
    assert (r.rc, r.out.strip()) == (0, "prioritized: spec 054-price-alerts"), r
    assert "issue-54" not in str(world.state()["steering"])


def test_a_zero_padded_number_without_a_spec_is_refused_even_with_an_open_issue_ac_175_1(world):  # AC-175.1
    world.policy(sources=["specs"])
    world.issue(54)
    line = refused(world, "prioritize", "054")
    assert "054" in line and "no spec" in line and "spec-54" in line and "#54" in line


# ---------------- AC-175.2: explicit forms, the issue fallback, the guide ----------------

def test_hash_and_issue_forms_always_name_the_issue_ac_175_2(world):  # AC-175.2
    world.policy(sources=["specs"])
    world.spec(154, "price-alerts")
    world.issue(154)
    for item in ("#154", "issue-154"):
        r = world.run("prioritize", item)
        assert (r.rc, r.out.strip()) == (0, "prioritized: issue #154"), r
    r = world.run("skip", "#154", "--reason", "r")
    assert (r.rc, r.out.strip()) == (0, "skipped: issue #154 (reason: r)"), r
    r = world.run("resume", "issue-154")
    assert (r.rc, r.out.strip()) == (0, "resumed: issue #154"), r


def test_spec_forms_always_name_the_spec_ac_175_2(world):  # AC-175.2
    world.policy(sources=["specs"])
    world.spec(154, "price-alerts")
    world.issue(154)
    for item in ("spec-154", ID):
        r = world.run("prioritize", item)
        assert (r.rc, r.out.strip()) == (0, f"prioritized: spec {ID}"), r
    r = world.run("skip", "spec-154", "--reason", "r")
    assert (r.rc, r.out.strip()) == (0, f"skipped: spec {ID} (reason: r)"), r


def test_a_bare_number_with_no_spec_names_the_open_issue_ac_175_2(world):  # AC-175.2
    world.policy(sources=["specs"])
    world.spec(154, "price-alerts")
    world.issue(638)
    r = world.run("prioritize", "638")
    assert (r.rc, r.out.strip()) == (0, "prioritized: issue #638"), r
    r = world.run("skip", "638", "--reason", "r")
    assert (r.rc, r.out.strip()) == (0, "skipped: issue #638 (reason: r)"), r
    r = world.run("resume", "638")
    assert (r.rc, r.out.strip()) == (0, "resumed: issue #638"), r


def test_the_guide_item_line_states_the_forms_and_the_refusal_ac_175_2():  # AC-175.2
    text = DOCS.read_text()
    [para] = [p for p in re.split(r"\n\s*\n", text) if p.lstrip().startswith("An item is")]
    assert "spec-<N>" in para and "#<N>" in para and "issue-<N>" in para
    assert re.search(r"refus|both", para, re.I)


# ---------------- AC-175.3: ambiguity and unknown items are refused, the state stays ----------------

def test_a_bare_number_that_is_a_spec_and_an_open_issue_is_refused_by_all_three_commands_ac_175_3(world):  # AC-175.3
    world.policy(sources=["specs"])
    world.spec(154, "price-alerts")
    world.issue(154)
    world.run("slots", "2")                       # a state file exists, so "unchanged" is a real comparison
    want = f"ERROR: 154 is both spec {ID} and open issue #154: write spec-154 or #154"
    assert refused(world, "skip", "154", "--reason", "r") == want
    assert refused(world, "prioritize", "154") == want
    assert refused(world, "resume", "154") == want


def test_a_bare_number_that_matches_nothing_is_refused_ac_175_3(world):  # AC-175.3
    world.policy(sources=["specs"])
    world.spec(7, "price-alerts")
    world.run("slots", "2")
    line = refused(world, "skip", "999", "--reason", "r")
    assert "999" in line and "spec-999" in line and "#999" in line
    assert "neither a spec nor an open issue" in line


def test_a_spec_form_with_no_such_spec_is_refused_ac_175_3(world):  # AC-175.3
    world.policy(sources=["specs"])
    world.spec(7, "price-alerts")
    world.run("slots", "2")
    for item in ("spec-999", "999-nothing"):
        line = refused(world, "prioritize", item)
        assert item in line and "spec-999" in line and "#999" in line and "no spec" in line


def test_a_bare_number_that_is_a_spec_is_refused_when_the_open_issues_cannot_be_read_ac_175_3(world):  # AC-175.3
    world.policy(sources=["specs"])
    world.spec(154, "price-alerts")
    world.run("slots", "2")
    world.edit_gh(lambda d: d.update(closed=True))          # no snapshot, GitHub unreachable
    line = refused(world, "skip", "154", "--reason", "r")
    assert f"154 is spec {ID}" in line and "cannot be read" in line and "spec-154" in line and "#154" in line


def test_an_explicit_form_needs_no_github_read_ac_175_3(world):  # AC-175.3
    world.policy(sources=["specs"])
    world.spec(154, "price-alerts")
    world.edit_gh(lambda d: d.update(closed=True))
    r = world.run("prioritize", "spec-154")
    assert (r.rc, r.out.strip()) == (0, f"prioritized: spec {ID}"), r
    r = world.run("prioritize", "#154")
    assert (r.rc, r.out.strip()) == (0, "prioritized: issue #154"), r
