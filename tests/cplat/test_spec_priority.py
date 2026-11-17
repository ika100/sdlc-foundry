"""Unit tests of `spec_priority`: reading the state from the Changelog and resolving a new spec's priority (spec 196)."""
import pytest

import core
import spec
import spec_priority

FALLBACK = "P1: normal bug or feature"


def make(*lines: str) -> spec.Spec:
    body = "# 1 — x\n\n## Changelog\n\n" + "\n".join(f"- 2026-11-17 {ln}" for ln in lines) + "\n"
    return spec.Spec(spec.Path("/tmp/001-x"), {"status": "draft", "priority": "P1"}, body)


@pytest.mark.parametrize("lines,want", [
    ((), {"state": "unset", "reason": "", "decide": False}),
    (("created",), {"state": "unset", "reason": "", "decide": False}),
    (("created", f"priority P1 proposed: {FALLBACK}"), {"state": "proposed", "reason": FALLBACK, "decide": False}),
    (("priority P0 given by you",), {"state": "given", "reason": "given by you", "decide": False}),
    (("priority P0 changed by you",), {"state": "changed", "reason": "changed by you", "decide": False}),
    (("priority P0 set on the issue #5",), {"state": "issue", "reason": "set on the issue #5", "decide": False}),
    (("priority P0 set on the issue #5 (p0, p2: decide)",),
     {"state": "issue", "reason": "set on the issue #5 (p0, p2: decide)", "decide": True}),
    ((f"priority P1 proposed: {FALLBACK}", "priority P2 changed by you"), {"state": "changed", "reason": "changed by you", "decide": False}),
    ((f"priority P1 proposed: {FALLBACK}", "approved"), {"state": "approved", "reason": FALLBACK, "decide": False}),
    ((f"priority P1 proposed: {FALLBACK}", "approved by cplat dispatch"), {"state": "proposed", "reason": FALLBACK, "decide": False}),
])
def test_state_reads_the_last_priority_line(lines, want):
    assert spec_priority.state(make(*lines)) == want


def fake_gh(monkeypatch, answers):
    class Res:
        def __init__(self, code, out):
            self.returncode, self.stdout = code, out

    monkeypatch.setattr(core, "run", lambda cmd, **kw: Res(*answers[cmd[3]]))


def test_resolve_prefers_the_given_level(tmp_path):
    assert spec_priority.resolve(tmp_path, "P0", [5], False) == ("P0", "priority P0 given by you")
    assert spec_priority.resolve(tmp_path, "P0", [], True) == ("P0", "priority P0 proposed: P0: named in the request")


def test_resolve_takes_the_most_urgent_label_and_marks_the_decision(tmp_path, monkeypatch):
    fake_gh(monkeypatch, {"5": (0, '{"labels": [{"name": "p2"}]}'), "6": (0, '{"labels": [{"name": "p0"}, {"name": "bug"}]}')})
    assert spec_priority.resolve(tmp_path, None, [5, 6], False) == ("P0", "priority P0 set on the issue #6 (p0, p2: decide)")
    assert spec_priority.resolve(tmp_path, None, [5, 6], True) == ("P0", "priority P0 proposed: P0: set on the issue #6")


def test_resolve_falls_back_with_a_note_when_labels_cannot_be_read(tmp_path, monkeypatch, capsys):
    fake_gh(monkeypatch, {"5": (1, "")})
    assert spec_priority.resolve(tmp_path, None, [5], False) == ("P1", f"priority P1 proposed: {FALLBACK}")
    assert "note: could not read the labels of #5; the priority is a proposal" in capsys.readouterr().err
