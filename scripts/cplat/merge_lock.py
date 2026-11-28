"""The repo merge lock (spec 167, ADR-089): every merge into main, from a dispatcher unit or a manual session, holds one
machine-wide lock per repo slug, and a branch that is behind its base is updated and has its checks run again on top
before it merges.

Inside the lock `held` also checks the release hold of the repo (spec 198): a hold of another process is waited for with the
lock released, that wait does not count against the timeout, and the merge then starts over from the lock. The release sets
its own hold with `set_release_hold`, which waits once for a merge already inside the lock.

  with merge_lock.held(slug, who, timeout) as hold:   an exclusive flock on `<state>/locks/<owner>__<name>.merge.lock`
      caught = merge_lock.catch_up(..., hold=hold)    inside the lock: behind check, `gh pr update-branch`, the new head's checks

The lock has two parts (spec 220): the flock, which every merge step holds, and a catch-up claim (`<owner>__<name>.merge-claim.json`
beside it, written only under the flock). A land that has to wait for the e2e of its updated head writes the claim and gives the
flock up for that wait (`Hold.waiting`); a land that finds a live claim queues, unless `held(fast_lane=)` says it is outside the
e2e scope, in which case it merges meanwhile (the fast lane). The release hold is checked again whenever the flock is taken. A
catch-up whose head had a green e2e keeps it while the base moved only outside the e2e scope (`CatchUp.kept`).

The callers (`pr wait --merge`, `ship land`) merge through `land_merge` (spec 171), which settles inside this lock: a head
that was not known is read here and guards the merge, a conflict in a generated file is regenerated, the cleanup after the
merge never fails it.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import core
import dispatch_state
import e2e_gate
import release_hold
import ship
from core import PlatformError, run

WAIT_LINE_EVERY = 60          # seconds between two "waiting for the merge lock" lines
QUEUE_LIMIT = 6 * 3600        # seconds a merge queues behind live holders before it gives up
HEAD_POLLS = 5               # polls for the new head after an update


def sleep(seconds: float) -> None:   # tests replace this
    time.sleep(seconds)


class Busy(PlatformError):
    """The merge lock stayed held by someone else past the timeout: no red check, no fix round, no escalation."""

    def __init__(self, slug: str, who: str, since: str):
        super().__init__(f"the merge lock of {slug} is held by {who} since {since}", hint="run it again")


class Conflict(PlatformError):
    """The branch could not be brought up to date with its base: a human decision."""


def slug_of(repo: Path, url: str) -> str:
    """owner/name of the pull request's repo: from its URL, else the repo's origin."""
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/", url or "")
    return m.group(1) if m else dispatch_state.slug_of(repo)


def who_of(url: str) -> str:
    """Who asks for the lock: the pull request, and the dispatcher unit when there is one."""
    who = f"pr {(url or '').rstrip('/').rsplit('/', 1)[-1]}"
    unit = os.environ.get("CPLAT_DISPATCH_UNIT")
    return f"{who} ({unit})" if unit else who


def _holder(slug: str) -> dict:
    try:
        return json.loads(dispatch_state.merge_info_path(slug).read_text())
    except (OSError, ValueError):
        return {}


MAX_CLAIMED_ROUNDS = 3       # claimed catch-up rounds per land; a later round keeps the lock through its checks


@dataclass
class LandStats:
    """What one land waited for (spec 220, AC-220.8); `land_merge.record_land` turns it into the run record's `lands` item."""
    lock_wait_s: float = 0.0              # every wait for the lock and for claims, the retake included
    lock_wait_catch_up_s: float = 0.0     # the part of it while a claim or a "checks" holder was seen
    catch_up_s: float = 0.0               # time in catch-up check waits
    catch_up_e2e: bool = False            # a catch-up waited on e2e checks
    range_scope: str | None = None        # "out" | "in" | "unknown" | None (no kept-e2e decision was made)
    fast_lane: bool = False
    e2e_kept: bool = False
    scope: str | None = None              # "docs" | "code" | "unknown" | None


def claim_path(slug: str) -> Path:
    return dispatch_state.merge_lock_path(slug).with_name(f"{dispatch_state.slug_dir(slug)}.merge-claim.json")


def _live_claim(slug: str) -> dict | None:
    """The catch-up claim of another live process; a claim of a dead process is stale and removed (the caller holds the lock)."""
    try:
        claim = json.loads(claim_path(slug).read_text())
    except (OSError, ValueError):
        return None
    pid = claim.get("pid") if isinstance(claim, dict) else None
    if not isinstance(pid, int) or pid == os.getpid():
        return None
    if release_hold.alive(pid):
        return claim
    claim_path(slug).unlink(missing_ok=True)
    return None


def _drop_claim(slug: str) -> None:
    """Remove the claim of this process (and only that one)."""
    try:
        claim = json.loads(claim_path(slug).read_text())
    except (OSError, ValueError):
        return
    if isinstance(claim, dict) and claim.get("pid") == os.getpid():
        claim_path(slug).unlink(missing_ok=True)


def _pr_url(slug: str, who: str) -> str:
    m = re.match(r"pr (\d+)", who)
    return f"https://github.com/{slug}/pull/{m.group(1)}" if m else who


def _acquire(lock, slug: str, timeout: float, interval: float, stats: LandStats,
             fast_lane: Callable[[], bool] | None, who: str) -> None:
    """Take the flock of `lock`. A holder's process that is alive, or a live claim of another process, is a queue; a release
    hold of another process is waited for outside the lock (spec 198) and drops this process's own claim; a land outside the
    e2e scope (`fast_lane()`, asked once, only when a live claim is seen) merges while the claimant waits on its checks."""
    begin = queued = said = time.monotonic()
    claim_said: float | None = None
    asked: list[bool] = []
    while True:
        mark = time.monotonic()
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = _holder(slug)
            since = holder.get("since") or "an unknown time"
            checks = holder.get("phase") == "checks"
            if isinstance(holder.get("pid"), int) and release_hold.alive(holder["pid"]):
                begin = time.monotonic()        # a live holder: the queue, not a stuck lock
            if time.monotonic() - begin > timeout or time.monotonic() - queued > QUEUE_LIMIT:
                raise Busy(slug, holder.get("who") or "another merge", since) from None
            if time.monotonic() - said >= WAIT_LINE_EVERY:
                said = time.monotonic()
                tail = " (waiting on its checks)" if checks else ""
                ship.say(f"waiting for the merge lock of {slug}: held by {holder.get('who') or 'another merge'}{tail} since {since}")
            sleep(interval)
            waited = time.monotonic() - mark
            stats.lock_wait_s += waited
            stats.lock_wait_catch_up_s += waited if checks else 0.0
            continue
        hold = release_hold.foreign(slug)       # inside the lock, so no merge starts between the check and the merge
        if hold is not None:
            _drop_claim(slug)
            fcntl.flock(lock, fcntl.LOCK_UN)    # wait outside the lock: the release itself must be able to merge
            waited = release_hold.wait_clear(slug, hold)
            begin += waited
            queued += waited
            said = time.monotonic()
            continue
        claim = _live_claim(slug)
        if claim is None:
            return
        if fast_lane is not None:
            if not asked:
                asked.append(bool(fast_lane()))
            if asked[0]:
                ship.say(f"fast lane: {claim.get('pr') or claim.get('who')} waits on its checks; "
                         f"merging {_pr_url(slug, who)} outside the e2e scope")
                stats.fast_lane = True
                return
        fcntl.flock(lock, fcntl.LOCK_UN)        # a live claim is a queue: not counted against the timeout
        begin = time.monotonic()
        if time.monotonic() - queued > QUEUE_LIMIT:
            raise Busy(slug, claim.get("who") or "another merge", claim.get("since") or "an unknown time")
        if claim_said is None or time.monotonic() - claim_said >= WAIT_LINE_EVERY:
            claim_said = time.monotonic()
            ship.say(f"waiting for the merge lock of {slug}: held by {claim.get('who') or 'another merge'} (waiting on its checks) "
                     f"since {claim.get('since') or 'an unknown time'}")
        sleep(interval)
        waited = time.monotonic() - mark
        stats.lock_wait_s += waited
        stats.lock_wait_catch_up_s += waited


class Hold:
    """The lock as a land holds it (spec 220): `waiting` gives the flock up for a catch-up wait under a claim, so that a land
    outside the e2e scope can merge meanwhile, and takes it back."""

    def __init__(self, slug: str, who: str, lock, timeout: float, interval: float, stats: LandStats):
        self.slug, self.who, self.stats = slug, who, stats
        self.locked = False
        self._lock, self._timeout, self._interval = lock, timeout, interval
        self._since = dispatch_state.now().strftime("%H:%M:%S")
        self.current = "merge"

    def _write_info(self, phase: str) -> None:
        self.current = phase
        dispatch_state.write_json(dispatch_state.merge_info_path(self.slug),
                                  {"who": self.who, "pid": os.getpid(), "since": self._since, "phase": phase})

    def phase(self, name: str) -> None:
        if self.locked:
            self._write_info(name)

    @contextlib.contextmanager
    def waiting(self, pr: str, claim: bool = True) -> Iterator[None]:
        """Claim, release the lock, run the body (the checks), take the lock back. Another live claim, no lock held or
        `claim=False`: only the phase of the lock changes. A foreign release hold found on the way back drops the claim and
        is waited for; the caller's next look at the base then sees whatever merged meanwhile."""
        if not claim or not self.locked or _live_claim(self.slug) is not None:
            self.phase("checks")
            yield
            self.phase("merge")
            return
        dispatch_state.write_json(claim_path(self.slug), {"who": self.who, "pid": os.getpid(), "pr": pr, "since": self._since})
        ship.say(f"  released the merge lock of {self.slug} while the checks run; in-scope merges wait, others may merge")
        dispatch_state.merge_info_path(self.slug).unlink(missing_ok=True)
        fcntl.flock(self._lock, fcntl.LOCK_UN)
        self.locked = False
        try:
            yield
            _acquire(self._lock, self.slug, self._timeout, self._interval, self.stats, None, self.who)
        except BaseException:
            _drop_claim(self.slug)
            raise
        _drop_claim(self.slug)
        self.locked = True
        self._write_info("merge")


@contextlib.contextmanager
def held(slug: str, who: str, timeout: float, interval: float = 5, *,
         fast_lane: Callable[[], bool] | None = None, stats: LandStats | None = None) -> Iterator[Hold]:
    """Hold the merge lock of `slug`. While the holder's process is alive the wait is a queue: it does not count against
    `timeout` and ends in `Busy` only after QUEUE_LIMIT seconds. `Busy` after `timeout` seconds when the holder's process
    is gone and the lock stays taken. A release hold of another process (spec 198) is waited for outside the lock and does
    not count against the timeout. A live claim of another process (spec 220) is a queue too, unless `fast_lane()` says this
    land is outside the e2e scope: then it merges while the claimant waits on its checks."""
    path, info = dispatch_state.merge_lock_path(slug), dispatch_state.merge_info_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = stats if stats is not None else LandStats()    # a caller's own, so its fast-lane predicate can fill `scope`
    with open(path, "a") as lock:
        _acquire(lock, slug, timeout, interval, stats, fast_lane, who)
        hold = Hold(slug, who, lock, timeout, interval, stats)
        hold.locked = True

        @contextlib.contextmanager
        def paused() -> Iterator[None]:
            """A GitHub rate-limit wait (#1028) never holds the lock: let go, wait, queue again. The head check of the merge
            (`catch_up`, `land_merge`) runs inside the lock, so a head or base that moved meanwhile is seen."""
            if not hold.locked:
                yield
                return
            info.unlink(missing_ok=True)
            fcntl.flock(lock, fcntl.LOCK_UN)
            hold.locked = False
            try:
                yield
            finally:
                _acquire(lock, slug, timeout, interval, stats, None, who)
                hold.locked = True
                hold._write_info(hold.current)

        core.RATE_WAIT_HOOKS.append(paused)
        try:
            hold._write_info("merge")
            yield hold
        finally:
            core.RATE_WAIT_HOOKS.remove(paused)
            _drop_claim(slug)
            if hold.locked:
                info.unlink(missing_ok=True)
                fcntl.flock(lock, fcntl.LOCK_UN)


def set_release_hold(slug: str, version: str, timeout: float, interval: float = 5) -> release_hold.Hold:
    """Set the release hold of `slug` for `version`, then wait once for a merge already inside the merge lock to end."""
    before = release_hold.read(slug)
    hold, taken = release_hold.claim(slug, version)       # HoldTaken: nothing is written
    path = dispatch_state.merge_lock_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    begin = time.monotonic()
    said: float | None = None
    with open(path, "a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock, fcntl.LOCK_UN)
                break
            except BlockingIOError:
                pass
            who = _holder(slug).get("who") or "another merge"
            if time.monotonic() - begin > timeout:
                release_hold.release(slug)
                raise PlatformError(f"the merge of {who} in {slug} did not end within {int(timeout)}s; the release did not start",
                                    hint="run the release again")
            if said is None or time.monotonic() - said >= WAIT_LINE_EVERY:
                said = time.monotonic()
                ship.say(f"waiting for the merge of {who} to end before the release")
            sleep(interval)
    tail = f" (taken over from the stop at confirm {before.confirm})" if taken and before is not None else ""
    ship.say(f"release hold set on {slug} for {version}{tail}")
    return hold


@dataclass
class CatchUp:
    """The outcome of `catch_up`: `status` is `green` (merge now) or `red` (the new head's checks failed)."""
    updated: bool = False
    status: str = "green"
    cs: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    kept: frozenset[str] = frozenset()      # spec 220: e2e workflows skipped on the merged head (empty: nothing kept)


class Behind(PlatformError):
    """A land that may not change the branch found it behind its base (spec 178, RELEASE)."""

    def __init__(self, base: str, behind: int):
        super().__init__(f"the branch is {behind} commit(s) behind {base}", hint="update the branch, then run the land again")
        self.base, self.behind = base, behind


BEHIND_TRIES = 4             # reads of the compare answer before the merge is refused


class Unknown(PlatformError):
    """GitHub gave no readable answer on whether the branch is behind its base: a merge on a guess is never done."""


def _behind(repo: Path, slug: str, url: str, head: str) -> tuple[int | None, str]:
    """(commits the head is behind its base, the base branch); None when GitHub gives no readable answer: that is unknown, not 0."""
    base = "main"
    try:
        base = json.loads(ship.gh(["pr", "view", url, "--json", "baseRefName"], cwd=repo, check=False) or "{}").get("baseRefName") or "main"
        out = ship.gh(["api", f"repos/{slug}/compare/{base}...{head}", "--jq", ".behind_by"], cwd=repo, check=False).strip()
    except Exception:  # noqa: BLE001
        return None, base
    return (int(out) if out.isdigit() else None), base


def _known(repo: Path, url: str, watch: ship.CheckWatch, interval: float) -> tuple[int, str, str]:
    """(behind, base, head): the head is read when it is not known yet, an unreadable answer is retried with a growing wait,
    and `Unknown` is raised when it stays unreadable."""
    backoff = max(interval, 1)
    for attempt in range(BEHIND_TRIES):
        head = watch.head or watch.head_sha()
        if head:
            behind, base = _behind(repo, slug_of(repo, url), url, head)
            if behind is not None:
                if watch.head is None:      # spec 171: the merge carries the head this answer was read for
                    watch.head = head
                return behind, base, head
        if attempt < BEHIND_TRIES - 1:
            ship.say(f"  could not tell whether {url} is behind its base; retrying in {int(backoff)}s")
            ship.sleep(backoff)
            backoff = min(backoff * 2, 60)
    raise Unknown(f"could not tell whether {url} is behind its base, so it is not merged",
                  hint="run the merge again; no pull request merges on a guess")


def await_change(watch: ship.CheckWatch, old: str, timeout: float, interval: float) -> None:
    """Poll until the head of the pull request differs from `old`, bounded by the wait timeout."""
    begin = ship.now()
    while watch.head_sha() in (None, old):
        if ship.now() - begin > timeout:
            raise PlatformError(f"GitHub does not show the updated head of {watch.pr}", hint="run the land again")
        ship.sleep(interval)


class PromptsOver(PlatformError):
    """The base and the branch each fit the prompt byte baseline, the two together do not (#1076)."""

    def __init__(self, url: str, base: str, total: int, baseline: int):
        super().__init__(f"{url} merged with {base} would make the prompts {total} bytes, {total - baseline} more than the "
                         f"baseline {baseline}; the update is not made",
                         hint=f"shorten the prompts on the branch by {total - baseline} bytes or more (or rebaseline them), push, "
                              "then run the land again")


def _merged_prompt_bytes(repo: Path, base: str, head: str) -> tuple[int, int] | None:
    """(prompt bytes, baseline) of the tree the update would make, from `git merge-tree` without touching the checkout;
    None when it cannot be told (no remote, a conflict, an old git): the update then goes on as before."""
    import promptrules
    try:
        if run(["git", "fetch", "-q", "origin", base, head], cwd=repo, check=False).returncode != 0:
            return None
        res = run(["git", "merge-tree", "--write-tree", f"origin/{base}", head], cwd=repo, check=False)
        if res.returncode != 0:
            return None
        tree = (res.stdout or "").split()[0]
        files = run(["git", "ls-tree", "-r", "-l", tree, "--", "plugins"], cwd=repo, check=False).stdout or ""
        total = 0
        for line in files.splitlines():
            meta, _, path = line.partition("\t")
            if promptrules.PROMPT.match(path):
                total += int(meta.split()[3])
        reg = run(["git", "show", f"{tree}:{promptrules.REGISTER}"], cwd=repo, check=False)
        data = yaml.safe_load(reg.stdout or "") if reg.returncode == 0 else None
        limit = ((data or {}).get("baseline") or {}).get("prompt_bytes") if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None
    return (total, int(limit)) if isinstance(limit, int) and total else None


def _verdict(r: e2e_gate.Range, e2e_head: str, new: str) -> tuple[bool, str, str]:
    """(kept, "out" | "in" | "unknown", the line to print) for the base commits since the head whose e2e ran."""
    scope = r.scope
    if scope.run is False:
        return True, "out", f"e2e: kept the green e2e of {e2e_head[:7]}; {r.commits} commit(s) since are outside the e2e scope"
    if scope.run is None:
        return False, "unknown", f"e2e: waiting for the e2e of {new[:7]}: the e2e scope could not be decided ({scope.error})"
    more = f" (and {len(scope.reasons) - 1} more)" if len(scope.reasons) > 1 else ""
    first = scope.reasons[0] if scope.reasons else "the range"
    return False, "in", f"e2e: waiting for the e2e of {new[:7]}: {first} is inside the e2e scope{more}"


def _e2e_ran(repo: Path, url: str, names: frozenset[str], cs: list[dict] | None = None) -> bool:
    if not names:
        return False
    try:
        return e2e_gate.ran(ship.checks(repo, url) if cs is None else cs, names)
    except ship.GhError:
        return False


def catch_up(repo: Path, url: str, watch: ship.CheckWatch, timeout: float, interval: float, allow: bool = True,
             hold: Hold | None = None) -> CatchUp:
    """Inside the lock, before the merge: a branch behind its base is updated (a merge commit on the branch, never a force
    push) and the checks of its new head are waited for; the first red one ends it. A conflict raises `Conflict`.
    A head that is not known yet is read; an unreadable answer raises `Unknown` and nothing merges.

    With a `hold` (spec 220) in a repo with an e2e workflow: a head whose e2e ran and passed keeps that e2e while the base
    moved only outside the e2e scope (`CatchUp.kept`: the new head's e2e is not waited for). A wait that includes the e2e
    runs under a claim (`Hold.waiting`, at most MAX_CLAIMED_ROUNDS times), and the base is looked at again after it."""
    behind, base, head = _known(repo, url, watch, interval)
    if behind <= 0:
        return CatchUp()
    stats = hold.stats if hold is not None else LandStats()
    slug = slug_of(repo, url)
    names = e2e_gate.workflows(repo) if hold is not None and e2e_gate.local(repo, slug) else frozenset()
    e2e_head = head if _e2e_ran(repo, url, names) else ""      # the head whose e2e really ran and passed
    out = CatchUp()
    claimed = 0
    while True:
        if not allow:
            raise Behind(base, behind)
        merged = _merged_prompt_bytes(repo, base, head)
        if merged and merged[0] > merged[1]:
            raise PromptsOver(url, base, *merged)
        scope = e2e_gate.range_scope(repo, url, base, e2e_head) if e2e_head else None
        watch.expect_from_current()
        res = run(["gh", "pr", "update-branch", url], cwd=repo, check=False)
        if res.returncode != 0:
            detail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
            raise Conflict(f"{url} conflicts with {base}: a human decision ({detail[0]})",
                           hint="resolve the conflict on the branch, then run the merge again")
        out.updated = True
        out.lines.append(f"{url} was behind {base}: updated, waiting for its checks again")
        await_change(watch, head, timeout, interval)      # the update is visible as a new head commit
        new = watch.head_sha() or ""
        kept = False
        if scope is not None:
            kept, verdict, line = _verdict(scope, e2e_head, new)
            ship.say(line)
            worse = {"out": 0, "unknown": 1, "in": 2}       # the land's range is as in as its worst round
            if stats.range_scope is None or worse[verdict] > worse[stats.range_scope]:
                stats.range_scope = verdict
        if kept:
            watch.skip_workflows(new, names)
        claim = hold is not None and bool(e2e_head) and claimed < MAX_CLAIMED_ROUNDS
        claimed += claim
        with hold.waiting(url, claim) if hold is not None else contextlib.nullcontext():
            began = time.monotonic()
            while True:
                out.status, out.cs, out.failed = ship.wait_checks(watch, timeout, interval)
                if out.status == "red" or watch.head_sha() in (None, watch.head):
                    break                      # a push during the last poll means the green belongs to an old head: wait again
            stats.catch_up_s += time.monotonic() - began
        stats.catch_up_e2e = stats.catch_up_e2e or (bool(e2e_head) and not kept)
        stats.e2e_kept = kept and out.status != "red"
        if out.status == "red":
            return out
        out.kept = names if kept else frozenset()
        if not kept and _e2e_ran(repo, url, names, out.cs):
            e2e_head = watch.head or new
        if hold is None:
            break
        behind, base, head = _known(repo, url, watch, interval)      # the base may have moved during a claimed wait (AC-220.5)
        if behind <= 0:
            break
    out.lines.append(f"GREEN: all {len(out.cs)} check(s) passed on {url} after the update")
    return out
