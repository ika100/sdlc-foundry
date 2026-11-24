"""pytest plugin injected by `cplat quiet test-fast --red` (spec 205): records why each test phase failed or passed.

Only pytest hooks, no imports from `cplat`. Every process (an xdist worker too) appends JSON lines to the file named by
CPLAT_RED_FILE; the process without `workerinput` writes the start record. The options stay in the environment because
xdist workers read them there; the classifier ignores records of files it was not given.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ENV = "CPLAT_RED_FILE"
_PATH: str | None = None   # #1048: read at start, since a suite's autouse fixture may unset CPLAT_* during the tests


def _path() -> str | None:
    return _PATH or os.environ.get(ENV) or None


def _append(record: dict) -> None:
    path = _path()
    if not path:
        return
    data = (json.dumps(record) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def pytest_configure(config) -> None:
    global _PATH
    _PATH = os.environ.get(ENV) or None
    if not hasattr(config, "workerinput"):
        _append({"kind": "start"})


def _module_file(name: str | None) -> str | None:
    if not name:
        return None
    try:
        mod = sys.modules.get(name)
        file = getattr(mod, "__file__", None) if mod is not None else None
        if not file:
            import importlib.util
            spec = importlib.util.find_spec(name)
            file = spec.origin if spec is not None and spec.origin and os.path.isabs(spec.origin) else None
        return os.path.realpath(file) if file else None
    except Exception:  # noqa: BLE001  (a module that cannot be found has no file)
        return None


def _describe(excinfo) -> dict:
    exc = excinfo.value
    if type(exc).__name__ == "CollectError" and exc.__cause__ is not None:   # pytest wraps an import error of a test module
        exc = exc.__cause__
        excinfo = pytest.ExceptionInfo.from_exception(exc)
    module = None
    if isinstance(exc, ImportError):
        module = getattr(exc, "name", None)
    elif isinstance(exc, AttributeError):
        obj = getattr(exc, "obj", None)
        if isinstance(obj, type(sys)):
            module = obj.__name__
    frames = []
    try:
        for entry in excinfo.traceback:
            frames.append(os.path.realpath(str(entry.path)))
    except Exception:  # noqa: BLE001
        pass
    return {
        "exc": [c.__name__ for c in type(exc).__mro__ if c is not object],
        "message": str(exc),
        "module": module,
        "module_file": _module_file(module),
        "top_file": _module_file(module.split(".", 1)[0]) if module else None,
        "frames": frames,
    }


def _file_of(node) -> str:
    path = getattr(node, "path", None)
    return os.path.realpath(str(path if path is not None else node.fspath))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    try:
        report = outcome.get_result()
        if report.outcome == "passed" and call.when != "call":
            return
        record = {
            "kind": "test",
            "nodeid": item.nodeid,
            "file": _file_of(item),
            "when": call.when,
            "outcome": report.outcome,
            "xfail": hasattr(report, "wasxfail"),
            "smoke": item.get_closest_marker("smoke") is not None,
            "exc": None, "message": "", "module": None, "module_file": None, "frames": [],
        }
        if call.excinfo is not None:
            record.update(_describe(call.excinfo))
        _append(record)
    except Exception:  # noqa: BLE001  (recording never changes the run)
        pass


def pytest_exception_interact(node, call, report) -> None:
    if not isinstance(node, pytest.Collector) or call.excinfo is None:
        return
    try:
        rec = {"kind": "collect", "file": _file_of(node)}
        rec.update(_describe(call.excinfo))
        _append(rec)
    except Exception:  # noqa: BLE001
        pass
