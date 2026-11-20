"""Spec 158 acceptance tests: the docs (AC-158.5, AC-158.8).

Structure, not sentences (spec 168, ADR-103): the release command calls the one `cplat` verb and holds no `gh issue close`; the
four commands name the milestone comments; every command's closing note names them next to `platform` escalations; an ADR next
to ADR-033 records the decision; the changelog has the fragment for #568. A literal that code or a rule depends on carries
`# interface: <reason>`."""
import re

import core

ROOT = core.PLATFORM_ROOT
COMMANDS = sorted((ROOT / "plugins").glob("*/commands/*.md"))
RELEASE = ROOT / "plugins/component/commands/release.md"


def phase_7(text: str) -> str:
    m = re.search(r"^## Phase 7.*?(?=^## )", text, re.M | re.S)
    return m.group(0) if m else ""


def test_the_release_command_has_no_hand_written_issue_close_ac_158_5():  # AC-158.5
    text = RELEASE.read_text()
    assert "gh issue close" not in text
    step = phase_7(text)
    assert "cplat component release issues" in step   # interface: the one cplat call of the issue step
    assert "## Phase 7 complete" in step   # interface: the summary heading of the release


def test_the_four_commands_say_cplat_posts_the_milestone_comments_ac_158_8():  # AC-158.8
    for rel in ("component/commands/spec.md", "component/commands/ship.md", "component/commands/release.md", "system/commands/ship.md"):
        path = ROOT / "plugins" / rel
        assert path.is_file(), rel
        body = [ln for ln in path.read_text().splitlines() if not ln.startswith(">")]   # outside the closing note
        hits = [ln for ln in body if "milestone comment" in ln]
        assert any("cplat" in ln and "itself, without asking" in ln for ln in hits), rel


def test_every_closing_note_names_milestone_comments_ac_158_8():  # AC-158.8
    assert COMMANDS
    rows = {p: [ln for ln in p.read_text().splitlines() if ln.startswith(">") and "/issue:report" in ln] for p in COMMANDS}   # the closing note: a quoted escalation line, not a description
    noted = {p: r for p, r in rows.items() if r}
    assert len(noted) >= 40
    missing = [str(p.relative_to(ROOT)) for p, r in noted.items() if not any("`platform` escalation" in ln and "milestone comment" in ln for ln in r)]
    assert not missing, missing


def test_an_adr_next_to_adr_033_records_the_decision_ac_158_8():  # AC-158.8
    adrs = sorted((ROOT / "docs/adr").glob("[0-9]*.md"))
    hits = [p for p in adrs if int(p.name.split("-")[0]) > 33 and "milestone comment" in p.read_text()]
    assert hits, "no ADR about milestone comments"
    text = hits[0].read_text()
    assert "ADR-033" in text and "#428" in text and "milestone comment" in text
    index = (ROOT / "docs/adr/README.md").read_text()
    assert hits[0].name in index


def test_the_changelog_has_an_entry_for_568_ac_158_8():  # AC-158.8
    fragments = [p for p in sorted((ROOT / "docs/changelog.d").glob("*.md")) if "(#568)" in p.read_text()]
    assert fragments, "no changelog fragment names (#568)"
