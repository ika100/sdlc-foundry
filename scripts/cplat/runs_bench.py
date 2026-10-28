"""`cplat platform runs benchmark <quick-task|build|ship> [--reset-first] [--plugins DIR]` (spec 099, ADR-035): one fixed task on a clean clone of the
sample repo (one fixed, trusted folder per workflow), run through `cplat headless`, recorded as a run of kind `benchmark` with its usage, and the sample repo reset.

The tasks and the pinned sample revision are in benchmark/tasks.json. Every git / gh call goes through `run`, which tests replace.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import runs
import runs_report
import runs_usage
import runs_usage_report
import settings
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


EXPECTED = {"quick-task": "open", "build": "open", "ship": "merged", "fix-rounds": "open"}


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


def _prepare(url: str, rev: str, task: dict, clone: Path, spec: bool = True) -> None:
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
    if spec:
        commit_spec(task, clone)


def commit_spec(task: dict, clone: Path) -> None:
    """The workflow's spec as a local commit (build, ship). With an arm it comes after the arm's commit, which alone goes to main."""
    if task.get("spec_file"):
        target = clone / "docs" / "specs" / task["spec_id"] / "spec.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BENCH_DIR / task["spec_file"], target)
        _ok(["git", "add", "docs/specs"], clone)
        _ok(["git", *GIT_IDENTITY, "commit", "-m", f"docs(spec): {task['spec_id']} (benchmark)"], clone)


def load_arm(name: str, workflow: str) -> dict:
    """The arm `name` from benchmark/arms/ (spec 107), checked against the workflow. Raises PlatformError."""
    path = BENCH_DIR / "arms" / f"{name}.json"
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise ValueError("not a valid arm name")
        arm = json.loads(path.read_text())
    except (OSError, ValueError):
        known = sorted(p.stem for p in (BENCH_DIR / "arms").glob("*.json"))
        raise PlatformError(f"unknown benchmark arm '{name}'", hint="arms: " + (", ".join(known) or "none")) from None
    if not isinstance(arm, dict) or workflow not in (arm.get("workflows") or []):
        raise PlatformError(f"benchmark arm '{name}' does not list the workflow {workflow}",
                            hint="workflows: " + ", ".join(arm.get("workflows") or []) if isinstance(arm, dict) else None)
    return arm


def stage_arm(arm: dict, clone: Path) -> None:
    """Write the arm's files, run its commands in the clone and commit `bench: arm <name>` locally (nothing leaves the machine).
    Raises RuntimeError naming the failing command."""
    for rel, content in (arm.get("files") or {}).items():
        target = (clone / rel).resolve()
        if clone.resolve() not in target.parents:
            raise RuntimeError(f"arm {arm['name']}: file {rel} is outside the clone")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)   # verbatim: no local path ever reaches the (public) sample repo
    for cmd in arm.get("commands") or []:
        code, out, err = run(cmd, clone)
        if code != 0:
            raise RuntimeError(f"arm {arm['name']}: `{' '.join(str(c) for c in cmd[:4])}` failed: {_why(out, err)}")
    _ok(["git", "add", "-A"], clone)
    _ok(["git", *GIT_IDENTITY, "commit", "--allow-empty", "-m", f"bench: arm {arm['name']}"], clone)


def load_seed(workflow: str) -> dict:
    """The seed of a workflow (`fix-rounds`, spec 108): arm-shaped, `files` only. Raises PlatformError."""
    task = json.loads((BENCH_DIR / "tasks.json").read_text())["workflows"][workflow]
    try:
        seed = json.loads((BENCH_DIR / task["seed"]).read_text())
        if not isinstance(seed, dict) or not isinstance(seed.get("files"), dict):
            raise ValueError("no files")
    except (OSError, ValueError) as e:
        raise PlatformError(f"benchmark seed {task.get('seed')} is not readable: {e}") from None
    return seed


def push_arm(url: str, clone: Path) -> None:
    """Push the arm commit (not forced) to main. The reset after the run puts main back."""
    _ok(["git", "push", url, "HEAD:refs/heads/main"], clone)


SUITE = ["bash", "-c", "SMOKE_BASE_URL= uv run python -m pytest tests/ -p scripts.smoke_pytest -q --tb=line"]


def recall_check(clone: Path) -> str | None:
    """`--recall` (spec 107): the full suite in the clone after the session. None when green, else why the arm's selection missed a failure."""
    code, out, err = run(SUITE, clone)
    if code == 0:
        return None
    failed = [ln.split()[1] for ln in out.splitlines() if ln.startswith("FAILED ") and len(ln.split()) > 1]
    return ("recall: the full suite fails on " + ", ".join(failed) if failed else f"recall: the full suite failed: {_why(out, err)}")[:300]


def _run_headless(argv: list[str], rid: str | None, platform: Path | None = None) -> str:
    """`platform`: the checkout whose plugins run (--plugins). Its `cplat` must run too: the installed shared plugin's bin/ comes
    first on the session's PATH, so the launcher is pointed there with CPLAT_PLATFORM."""
    import headless
    saved = {k: os.environ.get(k) for k in ("CPLAT_RUN_PARENT", "CPLAT_BENCHMARK", "CPLAT_PLATFORM")}
    if rid:
        os.environ["CPLAT_RUN_PARENT"] = os.environ["CPLAT_BENCHMARK"] = rid
    if platform:
        os.environ["CPLAT_PLATFORM"] = str(platform)
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


def plugin_args(plugins: str, clone: Path) -> tuple[list[str], dict]:
    """`--plugin-dir` args for the plugins the clone enables, and the record's `plugins` section (spec 100)."""
    folder = Path(plugins).resolve()
    try:
        enabled = json.loads((clone / ".claude" / "settings.json").read_text()).get("enabledPlugins") or {}
    except (OSError, ValueError, AttributeError):
        enabled = {}
    names = [k.split("@")[0] for k, v in enabled.items() if v is True]
    args: list[str] = []
    for name in names:
        manifest = folder / name / ".claude-plugin" / "plugin.json"
        try:
            ok = json.loads(manifest.read_text()).get("name") == name
        except (OSError, ValueError, AttributeError):
            ok = False
        if not ok:
            raise PlatformError(f"--plugins {folder}: the sample enables plugin '{name}', but {manifest} is missing or names another plugin")
        args += ["--plugin-dir", str(folder / name)]
    code, out, _ = run(["git", "-C", str(folder), "rev-parse", "HEAD"])
    commit = out.strip() if code == 0 else ""
    dirty = bool(run(["git", "-C", str(folder), "status", "--porcelain"])[1].strip()) if commit else False
    return args, {"dir": str(folder), "commit": commit, "dirty": dirty}


def _children(rid: str | None) -> dict[str, dict]:
    """Finished runs started inside benchmark run `rid` (`benchmark_of`), from the local buffer and the run store. Never raises."""
    found: dict[str, dict] = {}
    if not rid:
        return found
    try:
        for r in runs._read_buffer():
            if isinstance(r, dict) and r.get("benchmark_of") == rid and r.get("run_id"):
                found[r["run_id"]] = r
    except Exception:  # noqa: BLE001
        pass
    try:
        import runs_report
        slug = runs.configured_repo()
        if slug:
            today = runs.utcnow().date()
            files = runs.open_store(slug).read([today - datetime.timedelta(days=1), today])
            for r in runs_report.parse([text for _, text in files])[0]:
                if r.get("benchmark_of") == rid and r.get("run_id"):
                    found[r["run_id"]] = r
    except Exception:  # noqa: BLE001
        pass
    return found


def _pass_summary(label: str, rid: str | None, started: str, ended: str, new: list[dict]) -> dict:
    """Duration, tokens, cost and the validation checks of one pass of `--compare-validation`."""
    usage = None
    try:
        active = runs.active(rid)
        if active is not None:
            usage = runs_usage.for_run({**active, "started_at": started}, ended_at=ended)
    except Exception:  # noqa: BLE001
        pass
    tokens, cost, _ = _summary(usage)
    a, b = runs_report._ts(started), runs_report._ts(ended)
    checks = [{"name": c.get("name"), "decision": c.get("decision"), "rule": c.get("rule")}
              for r in new if isinstance(r.get("validation"), dict) for c in r["validation"].get("checks") or [] if isinstance(c, dict)]
    return {"pass": label, "duration_s": (b - a).total_seconds() if a and b else None, "tokens": tokens, "cost_usd": cost,
            "checks": checks}


def _fix_pass(label: str, rid: str | None, started: str, ended: str, new: list[dict], outcome: str, check: str | None) -> dict:
    """One pass of `fix-rounds` (spec 108): outcome, fix rounds, the fixing agents' (coder, quality) and the whole pass's usage, failed gates."""
    usage = None
    try:
        active = runs.active(rid)
        if active is not None:
            usage = runs_usage.for_run({**active, "started_at": started}, ended_at=ended)
    except Exception:  # noqa: BLE001
        pass
    tokens, cost, _ = _summary(usage)
    roles = [v for k, v in ((usage or {}).get("by_role") or {}).items() if str(k).endswith((":coder", ":quality")) and isinstance(v, dict)]
    fixing = _summary({"totals": {f: sum(int(v.get(f) or 0) for v in roles) for f in ("input", "output", "cache_read", "cache_write")}
                       | {"cost_usd": sum(float(v.get("cost_usd") or 0) for v in roles)}})
    rounds = sum(1 for r in new for a in r.get("agents") or [] if isinstance(a, dict)
                 for e in a.get("events") or [] if isinstance(e, dict) and e.get("kind") == "fix-round")
    gates = sorted({g for r in new if isinstance(r.get("gates"), dict) for g, v in r["gates"].items() if v == "failed"})
    return {"pass": label, "outcome": outcome, "result_check": check, "fix_rounds": rounds,
            "fixing": {"tokens": fixing[0], "cost_usd": fixing[1]}, "total": {"tokens": tokens, "cost_usd": cost}, "gates_failed": gates}


def _summary_verdict(on: dict, off: dict) -> str | None:
    if on["outcome"] != "done":
        return "summaries pass not done"
    if on["gates_failed"]:
        return "gate failed with summaries: " + ", ".join(on["gates_failed"])
    if on["fix_rounds"] > off["fix_rounds"]:
        return f"more fix rounds with summaries ({on['fix_rounds']}) than without ({off['fix_rounds']})"
    return None


def _required_missing(selective: dict) -> list[str]:
    """Checks a rule requires (mandatory categories; lint, typecheck and security always) that the change-aware pass did not run or reuse."""
    return sorted({f"{c['name']} ({c['rule']})" for c in selective["checks"] if c["decision"] == "skipped"
                   and (str(c["rule"]).startswith("mandatory:") or c["name"] in ("lint", "typecheck", "security"))})


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
    ap = argparse.ArgumentParser(prog="cplat platform runs benchmark", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workflow", choices=["quick-task", "build", "ship", "fix-rounds"])
    ap.add_argument("--reset-first", action="store_true", help="put the sample repo back to the pinned revision before starting")
    ap.add_argument("--model", help="coordinator model for the run (sonnet, opus, haiku); else the settings files, else sonnet")
    ap.add_argument("--plugins", metavar="DIR", help="run with the plugins in DIR (this worktree's plugins/) instead of the installed ones")
    ap.add_argument("--compare-validation", action="store_true",
                    help="run the task twice, change-aware validation on and then off (CPLAT_VALIDATION=full), and compare (spec 103)")
    ap.add_argument("--arm", metavar="NAME", help="apply benchmark/arms/NAME.json to the sample repo before the session (spec 107)")
    ap.add_argument("--recall", action="store_true",
                    help="after the session run the full suite in the clone; a failing test fails the record (spec 107)")
    ns = ap.parse_args(argv)
    if ns.workflow == "fix-rounds" and (ns.arm or ns.compare_validation):
        raise PlatformError("benchmark fix-rounds always runs its own two passes (summaries on, then off)",
                            hint="drop --arm and --compare-validation")
    arm = load_arm(ns.arm, ns.workflow) if ns.arm else None
    seed = load_seed(ns.workflow) if ns.workflow == "fix-rounds" else None
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
                            hint=f"cplat platform runs benchmark {ns.workflow} --reset-first")
    clone = runs.state_dir() / "benchmark" / ns.workflow
    try:
        _prepare(url, rev, task, clone, spec=arm is None)
        if arm:
            stage_arm(arm, clone)
        if not trusted(clone):
            raise PlatformError(f"the benchmark folder {clone} is not trusted in Claude Code, so its permission rules would be ignored",
                                hint=f"cd {clone} && claude   (accept the trust dialog, then /exit), and run the benchmark again")
        if main_now != rev:
            reset_sample(repo, rev, clone)
        keep = snapshot(repo, clone)
    except RuntimeError as e:
        raise PlatformError(f"sample repo {repo} could not be prepared: {e}") from None

    plugin_flags, plugin_info = plugin_args(ns.plugins, clone) if ns.plugins else ([], None)
    platform = Path(ns.plugins).resolve().parent if ns.plugins else None   # <checkout>/plugins → <checkout>
    model, _ = settings.coordinator_model(clone, steps(task)[0][1], ns.model)
    model_flags = ["--model", ns.model] if ns.model else []
    rid = runs.start("benchmark", repo=repo, mode="headless")
    if rid:
        runs_usage.register(rid, mode="own", project_dir=str(runs_usage.projects_root() / transcripts.cwd_slug(clone)))
    outcome, reset, note, check = "failed", "not run", None, None
    usage, compare, fix_compare = None, None, None
    try:
        if seed:   # fix-rounds: the seed goes to main like an arm, then the spec commit (none: the seed carries spec 901)
            try:
                stage_arm({"name": "fix-rounds", **seed}, clone)
                push_arm(url, clone)
            except RuntimeError as e:
                raise PlatformError(f"the seed could not be applied to {repo}: {e}") from None
        if arm:   # after every refusal above, so the reset below always removes it; then the spec commit on top of it
            try:
                push_arm(url, clone)
                commit_spec(task, clone)
            except RuntimeError as e:
                raise PlatformError(f"arm {ns.arm} could not be applied to {repo}: {e}") from None

        def one_pass(suffix: str = "") -> tuple[str, str | None]:
            out, why = "failed", None
            for name, prompt in steps(task):   # e.g. build: plan, then build; each its own phase, a failed step stops the run
                runs.phase(rid, f"benchmark:{name}{suffix}")
                out = _run_headless(["--repo", str(clone), "--max-runs", str(task["max_runs"]),
                                     "--max-minutes", str(task["max_minutes"]), *model_flags, *plugin_flags, prompt], rid, platform)
                if out != "done":
                    return out, f"step {name} did not finish"
            missing = result(ns.workflow, repo, keep)
            if missing:
                return "failed", missing
            if ns.recall and out == "done":   # spec 107: the full suite after the session, in every pass
                why = recall_check(clone)
                out = "failed" if why else out
            return out, why

        if seed:
            passes, seen = [], set(_children(rid))
            for label in ("on", "off"):
                if label == "off":   # the sample back to the pinned state; this pass adds the setting that turns the summaries off
                    reset_sample(repo, rev, clone, keep)
                    _prepare(url, rev, task, clone, spec=False)
                    stage_arm({"name": "fix-rounds", "files": {**seed["files"], ".platform-settings.yml": "failure_summary: off\n"}}, clone)
                    push_arm(url, clone)
                started = runs._iso(runs.utcnow())
                out, why = one_pass(f":{label}")
                children = _children(rid)
                new = [children[k] for k in sorted(children) if k not in seen]
                seen |= set(children)
                passes.append(_fix_pass(label, rid, started, runs._iso(runs.utcnow()), new, out, why))
            fix_compare = {"passes": passes, "verdict": _summary_verdict(*passes)}
            outcome, check = ("done", None) if fix_compare["verdict"] is None else ("failed", fix_compare["verdict"])
        elif not ns.compare_validation:
            outcome, check = one_pass()
        else:
            passes, seen = [], set(_children(rid))
            for label, mode in (("selective", None), ("full", "full")):
                if label == "full":   # the sample repo back to the pinned state for the second pass
                    reset_sample(repo, rev, clone, keep)
                    _prepare(url, rev, task, clone, spec=arm is None)
                    if arm:   # the second pass runs with the same arm
                        stage_arm(arm, clone)
                        push_arm(url, clone)
                        commit_spec(task, clone)
                saved = os.environ.get("CPLAT_VALIDATION")
                if mode:
                    os.environ["CPLAT_VALIDATION"] = mode
                else:
                    os.environ.pop("CPLAT_VALIDATION", None)
                started = runs._iso(runs.utcnow())
                try:
                    outcome, check = one_pass(f":{label}")
                finally:
                    if saved is None:
                        os.environ.pop("CPLAT_VALIDATION", None)
                    else:
                        os.environ["CPLAT_VALIDATION"] = saved
                children = _children(rid)
                new = [children[k] for k in sorted(children) if k not in seen]
                seen |= set(children)
                passes.append({**_pass_summary(label, rid, started, runs._iso(runs.utcnow()), new), "outcome": outcome})
                if outcome != "done":
                    break
            compare = {"passes": passes, "required_missing": _required_missing(passes[0]),
                       "recorded": bool(passes[0]["checks"])}
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
            "reset": reset, "reset_note": note, "result_check": check, "arm": ns.arm or "baseline",
            "plugins": plugin_info, "coordinator_model": model,
            **({"validation_compare": compare} if compare else {}),
            **({"summary_compare": fix_compare} if fix_compare else {})}})
    if reset == "failed":
        raise PlatformError(f"reset of sample repo {repo} failed: {note}; the benchmark record was written",
                            hint=f"cplat platform runs benchmark {ns.workflow} --reset-first")
    tokens, cost, prices = _summary(usage)
    print(f"benchmark {ns.workflow} v{task['task_version']} on {repo}@{rev[:7]}: {outcome}, {tokens} tokens, "
          f"est. USD {cost} (prices of {prices}); reset {reset}" + (f"; {check}" if check else ""))
    print(f"plugins {runs_usage_report.plugins_label(plugin_info) if plugin_info else 'installed'}, coordinator {model}")
    if compare:
        for p in compare["passes"]:
            print(f"  validation {p['pass']}: {p['outcome']}, duration {p['duration_s']}s, {p['tokens']} tokens, est. USD {p['cost_usd']}; "
                  + (", ".join(f"{c['name']} {c['decision']} ({c['rule']})" for c in p["checks"]) or "no validation section"))
        if not compare["recorded"]:
            print("  validation: no validation recorded in the change-aware pass")
            return 1
        if compare["required_missing"]:
            print("  validation: required check(s) did not run in the change-aware pass: " + ", ".join(compare["required_missing"]))
            return 1
    if fix_compare:
        for p in fix_compare["passes"]:
            print(f"  summaries {p['pass']}: {p['outcome']}, fix rounds {p['fix_rounds']}, fixing agents {p['fixing']['tokens']} tokens est. "
                  f"USD {p['fixing']['cost_usd']}, total {p['total']['tokens']} tokens est. USD {p['total']['cost_usd']}")
        if fix_compare["verdict"]:
            print(f"  summaries: {fix_compare['verdict']}")
        return 0 if fix_compare["verdict"] is None else 1
    return 0 if outcome == "done" else 1
