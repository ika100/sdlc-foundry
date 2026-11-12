"""Spec 131: the plugin side of unit mode (AC-131.1, AC-131.2), the preflight note of /system:ship (AC-131.11) and the written
measurement of AC-131.18 (a number over the first 7 days after the release goes in measurements.md, as spec 126 did).
"""
import json

import core
from structure import points_to

ROOT = core.PLATFORM_ROOT
SPEC_DIR = ROOT / "docs" / "specs" / "131-runs-that-finish-on-their-own"
MEASUREMENTS = SPEC_DIR / "measurements.md"
UNIT_MODE = ROOT / "plugins" / "component" / "references" / "unit-mode.md"


def read(path):
    assert path.is_file(), f"{path} is missing"
    return path.read_text()


# ---------------- AC-131.18: the measurement is written down ----------------

def test_ac_131_18_measurements_md_names_the_report_command_and_the_release_date():  # AC-131.18
    t = read(MEASUREMENTS)
    assert "cplat platform runs report --since 7" in t
    assert "Unattended ships" in t and "release" in t.lower()


def test_ac_131_18_measurements_md_has_one_row_per_target():  # AC-131.18
    t = read(MEASUREMENTS).lower()
    assert "70%" in t and "done" in t                                         # at least 70% of unattended ships end done
    assert "20%" in t and "escalated or failed" in t                          # under 20% of the spend
    assert "approval" in t and "git" in t                                     # no escalation on a git or gh approval
    assert "only verification" in t and "budget" in t                         # no budget stop with only verification left


# ---------------- AC-131.1: unit mode in the commands ----------------

def test_the_unit_mode_reference_names_every_unit():  # AC-131.1
    t = read(UNIT_MODE)
    for unit in ("plan", "red-tests", "task:", "verification", "land"):
        assert unit in t
    assert points_to("plugins/component/references/unit-mode.md","cplat component ship") and "another unit" in t.lower()


def test_ship_and_build_take_unit_and_read_the_reference():  # AC-131.1
    for name in ("ship", "build"):
        t = read(ROOT / "plugins" / "component" / "commands" / f"{name}.md")
        assert "--unit" in t and "references/unit-mode.md" in t, name


# ---------------- AC-131.2: the Stop hook reaches unit sessions ----------------

def test_the_ship_stop_hook_also_runs_when_cplat_unit_is_set():  # AC-131.2
    hooks = json.loads(read(ROOT / "plugins" / "shared" / "hooks" / "hooks.json"))["hooks"]["Stop"]
    commands = [h["command"] for group in hooks for h in group["hooks"] if "component ship gate" in h["command"]]
    assert commands and all("CPLAT_UNIT" in c and "cplat-ship.json" in c for c in commands)


# ---------------- AC-131.11: the system ship command ----------------

def test_system_ship_tells_what_to_do_with_a_failed_repo_preflight():  # AC-131.11
    t = read(ROOT / "plugins" / "system" / "commands" / "ship.md")
    assert "preflight failed" in t
