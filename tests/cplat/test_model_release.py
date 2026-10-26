"""Spec 113 acceptance tests: what the release says (AC-113.17).

A 4.x minor: `cplat --help` lists `model show [--json]`, no existing command changes, the changelog and the "Status" of the domain
model guide say what is in place, and no slash command is added for `cplat model show`."""
import re
from pathlib import Path

import cplat

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = (ROOT / "docs" / "CHANGELOG.md")
GUIDE = (ROOT / "docs" / "DOMAIN-MODEL.md")

# the commands of 4.7.0 (cplat.COMMANDS before this spec): none of them may disappear or be renamed
EXISTING = ["new-service", "new-app", "update-service", "doctor", "shape", "compose", "promote", "status", "secret", "addon", "feedback",
            "triage", "spec", "ship", "pr", "quiet", "validate", "app-ship", "smoke", "headless", "build", "runs", "retro", "deps", "alerts",
            "fleet", "budget", "adopt"]


def test_help_lists_model_show_ac_113_17(capsys):  # AC-113.17
    assert cplat.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "model show [--json]" in out
    line = next(ln for ln in out.splitlines() if "model show" in ln)
    assert "113" in line or "domain model" in line


def test_model_is_registered_and_nothing_else_changed_ac_113_17():  # AC-113.17
    assert cplat.COMMANDS["model"] == "modelcmd"
    missing = [c for c in EXISTING if c not in cplat.COMMANDS]
    assert missing == [], f"commands that disappeared: {missing}"


def unreleased() -> str:
    text = CHANGELOG.read_text()
    start = text.index("## [Unreleased]")
    # [Unreleased] plus the newest released section: the release moves the entry there
    heads = [m.start() for m in re.finditer(r"^## \[", text[start + 1:], re.M)]
    end = start + 1 + heads[1] if len(heads) > 1 else len(text)
    return text[start:end]


def test_the_changelog_announces_the_model_and_that_nothing_else_changed_ac_113_17():  # AC-113.17
    entry = next((p for p in unreleased().split("\n\n") if "(113" in p or "113)" in p or "113:" in p), "")
    assert entry, "no entry for spec 113 under [Unreleased]"
    assert "cplat model show" in entry and "schema: 1" in entry and "5.0" in entry
    assert re.search(r"(?i)\bno\b[^.]*\bchanged\b", entry), "the entry must say that no command, flag, output format or file schema changed"
    assert re.search(r"(?i)slash command", entry)
    assert "ADR-053" in entry or "DOMAIN-MODEL" in entry or "domain-model" in entry.lower()


def test_the_guides_status_names_the_core_the_command_and_the_json_ac_113_17():  # AC-113.17
    status = next(ln for ln in GUIDE.read_text().splitlines() if ln.startswith("**Status:**"))
    assert re.search(r"(?i)internal core[^.]*\bis in place\b|\bis in place\b[^.]*internal core", status), status
    assert "cplat model show" in status
    assert "schema: 1" in status and "5.0" in status and re.search(r"(?i)may change", status)
    assert "lands in 4.x" not in status


def test_no_slash_command_is_added_for_the_model_ac_113_17():  # AC-113.17
    commands = sorted((ROOT / "plugins").glob("*/commands/*.md"))
    assert commands
    assert not [c for c in commands if c.stem == "model"]
    assert not [c.name for c in commands if "cplat model" in c.read_text() or "cplat.py model" in c.read_text()]
    assert (ROOT / "scripts" / "cplat" / "modelcmd.py").is_file(), "cplat model show lives in scripts/cplat/modelcmd.py"
