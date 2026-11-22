"""`system wait` and `cluster wait` (spec 143): block until Argo CD runs what `main` of the gitops repo says.

  cplat system wait --env <env> [<component>…] [--revision SHA] [--refresh] [--timeout S] [--context C] [--repo-dir DIR]
  cplat cluster wait [<cluster>] [--refresh] [--timeout S] [--context C] [--repo-dir DIR]

An app is in its wanted state when Argo CD synced it to the wanted revision (default: the head of `main` on GitHub when the
wait starts, read with one `git fetch`; a later commit that contains it also counts), it is Synced and Healthy, and a
component's app runs the image tag that revision pins for it (the image rule of `cplat component ship deploy`, spec 077).
One line each time an app's state changes; exit 0 READY, 1 RED (a sync error, a failed sync or Degraded at the wanted
revision; a ComparisonError with a network cause only when it lasts until the timeout, #506), 2 TIMEOUT (one line per app behind; the command with `--refresh` when Argo CD has not picked up the revision).
Every wait asks Argo CD for a hard refresh of each app not yet at the revision when it starts and once more after 45 s (#867;
`--refresh` is kept and only drops the hint). A container of the version waited for that stays in ImagePullBackOff, ErrImagePull,
InvalidImageName or CrashLoopBackOff longer than 60 s is RED at once, naming pod, reason, image and the last event (#867), except an
image tag not in the registry while the component's CI run on main is queued or running (#892: it builds that image; one
`gh run list`, asked again at most once a minute while it runs, and 5 more minutes for the kubelet's pull back-off after it passed).
The pods of an external Helm entry's child Application (`<svc>-<env>-chart`) are read in that child's destination namespace (#883).
The pods of a database or other add-on app (pods named after one of its resources: a CloudNativePG cluster's instance and initdb
pods, a bucket's pods) in one of those states longer than 60 s are named on the app's progress line (#925): a missing tag or
manifest (or an invalid image name) is RED as for a component; a pull failing on the network reads "image pull failing: <cause>"
and keeps waiting, as does a crash loop. Each poll lists a namespace's pods once.
A database Degraded only because WAL archiving to its in-cluster backup bucket fails waits while that bucket is not Ready and for
5 minutes after the archiving failure began or the bucket became Ready (#902), then it is RED as before. A context that is not the system's
cluster, a cluster that does not answer, or no Argo CD exits 1 at once.
In a system on several clusters (spec 201) the context of `--env`'s cluster is used (`kube_contexts` in the settings files), never the
current one; in a cluster repo with `clusters`, `cluster wait <cluster>` names the cluster whose roots it waits for.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

import envcluster
import gitops
import model
import settings
import ship
import waits
from core import PlatformError, run

ROOTS = ("platform-operators", "platform-systems")     # the cluster repo's own applications (spec 125, scripts/render.py)
REFRESH = "argocd.argoproj.io/refresh=hard"
# Spec 148 (#542), #867: an app behind the revision (or not generated yet) gets a hard refresh when the wait starts, since every
# wait follows a merged gitops PR, and once more this long into the wait; so does the system's root app: Argo CD polls git every
# 3 minutes, and a root app whose repo fetch timed out never generates the app.
AUTO_REFRESH_AFTER = 45.0
# #867: a container of the new version waiting for one of these reasons longer than POD_FAIL_AFTER ends the wait RED at once.
POD_FAILURES = ("ImagePullBackOff", "ErrImagePull", "InvalidImageName", "CrashLoopBackOff")
POD_FAIL_AFTER = 60.0
LGTM_APP = "operator-lgtm"       # #937: the cluster's shared Grafana (observability ui: lgtm), rendered by the operators
PULLS = ("ImagePullBackOff", "ErrImagePull")
PULL_EVENT = re.compile(r"pull|image", re.I)      # #925: the events of a pod that say why its image pull fails
# #892: a missing image tag while the component's CI run on main builds it is not stuck. The run's state is asked again at most this
# often while it runs; after it passed, the kubelet's pull back-off (up to 5 minutes) may still hold the pod for this long.
CI_RECHECK = 60.0
BUILT_GRACE = 300.0
BUILDING = ("queued", "in_progress", "waiting", "pending", "requested")
# #902: a database whose WAL archiving fails while its in-cluster backup bucket starts is pending, not RED, for this long after the
# failure began or the bucket became Ready (and as long as the bucket is not Ready).
ARCHIVE_GRACE = 300.0
ARCHIVE_FAILURE = re.compile(r"barman-cloud|exit status|could not connect|endpoint|connection|timed? ?out", re.I)
NOT_IN_REGISTRY = re.compile(r"manifest unknown|not found", re.I)
NO_ARGO = re.compile(r"doesn't have a resource type|the server could not find the requested resource|namespaces? \"?argocd\"? not found",
                     re.I)
# A ComparisonError whose cause is the network (#506): Argo CD could not reach the repo and retries by itself, so the wait keeps
# waiting; one still there at the timeout is RED with its message.
NETWORK = re.compile(r"i/o timeout|connection (?:reset|refused|timed out)|TLS handshake timeout|context deadline exceeded"
                     r"|temporary failure in name resolution|server misbehaving|lookup \S+ on \S+: no such host|network is unreachable"
                     r"|no route to host|unexpected EOF", re.I)


def kubectl(args: list[str], context: str | None = None, check: bool = False) -> subprocess.CompletedProcess:  # tests replace this
    cmd = ["kubectl", *(["--context", context] if context else []), *args]
    try:
        return run(cmd, check=check, timeout=30)
    except PlatformError as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def gh(args: list[str]) -> subprocess.CompletedProcess:    # tests replace this
    cmd = ["gh", *args]
    try:
        return run(cmd, check=False, timeout=30)
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
    repo: str = ""               # the component's GitHub repo (owner/name), whose CI run builds its image (#892)
    bucket: str = ""             # a database's in-cluster backup bucket: its object prefix `<system>-<bucket>` (#902)
    bucket_app: str = ""         # and that bucket's Argo CD app in the same environment
    shared: bool = False         # #937: a cluster-wide app (the shared Grafana): its trouble is a warning, it never holds the wait


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
    repos = {c.name: c.repo or "" for c in m.components}
    out = [Target(i.argo_application, i.tag, True, i.component, env, repos.get(i.component, "")) for i in insts]
    if names:
        return system, out, every
    ris = [r for r in m.resource_instances if r.environment == env]
    for r in ris:
        if not r.argo_application:
            continue
        to = (r.backup or {}).get("to") if r.type == "database" else None
        bucket = next((b for b in ris if to and b.resource == to and not b.external and b.argo_application), None)
        out.append(Target(r.argo_application, env=env, bucket=f"{system}-{to}" if bucket else "",
                          bucket_app=bucket.argo_application or "" if bucket else ""))
    e = m.environment(env)
    if e and e.observability and e.observability.argo_application and insts:
        out.append(Target(e.observability.argo_application))
    if e and e.observability and e.observability.ui == "lgtm":
        out.append(Target(LGTM_APP, shared=True))
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


def judge(t: Target, st: dict | None, wanted: str, at, ctx: str, pins=None, archive=None) -> tuple[str, str, str]:
    """(kind: reached | behind | retrying | red, the progress line, what it waits for or why it is red). `retrying` is a
    ComparisonError with a network cause (#506): it waits like `behind` and turns RED at the timeout. `archive(t, st)` says why a
    Degraded database only waits for its backup bucket (#902), else None."""
    if st is None:
        return ("reached", "", "") if t.shared else ("behind", f"{t.app}: missing", "missing")
    sync = (st.get("sync") or {}).get("status") or "?"
    health = st.get("health") or {}
    hstatus = health.get("status") or "?"
    rev = (st.get("sync") or {}).get("revision") or ""
    tag = pins(t, rev) if pins else t.tag
    images: list[str] = []
    if t.component:
        images = list((st.get("summary") or {}).get("images") or []) or (ship.workload_images(ctx, st) if tag else [])
    line = f"{t.app}: {sync}/{hstatus} at {waits.short(rev)}" + (f", runs {_shown(images, tag)}" if t.component else "")
    if t.shared:                         # #937: another repo may own it, so no revision; never red, never behind (see _addon_pods)
        return "reached", line, "" if hstatus == "Healthy" else f"{sync}/{hstatus}"
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
        pending = archive(t, st) if archive and t.bucket else None
        if pending:
            return "behind", line, pending
        return "red", line, "health Degraded" + (f": {health['message']}" if health.get("message") else "")
    if t.component and tag and not _matches(images, tag):
        return "behind", line, f"waiting for image {waits.tag_short(tag)}, runs {', '.join(images) or 'nothing'}"
    if (sync, hstatus) != ("Synced", "Healthy"):
        return "behind", line, f"{sync}/{hstatus}"
    return "reached", line, ""


# ---------------- the pods of the new version (#867) ----------------

def wallclock() -> float:      # tests replace this: the pod's start time is a cluster timestamp, not the wait's clock
    return time.time()


def _stamp(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() if value else None
    except ValueError:
        return None


def _json(p: subprocess.CompletedProcess) -> dict:
    if p.returncode != 0:
        return {}
    try:
        doc = json.loads(p.stdout or "{}")
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


class PollReads:
    """#925: one kubectl read per poll. The same read asked twice in one poll (the pods of a namespace for a component, a database
    and its backup bucket) is answered from the first; `clear()` starts the next poll."""

    def __init__(self, get):
        self.get, self.seen = get, {}

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        key = tuple(args)
        if key not in self.seen:
            self.seen[key] = self.get(args)
        return self.seen[key]

    def clear(self) -> None:
        self.seen.clear()


class PodWatch:
    """Whether a pod of the version a wait expects is stuck: a container waiting in one of POD_FAILURES for more than
    POD_FAIL_AFTER seconds (seen during this wait, or since the pod started). `get` runs kubectl with the wait's context,
    `clock` is the wait's clock. Reads nothing when the app names no namespaced workload or child Application; a kubectl error
    reads as no pods."""

    def __init__(self, get, clock):
        self.get, self.clock, self.first = get, clock, {}

    def __call__(self, status: dict, wanted, building=None) -> str | None:
        """`building()` (optional) is the state of the CI run that builds the image: "building", "built" (it passed after it was
        seen building) or None (no run builds it, or it failed). A missing image tag is not stuck while it builds (#892)."""
        for ns in self._spaces(status):
            for pod in self._pods(ns):
                why = self._stuck(ns, pod, wanted, building)
                if why:
                    return why
        return None

    def addon(self, status: dict, at_once: bool = False) -> tuple[str, str] | None:
        """#925: (red | waiting, why) for the first pod of a database or add-on app stuck longer than POD_FAIL_AFTER, else None. Its
        pods are those named after one of the app's resources (`<cluster>-1`, `<cluster>-1-initdb-…`, a bucket's pods). A missing tag
        or manifest and an invalid image name are red; a pull failing on the network, another pull error or a crash loop waits.
        #937 `at_once`: the app reads Healthy, so a stuck pod waits from the first poll (red still only after POD_FAIL_AFTER)."""
        resources = [r for r in status.get("resources") or [] if r.get("namespace") and r.get("name") and r.get("kind") != "Application"]
        prefixes = tuple(sorted({str(r["name"]) + "-" for r in resources}))
        for ns in _namespaces(status):
            for pod in self._pods(ns):
                name = str((pod.get("metadata") or {}).get("name") or "")
                if not prefixes or not name.startswith(prefixes):
                    continue
                for _, reason, seen, image, message in self._failing(ns, pod, name, 0.0 if at_once else POD_FAIL_AFTER):
                    pulls = [m for m in self._events(ns, name) if PULL_EVENT.search(m)]
                    where = f"pod {ns}/{name}: {reason}, image {image}" + (f"; last event: {pulls[-1]}" if pulls else "")
                    text = " ".join([message, *pulls]) if reason in PULLS else ""
                    net = NETWORK.search(text)
                    if net:
                        return "waiting", f"image pull failing: {net.group(0)} ({where})"
                    if (reason == "InvalidImageName" or NOT_IN_REGISTRY.search(text)) and seen > POD_FAIL_AFTER:
                        return "red", (f"pod {ns}/{name}: {reason} for {int(seen)}s, image {image}"
                                       + (f"; last event: {pulls[-1]}" if pulls else "") + " (the image tag does not exist in the registry)")
                    if reason in PULLS:
                        return "waiting", f"image pull failing: {reason} ({where})"
                    return "waiting", where
        return None

    def _spaces(self, status: dict) -> list[str]:
        """The namespaces of the app's workloads and (#883) the destination namespace of each child Application it manages (an
        external Helm entry's `<svc>-<env>-chart`, one level): the chart's pods run there."""
        spaces = set(_namespaces(status))
        for r in status.get("resources") or []:
            if r.get("kind") == "Application" and r.get("group") == "argoproj.io" and r.get("name"):
                child = _json(self.get(["-n", r.get("namespace") or "argocd", "get", "application", str(r["name"]), "-o", "json"]))
                ns = ((child.get("spec") or {}).get("destination") or {}).get("namespace")
                if ns:
                    spaces.add(str(ns))
        return sorted(spaces)

    def _pods(self, ns: str) -> list[dict]:
        return [p for p in _json(self.get(["-n", ns, "get", "pods", "-o", "json"])).get("items") or [] if isinstance(p, dict)]

    def _failing(self, ns: str, pod: dict, name: str, after: float = POD_FAIL_AFTER):
        """(container, reason, seconds, image, waiting message) of each container waiting in POD_FAILURES for over `after` seconds."""
        spec, st = pod.get("spec") or {}, pod.get("status") or {}
        images = {c.get("name"): c.get("image") or "" for c in (spec.get("initContainers") or []) + (spec.get("containers") or [])}
        started = _stamp(st.get("startTime"))
        for c in (st.get("initContainerStatuses") or []) + (st.get("containerStatuses") or []):
            waiting = (c.get("state") or {}).get("waiting") or {}
            reason = waiting.get("reason")
            if reason not in POD_FAILURES:
                continue
            key = (ns, name, c.get("name"), reason)
            first = self.first.setdefault(key, self.clock())
            seen = max(self.clock() - first, wallclock() - started if started else 0.0)
            if after and seen <= after:
                continue
            yield c.get("name"), reason, seen, images.get(c.get("name")) or c.get("image") or "?", " ".join(str(waiting.get("message") or "").split())

    def _stuck(self, ns: str, pod: dict, wanted, building=None) -> str | None:
        spec = pod.get("spec") or {}
        images = [c.get("image") or "" for c in (spec.get("initContainers") or []) + (spec.get("containers") or [])]
        if not any(wanted(i) for i in images):
            return None                      # a pod of another version: not what this wait waits for
        name = (pod.get("metadata") or {}).get("name") or "?"
        for _, reason, seen, image, _ in self._failing(ns, pod, name):
            event = self._event(ns, name)
            why = f"pod {ns}/{name}: {reason} for {int(seen)}s, image {image}"
            if event:
                why += f"; last event: {event}"
            if reason in PULLS and NOT_IN_REGISTRY.search(event or ""):
                if building and building() is not None:
                    continue                 # #892: the component's CI run builds that tag (or just pushed it)
                why += " (the image tag does not exist in the registry)"
            return why
        return None

    def _events(self, ns: str, pod: str) -> list[str]:
        """The pod's event messages, the last one the one to show: Warnings after Normal ones, each group oldest first."""
        p = self.get(["-n", ns, "get", "events", "--field-selector", f"involvedObject.kind=Pod,involvedObject.name={pod}", "-o", "json"])
        events = [e for e in _json(p).get("items") or [] if isinstance(e, dict)]
        events.sort(key=lambda e: (e.get("type") == "Warning",
                                   str(e.get("lastTimestamp") or e.get("eventTime") or (e.get("metadata") or {}).get("creationTimestamp") or "")))
        return [" ".join(str(e.get("message") or "").split()) for e in events]

    def _event(self, ns: str, pod: str) -> str:
        events = self._events(ns, pod)
        return events[-1] if events else ""


def _namespaces(status: dict) -> list[str]:
    return sorted({r["namespace"] for r in status.get("resources") or [] if r.get("namespace") and r.get("kind") != "Application"})


class CiRuns:
    """#892: whether the CI run on main of a component's repo builds its image: the newest `ci` run on main, read with one
    `gh run list` per repo and asked again at most every CI_RECHECK seconds while it is queued or running. "building" while it
    is; "built" for BUILT_GRACE seconds after a run seen building passed (the kubelet's pull back-off); otherwise None (no run, a
    finished run never seen building, a failed run, or gh cannot tell): the missing tag fails fast as before."""

    def __init__(self, clock):
        self.clock, self.cache, self.passed = clock, {}, {}

    def __call__(self, slug: str) -> str | None:
        if not slug:
            return None
        now = self.clock()
        state, at = self.cache.get(slug, (None, None))
        if at is None or (state == "building" and now - at >= CI_RECHECK):
            seen = state == "building"
            state = self._ask(slug)
            if seen and state == "success":
                self.passed[slug] = now
            self.cache[slug] = (state, now)
        if state == "building":
            return "building"
        if slug in self.passed and now - self.passed[slug] <= BUILT_GRACE:
            return "built"
        return None

    @staticmethod
    def _ask(slug: str) -> str | None:
        p = gh(["run", "list", "-R", slug, "--workflow", "ci", "--branch", "main", "--limit", "1", "--json", "status,conclusion"])
        try:
            runs = json.loads(p.stdout or "[]") if p.returncode == 0 else []
        except ValueError:
            runs = []
        if not runs or not isinstance(runs, list) or not isinstance(runs[0], dict):
            return None
        if str(runs[0].get("status") or "") in BUILDING:
            return "building"
        return str(runs[0].get("conclusion") or "") or None


# ---------------- a database waiting for its backup bucket (#902) ----------------

def _ready(pod: dict) -> tuple[bool, float | None]:
    """(Ready, when its Ready condition last changed) of a pod."""
    cond = next((c for c in (pod.get("status") or {}).get("conditions") or [] if c.get("type") == "Ready"), None) or {}
    return cond.get("status") == "True", _stamp(cond.get("lastTransitionTime"))


class ArchiveWatch:
    """#902: why a Degraded database app only waits for its in-cluster backup bucket, else None. That is so when every Degraded
    resource of the app is a CloudNativePG Cluster whose ContinuousArchiving is False with a Barman Cloud or connection failure, and
    the bucket (its Argo CD app and its SeaweedFS pods in the same namespace) is not Ready, or the failure began or the bucket became
    Ready at most ARCHIVE_GRACE seconds ago. `get` runs kubectl with the wait's context; a kubectl error reads as not pending."""

    def __init__(self, get):
        self.get, self.items = get, {}      # items: the wait's latest Argo CD applications, set before each poll is judged

    def __call__(self, t: Target, st: dict) -> str | None:
        resources = st.get("resources") or []
        if any((r.get("health") or {}).get("status") == "Degraded" and r.get("kind") != "Cluster" for r in resources):
            return None                      # something else is broken
        clusters = [r for r in resources if r.get("kind") == "Cluster" and r.get("group") == "postgresql.cnpg.io"
                    and r.get("namespace") and r.get("name")]
        failing = []
        for r in clusters:
            doc = _json(self.get(["-n", r["namespace"], "get", "clusters.postgresql.cnpg.io", r["name"], "-o", "json"]))
            arch = next((c for c in (doc.get("status") or {}).get("conditions") or [] if c.get("type") == "ContinuousArchiving"), None)
            if arch and arch.get("status") == "False":
                if not ARCHIVE_FAILURE.search(str(arch.get("message") or "")):
                    return None
                failing.append((r["namespace"], arch))
        if not failing:
            return None
        ns, arch = failing[0]
        message = " ".join(str(arch.get("message") or "").split())
        bucket = (self.items.get(t.bucket_app) or {}).get("health", {}).get("status") if t.bucket_app else None
        pods = [p for p in _json(self.get(["-n", ns, "get", "pods", "-o", "json"])).get("items") or []
                if str((p.get("metadata") or {}).get("name") or "").startswith(t.bucket + "-")
                and (p.get("status") or {}).get("phase") not in ("Succeeded", "Failed")]
        states = [(str((p.get("metadata") or {}).get("name")), *_ready(p)) for p in pods]
        waiting = [name for name, ok, _ in states if not ok]
        if bucket not in (None, "Healthy") or waiting:
            what = f"pod {waiting[0]} not Ready" if waiting else f"app {t.bucket_app} {bucket}"
            return f"archiving waits for backup bucket {t.bucket} ({what}): {message}"
        since = max([s for s in [_stamp(arch.get("lastTransitionTime")), *(at for _, _, at in states)] if s is not None], default=None)
        age = wallclock() - since if since is not None else 0.0
        if age <= ARCHIVE_GRACE:
            return f"archiving waits for backup bucket {t.bucket} (Ready {int(age)}s, up to {int(ARCHIVE_GRACE)}s): {message}"
        return None


# ---------------- the wait ----------------

def _refresh(names: list[str], ctx: str) -> None:
    for name in names:
        kubectl(["-n", "argocd", "annotate", "application", name, REFRESH, "--overwrite"], ctx)


def _errored(st: dict | None) -> bool:
    return any(str(c.get("type", "")) == "ComparisonError" for c in (st or {}).get("conditions") or [])


def _stuck_pod(states: list, items: dict[str, dict], at, pins, pods: PodWatch, ci=None) -> tuple[Target, str] | None:
    """#867: the first component behind at the wanted revision whose new pods are stuck (PodWatch), with why; `ci(repo)` says
    whether the component's CI run builds its image (#892)."""
    for t, kind, _, why in states:
        st = items.get(t.app)
        if kind != "behind" or not t.component or not st or why.startswith("waiting for revision"):
            continue
        tag = pins(t, (st.get("sync") or {}).get("revision") or "")
        building = (lambda repo=t.repo: ci(repo)) if ci and t.repo else None
        stuck = pods(st, lambda image, tag=tag: _matches([image], tag), building) if tag else None
        if stuck:
            return t, stuck
    return None


def _addon_pods(states: list, items: dict[str, dict], pods: PodWatch) -> list:
    """#925: a database or add-on app behind at the wanted revision whose pods are stuck: the why on its progress line, and red for a
    missing image (PodWatch.addon). #937: also one that reads Synced/Healthy (a SeaweedFS bucket's `Seaweed` has no Argo CD health
    check): a stuck pod keeps it behind. A shared app (the cluster's Grafana) only carries the why as a warning: kind "warn"."""
    out = []
    for t, kind, line, why in states:
        st = items.get(t.app)
        if not t.component and kind in ("behind", "reached") and st and why != "missing" and not why.startswith("waiting for revision"):
            found = pods.addon(st, at_once=kind == "reached")
            if found:
                verdict, why = found
                if t.shared:
                    kind = "warn"
                elif verdict == "red":
                    kind = "red"
                else:
                    kind = "behind"
                if verdict != "red" or t.shared:
                    line = f"{line}; {why}"         # on every progress line of the app while it lasts
        out.append((t, kind, line, why))
    return out


def watch(repo: Path, targets: list[Target], wanted: str, ctx: str, items: dict[str, dict], label: str, command: str,
          refresh: bool, timeout: float, interval: float, system: str | None = None) -> tuple[int, list[str]]:
    at, pins = Ancestry(repo, wanted), Pins(repo, wanted, system)
    reads = PollReads(lambda args: kubectl(args, ctx))       # #925: each poll lists a namespace's pods once
    pods = PodWatch(reads, waits.now)
    ci = CiRuns(waits.now)
    archive = ArchiveWatch(reads)
    w7 = waits.short(wanted)
    begin = waits.now()
    refreshes = 0                 # #867: one when the wait starts, one more after AUTO_REFRESH_AFTER (spec 148)
    root = f"{system}-root" if system else None
    last: dict[str, str] = {}
    while True:
        archive.items = items
        reads.clear()
        states = [(t, *judge(t, items.get(t.app), wanted, at, ctx, pins, archive)) for t in targets]
        states = _addon_pods(states, items, pods)
        for t, _, line, _ in states:
            if line and last.get(t.app) != line:
                ship.say(line)
                last[t.app] = line
        red = next(((t, why) for t, kind, _, why in states if kind == "red"), None) or _stuck_pod(states, items, at, pins, pods, ci)
        if red:
            rev = ((items.get(red[0].app) or {}).get("sync") or {}).get("revision")
            return waits.RED, [f"RED: {red[0].app} at {waits.short(rev)}: {red[1]}"]
        behind = [(t, why) for t, kind, _, why in states if kind in ("behind", "retrying")]
        if not behind:
            held = [t for t in targets if not t.shared]
            warn = [f"WARNING: {t.app} (shared by the cluster) is not ready: {why}" for t, kind, _, why in states
                    if t.shared and (kind == "warn" or why)]
            return waits.REACHED, [f"READY: {len(held)} app(s) {label} run {w7}", *warn]
        if refreshes == 0 or (refreshes == 1 and waits.now() - begin >= AUTO_REFRESH_AFTER):
            refreshes += 1
            stale = [t.app for t, why in behind if t.app in items and (why.startswith("waiting for revision") or _errored(items[t.app]))]
            if root and root in items and (_errored(items[root]) or any(why == "missing" for _, why in behind)):
                stale.insert(0, root)
            if stale:
                _refresh(stale, ctx)
                when = "yet" if refreshes == 1 else f"after {int(waits.now() - begin)}s"
                ship.say(f"asked Argo CD for a hard refresh of {', '.join(stale)} (not at {w7} {when})")
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
    m = model.load_dir(gitops.find_app(repo, ns.system))
    ctx, items = resolve_context(repo, envcluster.env_context(repo, m, ns.env, ns.context), every, f"system {system}")
    return watch(repo, targets, wanted, ctx, items, f"in {ns.env}", command, ns.refresh, ns.timeout, ns.interval, system)


def _named_cluster(repo: Path, name: str | None) -> str | None:
    """The cluster `cluster wait` is for: required and validated with `clusters` in cluster.yaml; else None (today's behaviour)."""
    doc = yaml.safe_load((repo / "cluster.yaml").read_text()) or {}
    listed = doc.get("clusters") if isinstance(doc, dict) else None
    if not listed:
        if name and isinstance(doc, dict) and name != doc.get("cluster"):
            raise PlatformError(f"unknown cluster '{name}' (cluster: {doc.get('cluster')})", hint="name this repo's cluster, or leave it out")
        return None
    shown = ", ".join(map(str, listed))
    if not name:
        raise PlatformError(f"name the cluster to wait for: cplat cluster wait <cluster> (clusters: {shown})")
    if name not in listed:
        raise PlatformError(f"unknown cluster '{name}' (clusters: {shown})")
    return name


def cluster_wait(repo: Path, ns: argparse.Namespace, command: str) -> tuple[int, list[str]]:
    if not (repo / "cluster.yaml").is_file():
        raise PlatformError(f"not a cluster repo: {repo} has no cluster.yaml", hint="run it in the cluster repo (/cluster:new creates one)")
    cluster = _named_cluster(repo, ns.cluster)
    context = envcluster.cluster_context(repo, cluster, ns.context, f"cluster {cluster}") if cluster else ns.context
    wanted = wanted_revision(repo, None)
    ctx, items = resolve_context(repo, context, set(ROOTS), f"cluster repo {repo.name}")
    return watch(repo, [Target(r) for r in ROOTS], wanted, ctx, items, "of the cluster", command, ns.refresh, ns.timeout, ns.interval)


def main(argv: list[str]) -> int:
    kind, rest = argv[0], argv[1:]
    ap = argparse.ArgumentParser(prog=f"cplat {kind} wait", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if kind == "system":
        ap.add_argument("components", nargs="*", help="limit the wait to these components' apps")
        ap.add_argument("--env", required=True)
        ap.add_argument("--revision", help="wait for this commit of the gitops repo (default: the head of main on GitHub)")
        ap.add_argument("--system", help="the system, when the repo holds several")
    if kind == "cluster":
        ap.add_argument("cluster", nargs="?", help="the cluster to wait for (required when cluster.yaml lists `clusters`)")
    ap.add_argument("--refresh", action="store_true", help="kept for scripts: every wait asks Argo CD for a hard refresh of each app behind the revision")
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
