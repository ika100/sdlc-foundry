"""`cplat platform eval-gate`: a change to the prompts ships only after the benchmark ran on it (spec 151, ADR-085).

  cplat platform eval-gate [--base REF] [--workflow W …] [--json]

The prompts are the Markdown files the agents read: `plugins/*/{agents,commands,references,skills}/**/*.md`. When one
changed since REF (default: the newest `v*` tag), every named workflow (default quick-task and build) needs a benchmark
record (`cplat platform runs benchmark <w> --plugins plugins`) whose plugins had exactly this `plugins/` tree, outcome
`done`, and at most 1.5 times the tokens of the median `done` run of the version REF names. `cplat platform release`
runs the same check before it opens the release PR. Exit 0 pass, 1 fail (one line each, with the command to run).
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import statistics
import subprocess
from pathlib import Path
from typing import Callable

from core import PlatformError

PROMPT = re.compile(r"^plugins/[^/]+/(agents|commands|references|skills)/.+\.md$")
WORKFLOWS = ("quick-task", "build")
TOKEN_LIMIT = 1.5
WINDOW_DAYS = 45
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False).stdout.strip()


def latest_tag(repo: Path) -> str:
    return _git(repo, "describe", "--tags", "--abbrev=0", "--match", "v*") or ""


def prompt_changes(repo: Path, base: str) -> list[str]:
    return [f for f in _git(repo, "diff", "--name-only", f"{base}...HEAD").splitlines() if PROMPT.match(f)]


def plugins_tree(repo: Path, rev: str) -> str:
    return _git(repo, "rev-parse", "-q", "--verify", f"{rev}:plugins")


def tokens(rec: dict) -> int | None:
    totals = (rec.get("usage") or {}).get("totals") if isinstance(rec.get("usage"), dict) else None
    if not isinstance(totals, dict):
        return None
    return int(sum(float(totals.get(f) or 0) for f in TOKEN_FIELDS))


def verdict(records: list[dict], *, head_tree: str, tree_of: Callable[[str], str], baseline_version: str,
            workflows: tuple[str, ...] = WORKFLOWS) -> list[str]:
    """The failures (empty: pass). `tree_of(commit)` is the `plugins/` tree of a commit ("" when unknown)."""
    return verdict_runs(records, head_tree=head_tree, tree_of=tree_of, baseline_version=baseline_version,
                        workflows=workflows)[0]


def verdict_runs(records: list[dict], *, head_tree: str, tree_of: Callable[[str], str], baseline_version: str,
                 workflows: tuple[str, ...] = WORKFLOWS) -> tuple[list[str], dict[str, str]]:
    """(the failures, `{workflow: run_id}` of the record that passed for each passing workflow)."""
    fails = []
    passed: dict[str, str] = {}
    for w in workflows:
        mine = [r for r in records if r.get("kind") == "benchmark" and (r.get("benchmark") or {}).get("workflow") == w]
        cand = []
        for r in mine:
            p = (r.get("benchmark") or {}).get("plugins")
            if isinstance(p, dict) and p.get("commit") and not p.get("dirty") and tree_of(str(p["commit"])) == head_tree:
                cand.append(r)
        run_it = f"cplat platform runs benchmark {w} --plugins plugins --reset-first"
        if not cand:
            fails.append(f"{w}: no benchmark ran with these prompts; run `{run_it}`")
            continue
        last = max(cand, key=lambda r: str(r.get("ended_at") or r.get("started_at") or ""))
        if last.get("outcome") != "done":
            fails.append(f"{w}: the last benchmark with these prompts ended {last.get('outcome')} (run {last.get('run_id')}); "
                         f"fix the prompts and run `{run_it}` again")
            continue
        base = [t for r in mine if r.get("outcome") == "done" and str(r.get("platform_version")) == baseline_version
                and r not in cand and (t := tokens(r)) is not None]
        have = tokens(last)
        if base and have is not None and have > TOKEN_LIMIT * statistics.median(base):
            fails.append(f"{w}: {have:,} tokens, more than {TOKEN_LIMIT}× the {baseline_version} median of "
                         f"{int(statistics.median(base)):,} ({len(base)} run(s)); make the prompts leaner or explain it in the release")
            continue
        passed[w] = str(last.get("run_id"))
    return fails, passed


def _records(days: int) -> list[dict]:
    import runs
    import runs_report
    import runs_store
    slug = runs.configured_repo()
    if slug is None:
        raise PlatformError("no run store configured (CPLAT_RUNS_REPO is not set): the gate reads the benchmark records there",
                            hint="set CPLAT_RUNS_REPO=<owner/name>")
    now = runs.utcnow()
    try:
        files = runs.open_store(slug).read([now.date() - datetime.timedelta(days=n) for n in range(days, -1, -1)])
    except runs_store.StoreError as e:
        raise PlatformError(f"run store {slug} is unreachable: {e}") from None
    return runs_report.parse([t for _, t in files])[0]


def check(repo: Path, base: str | None = None, workflows: tuple[str, ...] = WORKFLOWS,
          records: Callable[[int], list[dict]] = _records) -> tuple[list[str], list[str]]:
    """(the changed prompt files, the failures)."""
    base = base or latest_tag(repo)
    if not base:
        return [], []
    changed = prompt_changes(repo, base)
    if not changed:
        return [], []
    fails = verdict(records(WINDOW_DAYS), head_tree=plugins_tree(repo, "HEAD"), tree_of=lambda c: plugins_tree(repo, c),
                    baseline_version=base.lstrip("v"), workflows=workflows)
    return changed, fails


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat platform eval-gate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="compare with this ref (default: the newest v* tag)")
    ap.add_argument("--workflow", action="append", choices=["quick-task", "build", "ship", "fix-rounds"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    changed, fails = check(Path(ns.repo).resolve(), ns.base, tuple(ns.workflow or WORKFLOWS))
    if ns.json:
        print(json.dumps({"prompts_changed": changed, "ok": not fails, "failures": fails}, indent=2))
    elif not changed:
        print("OK: no prompt changed since the last release; no benchmark needed")
    else:
        print(f"{len(changed)} prompt file(s) changed since the last release")
        for f in fails:
            print(f"FAIL: {f}")
        if not fails:
            print("OK: the benchmark passed with these prompts")
    return 1 if fails else 0
