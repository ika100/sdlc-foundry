"""`promote`: pin services to a newer image in the next environment (dev → staging → prod)."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

import core
import evidence
import gitops
from core import PlatformError, Report, run

ORDER = ["dev", "staging", "prod"]
SEMVER = re.compile(r"^v?(\d+\.\d+\.\d+)$")


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args]).stdout


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat promote", description=__doc__)
    p.add_argument("items", nargs="*", help="<service...> <from-env> <to-env>   (or --all <from-env> <to-env>)")
    p.add_argument("--all", action="store_true", help="every service that is in <from-env>")
    p.add_argument("--version", help="prod: release to pin (vX.Y.Z); default: newest release tag with a published image")
    p.add_argument("--sha", help="staging: full commit SHA to pin; default: head of the service's main branch")
    p.add_argument("--no-verify", action="store_true", help="do not check that the image tag exists in GHCR")
    p.add_argument("--app")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--pr", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def image_tags(image: str) -> set[str]:
    """Tags published for a ghcr.io/<owner>/<package> image (needs read:packages)."""
    m = re.match(r"^ghcr\.io/([^/]+)/(.+)$", image)
    if not m:
        raise PlatformError(f"cannot verify tags of non-GHCR image {image}", hint="pass --no-verify")
    owner, pkg = m.groups()
    for kind in ("users", "orgs"):
        try:
            raw = gh(["api", f"/{kind}/{owner}/packages/container/{pkg}/versions?per_page=100", "--jq", "[.[].metadata.container.tags[]]"])
            return set(json.loads(raw or "[]"))
        except PlatformError:
            continue
    raise PlatformError(f"cannot list image tags of {image}", hint="gh auth refresh -s read:packages  (or pass --no-verify)")


def head_sha(repo_slug: str) -> str:
    return gh(["api", f"repos/{repo_slug}/commits/main", "-q", ".sha"]).strip()


def release_versions(repo_slug: str) -> list[str]:
    raw = gh(["api", f"repos/{repo_slug}/tags?per_page=100", "--jq", "[.[].name]"])
    versions = [t for t in json.loads(raw or "[]") if SEMVER.match(t)]
    return sorted(versions, key=lambda v: core.vtuple(SEMVER.match(v).group(1)), reverse=True)


def pick_tag(svc: dict, to_env: str, ns: argparse.Namespace) -> tuple[str, str]:
    """Returns (image_tag, human description). Staging = sha-<40> of a main build (spec 078); prod = X.Y.Z (the vX.Y.Z git tag without 'v')."""
    slug = svc["repo"]
    if to_env == "staging":
        sha = ns.sha or head_sha(slug)
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise PlatformError(f"--sha must be a full 40-character commit SHA, got '{sha}'")
        return f"sha-{sha}", f"commit {sha[:7]}"
    wanted = ns.version
    if wanted:
        m = SEMVER.match(wanted)
        if not m:
            raise PlatformError(f"--version must look like vX.Y.Z, got '{wanted}'")
        return m.group(1), f"release v{m.group(1)}"
    tags = image_tags(svc["image"]) if not ns.no_verify else set()
    for v in release_versions(slug):
        plain = SEMVER.match(v).group(1)
        if ns.no_verify or plain in tags:
            return plain, f"release v{plain}"
    raise PlatformError(f"no release of {slug} has a published image", hint=f"cut one with /svc:release in {slug} (CI publishes X.Y.Z images on v*.*.* tags)")


def _staging_tag(app_dir: Path, name: str) -> str | None:
    """The newTag staging runs now (the local overlay), or None when the service is not pinned there."""
    try:
        doc = yaml.safe_load((app_dir / "overlays" / "staging" / name / "kustomization.yaml").read_text())
        return str(doc["images"][0]["newTag"])
    except (OSError, yaml.YAMLError, KeyError, IndexError, TypeError):
        return None


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    if len(ns.items) < (2 if ns.all else 3):
        raise PlatformError("usage: promote <service...> <from> <to>   |   promote --all <from> <to>")
    *names, frm, to = ns.items
    if ns.all and names:
        raise PlatformError("--all and explicit services are mutually exclusive")
    for e in (frm, to):
        if e not in ORDER:
            raise PlatformError(f"unknown environment '{e}'", hint="dev, staging or prod")
    if ORDER.index(to) <= ORDER.index(frm):
        raise PlatformError(f"cannot promote {frm} → {to}", hint="promotion only moves forward: dev → staging → prod (dev tracks the service's main branch)")
    if to == "dev":
        raise PlatformError("dev is not a promotion target")
    if ns.version and len(names) > 1:
        raise PlatformError("--version applies to a single service")

    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.app)
    if not ns.dry_run:
        gitops.require_clean(repo)
    y, data = gitops.load(app_dir)
    services = gitops.services_of(data)
    by_name = {s["name"]: s for s in services}
    if ns.all:
        names = [s["name"] for s in services if frm in (s.get("environments") or ["dev"])]
        if not names:
            raise PlatformError(f"no service is in {frm}")
    r = Report(title=f"promote {', '.join(names)}: {frm} → {to} ({app_dir.name})")
    plan: list[tuple[str, str]] = []
    summaries: dict[str, evidence.Evidence] = {}
    for n in names:
        svc = by_name.get(n)
        if svc is None:
            raise PlatformError(f"{n} is not in services.yaml", hint="current: " + ", ".join(by_name))
        if frm not in (svc.get("environments") or ["dev"]):
            raise PlatformError(f"{n} is not in {frm} yet", hint=f"promote it through the earlier environment first")
        tag, what = pick_tag(svc, to, ns)
        if not ns.no_verify and to == "staging":
            have = image_tags(svc["image"])
            if tag not in have and f"sha-{tag[4:11]}" in have:    # built before spec 078: only the short tag exists
                tag = f"sha-{tag[4:11]}"
            if tag not in have:
                raise PlatformError(f"image {svc['image']}:{tag} does not exist yet", hint=f"wait for CI on {svc['repo']}'s main to finish (it publishes sha-<40> tags), or pass --sha of a built commit")
        elif not ns.no_verify and to == "prod" and tag not in image_tags(svc["image"]):
            raise PlatformError(f"image {svc['image']}:{tag} does not exist", hint=f"the release v{tag} must have been built by CI in {svc['repo']}")
        if to == "prod":    # spec 093: what the release has been through; it never blocks
            summaries[n] = evidence.summary(svc, f"v{tag}", _staging_tag(app_dir, n))
        plan.append((n, tag))
        r.will_do.append(f"{n}: {to} → {svc['image']}:{tag} ({what})" + ("   [PRODUCTION]" if to == "prod" else ""))
    r.will_do.append("add the environment to the service's `environments`, regenerate manifests, pin the tag")
    if ns.pr:
        r.will_do.append("[outward] open a pull request (branch promote/…)")
    if summaries:
        r.data["evidence"] = {n: ev.data() for n, ev in summaries.items()}
        if not ns.json:
            print("\n\n".join("\n".join(ev.lines()) for ev in summaries.values()) + "\n")
    if ns.dry_run:
        r.emit(True, ns.json)
        return 0

    for n, _ in plan:
        envs = by_name[n].get("environments")
        if envs is None:
            by_name[n]["environments"] = ["dev"]
            envs = by_name[n]["environments"]
        if to not in envs:
            envs.append(to)
    gitops.save(app_dir, y, data)
    gitops.render(repo)
    for n, tag in plan:  # render created the overlay at `latest`; pin the tag (render preserves it from now on)
        k = app_dir / "overlays" / to / n / "kustomization.yaml"
        doc = yaml.safe_load(k.read_text())
        doc["images"][0]["newTag"] = tag
        k.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
    gitops.render(repo)  # idempotent: proves the pin survives a re-render
    r.did.append("pinned " + ", ".join(f"{n}={t}" for n, t in plan))
    if ns.pr:
        title = f"chore(promote): {' '.join(n for n, _ in plan)} {frm}→{to}"
        body = "\n".join(f"- {n}: `{t}`" for n, t in plan) + ("\n\n**Production promotion — review carefully.**" if to == "prod" else "")
        if summaries:
            body += "\n\n## Evidence\n\n" + "\n\n".join("\n".join(ev.lines()) for ev in summaries.values())
        r.did.append("opened " + gitops.open_pr(repo, f"promote/{gitops.slug('-'.join(n for n, _ in plan))}-{to}", title, body))
        r.next_steps.append("review and merge; Argo rolls the environment after the merge")
    else:
        r.next_steps.append("review `git diff`, run `devbox run validate`, then commit (or re-run with --pr)")
    r.undo.append("revert the merged PR (Argo converges back); nothing else to clean up")
    r.data["pins"] = dict(plan)
    r.emit(False, ns.json)
    return 0
