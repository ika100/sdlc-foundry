"""`cplat runs benchmark <quick-task|build|ship> [--reset-first]` (spec 099, ADR-035): one fixed task on a clean clone of the
sample repo (one fixed, trusted folder per workflow), run through `cplat headless`, recorded as a run of kind `benchmark` with its usage, and the sample repo reset.

The tasks and the pinned sample revision are in benchmark/tasks.json. Every git / gh call goes through `run`, which tests replace.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import runs
import runs_usage
import transcripts
from core import PlatformError

BENCH_DIR = Path(__file__).resolve().parent / "benchmark"
GIT_IDENTITY = ["-c", "user.name=cplat-benchmark", "-c", "user.email=benchmark@invalid"]


def run(cmd: list[str], cwd: Path | str | None = None) -> tuple[int, str, str]:   # tests replace this
    try:
        p = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", f"{type(e).__name__}: {e}"
    return p.returncode, p.stdout, p.stderr


def _why(out: str, err: str) -> str:
    lines = [ln.strip() for ln in (err or out or "").strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "no output")[:200]


def _ok(cmd: list[str], cwd: Path | str | None = None) -> str:
    code, out, err = run(cmd, cwd)
    if code != 0:
        raise RuntimeError(f"`{' '.join(str(c) for c in cmd[:3])}` failed: {_why(out, err)}")
    return out


def _remote_main(url: str) -> str:
    code, out, err = run(["git", "ls-remote", url, "refs/heads/main"])
    if code != 0:
        raise RuntimeError(_why(out, err))
    return out.split()[0] if out.split() else ""


def _open_prs(repo: str) -> list[int]:
    try:
        prs = json.loads(_ok(["gh", "pr", "list", "--repo", repo, "--state", "open", "--json", "number", "--limit", "100"]) or "[]")
    except ValueError:
        prs = []
    return [pr["number"] for pr in prs if isinstance(pr, dict) and isinstance(pr.get("number"), int)] if isinstance(prs, list) else []


def _refs(url: str, kind: str, clone: Path) -> list[str]:
    lines = _ok(["git", "ls-remote", f"--{kind}", url], clone).splitlines()
    return [line.split()[-1] for line in lines if line.split()]


def _newest_pr(repo: str) -> int:
    try:
        prs = json.loads(_ok(["gh", "pr", "list", "--repo", repo, "--state", "all", "--json", "number", "--limit", "1"]) or "[]")
    except ValueError:
        prs = []
    return max((pr["number"] for pr in prs if isinstance(pr, dict) and isinstance(pr.get("number"), int)), default=0) \
        if isinstance(prs, list) else 0


def snapshot(repo: str, clone: Path) -> dict:
    """The PRs, branches and tags that exist before a run: the reset after the run leaves them alone."""
    url = f"https://github.com/{repo}"
    return {"prs": set(_open_prs(repo)), "refs": set(_refs(url, "heads", clone)) | set(_refs(url, "tags", clone)),
            "newest_pr": _newest_pr(repo)}


EXPECTED = {"quick-task": "open", "build": "open", "ship": "merged"}


def result(workflow: str, repo: str, keep: dict) -> str | None:
    """Why the run did not deliver, or None when it did: quick-task and build end at a new open PR, ship at a new merged one."""
    state = EXPECTED[workflow]
    try:
        prs = json.loads(_ok(["gh", "pr", "list", "--repo", repo, "--state", state, "--json", "number", "--limit", "20"]) or "[]")
    except (ValueError, RuntimeError) as e:
        return f"could not check the result: {e}"[:200]
    new = [pr for pr in prs if isinstance(pr, dict) and isinstance(pr.get("number"), int) and pr["number"] > keep.get("newest_pr", 0)] \
        if isinstance(prs, list) else []
    return None if new else f"no new {state} PR in {repo}"


def trusted(clone: Path) -> bool:   # tests replace this
    """Claude Code only applies the repo's permission rules in a folder whose trust dialog was accepted (read-only check)."""
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home()) / ".claude.json"
    try:
        projects = json.loads(config.read_text()).get("projects") or {}
    except (OSError, ValueError, AttributeError):
        return False
    entry = projects.get(str(clone)) or projects.get(str(clone.resolve())) or {}
    return isinstance(entry, dict) and entry.get("hasTrustDialogAccepted") is True


def reset_sample(repo: str, rev: str, clone: Path, keep: dict | None = None) -> None:
    """Close the open PRs (and delete their branches), delete the other branches and the tags that are not ancestors of
    `rev` (with their releases), force main back to `rev` and check it. PRs and refs in `keep` (a `snapshot` taken before
    the run) are left alone. Raises RuntimeError with the reason."""
    url = f"https://github.com/{repo}"
    keep_prs, keep_refs = (keep or {}).get("prs", set()), (keep or {}).get("refs", set())
    for number in _open_prs(repo):
        if number not in keep_prs:
            _ok(["gh", "pr", "close", str(number), "--repo", repo, "--delete-branch"])
    for ref in _refs(url, "heads", clone):
        if ref.startswith("refs/heads/") and ref != "refs/heads/main" and ref not in keep_refs:
            _ok(["git", "push", url, "--delete", ref], clone)
    for ref in _refs(url, "tags", clone):
        if not ref.startswith("refs/tags/") or ref.endswith("^{}") or ref in keep_refs:
            continue
        tag = ref[len("refs/tags/"):]
        code, out, _ = run(["gh", "api", f"repos/{repo}/compare/{tag}...{rev}", "-q", ".status"])
        if code == 0 and out.strip() in ("ahead", "identical"):
            continue
        run(["gh", "release", "delete", tag, "--repo", repo, "--yes"])   # a tag may have no release
        _ok(["git", "push", url, "--delete", ref], clone)
    _ok(["git", "push", "--force", url, f"{rev}:refs/heads/main"], clone)
    if _remote_main(url) != rev:
        raise RuntimeError(f"main of {repo} is not at {rev[:7]} after the reset")


def _prepare(url: str, rev: str, task: dict, clone: Path) -> None:
    """Clone once, then reuse the folder (its trust stays): back to `rev` with no local branches and no untracked files."""
    clone.parent.mkdir(parents=True, exist_ok=True)
    if not (clone / ".git").exists():
        _ok(["git", "clone", url, str(clone)])
    _ok(["git", "fetch", "--prune", "origin"], clone)
    run(["git", "fetch", "origin", rev], clone)   # the pinned commit may no longer be on a branch
    _ok(["git", "checkout", "-f", "-B", "main", rev], clone)
    for branch in _ok(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"], clone).split():
        if branch != "main":
            _ok(["git", "branch", "-D", branch], clone)
    _ok(["git", "clean", "-ffdx", "-e", ".devbox", "-e", ".venv"], clone)
    if task.get("spec_file"):
        target = clone / "docs" / "specs" / task["spec_id"] / "spec.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BENCH_DIR / task["spec_file"], target)
        _ok(["git", "add", "docs/specs"], clone)
        _ok(["git", *GIT_IDENTITY, "commit", "-m", f"docs(spec): {task['spec_id']} (benchmark)"], clone)


def _run_headless(argv: list[str], rid: str | None) -> str:
    import headless
    saved = {k: os.environ.get(k) for k in ("CPLAT_RUN_PARENT", "CPLAT_BENCHMARK")}
    if rid:
        os.environ["CPLAT_RUN_PARENT"] = os.environ["CPLAT_BENCHMARK"] = rid
    try:
        return "done" if headless.main(argv) == 0 else "failed"
    except Exception as e:  # noqa: BLE001  (the benchmark is recorded as failed)
        print(f"benchmark: headless stopped with {type(e).__name__}: {e}", flush=True)
        return "failed"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def steps(task: dict) -> list[tuple[str, str]]:
    """The task's prompts as (phase name, prompt): `steps` for a workflow that needs several commands, else `prompt` alone."""
    if task.get("steps"):
        return [(s["name"], s["prompt"]) for s in task["steps"]]
    return [("run", task["prompt"])]


def _summary(usage: dict | None) -> tuple[int, str, str]:
    t = (usage or {}).get("totals") or {}
    tokens = sum(int(t.get(f) or 0) for f in ("input", "output", "cache_read", "cache_write"))
    cost = t.get("cost_usd")
    return tokens, f"{cost:.2f}" if isinstance(cost, (int, float)) else "unknown", str((usage or {}).get("price_table"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat runs benchmark", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workflow", choices=["quick-task", "build", "ship"])
    ap.add_argument("--reset-first", action="store_true", help="put the sample repo back to the pinned revision before starting")
    ns = ap.parse_args(argv)
    tasks = json.loads((BENCH_DIR / "tasks.json").read_text())
    repo, rev = tasks["sample"]["repo"], tasks["sample"]["rev"]
    task = tasks["workflows"][ns.workflow]
    url = f"https://github.com/{repo}"
    try:
        main_now = _remote_main(url)
    except RuntimeError as e:
        raise PlatformError(f"sample repo {repo} cannot be reached: {e}") from None
    if main_now != rev and not ns.reset_first:
        raise PlatformError(f"sample repo {repo}: main is at {main_now[:7] or 'nothing'}, not the pinned {rev[:7]}",
                            hint=f"cplat runs benchmark {ns.workflow} --reset-first")
    clone = runs.state_dir() / "benchmark" / ns.workflow
    try:
        _prepare(url, rev, task, clone)
        if not trusted(clone):
            raise PlatformError(f"the benchmark folder {clone} is not trusted in Claude Code, so its permission rules would be ignored",
                                hint=f"cd {clone} && claude   (accept the trust dialog, then /exit), and run the benchmark again")
        if main_now != rev:
            reset_sample(repo, rev, clone)
        keep = snapshot(repo, clone)
    except RuntimeError as e:
        raise PlatformError(f"sample repo {repo} could not be prepared: {e}") from None

    rid = runs.start("benchmark", repo=repo, mode="headless")
    if rid:
        runs_usage.register(rid, mode="own", project_dir=str(runs_usage.projects_root() / transcripts.cwd_slug(clone)))
    outcome, reset, note, check = "failed", "not run", None, None
    usage = None
    try:
        for name, prompt in steps(task):   # e.g. build: plan, then build; each its own phase, a failed step stops the run
            runs.phase(rid, f"benchmark:{name}")
            outcome = _run_headless(["--repo", str(clone), "--max-runs", str(task["max_runs"]),
                                     "--max-minutes", str(task["max_minutes"]), prompt], rid)
            if outcome != "done":
                check = f"step {name} did not finish"
                break
        if outcome == "done":
            missing = result(ns.workflow, repo, keep)
            if missing:
                outcome, check = "failed", missing
    finally:
        runs.phase(rid, "benchmark:reset")
        try:
            reset_sample(repo, rev, clone, keep)
            reset = "done"
        except Exception as e:  # noqa: BLE001
            reset, note = "failed", f"{type(e).__name__}: {e}"[:200]
        try:
            active = runs.active(rid)
            if active is not None:
                usage = runs_usage.for_run(active, ended_at=runs._iso(runs.utcnow()))
        except Exception:  # noqa: BLE001
            pass
        runs.finish(rid, outcome, fields={"benchmark": {
            "workflow": ns.workflow, "task_version": task["task_version"], "sample_repo": repo, "sample_rev": rev,
            "reset": reset, "reset_note": note, "result_check": check}})
    if reset == "failed":
        raise PlatformError(f"reset of sample repo {repo} failed: {note}; the benchmark record was written",
                            hint=f"cplat runs benchmark {ns.workflow} --reset-first")
    tokens, cost, prices = _summary(usage)
    print(f"benchmark {ns.workflow} v{task['task_version']} on {repo}@{rev[:7]}: {outcome}, {tokens} tokens, "
          f"est. USD {cost} (prices of {prices}); reset {reset}" + (f"; {check}" if check else ""))
    return 0 if outcome == "done" else 1
