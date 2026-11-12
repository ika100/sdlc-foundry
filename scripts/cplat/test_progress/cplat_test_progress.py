"""pytest plugin injected by `cplat quiet test-fast` (spec 185): records which tests started and ended in a progress file.

Only pytest hooks, no imports from `cplat`. The controller writes the file (an xdist worker has `workerinput` and skips it).
"""
from __future__ import annotations

import os

ENV = "PYTEST_PROGRESS_FILE"
_path: str | None = None


def _drop_from_environment() -> None:
    """A pytest started by a test must not write to the file nor load this plugin."""
    os.environ.pop(ENV, None)
    opts = os.environ.get("PYTEST_ADDOPTS", "")
    cleaned = opts.replace("-p cplat_test_progress", "").strip()
    if cleaned:
        os.environ["PYTEST_ADDOPTS"] = " ".join(cleaned.split())
    else:
        os.environ.pop("PYTEST_ADDOPTS", None)


def pytest_configure(config) -> None:
    global _path
    path = os.environ.get(ENV)
    if hasattr(config, "workerinput"):
        return
    if path:
        _path = path
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# cplat test progress\n")
        _drop_from_environment()


def _append(kind: str, nodeid: str) -> None:
    if _path:
        with open(_path, "a", encoding="utf-8") as fh:
            fh.write(f"{kind} {nodeid}\n")


def pytest_runtest_logstart(nodeid, location) -> None:
    _append("start", nodeid)


def pytest_runtest_logfinish(nodeid, location) -> None:
    _append("end", nodeid)
