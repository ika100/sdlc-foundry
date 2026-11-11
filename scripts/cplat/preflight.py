"""Spec 131: the run allowlist, the refused rules and the preflight of an unattended run.

The allowlist is passed to each session as arguments and in the env; nothing is written to any settings file.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import core

TIMEOUT = 30
LAND_COMMANDS = ("/component:ship", "/system:ship")
MINIMUM = ("Bash(cplat *)", "Read(~/.claude/plugins/**)")     # what a session needs first (spec 171)


@dataclass
class Failure:
    category: str
    detail: str

    def line(self) -> str:
        return f"preflight failed: {self.category}: {self.detail}"

    def reason(self) -> str:
        return f"preflight failed: {self.category}"


def branches_of(command: str, specs: list[str]) -> list[str]:
    if command == "/system:ship":
        return ["feature/*"]
    return [f"feature/{s}" for s in specs] or ["feature/x"]


def run_allowlist(command: str, branches: list[str]) -> list[str]:
    rules: list[str] = []
    for b in branches:
        rules += [f"Bash(git switch {b})", f"Bash(git switch -c {b})"]
    rules += ["Bash(git add *)", "Bash(git commit -s *)", "Bash(git rm *)"]
    for b in branches:
        rules += [f"Bash(git push -u origin {b})", f"Bash(git push origin {b})"]
    rules.append("Bash(gh pr create *)")
    if command in LAND_COMMANDS:
        rules += ["Bash(cplat component ship land)", "Bash(cplat component ship land *)"]
    if command == "/system:ship":
        rules.append("Bash(cplat system ship entry land *)")
    return list(dict.fromkeys(rules))


def refused_rules(default_branch: str) -> list[str]:
    d = default_branch
    return [
        "Bash(git push --force*)", "Bash(git push -f*)", "Bash(git push * --force*)", "Bash(git push * -f*)",
        "Bash(git push * +*)", f"Bash(git push * {d})", f"Bash(git push * {d}:*{d}*)", f"Bash(git push * {d}:refs*)", f"Bash(git push * *:{d})",
        f"Bash(git push * *:refs/heads/{d})",
        "Bash(gh pr merge*)", "Bash(gh api *merge*)",
        "Bash(cplat pr wait *--merge*)",
        "Bash(git rm -f*)", "Bash(git rm --force*)", "Bash(git rm -rf*)", "Bash(git rm -fr*)",
        "Bash(git rm * -f*)", "Bash(git rm * --force*)", "Bash(git rm * -rf*)", "Bash(git rm * -fr*)",
    ]


def env(allowlist: list[str]) -> dict[str, str]:
    return {"CPLAT_RUN_ALLOWLIST": json.dumps(allowlist)}


def matches(rule: str, command: str) -> bool:
    if rule in ("Bash", "Bash(*)"):
        return True
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return False
    pat = rule[5:-1]
    if pat.endswith(":*"):
        p = pat[:-2]
        return command == p or command.startswith(p + " ")
    return re.fullmatch(".*".join(re.escape(part) for part in pat.split("*")), command, re.DOTALL) is not None


def read_matches(rule: str, path: str) -> bool:
    """Whether a `Read` allow rule covers `path`: `Read`, `Read(**)` or a glob (`**` any, `*` no `/`; `~` or the home accepted)."""
    if rule == "Read":
        return True
    if not (rule.startswith("Read(") and rule.endswith(")")):
        return False
    glob = rule[5:-1]
    home = str(Path.home())
    if glob.startswith("~"):
        glob = home + glob[1:]
    target = home + path[1:] if path.startswith("~") else path
    pat = "".join(".*" if part == "**" else "[^/]*" if part == "*" else re.escape(part)
                  for part in re.split(r"(\*\*|\*)", glob))
    return re.fullmatch(pat, target, re.DOTALL) is not None


def _self_check() -> None:
    for command in ("/component:build", "/component:ship", "/system:ship"):
        for branches in (["feature/*"], ["feature/001-x"]):
            allow = run_allowlist(command, branches)
            refused = refused_rules("main")
            assert not set(allow) & set(refused)
            for rule in allow:
                sample = rule[5:-1].replace("*", "x")
                assert not any(matches(r, sample) for r in refused), (rule, sample)


_self_check()


# ---------------- environment access (tests replace these) ----------------

def _exec(args: list[str], cwd: Path | None) -> tuple[int, str]:
    try:
        res = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    return res.returncode, (res.stdout or "").strip()


def git(args: list[str], cwd: Path) -> tuple[int, str]:
    return _exec(["git", *args], cwd)


def gh(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    return _exec(["gh", *args], cwd)


def default_branch(repo: Path) -> str:
    code, out = git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], repo)
    name = out.removeprefix("origin/") if code == 0 else ""
    return name or "main"


def layers(repo: Path) -> list[tuple[str, Path]]:
    managed = ("/Library/Application Support/ClaudeCode/managed-settings.json" if platform.system() == "Darwin"
               else "/etc/claude-code/managed-settings.json")
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    user = Path(cfg) / "settings.json" if cfg else Path.home() / ".claude" / "settings.json"
    return [("managed", Path(managed)), ("user", user), ("project", repo / ".claude" / "settings.json"),
            ("local", repo / ".claude" / "settings.local.json")]


def _origin(repo: Path) -> tuple[str, str]:
    """(host, slug) of `origin`; host defaults to github.com, slug to ''."""
    _, url = git(["remote", "get-url", "origin"], repo)
    m = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)[/:]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return (m.group(1), m.group(2)) if m else ("github.com", "")


# ---------------- checks ----------------

def _representative(branches: list[str], command: str, base: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for b in branches:
        b = "feature/x" if b == "feature/*" else b
        out += [("branch", f"git switch -c {b}"), ("commit", 'git commit -s -m "<subject>"'),
                ("push", f"git push -u origin {b}"),
                ("pr", f'gh pr create --base {base} --head {b} --title "<title>" --body-file .pr-body.md')]
    if command in LAND_COMMANDS:
        out.append(("land", "cplat component ship land"))
    return out


def _rules(path: Path, kind: str) -> list[str]:
    try:
        perms = json.loads(path.read_text()).get("permissions", {})
        return [r for r in perms.get(kind, []) if isinstance(r, str)]
    except (OSError, ValueError, AttributeError):
        return []


def _blocked(repo: Path, command: str, branches: list[str], only: tuple[str, ...] | None = None) -> Failure | None:
    base = default_branch(repo)
    for action, cmd in _representative(branches, command, base):
        for name, path in layers(repo):
            if only is not None and name not in only and name in ("project", "local"):
                continue
            for kind in ("deny", "ask"):
                for rule in _rules(path, kind):
                    if matches(rule, cmd):
                        return Failure("blocked-by-settings",
                                       f'{action}: {kind} rule "{rule}" in {name} settings ({path}) matches "{cmd}": '
                                       "remove or narrow the rule, or run the command attended")
    return None


def _no_allowlist(repo: Path) -> Failure | None:
    path = repo / ".claude" / "settings.json"
    if not path.is_file():
        return Failure("no-repo-allowlist",
                       f"{repo} has no committed allowlist (.claude/settings.json): run /platform:update or cplat adopt")
    allow = _rules(path, "allow")
    missing = []
    if not any(matches(r, "cplat spec check") for r in allow):
        missing.append(MINIMUM[0])
    if not any(read_matches(r, "~/.claude/plugins/cache/sdlc-foundry/component/1.0.0/commands/ship.md") for r in allow):
        missing.append(MINIMUM[1])
    if not missing:
        return None
    return Failure("no-repo-allowlist",
                   f"{' and '.join(missing)} not allowed by {path}: add to permissions.allow "
                   "(the library template's allowlist has it), or run /platform:update")


def _identity(repo: Path) -> Failure | None:
    have_env = os.environ.get("GIT_AUTHOR_NAME") and os.environ.get("GIT_AUTHOR_EMAIL")
    if have_env:
        return None
    ok = all(git(["config", "--get", k], repo)[1] for k in ("user.name", "user.email"))
    if ok:
        return None
    return Failure("git-identity", "commit -s needs an author: git config --global user.name '<name>' "
                                   "and user.email '<email>'")


def _retried(args: list[str], repo: Path) -> tuple[int, str, str]:
    """A `gh` call through core.run, which runs it again on a dropped network: (exit code, stdout, stderr)."""
    try:
        res = core.run(["gh", *args], cwd=repo, check=False, timeout=TIMEOUT)
    except core.PlatformError as e:
        return 1, "", str(e)
    return res.returncode, (res.stdout or "").strip(), (res.stderr or "").strip()


def _offline(err: str) -> str | None:
    """The network error in `err`, if the call failed for want of a network rather than for its own reason."""
    hit = core.NETWORK_DOWN.search(err) or core.NETWORK_FLAKY.search(err)
    return err.splitlines()[-1] if hit else None


def _auth(repo: Path) -> Failure | None:
    host = _origin(repo)[0]
    code, _, err = _retried(["auth", "status", "--hostname", host], repo)
    if code == 0:
        return None
    if (why := _offline(err)):          # a dropped network once read as "not logged in" and escalated a run
        return Failure("gh-auth", f"could not reach {host} to check the gh login ({why}): check the network, then run again")
    return Failure("gh-auth", f"gh is not logged in for {host}: gh auth login --hostname {host}")


def _push_access(repo: Path, slug: str) -> Failure | None:
    if not slug:
        return None
    code, out, err = _retried(["api", f"repos/{slug}", "--jq", ".permissions.push"], repo)   # a drop once read as "cannot push"
    if code == 0 and out == "true":
        return None
    if code != 0:
        why = err.splitlines()[-1] if err else f"gh exited {code}"
        return Failure("no-push-access", f"could not read the push access to {slug} ({why}): check the network "
                                         "and gh, then run again")
    user = gh(["api", "user", "--jq", ".login"], repo)[1] or "this account"
    return Failure("no-push-access", f"{user} cannot push to {slug}: ask for write access to it")


def check(repo: Path, command: str, specs: list[str],
          targets: list[tuple[Path, str]] | None = None) -> Failure | None:
    """The five checks in order; the first failure wins. `targets` are (clone, slug) pairs besides the repo."""
    repo = Path(repo)
    branches = branches_of(command, specs)
    clones = [(repo, _origin(repo)[1]), *(targets or [])]
    for path, _ in clones:
        if (f := _no_allowlist(path)):
            return f
    for path, _ in clones:
        if (f := _blocked(path, command, branches)):
            return f
    if (f := _identity(repo)):
        return f
    if (f := _auth(repo)):
        return f
    for path, slug in clones:
        if (f := _push_access(path, slug)):
            return f
    return None


def check_repo(clone: Path, slug: str) -> Failure | None:
    """The checks of a repo started later by `/system:ship`: allowlist, settings and push access."""
    clone = Path(clone)
    return (_no_allowlist(clone) or _blocked(clone, "/system:ship", ["feature/*"]) or _push_access(clone, slug))
