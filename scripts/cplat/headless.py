"""`headless`: run a slash command unattended with `claude -p`, and start it again until its ship run is finished (spec 070).

  cplat headless "/component:ship 012"                         run in the current repo until done, escalated or out of runs
  cplat headless "/component:ship 012" --quiet 23:30-07:00     never start a run inside that window (e.g. nightly jobs on the
                                                         same subscription); wait for it to end, or --no-wait to exit
  cplat headless --dry-run "/component:fix ..."            print the claude command

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

Unit mode (spec 131): `/component:ship` and `/component:build` with at least one spec run one fresh session per unit of the
plan (cplat supervisor.py), saved at checkpoints; the same command again continues at the first unit without one. No session
or time cap applies unless `--max-runs`/`--max-minutes` is given. The legacy loop (other prompts and `/system:ship`) caps at
6 sessions and 240 minutes when they are not given.

Run allowlist (spec 131): for a ship, build or system ship the git, `gh pr create` and land commands of the run's feature
branch are printed and passed to every session as `--allowedTools` (refused rules such as force pushes, pushes to the
default branch and merges as `--disallowedTools`) and in `CPLAT_RUN_ALLOWLIST`; no settings file is written. Before any
session a preflight checks the settings layers, git identity, gh login and push access: `preflight failed: <category>: <detail>`,
exit 1, nothing started.
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
import preflight
import runs as runlog
import settings
import ship
import stopgate
import supervisor
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


UNIT_COMMANDS = ("/component:ship", "/component:build")
COVERED_COMMANDS = (*UNIT_COMMANDS, "/system:ship")
LEGACY_MAX_RUNS, LEGACY_MAX_MINUTES = 6, 240


def command_of(prompt: str) -> str:
    words = prompt.split()
    return words[0] if words else ""


def claude_cmd(prompt: str, model: str | None, plugin_dirs: list[str] | None = None,
               allow: list[str] | None = None, deny: list[str] | None = None, add_dirs: list[str] | None = None) -> list[str]:
    exe = os.environ.get("CPLAT_CLAUDE") or "claude"
    cmd = [exe, "-p", prompt, "--permission-mode", "acceptEdits", "--output-format", "text"]
    for d in add_dirs or []:      # a system ship's clones next to the gitops repo (a session may work only where it may cd)
        cmd += ["--add-dir", d]
    if model:
        cmd += ["--model", model]
    for d in plugin_dirs or []:
        cmd += ["--plugin-dir", d]
    if plugin_dirs:   # plugins loaded in place are not under ~/.claude/plugins, so their files need their own Read rule
        rules = [f"Read(/{d}/**)" for d in plugin_dirs]
        cmd += ["--settings", json.dumps({"permissions": {"allow": rules}})]
    if allow:
        cmd += ["--allowedTools", *allow]
    if deny:
        cmd += ["--disallowedTools", *deny]
    return cmd


def spec_ids(repo: Path, refs: list[str]) -> list[str]:
    import spec as specmod
    out = []
    for ref in refs:
        try:
            out.append(specmod.find(repo, ref).id)
        except PlatformError:
            out.append(ref)
    return out


def plan_targets(repo: Path, ids: list[str]) -> list[tuple[Path, str]]:
    """(clone, slug) of every repo of the plans of a system ship (design: Targets); clones that do not exist are skipped."""
    import appship_sched as sched
    import appship_state as astate
    out: list[tuple[Path, str]] = []
    for sid in ids:
        for r in astate.plan_repos(repo, sid):
            clone = sched.clone_path(repo, r["id"])
            if clone.is_dir():
                out.append((clone, f"{sched._org(repo)}/{r['id']}"))
    return out


def system_clones(repo: Path, ids: list[str]) -> list[str]:
    """The clone folders of every component repo of a system ship's plans, whether they exist yet or not."""
    import appship_sched as sched
    import appship_state as astate
    return [str(sched.clone_path(repo, r["id"]).absolute()) for sid in ids for r in astate.plan_repos(repo, sid)
            if r.get("shape") != "gitops-app"]


def allowlist_block(allow: list[str], deny: list[str]) -> str:
    lines = ["run allowlist (this run's sessions only; no settings file is changed):", *(f"  {r}" for r in allow),
             "refused: " + ", ".join(deny)]
    return "\n".join(lines)


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
    rest = {k: v for k, v in st.items() if k not in {"updated", "blocks", "owner", "stop_gate"}}
    return st.get("phase"), head, st.get("fix_rounds", 0), repr(sorted(rest.items()))


def session_of(cmd: list[str]) -> str | None:
    return cmd[cmd.index("--session-id") + 1] if "--session-id" in cmd[:-1] else None


def last_message(log: Path, start: int) -> str:
    """The text a session wrote to the log after its `===` header."""
    try:
        with log.open("rb") as fh:
            fh.seek(start)
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("===")).strip()


def run_once(cmd: list[str], repo: Path, log: Path, minutes: float, run_id: str | None = None, session_id: str | None = None) -> int:
    session_id = session_id or session_of(cmd)
    session_env = {"CPLAT_SESSION_ID": session_id} if session_id else {}
    prompt = cmd[cmd.index("-p") + 1] if "-p" in cmd[:-1] else ""
    with log.open("a") as fh, telemetry.session(repo, run_id, settings.workflow_of(prompt) or "headless") as otel:
        fh.write(f"\n=== {clock():%Y-%m-%d %H:%M:%S} {shlex.join(cmd)}\n")
        fh.flush()
        try:
            p = subprocess.run(cmd, cwd=repo, stdout=fh, stderr=subprocess.STDOUT, timeout=minutes * 60,
                               env=telemetry.merge_env({**os.environ, "CPLAT_HEADLESS": "1", **session_env, **({"CPLAT_RUN_PARENT": run_id} if run_id else {})}, otel))
            return p.returncode
        except subprocess.TimeoutExpired:
            fh.write(f"\n=== timed out after {minutes:.0f} min\n")
            return 124
        except FileNotFoundError:
            raise PlatformError(f"`{cmd[0]}` is not installed or not on PATH", hint="install Claude Code, or set CPLAT_CLAUDE") from None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat headless", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="+", help="the prompt, usually a slash command such as /component:ship 012")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--max-runs", type=int, default=None, help="sessions in total (default: no cap in unit mode, 6 otherwise)")
    ap.add_argument("--max-minutes", type=float, default=None,
                    help="wall-clock budget for all sessions together, from the first start (default: no cap in unit mode, 240 otherwise)")
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
    prompt = " ".join(ns.prompt)
    if command_of(prompt) not in COVERED_COMMANDS and not (repo / ".claude" / "settings.json").is_file():
        raise PlatformError("no .claude/settings.json: an unattended run needs the repo's committed permission allowlist",
                            hint="/platform:update (or cplat adopt) brings it")   # covered commands: the preflight (AC-131.11)
    telemetry.reset()
    window = parse_window(ns.quiet)
    model, source = settings.coordinator_model(repo, prompt, ns.model)
    command = command_of(prompt)
    refs = budget.spec_refs(prompt)
    covered = command in COVERED_COMMANDS
    unit_mode = command in UNIT_COMMANDS and bool(refs)
    dirs = plugin_dirs_of(ns.plugin_dir)
    if dirs:                                   # spec 155: a system ship's repo sessions load the same plugins
        os.environ["CPLAT_PLUGIN_DIRS"] = os.pathsep.join(dirs)
    allow = deny = None
    ids: list[str] = []
    if covered:
        ids = spec_ids(repo, refs)
        allow = preflight.run_allowlist(command, preflight.branches_of(command, ids))
        deny = preflight.refused_rules(preflight.default_branch(repo))
    cmd = claude_cmd(prompt, model, dirs, allow, deny, system_clones(repo, ids) if command == "/system:ship" else None)
    if ns.dry_run:
        print(shlex.join(cmd))
        if allow is not None:
            print(allowlist_block(allow, deny or []))
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
        if allow is not None:
            print(allowlist_block(allow, deny or []), flush=True)
            targets = plan_targets(repo, ids) if command == "/system:ship" else None
            failure = preflight.check(repo, command, ids, targets)
            if failure:
                print(failure.line(), flush=True)
                state.update(result=failure.reason(), code=EXIT_STOPPED)
                return finish(repo, log_dir(repo) / f"{clock():%Y-%m-%d_%H%M%S}.log", failure.reason(), EXIT_STOPPED)
        if unit_mode:
            log = log_dir(repo) / f"{clock():%Y-%m-%d_%H%M%S}.log"
            return supervisor.drive(repo, command, ids, prompt, lambda p: claude_cmd(p, model, dirs, allow, deny),
                                    preflight.env(allow or []), rid, ns, log, state)
        return _drive(ns, repo, prompt, window, cmd, rid, state, preflight.env(allow) if allow else {})
    except BaseException as e:
        state["result"] = f"error: {e}"
        runlog.finish(rid, "failed", fields={"command": prompt, "sessions": state["sessions"], "stop_reason": "error", **state_fields})
        rid = None
        raise
    finally:
        if rid:
            reason, outcome = stop_of(state["result"], state["code"])
            esc = {"reason": state["result"], "cause": "decision"} if reason == "budget" else None
            if reason == "preflight":
                esc = {"reason": state["result"], "cause": "environment"}
            if reason == "escalated" and state["result"].startswith("no progress"):   # AC-088.18, AC-126.7
                esc = {"reason": state["result"], "cause": state.get("cause") or "decision"}
            runlog.finish(rid, outcome, escalation=esc, fields={"command": prompt, "sessions": state["sessions"], "stop_reason": reason, **state_fields})


def stop_of(result: str, code: int) -> tuple[str, str]:
    """(stop_reason, outcome) of a headless invocation, from its result line (spec 087)."""
    if result == "finished" or result.startswith("shipped"):
        return "done", "done"
    if result.startswith("preflight failed"):
        return "preflight", "escalated"
    if "budget exhausted:" in result:
        return "budget", "escalated"
    if result.startswith("needs you") or result.startswith("no progress"):
        return "escalated", "escalated"
    if result.startswith("stopped after") or "time budget" in result:
        return "out of runs", "failed"
    if "quiet window" in result:
        return "quiet window", "abandoned"
    return "error", "failed"


def _drive(ns: argparse.Namespace, repo: Path, prompt: str, window, cmd: list[str], rid: str | None, state: dict,
           extra_env: dict[str, str] | None = None) -> int:
    max_runs = ns.max_runs if ns.max_runs is not None else LEGACY_MAX_RUNS
    max_minutes = ns.max_minutes if ns.max_minutes is not None else LEGACY_MAX_MINUTES
    log = log_dir(repo) / f"{clock():%Y-%m-%d_%H%M%S}.log"
    begin: dt.datetime | None = None    # the budget starts with the first session, not while waiting out a quiet window
    runs, code = 0, 0
    snapped = False                    # spec 102: a stop that already wrote the recovery snapshot
    last: tuple | None = None
    result = "finished"
    while runs < max_runs:
        wait = seconds_left_in_window(window, clock())
        if wait:
            if ns.no_wait:
                result = f"inside the quiet window {ns.quiet}: not started"
                state.update(result=result, code=EXIT_QUIET)
                return finish(repo, log, result, EXIT_QUIET)
            print(f"inside the quiet window {ns.quiet}: waiting {wait / 60:.0f} min", flush=True)
            sleep(wait)
        begin = begin or clock()
        left = max_minutes - (clock() - begin).total_seconds() / 60
        if left <= 1:
            result = f"time budget of {max_minutes:.0f} min used up"
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
        print(f"run {runs}/{max_runs}: {prompt}  (log: {log})", flush=True)
        sid = str(uuid.uuid4())
        if rid:
            import runs_usage
            runs_usage.register(rid, mode="own", session=sid)
        before = log.stat().st_size if log.exists() else 0
        saved = {k: os.environ.get(k) for k in extra_env or {}}
        os.environ.update(extra_env or {})
        try:
            code = run_once(cmd + ["--session-id", sid], repo, log, left, rid, sid)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        st = unfinished(repo)
        if st is None:
            result = describe_end(repo, code)
            break
        key = progress_key(repo, st)
        if key == last:
            result = f"no progress: two runs in a row ended in phase {st['phase']} with nothing changed"
            msg = last_message(log, before)
            if excerpt := stopgate.excerpt(msg):
                result += f"; last message: {excerpt}"
            state["cause"] = ship.no_progress_cause(repo, st, msg)
            ship.escalate(repo, result, state["cause"])
            snapped = True
            break
        last = key
        print(f"run {runs} ended in phase {st['phase']} (exit {code}); resuming", flush=True)
    else:
        result = f"stopped after {max_runs} runs, ship run still unfinished"
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
