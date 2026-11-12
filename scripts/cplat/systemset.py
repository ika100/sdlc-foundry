"""`system set --env ENV`: change one environment's promote rule, policy, host, operators or observability UI in system.yaml and render the manifests."""
from __future__ import annotations

import argparse
import string
from pathlib import Path

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

import gitops
from core import PlatformError, Report

POLICIES = ("audit", "enforce", "off")
STAGING_PROMOTE = ("after-dev-smoke", "manual")
OBSERVABILITY = ("lgtm", "none", "off")   # off removes the observability block
OPERATORS = ("owner", "install")   # owner: the cluster repo installs them (the key is set); install: the system does (no key)
PLACEHOLDERS = ("component", "system", "env")
TREES = ("applications", "bootstrap")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat system set", description=__doc__)
    p.add_argument("--env", required=True, metavar="ENV", help="the environment to change")
    p.add_argument("--promote", metavar="RULE", help="staging: after-dev-smoke|manual; prod: manual")
    p.add_argument("--policy", metavar="POLICY", help="audit|enforce|off")
    p.add_argument("--host", metavar="HOST", help="host template with {component}, {system}, {env}")
    p.add_argument("--operators", metavar="WHO", help="owner (a cluster repo installs the operators) | install (the system does)")
    p.add_argument("--observability", metavar="VALUE", help="lgtm|none (sets observability.ui) | off (removes the observability block)")
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


def check_operators(env: str, value: str) -> None:
    if value not in OPERATORS:
        raise PlatformError(f"environments.{env}.operators: '{value}' is not allowed", hint="allowed: " + ", ".join(OPERATORS))


def check_observability(env: str, value: str, block) -> None:
    key = f"environments.{env}.observability"
    block = block or {}
    if value not in OBSERVABILITY:
        raise PlatformError(f"{key}.ui: '{value}' is not allowed", hint="allowed: " + ", ".join(OBSERVABILITY))
    if value == "lgtm" and block.get("exportTo"):
        raise PlatformError(f"{key}.exportTo: ui lgtm and exportTo exclude each other (exportTo is {block['exportTo']})",
                            hint="remove exportTo from system.yaml first, or keep it with --observability none")
    others = [str(k) for k in block if k != "ui"]
    if value == "off" and others:
        raise PlatformError(f"{key}: off would remove {', '.join(others)}", hint="--observability none (keeps the collector without a UI)")


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


def add_key(conf, key: str, value) -> None:
    """Set `key` in an environment's mapping. A new key goes inside the block, before the comment lines that follow the block's
    last key (ruamel keeps those on that key, so a plain append landed below them, under the next section's comment; #429)."""
    if key in conf or not conf:
        conf[key] = value
        return
    last = list(conf)[-1]
    tail = conf.ca.items.get(last) if hasattr(conf, "ca") else None
    conf[key] = value
    if tail and len(tail) > 2 and tail[2] is not None:
        conf.ca.items[key] = [None, None, tail[2], None]
        tail[2] = None


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
    wanted = {k: v for k, v in (("promote", ns.promote), ("policy", ns.policy), ("host", ns.host), ("operators", ns.operators), ("observability", ns.observability)) if v is not None}
    if not wanted:
        raise PlatformError("nothing to change", hint="pass at least one of --promote, --policy, --host, --operators, --observability")
    if "promote" in wanted:
        check_promote(ns.env, wanted["promote"])
    if "policy" in wanted:
        check_policy(ns.env, wanted["policy"])
    if "host" in wanted:
        check_host(ns.env, wanted["host"])
    if "operators" in wanted:
        check_operators(ns.env, wanted["operators"])
    noop = None
    if "observability" in wanted:
        env_conf = envs[ns.env] or {}
        check_observability(ns.env, wanted["observability"], env_conf.get("observability"))
        if wanted["observability"] == "off" and "observability" not in env_conf:
            noop = f"environments.{ns.env}.observability is not set; nothing to remove"
            del wanted["observability"]
    if not wanted:
        r = Report(title=f"system set: {ns.env} ({app_dir.name})")
        r.did.append(noop or "nothing to change")
        r.data = {"changed": [], "pr": None}
        r.emit(ns.dry_run, ns.json)
        return 0
    if not ns.dry_run:
        gitops.require_clean(repo)

    r = Report(title=f"system set: {ns.env} ({app_dir.name})")
    if noop:
        r.will_do.append(noop)
    for k, v in wanted.items():
        r.will_do.append(f"remove environments.{ns.env}.operators (the system installs its operators)" if (k, v) == ("operators", "install")
                         else f"remove environments.{ns.env}.observability" if (k, v) == ("observability", "off")
                         else f"set environments.{ns.env}.observability.ui to {v}" if k == "observability"
                         else f"set environments.{ns.env}.{k} to {v}")
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
        if (k, v) == ("operators", "install"):
            conf.pop("operators", None)
            continue
        if k == "observability":
            if v == "off":
                conf.pop("observability", None)
                continue
            if conf.get("observability") is None:
                add_key(conf, "observability", CommentedMap())
            add_key(conf["observability"], "ui", v)
            continue
        add_key(conf, k, DoubleQuotedScalarString(v) if k == "policy" and v == "off" else v)    # a bare off is false in YAML 1.1
    gitops.save(app_dir, y, data)
    try:
        gitops.render(repo)
    except PlatformError:
        restore(repo, before)
        raise
    changed = gitops.rendered_changes(repo)
    r.did.extend(r.will_do[1 if noop else 0:][:len(wanted)])
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
