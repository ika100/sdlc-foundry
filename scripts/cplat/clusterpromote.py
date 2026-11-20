"""`cluster promote <cluster>` (spec 201, AC-201.8): one PR that moves a later cluster to the platform release the cluster listed before it
runs, only when that cluster is healthy and its smoke tests are green. A promotion is a person's decision: no headless or unit run opens one.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

import backupstate
import clusterrepo
import core
import envcluster
import gitops
import model
import pr_rules
import upgradeverify
from core import PlatformError, Report, run

RELEASE_HEADER = "# Written by /platform:update and /cluster:promote: the platform release this cluster's tree is rendered with.\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat cluster promote", description=__doc__)
    p.add_argument("cluster")
    p.add_argument("--context", help="the kube context of the cluster listed before it")
    p.add_argument("--component-dir", action="append", metavar="NAME=DIR", help="a checkout of a component for the smoke tests; repeatable")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def _render(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return core.run_renderer(repo, *args)


def _last(res: subprocess.CompletedProcess[str]) -> str:
    lines = [ln for ln in (res.stderr or res.stdout or "").strip().splitlines() if ln.strip()]
    return lines[-1].removeprefix("ERROR: ") if lines else f"scripts/render.py exited {res.returncode}"


def _effective(repo: Path) -> dict:
    res = _render(repo, "--effective")
    if res.returncode != 0:
        raise PlatformError(_last(res))
    return json.loads(res.stdout)


def _listed(repo: Path) -> list[str]:
    try:
        doc = yaml.safe_load((repo / "cluster.yaml").read_text())
    except yaml.YAMLError as e:
        raise PlatformError(f"cluster.yaml is not valid YAML ({str(e).splitlines()[0]})") from None
    listed = doc.get("clusters") if isinstance(doc, dict) else None
    return [c for c in listed if isinstance(c, str)] if isinstance(listed, list) else []


def _operator_failures(prev: dict, ctx: str) -> list[str]:
    out: list[str] = []
    for op in prev["operators"]:
        name = f"operator-{op}"
        try:
            doc = backupstate.get_json(["applications.argoproj.io", name, "-n", "argocd"], ctx)
        except backupstate.ReadError as e:
            out.append(f"{name}: {e}")
            continue
        status = doc.get("status") or {}
        sync = (status.get("sync") or {}).get("status") or "unknown"
        health = (status.get("health") or {}).get("status") or "unknown"
        if (sync, health) != ("Synced", "Healthy"):
            out.append(f"{name}: {sync}, {health}")
    return out


def _clone(slug: str, dest: Path) -> str | None:
    res = run(["gh", "repo", "clone", slug, str(dest), "--", "--depth", "1", "--branch", "main"], check=False)
    if res.returncode == 0:
        return None
    text = (res.stderr or "") + (res.stdout or "")
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), f"gh exited {res.returncode}")


def _smoke_failures(prev: dict, dirs: dict[str, str]) -> list[str]:
    out: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cplat-promote-") as tmp:
        for i, s in enumerate(prev["systems"]):
            dest = Path(tmp) / str(i)
            failure = _clone(s["repo"], dest)
            if failure:
                out.append(f"cannot read {s['repo']} (main): {failure}")
                continue
            try:
                m = model.load_dir(dest / "applications" / s["name"])
            except (PlatformError, model.NotMigrated, OSError) as e:
                out.append(f"cannot load {s['name']} from {s['repo']}: {e}")
                continue
            envs = s["environments"] if s["environments"] is not None else list(model.ENVIRONMENTS)
            seen: set[tuple[str, str]] = set()
            for inst in m.instances:
                comp = m.component(inst.component)
                key = (inst.component, inst.environment)
                if comp is None or comp.external or inst.environment not in envs or key in seen:
                    continue
                seen.add(key)
                if comp.name not in dirs:
                    out.append(f"smoke {comp.name} ({inst.environment}): no checkout of {comp.name}; pass --component-dir {comp.name}=<dir>")
                    continue
                passed, text = upgradeverify.run_component_smoke(m, comp, inst.environment, dirs)
                if not passed:
                    out.append(f"smoke {comp.name} ({inst.environment}): {text}")
    return out


def _stage(repo: Path, cluster: str) -> None:
    for path in (f"clusters/{cluster}", "cluster", ".platform"):
        if (repo / path).exists() or run(["git", "ls-files", "--", path], cwd=repo).stdout.strip():
            run(["git", "add", "-A", "--", path], cwd=repo)


def _drop_unused_releases(repo: Path) -> None:
    kept = repo / ".platform" / "releases"
    if not kept.is_dir():
        return
    named = set()
    for f in (repo / "clusters").glob("*/release.yaml"):
        doc = yaml.safe_load(f.read_text())
        if isinstance(doc, dict) and doc.get("platform"):
            named.add(str(doc["platform"]))
    for d in kept.iterdir():
        if d.is_dir() and d.name not in named:
            shutil.rmtree(d)


def cmd_promote(ns: argparse.Namespace) -> int:
    c = ns.cluster
    if os.environ.get("CPLAT_HEADLESS") or os.environ.get("CPLAT_UNIT"):
        raise PlatformError("a promotion is opened by a person, never by a ship, update or engine run", hint=f"run /cluster:promote {c} yourself")
    repo = clusterrepo._repo(ns)
    gitops.require_clean(repo)
    listed = _listed(repo)
    if not listed:
        raise PlatformError("this cluster repo has one cluster; there is nothing to promote")
    if c not in listed:
        raise PlatformError(f"unknown cluster '{c}' (clusters: {', '.join(listed)})")
    if c == listed[0]:
        raise PlatformError(f"{c} is the first cluster: it takes each /platform:update directly, so there is nothing to promote")
    dirs = upgradeverify.parse_dirs(ns.component_dir)
    eff = _effective(repo)
    by_name = {x["name"]: x for x in eff["clusters"]}
    prev = by_name[listed[listed.index(c) - 1]]
    pname = prev["name"]
    target = prev["release"]
    if not target:
        raise PlatformError(f"cluster {pname} runs no known platform release", hint="restore .platform-version from git history, then run it again")
    if by_name[c]["release"] == target and _render(repo, "--check").returncode == 0:
        msg = f"{c} already runs what {pname} runs (platform {target}); no pull request"
        if ns.json:
            Report(title=f"Promote {c}", did=[msg], data={"promoted": False}).emit(False, True)
        else:
            print(msg)
        return 0
    title = pr_rules.fit(f"feat(cluster): promote {c} to platform {target} (what {pname} runs)")
    branch = f"cluster/promote-{c}-{target}"
    if ns.dry_run:
        ops = ", ".join(f"operator-{o}" for o in prev["operators"]) or "none"
        r = Report(title=f"Promote {c} to platform {target} (what {pname} runs)")
        r.will_do = [
            f"gate on {pname}: Argo CD applications {ops} are Synced and Healthy",
            f"gate on {pname}: the smoke tests of {', '.join(s['name'] for s in prev['systems']) or 'no system'} in its environments pass",
            f"write clusters/{c}/release.yaml (platform: {target}; deleted when {target} is this repo's release), run uv run scripts/render.py "
            f"(changes cluster/{c}/**) and delete each .platform/releases/<x>/ no cluster names any more",
            f"[outward] branch {branch}, commit '{title}' (signed off), push and open one PR",
        ]
        r.emit(True, ns.json)
        return 0
    ctx = envcluster.cluster_context(repo, pname, ns.context, f"cluster {pname}")
    problems = _operator_failures(prev, ctx) + _smoke_failures(prev, dirs)
    if problems:
        if ns.json:
            print(json.dumps({"promoted": False, "reason": f"{pname} is not ready", "problems": problems}, indent=2))
        else:
            print(f"NOT PROMOTED: {pname} is not ready:")
            print("\n".join(f"  {p}" for p in problems))
        return 1
    release_file = repo / "clusters" / c / "release.yaml"
    original = release_file.read_text() if release_file.exists() else None
    if target == eff["release"]:
        release_file.unlink(missing_ok=True)
    else:
        release_file.write_text(f"{RELEASE_HEADER}platform: {target}\n")
    res = _render(repo)
    if res.returncode != 0:
        if original is None:
            release_file.unlink(missing_ok=True)
        else:
            release_file.write_text(original)
        raise PlatformError(_last(res))
    _drop_unused_releases(repo)
    run(["git", "checkout", "-q", "-b", branch], cwd=repo)
    _stage(repo, c)
    run(["git", *core.git_identity(repo), "commit", "-q", "-s", "-m", title], cwd=repo)
    run(["git", "push", "-q", "-u", "origin", branch], cwd=repo)
    body = (f"Moves cluster `{c}` to platform {target}, what `{pname}` runs. The operators of `{pname}` were Synced and Healthy and the smoke "
            f"tests of its environments passed.\n\nOnly `clusters/{c}/release.yaml`, `cluster/{c}/` and the kept renderers no cluster names "
            "any more change.")
    out = run(["gh", "pr", "create", "--base", "main", "--title", title, "--body", body], cwd=repo).stdout.strip().splitlines()
    url = out[-1] if out else ""
    nxt = f"merge it; Argo CD on {c} then runs what {pname} runs. Wait with: cplat cluster wait {c} --refresh"
    if ns.json:
        Report(title=f"Promote {c} to platform {target}", did=[f"opened {url}"], next_steps=[nxt],
               data={"promoted": True, "pr": url, "platform": target}).emit(False, True)
    else:
        print(url)
        print(f"next: {nxt}")
    return 0


def main(argv: list[str]) -> int:
    return cmd_promote(build_parser().parse_args(argv[1:] if argv[:1] == ["promote"] else argv))
