"""Shared helpers for platform.py: process execution, errors, registry access, versions, reporting."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT / "scripts"))
import shapes as registry  # noqa: E402  (scripts/shapes.py: the shape registry loader and validators)

# The platform's own checkout is always the template source: commands run the script from a clone at the wanted ref.


class PlatformError(Exception):
    """A user-facing failure. `hint` says how to fix it."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


RATE_LIMITED = re.compile(r"API rate limit (?:already )?exceeded|secondary rate limit", re.I)
RATE_LIMIT_MAX_WAIT = 65 * 60   # seconds a single call may wait for GitHub's limits in total (spec 137)
sleep = time.sleep              # tests replace these two
now = time.time
# A `git push` that GitHub refuses on its own side (#500): `fatal error in commit_refs_rules`, a 5xx, a dropped connection. The
# push changed nothing, so cplat backs off and pushes again for up to PUSH_RETRY_MAX_WAIT before it fails.
PUSH_TRANSIENT = re.compile(
    r"fatal error in commit_refs_rules|internal server error|bad gateway|service unavailable|gateway time-?out"
    r"|returned error: 5\d\d|HTTP 5\d\d|RPC failed|remote end hung up unexpectedly|early EOF|unexpected disconnect"
    r"|could not resolve host|connection (?:reset|refused|timed out)|operation timed out|failed to connect"
    r"|TLS handshake timeout|SSL_ERROR_SYSCALL|gnutls_handshake|kex_exchange_identification", re.I)
PUSH_RETRY_MAX_WAIT = 8 * 60    # seconds a push may wait in total for GitHub to accept it again
# A dropped network (spec 148, #539 #543): the request never reached GitHub (`dial tcp … network is down`, no DNS, refused),
# so any `gh` call and any networked git command may simply run again. An error after the request was sent (a reset, a
# timeout, a 5xx) is retried only for a call that is safe to repeat: a read, or a write that sets a state (`pr ready`, PUT).
NETWORK_DOWN = re.compile(
    r"dial tcp|network is (?:down|unreachable)|no such host|could not resolve host|temporary failure in name resolution"
    r"|connection refused|TLS handshake timeout|no route to host|failed to connect", re.I)
NETWORK_FLAKY = re.compile(
    r"connection reset|i/o timeout|unexpected EOF|operation timed out|context deadline exceeded|HTTP 5\d\d|\b50[234]\b"
    r"|bad gateway|service unavailable|gateway time-?out|something went wrong|remote end hung up unexpectedly|early EOF", re.I)
NETWORK_RETRY_MAX_WAIT = 5 * 60   # seconds one call may wait in total for the network to come back
_GIT_NETWORK = ("fetch", "pull", "ls-remote", "clone")   # push has its own rule (PUSH_TRANSIENT)
_GH_SAFE = ("view", "list", "status", "checks", "diff", "ready", "edit", "download")
_GH_FIELDS = ("-f", "-F", "--field", "--raw-field", "--input")


def _is_push(cmd: list[str]) -> bool:
    """`git push …`, also with global options before the subcommand (`git -C dir push`)."""
    if not cmd or Path(str(cmd[0])).name != "git":
        return False
    rest, i = cmd[1:], 0
    while i < len(rest) and str(rest[i]).startswith("-"):
        i += 2 if rest[i] in ("-C", "-c") else 1
    return i < len(rest) and rest[i] == "push"


def _subcommand(cmd: list[str]) -> list[str]:
    """The words after the program and its global options (`git -C dir fetch` → ["fetch", …])."""
    rest, i = [str(c) for c in cmd[1:]], 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 2 if rest[i] in ("-C", "-c", "-R", "--repo") else 1
    return rest[i:]


def _gh_safe(words: list[str]) -> bool:
    """A `gh` call that may run twice: a read, `pr ready`, `repo edit`, or `gh api` as GET or PUT."""
    if not words:
        return False
    if words[0] == "api":
        method = next((words[k + 1] for k, w in enumerate(words[:-1]) if w in ("-X", "--method")), None)
        if method is None:              # gh api sends a POST once a field is given
            return not any(w in _GH_FIELDS for w in words)
        return method.upper() in ("GET", "PUT")
    return words[0] in ("auth", "search") or (len(words) > 1 and words[1] in _GH_SAFE)


def network_retry(cmd: list[str], said: str) -> str | None:
    """The network error that makes a failed `cmd` worth running again (spec 148), or None."""
    if not cmd:
        return None
    prog, words = Path(str(cmd[0])).name, _subcommand(cmd)
    if prog == "git" and words and words[0] in _GIT_NETWORK:
        hit = NETWORK_DOWN.search(said) or NETWORK_FLAKY.search(said)
    elif prog == "gh":
        hit = NETWORK_DOWN.search(said) or (NETWORK_FLAKY.search(said) if _gh_safe(words) else None)
    else:
        return None
    return hit.group(0) if hit else None


def _rate_limit_kind(text: str) -> str:
    low = text.lower()
    return "secondary" if "secondary rate limit" in low else "graphql" if "graphql" in low else "core"


def _rate_limit_wait(kind: str) -> float | None:
    """Seconds until GitHub resets the named limit, plus 30 s; None when unknown or already past (spec 137)."""
    if kind == "secondary":
        return None
    try:
        out = subprocess.run(["gh", "api", "rate_limit", "--jq", f".resources.{kind}.reset"], text=True, capture_output=True,
                             timeout=30).stdout.strip()
        wait = int(out) - now() + 30
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return wait if wait > 30 else None


def _journey_wait(seconds: float, kind: str) -> None:
    """Spec 136 (AC-136.3): a rate-limit wait is an external wait of the open journey, if any. Never raises, never prints."""
    try:
        import runs_journey
        runs_journey.note_external_wait(seconds, kind)
    except Exception:  # noqa: BLE001
        pass


def run(cmd: list[str], *, cwd: Path | str | None = None, check: bool = True, capture: bool = True,
        env: dict[str, str] | None = None, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command; raise PlatformError with the command's stderr when it fails and `check` is set. A `gh` call that GitHub
    refuses for its rate limit waits for the reset and runs again (spec 137, #409); a `git push` the remote refuses for a
    transient reason backs off and pushes again for up to PUSH_RETRY_MAX_WAIT (#500); a `gh` or networked git call that
    failed on a dropped network runs again for up to NETWORK_RETRY_MAX_WAIT (spec 148)."""
    full_env = {**os.environ, **(env or {})}
    waited, backoff = 0.0, 60.0
    pushed, push_backoff = 0.0, 15.0
    offline, net_backoff = 0.0, 10.0
    while True:
        try:
            proc = subprocess.run(cmd, cwd=cwd, env=full_env, text=True, capture_output=capture, timeout=timeout)
        except FileNotFoundError:
            raise PlatformError(f"`{cmd[0]}` is not installed or not on PATH", hint=install_hint(cmd[0])) from None
        except subprocess.TimeoutExpired:
            raise PlatformError(f"`{' '.join(cmd[:3])}` timed out after {timeout}s") from None
        said = f"{proc.stderr or ''}\n{proc.stdout or ''}"
        transient = PUSH_TRANSIENT.search(said) if proc.returncode != 0 and _is_push(cmd) else None
        if transient and pushed + push_backoff <= PUSH_RETRY_MAX_WAIT:
            print(f"git push refused by the remote ({transient.group(0)}): pushing again in {int(push_backoff)} s",
                  file=sys.stderr, flush=True)
            sleep(push_backoff)
            pushed += push_backoff
            push_backoff = min(push_backoff * 2, 120.0)
            continue
        dropped = network_retry(cmd, said) if proc.returncode != 0 and not transient else None
        if dropped and offline + net_backoff <= NETWORK_RETRY_MAX_WAIT:
            print(f"`{' '.join(str(c) for c in cmd[:3])}` hit a network error ({dropped}): trying again in {int(net_backoff)} s",
                  file=sys.stderr, flush=True)
            sleep(net_backoff)
            offline += net_backoff
            net_backoff = min(net_backoff * 2, 60.0)
            continue
        if not (cmd and cmd[0] == "gh" and proc.returncode != 0 and RATE_LIMITED.search(said)):
            break
        kind = _rate_limit_kind(said)
        wait = _rate_limit_wait(kind)
        if wait is None:
            wait, backoff = backoff, min(backoff * 2, 600.0)
        if waited + wait > RATE_LIMIT_MAX_WAIT:
            raise PlatformError(f"GitHub's {kind} rate limit is still exhausted after waiting {int(waited // 60)} min for "
                                f"`{' '.join(cmd[:3])}`",
                                hint="another tool is using this account's GitHub budget (for example a second `cplat platform ui` "
                                     "console or another session's CI waits): stop it, then run the command again")
        until = time.strftime("%H:%M", time.gmtime(now() + wait))
        print(f"GitHub rate limit ({kind}): waiting until {until} UTC", file=sys.stderr, flush=True)
        sleep(wait)
        waited += wait
        _journey_wait(wait, kind)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        raise PlatformError(f"`{' '.join(cmd[:4])}` failed (exit {proc.returncode}): " + " | ".join(detail))
    return proc


def git_dir(repo: Path | str) -> Path | None:
    """The absolute git dir of this checkout (`git rev-parse --git-dir`): per-run state lives here, so a linked
    worktree never sees state another checkout wrote (ADR-051). For the main checkout it is the `.git` directory."""
    out = run(["git", "rev-parse", "--git-dir"], cwd=repo, check=False).stdout.strip()
    if not out:
        return None
    return (Path(out) if Path(out).is_absolute() else Path(repo) / out).resolve()


def install_hint(tool: str) -> str | None:
    return {
        "gh": "brew install gh && gh auth login",
        "git": "install git",
        "devbox": "curl -fsSL https://get.jetify.com/devbox/install.sh | bash",
        "docker": "install and start Docker Desktop",
        "uv": "brew install uv",
        "kubectl": "provided by `devbox shell` in a gitops repo",
    }.get(tool)


def find_copier() -> list[str]:
    """Command prefix that runs copier: PATH, ~/.local/bin (uv tool), or an ephemeral uv tool run."""
    found = shutil.which("copier")
    if found:
        return [found]
    local = Path.home() / ".local" / "bin" / "copier"
    if local.is_file():
        return [str(local)]
    if shutil.which("uv"):
        return ["uv", "tool", "run", "--from", "copier", "copier"]
    raise PlatformError("copier is not installed and uv is unavailable", hint="brew install uv && uv tool install copier")


def has_gh() -> bool:
    return shutil.which("gh") is not None


def gh_login() -> str | None:
    if not has_gh():
        return None
    p = run(["gh", "api", "user", "-q", ".login"], check=False)
    return p.stdout.strip() or None if p.returncode == 0 else None


# ---------- platform version / changelog ----------

_VERSION_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\](?: — (\S+))?", re.M)


def platform_version(root: Path = PLATFORM_ROOT) -> str:
    """Latest released version from docs/CHANGELOG.md (the first `## [x.y.z]` heading)."""
    text = (root / "docs" / "CHANGELOG.md").read_text()
    m = _VERSION_RE.search(text)
    return m.group(1) if m else "0.0.0"


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def changelog_between(old: str | None, new: str, root: Path = PLATFORM_ROOT) -> str:
    """CHANGELOG sections with old < version <= new, as one text block (empty if unknown)."""
    text = (root / "docs" / "CHANGELOG.md").read_text()
    heads = list(_VERSION_RE.finditer(text))
    out = []
    for i, m in enumerate(heads):
        v = m.group(1)
        if vtuple(v) <= vtuple(new) and (old is None or vtuple(v) > vtuple(old)):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            out.append(text[m.start():end].strip())
    return "\n\n".join(out)


def read_stamp(repo: Path) -> dict[str, str]:
    f = repo / ".platform-version"
    if not f.is_file():
        return {}
    data = {}
    for line in f.read_text().splitlines():
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data


def write_stamp(repo: Path, shape: str, ref: str) -> None:
    (repo / ".platform-version").write_text(
        "# Written by /component:new and /platform:update; read by /platform:doctor.\n"
        f"platform: {platform_version()}\nshape: {shape}\nref: {ref}\n"
    )


# ---------- reporting ----------

@dataclass
class Report:
    """What a command intends to do / did, rendered as text or JSON."""

    title: str
    will_do: list[str] = field(default_factory=list)       # outward-facing steps are prefixed with "[outward]"
    did: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    undo: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def text(self, dry_run: bool) -> str:
        lines = [f"## {self.title}" + ("  (dry run — nothing was changed)" if dry_run else "")]
        if dry_run:
            lines += ["", "What I will do:"] + [f"  {i}. {s}" for i, s in enumerate(self.will_do, 1)]
        else:
            lines += ["", "What happened:"] + [f"  ✓ {s}" for s in self.did]
        if self.next_steps:
            lines += ["", "Next:"] + [f"  - {s}" for s in self.next_steps]
        if self.undo and not dry_run:
            lines += ["", "To undo:"] + [f"  - {s}" for s in self.undo]
        return "\n".join(lines)

    def emit(self, dry_run: bool, as_json: bool) -> None:
        if as_json:
            print(json.dumps({"title": self.title, "dry_run": dry_run, "will_do": self.will_do, "did": self.did,
                              "next": self.next_steps, "undo": self.undo, **self.data}, indent=2))
        else:
            print(self.text(dry_run))


PR_BODY = ".pr-body.md"   # where agents write a PR body: Claude Code never lets edits into .git/, even under acceptEdits


def _own_git_dir(repo: Path) -> Path | None:
    """git_dir(), else a plain `.git` directory (a repo git cannot read, e.g. a bare skeleton)."""
    return git_dir(repo) or (repo / ".git" if (repo / ".git").is_dir() else None)


def git_path(repo: Path, given: str | Path) -> Path:
    """`given` relative to the repo, where a `.git/…` path means this checkout's git dir: in a linked worktree `.git`
    is a file and the git dir lives elsewhere (#227)."""
    p = Path(given)
    if p.is_absolute():
        return p
    if p.parts[:1] == (".git",) and (gd := _own_git_dir(repo)) is not None:
        return gd.joinpath(*p.parts[1:])
    return repo / p


def stage_pr_body(repo: Path, given: str | Path) -> Path:
    """The PR body the model wrote, moved out of the work tree into the git dir's PR_BODY.md (so no commit picks it up)
    and returned; in a linked worktree that is the worktree's own git dir (#227). A file already in the git dir is used
    as it is; `.git/PR_BODY.md` is still found when the default `.pr-body.md` is missing."""
    path = git_path(repo, given)
    gd = _own_git_dir(repo)
    if gd is None:
        return path
    staged = gd / "PR_BODY.md"
    if not path.is_file() and Path(given).name == PR_BODY and staged.is_file():
        return staged
    if not path.is_file() or gd in path.resolve().parents:
        return path
    staged.write_text(path.read_text())
    path.unlink()
    return staged


def git_identity(repo: Path) -> list[str]:
    """`-c user.name=… -c user.email=…` fallbacks so commits never fail on a missing identity."""
    name = run(["git", "config", "user.name"], cwd=repo, check=False).stdout.strip() or "claude-bootstrap"
    email = run(["git", "config", "user.email"], cwd=repo, check=False).stdout.strip() or "claude-bootstrap@users.noreply.github.com"
    return ["-c", f"user.name={name}", "-c", f"user.email={email}"]
