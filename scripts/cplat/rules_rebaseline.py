"""`cplat platform rules rebaseline` (spec 180, AC-180.5, AC-180.6): raise the prompt baseline behind the eval gate.

The register's `baseline.prompt_bytes` only grows through this command: it refuses a short reason and a dirty tree, does
nothing when the prompts fit the baseline, applies the eval gate (spec 151) to the HEAD plugin tree for quick-task and
build, and only then writes `commit`, `prompt_bytes` and a `history` entry into docs/rules/register.yml by line edits,
so the comments of the register stay. The contract is docs/specs/180-*/design.md, `cplat platform rules rebaseline`.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import evalgate
import promptrules as pr
from core import PlatformError

WORKFLOWS = ("quick-task", "build")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’_-]*")
_INDENT = re.compile(r"^(\s*)")


@dataclass
class Outcome:
    status: str                       # raised | nothing | refused
    old: int
    new: int
    reason: str
    benchmark_runs: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)      # what the CLI prints

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "refused" else 0


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False).stdout


def _dirty_paths(repo: Path) -> list[str]:
    return [ln[3:].strip() for ln in _git(repo, "status", "--porcelain").splitlines() if ln.strip()]


def _write(repo: Path, commit: str, total: int, entry: list[str]) -> None:
    """Replace `commit:` and `prompt_bytes:` under `baseline:` and append `entry` (lines) to its `history:`."""
    path = repo / pr.REGISTER
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if re.match(r"baseline\s*:", ln))
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][0] in " \t#"):
        end += 1
    last = end - 1
    while last > start and not lines[last].strip():
        last -= 1
    indent = next((_INDENT.match(lines[i]).group(1) for i in range(start + 1, end)
                   if lines[i].strip() and not lines[i].lstrip().startswith("#")), "  ")
    hist = None
    for i in range(start + 1, end):
        text = lines[i]
        if text.startswith(indent + "commit:"):
            lines[i] = f'{indent}commit: "{commit}"\n'
        elif text.startswith(indent + "prompt_bytes:"):
            lines[i] = f"{indent}prompt_bytes: {total}\n"
        elif text.startswith(indent + "history:"):
            hist = i
            if "[" in text:
                lines[i] = f"{indent}history:\n"
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    block = [f"{indent}  {ln}" for ln in entry]
    if hist is None:
        block.insert(0, f"{indent}history:                       # newest last; written only by `cplat platform rules rebaseline`\n")
    lines[last + 1:last + 1] = block
    path.write_text("".join(lines), encoding="utf-8")


def _entry_lines(date: str, old: int, new: int, reason: str, runs: list[str]) -> list[str]:
    return [f'- date: "{date}"\n', f"  old: {old}\n", f"  new: {new}\n",
            f"  reason: {json.dumps(reason, ensure_ascii=False)}\n", f"  benchmark_runs: [{', '.join(runs)}]\n"]


def rebaseline(repo: Path, reason: str, *, today: datetime.date | None = None) -> Outcome:
    repo = Path(repo)
    reason = reason.strip()
    register = pr.load_register(repo)
    old = register.baseline_bytes or 0
    total = pr.prompt_bytes(repo)

    def refuse(message: str, failures: list[str] | None = None, runs: list[str] | None = None) -> Outcome:
        return Outcome("refused", old, total, reason, runs or [], failures or [message],
                       [*(f"FAIL: {f}" for f in failures or []), f"ERROR: {message}"])

    if len(_WORD.findall(reason)) < pr.MIN_REASON_WORDS:
        return refuse("the reason needs at least 3 words")
    dirty = _dirty_paths(repo)
    if dirty:
        return refuse(f"uncommitted changes: {', '.join(dirty)}; rebaseline measures a clean tree")
    if total <= old:
        return Outcome("nothing", old, total, reason, [], [],
                       [f"OK: the prompts total {total} bytes, within the baseline {old}; nothing needs raising"])
    fails, runs = evalgate.verdict_runs(
        evalgate._records(evalgate.WINDOW_DAYS), head_tree=evalgate.plugins_tree(repo, "HEAD"),
        tree_of=lambda c: evalgate.plugins_tree(repo, c),
        baseline_version=evalgate.latest_tag(repo).lstrip("v"), workflows=WORKFLOWS)
    if fails:
        return refuse(f"the eval gate did not pass; the baseline stays {old}", list(fails))
    ids = [runs[w] for w in WORKFLOWS if w in runs]
    date = (today or datetime.datetime.now(datetime.timezone.utc).date()).isoformat()
    _write(repo, _git(repo, "rev-parse", "HEAD").strip(), total, _entry_lines(date, old, total, reason, ids))
    return Outcome("raised", old, total, reason, ids, [],
                   [f"raised the prompt baseline from {old} to {total} bytes (benchmark runs {', '.join(ids)}); "
                    "commit docs/rules/register.yml"])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat platform rules rebaseline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reason", required=True, help="why the prompts may grow (at least 3 words)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    try:
        out = rebaseline(Path(ns.repo).resolve(), ns.reason)
    except pr.RegisterError as e:
        raise PlatformError(str(e), "restore docs/rules/register.yml") from e
    if ns.json:
        print(json.dumps({"status": out.status, "old": out.old, "new": out.new, "reason": out.reason,
                          "benchmark_runs": out.benchmark_runs, "failures": out.failures}, indent=2))
    else:
        stream = sys.stderr if out.status == "refused" else sys.stdout
        for line in out.lines:
            print(line, file=stream)
    return out.exit_code
