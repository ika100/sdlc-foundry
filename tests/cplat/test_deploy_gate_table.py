"""Spec 105 acceptance test AC-105.8: `docs/unattended-delivery.md` has one table "Deploy gate" (columns step, enforced by, check,
test) for the steps of the gate; every step is there, says `code` or `agent`, and a `code` row names tests that exist in
`tests/cplat`. A step whose named test does not exist fails here."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "unattended-delivery.md"
STEPS = ["pin confirmed", "argo healthy", "smoke", "retry", "escalation", "digest match", "promotion"]


def gate_rows() -> list[list[str]]:
    lines = DOC.read_text().splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("#") and "deploy gate" in ln.lower()), None)
    assert start is not None, 'docs/unattended-delivery.md has no heading "Deploy gate"'
    rows: list[list[str]] = []
    for ln in lines[start + 1:]:
        if ln.startswith("#"):
            break
        if ln.startswith("|"):
            rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
    assert len(rows) > 2, "the Deploy gate section has no table"
    header, _sep, *body = rows
    assert [h.lower() for h in header[:4]] == ["step", "enforced by", "check", "test"], header
    return body


def defined_tests() -> set[str]:
    names: set[str] = set()
    for f in (ROOT / "tests" / "cplat").glob("test_*.py"):
        names |= set(re.findall(r"^def (test_\w+)", f.read_text(), re.M))
    return names


def test_the_deploy_gate_table_lists_every_step_ac_105_8():  # AC-105.8
    """AC-105.8: pin confirmed, Argo healthy, smoke, retry, escalation, digest match and promotion each have a row."""
    steps = [r[0].lower() for r in gate_rows()]
    for want in STEPS:
        assert any(want in s for s in steps), f"no row for the step '{want}'"


def test_every_row_says_code_or_agent_ac_105_8():  # AC-105.8
    """AC-105.8: `enforced by` is `code` or `agent` for every row."""
    for r in gate_rows():
        assert r[1].strip("` ").lower() in {"code", "agent"}, r


def test_every_code_row_names_existing_tests_ac_105_8():  # AC-105.8
    """AC-105.8: a `code` row names a check and at least one test that exists; every test it names exists."""
    known = defined_tests()
    for r in gate_rows():
        named = re.findall(r"test_\w+", r[3])
        if r[1].strip("` ").lower() == "code":
            assert r[2].strip(" -"), f"row '{r[0]}' names no check"
            assert named, f"row '{r[0]}' is enforced by code but names no test"
        missing = [t for t in named if t not in known]
        assert not missing, f"row '{r[0]}' names tests that do not exist: {missing}"
