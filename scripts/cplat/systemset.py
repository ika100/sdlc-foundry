"""`system set --env ENV`: change one environment's promote rule, policy or host in system.yaml and render the manifests."""
from __future__ import annotations

import argparse
import string
from pathlib import Path

from ruamel.yaml.scalarstring import DoubleQuotedScalarString

import gitops
from core import PlatformError, Report

POLICIES = ("audit", "enforce", "off")
STAGING_PROMOTE = ("after-dev-smoke", "manual")
PLACEHOLDERS = ("component", "system", "env")
TREES = ("applications", "bootstrap")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat system set", description=__doc__)
    p.add_argument("--env", required=True, metavar="ENV", help="the environment to change")
    p.add_argument("--promote", metavar="RULE", help="staging: after-dev-smoke|manual; prod: manual")
    p.add_argument("--policy", metavar="POLICY", help="audit|enforce|off")
    p.add_argument("--host", metavar="HOST", help="host template with {component}, {system}, {env}")
    p.add_argument("--system", help="system name when the repo has several")
    p.add_argument("--repo-dir", default=".", help="the gitops-app repo (default: current directory)")
    p.add_argument("--pr", action="store_true", help="create branch, commit, push and open a pull request")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def check_promote(env: str, value: str) -> None:
    key = f"environments.{env}.promote"
    if env == "dev":
        raise PlatformError(f"{key}: dev takes no promote rule", hint="dev follows main; only staging and prod take promote")
    if env == "prod" and value != "manual":
        raise PlatformError(f"{key}: prod takes only manual (got '{value}')", hint="allowed: manual")
    if env != "prod" and value not in STAGING_PROMOTE:
        raise PlatformError(f"{key}: '{value}' is not a promote rule", hint="allowed: " + ", ".join(STAGING_PROMOTE))


def check_policy(env: str, value: str) -> None:
    if value not in POLICIES:
        raise PlatformError(f"environments.{env}.policy: '{value}' is not a policy", hint="allowed: " + ", ".join(POLICIES))


def check_host(env: str, value: str) -> None:
    key = f"environments.{env}.host"
    if not value.strip():
        raise PlatformError(f"{key}: the host must not be empty")
    try:
        fields = [f for _, f, _, _ in string.Formatter().parse(value) if f is not None]
    except ValueError as e:
        raise PlatformError(f"{key}: malformed host template ({e})", hint="placeholders: " + ", ".join("{" + n + "}" for n in PLACEHOLDERS)) from e
    bad = sorted({f for f in fields if f not in PLACEHOLDERS})
    if bad:
        raise PlatformError(f"{key}: unknown placeholder {', '.join('{' + b + '}' for b in bad)}", hint="allowed: " + ", ".join("{" + n + "}" for n in PLACEHOLDERS))


def snapshot(repo: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for t in TREES for p in sorted((repo / t).rglob("*")) if p.is_file()}


def restore(repo: Path, before: dict[Path, bytes]) -> None:
    for t in TREES:
        for p in sorted((repo / t).rglob("*")) if (repo / t).is_dir() else []:
            if p.is_file() and p not in before:
                p.unlink()
    for p, raw in before.items():
        if not p.is_file() or p.read_bytes() != raw:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.system)
    y, data = gitops.load(app_dir)
    envs = data.get("environments") or {}
    if ns.env not in envs:
        raise PlatformError(f"no environment '{ns.env}' in {app_dir.name}", hint="environments: " + ", ".join(envs))
    wanted = {k: v for k, v in (("promote", ns.promote), ("policy", ns.policy), ("host", ns.host)) if v is not None}
    if not wanted:
        raise PlatformError("nothing to change", hint="pass at least one of --promote, --policy, --host")
    if "promote" in wanted:
        check_promote(ns.env, wanted["promote"])
    if "policy" in wanted:
        check_policy(ns.env, wanted["policy"])
    if "host" in wanted:
        check_host(ns.env, wanted["host"])
    if not ns.dry_run:
        gitops.require_clean(repo)

    r = Report(title=f"system set: {ns.env} ({app_dir.name})")
    for k, v in wanted.items():
        r.will_do.append(f"set environments.{ns.env}.{k} to {v}")
    r.will_do.append("regenerate ApplicationSets and manifests (render.py)")
    if ns.pr:
        r.will_do.append("[outward] open a pull request (branch system/set-…)")
    if ns.dry_run:
        r.data = {"pr": None}
        r.emit(True, ns.json)
        return 0

    before = snapshot(repo)
    conf = envs[ns.env]
    if conf is None:
        envs[ns.env] = conf = {}
    for k, v in wanted.items():
        conf[k] = DoubleQuotedScalarString(v) if k == "policy" and v == "off" else v    # a bare off is false in YAML 1.1
    gitops.save(app_dir, y, data)
    try:
        gitops.render(repo)
    except PlatformError:
        restore(repo, before)
        raise
    changed = gitops.rendered_changes(repo)
    r.did.append(f"updated system.yaml and regenerated {len(changed)} file(s)")
    url = None
    if ns.pr:
        keys = " ".join(wanted)
        url = gitops.open_pr(repo, f"system/set-{gitops.slug(ns.env)}", f"chore(system): set {ns.env} {keys}", f"`/system:set --env {ns.env}`: changes {keys} of environment {ns.env}. Generated files regenerated by `devbox run render`.")
        r.did.append(f"opened {url}")
        r.next_steps.append("review and merge the PR; Argo syncs after the merge")
    else:
        r.next_steps.append("review the diff, run `devbox run validate`, then commit (or re-run with --pr)")
    r.undo.append("discard the working-tree changes under applications and bootstrap")
    r.data = {"changed": changed, "pr": url}
    r.emit(False, ns.json)
    return 0
