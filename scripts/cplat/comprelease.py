"""`cplat component release target`: the commit a component release tags (spec 138, #426).

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


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat component release", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("target", help="the commit to tag (staging's, or main's head without staging) and the version")
    p.add_argument("--repo", default=".")
    p.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    d = target(Path(ns.repo).resolve())
    print(json.dumps(d, indent=2) if ns.json else "\n".join(lines(d)))
    return 0 if d["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
