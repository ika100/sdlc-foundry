"""Spec 223 acceptance tests: `cplat platform change-quality` (AC-223.4 to AC-223.6).

World: a tmp git repo shaped like the platform repo with released sections 5.29.0, 5.30.0, 5.30.1 and 5.31.0 in docs/CHANGELOG.md, a
git history whose squash-merge subjects end in `(#N)` and whose tags v5.30.0, v5.30.1, v5.31.0 contain those commits, a
docs/PERFORMANCE.md with journey rows, and a fake `gh` (cq223_world) that holds the fleet's `.platform-version` history."""
import json
import re

import pytest

import cplat
from changelog_support import changelog_entry
from cq223_world import fake_gh, git  # noqa: F401  (fake_gh is a fixture)

CHANGELOG = """# CHANGELOG

## [Unreleased]

## [5.31.0] - 2026-11-26

### Added

**New thing.** Text (#850).

### Fixed

**Fix m.** A fix of the thing (#860).
Caused by: #850

**Fix n.** A fix that names no cause (#861).

**Fix upstream.** A tool of the cloud broke (#862).
Caused by: none

**Fix o.** Nobody found the cause (#863).
Caused by: unknown

## [5.30.1] - 2026-11-25

### Fixed

**Fix a.** The first fix (#815).
Caused by: #700

**Fix b.** The second fix (#816).
Caused by: #701

## [5.30.0] - 2026-11-24

### Added

**One.** A feature (#700).

**Two.** Another feature (#701).

## [5.29.0] - 2026-11-10

### Fixed

**Old fix.** Before the window (#600).
"""

PERFORMANCE = """# Performance

| # | date | base | name | result | other |
|---|---|---|---|---|---|
| 13 | 2026-11-13 | main | `t13-*` | finished in 90 minutes, fixed by [#816](https://github.com/ika100/sdlc-foundry/pull/816) | none |
| 14 | 2026-11-14 | main | `t14-*` | unattended; **stopped after sentence 2 (20 minutes)**: the CI failed ([#815](https://github.com/ika100/sdlc-foundry/issues/815)) | none |
| 15 | 2026-11-15 | main | `t15-*` | unattended; **stopped in part 2**: something else ([#999](https://github.com/ika100/sdlc-foundry/issues/999)) | none |
"""

FLEET = {"o/a": {"answers": True, "history": ["5.30.1", "5.30.0", "5.29.0"]},   # held 5.30.0: affected
         "o/b": {"answers": True, "history": ["5.30.1", "5.29.0"]},             # never held 5.30.0
         "o/c": {"answers": False, "history": ["5.30.0"]},                      # not a platform repo
         "o/d": {"answers": True, "history": ["5.31.0", "5.29.5"]}}


def build(root, changelog=CHANGELOG):
    (root / ".claude-plugin").mkdir(parents=True)
    (root / "docs/changelog.d").mkdir(parents=True)
    (root / ".claude-plugin/marketplace.json").write_text(json.dumps({"plugins": []}))
    (root / "docs/CHANGELOG.md").write_text(changelog)
    (root / "docs/PERFORMANCE.md").write_text(PERFORMANCE)
    (root / "docs/changelog.d/README.md").write_text("fragments\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "chore: init")
    for tag, subjects in (("v5.30.0", ["feat: one (#700)", "feat: two (#701)"]), ("v5.30.1", ["fix: a (#815)", "fix: b (#816)"]),
                          ("v5.31.0", ["feat: new thing (#850)"])):
        for subject in subjects:
            git(root, "commit", "-q", "--allow-empty", "-m", subject)
        git(root, "tag", tag)
    return root


@pytest.fixture()
def world(tmp_path, fake_gh):
    fake_gh.set(fleet=FLEET, login="o")
    return build(tmp_path / "platform")


def run(root, capsys, *args):
    rc = cplat.main(["platform", "change-quality", "--repo", str(root), *args])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def report(root, capsys, *extra):
    rc, out, err = run(root, capsys, "--since", "v5.30.0", *extra)
    assert rc == 0, out + err
    return out


# ---------------- AC-223.4: rows, caught before release, unattributed, rate ----------------

def test_one_row_per_release_with_the_fixes_it_caused_ac_223_4(world, capsys):  # AC-223.4
    lines = report(world, capsys).splitlines()
    assert lines[0].startswith("Change quality 5.30.0 to 5.31.0 (3 releases, since v5.30.0)")
    row = next(ln for ln in lines if ln.strip().startswith("5.30.0:"))
    assert row.strip().startswith("5.30.0: 2, carried by 5.30.1")
    assert "  5.30.1: 0" in lines and "  5.31.0: 0" in lines
    assert not any(ln.strip().startswith("5.29.0") for ln in lines)          # outside the window


def test_same_release_fix_is_caught_before_release_and_the_rest_is_counted_apart_ac_223_4(world, capsys):  # AC-223.4
    lines = report(world, capsys).splitlines()
    assert "caught before release: 1" in lines
    assert "unattributed: 2" in lines             # no cause line and `unknown`; the entry of 5.29.0 is outside the window
    assert "none (not from a platform change): 1" in lines
    assert any(ln.strip().startswith("5.31.0:") and "Fix upstream" in ln for ln in lines)   # a `none` entry follows its count


def test_the_change_failure_rate_over_all_and_over_minor_releases_ac_223_4(world, capsys):  # AC-223.4
    lines = report(world, capsys).splitlines()
    assert "change-failure rate: 1 of 3 releases (33%)" in lines
    assert "change-failure rate, minor and major releases: 1 of 2 releases (50%)" in lines


def test_a_version_without_a_heading_is_an_error_ac_223_4(world, capsys):  # AC-223.4
    rc, out, err = run(world, capsys, "--since", "v9.9.9")
    assert rc == 1 and "9.9.9" in err and out == ""


def test_an_unreleased_fixed_fragment_is_a_carrier_too_ac_223_4(world, capsys):  # AC-223.4
    (world / "docs/changelog.d/870-x.fixed.md").write_text("**Fix x (#870).** Text.\nCaused by: #850\n")
    data = json.loads(report(world, capsys, "--json"))
    assert len(data["releases"][2]["caused"]) == 1
    caused = data["releases"][2]["caused"][0]
    assert caused["carrier"] == "Unreleased" and caused["cause"] == "#850"
    assert data["change_failure_rate"]["failed"] == 2


def test_this_change_has_its_changelog_entry_ac_223_4():  # AC-223.4
    assert changelog_entry("cplat platform change-quality", fragment="223-*.added.md")


# ---------------- AC-223.5: blast radius ----------------

def test_the_row_shows_carriers_stopped_journeys_and_affected_repos_ac_223_5(world, capsys):  # AC-223.5
    out = report(world, capsys)
    row = next(ln for ln in out.splitlines() if ln.strip().startswith("5.30.0:"))
    assert "carried by 5.30.1" in row and "stopped journeys: 14" in row and "repos: 1 (o/a)" in row


def test_the_json_blast_radius_ac_223_5(world, capsys):  # AC-223.5
    data = json.loads(report(world, capsys, "--json"))
    row = next(r for r in data["releases"] if r["version"] == "5.30.0")
    assert row["carried_by"] == ["5.30.1"] and row["stopped_journeys"] == [14] and row["affected_repos"] == ["o/a"]


def test_an_unreleased_fragment_id_names_a_stopped_journey_without_a_link_ac_223_5(world, capsys):  # AC-223.5
    (world / "docs/changelog.d/812-x.fixed.md").write_text("**Fix x.** A fix with no number in its text.\nCaused by: #701\n")
    with (world / "docs/PERFORMANCE.md").open("a") as f:
        f.write("| 16 | 2026-11-16 | main | `t16-*` | unattended; **stopped in part 1**: see issue #812 | none |\n")
    data = json.loads(report(world, capsys, "--json"))
    row = next(r for r in data["releases"] if r["version"] == "5.30.0")
    assert len(row["caused"]) == 3 and {"5.30.1", "Unreleased"} == {c["carrier"] for c in row["caused"]}
    assert row["stopped_journeys"] == [14, 16] and row["carried_by"] == ["5.30.1", "Unreleased"]


def test_an_unreadable_fleet_is_unknown_never_zero_ac_223_5(world, fake_gh, capsys):  # AC-223.5
    fake_gh.set(login_fails=True)
    out = report(world, capsys)
    row = next(ln for ln in out.splitlines() if ln.strip().startswith("5.30.0:"))
    assert "repos: unknown" in row and "repos: 0" not in row
    data = json.loads(report(world, capsys, "--json"))
    row = next(r for r in data["releases"] if r["version"] == "5.30.0")
    assert row["affected_repos"] == "unknown" and row["affected_reason"]


def test_the_fleet_is_read_only_when_a_release_caused_a_fix_ac_223_5(tmp_path, fake_gh, capsys):  # AC-223.5
    quiet = CHANGELOG.replace("Caused by: #700", "Caused by: none").replace("Caused by: #701", "Caused by: none")
    quiet = quiet.replace("Caused by: #850", "Caused by: none")
    fake_gh.set(fleet=FLEET, login="o")
    root = build(tmp_path / "platform", quiet)
    assert "change-failure rate: 0 of 3 releases (0%)" in report(root, capsys).splitlines()
    assert not any(c[:2] == ["api", "user"] or c[:2] == ["repo", "list"] for c in fake_gh.calls())


# ---------------- AC-223.6: JSON and the platform-repo check ----------------

def test_json_is_one_document_with_the_contract_keys_ac_223_6(world, capsys):  # AC-223.6
    rc, out, err = run(world, capsys, "--since", "v5.30.0", "--json")
    assert rc == 0
    data = json.loads(out)                                                   # nothing else on stdout
    assert set(data) == {"window", "releases", "caught_before_release", "unattributed", "none", "change_failure_rate",
                         "change_failure_rate_minor"}
    assert data["window"]["since"] == "v5.30.0" and data["window"]["releases"] == 3
    assert data["window"]["from"] == "5.30.0" and data["window"]["until"] == "5.31.0"
    assert [r["version"] for r in data["releases"]] == ["5.30.0", "5.30.1", "5.31.0"]
    for r in data["releases"]:
        assert {"version", "caused", "carried_by", "stopped_journeys", "affected_repos"} <= set(r)
    caused = data["releases"][0]["caused"]
    assert sorted(c["cause"] for c in caused) == ["#700", "#701"] and {c["carrier"] for c in caused} == {"5.30.1"}
    assert [c["carrier"] for c in data["caught_before_release"]] == ["5.31.0"] and data["caught_before_release"][0]["cause"] == "#850"
    assert len(data["unattributed"]) == 2 and {u["carrier"] for u in data["unattributed"]} == {"5.31.0"}
    assert sorted(str(u["cause"]) for u in data["unattributed"]) == ["None", "unknown"]
    assert len(data["none"]) == 1 and "Fix upstream" in data["none"][0]["entry"]
    assert data["change_failure_rate"] == {"failed": 1, "releases": 3, "pct": 33}
    assert data["change_failure_rate_minor"] == {"failed": 1, "releases": 2, "pct": 50}


def test_outside_the_platform_repo_it_names_the_platform_repo_ac_223_6(tmp_path, capsys):  # AC-223.6
    rc, out, err = run(tmp_path, capsys, "--json")
    assert rc == 1 and out == "" and "ika100/sdlc-foundry" in err
