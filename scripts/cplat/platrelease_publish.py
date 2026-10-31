"""The post-merge part of `cplat platform release` (spec 129): the upgrade e2e on the merge commit, the gate, the tag stop,
the tag, the GitHub release and the release guard. Every step is entered from the state detected by platrelease_state."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

import core
import platrelease_changelog as changelog
import platrelease_state as st
import ship

APPEAR_WINDOW = 600     # seconds a workflow run may take to show up after its push
STOP_EXIT = 3


def wait_for_run(repo: Path, slug: str, list_args: list[str], select: Callable[[list[dict]], list[dict]],
                 timeout: float, interval: float) -> tuple[str, str]:
    """Poll the run list until a selected run appears (at most APPEAR_WINDOW), then follow the newest one (highest
    databaseId). (status, url) with status green | red | absent | timeout."""
    begin = ship.now()
    while True:
        runs = select(json.loads(ship.gh(list_args, cwd=repo) or "[]"))
        if runs:
            break
        if ship.now() - begin >= APPEAR_WINDOW:
            return "absent", ""
        ship.sleep(interval)
    newest = max(runs, key=lambda r: int(r["databaseId"]))
    url = newest.get("url", "")
    watch = ship.RunWatch(repo, slug, str(newest["databaseId"]), ship.QUEUE_TIMEOUT)
    begin = ship.now()
    while True:
        status = watch.poll()
        if status != "pending":
            return status, url
        if ship.now() - begin > timeout:
            return "timeout", url
        ship.sleep(interval)


def _upgrade_e2e(repo: Path, slug: str, sha: str, o) -> None:
    args = ["run", "list", "-R", slug, "--workflow", "e2e-upgrade.yml", "--commit", sha, "--event", "push",
            "--json", "databaseId,status,conclusion,url"]
    ship.say(f"waiting for the upgrade e2e on {sha[:7]}")
    status, url = wait_for_run(repo, slug, args, lambda rs: rs, o.timeout, o.interval)
    why = {"absent": f"did not start within {APPEAR_WINDOW // 60} minutes", "red": f"red: {url}",
           "timeout": f"still running after {int(o.timeout)}s"}.get(status)
    if why:
        raise core.PlatformError(f"upgrade e2e on {sha}: {why}")


def _gate(repo: Path, sha: str) -> None:
    rc, out = st.run_check(repo, [sys.executable, "scripts/release-check.py", "gate", sha])
    if out.strip():
        print(out.rstrip())
    if rc != 0:
        raise core.PlatformError("release-check gate failed")


def _notes(repo: Path, sha: str, version: str) -> str:
    text = core.run(["git", "show", f"{sha}:docs/CHANGELOG.md"], cwd=repo).stdout
    body = changelog.section_body(text, version)
    if not body:
        raise core.PlatformError(f"docs/CHANGELOG.md at {sha[:7]} has no ## [{version}] section to publish")
    return body


def _tag_stop(tag: str, sha: str, notes: str) -> int:
    print(f"CONFIRM: tag\n  tag: {tag}\n  merge commit: {sha}\n  release notes:\n--- release notes ---\n{notes}\n--- end ---\n"
          "  continue: cplat platform release --confirm tag")
    return STOP_EXIT


def _tag_check(repo: Path, tag: str, sha: str) -> bool:
    """AC-129.19: origin and local tag. True when the tag is already on origin at `sha`; raises when it is elsewhere."""
    on_origin = st._origin_tags(repo).get(tag)
    local = core.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"], cwd=repo, check=False).stdout.strip()
    for found in (on_origin, local):
        if found and found != sha:
            raise core.PlatformError(f"tag {tag} is on {found}, not on the release's merge commit {sha}")
    if on_origin:
        return True
    if not local:
        core.run(["git", "tag", "-a", tag, "-m", tag, sha], cwd=repo)
    return False


def _tag(repo: Path, tag: str, sha: str) -> None:
    if not _tag_check(repo, tag, sha):
        core.run(["git", "push", "origin", f"refs/tags/{tag}"], cwd=repo)
    print(f"tagged {tag} on {sha[:7]}")


def _release(repo: Path, slug: str, tag: str, version: str, sha: str) -> str:
    url = ship.gh(["release", "view", tag, "-R", slug, "--json", "url", "-q", ".url"], cwd=repo, check=False).strip()
    if url:
        return url
    gitdir = Path(core.run(["git", "rev-parse", "--absolute-git-dir"], cwd=repo).stdout.strip())
    path = gitdir / "RELEASE_NOTES.md"
    path.write_text(_notes(repo, sha, version) + "\n")
    out = ship.gh(["release", "create", tag, "-R", slug, "--title", tag, "--notes-file", str(path), "--verify-tag"], cwd=repo)
    return [ln for ln in out.splitlines() if ln.strip()][-1].strip()


def _guard(repo: Path, slug: str, tag: str, o) -> None:
    args = ["run", "list", "-R", slug, "--workflow", "release-guard.yml", "--event", "push", "--limit", "50",
            "--json", "databaseId,headBranch,status,conclusion,url"]
    ship.say(f"waiting for the release-guard run on {tag}")
    status, url = wait_for_run(repo, slug, args, lambda rs: [r for r in rs if r.get("headBranch") == tag],
                               o.timeout, o.interval)
    if status == "red":
        raise core.PlatformError(f"release-guard on {tag} is red: {url}; the tag and the release stay")
    if status == "absent":
        raise core.PlatformError(f"release-guard on {tag}: no run started within {APPEAR_WINDOW // 60} minutes")
    if status == "timeout":
        raise core.PlatformError(f"release-guard on {tag}: still running after {int(o.timeout)}s: {url}")


def continue_from(repo: Path, state: st.State, version: str, sha: str | None, o) -> int:
    """merged → tagged → guarding, from the phase the run starts in (or the merge just made)."""
    tag, slug = f"v{version}", ship.service_slug(repo)
    phase = state.phase
    release_url = state.release_url
    if phase == st.GUARD_RED:
        raise core.PlatformError(f"release-guard on {tag} is red: {(state.guard or {}).get('url')}; "
                                 "the tag and the release stay")
    if phase == st.MERGED:
        assert sha
        _upgrade_e2e(repo, slug, sha, o)
        _gate(repo, sha)
        if o.confirm != "tag":
            return _tag_stop(tag, sha, _notes(repo, sha, version))
        _tag(repo, tag, sha)
    if phase in (st.MERGED, st.TAGGED):
        assert sha
        release_url = _release(repo, slug, tag, version, sha)
        print(f"release: {release_url}")
    _guard(repo, slug, tag, o)
    print(f"RELEASED: {tag}\n  tag: https://github.com/{slug}/tree/{tag}\n  release: {release_url}")
    return 0
