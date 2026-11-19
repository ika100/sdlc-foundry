#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Check the registered systems against this cluster repo (spec 125, `devbox run check`).

For every system in cluster.yaml it reads the system repo's `main` (GH_TOKEN, Contents: read), works out the operators the system
needs and fails, one line per gap, when cluster.yaml does not list them or when an environment would install operators itself.
A different platform release only warns.

Usage: check.py [--urls]
  --urls   print `<system> <host>` for every hostname the systems expose (used by `cluster-up`); never fails on an unreadable repo.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import render  # noqa: E402  (the cluster renderer: cluster.yaml validation)
import system_render as sr  # noqa: E402  (a copy of the gitops-app renderer: system.yaml loading and the operator tables)


def read_yaml(path: Path) -> dict:
    try:
        doc = yaml.safe_load(path.read_text()) if path.is_file() else None
    except yaml.YAMLError:
        return {}
    return doc if isinstance(doc, dict) else {}


def release_of(root: Path) -> str | None:
    """`platform: x.y.z` of .platform-version, else the recorded `_commit` without a leading v (decision 6)."""
    value = read_yaml(root / ".platform-version").get("platform")
    if value is None:
        value = read_yaml(root / ".copier-answers.yml").get("_commit")
    return str(value).removeprefix("v") if value else None


def clone(repo: str, dest: Path) -> str | None:
    """None when `main` was cloned, else the first line of gh's error."""
    try:
        p = subprocess.run(["gh", "repo", "clone", repo, str(dest), "--", "--depth", "1", "--branch", "main"],
                           capture_output=True, text=True)
    except OSError as err:
        return str(err)
    if p.returncode == 0:
        return None
    return next((ln.strip() for ln in (p.stderr + p.stdout).splitlines() if ln.strip()), f"gh exited {p.returncode}")


def needs(system: dict) -> dict[str, set[str]]:
    """environment -> the operators the system needs there (design section 4, step 4)."""
    services, cfg = system["services"], system["cfg"]
    instances = sr.resource_instances(system)
    out: dict[str, set[str]] = {}
    for env in sr.ENVS:
        ops: set[str] = set()
        for _, e, typ, external in instances:
            if e != env:
                continue
            if external:
                ops.add("external-secrets")
            elif typ in sr.OPERATOR_OF_TYPE:
                ops.add(sr.OPERATOR_OF_TYPE[typ])
                if typ in ("bucket", "broker"):
                    ops.add("external-secrets")
            elif typ == "cache":
                # a cache has no operator, but its password comes from External Secrets too
                ops.add("external-secrets")
        for svc in services:
            if env in sr.envs_of(svc) and (svc.get("secretRefs") or sr.at(svc, env).get("secrets")):
                ops.add("external-secrets")
        if env in sr.policy_envs(services, cfg):
            ops.add("kyverno")
        if (cfg.get("autoscaling") or {}).get(env) == "keda":
            ops.add("keda")
        out[env] = ops
    return out


def version_tuple(value: str | None) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in value.split(".")) if value else None
    except ValueError:
        return None


def older(theirs: str | None, mine: str | None) -> bool:
    """True when the system's release is unknown or older than the cluster repo's (design section 4, step 2)."""
    if theirs is None:
        return True
    a, b = version_tuple(theirs), version_tuple(mine)
    return a is not None and b is not None and a < b


def check_system(name: str, repo: str, root: Path, cluster_ops: list[str], release: str | None,
                 eff: dict | None = None) -> tuple[list[str], list[str], set[str]]:
    """(WARNING and ERROR lines in order, the ERROR lines among them, the operators needed).

    With `eff` (render.effective() of a repo that lists clusters) the operator need of an environment is checked against the cluster
    that runs it, and a system with `environments` gets the assignment checks of design section 4, step 2."""
    lines: list[str] = []
    errors: list[str] = []
    wanted: set[str] = set()
    clusters = eff["clusters"] if eff and len(eff["clusters"]) > 0 and eff["clusters"][0]["tree"] != "cluster" else []
    assigned: dict[str, str] | None = None     # env -> cluster, None for form 125 (the first cluster runs all three)
    for cl in clusters:
        for sysentry in cl["systems"]:
            if sysentry["name"] == name and sysentry["environments"] is not None:
                assigned = (assigned or {}) | {e: cl["name"] for e in sysentry["environments"]}
    on_cluster = {e: (assigned or {}).get(e) or clusters[0]["name"] for e in sr.ENVS} if clusters else {}
    ops_of = {cl["name"]: cl["operators"] for cl in clusters}

    def err(text: str) -> None:
        lines.append(f"ERROR: {text}")
        errors.append(text)

    apps = root / "applications"
    if not (apps / name / "system.yaml").is_file():
        err(f"{name}: {repo} has no applications/{name}/system.yaml on main")
    else:
        loaded = []
        for d in sorted(p for p in apps.iterdir() if (p / "system.yaml").is_file()):
            try:
                loaded.append(sr.load_system(d))
            except sr.RenderError as e:
                err(f"{name}: {repo} does not render with this cluster's platform release {release or 'unknown'}: {e}")
                loaded = []
                break
        for system in loaded:
            s = system["system"]
            per_env = needs(system)
            for env in sr.ENVS:
                if system["cfg"]["operators"].get(env) != "owner":
                    err(f"{s} ({env}): would install operators itself: set environments.{env}.operators: owner in {repo}")
                for op in sorted(per_env[env]):
                    wanted.add(op)
                    if clusters:
                        c = on_cluster[env]
                        if op not in ops_of[c]:
                            err(f"{s} ({env}): needs {op}, which cluster {c} does not install")
                    elif op not in cluster_ops:
                        err(f"{s} ({env}): needs {op}, which cluster.yaml does not list in operators")
            if assigned is not None and s == name:
                assignment_errors(system, assigned, [cl["name"] for cl in clusters], name, repo, root, release, err)
    theirs = release_of(root)
    if theirs is None:
        lines.insert(0, f"WARNING: {name}: release unknown (no .platform-version or _commit on main of {repo}), "
                        f"this cluster repo on {release or 'unknown'}")
    elif theirs != release:
        lines.insert(0, f"WARNING: {name} is on platform {theirs}, this cluster repo on {release or 'unknown'}")
    return lines, errors, wanted


def assignment_errors(system: dict, assigned: dict[str, str], listed: list[str], name: str, repo: str, root: Path,
                      release: str | None, err) -> None:
    """Design section 4, step 2, in its order; the first case that applies ends the list."""
    s = system["system"]
    left_out = [e for e in sr.ENVS if e not in assigned]
    for env in left_out:
        err(f"{s} ({env}): {repo} declares {env}, which systems.{s}.environments in cluster.yaml leaves out; assign it to a cluster")
    if left_out:
        return
    own = system["cfg"].get("cluster") or {}
    theirs = release_of(root)
    if not own and older(theirs, release):
        used = [c for c in listed if c in assigned.values()]
        err(f"{s} runs on clusters {', '.join(used)}, but {repo} is on platform {theirs or 'unknown'}, older than this cluster repo "
            f"({release or 'unknown'}); run /platform:update in {repo} first")
        return
    wrong = [e for e in sr.ENVS if own.get(e) != assigned[e]]
    for env in wrong:
        err(f"{s} ({env}): cluster.yaml runs it on {assigned[env]}, but {repo} sets environments.{env}.cluster: {own.get(env) or 'nothing'}; "
            f"set it to {assigned[env]} in {repo}")
    if wrong:
        return
    for env in sr.ENVS:
        if not (root / "bootstrap" / "environments" / f"{s}-{env}.yaml").is_file():
            err(f"{s}: {repo} has no bootstrap/environments/{s}-{env}.yaml on main; run devbox run render in {repo} and merge it")


def urls(name: str, root: Path) -> list[str]:
    hosts: list[str] = []
    for f in sorted((root / "applications").glob("*/overlays/*/*/httproute.yaml")):
        names = (read_yaml(f).get("spec") or {}).get("hostnames") or []
        hosts += [str(h) for h in names if str(h) not in hosts]
    return [f"{name} {h}" for h in hosts]


def main() -> int:
    flags = sys.argv[1:]
    if flags not in ([], ["--urls"]):
        print("usage: check.py [--urls]", file=sys.stderr)
        return 2
    try:
        c = render.validate(render.load(), render.answers().get("github_org") or "")
    except render.ClusterError as err:
        print(f"ERROR: cluster.yaml: {err}", file=sys.stderr)
        return 1
    try:
        eff = render.effective(c)
    except render.ClusterError as err:
        print(f"ERROR: {err.file}: {err}", file=sys.stderr)
        return 1
    if not flags:
        for line in [f"EXCEPTION: {x}" for cl in eff["clusters"] for x in cl["exceptions"]] + render.behind_lines(eff):
            print(line)
    if not c["systems"]:
        if not flags:
            print("OK: no systems registered")
        return 0
    release = release_of(ROOT)
    tmp = Path(tempfile.mkdtemp(prefix="cluster-check-"))
    problems = 0
    oks: list[str] = []
    try:
        for i, (name, repo) in enumerate(c["systems"].items()):
            dest = tmp / str(i)
            failure = clone(repo, dest)
            if flags:
                if failure:
                    print(f"WARNING: {name}: cannot read {repo}", file=sys.stderr)
                else:
                    for line in urls(name, dest):
                        print(line)
                continue
            if failure:
                print(f"ERROR: {name}: cannot read {repo} (main): {failure}; the check needs a token with Contents: read on it "
                      f"(CI: the SYSTEMS_TOKEN secret; locally: gh auth login)")
                problems += 1
                continue
            lines, errors, wanted = check_system(name, repo, dest, c["operators"], release, eff)
            print("\n".join(lines)) if lines else None
            problems += len(errors)
            oks.append(f"OK: {name} {repo} needs: {', '.join(sorted(wanted)) or 'none'}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if flags:
        return 0
    if problems:
        print(f"FAILED: {problems} problem(s)")
        return 1
    print("\n".join(oks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
