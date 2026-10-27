"""Console actions (spec 122): run a confirmed command through `cplat headless`, track it, lock its object, stop and persist it.

Nothing runs without an explicit `start` call; the confirmation is the HTTP request of the confirm button. The console never
writes to a repo or a cluster itself: every change is a slash command run by `cplat headless` in the repo's local clone. The
only direct command is `gh repo clone` (the system switcher).
State: ${XDG_STATE_HOME:-~/.local/state}/sdlc-foundry/console/actions.json, logs in `.../console/actions/<id>.log`."""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import yaml

CPLAT = Path(__file__).resolve().parents[1] / "cplat.py"
TAIL_LINES = 20
KILL_AFTER = 10.0
_KUBE = "kube" + "ctl"
_PR_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
_RUN_RE = re.compile(r"\b\d{8}T\d{6}Z-[0-9a-f]{8}\b")
_PRIVATE = ("_argv", "_key", "_pid", "_retried")
SINGLE_SESSION = {"approve", "request-changes", "answer", "promote", "amend", "fix", "make-spec", "dismiss", "cut-release",
                  "describe", "model", "pause", "resume", "undo", "review-approve"}
REPO_LEVEL = {"describe", "model", "clone"}


class Conflict(Exception):
    """Another action on the same object is running (HTTP 409)."""


class Missing(Exception):
    """A prerequisite is missing (HTTP 412); `needs` names it."""

    def __init__(self, needs: str):
        super().__init__(f"missing prerequisite: {needs}")
        self.needs = needs


def now() -> dt.datetime:   # tests replace this
    return dt.datetime.now(dt.timezone.utc)


def _stamp() -> str:
    return now().strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- paths ----------------

def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "sdlc-foundry" / "console"


def workspace() -> Path:
    """The folder with the local clones: `workspace` of the personal settings, default ~/src."""
    path = Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")) / "sdlc-foundry" / "settings.yml"
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    value = data.get("workspace") if isinstance(data, dict) else None
    return Path(str(value)).expanduser() if value else Path.home() / "src"


def clone_of(repo: str) -> Path:
    return workspace() / repo.split("/")[-1]


# ---------------- commands ----------------

# What may flow from a request into a command: values become one argv element each (no shell), and each is checked
# against a fixed pattern so a value can never be read as an option or a second command.
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
VERSION = re.compile(r"^v?[0-9A-Za-z][0-9A-Za-z._-]{0,62}$")
NUMBER = re.compile(r"^[0-9]{1,6}(\.[0-9]{1,2})?$")
EVENT = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,40}-[0-9a-f]{8}$")
PR_NUMBER = re.compile(r"^[0-9]{1,6}$")
LIMITS = ("minutes", "invocations", "reruns", "cost")
MODEL_COMMANDS = ("/component:add ", "/component:set ", "/component:remove ", "/resource:add ", "/resource:remove ",
                  "/system:set ", "/system:new ", "/system:autonomy set ")
MAX_TEXT = 2000


def _match(pattern: re.Pattern, value: object, what: str) -> str:
    text = str(value or "")
    if not pattern.match(text):
        raise ValueError(f"invalid {what}: {text[:60]!r}")
    return text


def _spec_no(obj: dict) -> str:
    spec = str(obj.get("spec") or "")
    if not spec:
        raise ValueError("the object names no spec")
    return _match(re.compile(r"^[0-9]{1,4}$"), spec.split("-", 1)[0], "spec number")


def _need(args: dict, key: str) -> str:
    """A free-text argument: one line, no control characters, at most MAX_TEXT characters."""
    value = " ".join(str(args.get(key) or "").split())
    if not value:
        raise ValueError(f"missing {key}")
    if len(value) > MAX_TEXT or any(ord(c) < 32 for c in value):
        raise ValueError(f"invalid {key}")
    return value


def _slash(kind: str, obj: dict, args: dict) -> tuple[str, list[str]]:
    """The prompt and the extra headless flags of one action kind."""
    level = args.get("level") or "component"
    if level not in ("component", "system", "decide"):
        raise ValueError(f"unknown level {level!r}")
    if kind == "approve":
        return f"/{level}:spec approve {_spec_no(obj)}", []
    if kind == "approve-ship":
        n = _spec_no(obj)
        return f"/{level}:spec approve {n} and then /{level}:ship {n}", ["--budget", f"cost={_match(NUMBER, args.get('budget'), 'budget')}"]
    if kind == "request-changes":
        return f"/{level}:spec --amend {_spec_no(obj)} {_need(args, 'comment')}", []
    if kind == "answer":
        return f"/{level}:spec --amend {_spec_no(obj)} answers to open questions: {_need(args, 'answers')}", []
    if kind == "promote":
        return (f"/instance:promote {_match(NAME, obj['component'], 'component')} --to {_match(NAME, args.get('to'), 'environment')}"
                f" --version {_match(VERSION, obj['version'], 'version')}", [])
    if kind == "more-budget":
        limit = str(args.get("limit") or "")
        if limit not in LIMITS:
            raise ValueError(f"invalid limit: {limit[:20]!r}")
        return f"/{level}:ship {_spec_no(obj)}", ["--budget", f"{limit}={_match(NUMBER, args.get('value'), 'budget value')}"]
    if kind == "amend":
        return f"/{level}:spec --amend {_spec_no(obj)} {_need(args, 'text')}", []
    if kind == "fix":
        return f"/component:fix #{_match(NUMBER, obj['issue'], 'issue')}", []
    if kind == "make-spec":
        return f"/component:spec #{_match(NUMBER, obj['issue'], 'issue')}", []
    if kind == "dismiss":
        return (f"/issue:triage {_match(NUMBER, obj['issue'], 'issue')} dismiss as wontfix: {_need(args, 'reason')} (confirmed by the user in the console)", [])
    if kind == "cut-release":
        return "/component:release", []
    if kind == "describe":
        text = _need(args, "text")
        return (f"Let Claude decide: {text}" if level == "decide" else f"/{level}:spec {text}"), []
    if kind in ("pause", "resume"):
        return f"/system:autonomy {kind}", []
    if kind == "undo":
        return f"/system:autonomy undo {_match(EVENT, obj.get('event'), 'event')}", []
    if kind == "review-approve":
        return (f"/system:autonomy approve {_match(REPO, obj.get('pr_repo'), 'pr_repo')}#{_match(PR_NUMBER, obj.get('pr'), 'pr')}", [])
    if kind == "model":
        command = _need(args, "command")
        if not command.startswith(MODEL_COMMANDS):
            raise ValueError("a model action runs only /component:add|set|remove, /resource:add|remove, /system:set, /system:new "
                             "or /system:autonomy set")
        return command, []
    raise ValueError(f"unknown action kind {kind!r}")


def command_for(kind: str, obj: dict, args: dict) -> tuple[list[str], str, str]:
    """`(argv, display, repo)` of one action. Raises ValueError for an unknown kind or missing arguments."""
    repo = str(obj.get("repo") or "")
    if "/" not in repo:
        raise ValueError("the object names no repository")
    repo = _match(REPO, repo, "repository")
    clone = clone_of(repo)
    if kind == "clone":
        argv = ["gh", "repo", "clone", repo, str(clone)]
        return argv, shlex.join(argv), repo
    try:
        prompt, extra = _slash(kind, obj, args)
    except KeyError as e:
        raise ValueError(f"the object lacks {e.args[0]}") from None
    flags = ["--repo", str(clone)] + (["--max-runs", "1"] if kind in SINGLE_SESSION else []) + extra
    argv = [sys.executable, str(CPLAT), "headless", prompt, *flags]
    display = "cplat headless " + shlex.quote(prompt) + "".join(f" {shlex.quote(x)}" for x in extra)
    return argv, display, repo


def prerequisites(kind: str, obj: dict, env: dict, args: dict | None = None) -> list[str]:
    """What is missing for this action: `claude`, `gh`, `kube:<env>`, `clone:<repo>`."""
    path = env.get("PATH", "")
    missing: list[str] = []
    if kind != "clone":
        claude = env.get("CPLAT_CLAUDE")
        if not (claude and Path(claude).is_file()) and not shutil.which("claude", path=path):
            missing.append("claude")
    if not _gh_logged_in(env):
        missing.append("gh")
    if kind == "promote":
        target = (args or {}).get("to") or "prod"
        if not shutil.which(_KUBE, path=path):
            missing.append(f"kube:{target}")
    repo = str(obj.get("repo") or "")
    if kind != "clone" and "/" in repo and not (clone_of(repo) / ".claude" / "settings.json").is_file():
        missing.append(f"clone:{repo}")
    return missing


def _gh_logged_in(env: dict) -> bool:
    gh = shutil.which("gh", path=env.get("PATH", ""))
    if not gh:
        return False
    try:
        return subprocess.run([gh, "auth", "status"], env=env, capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ---------------- state ----------------

_lock = threading.RLock()
_actions: dict[str, dict] = {}
_procs: dict[str, subprocess.Popen] = {}
_loaded: Path | None = None


def _file() -> Path:
    return state_dir() / "actions.json"


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def load() -> None:
    """Read actions.json; an entry still `running` whose process is gone becomes `stopped`."""
    global _loaded
    with _lock:
        try:
            rows = json.loads(_file().read_text())
        except (OSError, ValueError):
            rows = []
        _actions.clear()
        changed = False
        for a in rows if isinstance(rows, list) else []:
            if a.get("state") == "running" and a["id"] not in _procs and not _alive(a.get("_pid")):
                a.update(state="stopped", ended_at=_stamp(), reason="the console stopped while it ran")
                changed = True
            _actions[a["id"]] = a
        _loaded = _file()
        if changed:
            _save()


def _ensure() -> None:
    if _loaded != _file():
        load()


def _save() -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(list(_actions.values()), indent=1))
    tmp.replace(path)


def _public(a: dict) -> dict:
    return {k: v for k, v in a.items() if k not in _PRIVATE}


def _lock_key(kind: str, obj: dict, args: dict) -> str:
    if kind in REPO_LEVEL:
        return json.dumps([kind, obj.get("repo"), args], sort_keys=True)
    ident = {k: obj.get(k) for k in ("repo", "spec", "run_id", "issue", "component", "version", "event", "pr_repo", "pr")}
    return json.dumps(ident, sort_keys=True)


def list_actions() -> list[dict]:
    with _lock:
        _ensure()
        return [_public(a) for a in _actions.values()]


def get(action_id: str) -> dict | None:
    with _lock:
        _ensure()
        a = _actions.get(action_id)
        return _public(a) if a else None


def running() -> list[dict]:
    return [a for a in list_actions() if a["state"] == "running"]


def active_for(obj: dict) -> dict | None:
    """The running action that locks this object, if any (the panels disable its other actions)."""
    key = _lock_key("", obj, {})
    with _lock:
        _ensure()
        return next((_public(a) for a in _actions.values()
                     if a["state"] == "running" and a["_key"] == key and a["kind"] not in REPO_LEVEL), None)


def summary() -> dict:
    with _lock:
        _ensure()
        return {"running": sum(a["state"] == "running" for a in _actions.values()),
                "failed": sum(a["state"] == "failed" and not a.get("_retried") for a in _actions.values())}


# ---------------- running ----------------

def start(kind: str, obj: dict, args: dict, env: dict | None = None) -> str:
    """Run one confirmed action in the background and return its id.

    Raises ValueError (400), Missing (412) or Conflict (409)."""
    argv, display, repo = command_for(kind, obj, args)
    missing = prerequisites(kind, obj, env if env is not None else dict(os.environ), args)
    if missing:
        raise Missing(missing[0])
    return _launch(kind, obj, args, argv, display, repo)


def retry(action_id: str, env: dict | None = None) -> str:
    """Start the same command again as a new action."""
    with _lock:
        _ensure()
        old = _actions.get(action_id)
        if old is None:
            raise KeyError(action_id)
        old_copy = dict(old)
    missing = prerequisites(old_copy["kind"], old_copy["object"], env if env is not None else dict(os.environ), old_copy.get("args"))
    if missing:
        raise Missing(missing[0])
    new_id = _launch(old_copy["kind"], old_copy["object"], old_copy.get("args") or {}, old_copy["_argv"], old_copy["command"], old_copy["repo"])
    with _lock:
        old["_retried"] = True
        _save()
    return new_id


def _launch(kind: str, obj: dict, args: dict, argv: list[str], display: str, repo: str) -> str:
    key = _lock_key(kind, obj, args)
    with _lock:
        _ensure()
        if any(a["state"] == "running" and a["_key"] == key for a in _actions.values()):
            raise Conflict("another action on this object is running")
        action_id = uuid.uuid4().hex[:12]
        log = state_dir() / "actions" / f"{action_id}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                errors="replace", start_new_session=True, env=dict(os.environ))
        _procs[action_id] = proc
        _actions[action_id] = {"id": action_id, "kind": kind, "object": obj, "args": args, "command": display, "repo": repo,
                               "started_at": _stamp(), "ended_at": None, "state": "running", "step": "", "tail": [],
                               "links": {"run": None, "pr": None}, "reason": None, "log": str(log),
                               "_argv": argv, "_key": key, "_pid": proc.pid}
        _save()
    threading.Thread(target=_watch, args=(action_id, proc, log), daemon=True).start()
    return action_id


def _watch(action_id: str, proc: subprocess.Popen, log: Path) -> None:
    tail: collections.deque[str] = collections.deque(maxlen=TAIL_LINES)
    step, phase_seen = "", False
    links: dict[str, str | None] = {"run": None, "pr": None}
    with log.open("a") as fh:
        for raw in proc.stdout or []:
            fh.write(raw)
            fh.flush()
            line = raw.rstrip("\n")
            tail.append(line)
            if line.strip():
                if line.startswith("=== "):
                    step, phase_seen = line.strip("= ").strip() or line, True
                elif not phase_seen:
                    step = line.strip()
            links["pr"] = (_PR_RE.findall(line) or [links["pr"]])[-1]
            links["run"] = (_RUN_RE.findall(line) or [links["run"]])[-1]
            with _lock:
                a = _actions.get(action_id)
                if a:
                    a.update(step=step, tail=list(tail), links=dict(links))
    code = proc.wait()
    with _lock:
        _procs.pop(action_id, None)
        a = _actions.get(action_id)
        if a is None:
            return
        a.update(tail=list(tail), links=dict(links))
        if a["state"] == "running":
            a["ended_at"] = _stamp()
            if code == 0:
                a["state"] = "done"
            else:
                last = next((x for x in reversed(tail) if x.strip()), "")
                a.update(state="failed", reason=f"exit code {code}" + (f": {last.strip()[:200]}" if last else ""))
        _save()


# ---------------- stopping ----------------

def stop_all() -> list[str]:
    """Stop every running action (SIGTERM to its process group, SIGKILL after 10 s) and mark it `stopped`."""
    with _lock:
        _ensure()
        victims = [(a["id"], a["_pid"]) for a in _actions.values() if a["state"] == "running"]
        for aid, _ in victims:
            _actions[aid].update(state="stopped", ended_at=_stamp(), reason="stopped from the console")
        _save()
    for _, pid in victims:
        _signal_group(pid, signal.SIGTERM)
    deadline = time.monotonic() + KILL_AFTER
    while time.monotonic() < deadline and any(_alive_child(aid, pid) for aid, pid in victims):
        time.sleep(0.05)
    for aid, pid in victims:
        if _alive_child(aid, pid):
            _signal_group(pid, signal.SIGKILL)
    return [aid for aid, _ in victims]


def _alive_child(action_id: str, pid: int) -> bool:
    proc = _procs.get(action_id)
    return proc.poll() is None if proc is not None else _alive(pid)


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError):
        pass
