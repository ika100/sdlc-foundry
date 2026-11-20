"""Spec 212: record which repo files a test run imports, opens, lists or hands to a subprocess.

Off unless a recording run turns it on: the cplat tests' plugin (`tests/cplat/depsmap.py`) in its own processes, and cplat
itself when it starts with SDLC_DEPS_TRACE set (a cplat process started from a recorded test, fixture or render). What is
recorded goes into a bucket: a test file, a fixture or a shared render. The map built from the buckets and the selection made
from it are in docs/specs/212-*/design.md.
"""
from __future__ import annotations

import ast
import atexit
import builtins
import contextlib
import hashlib
import json
import os
import secrets
import shlex
import sys
import threading
from pathlib import Path
from typing import Iterator

TRACE = "SDLC_DEPS_TRACE"   # the folder a traced cplat process writes its record into (one per bucket); not CPLAT_: the
ROOT = "SDLC_DEPS_ROOT"     # suite removes those before each test (A6). ROOT: the repo whose files count
KINDS = ("files", "dirs", "trees")   # opened or imported files; listed directories; subprocess arguments (everything below)
CHILD = "_"                          # the one bucket of a traced cplat process
_EVENTS = frozenset({"open", "os.listdir", "os.scandir", "glob.glob", "glob.glob/2", "subprocess.Popen"})
# where a module-level import of a test, support module or cplat module is looked up, in sys.path order of the suite
IMPORT_DIRS = ("tests/cplat", "scripts/cplat", "scripts")


class Recorder:
    def __init__(self, root: str | Path, trace_dir: str | Path | None = None, quiet: frozenset[tuple[str, str]] = frozenset()):
        self.root = os.path.realpath(root)
        self.prefix = self.root + os.sep
        self.trace_dir = Path(trace_dir) if trace_dir else None
        self.quiet = quiet   # (file, function): the imports these make are no test's dependency
        self.buckets: dict[str, dict[str, set[str]]] = {}
        self.current: str | None = None
        self.local = threading.local()

    # ---- paths ----

    def rel(self, path, cwd: str | None = None) -> str | None:
        """The repo-relative posix path of `path`, '.' for the repo itself, None outside it (or in .git)."""
        if isinstance(path, int) or path is None:
            return None
        try:
            path = os.fsdecode(os.fspath(path))
        except TypeError:
            return None
        if not path:
            return None
        if not os.path.isabs(path):
            try:
                path = os.path.join(cwd or os.getcwd(), path)
            except OSError:
                return None
        path = os.path.normpath(path)
        if path == self.root:
            return "."
        if not path.startswith(self.prefix):
            return None
        parts = path[len(self.prefix):].split(os.sep)
        if ".git" in parts:
            return None
        if "__pycache__" in parts:   # an import read the cached bytecode: the dependency is the source next to it
            i = parts.index("__pycache__")
            if i != len(parts) - 2 or not parts[-1].endswith(".pyc"):
                return None
            parts = [*parts[:i], parts[-1].split(".", 1)[0] + ".py"]
        return "/".join(parts)

    # ---- buckets ----

    def ensure(self, name: str) -> dict[str, set[str]]:
        b = self.buckets.get(name)
        if b is None:
            b = self.buckets[name] = {"files": set(), "dirs": set(), "trees": set(), "uses": set()}
        return b

    def add(self, kind: str, rel: str | None) -> None:
        if rel is not None and self.current is not None:
            self.ensure(self.current)[kind].add(rel)

    def dir_for(self, name: str) -> str:
        """The folder the cplat processes of bucket `name` write their records into."""
        assert self.trace_dir is not None
        d = self.trace_dir / ("b-" + hashlib.sha1(name.encode()).hexdigest()[:16])
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            (d / "name").write_text(name)
        return str(d)

    # ---- the audit hook and the import wrapper ----

    def _muted(self) -> bool:
        return self.current is None or getattr(self.local, "busy", False) or getattr(self.local, "quiet", False)

    def hook(self, event: str, args: tuple) -> None:
        if event not in _EVENTS or self._muted():
            return
        self.local.busy = True
        try:
            self._event(event, args)
        except Exception:  # noqa: BLE001  (an audit hook that raises would fail the audited call in the test)
            pass
        finally:
            self.local.busy = False

    def _event(self, event: str, args: tuple) -> None:
        if event == "open":
            self.add("files", self.rel(args[0]))
        elif event in ("os.listdir", "os.scandir"):
            self.add("dirs", self.rel("." if args[0] is None else args[0]))
        elif event.startswith("glob.glob"):
            root_dir = args[2] if len(args) > 2 else None
            fixed = []
            for part in str(args[0]).split(os.sep):
                if any(c in part for c in "*?["):
                    break
                fixed.append(part)
            base = os.sep.join(fixed) or "."
            self.add("trees", self.rel(base, os.fsdecode(root_dir) if root_dir else None))
        elif event == "subprocess.Popen":
            executable, argv, cwd = args[0], args[1], args[2]
            cwd = os.fsdecode(cwd) if cwd is not None else None
            if isinstance(argv, (str, bytes)):
                try:
                    argv = shlex.split(os.fsdecode(argv))
                except ValueError:
                    argv = [os.fsdecode(argv)]
            for a in [executable, *(argv or [])]:
                if a is None:
                    continue
                try:
                    a = os.fsdecode(os.fspath(a))
                except TypeError:
                    continue
                for cand in (a, a.split("=", 1)[1] if a.startswith("-") and "=" in a else None):
                    rel = self.rel(cand, cwd) if cand else None
                    if rel is None:
                        continue
                    full = os.path.join(self.root, rel)
                    if os.path.isdir(full):
                        self.add("trees", rel)
                    elif os.path.exists(full):
                        self.add("files", rel)

    def install(self) -> None:
        sys.addaudithook(self.hook)
        real = builtins.__import__
        rec = self

        def traced_import(name, globals=None, locals=None, fromlist=(), level=0):
            if rec.current is None or getattr(rec.local, "busy", False):
                return real(name, globals, locals, fromlist, level)
            code = sys._getframe(1).f_code
            if (code.co_filename, code.co_name) in rec.quiet:
                was = getattr(rec.local, "quiet", False)
                rec.local.quiet = True     # the suite's autouse fixtures import to patch; that is no test's dependency
                try:
                    return real(name, globals, locals, fromlist, level)
                finally:
                    rec.local.quiet = was
            module = real(name, globals, locals, fromlist, level)
            if not level and not getattr(rec.local, "quiet", False):
                # also a module already imported by an earlier test: the import statement ran in this one
                rec.add("files", rec.rel(getattr(sys.modules.get(name), "__file__", None)))
            return module

        builtins.__import__ = traced_import

    def loaded_modules(self) -> None:
        for m in list(sys.modules.values()):
            self.add("files", self.rel(getattr(m, "__file__", None)))

    def dump(self) -> dict[str, dict[str, list[str]]]:
        return {name: {k: sorted(v) for k, v in b.items()} for name, b in self.buckets.items()}


_rec: Recorder | None = None


def start(root: str | Path, trace_dir: str | Path, quiet: frozenset[tuple[str, str]] = frozenset()) -> Recorder:
    """Turn recording on in this (pytest) process; buckets are switched with `bucket`."""
    global _rec
    if _rec is None:
        _rec = Recorder(root, trace_dir, quiet)
        os.environ[ROOT] = _rec.root
        _rec.install()
    return _rec


def active() -> bool:
    return _rec is not None


@contextlib.contextmanager
def bucket(name: str) -> Iterator[None]:
    """Record into bucket `name` (and let the cplat processes started meanwhile write theirs to its folder)."""
    if _rec is None:
        yield
        return
    prev, prev_env = _rec.current, os.environ.get(TRACE)
    _rec.ensure(name)
    _rec.current = name
    os.environ[TRACE] = _rec.dir_for(name)
    try:
        yield
    finally:
        _rec.current = prev
        if prev_env is None:
            os.environ.pop(TRACE, None)
        else:
            os.environ[TRACE] = prev_env


def attach(name: str) -> None:
    """The current bucket depends on everything bucket `name` recorded (a shared render built by another test)."""
    if _rec is not None and _rec.current is not None and _rec.current != name:
        _rec.ensure(_rec.current)["uses"].add(name)


def child() -> None:
    """In a cplat process started from a recorded run: record what this process touches and write it at exit."""
    global _rec
    folder, root = os.environ.get(TRACE), os.environ.get(ROOT)
    if not folder or not root or _rec is not None:
        return
    _rec = Recorder(root)
    _rec.current = CHILD
    _rec.install()

    def write() -> None:
        try:
            _rec.current = CHILD
            _rec.loaded_modules()
            data = _rec.dump().get(CHILD, {})
            out = Path(folder) / f"{os.getpid()}-{secrets.token_hex(4)}.json"
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, out)
        except Exception:  # noqa: BLE001  (a lost record only widens the next selection's fallback, never fails cplat)
            pass

    atexit.register(write)


# ---- module-level imports, read statically ----

def autouse_fixtures(path: Path) -> frozenset[tuple[str, str]]:
    """(file, name) of each `@pytest.fixture(autouse=True)` function defined in `path`."""
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, ValueError):
        return frozenset()
    found = set()
    for n in tree.body:
        if isinstance(n, ast.FunctionDef):
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and any(k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value
                                                   for k in d.keywords):
                    found.add((str(path), n.name))
    return frozenset(found)


def _module_imports(path: Path) -> list[str]:
    """Names imported at module level (also under if/try/with), plus the names in a `pytest_plugins` list."""
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except (OSError, SyntaxError, ValueError):
        return []
    names: list[str] = []

    def walk(nodes) -> None:
        for n in nodes:
            if isinstance(n, ast.Import):
                names.extend(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                names.append(n.module)
            elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytest_plugins" for t in n.targets):
                if isinstance(n.value, (ast.List, ast.Tuple)):
                    names.extend(e.value for e in n.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
            elif isinstance(n, (ast.If, ast.Try, ast.With)):
                walk(ast.iter_child_nodes(n))
            elif sys.version_info >= (3, 11) and isinstance(n, getattr(ast, "TryStar", ())):
                walk(ast.iter_child_nodes(n))
    walk(tree.body)
    return names


class Imports:
    """The repo files a module imports at module level, directly or through the modules it imports."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._direct: dict[str, list[str]] = {}

    def resolve(self, name: str) -> str | None:
        first = name.split(".")[0]
        for d in IMPORT_DIRS:
            for cand in (f"{d}/{first}.py", f"{d}/{first}/__init__.py"):
                if (self.root / cand).is_file():
                    return cand
        return None

    def direct(self, rel: str) -> list[str]:
        if rel not in self._direct:
            found = (self.resolve(n) for n in _module_imports(self.root / rel))
            self._direct[rel] = sorted({r for r in found if r and r != rel})
        return self._direct[rel]

    def closure(self, rels) -> set[str]:
        seen = {r for r in rels if r.endswith(".py") and (self.root / r).is_file()}
        todo = list(seen)
        while todo:
            for r in self.direct(todo.pop()):
                if r not in seen:
                    seen.add(r)
                    todo.append(r)
        return seen
