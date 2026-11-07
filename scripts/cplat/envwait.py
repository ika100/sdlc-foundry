"""`system wait` and `cluster wait` (spec 143): block until Argo CD runs what `main` of the gitops repo says.

  cplat system wait --env <env> [<component>…] [--revision SHA] [--refresh] [--timeout S] [--context C] [--repo-dir DIR]
  cplat cluster wait [--refresh] [--timeout S] [--context C] [--repo-dir DIR]

An app is in its wanted state when Argo CD synced it to the wanted revision (default: the head of `main` on GitHub when the
wait starts, read with one `git fetch`; a later commit that contains it also counts), it is Synced and Healthy, and a
component's app runs the image tag that revision pins for it (the image rule of `cplat component ship deploy`, spec 077).
One line each time an app's state changes; exit 0 READY, 1 RED (a sync error, a failed sync or Degraded at the wanted
revision; a ComparisonError with a network cause only when it lasts until the timeout, #506), 2 TIMEOUT (one line per app behind; the command with `--refresh` when Argo CD has not picked up the revision).
`--refresh` asks Argo CD once for a hard refresh of each app not yet at the revision. A context that is not the system's
cluster, a cluster that does not answer, or no Argo CD exits 1 at once.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

import gitops
import model
import settings
import ship
import waits
from core import PlatformError, run

ROOTS = ("platform-operators", "platform-systems")     # the cluster repo's own applications (spec 125, scripts/render.py)
REFRESH = "argocd.argoproj.io/refresh=hard"
# Spec 148 (#542): an app still behind (or not generated yet) this long into the wait gets one hard refresh, and so does the
# system's root app: Argo CD polls git every 3 minutes, and a root app whose repo fetch timed out never generates the app.
AUTO_REFRESH_AFTER = 45.0
NO_ARGO = re.compile(r"doesn't have a resource type|the server could not find the requested resource|namespaces? \"?argocd\"? not found",
                     re.I)
# A ComparisonError whose cause is the network (#506): Argo CD could not reach the repo and retries by itself, so the wait keeps
# waiting; one still there at the timeout is RED with its message.
NETWORK = re.compile(r"i/o timeout|connection (?:reset|refused|timed out)|TLS handshake timeout|context deadline exceeded"
                     r"|temporary failure in name resolution|server misbehaving|lookup \S+ on \S+: no such host|network is unreachable"
                     r"|no route to host", re.I)


def kubectl(args: list[str], context: str | None = None, check: bool = False) -> subprocess.CompletedProcess:  # tests replace this
    cmd = ["kubectl", *(["--context", context] if context else []), *args]
    try:
        return run(cmd, check=check, timeout=30)
    except PlatformError as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=repo, check=check)


@dataclass(frozen=True)
class Target:
    app: str
    tag: str | None = None       # the image tag (or digest) the wanted revision pins: components only
    component: bool = False
    name: str = ""               # the component and environment, to read the pin of a later revision
    env: str = ""


# ---------------- the wanted revision: one ask of GitHub ----------------

def _fetch(repo: Path) -> None:
    p = git(repo, "fetch", "-q", "origin", "main")
    if p.returncode != 0:
        line = next((ln for ln in (p.stderr or "").splitlines() if ln.strip()), "unknown error")
        raise PlatformError(f"cannot read the head of main from GitHub: git fetch origin main failed: {line}",
                            hint="check the network and the repo's origin, then run the wait again")


def wanted_revision(repo: Path, revision: str | None) -> str:
    """The commit to wait for: `revision` (fetched only when the clone lacks it), else the head of `main` on GitHub."""
    if revision:
        p = git(repo, "rev-parse", "--verify", "-q", f"{revision}^{{commit}}")
        if p.returncode != 0:
            _fetch(repo)
            p = git(repo, "rev-parse", "--verify", "-q", f"{revision}^{{commit}}")
        if p.returncode != 0:
            raise PlatformError(f"unknown revision {revision}", hint="pass a commit of the gitops repo's main")
        return p.stdout.strip()
    _fetch(repo)
    return git(repo, "rev-parse", "origin/main", check=True).stdout.strip()


class Ancestry:
    """Whether a revision Argo CD reports is the wanted one or a later commit that contains it, decided locally."""

    def __init__(self, repo: Path, wanted: str):
        self.repo, self.wanted, self.seen = repo, wanted, {wanted: True}

    def __call__(self, rev: str | None) -> bool:
        if not rev:
            return False
        if rev not in self.seen:
            p = git(self.repo, "merge-base", "--is-ancestor", self.wanted, rev)
            # 0: contains it; 1: does not; otherwise the clone does not know `rev`: newer than the fetch, so it contains it
            self.seen[rev] = p.returncode != 1
        return self.seen[rev]


def _reader(repo: Path, rev: str):
    def read(path: str) -> dict | None:
        p = git(repo, "show", f"{rev}:{path}")
        if p.returncode != 0:
            return None
        try:
            doc = yaml.safe_load(p.stdout)
        except yaml.YAMLError:
            return None
        return doc if isinstance(doc, dict) else None
    return read


# ---------------- which apps ----------------

def env_targets(repo: Path, system: str | None, rev: str, env: str, names: list[str]) -> tuple[str, list[Target], set[str]]:
    """(system, the apps to wait for, every Argo CD app of the system in any environment) at revision `rev`."""
    if not system:
        system = gitops.find_app(repo, None).name
    m = model.load_remote(system, _reader(repo, rev))
    envs = [e.name for e in m.environments]
    if env not in envs:
        raise PlatformError(f"no environment '{env}' in system {system}", hint="environments: " + ", ".join(envs))
    every = {i.argo_application for i in m.instances} | {r.argo_application for r in m.resource_instances if r.argo_application}
    insts = m.instances_in(env)
    if names:
        unknown = [n for n in names if not any(i.component == n for i in insts)]
        if unknown:
            raise PlatformError(f"no instance of {', '.join(unknown)} in {env}",
                                hint="components with an instance there: " + (", ".join(i.component for i in insts) or "none"))
        insts = [i for i in insts if i.component in names]
    out = [Target(i.argo_application, i.tag, True, i.component, env) for i in insts]
    if names:
        return system, out, every
    out += [Target(r.argo_application) for r in m.resource_instances if r.environment == env and r.argo_application]
    e = m.environment(env)
    if e and e.observability and e.observability.argo_application and insts:
        out.append(Target(e.observability.argo_application))
    return system, out, every


# ---------------- the cluster ----------------

def list_apps(ctx: str) -> dict[str, dict]:
    """Argo CD application -> status; raises naming the problem and the context."""
    p = kubectl(["-n", "argocd", "get", "applications", "-o", "json"], ctx)
    if p.returncode != 0:
        err = next((ln.strip() for ln in (p.stderr or "").splitlines() if ln.strip()), "no answer")
        if NO_ARGO.search(err):
            raise PlatformError(f"no Argo CD in context {ctx}: {err}", hint="install Argo CD (devbox run cluster-up locally), or pass --context")
        raise PlatformError(f"the cluster of context {ctx} does not answer: {err}",
                            hint="start the cluster (devbox run cluster-up locally), or pass --context <the cluster's context>")
    try:
        items = json.loads(p.stdout or "{}").get("items") or []
        return {i["metadata"]["name"]: i.get("status") or {} for i in items}
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise PlatformError(f"cannot read the Argo CD applications of context {ctx}: {e}") from None


def resolve_context(repo: Path, explicit: str | None, known: set[str], what: str) -> tuple[str, dict[str, dict]]:
    """(context, its applications). Without --context the configured or current context must hold one of `known`."""
    ctx, source = explicit, "--context"
    if not ctx:
        ctx, source = settings.kube_context(repo)
    if not ctx:
        p = kubectl(["config", "current-context"])
        ctx, source = (p.stdout.strip() if p.returncode == 0 else ""), "the current context"
    if not ctx:
        raise PlatformError("no kube context", hint="pass --context <name>, or select one: kubectl config use-context <name>")
    items = list_apps(ctx)
    if not explicit and known and not known & set(items):
        raise PlatformError(f"context {ctx} ({source}) is not the cluster of {what}: none of its Argo CD applications is there "
                            f"(for example {sorted(known)[0]})", hint="pass --context <the cluster's context>")
    return ctx, items


# ---------------- one app's state ----------------

def _matches(images: list[str], tag: str) -> bool:
    if tag.startswith("sha256:"):
        return any(f"@{tag}" in i for i in images)
    tags = {tag}
    if re.fullmatch(r"sha-[0-9a-f]{40}", tag):
        tags.add(tag[:11])                      # spec 077: the short build tag names the same build
    return any(i.rsplit("@", 1)[0].rsplit(":", 1)[-1] in tags for i in images)


def _shown(images: list[str], tag: str | None) -> str:
    if not images:
        return "nothing"
    hit = next((i for i in images if tag and _matches([i], tag)), images[0])
    return waits.tag_short(hit.rsplit("@", 1)[-1] if "@" in hit else hit.rsplit(":", 1)[-1])


class Pins:
    """The tag a revision pins for a component: the wanted revision's, or a later revision's when the clone knows it."""

    def __init__(self, repo: Path, wanted: str, system: str | None):
        self.repo, self.wanted, self.system, self.cache = repo, wanted, system, {}
        self.refetched = False

    def __call__(self, t: Target, rev: str) -> str | None:
        if not t.component or not rev or rev == self.wanted or not self.system:
            return t.tag
        key = (rev, t.env, t.name)
        if key not in self.cache:
            if not self.refetched and git(self.repo, "cat-file", "-e", f"{rev}^{{commit}}").returncode != 0:
                self.refetched = True   # spec 154 (#558): Argo is at a commit newer than the fetch (a pin PR merged since)
                try:
                    _fetch(self.repo)
                except PlatformError:
                    pass
            read = _reader(self.repo, rev)          # a revision the clone does not know reads as None: the wanted pin stays
            self.cache[key] = model.pin_of(read(f"applications/{self.system}/{model.pin_path(t.env, t.name)}"))
        return self.cache[key] or t.tag


def judge(t: Target, st: dict | None, wanted: str, at, ctx: str, pins=None) -> tuple[str, str, str]:
    """(kind: reached | behind | retrying | red, the progress line, what it waits for or why it is red). `retrying` is a
    ComparisonError with a network cause (#506): it waits like `behind` and turns RED at the timeout."""
    if st is None:
        return "behind", f"{t.app}: missing", "missing"
    sync = (st.get("sync") or {}).get("status") or "?"
    health = st.get("health") or {}
    hstatus = health.get("status") or "?"
    rev = (st.get("sync") or {}).get("revision") or ""
    tag = pins(t, rev) if pins else t.tag
    images: list[str] = []
    if t.component:
        images = list((st.get("summary") or {}).get("images") or []) or (ship.workload_images(ctx, st) if tag else [])
    line = f"{t.app}: {sync}/{hstatus} at {waits.short(rev)}" + (f", runs {_shown(images, tag)}" if t.component else "")
    if not at(rev):
        return "behind", line, f"waiting for revision {waits.short(wanted)}, Argo CD is at {waits.short(rev)}"
    errors = [c for c in st.get("conditions") or [] if str(c.get("type", "")).endswith("Error")]
    if errors:
        why = f"{errors[0]['type']}: {errors[0].get('message', '')}".strip()
        if errors[0]["type"] == "ComparisonError" and NETWORK.search(str(errors[0].get("message", ""))):
            return "retrying", line, why
        return "red", line, why
    op = st.get("operationState") or {}
    op_rev = (op.get("syncResult") or {}).get("revision") or ((op.get("operation") or {}).get("sync") or {}).get("revision")
    if op.get("phase") in ("Failed", "Error") and (not op_rev or at(op_rev)):
        return "red", line, f"sync {op['phase']}: {op.get('message', '')}".strip()
    if hstatus == "Degraded":
        return "red", line, "health Degraded" + (f": {health['message']}" if health.get("message") else "")
    if t.component and tag and not _matches(images, tag):
        return "behind", line, f"waiting for image {waits.tag_short(tag)}, runs {', '.join(images) or 'nothing'}"
    if (sync, hstatus) != ("Synced", "Healthy"):
        return "behind", line, f"{sync}/{hstatus}"
    return "reached", line, ""


# ---------------- the wait ----------------

def _refresh(names: list[str], ctx: str) -> None:
    for name in names:
        kubectl(["-n", "argocd", "annotate", "application", name, REFRESH, "--overwrite"], ctx)


def _errored(st: dict | None) -> bool:
    return any(str(c.get("type", "")) == "ComparisonError" for c in (st or {}).get("conditions") or [])


def watch(repo: Path, targets: list[Target], wanted: str, ctx: str, items: dict[str, dict], label: str, command: str,
          refresh: bool, timeout: float, interval: float, system: str | None = None) -> tuple[int, list[str]]:
    at, pins = Ancestry(repo, wanted), Pins(repo, wanted, system)
    w7 = waits.short(wanted)
    if refresh:
        behind = [t.app for t in targets if t.app in items and not at(((items[t.app].get("sync") or {}).get("revision")))]
        _refresh(behind, ctx)
        if behind:
            ship.say(f"asked Argo CD for a hard refresh of {', '.join(behind)} (not at {w7} yet)")
    begin = waits.now()
    auto_refreshed = refresh
    root = f"{system}-root" if system else None
    last: dict[str, str] = {}
    while True:
        states = [(t, *judge(t, items.get(t.app), wanted, at, ctx, pins)) for t in targets]
        for t, _, line, _ in states:
            if last.get(t.app) != line:
                ship.say(line)
                last[t.app] = line
        red = next(((t, why) for t, kind, _, why in states if kind == "red"), None)
        if red:
            rev = ((items.get(red[0].app) or {}).get("sync") or {}).get("revision")
            return waits.RED, [f"RED: {red[0].app} at {waits.short(rev)}: {red[1]}"]
        behind = [(t, why) for t, kind, _, why in states if kind in ("behind", "retrying")]
        if not behind:
            return waits.REACHED, [f"READY: {len(targets)} app(s) {label} run {w7}"]
        if not auto_refreshed and waits.now() - begin >= AUTO_REFRESH_AFTER:   # spec 148 (#542): once per wait
            auto_refreshed = True
            stale = [t.app for t, why in behind if t.app in items and (why.startswith("waiting for revision") or _errored(items[t.app]))]
            if root and root in items and (_errored(items[root]) or any(why == "missing" for _, why in behind)):
                stale.insert(0, root)
            if stale:
                _refresh(stale, ctx)
                ship.say(f"asked Argo CD for a hard refresh of {', '.join(stale)} (not at {w7} after {int(AUTO_REFRESH_AFTER)}s)")
        left = timeout - (waits.now() - begin)
        if left <= 0:
            flaky = next(((t, why) for t, kind, _, why in states if kind == "retrying"), None)
            if flaky:
                rev = ((items.get(flaky[0].app) or {}).get("sync") or {}).get("revision")
                return waits.RED, [f"RED: {flaky[0].app} at {waits.short(rev)}: {flaky[1]} (still failing after {int(timeout)}s)"]
            lines = [f"TIMEOUT: {len(behind)} of {len(targets)} app(s) {label} not ready after {int(timeout)}s (wanted revision {w7})"]
            lines += [f"  {t.app}: {why}" for t, why in behind]
            if not refresh and any(why.startswith("waiting for revision") for _, why in behind):
                lines += ["Argo CD has not picked up the revision yet; run it again with a hard refresh:", f"{command} --refresh"]
            return waits.TIMEOUT, lines
        waits.sleep(min(interval, left))
        try:
            items = list_apps(ctx)
        except PlatformError:
            pass                                  # a missed poll: the next one decides, the timeout ends it


def system_wait(repo: Path, ns: argparse.Namespace, command: str) -> tuple[int, list[str]]:
    wanted = wanted_revision(repo, ns.revision)
    system, targets, every = env_targets(repo, ns.system, wanted, ns.env, ns.components)
    ctx, items = resolve_context(repo, ns.context, every, f"system {system}")
    return watch(repo, targets, wanted, ctx, items, f"in {ns.env}", command, ns.refresh, ns.timeout, ns.interval, system)


def cluster_wait(repo: Path, ns: argparse.Namespace, command: str) -> tuple[int, list[str]]:
    if not (repo / "cluster.yaml").is_file():
        raise PlatformError(f"not a cluster repo: {repo} has no cluster.yaml", hint="run it in the cluster repo (/cluster:new creates one)")
    wanted = wanted_revision(repo, None)
    ctx, items = resolve_context(repo, ns.context, set(ROOTS), f"cluster repo {repo.name}")
    return watch(repo, [Target(r) for r in ROOTS], wanted, ctx, items, "of the cluster", command, ns.refresh, ns.timeout, ns.interval)


def main(argv: list[str]) -> int:
    kind, rest = argv[0], argv[1:]
    ap = argparse.ArgumentParser(prog=f"cplat {kind} wait", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if kind == "system":
        ap.add_argument("components", nargs="*", help="limit the wait to these components' apps")
        ap.add_argument("--env", required=True)
        ap.add_argument("--revision", help="wait for this commit of the gitops repo (default: the head of main on GitHub)")
        ap.add_argument("--system", help="the system, when the repo holds several")
    ap.add_argument("--refresh", action="store_true", help="ask Argo CD once for a hard refresh of each app behind the revision")
    ap.add_argument("--timeout", type=float, default=waits.DEFAULT_TIMEOUT)
    ap.add_argument("--interval", type=float, default=10.0, help=argparse.SUPPRESS)
    ap.add_argument("--context", help="kube context (default: the configured one, else the current one)")
    ap.add_argument("--repo-dir", default=".")
    ns = ap.parse_args(rest)
    repo = Path(ns.repo_dir).resolve()
    command = shlex.join(["cplat", kind, "wait", *rest])

    def body() -> tuple[int, str]:
        code, lines = (system_wait if kind == "system" else cluster_wait)(repo, ns, command)
        print("\n".join(lines), flush=True)
        return code, waits.RESULTS[code]
    return waits.record(repo, f"{kind} wait", body)
