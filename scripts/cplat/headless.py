"""`headless`: run a slash command unattended with `claude -p`, and start it again until its ship run is finished (spec 070).

  cplat headless "/svc:ship 012"                         run in the current repo until done, escalated or out of runs
  cplat headless "/svc:ship 012" --quiet 23:30-07:00     never start a run inside that window (e.g. nightly jobs on the
                                                         same subscription); wait for it to end, or --no-wait to exit
  cplat headless --dry-run "/svc:fix-bug ..."            print the claude command

Each run is a fresh `claude -p` session with `--permission-mode acceptEdits` and the repo's committed permission allowlist:
file edits inside the repo are accepted, any other tool not allowlisted is refused instead of prompting, so nobody has to watch. A run ends when Claude stops, the
time is up, or the context runs out; if `cplat ship` state says the run is unfinished and not escalated, the next run
resumes it from disk (spec status, plan.md `done` flags, the ship state). Logs: ~/.cache/sdlc-foundry/headless/<repo>/.

The coordinator model (spec 100) is always passed as `--model`: the flag, else `coordinator_model` in the repo's
`.platform-settings.yml`, else in ~/.config/sdlc-foundry/settings.yml (see settings.py), else sonnet; only sonnet, opus
and haiku are accepted. `--plugin-dir PATH` (repeatable) loads a plugin from a folder for the sessions.

One budget (spec 102) covers the run and every ship under it: 180 min, 60 invocations, 6 CI reruns and $15 per spec in the
prompt; `--budget KEY=VALUE` (repeatable, a number or `off`) replaces a limit. The next session is not started once a limit
is used up: `budget exhausted: <limit>`, stop reason `budget`, exit 1.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import budget
import runs as runlog
import settings
import ship
import telemetry
from core import PlatformError

EXIT_DONE, EXIT_STOPPED, EXIT_QUIET = 0, 1, 3


def clock() -> dt.datetime:   # tests replace this
    return dt.datetime.now()


def sleep(seconds: float) -> None:   # tests replace this
    time.sleep(seconds)


def parse_window(text: str | None) -> tuple[dt.time, dt.time] | None:
    if not text:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", text)
    if not m:
        raise PlatformError(f"--quiet expects HH:MM-HH:MM, got '{text}'")
    a, b, c, d = map(int, m.groups())
    return dt.time(a, b), dt.time(c, d)


def seconds_left_in_window(window: tuple[dt.time, dt.time] | None, at: dt.datetime) -> float:
    """0 outside the window, else seconds until it ends (windows may wrap midnight)."""
    if not window:
        return 0
    start, end = window
    t = at.time()
    inside = start <= t < end if start <= end else (t >= start or t < end)
    if not inside:
        return 0
    end_at = at.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if end_at <= at:
        end_at += dt.timedelta(days=1)
    return (end_at - at).total_seconds()


def claude_cmd(prompt: str, model: str | None, plugin_dirs: list[str] | None = None) -> list[str]:
    exe = os.environ.get("CPLAT_CLAUDE") or "claude"
    cmd = [exe, "-p", prompt, "--permission-mode", "acceptEdits", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    for d in plugin_dirs or []:
        cmd += ["--plugin-dir", d]
    if plugin_dirs:   # plugins loaded in place are not under ~/.claude/plugins, so their files need their own Read rule
        rules = [f"Read(/{d}/**)" for d in plugin_dirs]
        cmd += ["--settings", json.dumps({"permissions": {"allow": rules}})]
    return cmd


def plugin_dirs_of(paths: list[str]) -> list[str]:
    dirs = [str(Path(p).resolve()) for p in paths]
    for d in dirs:
        if not (Path(d) / ".claude-plugin" / "plugin.json").is_file():
            raise PlatformError(f"--plugin-dir {d} has no .claude-plugin/plugin.json")
    return dirs


def log_dir(repo: Path) -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sdlc-foundry" / "headless" / repo.name
    base.mkdir(parents=True, exist_ok=True)
    return base


def notify(title: str, text: str) -> None:
    """Best effort: macOS notification centre or notify-send; silent where neither exists."""
    try:
        if platform.system() == "Darwin" and shutil.which("osascript"):
            subprocess.run(["osascript", "-e", f'display notification {quote(text)} with title {quote(title)}'],
                           capture_output=True, timeout=10)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title, text], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', "'") + '"'


def unfinished(repo: Path) -> dict | None:
    """The ship run that a next session should resume, if any."""
    try:
        st = ship.load_state(repo)
    except PlatformError:
        return None
    if st and st["phase"] != "done" and not st.get("escalated"):
        return st
    return None


def progress_key(repo: Path, st: dict) -> tuple:
    """What a session can change: phase, HEAD, fix rounds and the rest of the ship state (spec 080)."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    rest = {k: v for k, v in st.items() if k not in {"updated", "blocks"}}
    return st.get("phase"), head, st.get("fix_rounds", 0), repr(sorted(rest.items()))


def run_once(cmd: list[str], repo: Path, log: Path, minutes: float, run_id: str | None = None) -> int:
    prompt = cmd[cmd.index("-p") + 1] if "-p" in cmd[:-1] else ""
    with log.open("a") as fh, telemetry.session(repo, run_id, settings.workflow_of(prompt) or "headless") as otel:
        fh.write(f"\n=== {clock():%Y-%m-%d %H:%M:%S} {shlex.join(cmd)}\n")
        fh.flush()
        try:
            p = subprocess.run(cmd, cwd=repo, stdout=fh, stderr=subprocess.STDOUT, timeout=minutes * 60,
                               env=telemetry.merge_env({**os.environ, "CPLAT_HEADLESS": "1", **({"CPLAT_RUN_PARENT": run_id} if run_id else {})}, otel))
            return p.returncode
        except subprocess.TimeoutExpired:
            fh.write(f"\n=== timed out after {minutes:.0f} min\n")
            return 124
        except FileNotFoundError:
            raise PlatformError(f"`{cmd[0]}` is not installed or not on PATH", hint="install Claude Code, or set CPLAT_CLAUDE") from None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat headless", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="+", help="the prompt, usually a slash command such as /svc:ship 012")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--max-runs", type=int, default=6, help="sessions in total (each resumes the last)")
    ap.add_argument("--max-minutes", type=float, default=240, help="wall-clock budget for all sessions together (from the first start)")
    ap.add_argument("--quiet", help="HH:MM-HH:MM: never start a session inside this window")
    ap.add_argument("--no-wait", action="store_true", help="inside the quiet window: exit (code 3) instead of waiting")
    ap.add_argument("--model", help="coordinator model: sonnet (default), opus or haiku; else the settings files")
    ap.add_argument("--plugin-dir", action="append", default=[], help="load a plugin from this folder (repeatable)")
    ap.add_argument("--budget", action="append", default=[], metavar="KEY=VALUE",
                    help="replace a limit of the run's budget: minutes, invocations, reruns, cost (a number or off; spec 102)")
    ap.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args(argv)
    repo = Path(ns.repo).resolve()
    if not (repo / ".git").exists():
        raise PlatformError(f"{repo} is not a git repository")
    if not (repo / ".claude" / "settings.json").is_file():
        raise PlatformError("no .claude/settings.json: an unattended run needs the repo's committed permission allowlist",
                            hint="/shared:update-service (or cplat adopt) brings it")
    telemetry.reset()
    prompt = " ".join(ns.prompt)
    window = parse_window(ns.quiet)
    model, source = settings.coordinator_model(repo, prompt, ns.model)
    cmd = claude_cmd(prompt, model, plugin_dirs_of(ns.plugin_dir))
    if ns.dry_run:
        print(shlex.join(cmd))
        print(f"coordinator: {model} ({source})")
        return 0
    print(f"coordinator: {model} ({source})", flush=True)
    state_fields = {"coordinator_model": model, "coordinator_model_source": source}
    options = budget.parse_options(ns.budget)
    rid = runlog.start("headless", repo=runlog.repo_slug(repo), mode="headless")
    budget.open_root(rid, budget.work_key(repo, budget.spec_refs(prompt), prompt), ships=budget.ships_in(prompt), options=options, repo=repo)
    if line := budget.limits_line(rid):
        print(line, flush=True)
    state = {"sessions": 0, "result": "", "code": EXIT_STOPPED}
    try:
        return _drive(ns, repo, prompt, window, cmd, rid, state)
    except BaseException as e:
        state["result"] = f"error: {e}"
        runlog.finish(rid, "failed", fields={"command": prompt, "sessions": state["sessions"], "stop_reason": "error", **state_fields})
        rid = None
        raise
    finally:
        if rid:
            reason, outcome = stop_of(state["result"], state["code"])
            esc = {"reason": state["result"], "cause": "decision"} if reason == "budget" else None
            if reason == "escalated" and state["result"].startswith("no progress"):   # AC-088.18
                esc = {"reason": state["result"], "cause": "environment"}
            runlog.finish(rid, outcome, escalation=esc, fields={"command": prompt, "sessions": state["sessions"], "stop_reason": reason, **state_fields})


def stop_of(result: str, code: int) -> tuple[str, str]:
    """(stop_reason, outcome) of a headless invocation, from its result line (spec 087)."""
    if result == "finished" or result.startswith("shipped"):
        return "done", "done"
    if "budget exhausted:" in result:
        return "budget", "escalated"
    if result.startswith("needs you") or result.startswith("no progress"):
        return "escalated", "escalated"
    if result.startswith("stopped after") or "time budget" in result:
        return "out of runs", "failed"
    if "quiet window" in result:
        return "quiet window", "abandoned"
    return "error", "failed"


def _drive(ns: argparse.Namespace, repo: Path, prompt: str, window, cmd: list[str], rid: str | None, state: dict) -> int:
    log = log_dir(repo) / f"{clock():%Y-%m-%d_%H%M%S}.log"
    begin: dt.datetime | None = None    # the budget starts with the first session, not while waiting out a quiet window
    runs, code = 0, 0
    snapped = False                    # spec 102: a stop that already wrote the recovery snapshot
    last: tuple | None = None
    result = "finished"
    while runs < ns.max_runs:
        wait = seconds_left_in_window(window, clock())
        if wait:
            if ns.no_wait:
                result = f"inside the quiet window {ns.quiet}: not started"
                state.update(result=result, code=EXIT_QUIET)
                return finish(repo, log, result, EXIT_QUIET)
            print(f"inside the quiet window {ns.quiet}: waiting {wait / 60:.0f} min", flush=True)
            sleep(wait)
        begin = begin or clock()
        left = ns.max_minutes - (clock() - begin).total_seconds() / 60
        if left <= 1:
            result = f"time budget of {ns.max_minutes:.0f} min used up"
            break
        limit = budget.check(rid, "session")
        if limit:                                       # spec 102: nothing is killed, the next session is not started
            result = budget.stop(rid, limit, "session")
            if (open_ship := unfinished(repo)) is not None:
                ship.budget_stop(repo, open_ship, limit, "session")
            else:
                budget.snapshot(repo, "headless", result, [])
            snapped = True
            break
        budget.count_invocation(rid)
        runs += 1
        state["sessions"] = runs
        print(f"run {runs}/{ns.max_runs}: {prompt}  (log: {log})", flush=True)
        sid = str(uuid.uuid4())
        if rid:
            import runs_usage
            runs_usage.register(rid, mode="own", session=sid)
        code = run_once(cmd + ["--session-id", sid], repo, log, left, rid)
        st = unfinished(repo)
        if st is None:
            result = describe_end(repo, code)
            break
        key = progress_key(repo, st)
        if key == last:
            result = f"no progress: two runs in a row ended in phase {st['phase']} with nothing changed"
            ship.escalate(repo, result, "environment")
            snapped = True
            break
        last = key
        print(f"run {runs} ended in phase {st['phase']} (exit {code}); resuming", flush=True)
    else:
        result = f"stopped after {ns.max_runs} runs, ship run still unfinished"
    ok = result == "finished" or result.startswith("shipped")
    if not snapped and (result.startswith("stopped after") or "time budget" in result):
        budget.snapshot(repo, (unfinished(repo) or {}).get("phase") or "headless", result, [])
    state.update(result=result, code=EXIT_DONE if ok else EXIT_STOPPED)
    return finish(repo, log, result, EXIT_DONE if ok else EXIT_STOPPED)


def describe_end(repo: Path, code: int) -> str:
    try:
        st = ship.load_state(repo)
    except PlatformError:
        st = None
    if st and st.get("escalated"):
        return f"needs you: {st['spec']} escalated in phase {st['phase']}: {st['escalated']}"
    if st and st["phase"] == "done":
        return f"shipped {st['spec']}" + (f" ({st['deployed']} in dev)" if st.get("deployed") else "")
    return "finished" if code == 0 else f"claude exited with {code}"


def finish(repo: Path, log: Path, result: str, code: int) -> int:
    line = f"HEADLESS {repo.name}: {result}"
    with (log.parent / "summary.log").open("a") as fh:
        fh.write(f"{clock():%Y-%m-%d %H:%M} {line}  ({log.name})\n")
    print(line)
    notify(f"{repo.name}: unattended run", result)
    return code
