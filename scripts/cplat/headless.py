"""`headless`: run a slash command unattended with `claude -p`, and start it again until its ship run is finished (spec 070).

  cplat headless "/component:ship 012"                         run in the current repo until done, escalated or out of runs
  cplat headless "/component:ship 012" --quiet 23:30-07:00     never start a run inside that window (e.g. nightly jobs on the
                                                         same subscription); wait for it to end, or --no-wait to exit
  cplat headless --dry-run "/component:fix ..."            print the claude command

Each run is a fresh `claude -p` session with `--permission-mode acceptEdits` and the repo's committed permission allowlist
(passed as `--settings`, so it applies in a clone Claude Code has not trusted, #588):
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
plan (cplat supervisor.py), saved at checkpoints; independent `parallel_safe` tasks share one batch unit whose session runs
their coders at once (spec 159, `--parallel N`, default 3); the same command again continues at the first unit without one. No session
or time cap applies unless `--max-runs`/`--max-minutes` is given. The legacy loop (other prompts and `/system:ship`) caps at
6 sessions and 240 minutes when they are not given.

Run allowlist (spec 131): for a ship, build or system ship the git, `gh pr create` and land commands of the run's feature
branch are printed and passed to every session as `--allowedTools` (refused rules such as force pushes, pushes to the
default branch and merges as `--disallowedTools`) and in `CPLAT_RUN_ALLOWLIST`; no settings file is written. Before any
session a preflight checks the refused rules against the run's commands (spec 206), the settings layers, git identity, gh login and push access, then (spec 207) folder trust, the subagents' tools, the agent worktree
and the models (one check call each): `preflight failed: <category>: <detail>`,
exit 1, nothing started. For a ship or build, a command the committed plan.md/design.md names as
`NAME=value devbox run <script>` is allowed verbatim (the others are listed as `not allowed: <command>`), and the ship
reads the CI logs cplat saved (spec 184).

Usage limit (spec 184): a session that ends with the usage-limit message (or silent and short) is a pause, not a stop:
`paused: usage limit, resumes at <time>` (or `next try at <time>`, backing off 5, 10, 20, 40, 60 min), then the same
prompt starts again. A pause is no invocation, no stop without progress and no budget minutes. Pauses beyond 360 min
stop the run: `environment pause: usage limit resets at <time>`, exit 1, escalated with cause `environment`.

Slot (spec 184): every run holds one of the repo's `slots` (counted over every worktree and clone of the machine). When
none is free the run starts no session and prints `waiting for a slot: held by <command> (pid, since, checkout)`; it starts
within a minute after the holder ends. `--dry-run` takes no slot.
"""
from __future__ import annotations

import argparse
import contextlib
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
import core
import envprefix
import escalation_rules
import preflight
import run_slot
import runs as runlog
import settings
import loopguard
import ship
import stopgate
import supervisor
import telemetry
import usagelimit
import waitdetach
from core import PlatformError

EXIT_DONE, EXIT_STOPPED, EXIT_QUIET = 0, 1, 3
LOOPED = 125                  # spec 202: the code of a session the loop guard ended
GUARD_POLL = 10               # seconds between two looks of the guard at the session's transcript
WAIT_LIMIT_MIN = 120          # spec 202: a detached wait still running after this long is stopped and escalated
PAUSED_RESULT = "paused at a checkpoint by cplat dispatch"   # spec 167: the dispatcher's stop flag ended the run
STOP_FLAG = "cplat-dispatch-stop"


def clock() -> dt.datetime:   # tests replace this
    return dt.datetime.now()


def sleep(seconds: float) -> None:   # tests replace this
    time.sleep(seconds)


def stop_requested(repo: Path) -> bool:
    """Spec 167 (AC-167.11): `cplat dispatch pause` wrote the stop flag into this checkout's git dir."""
    try:
        gd = core.git_dir(repo)
        return gd is not None and (gd / STOP_FLAG).exists()
    except Exception:   # noqa: BLE001  (a missing flag never stops a run)
        return False


def write_dispatch_result(record: dict) -> None:
    """Spec 167: the result file the dispatcher reads (`CPLAT_DISPATCH_RESULT`); written whole, never raises."""
    path = os.environ.get("CPLAT_DISPATCH_RESULT")
    if not path:
        return
    try:
        target = Path(path)
        tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(record))
        os.replace(tmp, target)
    except OSError:
        pass


def run_tokens(rid: str | None) -> int | None:
    """Input, output and cache tokens of the run's usage so far; None when the usage is not complete (never 0 by guess)."""
    if not rid:
        return None
    try:
        import runs_usage
        rec = runlog.active(rid)
        if rec is None:
            return None
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sec = runs_usage.for_run(rec, ended_at=now, budget_s=3.0, peek=True)
        totals = (sec or {}).get("totals")
        if not totals or (sec or {}).get("incomplete"):
            return None
        return int(sum(float(totals.get(k) or 0) for k in ("input", "output", "cache_read", "cache_write")))
    except Exception:   # noqa: BLE001
        return None


def run_cost(rid: str | None) -> float | None:
    """USD cost of the run's usage so far; None when the usage or the prices are not complete (never 0 by guess)."""
    if not rid:
        return None
    try:
        import runs_usage
        rec = runlog.active(rid)
        if rec is None:
            return None
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sec = runs_usage.for_run(rec, ended_at=now, budget_s=3.0, peek=True)
        totals = (sec or {}).get("totals")
        if not totals or (sec or {}).get("incomplete") or not totals.get("cost_complete") or totals.get("cost_usd") is None:
            return None
        return float(totals["cost_usd"])
    except Exception:   # noqa: BLE001
        return None


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


def repo_rules(repo: Path) -> dict[str, list[str]]:
    """The permission rules of the repo's committed `.claude/settings.json` (the HEAD version, so an uncommitted edit
    grants nothing). Claude Code ignores the file in a folder it has not trusted, such as a system ship's fresh clone
    (#588, spec 162); passed as `--settings` they apply there too, while the file's hooks and other settings stay gated by trust."""
    try:
        text = subprocess.run(["git", "-C", str(repo), "show", "HEAD:.claude/settings.json"],
                              capture_output=True, text=True, check=True).stdout
        perms = json.loads(text).get("permissions") or {}
    except (OSError, subprocess.CalledProcessError, ValueError, AttributeError):
        return {}
    if not isinstance(perms, dict):
        return {}
    return {k: [r for r in v if isinstance(r, str)] for k in ("allow", "deny", "ask")
            if isinstance(v := perms.get(k), list) and v}


KEEP_PLUGINS = ("component", "shared", "svc")   # every shape's ship: the commands, quality/security, PM/architect/reviewer
NO_MCP = ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
# The built-in tools an unattended session and its subagents use (journeys 22 and 23 called nothing else). `--tools`
# bounds the subagents too: a subagent may name a tool in its frontmatter, but a call to one left out is denied. The rest
# of the default set (skills, tool search, cron, monitor, worktrees, …) cost about 12 k tokens on every model call.
# Glob and Grep stay out of the unit sessions: the default set has neither on macOS and Linux (search runs through Bash),
# and naming them adds 1.6 k to every session and subagent. A session that may plan keeps them with the web tools: the
# architect has no Bash, so without them it cannot search the repo (journey 25: each plan unit's Glob and Grep denied).
SESSION_TOOLS = ("Bash", "Read", "Edit", "Write", "Agent", "SendMessage")
PLAN_TOOLS = ("Glob", "Grep", "WebSearch", "WebFetch")


def _enabled_plugins(repo: Path) -> dict[str, bool]:
    """The plugins Claude Code would enable here: the user's settings, then the repo's (later files win)."""
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    out: dict[str, bool] = {}
    for f in (home / "settings.json", repo / ".claude" / "settings.json", repo / ".claude" / "settings.local.json"):
        try:
            data = json.loads(f.read_text()).get("enabledPlugins") or {}
        except (OSError, ValueError, AttributeError):
            continue
        out.update({k: bool(v) for k, v in data.items() if isinstance(k, str)} if isinstance(data, dict) else {})
    return out


def lean(repo: Path, prompt: str) -> tuple[dict[str, bool], list[str]]:
    """#869: an unattended session loads only what its run uses. Every enabled plugin the repo's shape and the command
    do not need is switched off and no MCP server is started: each skill, agent and MCP tool listed costs tokens on
    every model call (37 k of fixed context went down to 28 k in a service repo). `CPLAT_HEADLESS_LEAN=0` keeps all."""
    if os.environ.get("CPLAT_HEADLESS_LEAN") == "0":
        return {}, []
    import shapecmd
    keep = set(KEEP_PLUGINS)
    if m := re.match(r"/([a-z0-9-]+):", prompt):
        keep.add(m.group(1))
    try:
        route = shapecmd.route(repo)
    except Exception:      # an unknown shape: leave the plugins as they are, the session reports the shape itself
        return {}, NO_MCP
    keep |= {route["plugin"], *(a.split(":", 1)[0] for a in route["agents"].values())}
    off = {name: False for name, on in _enabled_plugins(repo).items() if on and name.split("@", 1)[0] not in keep}
    return off, NO_MCP


def session_tools(prompt: str) -> list[str]:
    """The `--tools` of an unattended session: the architect's search and web tools only where it may plan (the `plan`
    unit, or a session that runs the whole command). `CPLAT_HEADLESS_LEAN=0` keeps the default set."""
    if os.environ.get("CPLAT_HEADLESS_LEAN") == "0":
        return []
    unit = m.group(1) if (m := re.search(r"--unit\s+(\S+)", prompt)) else None
    return ["--tools", ",".join([*SESSION_TOOLS, *(PLAN_TOOLS if unit in (None, "plan") else ())])]


def claude_cmd(prompt: str, model: str | None, plugin_dirs: list[str] | None = None,
               allow: list[str] | None = None, deny: list[str] | None = None, add_dirs: list[str] | None = None,
               rules: dict[str, list[str]] | None = None, repo: Path | None = None) -> list[str]:
    exe = os.environ.get("CPLAT_CLAUDE") or "claude"
    cmd = [exe, "-p", prompt, "--permission-mode", "acceptEdits", "--output-format", "text"]
    plugins_off, mcp = lean(repo, prompt) if repo is not None else ({}, [])
    cmd += mcp + (session_tools(prompt) if repo is not None else [])
    for d in add_dirs or []:      # a system ship's clones next to the gitops repo (a session may work only where it may cd)
        cmd += ["--add-dir", d]
    if model:
        cmd += ["--model", model]
    for d in plugin_dirs or []:
        cmd += ["--plugin-dir", d]
    perms = {k: list(v) for k, v in (rules or {}).items()}
    if plugin_dirs:   # plugins loaded in place are not under ~/.claude/plugins, so their files need their own Read rule
        perms.setdefault("allow", []).extend(f"Read(/{d}/**)" for d in plugin_dirs)
    extra = ({"permissions": perms} if perms else {}) | ({"enabledPlugins": plugins_off} if plugins_off else {})
    if extra:
        cmd += ["--settings", json.dumps(extra)]
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


def allowlist_block(allow: list[str], deny: list[str], not_allowed: list[str] | tuple[str, ...] = ()) -> str:
    lines = ["run allowlist (this run's sessions only; no settings file is changed):", *(f"  {r}" for r in allow),
             "refused: " + ", ".join(deny), *(f"not allowed: {c}" for c in not_allowed)]
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


def run_once(cmd: list[str], repo: Path, log: Path, minutes: float, run_id: str | None = None, session_id: str | None = None,
             guard: loopguard.Guard | None = None) -> int:
    session_id = session_id or session_of(cmd)
    session_env = {"CPLAT_SESSION_ID": session_id} if session_id else {}
    prompt = cmd[cmd.index("-p") + 1] if "-p" in cmd[:-1] else ""
    with log.open("a") as fh, telemetry.session(repo, run_id, settings.workflow_of(prompt) or "headless") as otel:
        fh.write(f"\n=== {clock():%Y-%m-%d %H:%M:%S} {shlex.join(cmd)}\n")
        fh.flush()
        try:
            p = subprocess.Popen(cmd, cwd=repo, stdout=fh, stderr=subprocess.STDOUT,
                                 env=telemetry.merge_env({**os.environ, "CPLAT_HEADLESS": "1", **session_env, **({"CPLAT_RUN_PARENT": run_id} if run_id else {})}, otel))
        except FileNotFoundError:
            raise PlatformError(f"`{cmd[0]}` is not installed or not on PATH", hint="install Claude Code, or set CPLAT_CLAUDE") from None
        try:
            return watch(p, minutes, guard)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            fh.write(f"\n=== timed out after {minutes:.0f} min\n")
            return 124
        except BaseException:
            p.kill()
            p.wait()
            raise


def watch(p: subprocess.Popen, minutes: float, guard: loopguard.Guard | None) -> int:
    """Wait for the session; with a guard look at its transcript every GUARD_POLL s and end it on a trip (SIGTERM, SIGKILL after 10 s)."""
    deadline = time.monotonic() + minutes * 60
    if guard is not None:                 # a session that ends within a second has made no loop: no look, no poll interval
        with contextlib.suppress(subprocess.TimeoutExpired):
            return p.wait(timeout=1)
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise subprocess.TimeoutExpired(p.args, minutes * 60)
        if guard is None:
            return p.wait(timeout=left)
        if p.poll() is not None:
            return p.returncode
        if guard.observe(clock()):
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            return LOOPED
        sleep(GUARD_POLL)


def phase_of(repo: Path, command: str, unit: str | None = None) -> str:
    """The phase named in a loop reason: the open ship run's, else the unit's, else the command's last word."""
    st = unfinished(repo)
    if st and st.get("phase"):
        return str(st["phase"])
    return unit or os.environ.get("CPLAT_UNIT") or command.rsplit(":", 1)[-1].strip("/") or "headless"


def make_guard(ns: argparse.Namespace, repo: Path, sid: str, command: str, unit: str | None = None) -> loopguard.Guard:
    calls, minutes = getattr(ns, "guard", None) or loopguard.DEFAULT
    return loopguard.Guard(calls, minutes, repo, sid, lambda: phase_of(repo, command, unit))


def escalate(repo: Path, reason: str, cause: str) -> None:
    """Escalate the open ship run, else the units file."""
    if unfinished(repo) is not None:
        ship.escalate(repo, reason, cause)
    else:
        import units
        units.escalate(repo, reason, cause)


class Waits:
    """Spec 202: before a session, wait while a detached wait of the checkout runs; no model call is made meanwhile."""

    def __init__(self) -> None:
        self.reported: set[str] = set()

    def hold(self, repo: Path, state: dict) -> str | None:
        """None when a session may start, else the result line of the run that stopped it."""
        if running := waitdetach.alive(repo):
            w = running[0]
            try:
                since = f"{dt.datetime.fromisoformat(w.started_at):%H:%M:%S}"
            except ValueError:
                since = w.started_at or "?"
            print(f"waiting for {w.command} (pid {w.pid}, since {since}): no session starts until it ends", flush=True)
        held = waitdetach.hold(repo, limit_min=WAIT_LIMIT_MIN, clock=clock, sleep=sleep)
        if not held.done:
            result = f"wait {held.command} still running after {WAIT_LIMIT_MIN} min"
            escalate(repo, result, "environment")
            state["cause"] = "environment"
            return result
        for e in waitdetach.ended(repo):
            if e.id not in self.reported:
                self.reported.add(e.id)
                print(f"wait {e.command} ended: exit {e.code}" if e.result is not None and e.code is not None
                      else f"wait {e.command} ended without a result", flush=True)
        return None

    @staticmethod
    def looped(repo: Path, guard: loopguard.Guard, state: dict) -> str:
        """A session the guard ended: escalate with cause platform; the reason is the run's result."""
        reason = guard.observe(clock()) or "looping"
        escalate(repo, reason, "platform")
        state["cause"] = "platform"
        return reason


def main(argv: list[str]) -> int:
    with contextlib.ExitStack() as stack:
        try:
            return _main(argv, stack)
        except run_slot.SlotBusy as e:       # spec 184: no run record, no session
            print(e, flush=True)
            return EXIT_STOPPED


def _main(argv: list[str], stack: contextlib.ExitStack) -> int:
    ap = argparse.ArgumentParser(prog="cplat headless", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="+", help="the prompt, usually a slash command such as /component:ship 012")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--max-runs", type=int, default=None, help="sessions in total (default: no cap in unit mode, 6 otherwise)")
    ap.add_argument("--max-minutes", type=float, default=None,
                    help="wall-clock budget for all sessions together, from the first start (default: no cap in unit mode, 240 otherwise)")
    ap.add_argument("--quiet", help="HH:MM-HH:MM: never start a session inside this window")
    ap.add_argument("--no-wait", action="store_true", help="instead of waiting: exit 3 inside the quiet window, exit 1 (`slot busy: held by <command> ...`) when "
                    "every slot of the repo is held (spec 184)")
    ap.add_argument("--model", help="coordinator model: sonnet (default), opus or haiku; else the settings files")
    ap.add_argument("--plugin-dir", action="append", default=[], help="load a plugin from this folder (repeatable)")
    ap.add_argument("--parallel", type=int, default=None, metavar="N",
                    help="unit mode: independent tasks run at once, at most N per batch (default 3; 1 runs one task per session; spec 159)")
    ap.add_argument("--budget", action="append", default=[], metavar="KEY=VALUE",
                    help="replace a limit of the run's budget: minutes, invocations, reruns, cost (a number or off; spec 102)")
    ap.add_argument("--loop-guard", metavar="CALLS/MINUTES", default=None,
                    help="end a session that makes CALLS model calls in MINUTES without progress, and escalate (default 10/5; spec 202)")
    ap.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args(argv)
    ns.guard = loopguard.parse(ns.loop_guard) if ns.loop_guard is not None else loopguard.DEFAULT   # before anything starts
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
    if ns.parallel is not None:                # spec 159: read by units.py in this process and in every session
        if ns.parallel < 1:
            raise PlatformError("--parallel needs at least 1")
        os.environ["CPLAT_PARALLEL_TASKS"] = str(ns.parallel)
    if dirs:                                   # spec 155: a system ship's repo sessions load the same plugins
        os.environ["CPLAT_PLUGIN_DIRS"] = os.pathsep.join(dirs)
    allow = deny = None
    ids: list[str] = []
    not_allowed: list[str] = []
    if covered:
        ids = spec_ids(repo, refs)
        logs = [preflight.ci_log_dir(repo)]
        if command == "/system:ship":
            logs += [preflight.ci_log_dir(Path(c)) for c in system_clones(repo, ids)]
        allow = preflight.run_allowlist(command, preflight.branches_of(command, ids), logs)
        deny = preflight.refused_rules(preflight.default_branch(repo))
        if command in UNIT_COMMANDS and ids:
            extra, not_allowed = envprefix.commands(repo, ids)
            allow += [f"Bash({c})" for c in extra]
    rules = repo_rules(repo)
    cmd = claude_cmd(prompt, model, dirs, allow, deny, system_clones(repo, ids) if command == "/system:ship" else None, rules, repo)
    if ns.dry_run:
        print(shlex.join(cmd))
        if allow is not None:
            print(allowlist_block(allow, deny or [], not_allowed))
        print(f"coordinator: {model} ({source})")
        return 0
    stack.enter_context(run_slot.held(repo, prompt, wait=not ns.no_wait))   # spec 184: before the run record and the ledger
    print(f"coordinator: {model} ({source})", flush=True)
    state_fields = {"coordinator_model": model, "coordinator_model_source": source}
    options = budget.parse_options(ns.budget)
    rid = runlog.start("headless", repo=runlog.repo_slug(repo), mode="headless")
    dispatch_unit = os.environ.get("CPLAT_DISPATCH_UNIT") or None
    dispatch_record = {"unit": dispatch_unit, "run_id": rid, "pid": os.getpid(),
                       "started_at": clock().isoformat(timespec="seconds"), "ended_at": None}
    tokens: int | None = None
    cost: float | None = None
    write_dispatch_result(dispatch_record)
    if dispatch_unit:                  # spec 167: the dispatcher finds a unit's run by this field
        runlog.set_section(rid, "dispatch_unit", dispatch_unit)
        state_fields["dispatch_unit"] = dispatch_unit
    budget.open_root(rid, budget.work_key(repo, budget.spec_refs(prompt), prompt), ships=budget.ships_in(prompt), options=options, repo=repo)
    if line := budget.limits_line(rid):
        print(line, flush=True)
    state = {"sessions": 0, "result": "", "code": EXIT_STOPPED}
    try:
        if allow is not None:
            print(allowlist_block(allow, deny or [], not_allowed), flush=True)
            targets = plan_targets(repo, ids) if command == "/system:ship" else None
            run_ctx = preflight.RunContext(allow=allow, deny=deny or [], plugin_dirs=dirs, model=model, run_id=rid,
                                           add_dirs=system_clones(repo, ids) if command == "/system:ship" else [])
            failure = preflight.check(repo, command, ids, targets, deny=deny, run=run_ctx)
            if failure:
                print(failure.line(), flush=True)
                state.update(result=failure.reason(), code=EXIT_STOPPED)
                return finish(repo, log_dir(repo) / f"{clock():%Y-%m-%d_%H%M%S}.log", failure.reason(), EXIT_STOPPED)
        if unit_mode:
            log = log_dir(repo) / f"{clock():%Y-%m-%d_%H%M%S}.log"
            announced = set(envprefix.commands(repo, ids)[0]) if ids else set()
            session_env = preflight.env(allow or [])

            def make_cmd(p: str) -> list[str]:        # a command the plan names later in the run is allowed from then on
                if ids and allow is not None:
                    for c in envprefix.commands(repo, ids)[0]:
                        if f"Bash({c})" not in allow:
                            allow.append(f"Bash({c})")
                        if c not in announced:
                            announced.add(c)
                            print(f"run allowlist: added {c}", flush=True)
                    session_env.update(preflight.env(allow))      # the session's CPLAT_RUN_ALLOWLIST names the added command too
                return claude_cmd(p, model, dirs, allow, deny, rules=rules, repo=repo)

            return supervisor.drive(repo, command, ids, prompt, make_cmd,
                                    session_env, rid, ns, log, state)
        return _drive(ns, repo, prompt, window, cmd, rid, state, preflight.env(allow) if allow else {})
    except BaseException as e:
        state["result"] = f"error: {e}"
        tokens = run_tokens(rid) if os.environ.get("CPLAT_DISPATCH_RESULT") else None
        cost = run_cost(rid) if os.environ.get("CPLAT_DISPATCH_RESULT") else None
        runlog.finish(rid, "failed", fields={"command": prompt, "sessions": state["sessions"], "stop_reason": "error", **state_fields})
        rid = None
        raise
    finally:
        reason, outcome = stop_of(state["result"], state["code"])
        esc = None
        if rid:
            esc = {"reason": state["result"], "cause": "decision"} if reason == "budget" else None
            if reason == "preflight" or state["result"].startswith("environment pause:"):
                esc = {"reason": state["result"], "cause": "environment"}
            if reason == "escalated" and state["result"].startswith(("no progress", "looping:", "wait ")):   # AC-088.18, AC-126.7, AC-202.3
                esc = {"reason": state["result"], "cause": state.get("cause") or "decision"}
            if os.environ.get("CPLAT_DISPATCH_RESULT"):
                tokens = run_tokens(rid)        # before runlog.finish removes the active record
                cost = run_cost(rid)
            runlog.finish(rid, outcome, escalation=esc, fields={"command": prompt, "sessions": state["sessions"], "stop_reason": reason, **state_fields})
        if os.environ.get("CPLAT_DISPATCH_RESULT"):   # spec 167: tell the dispatcher how the run ended (also after an exception)
            cause = None
            if esc:
                cause = esc["cause"]
            elif reason == "escalated":
                cause = state.get("cause") or escalation_rules.resolve(None, state["result"]).cause
            write_dispatch_result({**dispatch_record, "ended_at": clock().isoformat(timespec="seconds"), "result": state["result"],
                                   "stop_reason": reason, "outcome": outcome, "cause": cause, "code": state["code"], "tokens": tokens, "cost_usd": cost})


def stop_of(result: str, code: int) -> tuple[str, str]:
    """(stop_reason, outcome) of a headless invocation, from its result line (spec 087)."""
    if result == "finished" or result.startswith("shipped"):
        return "done", "done"
    if result.startswith("preflight failed"):
        return "preflight", "escalated"
    if result.startswith("environment pause:"):       # spec 184: the usage limit outlasted the run's pauses
        return "escalated", "escalated"
    if "budget exhausted:" in result:
        return "budget", "escalated"
    if result.startswith(("needs you", "no progress", "looping:")) or (result.startswith("wait ") and "still running after" in result):
        return "escalated", "escalated"
    if result.startswith("stopped after") or "time budget" in result:
        return "out of runs", "failed"
    if "quiet window" in result:
        return "quiet window", "abandoned"
    if result.startswith("paused at a checkpoint"):   # spec 167: the dispatcher's stop flag
        return "paused", "abandoned"
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
    pauser = usagelimit.Pauser()
    waits = Waits()
    while runs < max_runs:
        wait = seconds_left_in_window(window, clock())
        if wait:
            if ns.no_wait:
                result = f"inside the quiet window {ns.quiet}: not started"
                state.update(result=result, code=EXIT_QUIET)
                return finish(repo, log, result, EXIT_QUIET)
            print(f"inside the quiet window {ns.quiet}: waiting {wait / 60:.0f} min", flush=True)
            sleep(wait)
        if stop_requested(repo):                        # spec 167: a pause stops the run before its next session
            state.update(result=PAUSED_RESULT, code=EXIT_STOPPED)
            return finish(repo, log, PAUSED_RESULT, EXIT_STOPPED)
        if stopped := waits.hold(repo, state):          # spec 202: no session while a detached wait runs
            state.update(result=stopped, code=EXIT_STOPPED)
            return finish(repo, log, stopped, EXIT_STOPPED)
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
        started = clock()
        open_before = unfinished(repo)
        key_before = progress_key(repo, open_before) if open_before else None
        guard = make_guard(ns, repo, sid, command_of(prompt))
        try:
            code = run_once(cmd + ["--session-id", sid], repo, log, left, rid, sid, guard=guard)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        waited = bool(waitdetach.alive(repo))           # spec 202: it ended while its wait runs: no limit, no stall
        if code == LOOPED:
            result = waits.looped(repo, guard, state)
            state.update(result=result, code=EXIT_STOPPED)
            return finish(repo, log, result, EXIT_STOPPED)
        st = unfinished(repo)
        ended = describe_end(repo, code) if st is None else ""
        message = last_message(log, before)
        # a silent session that changed something (or a silent exit 0 with no ship run open) did its work: no limit
        quiet_end = not message and (code == 0 and st is None or st is not None and progress_key(repo, st) != key_before)
        hit = None if quiet_end or waited or ended.startswith(("needs you", "shipped")) else \
            usagelimit.detect(message, (clock() - started).total_seconds(), clock())
        if hit is not None:                             # spec 184: a pause is neither a run nor a stop without progress
            usagelimit.record(hit, clock())
            budget.count_invocation(rid, -1)            # also when the pause ends the run: a rerun must not carry it
            pause = pauser.pause(hit, clock())
            if pause.stop:
                result = pause.stop
                state.update(result=result, code=EXIT_STOPPED)
                return finish(repo, log, result, EXIT_STOPPED)
            print(pause.line, flush=True)
            runs -= 1
            sleep(pause.seconds)
            begin += dt.timedelta(seconds=pause.seconds)
            budget.add_pause(rid, pause.seconds / 60)
            continue
        pauser.resumed()
        if st is None:
            result = ended
            break
        key = progress_key(repo, st)
        if waited:                                      # spec 202: waiting is not standing still
            last = None
            print(f"run {runs} ended in phase {st['phase']} (exit {code}) while a wait runs; resuming", flush=True)
            continue
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
