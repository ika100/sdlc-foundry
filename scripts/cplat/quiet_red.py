"""Spec 205 (AC-205.5): `cplat quiet test-fast --red -- <test files>` runs the tests once and classes each one:
`missing behaviour` (the code under test does not do it yet), `test error` (the test itself is broken) or `passes`.
With `--spec <spec>` (AC-205.8) an amended spec's run judges only the tests of new or changed criteria (`red_scope`).

The injected pytest plugin `cplat_red_check` records the exceptions; `classify` applies the rules (design.md, section 2).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import core

RECORD_FILE = "cplat-red-check.json"      # in the git dir; the freeze gate (spec 205) reads it
MISSING, ERROR, PASSES, SKIPPED = "missing behaviour", "test error", "passes", "skipped (not judged)"
_IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "AttributeError"}
_MAX_LINE = 200


def runs_pytest(cwd: Path) -> bool:
    try:
        script = json.loads((cwd / "devbox.json").read_text())["shell"]["scripts"]["test-fast"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    text = " ".join(script) if isinstance(script, list) else str(script)
    return "pytest" in text


def _load(path: Path) -> tuple[bool, list[dict]]:
    started, records = False, []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False, []
    for ln in text.splitlines():
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("kind") == "start":
            started = True
            records.append(rec)
        else:
            records.append(rec)
    return started, records


class _Code:
    """What counts as test code and as a repo frame under one root."""

    def __init__(self, root: Path, shape: str | None, sys_path: list[str] | None = None):
        import spec
        self.root = root.resolve()
        self.globs = spec.test_globs(shape)
        self.ignored = spec._ignored
        self.test_roots = {g.split("/", 1)[0] for g in self.globs if g.split("/", 1)[0] and not re.search(r"[*?\[]", g.split("/", 1)[0])}
        rels = [self.rel(p) for p in sys_path or []]      # in-repo directories of the test run's sys.path (#1062)
        self.path_dirs = [r for r in rels if r is not None and not self.ignored(r) and "site-packages" not in r.parts]
        self.planned = self._planned_stems(spec)

    def _planned_stems(self, spec) -> set[str]:
        """Names of the files the plan of a spec in build lists in `files:` (`a/x.py` → `x`, `a/pkg/` → `pkg`)."""
        stems: set[str] = set()
        try:
            for s in spec.judged_specs(self.root):
                for t in (s.plan[0].get("tasks") or []) if s.plan else []:
                    for f in (t.get("files") or []) if isinstance(t, dict) else []:
                        p = Path(str(f).rstrip("/"))
                        if p.suffix in ("", ".py") and p.name:
                            stems.add(p.stem)
                        for base in (Path("src"), *self.path_dirs):      # `src/pkg/mod.py` plans the package `pkg`
                            if p.suffix in ("", ".py") and base in p.parents and p != base:
                                stems.add(p.relative_to(base).parts[0].removesuffix(".py"))
        except Exception:  # noqa: BLE001  (a plan that cannot be read names nothing)
            pass
        return stems

    def rel(self, path: str) -> Path | None:
        try:
            return Path(path).resolve().relative_to(self.root)
        except (ValueError, OSError):
            return None

    def is_test(self, path: str) -> bool:
        rel = self.rel(path)
        if rel is None:
            return False
        return rel.name == "conftest.py" or any(_glob_match(rel, g) for g in self.globs)

    def is_repo_frame(self, path: str) -> bool:
        rel = self.rel(path)
        return rel is not None and not self.ignored(rel) and "site-packages" not in rel.parts

    def own_package(self, top: str, top_file: str | None) -> bool:
        """The repo's own code: the project's package name, a module or package under the root or `src/`, or one the
        test run found inside the repo, one a plan task of the spec in build names, or one that would sit in an in-repo
        `sys.path` directory of the run (`scripts/cplat`, #1062)."""
        if top_file and self.is_repo_frame(top_file):
            return True
        for base in (self.root, self.root / "src", *(self.root / d for d in self.path_dirs)):
            if (base / top).is_dir() or (base / f"{top}.py").is_file():
                return True
        return top in self.planned or top in self.project_names()

    def project_names(self) -> set[str]:
        try:
            import tomllib
            name = tomllib.loads((self.root / "pyproject.toml").read_text()).get("project", {}).get("name")
        except (OSError, ValueError, ImportError):
            return set()
        return {re.sub(r"[-.]+", "_", name).lower()} if isinstance(name, str) else set()

    def test_module(self, module: str, module_file: str | None) -> bool:
        if module_file:
            return self.is_test(module_file)
        first = module.split(".", 1)[0]
        return first == "conftest" or first in self.test_roots


def _glob_match(rel: Path, glob: str) -> bool:
    rx = re.escape(glob).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.fullmatch(rx, rel.as_posix()) is not None


def _line(exc: list[str] | None, message: str) -> str:
    kind = (exc or ["Exception"])[0]
    last = next((ln.strip() for ln in reversed((message or "").splitlines()) if ln.strip()), "")
    return (f"{kind}: {last}" if last else kind)[:_MAX_LINE]


def _static_names(path: Path) -> list[str]:
    import spec
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return []
    return sorted({m.group(m.lastindex) for m in spec._TEST_DEFS[0].finditer(text)})


def _import_class(rec: dict, code: _Code) -> tuple[str, str] | None:
    """An import or attribute error naming a non-test module: missing behaviour when the module is the repo's own code
    (#956), a test error otherwise, with "<pkg> is not installed" when its top-level package cannot be found at all."""
    exc = set(rec.get("exc") or [])
    mod = rec.get("module")
    if not (exc & _IMPORT_ERRORS) or not mod or code.test_module(mod, rec.get("module_file")):
        return None
    line = _line(rec.get("exc"), rec.get("message", ""))
    if "AttributeError" in exc and not exc & {"ImportError", "ModuleNotFoundError"}:
        return MISSING, line
    top = mod.split(".", 1)[0]
    if code.own_package(top, rec.get("top_file")):
        return MISSING, line
    if not rec.get("top_file"):
        return ERROR, f"{top} is not installed: add it to the dev dependencies"
    return ERROR, line


def _judge_collect(rec: dict, code: _Code) -> tuple[str, str]:
    if "NotImplementedError" in (rec.get("exc") or []):
        return MISSING, _line(rec.get("exc"), rec.get("message", ""))
    return _import_class(rec, code) or (ERROR, _line(rec.get("exc"), rec.get("message", "")))


def _judge_test(recs: list[dict], code: _Code) -> tuple[str, str]:
    order = {"setup": 0, "call": 1, "teardown": 2}
    recs = sorted(recs, key=lambda r: order.get(r.get("when"), 3))
    bad = [r for r in recs if r.get("outcome") != "passed"]
    if not bad:                                                                         # 2
        return PASSES, ""
    first = bad[0]
    if first.get("outcome") == "skipped" or any(r.get("outcome") == "skipped" for r in bad):   # 3
        sk = next(r for r in bad if r.get("outcome") == "skipped")
        why = next((ln.strip() for ln in reversed((sk.get("message") or "").splitlines()) if ln.strip()), "")[:_MAX_LINE]
        if sk.get("smoke") and not sk.get("xfail"):
            return SKIPPED, why
        return ERROR, why or "skipped"
    for r in bad:                                                                       # 4
        if "NotImplementedError" in (r.get("exc") or []):
            return MISSING, _line(r.get("exc"), r.get("message", ""))
    for r in bad:                                                                       # 5
        if (judged := _import_class(r, code)) is not None:
            return judged
    if first.get("when") != "call":                                                     # 6
        return ERROR, _line(first.get("exc"), first.get("message", ""))
    exc, text = first.get("exc") or [], _line(first.get("exc"), first.get("message", ""))
    if "AssertionError" in exc or "Failed" in exc:                                      # 7
        return MISSING, text
    repo = [f for f in first.get("frames") or [] if code.is_repo_frame(f)]              # 8
    if repo and not code.is_test(repo[-1]):
        return MISSING, text
    return ERROR, text


def classify(records: list[dict], root: Path, shape: str | None, files: list[str]) -> list[tuple[str, str, str]]:
    """(node id, class, exception line) per test of `files` (absolute paths), sorted by node id."""
    start = next((r for r in records if r.get("kind") == "start"), {})
    code = _Code(root, shape, start.get("sys_path") if isinstance(start.get("sys_path"), list) else None)
    wanted = {str(Path(f).resolve()) for f in files}

    def wanted_file(f: str) -> bool:
        return f in wanted or any(f.startswith(w.rstrip("/") + "/") for w in wanted)

    def rel(f: str) -> str:
        r = code.rel(f)
        return r.as_posix() if r is not None else f

    collects: dict[str, dict] = {}
    tests: dict[str, list[dict]] = {}
    for rec in records:
        f = rec.get("file")
        if not isinstance(f, str) or not wanted_file(str(Path(f).resolve())):
            continue
        if rec.get("kind") == "collect":
            collects.setdefault(str(Path(f).resolve()), rec)
        elif rec.get("kind") == "test":
            tests.setdefault(rec.get("nodeid", ""), []).append(rec)
    out: list[tuple[str, str, str]] = []
    for f, rec in collects.items():                                                     # 1
        cls, why = _judge_collect(rec, code)
        names = _static_names(Path(f))
        for node in ([f"{rel(f)}::{n}" for n in names] or [rel(f)]):
            out.append((node, cls, why))
    for node, recs in tests.items():
        if str(Path(recs[0]["file"]).resolve()) in collects:
            continue
        cls, why = _judge_test(recs, code)
        out.append((node, cls, why))
    return sorted(out)


def _summary(rows: list[tuple[str, str, str]], log: Path) -> str:
    import red_scope
    counts = [(c, sum(1 for _, k, _ in rows if k == c)) for c in (MISSING, ERROR, PASSES)]
    counts.append(("passes (not judged)", sum(1 for _, k, _ in rows if k.startswith(red_scope.NOT_JUDGED))))
    counts.append((red_scope.REGRESSION, sum(1 for _, k, _ in rows if k == red_scope.REGRESSION)))
    counts.append(("skipped", sum(1 for _, k, _ in rows if k == SKIPPED)))
    parts = [f"{n} {c}" for c, n in counts if n]
    return f"red check: {', '.join(parts) if parts else 'no test ran'} (log: {log})"


def _file_args(cwd: Path, args: list[str]) -> list[str]:
    files = []
    for a in args:
        if a.startswith("-"):
            continue
        f = a.split("::", 1)[0]
        if (cwd / f).exists():
            files.append(str((cwd / f).resolve()))
    return files


def _write_record(cwd: Path, files: list[str], code: int) -> None:
    gd = core.git_dir(cwd)
    if gd is None:
        return
    root = cwd.resolve()
    head = core.run(["git", "rev-parse", "HEAD"], cwd=cwd, check=False).stdout.strip() or None
    hashes = {}
    for f in sorted(set(files)):
        p = Path(f)
        if p.is_file():
            hashes[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    rec = {"head": head, "exit": code, "files": hashes, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (gd if gd.is_absolute() else cwd / gd).joinpath(RECORD_FILE).write_text(json.dumps(rec, indent=2) + "\n")


def _scope(cwd: Path, spec_ref: str):
    """AC-205.8: the scope of an amended spec, None for a first build; PlatformError for an unknown spec or no done commit."""
    import red_scope
    import spec
    return red_scope.scope(cwd.resolve(), spec.find(cwd.resolve(), spec_ref))


def run(cwd: Path, args: list[str], *, raw: bool, on: bool, spec_ref: str | None = None) -> int:
    import quiet
    import quiet_limit
    if not runs_pytest(cwd):
        print(quiet.USAGE, file=sys.stderr)
        return 2
    sc = None
    if spec_ref is not None:
        try:
            sc = _scope(cwd, spec_ref)
        except core.PlatformError as e:
            print(f"red check: {e}", file=sys.stderr)
            return 2
    cmd = ["devbox", "run", "test-fast", "--", *args]
    log = quiet._log_path(cwd, "test-fast-red")
    add, progress = quiet_limit.progress_env(log)
    red_file = Path(f"{log}.red")
    red_file.unlink(missing_ok=True)      # two runs within one second share a log name
    add["PYTEST_ADDOPTS"] = f"{add['PYTEST_ADDOPTS']} -p cplat_red_check"
    add["CPLAT_RED_FILE"] = str(red_file)
    add["CPLAT_RED_ROOT"] = str(cwd.resolve())
    deadline = time.monotonic() + quiet_limit.GIVE_UP_SECONDS
    with log.open("wb") as fh:
        proc = quiet_limit.start(quiet_limit.with_env(cmd, add), cwd=cwd, out=fh, env=core.repo_env(add))
        try:
            code = quiet_limit.wait_until(proc, deadline)
        finally:
            if proc.poll() is None:
                quiet_limit.stop(proc)
    if code is None:
        print("\n".join(quiet_limit.gave_up_lines("test-fast", log, progress)))
        return 124
    started, records = _load(red_file)
    if not started:
        print(quiet.USAGE, file=sys.stderr)
        return 2
    import spec
    files = _file_args(cwd, args)
    rows = classify(records, cwd, spec.repo_shape(cwd.resolve()), files)
    if sc is not None:
        import red_scope
        print(red_scope.scope_line(sc))
        rows, rc = red_scope.apply(rows, sc, cwd.resolve(), files)
    else:
        judged = [r for r in rows if r[1] != SKIPPED]
        rc = 0 if judged and all(r[1] == MISSING for r in judged) else 1
    for node, cls, why in rows:
        print(f"{node}: {cls}" + (f" — {why}" if why else ""))
    print(_summary(rows, log))
    _write_record(cwd, files, rc)
    return rc
