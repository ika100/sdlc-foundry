"""`rules-baseline` house rule (spec 180, AC-180.7): a raised prompt baseline needs its history entry.

When the head's `baseline.prompt_bytes` is above the merge base's, the head history must hold an entry the base did not have,
and the newest entry's `new` must equal the baseline. The old and new count, the reason and the run ids of the newest entry
are shown as a note. The contract is docs/specs/180-prompt-checks-test-behaviour-not-t/design.md, `cplat platform pr-check`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import promptrules as pr
import rules_retire


def _key(h: pr.BaselineRaise) -> tuple:
    return (h.date, h.old, h.new, h.reason, tuple(h.benchmark_runs))


def check(repo: Path, base: str, notes: list[str] | None = None) -> list[str]:
    path = repo / pr.REGISTER
    if not path.is_file():
        return []
    rev = rules_retire._base_rev(repo, base)
    shown = subprocess.run(["git", "show", f"{rev}:{pr.REGISTER}"], cwd=repo, text=True, capture_output=True, check=False)
    if shown.returncode != 0:
        return []
    try:
        head_text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    base_bytes, base_history, _ = pr.parse_baseline(shown.stdout)
    head_bytes, head_history, line = pr.parse_baseline(head_text)
    if base_bytes is None or head_bytes is None or head_bytes <= base_bytes:
        return []
    where = f"rules-baseline: {pr.REGISTER}:{line}:"
    problems: list[str] = []
    known = {_key(h) for h in base_history}
    if head_history and notes is not None:
        newest = head_history[-1]
        notes.append(f"rules-baseline: prompt baseline {newest.old} → {newest.new} bytes; reason: {newest.reason}; "
                     f"benchmark runs: {', '.join(newest.benchmark_runs)}")
    if not any(_key(h) not in known for h in head_history):
        problems.append(f"{where} the baseline rose from {base_bytes} to {head_bytes} bytes with no history entry; raise it with "
                        'cplat platform rules rebaseline --reason "<why>", not by hand')
    elif head_history[-1].new != head_bytes:
        problems.append(f"{where} the newest history entry raises to {head_history[-1].new} bytes, the baseline says {head_bytes}")
    return problems
