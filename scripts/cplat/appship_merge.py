"""`cplat app-ship` merge slot (spec 097, ADR-042): the one place where a product run, and the repo ships it drives, merge
into the gitops-app. One at a time, in plan order; a PR that no longer merges cleanly is never merged or rebased."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import time
from collections.abc import Iterator
from pathlib import Path

import appship_state as state
import ship
from core import PlatformError

LOCK_FILE = "cplat-app-ship.lock"
UNKNOWN_POLLS = 3


def sleep(seconds: float) -> None:   # tests replace this
    time.sleep(seconds)


def lock_path(gitops_dir: Path) -> Path:
    # common dir ON PURPOSE (ADR-051): the merge slot must serialise merges across every checkout of a gitops-app
    return state.common_dir(gitops_dir) / LOCK_FILE


class Conflict(PlatformError):
    """The PR no longer merges cleanly; `after` is the last PR this product run merged."""

    def __init__(self, pr: str, after: str | None):
        self.pr, self.after = pr, after
        tail = f" after {after} merged" if after else ""
        super().__init__(f"gitops PR {pr} no longer merges cleanly{tail}",
                         hint="resolve the conflict in the gitops PR (a human decision), then resume the run")


def plan_index(gitops_dir: Path, repo_id: str) -> int:
    """The repo's position in the product plan's `repos`; the gitops entry (and anything unknown) is 0."""
    st = state.load_state(gitops_dir) or {}
    for i, r in enumerate(state.plan_repos(gitops_dir, st.get("spec", ""))):
        if r["id"] == repo_id:
            return 0 if r.get("shape") == "gitops-app" else i
    return 0


def _register(gitops_dir: Path, repo_id: str, index: int) -> None:
    def change(st: dict) -> None:
        st["waiting"] = [w for w in st.get("waiting") or [] if w.get("repo") != repo_id] + [{"repo": repo_id, "plan_index": index}]
    state.update(gitops_dir, change)


def _deregister(gitops_dir: Path, repo_id: str) -> None:
    def change(st: dict) -> None:
        st["waiting"] = [w for w in st.get("waiting") or [] if w.get("repo") != repo_id]
    state.update(gitops_dir, change)


def _ahead(gitops_dir: Path, repo_id: str, index: int) -> dict | None:
    st = state.load_state(gitops_dir) or {}
    return next((w for w in st.get("waiting") or [] if w.get("repo") != repo_id and w.get("plan_index", 0) < index), None)


@contextlib.contextmanager
def slot(gitops_dir: Path, repo_id: str, plan_index: int, timeout: float, interval: float = 5) -> Iterator[None]:
    """Hold the merge slot: served in plan order (the lowest plan index of the waiting repos first)."""
    _register(gitops_dir, repo_id, plan_index)
    try:
        begin = time.monotonic()
        with open(lock_path(gitops_dir), "a") as lock:
            while True:
                who = "another merge holds the slot"
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    held = False
                else:
                    held = True
                if held:
                    ahead = _ahead(gitops_dir, repo_id, plan_index)
                    if ahead is None:
                        break
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    who = f"{ahead['repo']} (plan position {ahead['plan_index']}) is waiting before it"
                if time.monotonic() - begin > timeout:
                    raise PlatformError(f"the gitops merge slot did not free up for {repo_id} within {int(timeout)}s: {who}",
                                        hint="run the command again; the repo ahead of it merges first")
                sleep(interval)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        _deregister(gitops_dir, repo_id)


def merge(gitops_dir: Path, pr: str, repo_id: str, *, cwd: Path) -> None:
    """Inside the slot: check mergeable, squash-merge, log. Never `--admin`, never a force-push."""
    view: dict = {}
    for attempt in range(UNKNOWN_POLLS):
        view = json.loads(ship.gh(["pr", "view", pr, "--json", "mergeable,state"], cwd=cwd) or "{}")
        if view.get("mergeable") != "UNKNOWN" or view.get("state") == "MERGED":
            break
        if attempt < UNKNOWN_POLLS - 1:
            sleep(2)                                   # GitHub computes mergeable lazily
    if view.get("state") != "MERGED":
        if view.get("mergeable") == "CONFLICTING":
            log = (state.load_state(gitops_dir) or {}).get("gitops_merged") or []
            raise Conflict(pr, log[-1]["pr"] if log else None)
        ship.gh(["pr", "merge", pr, "--squash", "--delete-branch"], cwd=cwd)

    def change(st: dict) -> None:
        st.setdefault("gitops_merged", []).append(
            {"pr": pr, "repo": repo_id, "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    state.update(gitops_dir, change)


def land(gitops_dir: Path, pr: str, repo_id: str, timeout: float, interval: float) -> tuple[bool, list[str]]:
    """Wait for every check of the gitops-app's own PR, then merge it through the slot. Red → (False, failed checks)."""
    view = json.loads(ship.gh(["pr", "view", pr, "--json", "state,isDraft"], cwd=gitops_dir) or "{}")
    if view.get("state") == "MERGED":
        return True, [f"{pr} is already merged"]
    if view.get("isDraft"):
        ship.gh(["pr", "ready", pr], cwd=gitops_dir, check=False)
    st = state.load_state(gitops_dir) or {}
    status, cs, failed = ship.wait_checks(ship.CheckWatch(gitops_dir, pr, ship.QUEUE_TIMEOUT, st.get("run_id")), timeout, interval)
    if status == "red":
        return False, ship.red(gitops_dir, pr, cs, failed)
    try:
        with slot(gitops_dir, repo_id, plan_index(gitops_dir, repo_id), timeout, interval):
            merge(gitops_dir, pr, repo_id, cwd=gitops_dir)
    except Conflict as e:
        return False, [str(e)]
    return True, [f"merged {pr}"]
