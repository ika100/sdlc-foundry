"""Spec 108: helpers for the failure-summary acceptance tests (not a test module).

`scripts/cplat/failsum/` does not exist yet, so every helper imports it inside the function: the tests collect and each fails
until the package is there. The sample logs in fixtures/failsum/ have the real output shape of each tool; they are minimal.
"""
from __future__ import annotations

import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "failsum"
LOG = Path("/Users/eike/.cache/sdlc-foundry/logs/todo-api/20261028-101500-ci.log")
TITLE = "FAILED (exit 1): devbox run {script} (log: {log})"


def sample(name: str) -> str:
    return (FIXTURES / name).read_text()


def marker(script: str, path: str = "/work/todo-api") -> str:
    """The line devbox prints before every script it runs (design: `Info: Running script "<name>" on <path>`)."""
    return f'Info: Running script "{script}" on {path}\n'


def summarize(text: str, script: str = "test", *, root: str | None = None, log: Path = LOG, rc: int = 1):
    import failsum
    return failsum.summarize(text, title=TITLE.format(script=script, log=log), check=script, command=f"devbox run {script}",
                             exit_code=rc, log=log, root=Path(root) if root else None)


def render(text: str, script: str = "test", **kw) -> str:
    return summarize(text, script, **kw).render()


def has(rendered: str, pattern: str) -> bool:
    return re.search(pattern, rendered, re.MULTILINE) is not None


def headers(rendered: str) -> list[str]:
    return [ln for ln in rendered.splitlines() if ln.startswith("== check: ")]


def formats_of(header: str) -> list[str]:
    m = re.search(r"\| format: ([^|]+?) \|", header)
    assert m, f"no format field in {header!r}"
    return [f.strip() for f in m.group(1).split(",")]


def excerpt_runs(rendered: str) -> list[int]:
    """The length of every run of consecutive excerpt lines (`    > ...`)."""
    runs, n = [], 0
    for ln in rendered.splitlines():
        if ln.startswith("    > "):
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    return runs
