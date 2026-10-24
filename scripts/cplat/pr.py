"""`pr wait`: wait for any pull request's CI and optionally merge it on green (spec 079).

  cplat pr wait <number|url> [-R owner/repo] [--merge] [--timeout S]

The same watch as `cplat ship land` (spec 072): one line per concluded check, the first red check ends the wait, a
stale or stuck run is rerun once, and a job that failed on a transient error (a download, a registry, the network)
is rerun once before it counts. Exit 0: green (and merged with --merge); 1: red, with the failing log tails.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import runs
import ship
from core import PlatformError, run


def url_of(pr: str, slug: str | None) -> str:
    if pr.startswith("https://"):
        return pr
    if slug:
        return f"https://github.com/{slug}/pull/{pr.lstrip('#')}"
    return pr.lstrip("#")


def wait(repo: Path, pr: str, merge: bool, timeout: float, interval: float, queue_timeout: float,
         slug: str | None = None) -> tuple[bool, list[str]]:
    """Spec 087: counts toward the repo's unfinished ship run, else records its own `pr-wait` run."""
    rid = runs.attach_point(repo)
    own = None if rid else runs.start("pr-wait", repo=slug or runs.repo_slug(repo))
    try:
        ok, lines = _wait(repo, pr, merge, timeout, interval, queue_timeout, rid or own)
    except BaseException:
        if own:
            runs.finish(own, "failed")
        raise
    if own:
        runs.finish(own, "done" if ok else "failed")
    return ok, lines


def _wait(repo: Path, pr: str, merge: bool, timeout: float, interval: float, queue_timeout: float,
          run_id: str | None) -> tuple[bool, list[str]]:
    view = json.loads(ship.gh(["pr", "view", pr, "--json", "state,url"], cwd=repo) or "{}")
    url = view.get("url") or pr
    if view.get("state") == "MERGED":
        return True, [f"{url} is already merged"]
    if view.get("state") == "CLOSED":
        raise PlatformError(f"{url} was closed without merging")
    status, cs, failed = ship.wait_checks(ship.CheckWatch(repo, url, queue_timeout, run_id), timeout, interval)
    if status == "red":
        return False, ship.red(repo, url, cs, failed)
    lines = [f"GREEN: all {len(cs)} check(s) passed on {url}"]
    if merge:
        res = run(["gh", "pr", "merge", url, "--squash", "--delete-branch"], cwd=repo, check=False)
        if res.returncode != 0:
            detail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
            raise PlatformError(f"merging {url} failed: {detail[0]}", hint="a conflict with main is a human decision")
        lines.append(f"merged {url} (squash)")
    return True, lines


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat pr", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("wait")
    p.add_argument("pr", help="PR number or URL")
    p.add_argument("-R", "--repo-slug", dest="slug", help="owner/repo when the PR is not in the current repo")
    p.add_argument("--merge", action="store_true", help="squash-merge (and delete the branch) when every check passed")
    p.add_argument("--timeout", type=float, default=3600)
    p.add_argument("--interval", type=float, default=20)
    p.add_argument("--queue-timeout", type=float, default=ship.QUEUE_TIMEOUT)
    p.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    ok, lines = wait(Path(ns.repo).resolve(), url_of(ns.pr, ns.slug), ns.merge, ns.timeout, ns.interval, ns.queue_timeout, ns.slug)
    print("\n".join(lines))
    return 0 if ok else 1
