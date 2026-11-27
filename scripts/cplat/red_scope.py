"""Spec 205 (AC-205.8): the scope of the red check of an amended spec.

A spec is amended after an earlier build when its Changelog has a `done` bullet followed later by an `amended` bullet. Its
red check judges only the tests that trace to a criterion new or changed since the spec's last `done` commit; every other
test of the trace must pass, and one that does not is a `regression` (design.md, "Decisions — AC-205.8" and section 6).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import core
from core import PlatformError

DONE = re.compile(r"^- \d{4}-\d{2}-\d{2} done\b")
AMENDED = re.compile(r"^- \d{4}-\d{2}-\d{2} amended\b")
_ID = re.compile(r"AC-(\d{3,})\.(\d+)(?!\d)")
_SLUG = re.compile(r"(?<![^_])ac_(\d{3,})_(\d+)(?![^_])", re.I)
_SUFFIX = re.compile(r"\[.*\]$")
REGRESSION = "regression"
NOT_JUDGED = "passes (not judged"


@dataclass
class Scope:
    spec_id: str
    number: str
    sha: str
    active: set[str]
    changed: set[str]


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _bullets(text: str) -> list[str]:
    """The Changelog bullets of a spec's text (body or whole file), continuation lines joined, whitespace collapsed."""
    import spec
    out: list[str] = []
    for ln in (spec.sections(text).get("changelog") or "").splitlines():
        if ln.startswith("- "):
            out.append(ln)
        elif out and ln[:1].isspace() and ln.strip():
            out[-1] += " " + ln
    return [_collapse(b) for b in out]


def amended(sp) -> bool:
    """A `done` bullet, then a later `amended` bullet in the Changelog (no git needed)."""
    seen_done = False
    for b in _bullets(sp.body):
        if DONE.match(b):
            seen_done = True
        elif seen_done and AMENDED.match(b):
            return True
    return False


def _last_done(sp) -> str:
    return [b for b in _bullets(sp.body) if DONE.match(b)][-1]


def _rel(root: Path, sp) -> str:
    return (Path(sp.dir).resolve() / "spec.md").relative_to(root.resolve()).as_posix()


def done_commit(root: Path, sp) -> str:
    """The newest commit whose spec.md ends its Changelog with the current file's last `done` bullet."""
    rel, done = _rel(root, sp), _last_done(sp)
    log = core.run(["git", "log", "--format=%H", "HEAD", "--", rel], cwd=root, check=False)
    for sha in log.stdout.split() if log.returncode == 0 else []:
        shown = core.run(["git", "show", f"{sha}:{rel}"], cwd=root, check=False)
        if shown.returncode != 0:
            continue
        bullets = _bullets(shown.stdout)
        if bullets and bullets[-1] == done:
            return sha
    raise PlatformError(f'no commit of {rel} ends its Changelog with "{done}"; fetch the full history (git fetch --unshallow)')


def criteria(text: str) -> dict[str, str]:
    """Active criterion id -> its text (bullet line plus indented continuation lines, after `spec_replace.hash_text`,
    whitespace collapsed)."""
    import spec
    import spec_replace
    raw = (spec.sections(text).get("acceptance criteria") or "").splitlines()
    hashed = spec_replace.hash_text("\n".join(raw)).splitlines()
    out: dict[str, str] = {}
    cur: str | None = None
    for i, ln in enumerate(raw):
        m = spec.AC_LINE.match(ln)
        if m:
            cur = None if m.group(1) else m.group(2)
            if cur:
                out[cur] = hashed[i] if i < len(hashed) else ln
        elif cur and ln[:1].isspace() and ln.strip():
            out[cur] += " " + (hashed[i] if i < len(hashed) else ln)
        else:
            cur = None
    return {k: _collapse(v) for k, v in out.items()}


def scope(root: Path, sp) -> Scope | None:
    """None when the spec is not amended after a build; PlatformError when its last `done` commit is not in the history."""
    if not amended(sp):
        return None
    root = root.resolve()
    sha = done_commit(root, sp)
    old = criteria(core.run(["git", "show", f"{sha}:{_rel(root, sp)}"], cwd=root).stdout)
    now = criteria(sp.body)
    active = set(sp.active_acs())
    changed = {a for a in active if a not in old or old[a] != now.get(a)}
    return Scope(sp.id, sp.number, sha, active, changed)


def sort_ids(ids) -> list[str]:
    return sorted(ids, key=lambda a: tuple(int(x) for x in a[3:].split(".")))


def _ids(text: str, number: str, active: set[str]) -> set[str]:
    found = {f"AC-{m.group(1)}.{m.group(2)}" for m in _ID.finditer(text)}
    found |= {f"AC-{m.group(1)}.{m.group(2)}" for m in _SLUG.finditer(text)}
    return {a for a in found if a.split("-", 1)[1].split(".", 1)[0] == number and a in active}


_PARSED: dict[tuple[str, int, int], tuple[str, ast.Module | None]] = {}


def _parse(path: Path) -> tuple[str, ast.Module | None]:
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return "", None
    if key not in _PARSED:
        text = path.read_text(errors="ignore")
        try:
            tree: ast.Module | None = ast.parse(text)
        except SyntaxError:
            tree = None
        _PARSED[key] = (text, tree)
    return _PARSED[key]


def _find(body: list, name: str):
    return next((n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name), None)


def _first_line(node) -> int:
    return min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])


def _chain(tree: ast.Module | None, parts: list[str]) -> list:
    """The class/function nodes of a node id's parts, or [] when one is not found."""
    chain, body = [], tree.body if tree is not None else []
    for p in parts:
        node = _find(body, p)
        if node is None:
            return []
        chain.append(node)
        body = node.body
    return chain


def own_criteria(path: Path, test: str, number: str, active: set[str]) -> set[str] | None:
    """The criteria of spec `number` a test names on its own lines and name, else on its class; None when neither names a
    criterion of any spec. A test that names another spec's criterion (`AC-189.1`) traces to none of this spec's."""
    import spec
    text, tree = _parse(path)
    lines = text.splitlines()
    parts = [_SUFFIX.sub("", p) for p in test.split("::") if p]
    if parts and tree is not None:
        chain = _chain(tree, parts)
        if chain:
            fn = chain[-1]
            own = "\n".join(lines[_first_line(fn) - 1:fn.end_lineno]) + "\n" + fn.name
            if _names_any(own):                                                           # 1
                return _ids(own, number, active)
            for cls in reversed(chain[:-1]):                                              # 2
                head = "\n".join(lines[_first_line(cls) - 1:cls.lineno])
                own = f"{head}\n{ast.get_docstring(cls) or ''}\n{cls.name}"
                if _names_any(own):
                    return _ids(own, number, active)
    elif parts:
        name = parts[-1]
        for m in spec._TEST_DEFS[0].finditer(text):
            if m.group(1) == name and _names_any(own := m.group(0) + "\n" + name):
                return _ids(own, number, active)
    return None


def test_criteria(path: Path, test: str, number: str, active: set[str]) -> set[str]:
    """The criteria a test traces to: its own lines and name, else its class, else the whole file."""
    own = own_criteria(path, test, number, active)
    return own if own is not None else _ids(_parse(path)[0], number, active)                  # 3


def _names_any(text: str) -> bool:
    return bool(_ID.search(text) or _SLUG.search(text))


def base_commit(root: Path) -> str | None:
    """The fork point of the build branch: its merge base with the remote default branch (None when it cannot be told)."""
    ref = core.run(["git", "symbolic-ref", "-q", "refs/remotes/origin/HEAD"], cwd=root, check=False)
    branch = (ref.stdout or "").strip() if ref.returncode == 0 and (ref.stdout or "").strip() else "refs/remotes/origin/main"
    mb = core.run(["git", "merge-base", "HEAD", branch], cwd=root, check=False)
    return (mb.stdout or "").strip() or None if mb.returncode == 0 else None


def _source(text: str, parts: list[str]) -> str | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    chain = _chain(tree, parts)
    if not chain:
        return None
    fn = chain[-1]
    return "\n".join(text.splitlines()[_first_line(fn) - 1:fn.end_lineno])


def unchanged_since(root: Path, path: Path, test: str, base: str) -> bool:
    """The test exists at `base` with the same source: the build neither added nor changed it."""
    parts = [_SUFFIX.sub("", p) for p in test.split("::") if p]
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    old = core.run(["git", "show", f"{base}:{rel}"], cwd=root, check=False)
    if old.returncode != 0 or not parts:
        return False
    before, now = _source(old.stdout, parts), _source(_parse(path)[0], parts)
    return before is not None and before == now


def _test_file(root: Path, file: str, files: list[str]) -> Path:
    """The file of a node id: pytest prints it relative to its rootdir (`tests/cplat/pytest.ini` makes it `test_x.py`),
    so a path that is not under the repo root is matched against the run's files by its tail."""
    if (root / file).is_file():
        return root / file
    tail = "/" + file
    return next((Path(f) for f in files if Path(f).as_posix().endswith(tail)), root / file)


def apply(rows: list[tuple[str, str, str]], sc: Scope, root: Path,
          files: list[str] | None = None) -> tuple[list[tuple[str, str, str]], int]:
    """Relabel `quiet_red.classify`'s rows for the scope and compute the exit code (`files`: the run's test files)."""
    import quiet_red
    out: list[tuple[str, str, str]] = []
    judged_rows: list[str] = []
    ok = bool(rows)
    base: list[str | None] = []
    for node, cls, why in rows:
        file, _, test = node.partition("::")
        path = _test_file(root, file, files or [])
        ids = own_criteria(path, test, sc.number, sc.active)
        if ids is None:          # names no criterion: the file's criteria, unless the build left the test as it was
            if not base:
                base.append(base_commit(root))
            ids = set() if base[0] and unchanged_since(root, path, test, base[0]) else test_criteria(path, test, sc.number, sc.active)
        if ids & sc.changed:
            out.append((node, cls, why))
            if cls != quiet_red.SKIPPED:
                judged_rows.append(cls)
                ok = ok and cls == quiet_red.MISSING
        elif cls == quiet_red.PASSES:
            named = ", ".join(sort_ids(ids)) if ids else f"no criterion of {sc.number}"
            out.append((node, f"{NOT_JUDGED}: {named} unchanged)", ""))
        elif cls == quiet_red.SKIPPED:
            out.append((node, cls, why))
        else:
            out.append((node, REGRESSION, why))
            ok = False
    if sc.changed and not judged_rows:
        ok = False
    return out, 0 if ok else 1


def scope_line(sc: Scope) -> str:
    if sc.changed:
        return (f"red check: judging the tests of {', '.join(sort_ids(sc.changed))} (new or changed since {sc.sha[:7]}); "
                "every other test must pass")
    return f"red check: no criterion is new or changed since {sc.sha[:7]}; every test must pass"
