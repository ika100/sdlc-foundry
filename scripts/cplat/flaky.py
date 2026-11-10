"""Spec 165 (AC-165.7): a test-fast run that fails only on a few tests runs them again alone once; tests that then pass are
flaky, not a regression of the change.

`rerun_args` turns the failed tests of one summary into the arguments of `devbox run test-fast -- <args>` for the test tool
that reported them (pytest, go test, Surefire, Vitest); None when the failure is anything but those tests.
"""
from __future__ import annotations

import re

MAX_TESTS = 5      # spec 165, A2: more failing tests is not a flake
TOOLS = ("pytest", "go-test", "surefire", "vitest")
_GO_TEST = re.compile(r"(?:^|\.)(Test\w*)(?:/|$)")


_DEFAULT = object()


def failed_tests(summary, limit=_DEFAULT) -> tuple[str, list[str]] | None:
    """(tool, test ids) when every entry of every check is a test failure of one tool, at most `limit` (default
    MAX_TESTS; None: no cap); else None."""
    cap = MAX_TESTS if limit is _DEFAULT else limit
    checks = [c for c in summary.checks if c.entries]
    if len(checks) != 1:
        return None
    c = checks[0]
    if len(c.formats) != 1 or c.formats[0] not in TOOLS or not all(e.test for e in c.entries):
        return None
    if c.reported is not None and c.reported != len(c.entries) or cap is not None and len(c.entries) > cap:
        return None
    return c.formats[0], [e.locator for e in c.entries]


def rerun_args(tool: str, tests: list[str]) -> list[str]:
    if tool == "pytest":
        return list(dict.fromkeys(tests))
    if tool == "go-test":   # `<package>.<Test>[/<subtest>]` or `<Test>`: the top-level test, anchored
        names = dict.fromkeys(m.group(1) if (m := _GO_TEST.search(t)) else t for t in tests)
        return ["-run", "^(" + "|".join(re.escape(n) for n in names) + ")$"]
    if tool == "surefire":  # `<package>.<Class>.<method>`
        sel = dict.fromkeys(f"{p[-2]}#{p[-1]}" if len(p := t.split("(")[0].rsplit(".", 2)) >= 2 else t for t in tests)
        return [f"-Dtest={','.join(sel)}", "-Dsurefire.failIfNoSpecifiedTests=false"]
    return list(dict.fromkeys(t.split(" > ")[0].strip() for t in tests))   # vitest: the test files
