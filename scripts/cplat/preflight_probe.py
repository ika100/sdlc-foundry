"""Probes that touch the machine rather than read settings (spec 207): a throwaway agent worktree where Claude Code creates
them, and one minimal model call per distinct model, cached for 60 minutes. Never writes a settings file or the Claude config."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import core
import preflight_trust
import runs

CACHE_MINUTES = 60
CALL_TIMEOUT = 120
FINGERPRINT_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
                    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CONFIG_DIR")
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


# ---------------- AC-207.4: the agent worktree probe ----------------

def worktree_location(repo: Path) -> Path:
    """Where Claude Code creates agent worktrees."""
    return repo / ".claude" / "worktrees"


def _git(repo: Path, *args: str):
    return core.run(["git", "-C", str(repo), *args], check=False)


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def check_worktree(repo: Path, add_dirs: list[str]) -> str | None:
    """Create one worktree at the agent location, check it lies where the session may work, and remove it again."""
    loc = worktree_location(repo)
    created_loc = not loc.exists()
    path = loc / f"cplat-preflight-{os.getpid()}"
    outside = False
    real = path
    try:
        done = _git(repo, "worktree", "add", "--detach", str(path), "HEAD")
        if done.returncode != 0:
            return (f"cannot create an agent worktree at {path} ({_last_line(done.stderr) or _last_line(done.stdout)}): "
                    f"run git worktree prune in {repo}, then run again")
        real = path.resolve()
        allowed = [repo.resolve(), *(Path(d).resolve() for d in add_dirs)]
        outside = not any(real.is_relative_to(a) for a in allowed)
    finally:
        _git(repo, "worktree", "remove", "--force", str(path))
        _git(repo, "worktree", "prune")
        if created_loc:
            try:
                loc.rmdir()
            except OSError:
                pass
    if outside:
        folders = ", ".join([str(repo), *add_dirs])
        return (f"agent worktrees go to {real}, outside the folders the session may work in ({folders}): "
                f"make {repo}/.claude/worktrees a plain folder inside the repo")
    return None


# ---------------- AC-207.6: one model call per distinct model ----------------

@dataclass
class CallResult:
    ok: bool
    error: str                  # last line of the error, "" when ok
    offline: bool               # the error reads like a dropped network
    usage: dict                 # input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens, cost_usd


def _usage(data: object) -> dict:
    data = data if isinstance(data, dict) else {}
    used = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    out: dict = {k: int(used.get(k) or 0) for k in USAGE_KEYS}
    out["cost_usd"] = float(data.get("total_cost_usd") or 0.0)
    return out


def model_call(model: str) -> CallResult:
    """One minimal `claude -p` call in a clean temporary folder, outside the run's session."""
    argv = [os.environ.get("CPLAT_CLAUDE") or "claude", "-p", "Reply with the single word ok.", "--model", model,
            "--output-format", "json", "--max-turns", "1"]
    cwd = tempfile.mkdtemp(prefix="cplat-preflight-")
    try:
        proc = subprocess.run(argv, cwd=cwd, env=core.repo_env(), text=True, capture_output=True, timeout=CALL_TIMEOUT)
    except FileNotFoundError:
        return CallResult(False, "`claude` is not installed or not on PATH", False, _usage(None))
    except subprocess.TimeoutExpired:
        return CallResult(False, f"timed out after {CALL_TIMEOUT} s", False, _usage(None))
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        data = None
    ok = proc.returncode == 0 and not (isinstance(data, dict) and data.get("is_error") is True)
    said = f"{proc.stderr or ''}\n{proc.stdout or ''}"
    if ok:
        return CallResult(True, "", False, _usage(data))
    error = (_last_line(proc.stderr) or _last_line(str(data.get("result") or "") if isinstance(data, dict) else "")
             or f"claude exited {proc.returncode}")
    offline = bool(core.NETWORK_DOWN.search(said) or core.NETWORK_FLAKY.search(said))
    return CallResult(False, error, offline, _usage(data))


REAL_MODEL_CALL = model_call        # tests replace model_call; this keeps the original


def _cache_file() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path(os.environ.get("HOME") or Path.home()) / ".cache")
    return Path(base) / "sdlc-foundry" / "preflight" / "models.json"


def _fingerprint() -> str:
    parts = [os.environ.get(k, "") for k in FINGERPRINT_VARS]
    try:
        account = json.loads(preflight_trust.config_file().read_text()).get("oauthAccount", {}).get("accountUuid", "")
    except (OSError, ValueError, AttributeError):
        account = ""
    parts.append(account if isinstance(account, str) else "")
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _key(model: str) -> str:
    return hashlib.sha256(f"{model}\0{_fingerprint()}".encode()).hexdigest()


def _read_cache() -> dict[str, datetime.datetime]:
    """The passes of the last CACHE_MINUTES minutes, `{key: time}`."""
    try:
        raw = json.loads(_cache_file().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    limit = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=CACHE_MINUTES)
    fresh: dict[str, datetime.datetime] = {}
    for key, stamp in raw.items():
        try:
            when = datetime.datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is not None and when > limit:
            fresh[key] = when
    return fresh


def _write_cache(entries: dict[str, datetime.datetime]) -> None:
    f = _cache_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({k: v.isoformat() for k, v in entries.items()}))
        os.replace(tmp, f)
    except OSError:
        pass                    # a cache that cannot be written only costs the next run one more call


def _call_with_retry(model: str) -> CallResult:
    """Call the model; a dropped network is retried as `core.run` retries it."""
    waited, backoff = 0.0, 10.0
    while True:
        result = globals()["model_call"](model)
        if result.ok or not result.offline or waited + backoff > core.NETWORK_RETRY_MAX_WAIT:
            return result
        core.sleep(backoff)
        waited += backoff
        backoff = min(backoff * 2, 60.0)


def check_models(models: dict[str, list[str]], run_id: str | None) -> str | None:
    """One call per model that has no pass from the last hour; the failure detail, or None. Logs each model under `preflight`."""
    cache = _read_cache()
    log: list[dict] = []
    failure: str | None = None
    for model, agents in models.items():
        key = _key(model)
        if key in cache:
            log.append({"model": model, "cached": True, **_usage(None)})
            continue
        result = _call_with_retry(model)
        log.append({"model": model, "cached": False, **_usage({"usage": result.usage, "total_cost_usd": result.usage.get("cost_usd")})})
        if result.ok:
            cache[key] = datetime.datetime.now(datetime.timezone.utc)
            _write_cache(cache)
            continue
        if result.offline:
            failure = f"could not reach the model API ({result.error}): check the network, then run again"
        else:
            failure = (f"{model} (used by {', '.join(agents)}) cannot be called ({result.error}): "
                       "run claude /login, or set a model the account may use")
        break
    runs.set_section(run_id, "preflight", {"model_calls": log})
    return failure
