"""Spec 188 acceptance tests: the retro "Explore" section and its kill rule (AC-188.8).

Contract: design.md, section "Retro Explore section": `retro_explore.section(specs, changelog_text, until)` and `render(sec)`;
the report stores it as `report["explore"]`. Specs are real spec folders read with `spec.read`."""
import datetime as dt
import json

import core
import cplat
import spec
from retro_world import Lazy, build, tracker  # noqa: F401  (tracker: fixture of `world`)
from test_retro_cli import world  # noqa: F401  (fixture)
from test_runs import clock, mem, store  # noqa: F401  (fixtures of `world`)

retro_explore = Lazy("retro_explore")
KILL = "kill rule met: retire /component:explore and /system:explore as tombstones (your decision)"
CHANGELOG = """# Changelog

## [5.21.0] - 2026-11-20

- Added: `/component:explore` got a sibling.

## [5.20.0] - 2026-11-13

- Added: `/component:explore` and `/system:explore` (spec 188).

## [5.19.0] - 2026-11-06

- Added: something else.
"""
RELEASE = {"version": "5.20.0", "date": "2026-11-13"}
UNTIL = dt.date(2026, 12, 20)          # before the 6 weeks (2026-12-25) are over
LATE = dt.date(2027, 1, 15)


def make(tmp_path, n, *, created="2026-11-14", explored=False, revised=0, amendments=0):
    d = tmp_path / "docs" / "specs" / f"{n:03d}-s{n}"
    d.mkdir(parents=True)
    assumptions = "".join(f"- ~~**A{i}** old~~ (revised)\n" for i in range(revised)) + "- **A9** kept.\n"
    log = f"- {created} created\n" + "".join(f"- {created} amended: change {i}\n" for i in range(amendments)) + f"- {created} approved\n"
    (d / "spec.md").write_text(
        f"---\nspec_id: {n:03d}-s{n}\ntitle: S{n}\nstatus: done\npriority: P1\n{'explored: true' if explored else ''}\n---\n\n"
        f"# {n:03d}\n\n## Problem\n\nx\n\n## Acceptance criteria\n\n- **AC-{n:03d}.1** Given a, when b, then c.\n\n"
        f"## Assumptions\n\n{assumptions}\n## Non-goals\n\n- None\n\n## Open questions\n\nNone.\n\n## Changelog\n\n{log}")
    return spec.read(d)


def spec_world(tmp_path, explored, other):
    """explored / other: lists of (revised, amendments); two more specs fall outside the window and are ignored."""
    specs, n = [], 1
    for flag, group in ((True, explored), (False, other)):
        for revised, amendments in group:
            specs.append(make(tmp_path, n, explored=flag, revised=revised, amendments=amendments))
            n += 1
    specs.append(make(tmp_path, n, created="2026-11-12", explored=True, revised=9, amendments=9))        # before the release
    specs.append(make(tmp_path, n + 1, created="2027-02-01", explored=False, revised=9, amendments=9))   # after `until`
    return specs


def test_the_section_compares_explored_and_other_specs_since_the_release_ac_188_8(tmp_path):  # AC-188.8
    specs = spec_world(tmp_path, [(0, 0), (0, 1), (1, 1)], [(1, 1), (2, 2)])
    sec = retro_explore.section(specs, CHANGELOG, UNTIL)
    assert sec["release"] == RELEASE
    assert sec["explored"] == {"count": 3, "revised_assumptions_mean": 0.33, "amendments_mean": 0.67}
    assert sec["other"] == {"count": 2, "revised_assumptions_mean": 1.5, "amendments_mean": 1.5}
    assert sec["kill_rule"] == {"due": "2026-12-25", "met": False}


def test_an_empty_group_has_null_means_and_other_amendment_words_count_ac_188_8(tmp_path):  # AC-188.8
    sec = retro_explore.section(spec_world(tmp_path, [], [(0, 2)]), CHANGELOG, UNTIL)
    assert sec["explored"] == {"count": 0, "revised_assumptions_mean": None, "amendments_mean": None}
    assert sec["other"]["amendments_mean"] == 2.0         # `created` and `approved` are no amendments, `amended` is


def test_without_a_release_the_section_says_so_ac_188_8(tmp_path):  # AC-188.8
    sec = retro_explore.section(spec_world(tmp_path, [(0, 0)], [(1, 1)]), "## [5.19.0] - 2026-11-06\n\n- Added: other.\n", UNTIL)
    assert sec["release"] is None and "explored" not in sec and "kill_rule" not in sec
    assert retro_explore.render(sec).strip().splitlines() == ["## Explore", "explore not released yet"]


def test_the_kill_rule_is_met_after_six_weeks_with_fewer_than_5_explored_specs_ac_188_8(tmp_path):  # AC-188.8
    sec = retro_explore.section(spec_world(tmp_path, [(0, 0)] * 4, [(1, 1)] * 3), CHANGELOG, LATE)
    assert sec["kill_rule"] == {"due": "2026-12-25", "met": True}
    assert retro_explore.render(sec).rstrip().splitlines()[-1] == KILL


def test_the_kill_rule_is_met_when_explored_specs_revise_no_fewer_assumptions_ac_188_8(tmp_path):  # AC-188.8
    sec = retro_explore.section(spec_world(tmp_path, [(1, 0)] * 5, [(1, 0)] * 3), CHANGELOG, LATE)
    assert sec["kill_rule"]["met"] is True
    sec = retro_explore.section(spec_world(tmp_path / "b", [(0, 0)] * 5, [(1, 0)] * 3), CHANGELOG, LATE)
    assert sec["kill_rule"]["met"] is False


def test_the_kill_rule_waits_for_the_due_date_ac_188_8(tmp_path):  # AC-188.8
    sec = retro_explore.section(spec_world(tmp_path, [(0, 0)], [(1, 1)]), CHANGELOG, UNTIL)
    assert sec["kill_rule"]["met"] is False
    lines = retro_explore.render(sec).rstrip().splitlines()
    assert lines[-1] == "kill rule: checked from 2026-12-25" and KILL not in lines


def test_the_section_renders_a_table_and_the_kill_rule_state_ac_188_8(tmp_path):  # AC-188.8
    sec = retro_explore.section(spec_world(tmp_path, [(0, 0), (0, 1), (1, 1)], [(1, 1), (2, 2)]), CHANGELOG, LATE)
    lines = retro_explore.render(sec).rstrip().splitlines()
    assert lines[:2] == ["## Explore", "explored vs other specs created since 5.20.0 (2026-11-13)"]
    assert "| specs | count | mean revised assumptions | mean amendments |" in lines
    assert "| explored | 3 | 0.33 | 0.67 |" in lines and "| other | 2 | 1.50 | 1.50 |" in lines
    assert lines[-1] == KILL
    not_met = retro_explore.section(spec_world(tmp_path / "b", [(0, 0)] * 5, [(1, 1)] * 3), CHANGELOG, LATE)
    assert retro_explore.render(not_met).rstrip().splitlines()[-1] == "kill rule: not met"


def test_the_report_stores_and_prints_the_section_after_rules_to_retire_ac_188_8(tmp_path):  # AC-188.8
    import retro_report
    sec = retro_explore.section(spec_world(tmp_path, [(0, 0)], [(1, 1)]), CHANGELOG, UNTIL)
    rules = {"weeks": ["2026-W40", "2026-W41", "2026-W42", "2026-W43"], "runs": 3, "entries": []}
    report = build(rules_to_retire=rules, explore=sec)
    assert report["explore"] == sec
    text = retro_report.render_private(report, "## Proposals\n1. A proposal")
    assert "## Explore" in text and text.index("## Rules to retire") < text.index("## Explore")
    assert "## Explore" not in retro_report.render_private(build(rules_to_retire=rules), "## Proposals\n1. A proposal")


def test_the_retro_builds_the_section_from_the_repos_specs_and_changelog_ac_188_8(world, tmp_path, monkeypatch, capsys):  # AC-188.8
    root = tmp_path / "platform"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "CHANGELOG.md").write_text(CHANGELOG)
    make(root, 1, explored=True)
    monkeypatch.setattr(core, "PLATFORM_ROOT", root)
    assert cplat.main(["platform", "retro", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["explore"]["release"] == RELEASE
    assert cplat.main(["platform", "retro"]) == 0
    assert "## Explore" in capsys.readouterr().out
