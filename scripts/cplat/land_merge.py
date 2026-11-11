"""The shared landing of a pull request (spec 171): `ship land` and `pr wait --merge` settle through here.

  land_merge.wait_green(...)    ship.wait_checks, again while a push moved the head, a conflict regenerated
  land_merge.settle(...)        inside the merge lock: catch up, merge on the head the checks were judged on
  land_merge.merge(...)         `gh pr merge --squash --match-head-commit`, never `--delete-branch`
  land_merge.cleanup(...)       the steps after a merge GitHub accepted; a failure is a WARNING line, never a failed land
  land_merge.regenerate(...)    a conflict in a generated file (docs/backlog.md) is merged, regenerated, committed, pushed

A merge GitHub accepted is a merge (AC-171.3); a head that was pushed after its checks is waited for (AC-171.4); a conflict
that only touches a generated block has one right answer (AC-171.6). Everything else about a conflict stays a person's
decision (`Unresolvable`). `run` is the caller's `run` (`ship.run` / `pr.run`), `gh` goes through `ship.gh`.
"""
from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import core
import dispatch_state
import merge_lock
import ship
import spec
from core import PlatformError


@dataclass(frozen=True)
class Generated:
    """A file with a generated block: the markers around it and the generator that rewrites it."""
    start: str
    end: str
    write: Callable[[Path], object]


GENERATED: dict[str, Generated] = {spec.BACKLOG.as_posix(): Generated(start=spec.START, end=spec.END, write=spec.write_index)}
MAX_REGEN_ROUNDS = 3
PLACEHOLDER = "<!-- cplat: generated block (spec 171) -->"


class Unresolvable(merge_lock.Conflict):
    """A conflict with the base that stays a person's decision."""


class MergeFailed(PlatformError):
    """GitHub refused the merge for a reason that is neither a conflict nor a moved head."""


@dataclass(frozen=True)
class Mode:
    """What a land may do to the pull request's branch: follow its base (catch-up), or never touch it (release)."""
    name: str
    catch_up: bool


CATCH_UP = Mode("catch-up", True)
RELEASE = Mode("release", False)
MAX_REFUSALS = 3
REFUSED = re.compile(r"required status check|is expected|head branch was modified|base branch was modified|match-head-commit", re.I)


class BaseMoved(PlatformError):
    """RELEASE only: the branch is behind its base or conflicts with it, and the land does not change the branch."""

    def __init__(self, url: str, base: str):
        super().__init__(f"{url} is behind {base}: {base} moved",
                         hint=f"update the branch of the pull request to {base} (and let its checks run), then run the land again")
        self.base, self.url = base, url


class MergeRefused(MergeFailed):
    """GitHub refused the merge `MAX_REFUSALS` times in one land (a pending required check or a moved head)."""

    def __init__(self, reason: str):
        super().__init__(f"merge refused {MAX_REFUSALS} times: {reason}",
                         hint="wait for the checks of the pull request, then run the land again")
        self.reason = reason


@dataclass
class Rounds:
    """Regeneration rounds (AC-171.6) and refused merges (AC-178.3) used by one land invocation."""
    used: int = 0
    refused: int = 0
    reason: str = ""


@dataclass
class Settled:
    status: str                                  # "merged" | "red"
    lines: list[str] = field(default_factory=list)
    cs: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    sha: str = ""                                # the merge commit
    updated: bool = False                        # the branch head changed on GitHub (catch-up or regeneration)


def _last_line(res) -> str:
    """The last non-empty line of a command's error output (else its output), else `exit <code>`."""
    for text in (res.stderr, res.stdout):
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        if lines:
            return lines[-1]
    return f"exit {res.returncode}"


def _view(repo: Path, url: str, fields: str) -> dict:
    try:
        data = json.loads(ship.gh(["pr", "view", url, "--json", fields], cwd=repo, check=False) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _reset_watch(watch: ship.CheckWatch) -> None:
    """A new head starts the watch over, as `CheckWatch._current` does."""
    watch.reported.clear()
    watch.queued_since.clear()
    watch.stale_seen.clear()
    watch.healed.clear()
    watch.cancel_seen.clear()


def await_head(watch: ship.CheckWatch, sha: str, polls: int = merge_lock.HEAD_POLLS) -> bool:
    """Wait until GitHub shows `sha` as the head of the pull request; then the watch carries it."""
    for attempt in range(polls):
        if watch.head_sha() == sha:
            if watch.head not in (None, sha):
                _reset_watch(watch)
            watch.head = sha
            return True
        if attempt < polls - 1:
            ship.sleep(2)
    return False


def _base_moved(repo: Path, url: str) -> BaseMoved:
    return BaseMoved(url, _view(repo, url, "baseRefName").get("baseRefName") or "main")


def ensure_current(repo: Path, url: str) -> None:
    """`BaseMoved` when the branch is behind its base or conflicts with it; `merge_lock.Unknown` when that is unreadable."""
    base = _view(repo, url, "baseRefName").get("baseRefName") or "main"
    if _view(repo, url, "mergeable").get("mergeable") == "CONFLICTING":
        raise BaseMoved(url, base)
    head = _view(repo, url, "headRefOid").get("headRefOid")
    behind = merge_lock._behind(repo, merge_lock.slug_of(repo, url), url, head)[0] if head else None
    if behind is None:
        raise merge_lock.Unknown(f"could not tell whether {url} is behind its base, so it is not merged",
                                 hint="run the land again; no pull request merges on a guess")
    if behind > 0:
        raise BaseMoved(url, base)


def wait_green(repo: Path, url: str, watch: ship.CheckWatch, timeout: float, interval: float, rounds: Rounds,
               run, mode: Mode = CATCH_UP) -> tuple[str, list[dict], list[dict], list[str]]:
    """The checks of the head: again while a push moved the head during the last poll, and a conflict with the base
    is regenerated (or stops as `Unresolvable`) before they are waited for again; a RELEASE land stops as `BaseMoved`."""
    lines: list[str] = []
    while True:
        try:
            status, cs, failed = ship.wait_checks(watch, timeout, interval)
        except ship.Conflicting as e:
            if not mode.catch_up:
                raise _base_moved(repo, url) from e
            lines += regenerate(repo, url, watch, rounds, run)
            continue
        if status == "red" or not watch.head or watch.head_sha() in (None, watch.head):
            return status, cs, failed, lines


def merge(repo: Path, url: str, head: str | None, run) -> tuple[str, str]:
    """("merged", merge commit) | ("head-moved", new head) | ("refused", reason) | ("conflicting", ""); `MergeFailed` otherwise."""
    cmd = ["gh", "pr", "merge", url, "--squash"] + (["--match-head-commit", head] if head else [])
    res = run(cmd, cwd=repo, check=False)
    if res.returncode == 0:
        return "merged", (_view(repo, url, "mergeCommit").get("mergeCommit") or {}).get("oid") or ""
    detail = _last_line(res)
    view = _view(repo, url, "state,mergeable,headRefOid,mergeCommit")
    if view.get("state") == "MERGED":
        return "merged", (view.get("mergeCommit") or {}).get("oid") or ""
    new = view.get("headRefOid")
    if head and new and new != head:
        return "head-moved", new
    if view.get("mergeable") == "CONFLICTING":
        return "conflicting", ""
    if REFUSED.search(detail):
        return "refused", detail
    raise MergeFailed(f"merging {url} failed: {detail}", hint="read the error, then run the merge again")


def _worktrees(repo: Path, run) -> list[tuple[Path, str]]:
    """(path, branch) of every worktree of the repository; the branch is "" for a detached one."""
    res = run(["git", "worktree", "list", "--porcelain"], cwd=repo, check=False)
    out: list[tuple[Path, str]] = []
    path, branch = None, ""
    for ln in (res.stdout or "").splitlines() + [""]:
        if ln.startswith("worktree "):
            path, branch = Path(ln[len("worktree "):]), ""
        elif ln.startswith("branch refs/heads/"):
            branch = ln[len("branch refs/heads/"):]
        elif not ln and path is not None:
            out.append((path, branch))
            path = None
    return out


def _step(name: str, warnings: list[str], fn: Callable[[], object]) -> bool:
    """Run one cleanup step; a failure (a non-zero git exit or an exception) is one WARNING line."""
    try:
        res = fn()
    except Exception as e:  # noqa: BLE001
        text = [ln.strip() for ln in str(e).splitlines() if ln.strip()]
        warnings.append(f"WARNING: {name} failed: {text[-1] if text else type(e).__name__}")
        return False
    if getattr(res, "returncode", 0) != 0:
        warnings.append(f"WARNING: {name} failed: {_last_line(res)}")
        return False
    return True


def cleanup(repo: Path, url: str, run) -> list[str]:
    """After a merge GitHub accepted: the remote branch, then the local steps. WARNING lines only, never an exception."""
    warnings: list[str] = []
    try:
        view = _view(repo, url, "headRefName,baseRefName,isCrossRepository")
        head, base = view.get("headRefName") or "", view.get("baseRefName") or "main"
        slug = merge_lock.slug_of(repo, url)
        if head and not view.get("isCrossRepository"):
            def delete_remote():
                res = run(["gh", "api", "-X", "DELETE", f"repos/{slug}/git/refs/heads/{head}"], cwd=repo, check=False)
                if res.returncode != 0 and "does not exist" in f"{res.stderr}\n{res.stdout}".lower():
                    return None            # GitHub deleted it already
                return res
            _step(f"deleting the remote branch {head}", warnings, delete_remote)
        if not head or dispatch_state.slug_of(repo) != slug:
            return warnings
        _local(repo, head, base, run, warnings)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"WARNING: cleanup failed: {str(e).strip() or type(e).__name__}")
    return warnings


def _local(repo: Path, head: str, base: str, run, warnings: list[str]) -> None:
    top = run(["git", "rev-parse", "--show-toplevel"], cwd=repo, check=False).stdout.strip()
    here = Path(top).resolve() if top else repo.resolve()
    trees = [(p.resolve() if p.exists() else p, b) for p, b in _worktrees(repo, run)]
    elsewhere = any(b == base and p != here for p, b in trees)
    exists = run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{head}"], cwd=repo, check=False).returncode == 0
    if elsewhere:      # the base is checked out in another worktree: no switch, no pull (A3)
        if exists and not any(b == head for _, b in trees):
            _step(f"deleting the local branch {head}", warnings, lambda: run(["git", "branch", "-D", "-q", head], cwd=repo, check=False))
        return
    current = run(["git", "branch", "--show-current"], cwd=repo, check=False).stdout.strip()
    if current != base and not _step(f"switching to {base}", warnings, lambda: run(["git", "switch", "-q", base], cwd=repo, check=False)):
        return
    _step(f"updating {base}", warnings, lambda: run(["git", "pull", "-q", "--ff-only"], cwd=repo, check=False))
    if exists:
        _step(f"deleting the local branch {head}", warnings, lambda: run(["git", "branch", "-D", "-q", head], cwd=repo, check=False))


# ---------------- regeneration of a conflict in a generated file ----------------

def _human(url: str, base: str, why: str) -> Unresolvable:
    return Unresolvable(f"{url} conflicts with {base}: rebase is a human decision ({why})",
                        hint="resolve the conflict on the branch, then run the land again")


def _git(repo: Path, run, *args: str, check: bool = False):
    return run(["git", *args], cwd=repo, check=check)


def _abort(repo: Path, run) -> None:
    _git(repo, run, "merge", "--abort")


def _mask(text: str, g: Generated) -> str | None:
    """`text` with the generated block replaced by one placeholder line; None when the markers are not there."""
    s = text.find(g.start)
    e = text.find(g.end, s + len(g.start)) if s >= 0 else -1
    if s < 0 or e < 0:
        return None
    return text[:s] + PLACEHOLDER + text[e + len(g.end):]


def _regenerate_file(repo: Path, url: str, path: str, g: Generated, run) -> str | None:
    """Merge the hand-written part of `path` as text and regenerate its block; the reason it cannot be, else None."""
    stages = []
    for n in (1, 2, 3):
        res = _git(repo, run, "show", f":{n}:{path}")
        masked = _mask(res.stdout, g) if res.returncode == 0 else None
        if masked is None:
            return f"{path} outside its generated block: stage {n} has no generated block"
        stages.append(masked)
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, text in zip(("base", "ours", "theirs"), (stages[0], stages[1], stages[2])):
            f = Path(tmp) / name
            f.write_text(text)
            files.append(str(f))
        res = _git(repo, run, "merge-file", "-p", files[1], files[0], files[2])
    if res.returncode != 0:
        return f"{path} outside its generated block"
    if res.stdout.count(PLACEHOLDER) != 1:
        return f"{path} outside its generated block: the block was changed"
    (repo / path).write_text(res.stdout.replace(PLACEHOLDER, f"{g.start}\n{g.end}", 1))
    g.write(repo)
    _git(repo, run, "add", path, check=True)
    return None


def regenerate(repo: Path, url: str, watch: ship.CheckWatch, rounds: Rounds, run) -> list[str]:
    """Merge the base into the PR branch, regenerate the generated files that conflict, commit (signed off), push (never
    forced) and wait for GitHub to show the new head. One line says what was done; `Unresolvable` stops the rest."""
    view = _view(repo, url, "headRefName,baseRefName")
    head, base = view.get("headRefName") or "", view.get("baseRefName") or "main"
    rounds.used += 1
    if rounds.used > MAX_REGEN_ROUNDS:
        raise Unresolvable(f"{url} still conflicts with {base} after {MAX_REGEN_ROUNDS} regeneration rounds: rebase is a human decision",
                           hint="resolve the conflict on the branch, then run the land again")
    if not head:
        raise _human(url, base, "the pull request's branch could not be read")
    if dispatch_state.slug_of(repo) != merge_lock.slug_of(repo, url):
        raise _human(url, base, "this checkout is not the repository of the pull request")
    current = _git(repo, run, "branch", "--show-current").stdout.strip()
    if current != head:
        raise _human(url, base, f"this checkout is on {current or 'no branch'}, not on {head}")
    if _git(repo, run, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise _human(url, base, "this checkout has uncommitted changes to tracked files")
    res = _git(repo, run, "fetch", "-q", "origin", base, head)
    if res.returncode != 0:
        raise PlatformError(f"fetching {base} and {head} failed: {_last_line(res)}", hint="run the land again")
    counts = _git(repo, run, "rev-list", "--left-right", "--count", f"HEAD...origin/{head}").stdout.split()
    ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 and all(c.isdigit() for c in counts) else (0, 0)
    if ahead:
        raise _human(url, base, f"{ahead} local commit(s) of {head} are not pushed")
    if behind and _git(repo, run, "merge", "-q", "--ff-only", f"origin/{head}").returncode != 0:
        raise _human(url, base, f"the local {head} cannot follow origin/{head}")
    pre = _git(repo, run, "rev-parse", "HEAD", check=True).stdout.strip()

    paths: list[str] = []
    try:
        res = _git(repo, run, "merge", "--no-ff", "--no-commit", f"origin/{base}")
        merging = _git(repo, run, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0
        unmerged = [p for p in _git(repo, run, "diff", "--name-only", "--diff-filter=U").stdout.splitlines() if p]
        if res.returncode not in (0, 1) or (res.returncode == 1 and not unmerged):
            raise _human(url, base, f"git merge failed: {_last_line(res)}")
        if not merging:
            raise _human(url, base, f"{head} already contains {base}")
        others = [p for p in unmerged if p not in GENERATED]
        if others:
            raise Unresolvable(f"{url} conflicts with {base} in {', '.join(others)}: rebase is a human decision",
                               hint="resolve the conflict on the branch, then run the land again")
        for p in unmerged:
            why = _regenerate_file(repo, url, p, GENERATED[p], run)
            if why:
                raise Unresolvable(f"{url} conflicts with {base} in {why}: rebase is a human decision",
                                   hint="resolve the conflict on the branch, then run the land again")
            paths.append(p)
        res = run(["git", *core.git_identity(repo), "commit", "-q", "-s", "--no-edit"], cwd=repo, check=False)
        if res.returncode != 0:
            raise PlatformError(f"committing the merge of {base} into {head} failed: {_last_line(res)}")
    except BaseException:
        _abort(repo, run)
        raise
    new = _git(repo, run, "rev-parse", "HEAD", check=True).stdout.strip()
    watch.expect_from_current()
    res = _git(repo, run, "push", "-q", "origin", head)
    if res.returncode != 0:
        _git(repo, run, "reset", "-q", "--hard", pre)
        raise PlatformError(f"pushing the regenerated merge of {url} failed: {_last_line(res)}",
                            hint="run the land again; the branch is back where it was")
    if not await_head(watch, new):
        raise PlatformError(f"GitHub does not show the pushed head {new[:7]} of {url} yet", hint="run the land again")
    n = f"round {rounds.used}/{MAX_REGEN_ROUNDS}"
    if paths:
        return [f"regenerated {', '.join(paths)} after merging {base} into {head} ({n})"]
    return [f"merged {base} into {head} without a conflict ({n})"]


# ---------------- the settle loop ----------------

def settle(repo: Path, url: str, watch: ship.CheckWatch, timeout: float, interval: float, rounds: Rounds, run,
           before_merge: Callable[[], tuple[bool, list[str]]] | None = None, mode: Mode = CATCH_UP) -> Settled:
    """Inside the merge lock, after the first green: catch up with the base (CATCH_UP) or stop as `BaseMoved` (RELEASE), then
    merge on the head the checks were judged on. A conflict in a generated file is regenerated, a head that moved or a merge
    GitHub refuses is waited for (`MAX_REFUSALS` in one land), and nothing merges unchecked."""
    lines: list[str] = []
    updated = False
    while True:
        try:
            caught = merge_lock.catch_up(repo, url, watch, timeout, interval, allow=mode.catch_up)
        except merge_lock.Behind as e:
            raise BaseMoved(url, e.base) from e
        except Unresolvable:
            raise
        except merge_lock.Conflict:
            if not mode.catch_up:
                raise _base_moved(repo, url) from None
            lines += regenerate(repo, url, watch, rounds, run)
            updated = True
            status, cs, failed, more = wait_green(repo, url, watch, timeout, interval, rounds, run, mode=mode)
            lines += more
            if status == "red":
                return Settled("red", lines, cs, failed, updated=updated)
            continue
        lines += caught.lines
        updated = updated or caught.updated
        if caught.status == "red":
            return Settled("red", lines, caught.cs, caught.failed, updated=updated)
        if before_merge:
            ok, more = before_merge()
            lines += more
            if not ok:
                return Settled("red", lines, updated=updated)
        watch.expected = {}                      # the green before this merge attempt met them
        kind, value = merge(repo, url, watch.head, run)
        if kind == "merged":
            return Settled("merged", lines + [f"merged {url} (squash)"] + cleanup(repo, url, run), sha=value, updated=updated)
        if kind in ("head-moved", "refused"):
            rounds.refused += 1
            rounds.reason = value if kind == "refused" else f"the head moved to {value[:7]}"
            if rounds.refused >= MAX_REFUSALS:
                raise MergeRefused(rounds.reason)
            if kind == "head-moved":      # the AC-171.4 line, now counted
                ship.say(f"  the head of {url} moved to {value[:7]} before the merge: waiting for its checks "
                         f"(refusal {rounds.refused}/{MAX_REFUSALS})")
            else:
                ship.say(f"  merge of {url} refused ({rounds.reason}): waiting for the checks of its head "
                         f"(refusal {rounds.refused}/{MAX_REFUSALS})")
            updated = updated or kind == "head-moved"
        else:
            if not mode.catch_up:
                raise _base_moved(repo, url)
            lines += regenerate(repo, url, watch, rounds, run)
            updated = True
        status, cs, failed, more = wait_green(repo, url, watch, timeout, interval, rounds, run, mode=mode)
        lines += more
        if status == "red":
            return Settled("red", lines, cs, failed, updated=updated)
