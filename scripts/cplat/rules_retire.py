"""`rules-retired` house rule (spec 168, AC-168.7): retiring or removing a register entry needs the eval gate to pass.

An entry (`<prompt path>`, `<id>`) is *changed* when it was not retired at the base and is missing or retired at the head,
or is retired at the head and did not exist at the base. Any change applies the eval gate (spec 151) to the head's plugin
tree for the workflows quick-task and build; the gate must pass, and every changed entry that is retired at the head records
the passing benchmark run ids in `benchmark_runs` (`--fix` writes them). The contract is
docs/specs/168-agent-rules-state-their-reason-and-can/design.md, `cplat platform pr-check`.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import evalgate
import promptrules as pr
from core import PlatformError

WORKFLOWS = ("quick-task", "build")
_DASH = re.compile(r"^(\s*-\s+)")
_RUNS = re.compile(r"^\s*benchmark_runs\s*:")
_ID_NUM = re.compile(r"\d+")

Key = tuple[str, str]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False).stdout


def _base_rev(repo: Path, base: str) -> str:
    """The commit the change started from (`base...HEAD` semantics); `base` itself when there is no merge base."""
    return _git(repo, "merge-base", base, "HEAD").strip() or base


def _base_entries(repo: Path, rev: str) -> dict[Key, pr.Entry]:
    found: dict[Key, pr.Entry] = {}
    for rel in filter(None, _git(repo, "ls-tree", "-r", "--name-only", rev, "--", pr.ENTRIES).splitlines()):
        prompt = pr.prompt_path(rel)
        if prompt is None:
            continue
        try:
            entries = pr.load_entries(rel, _git(repo, "show", f"{rev}:{rel}"))
        except pr.RegisterError:
            continue
        found.update({(prompt, e.id): e for e in entries if e.id})
    return found


def _head_entries(repo: Path) -> dict[Key, pr.Entry]:
    found: dict[Key, pr.Entry] = {}
    root = repo / pr.ENTRIES
    for file in sorted(root.rglob("*.yml")) if root.is_dir() else []:
        rel = file.relative_to(repo).as_posix()
        prompt = pr.prompt_path(rel)
        if prompt is None:
            continue
        try:
            entries = pr.load_entries(rel, file.read_text(encoding="utf-8"))
        except (pr.RegisterError, OSError):
            continue
        found.update({(prompt, e.id): e for e in entries if e.id})
    return found


def _order(key: Key) -> tuple[str, int]:
    m = _ID_NUM.search(key[1])
    return key[0], int(m.group(0)) if m else 0


def changed_keys(base: dict[Key, pr.Entry], head: dict[Key, pr.Entry]) -> list[Key]:
    keys = {k for k, b in base.items() if b.cls != "retired" and (k not in head or head[k].cls == "retired")}
    keys |= {k for k, h in head.items() if h.cls == "retired" and k not in base}
    return sorted(keys, key=_order)


def _write_runs(repo: Path, entry: pr.Entry, ids: list[str]) -> bool:
    """Put `benchmark_runs: [<ids>]` into `entry` of its file, indented like its keys; False when it cannot be done."""
    path = repo / entry.file
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = entry.line - 1
    m = _DASH.match(lines[start]) if 0 <= start < len(lines) else None
    if not m:
        return False
    indent = " " * len(m.group(1))
    end = start + 1
    while end < len(lines) and not _DASH.match(lines[end]) and (not lines[end].strip() or lines[end].startswith(indent)):
        end += 1
    value = f"{indent}benchmark_runs: [{', '.join(ids)}]\n"
    for i in range(start, end):
        if _RUNS.match(lines[i]):
            if "[" not in lines[i]:
                return False
            lines[i] = value
            break
    else:
        last = end - 1
        while last > start and not lines[last].strip():
            last -= 1
        if not lines[last].endswith("\n"):
            lines[last] += "\n"
        lines.insert(last + 1, value)
    path.write_text("".join(lines), encoding="utf-8")
    return True


def check(repo: Path, base: str, fix: bool = False, notes: list[str] | None = None) -> list[str]:
    """The `rules-retired` problems; `notes` (default: stdout) receives one line per entry `fix` wrote."""
    repo = Path(repo)
    before = _base_entries(repo, _base_rev(repo, base))
    after = _head_entries(repo)
    changed = changed_keys(before, after)
    if not changed:
        return []
    try:
        fails, runs = evalgate.verdict_runs(
            evalgate._records(evalgate.WINDOW_DAYS), head_tree=evalgate.plugins_tree(repo, "HEAD"),
            tree_of=lambda c: evalgate.plugins_tree(repo, c),
            baseline_version=evalgate.latest_tag(repo).lstrip("v"), workflows=WORKFLOWS)
    except PlatformError as e:
        return [f"rules-retired: {e}" + (f"; {e.hint}" if e.hint else "")]
    if fails:
        names = ", ".join(f"{p}#{i}" for p, i in changed)
        n = len(changed)
        what = "register entry" if n == 1 else "register entries"
        return [f"rules-retired: {n} {what} retired or removed ({names}); {f}" for f in fails]
    ids = list(runs.values())
    missing = []
    for key in changed:
        entry = after.get(key)
        if entry is not None and entry.cls == "retired":
            have = entry.benchmark_runs or []
            if not all(i in have for i in ids):
                missing.append((key, entry, [*have, *(i for i in ids if i not in have)]))
    written: set[Key] = set()
    if fix:   # bottom up, so the lines of the entries still to write do not move
        for key, entry, listed in sorted(missing, key=lambda m: (m[1].file, -m[1].line)):
            if _write_runs(repo, entry, listed):
                written.add(key)
    problems = []
    for key, _, _ in missing:
        if key in written:
            line = f"rules-retired: wrote benchmark_runs into {key[0]}#{key[1]}"
            print(line) if notes is None else notes.append(line)
        else:
            problems.append(f"rules-retired: {key[0]}#{key[1]} records no passing benchmark run; add benchmark_runs: "
                            f"[{', '.join(ids)}] (or run pr-check with --fix)")
    return problems
