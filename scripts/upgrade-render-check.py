#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Upgrade render check (spec 191, AC-191.1 to AC-191.3): render a system with the from-release and with the candidate and report, in
seconds and without a cluster, every change Kubernetes refuses in place or that loses data, unless a changelog `Upgrade step:` line
accepts it.

  upgrade-render-check.py [--from TAG]... [--work DIR] [--repo DIR]
      the run mode (AC-191.4): per from-release (default: the previous and the oldest supported one) build the system with that release,
      update it with this checkout and compare, each in a section `from <tag>:`. Needs git, uv and copier, no container runtime.
  upgrade-render-check.py compare --from-tag TAG [--repo DIR] BEFORE AFTER
      BEFORE and AFTER are gitops repos (each with scripts/render.py and applications/<system>/system.yaml); each is rendered with
      its own `uv run scripts/render.py`. --repo is the platform checkout whose changelog is read (default: this checkout).

Exit 0: no unaccepted breaking change; 1: breaking changes; 2: a render or a read failed (`ERROR: ...`).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "cplat"))
try:
    import platrelease_changelog as fragments  # noqa: E402  (spec 132: docs/changelog.d)
    import yaml  # noqa: E402
except ModuleNotFoundError as e:   # a bare `python3` lacks pyyaml; uv reads the dependencies above
    sys.exit(f"ERROR: {e}: run it as `uv run scripts/upgrade-render-check.py {' '.join(sys.argv[1:])}`")

ENVS = ("dev", "staging", "prod")
FOLDERS = ("addons", "overlays", "policies")
UNSET = "<unset>"
IMMUTABLE = "immutable: Kubernetes refuses the change"
LOSES = "loses data"
STEP = re.compile(r"Upgrade step:\s*(?P<kind>[A-Za-z]+)\s+(?P<field>\S+?):\s*(?P<text>.+)")
HEADING = re.compile(r"^## \[(?P<name>[^\]]+)\][^\n]*\n", re.M)
WORKLOADS = ("Deployment", "StatefulSet", "DaemonSet", "Job")
SUFFIX = {"": 1, "m": Decimal("0.001"), **{s: Decimal(1000) ** i for i, s in enumerate("kMGTPE", 1)},
          **{s: Decimal(1024) ** i for i, s in enumerate(["Ki", "Mi", "Gi", "Ti", "Pi", "Ei"], 1)}}


class CheckError(Exception):
    pass


@dataclass(frozen=True)
class Finding:
    env: str
    kind: str
    namespace: str
    name: str
    field: str
    old: str
    new: str
    reason: str

    def sort_key(self) -> tuple:
        return (ENVS.index(self.env), self.kind, self.namespace, self.name, self.field)


def render(repo: Path, side: str) -> None:
    p = subprocess.run(["uv", "run", "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    if p.returncode != 0:
        lines = [ln for ln in (p.stdout + "\n" + p.stderr).splitlines() if ln.strip()]
        raise CheckError(f"{side} does not render: {lines[-1].strip() if lines else f'exit {p.returncode}'}")


def system_dir(repo: Path) -> Path:
    apps = repo / "applications"
    dirs = sorted(d for d in apps.iterdir() if d.is_dir()) if apps.is_dir() else []
    named = [d for d in dirs if (d / "system.yaml").is_file()]
    found = named or dirs
    if not found:
        raise CheckError(f"{apps} has no system directory (applications/<system>)")
    return found[0]


def namespace_of(doc: dict, path: Path, base: Path, default: str) -> str:
    ns = (doc.get("metadata") or {}).get("namespace")
    if ns:
        return str(ns)
    for d in [path.parent, *path.parent.parents]:
        k = d / "kustomization.yaml"
        if k.is_file():
            data = yaml.safe_load(k.read_text())
            if isinstance(data, dict) and data.get("namespace"):
                return str(data["namespace"])
        if d == base:
            break
    return default


def load(repo: Path) -> tuple[Path, list[tuple[str, str, Path, dict]]]:
    """(system dir, [(env, namespace, file, doc)]) of every object document of every environment."""
    base = system_dir(repo)
    out = []
    for folder in FOLDERS:
        for env in ENVS:
            root = base / folder / env
            if not root.is_dir():
                continue
            for f in sorted(root.rglob("*")):
                if not f.is_file() or f.suffix not in (".yaml", ".yml") or f.name == "kustomization.yaml":
                    continue
                try:
                    docs = list(yaml.safe_load_all(f.read_text()))
                except yaml.YAMLError as e:
                    raise CheckError(f"{f}: unreadable YAML: {str(e).splitlines()[0] if str(e) else e}") from e
                for doc in docs:
                    if isinstance(doc, dict) and doc.get("kind") and isinstance(doc.get("metadata"), dict) and doc["metadata"].get("name"):
                        out.append((env, namespace_of(doc, f, base, f"{base.name}-{env}"), f, doc))
    return base, out


def objects(repo: Path) -> dict[tuple[str, str, str, str], dict]:
    return {(env, str(doc["kind"]), ns, str(doc["metadata"]["name"])): doc for env, ns, _f, doc in load(repo)[1]}


def secrets(repo: Path) -> dict[tuple[str, str, str], str]:
    out: dict[tuple[str, str, str], str] = {}
    for env, ns, f, doc in load(repo)[1]:
        kind, name = doc["kind"], str(doc["metadata"]["name"])
        if kind == "Secret":
            out[(env, ns, name)] = f"Secret {name}"
        elif kind == "ExternalSecret":
            target = ((doc.get("spec") or {}).get("target") or {}).get("name") or name
            out[(env, ns, str(target))] = f"ExternalSecret {name}"
        elif kind == "ConfigMap" and f.name == "credentials-configmap.yaml":
            try:
                plan = json.loads((doc.get("data") or {}).get("plan.json") or "{}")
            except ValueError as e:
                raise CheckError(f"{f}: plan.json is not JSON: {e}") from e
            for s in plan.get("secrets") or []:
                if isinstance(s, dict) and s.get("name"):
                    out[(env, ns, str(s["name"]))] = f"plan.json {name}"
    return out


def quantity(s: object) -> Decimal | None:
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|Pi|Ei|[kMGTPEm]?)", str(s).strip())
    if not m:
        return None
    try:
        return Decimal(m[1]) * Decimal(SUFFIX[m[2]])
    except InvalidOperation:
        return None


def get(doc: dict, path: str) -> object:
    cur: object = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return UNSET
        cur = cur[part]
    return cur


def show(v: object) -> str:
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True, separators=(",", ":"))


def differs(old: object, new: object) -> bool:
    return old != new


def smaller(old: object, new: object) -> bool:
    if old == UNSET or new == UNSET:
        return False
    a, b = quantity(old), quantity(new)
    return b < a if a is not None and b is not None else old != new


def ip_changed(old: object, new: object) -> bool:
    return old != UNSET and old != new


def is_cluster(kind: str, doc: dict) -> bool:
    return kind == "Cluster" and str(doc.get("apiVersion", "")).partition("/")[0] == "postgresql.cnpg.io"


# (kinds, field path, predicate(old, new), reason)
RULES = [
    (WORKLOADS, "spec.selector", differs, IMMUTABLE),
    (("StatefulSet",), "spec.volumeClaimTemplates", differs, IMMUTABLE),
    (("StatefulSet",), "spec.serviceName", differs, IMMUTABLE),
    (("PersistentVolumeClaim",), "spec.storageClassName", differs, IMMUTABLE),
    (("PersistentVolumeClaim",), "spec.accessModes", differs, IMMUTABLE),
    (("PersistentVolumeClaim",), "spec.resources.requests.storage", smaller, IMMUTABLE),
    (("Cluster",), "spec.storage.storageClass", differs, IMMUTABLE),
    (("Cluster",), "spec.storage.size", smaller, IMMUTABLE),
    (("Service",), "spec.clusterIP", ip_changed, IMMUTABLE),
    (("Service",), "spec.type", differs, IMMUTABLE),
]


def holds_data(kind: str, doc: dict) -> bool:
    if kind in ("PersistentVolumeClaim", "ExternalSecret") or is_cluster(kind, doc):
        return True
    return kind == "StatefulSet" and bool(get(doc, "spec.volumeClaimTemplates") not in (UNSET, None, []))


def findings(old: tuple[dict, dict], new: tuple[dict, dict]) -> list[Finding]:
    """old, new: (objects, secrets) of the from-release and the candidate."""
    (oo, os_), (no, ns_) = old, new
    out: list[Finding] = []
    for key, od in oo.items():
        env, kind, ns, name = key
        nd = no.get(key)
        if nd is None:
            if holds_data(kind, od):
                out.append(Finding(env, kind, ns, name, "object", "present", "removed", LOSES))
            continue
        for kinds, path, pred, reason in RULES:
            if kind not in kinds or (kind == "Cluster" and not is_cluster(kind, od)):
                continue
            o, n = get(od, path), get(nd, path)
            if pred(o, n):
                out.append(Finding(env, kind, ns, name, path, show(o), "removed" if n == UNSET else show(n), reason))
    for (env, ns, name) in os_:
        if (env, ns, name) not in ns_:
            out.append(Finding(env, "Secret", ns, name, "object", "present", "removed", LOSES))
    return sorted(out, key=Finding.sort_key)


def vtuple(v: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", v.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def changelog_text(repo: Path, tag: str) -> str:
    start = vtuple(tag)
    parts: list[str] = []
    f = repo / fragments.CHANGELOG
    if f.is_file():
        text = f.read_text()
        for m in HEADING.finditer(text):
            v = vtuple(m["name"])
            if v is not None and start is not None and v > start:
                parts.append(fragments._body_after(text, m.end())[0])
        parts.append(fragments.unreleased_body(text))
    try:
        parts += [t for _n, t in fragments.read_fragments(repo)]
    except ValueError as e:
        raise CheckError(f"changelog fragments: {e}") from e
    return "\n".join(parts)


def upgrade_steps(repo: Path, tag: str) -> dict[tuple[str, str], str]:
    steps: dict[tuple[str, str], str] = {}
    for line in changelog_text(repo, tag).splitlines():
        m = STEP.search(line)
        if m:
            steps.setdefault((m["kind"], m["field"]), m["text"].strip())
    return steps


def compare(before: Path, after: Path, tag: str, repo: Path) -> int:
    render(before, f"from-release {tag}")
    render(after, "candidate")
    old, new = (objects(before), secrets(before)), (objects(after), secrets(after))
    steps = upgrade_steps(repo, tag)
    found = findings(old, new)
    breaking = accepted = 0
    for f in found:
        where = f"{f.env} {f.kind} {f.namespace}/{f.name}"
        step = steps.get((f.kind, f.field))
        if step is not None:
            accepted += 1
            print(f"ACCEPTED {where} {f.field} (upgrade step: {step})")
        else:
            breaking += 1
            print(f'BREAKING {where} {f.field}: {f.old} -> {f.new} ({f.reason}) '
                  f'(accept it with a changelog line "Upgrade step: {f.kind} {f.field}: ...")')
    if breaking:
        print(f"FAILED: {breaking} breaking change(s), {tag} -> candidate")
        return 1
    envs = ", ".join(e for e in ENVS if any(k[0] == e for k in old[0]) or any(k[0] == e for k in objects(after)))
    done = f"OK: {len(old[0]) + len(old[1])} objects in {envs} compared, {tag} -> candidate, no breaking change"
    print(done + (f" ({accepted} accepted)" if accepted else ""))
    return 0


# The builder, run as `bash upgrade-system.sh create <tag> <dir>` (the from-release's system) and then `... update <dir>` (the candidate's).
BUILDER = REPO / "tests" / "e2e" / "lib" / "upgrade-system.sh"


def builder(step: str, *args: Path | str) -> tuple[int, str, str]:
    p = subprocess.run(["bash", str(BUILDER), step, *map(str, args)], cwd=REPO, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def last_line(out: str, err: str, code: int) -> str:
    lines = [ln for ln in (err + "\n" + out).splitlines() if ln.strip()]
    return lines[-1].strip() if lines else f"exit {code}"


def section(tag: str, work: Path, repo: Path) -> int:
    """Create the system with the from-release, update it with the candidate, compare; the section's exit code."""
    print(f"from {tag}:", flush=True)
    d = work / tag
    code, out, err = builder("create", tag, d)
    for ln in out.splitlines():
        if ln.startswith("skipped:"):
            print(ln)
    if code != 0:
        print(f"ERROR: from-release {tag} does not render: {last_line(out, err, code)}")
        return 2
    before = d / "before"
    shutil.copytree(d / "upg-gitops", before, symlinks=True)
    code, out, err = builder("update", d)
    if code != 0:
        print(f"ERROR: candidate does not render: {last_line(out, err, code)}")
        return 2
    try:
        return compare(before, d / "upg-gitops", tag, repo)
    except (CheckError, OSError, yaml.YAMLError) as e:
        print(f"ERROR: {e}")
        return 2


def release_tag(which: str) -> tuple[str | None, str]:
    p = subprocess.run([sys.executable, str(REPO / "scripts" / "release-check.py"), "from-tag", which], cwd=REPO, capture_output=True, text=True)
    out = p.stdout.strip()
    if p.returncode != 0:
        raise CheckError(last_line(p.stdout, p.stderr, p.returncode))
    return (None, out.removeprefix("skipped: ")) if out.startswith("skipped:") else (out, "")


def run(froms: list[str], work: Path | None, repo: Path) -> int:
    tags = list(dict.fromkeys(froms))
    if not froms:
        try:
            previous, _ = release_tag("previous")
            oldest, why = release_tag("oldest")
        except CheckError as e:
            print(f"ERROR: {e}")
            return 2
        tags = [t for t in (previous,) if t]
        if oldest is None:
            print(f"oldest supported release: skipped: {why}")
        elif oldest == previous:
            print(f"previous and oldest supported release are both {previous}: compared once")
        else:
            tags.append(oldest)
    base = (work or Path(tempfile.mkdtemp(prefix="upgrade-render-check-"))).resolve()
    base.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, int]] = []
    try:
        for tag in tags:
            results.append((tag, section(tag, base, repo)))
    finally:
        for tag in tags:
            wt = base / tag / "from"
            if wt.exists():
                subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=REPO, capture_output=True)
        if work is None:
            shutil.rmtree(base, ignore_errors=True)
    if all(c == 0 for _t, c in results):
        print(f"upgrade render check: OK ({', '.join(tags)})")
        return 0
    first, *rest = results
    print(f"upgrade render check: FAILED (from {first[0]}: exit {first[1]}" + "".join(f", from {t}: exit {c}" for t, c in rest) + ")")
    return 2 if any(c == 2 for _t, c in results) else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="upgrade-render-check.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="froms", action="append", default=[], metavar="TAG", help="from-release tag (repeatable)")
    ap.add_argument("--work", type=Path, default=None, help="work directory (default: a temporary one, removed at the end)")
    ap.add_argument("--repo", type=Path, default=REPO, help="platform checkout whose changelog is read")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("compare", help="compare two rendered system repos")
    c.add_argument("--from-tag", required=True)
    c.add_argument("--repo", type=Path, default=REPO)
    c.add_argument("before", type=Path)
    c.add_argument("after", type=Path)
    args = ap.parse_args(argv)
    if args.cmd is None:
        return run(args.froms, args.work, args.repo)
    try:
        return compare(args.before.resolve(), args.after.resolve(), args.from_tag, args.repo)
    except (CheckError, OSError, yaml.YAMLError) as e:
        print(f"ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
