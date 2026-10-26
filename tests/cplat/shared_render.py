"""Spec 112: render a repository once per test process and hand every test a private copy.

The cache lives under a directory inside the run's basetemp, so it lasts one test run and is never reused by the next."""
from __future__ import annotations

import contextlib
import io
import os
import shlex
import shutil
from pathlib import Path
from typing import Callable

TAIL_LINES = 20


@contextlib.contextmanager
def _git_quiet():
    """Build with git auto-maintenance off: a detached `git maintenance` would keep changing the source's .git after the build."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("GIT_CONFIG_")}
    count = int(os.environ.get("GIT_CONFIG_COUNT") or 0)
    extra = [("maintenance.auto", "false"), ("gc.auto", "0")]
    for i, (k, v) in enumerate(extra, start=count):
        os.environ[f"GIT_CONFIG_KEY_{i}"] = k
        os.environ[f"GIT_CONFIG_VALUE_{i}"] = v
    os.environ["GIT_CONFIG_COUNT"] = str(count + len(extra))
    try:
        yield
    finally:
        for k in [k for k in os.environ if k.startswith("GIT_CONFIG_")]:
            del os.environ[k]
        os.environ.update(saved)


class RenderFailed(Exception):
    """A shared render failed; every test that needs it errors with the same message."""


class SharedRenders:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.builds: dict[str, int] = {}
        self._sources: dict[str, Path] = {}
        self._failures: dict[str, str] = {}

    def _build(self, key: str, build: Callable[[Path], Path]) -> None:
        workdir = self.root / f"render-{len(self.builds)}"
        workdir.mkdir(parents=True)
        self.builds[key] = 1
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), _git_quiet():
                source = Path(build(workdir))
            if not source.is_dir():
                raise NotADirectoryError(f"build returned {str(source)!r}, which is not a directory")
        except (Exception, SystemExit) as err:
            message = f"shared render {key!r} failed: {type(err).__name__}: {err}"
            tail = "\n".join(out.getvalue().splitlines()[-TAIL_LINES:])
            self._failures[key] = message + ("\n" + tail if tail else "")
            return
        self._sources[key] = source

    def copy(self, key: str, build: Callable[[Path], Path], dest: Path) -> Path:
        if key not in self.builds:
            self._build(key, build)
        if key in self._failures:
            raise RenderFailed(self._failures[key])
        dest = Path(dest)
        if dest.exists():
            if not dest.is_dir() or any(dest.iterdir()):
                raise FileExistsError(f"{dest} exists and is not an empty directory")
            dest.rmdir()
        shutil.copytree(self._sources[key], dest, symlinks=True)
        return dest


def service_key(argv: list[str]) -> tuple[str, str, list[str]]:
    """(key, name, argv_without_dir) for a newsvc argv."""
    if "--dry-run" in argv:
        raise ValueError("a --dry-run render writes nothing and cannot be shared")
    if "--dir" not in argv:
        raise ValueError("argv needs --dir D")
    i = argv.index("--dir")
    if i + 1 >= len(argv):
        raise ValueError("--dir needs a value")
    rest = argv[:i] + argv[i + 2:]
    return shlex.join(rest), argv[0], rest
