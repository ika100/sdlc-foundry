"""scripts/bump_template_pins.py: bumping pins inside Jinja templates without parsing Jinja (issue #56)."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import bump_template_pins as b  # noqa: E402
import core  # noqa: E402


def test_copy_back_changes_only_the_literal_unique_line():
    old = "a\n<spotless.version>3.10.3</spotless.version>\nb\n"
    new = "a\n<spotless.version>3.10.4</spotless.version>\nb\n"
    source = "a\n<spotless.version>3.10.3</spotless.version>\nb {{ x }}\n"
    out, skipped = b.copy_back(old, new, source)
    assert out == "a\n<spotless.version>3.10.4</spotless.version>\nb {{ x }}\n" and skipped == []


def test_copy_back_never_guesses_when_a_line_has_jinja_or_is_ambiguous():
    old, new = "v: 1\nv: 1\nj: 2\n", "v: 9\nv: 9\nj: 3\n"
    out, skipped = b.copy_back(old, new, "v: 1\nv: 1\nj: {{ two }}\n")
    assert out == "v: 1\nv: 1\nj: {{ two }}\n"
    assert any("appears 2 times" in s for s in skipped) and any("2" in s for s in skipped)


def test_copy_back_reports_changes_that_are_not_one_to_one():
    out, skipped = b.copy_back("a\nb\n", "a\nb\nc\n", "a\nb\n")
    assert out == "a\nb\n" and skipped


@pytest.fixture()
def java_template(tmp_path):
    dest = tmp_path / "templates" / "service-java"
    shutil.copytree(ROOT / "templates" / "service-java", dest)
    return dest


def test_bump_updates_the_template_source_and_the_rerender_matches(java_template):
    def fake_updater(cmd, cwd, **_):
        pom = Path(cwd) / "pom.xml"
        pom.write_text(re.sub(r"<jacoco.version>[^<]+</jacoco.version>", "<jacoco.version>0.8.99</jacoco.version>", pom.read_text()))  # any current pin
        return subprocess.CompletedProcess(cmd, 0, "", "")

    changed, skipped = b.bump("service-java", java_template, core.find_copier(), run=fake_updater)
    source = (java_template / "pom.xml.jinja").read_text()
    assert "<jacoco.version>0.8.99</jacoco.version>" in source
    assert "{{ java_version }}" in source                      # Jinja lines are untouched
    assert changed == ["templates/service-java/pom.xml.jinja"]
    assert not [s for s in skipped if "re-render" in s]


def test_a_failing_updater_is_reported_not_fatal(java_template):
    def failing(cmd, cwd, **_):
        return subprocess.CompletedProcess(cmd, 1, "", "no network")

    changed, skipped = b.bump("service-java", java_template, core.find_copier(), run=failing)
    assert changed == [] and any("failed" in s and "no network" in s for s in skipped)
    assert (java_template / "pom.xml.jinja").read_text() == (ROOT / "templates/service-java/pom.xml.jinja").read_text()


def test_every_configured_manifest_exists_in_its_template():
    for name, spec in b.UPDATERS.items():
        for rel in spec["files"]:
            assert b.source_of(ROOT / "templates" / name, rel), f"{name}: {rel} has no template source"


def test_cli_rejects_unknown_templates(capsys):
    assert b.main(["nope"]) == 2
    assert "unknown template" in capsys.readouterr().err


def test_go_is_all_or_nothing_when_part_of_the_update_cannot_be_applied(tmp_path):
    """go.sum.jinja has Jinja, so go.mod must not be bumped alone (it would not build)."""
    dest = tmp_path / "templates" / "service-go"
    shutil.copytree(ROOT / "templates" / "service-go", dest)
    original = (dest / "go.mod.jinja").read_text()

    def fake_go(cmd, cwd, **_):
        mod = Path(cwd) / "go.mod"
        mod.write_text(mod.read_text().replace("v0.6.2", "v0.6.3"))
        (Path(cwd) / "go.sum").write_text((Path(cwd) / "go.sum").read_text() + "x v1 h1:abc=\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    changed, skipped = b.bump("service-go", dest, core.find_copier(), run=fake_go)
    assert changed == []
    assert (dest / "go.mod.jinja").read_text() == original
    assert any("rolled back" in s for s in skipped)


def test_protected_lines_are_never_bumped():
    old = '  "packageManager": "pnpm@11.22.0",\n  "x": "^1.0.0",\n'
    new = '  "packageManager": "pnpm@11.28.5",\n  "x": "^1.0.1",\n'
    out, skipped = b.copy_back(old, new, old)
    assert '"pnpm@11.22.0"' in out and '"^1.0.1"' in out and skipped == []
