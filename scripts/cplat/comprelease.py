"""`cplat component release target|wait|gates`: the commit a component release tags (spec 138, #426), the wait for `main`'s
`ci` run on it before the tag (spec 143), and the decision whether that green run stands in for the release gates (`gates`,
spec 186: exit 0 reuse, 1 run them locally, 2 still running).

A release tag never rebuilds: CI gives the `sha-<40>` image of the tagged commit its `X.Y.Z` tags, and prod is refused unless
that digest is the one staging runs (spec 106). So the release tags the commit staging runs; a component without staging (a
library, or a repo not linked to a gitops-app) tags `main`'s head. The CHANGELOG and the next development version follow in
a PR after the tag (the release agent), never before it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import PlatformError, run

SHA_PIN = re.compile(r"^sha-([0-9a-f]{40})$")
RELEASE_TAG = "v[0-9]*.[0-9]*.[0-9]*"
FOLLOW_UP = re.compile(r"^chore\(release\)", re.I)
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
AFTER_SHOWN = 10


def _git(repo: Path, *args: str, check: bool = True) -> str:
    r = run(["git", *args], cwd=repo, check=False)
    if check and r.returncode != 0:
        raise PlatformError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip() if r.returncode == 0 else ""


def shape_of(repo: Path) -> tuple[str, bool]:
    """(shape, deployable) of the repo; tests replace this."""
    import shapecmd
    r = shapecmd.route(repo)
    return r["shape"], bool(r["deployable"])


def staging_pin(repo: Path, apps: list[str], service: str) -> str | None:
    """The image tag the linked gitops-app pins staging to (sha-<40> for a build of main), or None; tests replace this."""
    import smoke
    return smoke.pinned_image(repo, apps, service, "staging")


def _apps(repo: Path) -> list[str]:
    import ship
    return ship.gitops_apps(repo)


def _service(repo: Path) -> str:
    import ship
    return ship.service_name(repo)


def next_dev(version: str, shape: str, repo: Path) -> dict | None:
    """The version file and the next development version the follow-up PR writes after tag `version`, or None (Go, and a
    library that reads its version from the tag)."""
    m = SEMVER.match(version)
    if not m:
        raise PlatformError(f"not a release version: {version}")
    major, minor, patch = map(int, m.groups())
    base = f"{major}.{minor}.{patch + 1}"
    if shape in ("service-python", "library-python"):
        py = repo / "pyproject.toml"
        project = py.read_text().split("[project]", 1)[-1].split("\n[", 1)[0] if py.is_file() else ""
        if re.search(r"^dynamic\s*=.*\bversion\b", project, re.M):
            return None
        return {"file": "pyproject.toml", "next": f"{base}.dev0"}
    if shape == "service-java":
        return {"file": "pom.xml", "next": f"{base}-SNAPSHOT"}
    if shape == "web-nextjs":
        return {"file": "package.json", "next": f"{base}-dev.0"}
    return None


def target(repo: Path) -> dict:
    """The release decision: {"ok": True, ...} or {"ok": False, "reason", "staging", "candidate", "next"}. Changes nothing
    but the fetched refs."""
    _git(repo, "fetch", "-q", "origin", "--tags", check=False)
    head = _git(repo, "rev-parse", "--verify", "-q", "origin/main^{commit}", check=False)
    shape, deployable = shape_of(repo)
    service = _service(repo)

    def refuse(reason: str, staging: str | None) -> dict:
        cand = head or "none"
        nxt = (f"promote {cand} to staging in the gitops-app (/instance:promote {service} --to staging --sha {cand}), "
               "verify it (/instance:verify staging), then run /component:release again.")
        return {"ok": False, "reason": reason, "staging": staging, "candidate": head or None, "next": nxt}

    if not head:
        return refuse("no origin/main: fetch the repo's main from GitHub first", None)
    apps = _apps(repo)
    pin: str | None = None
    if not deployable:
        kind = "library" if "library" in shape else shape
        commit, source, why = head, "main", f"a {kind} ({shape}) is not deployed, so it has no staging environment"
    elif not apps:
        commit, source, why = head, "main", "the repo is not linked to a gitops-app (no .platform-app.yml), so it has no staging"
    else:
        try:
            pin = staging_pin(repo, apps, service)
        except Exception as e:  # noqa: BLE001  (an unreadable pin refuses; it never guesses a commit)
            return refuse(f"cannot read the staging pin of {service}: {e}", None)
        if not pin:
            return refuse(f"no staging instance of {service} in {', '.join(apps)}", None)
        m = SHA_PIN.match(pin)
        if not m:
            return refuse(f"staging pins {pin}, not a sha-<40> build of main", pin)
        commit, source = m.group(1), "staging"
        why = (f"the commit staging runs ({pin}): CI re-tags its image without a rebuild, so prod gets the digest staging "
               "tested (spec 106)")
        if _git(repo, "cat-file", "-t", commit, check=False) != "commit" or \
                run(["git", "merge-base", "--is-ancestor", commit, "origin/main"], cwd=repo, check=False).returncode != 0:
            return refuse(f"staging runs {commit}, which is not on main", commit)
    tagged = [t for t in _git(repo, "tag", "--points-at", commit, "--list", RELEASE_TAG, check=False).splitlines() if t]
    if tagged:
        return refuse(f"{commit} is already released as {tagged[0]}", commit if source == "staging" else None)
    previous = _git(repo, "describe", "--tags", "--abbrev=0", "--match", RELEASE_TAG, commit, check=False) or None
    rng = f"{previous}..{commit}" if previous else commit
    subjects = [s for s in _git(repo, "log", "--no-merges", "--reverse", "--format=%s", rng).splitlines() if s]
    new = [s for s in subjects if not FOLLOW_UP.match(s)]
    if not new:
        return refuse(f"nothing new since {previous or 'the start'} but release follow-up commits",
                      commit if source == "staging" else None)
    import releases
    version = "v" + releases.next_version(previous, new).lstrip("v") if previous else "v0.1.0"   # the templates declare 0.1.0
    after = [s for s in _git(repo, "log", "--no-merges", "--reverse", "--format=%s", f"{commit}..origin/main").splitlines() if s]
    return {"ok": True, "commit": commit, "source": source, "why": why, "version": version, "previous": previous,
            "subjects": new, "main": head, "after": after, "staging": pin, "shape": shape,
            "version_file": next_dev(version, shape, repo)}


def lines(d: dict) -> list[str]:
    if not d["ok"]:
        return [f"REFUSED: {d['reason']}", f"Staging commit: {d['staging'] or 'none'}",
                f"Candidate commit: {d['candidate'] or 'none'} (main's head)", f"Next: {d['next']}"]
    n = len(d["subjects"])
    out = [f"Release: {d['version']} (previous {d['previous'] or 'none: the first release'}, {n} commit{'s' if n != 1 else ''})"]
    if d["source"] == "staging":
        out.append(f"Tag: {d['commit']} — {d['why'].replace('its image', 'its image ' + d['version'].lstrip('v'), 1)}")
    else:
        out.append(f"Tag: {d['commit']} — main's head: {d['why']}; tagged after main's ci run on it passed")
    k = len(d["after"])
    if k:
        out.append(f"Main: {d['main']} — {k} commit{'s' if k != 1 else ''} after the tagged commit {'are' if k != 1 else 'is'} "
                   "not in this release")
        out += [f"  - {s}" for s in d["after"][:AFTER_SHOWN]]
        if k > AFTER_SHOWN:
            out.append(f"  … and {k - AFTER_SHOWN} more")
    else:
        out.append(f"Main: {d['main']} — nothing after the tagged commit")
    vf = d["version_file"]
    rel = d["version"].lstrip("v")
    if vf:
        out.append(f"Version file: {vf['file']} → {vf['next']} in the follow-up PR; the tagged commit's file shows the previous "
                   f"development version, the release version is the tag, the image's {rel} tag and the CHANGELOG")
    else:
        out.append(f"Version file: none (the version comes from the tag at build time); the release version is the tag, "
                   f"the image's {rel} tag and the CHANGELOG")
    return out


# ---------------- wait: main's ci run on the commit to tag (spec 143) ----------------

NO_RUN_GRACE = 120.0
RED_CONCLUSIONS = {"failure", "cancelled", "timed_out", "startup_failure"}


def ci_wait(repo: Path, sha: str, timeout: float, interval: float = 10.0, grace: float = NO_RUN_GRACE) -> tuple[int, list[str]]:
    """Wait for `main`'s `ci` push run on `sha`: GREEN 0, RED 1 (with the failed log), NO RUN 1 after `grace`, TIMEOUT 2."""
    import ship
    import waits
    slug, s7 = ship.service_slug(repo), sha[:7]
    begin, last, known = waits.now(), None, False
    while True:
        out = ship.gh(["run", "list", "-R", slug, "--workflow", "ci", "--branch", "main", "--commit", sha, "--event", "push",
                       "--json", "databaseId,status,conclusion"], cwd=repo, check=False)
        try:
            rs = json.loads(out or "[]")
        except ValueError:
            rs = []
        elapsed = waits.now() - begin
        if rs:
            seen = ", ".join(f"run {r.get('databaseId')}: {r.get('conclusion') or r.get('status')}" for r in rs)
            if seen != last:
                print(f"{waits.clock()} {seen}", file=sys.stderr, flush=True)
                last = seen
            failed = [r for r in rs if r.get("conclusion") in RED_CONCLUSIONS]
            if failed:
                rid = str(failed[0].get("databaseId"))
                return waits.RED, [f"RED: main's ci run {rid} on {s7} {failed[0]['conclusion']}; do not tag",
                                   *ship.run_logs(repo, [(slug, rid)])]
            if all(r.get("status") == "completed" for r in rs):
                return waits.REACHED, [f"GREEN: main's ci run on {s7} passed; its image can be tagged"]
        elif not known:                           # #614: a commit of another repo has no run here either
            args = ["api", f"repos/{slug}/commits/{sha}", "--jq", ".sha"]
            found = ship.gh(args, cwd=repo, check=False) or ""
            if not found.strip().startswith(s7) and re.search(r"No commit found|HTTP 404|HTTP 422",
                                                              ship.GH_ERRORS.get(" ".join(args[:2]), "")):
                return waits.RED, [f"NO COMMIT: {s7} is not a commit of {slug}; run this in the repo that has it "
                                   "(`--repo <clone>`); do not tag"]
            known = found.strip().startswith(s7)       # a network error asks again on the next poll
        if not rs and elapsed >= grace:
            return waits.RED, [f"NO RUN: no ci run on main for {s7} after {int(grace)}s (a commit that changes only Markdown "
                               "builds no image); do not tag"]
        left = timeout - elapsed
        if left <= 0:
            return waits.TIMEOUT, [f"TIMEOUT: main's ci run on {s7} is still running after {int(timeout)}s",
                                   "run the same wait again"]
        waits.sleep(min(interval, left))


# ---------------- gates: reuse main's green ci run or run the gates locally (spec 186) ----------------

MAX_AGE_DAYS = 7
GATES = ("quality", "test", "security")


def _gh_json(repo: Path, args: list[str]) -> object:
    import ship
    key = " ".join(args[:2])
    ship.GH_ERRORS.pop(key, None)
    out = ship.gh(args, cwd=repo, check=False)
    err = ship.GH_ERRORS.get(key, "")
    if err or not out:
        raise PlatformError((err or "no answer from gh").splitlines()[-1])
    try:
        return json.loads(out)
    except ValueError as e:
        raise PlatformError(f"unreadable answer from gh: {e}") from e


def _decision(reuse: bool, reason: str | None, run: dict | None = None, jobs: list[dict] | None = None,
              line: str | None = None) -> dict:
    return {"reuse": reuse, "line": line or f"gates: run locally ({reason})", "reason": reason, "run": run,
            "jobs": jobs or []}


def gates(repo: Path, sha: str, timeout: float, interval: float = 10.0, now: datetime | None = None) -> tuple[int, dict]:
    """Decide whether `main`'s `ci` run on `sha` stands in for the release gates: (0, reuse), (1, run locally), (2, timeout)."""
    import ship
    import waits
    slug, s7 = ship.service_slug(repo), sha[:7]
    begin = waits.now()
    try:
        while True:
            runs = _gh_json(repo, ["run", "list", "-R", slug, "--workflow", "ci", "--branch", "main", "--commit", sha,
                                   "--event", "push", "--json", "databaseId,status,conclusion,attempt,updatedAt,url"])
            if not isinstance(runs, list) or not runs:
                return 1, _decision(False, f"no ci run on main for {s7}")
            latest = max(runs, key=lambda r: r.get("databaseId") or 0)
            if latest.get("status") == "completed":
                break
            left = timeout - (waits.now() - begin)
            if left <= 0:
                return 2, {"timeout": [f"TIMEOUT: main's ci run on {s7} is still running after {int(timeout)}s",
                                       "run the same call again"]}
            waits.sleep(min(interval, left))
        rid = latest["databaseId"]
        view = _gh_json(repo, ["run", "view", str(rid), "-R", slug, "--json",
                               "databaseId,attempt,conclusion,updatedAt,url,jobs"])
        if not isinstance(view, dict):
            raise PlatformError("unreadable run view")
        finished = view.get("updatedAt") or latest.get("updatedAt") or ""
        info = {"id": rid, "url": view.get("url") or latest.get("url"), "attempt": view.get("attempt"),
                "conclusion": view.get("conclusion"), "finished_at": finished}
        jobs = [{"name": j.get("name", ""), "conclusion": j.get("conclusion")} for j in view.get("jobs") or []]
    except (PlatformError, KeyError, TypeError, ValueError) as e:
        return 1, _decision(False, f"cannot read the ci runs: {e}")

    def local(reason: str) -> tuple[int, dict]:
        return 1, _decision(False, reason, info, jobs)
    if info["conclusion"] != "success":
        return local(f"ci run {rid} {info['conclusion']} on attempt {info['attempt']}")
    try:
        age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return local(f"cannot read the ci runs: bad finish time {finished!r}")
    if age > timedelta(days=MAX_AGE_DAYS):
        return local(f"ci run {rid} finished {age.days} days ago (more than {MAX_AGE_DAYS})")
    wanted = list(GATES)
    if run(["git", "cat-file", "-e", f"{sha}:Dockerfile"], cwd=repo, check=False).returncode == 0:
        wanted.append("docker")
    used: list[str] = []
    for g in wanted:
        mine = [j for j in jobs if j["name"] == g or j["name"].startswith(g + " ")]
        if not mine:
            return local(f"gate {g} has no job in ci run {rid}")
        for j in mine:
            if j["conclusion"] != "success":
                return local(f"gate job {j['name']} {j['conclusion']} in ci run {rid}")
        used += [j["name"] for j in mine]
    order = [j["name"] for j in jobs if j["name"] in used]
    line = f"gates: reused CI run {info['url']} on {s7} ({', '.join(order)})"
    return 0, _decision(True, None, info, jobs, line)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat component release", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("target", help="the commit to tag (staging's, or main's head without staging) and the version")
    p.add_argument("--repo", default=".")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("wait", help="wait for main's ci run on the commit to tag (spec 143)")
    p.add_argument("--commit", required=True)
    p.add_argument("--timeout", type=float, default=540.0)
    p.add_argument("--interval", type=float, default=10.0, help=argparse.SUPPRESS)
    p.add_argument("--repo", default=".")
    p = sub.add_parser("gates", help="reuse main's green ci run on the commit as the release gates, or run them locally (spec 186)")
    p.add_argument("--commit", required=True)
    p.add_argument("--timeout", type=float, default=540.0)
    p.add_argument("--interval", type=float, default=10.0, help=argparse.SUPPRESS)
    p.add_argument("--repo", default=".")
    p.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    if ns.cmd == "gates":
        import waits
        repo = Path(ns.repo).resolve()

        def decide() -> tuple[int, str]:
            code, d = gates(repo, ns.commit, ns.timeout, ns.interval)
            if code == 2:
                print("\n".join(d["timeout"]), flush=True)
            else:
                print(json.dumps(d, indent=2) if ns.json else d["line"], flush=True)
            return code, "timeout" if code == 2 else ("reached" if code == 0 else "red")
        return waits.record(repo, "component release gates", decide)
    if ns.cmd == "wait":
        import waits
        repo = Path(ns.repo).resolve()

        def body() -> tuple[int, str]:
            code, out = ci_wait(repo, ns.commit, ns.timeout, ns.interval)
            print("\n".join(out), flush=True)
            return code, waits.RESULTS[code]
        return waits.record(repo, "component release wait", body)
    d = target(Path(ns.repo).resolve())
    print(json.dumps(d, indent=2) if ns.json else "\n".join(lines(d)))
    return 0 if d["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
