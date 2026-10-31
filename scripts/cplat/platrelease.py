"""cplat platform release [--version X.Y.Z] [--dry-run] [--confirm merge|tag] [--timeout S] [--interval S] [--repo DIR]

Prepare, merge, tag and publish a platform release (spec 129). The progress is derived from git and GitHub on every run
(platrelease_state), never stored: a run that stopped continues at the first step not done. Two stops (exit 3) wait for
`--confirm merge` and `--confirm tag`. This module: preflight, dry run, prepare/commit/push/PR, the CI wait and the merge;
platrelease_publish: the upgrade e2e, the gate, the tag, the GitHub release and the release guard."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import core
import platrelease_changelog as changelog
import platrelease_state as st
import pr as prmod
import ship

E2E_NAME = "e2e upgrade (previous release → candidate)"   # the check name release-check.py uses (E2E_NAME)
CHANGELOG = "docs/CHANGELOG.md"
STOP_EXIT = 3


@dataclass
class Opts:
    version: str | None = None
    dry_run: bool = False
    confirm: str | None = None
    timeout: float = 5400
    interval: float = 20


def _git(repo: Path, *args: str, check: bool = True) -> str:
    return core.run(["git", *args], cwd=repo, check=check).stdout


# ---------------- preflight ----------------

def _preflight(repo: Path) -> None:
    for key in ("user.name", "user.email"):
        if not _git(repo, "config", key, check=False).strip():
            raise core.PlatformError("no git user for the DCO sign-off",
                                     hint=f"git config {key} <value>")
    dirty = [ln[3:] for ln in _git(repo, "status", "--porcelain").splitlines() if ln.strip()]
    if dirty:
        raise core.PlatformError("uncommitted changes: " + ", ".join(dirty))
    local = _git(repo, "rev-parse", "--verify", "-q", "refs/heads/main", check=False).strip()
    remote = _git(repo, "rev-parse", "origin/main").strip()
    if local != remote:
        raise core.PlatformError(f"local main {local[:7] or 'missing'} differs from origin/main {remote[:7]}")
    text = _git(repo, "show", f"origin/main:{CHANGELOG}", check=False)
    if not changelog.unreleased_body(text).strip():
        raise core.PlatformError(f"## [Unreleased] in {CHANGELOG} has no content")


# ---------------- prepare ----------------

def _check(repo: Path, cmd: list[str], name: str) -> None:
    rc, out = st.run_check(repo, cmd)
    if rc != 0:
        print(out.rstrip())
        raise core.PlatformError(f"{name} failed")


def _prepare(repo: Path, state: st.State, version: str) -> str:
    """idle/branch → the PR is open; returns the PR URL."""
    branch = f"release/{version}"
    if state.phase == st.IDLE:
        _git(repo, "switch", "-c", branch, "main")
    else:
        current = _git(repo, "branch", "--show-current").strip()
        dirty = [ln[3:] for ln in _git(repo, "status", "--porcelain").splitlines() if ln.strip()]
        if current != branch:
            if dirty:
                raise core.PlatformError("uncommitted changes: " + ", ".join(dirty))
            _git(repo, "switch", branch)
        else:
            other = [p for p in dirty if p != CHANGELOG]
            if other:
                raise core.PlatformError(f"{branch} has changes outside {CHANGELOG}: " + ", ".join(other))
    path = repo / CHANGELOG
    path.write_text(changelog.move_unreleased(path.read_text(), version, st.today().isoformat()))
    _check(repo, [sys.executable, "scripts/release-check.py", "rows", "--base", state.tag], "release-check rows")
    _check(repo, ["devbox", "run", "validate"], "devbox run validate")
    if int(_git(repo, "rev-list", "--count", "origin/main..HEAD").strip()) == 0:
        _git(repo, "add", CHANGELOG)
        _git(repo, "commit", "-s", "-m", f"chore: release {version}")
    _git(repo, "push", "-u", "origin", branch)
    body = (f"Release {version}: [Unreleased] of {CHANGELOG} moved under ## [{version}].\n"
            "Opened by cplat platform release.")
    out = ship.gh(["pr", "create", "--base", "main", "--head", branch, "--title", f"chore: release {version}",
                   "--body", body], cwd=repo)
    url = [ln for ln in out.splitlines() if ln.strip()][-1].strip()
    print(f"PR: {url}")
    return url


# ---------------- CI and merge ----------------

def _wait_pr(repo: Path, url: str, o: Opts, merge: bool, slug: str) -> None:
    ok, lines = prmod.wait(repo, url, merge, o.timeout, o.interval, ship.QUEUE_TIMEOUT, slug)
    if not ok:
        print("\n".join(lines))
        raise core.PlatformError(f"CI is red on {url}: not merged")


def _wait_e2e(repo: Path, url: str, o: Opts) -> None:
    """The upgrade e2e is the long check: poll it on the interval (bounded by --timeout) while it runs and nothing is red;
    pr.wait then judges every check."""
    begin = ship.now()
    while True:
        cs = ship.checks(repo, url)
        if any(c.get("bucket") == "fail" for c in cs):
            return
        if not any(c.get("name") == E2E_NAME and c.get("bucket") == "pending" for c in cs):
            return
        if ship.now() - begin > o.timeout:
            raise core.PlatformError(f"the upgrade e2e on {url} is still running after {int(o.timeout)}s")
        ship.sleep(o.interval)


def _ci_and_merge(repo: Path, url: str, version: str, o: Opts) -> tuple[bool, str | None]:
    """Wait for CI on the PR. (False, None) at the merge stop; (True, sha) once merged."""
    slug = ship.service_slug(repo)
    _wait_e2e(repo, url, o)
    _wait_pr(repo, url, o, False, slug)
    cs = ship.checks(repo, url)
    if not any(c.get("name") == E2E_NAME and c.get("bucket") == "pass" for c in cs):
        raise core.PlatformError(f"the upgrade e2e did not run on {url}")
    if o.confirm != "merge":
        passed = sum(1 for c in cs if c.get("bucket") == "pass")
        print(f"CONFIRM: merge\n  version: {version}\n  PR: {url}\n"
              f"  checks: {passed} passed (newest run of each workflow), {E2E_NAME}: pass\n"
              "  continue: cplat platform release --confirm merge")
        return False, None
    _wait_pr(repo, url, o, True, slug)
    sha = ship.gh(["pr", "view", url, "--json", "mergeCommit", "-q", ".mergeCommit.oid"], cwd=repo).strip()
    _git(repo, "fetch", "origin", "main")
    for args in (("switch", "main"), ("merge", "--ff-only", "origin/main")):
        p = core.run(["git", *args], cwd=repo, check=False)
        if p.returncode != 0:
            ship.say(f"note: local main not updated (git {' '.join(args)}): {(p.stderr or p.stdout).strip()}")
            break
    return True, sha


# ---------------- publish hand-over ----------------

def _publish(repo: Path, state: st.State, version: str, sha: str | None, o: Opts) -> int:
    """merged, tagged, guarding, guard-red: the post-merge part (platrelease_publish)."""
    import platrelease_publish as pub

    return pub.continue_from(repo, state, version, sha, o)


# ---------------- main ----------------

def _parse(argv: list[str]) -> tuple[Opts, Path]:
    ap = argparse.ArgumentParser(prog="cplat platform release", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirm", choices=["merge", "tag"])
    ap.add_argument("--timeout", type=float, default=5400)
    ap.add_argument("--interval", type=float, default=20)
    ap.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    return Opts(ns.version, ns.dry_run, ns.confirm, ns.timeout, ns.interval), Path(ns.repo)


def main(argv: list[str]) -> int:
    o, repo = _parse(argv)
    mism = changelog.plugin_mismatches(repo)
    if mism:
        raise core.PlatformError("\n".join(mism))
    if o.version is not None:
        st.check_syntax(o.version)
    st.fetch(repo)
    state = st.detect(repo)
    changes: list[str] = []
    if state.phase == st.IDLE:
        changes = st.needs_major(repo, state.tag)
        if o.version:
            version, reason = o.version, "--version"
        else:
            version, reason = st.proposal(state.tag, changes)
    else:
        version, reason = state.version or "", "release in flight"
    sha = state.merged_sha if state.phase in (st.MERGED, st.TAGGED, st.GUARDING, st.GUARD_RED) else None
    texts = st.steps(state.phase, version, sha, st.today().isoformat())
    print("\n".join(st.render(state, version, reason, texts)))

    if o.version is not None:
        st.check_in_flight(o.version, state)
    if o.confirm == "merge" and state.phase != st.PR_OPEN:
        raise core.PlatformError(f"--confirm merge needs phase pr-open, this run starts in phase {state.phase}")
    if o.confirm == "tag" and state.phase != st.MERGED:
        raise core.PlatformError(f"--confirm tag needs phase merged, this run starts in phase {state.phase}")
    if state.phase == st.IDLE:
        if o.version is not None:
            st.check_version(o.version, state, changes)
        _preflight(repo)
    if state.phase == st.GUARD_RED and not o.dry_run:
        raise core.PlatformError(f"release-guard on {state.tag} is red: {(state.guard or {}).get('url')}; "
                                 "the tag and the release stay")
    if o.dry_run:
        return 0

    if state.phase in (st.IDLE, st.BRANCH):
        url = _prepare(repo, state, version)
    elif state.phase == st.PR_OPEN:
        url = state.pr["url"]
    else:
        return _publish(repo, state, version, sha, o)
    merged, sha = _ci_and_merge(repo, url, version, o)
    if not merged:
        return STOP_EXIT
    state.phase = st.MERGED
    return _publish(repo, state, version, sha, o)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
