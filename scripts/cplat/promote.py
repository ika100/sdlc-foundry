"""`instance promote`: pin components to a newer image in the next environment (dev → staging → prod)."""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

import yaml

import core
import evidence
import gitops
import model
import registry
from core import PlatformError, Report, run

SEMVER = re.compile(r"^v?(\d+\.\d+\.\d+)$")


def gh(args: list[str]) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args]).stdout


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat instance promote", description=__doc__)
    p.add_argument("items", nargs="*", metavar="component", help="the components to promote (or --all)")
    p.add_argument("--to", help="the environment to promote into (the source is the environment before it)")
    p.add_argument("--all", action="store_true", help="every component that has an instance in the source environment")
    p.add_argument("--version", help="prod: release to pin: vX.Y.Z (one component) or <component>=vX.Y.Z,… (several, one PR); "
                                     "default: each component's newest release tag with a published image")
    p.add_argument("--sha", help="staging: full commit SHA to pin; default: head of the service's main branch")
    p.add_argument("--no-verify", action="store_true", help="do not check that the image tag exists in GHCR")
    p.add_argument("--accept-digest-mismatch", metavar="REASON", default=None,
                   help="prod: promote although the release image is not the one staging tested; REASON is a sentence")
    p.add_argument("--system", dest="app", help="the system (applications/<name>) when the repo holds several")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--pr", action="store_true")
    p.add_argument("--smoke", action="store_true",
                   help="staging, after the merge: wait until staging runs the pins, then run and record each component's staging smoke")
    p.add_argument("--refresh", action="store_true", help="--smoke: ask Argo CD for a hard refresh (right after a merge you made)")
    p.add_argument("--context", help="--smoke: kube context (default: the configured one, else the current one)")
    p.add_argument("--timeout", type=float, default=None, help="--smoke: seconds to wait for staging")
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
    wanted = ns.versions.get(svc["name"]) if getattr(ns, "versions", None) is not None else ns.version
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
    raise PlatformError(f"no release of {slug} has a published image", hint=f"cut one with /component:release in {slug} (CI publishes X.Y.Z images on v*.*.* tags)")


SHA_TAG = re.compile(r"^sha-[0-9a-f]{40}$")


def _reason_ok(reason: str) -> bool:
    return len(reason.split()) >= 3 and reason.rstrip()[-1:] in ".!?"


def _check_digests(svc: dict, staging_tag: str | None, release_tag: str) -> dict:
    """Spec 106: the digest of the staging build tag against the release tag. Returns the record, or `problem` for a refusal
    the override does not cover (`fatal`) or covers (`mismatch`). A failed lookup raises (RegistryError is a PlatformError)."""
    rec = {"staging_tag": staging_tag, "staging_digest": None, "release_tag": release_tag, "release_digest": None, "result": "refused"}
    if not staging_tag or not SHA_TAG.match(staging_tag):
        rec["problem"] = f"{svc['name']}: the staging image cannot be identified: {staging_tag or 'no pinned build'}"
        rec["fatal"] = True
        return rec
    got = registry.digests(svc["image"], [staging_tag, release_tag])
    rec["staging_digest"], rec["release_digest"] = got[staging_tag], got[release_tag]
    for kind, tag in (("staging", staging_tag), ("release", release_tag)):
        if got[tag] is None:
            rec["problem"] = f"{svc['name']}: the {kind} image tag {tag} is not published in {svc['image']}"
            rec["fatal"] = True
            return rec
    if got[staging_tag] == got[release_tag]:
        rec["result"] = "match"
    else:
        rec["result"] = "mismatch"
        rec["problem"] = (f"{svc['name']}: prod would not run what staging tested: staging {staging_tag} is {got[staging_tag]}, "
                          f"release {release_tag} is {got[release_tag]}")
    return rec


def _dev_pins_before(repo: Path, app_dir: Path, component: str) -> set[str]:
    """Every tag the dev overlay of `component` pinned, according to the git history of its kustomization.yaml."""
    rel = (app_dir / model.pin_path("dev", component)).relative_to(repo)
    revisions = run(["git", "log", "--format=%H", "--", str(rel)], cwd=repo).stdout.split()
    tags: set[str] = set()
    for rev in revisions:
        shown = run(["git", "show", f"{rev}:{rel}"], cwd=repo, check=False)
        if shown.returncode == 0 and (tag := model.pin_of(yaml.safe_load(shown.stdout))):
            tags.add(tag)
    return tags


def _rollback_dev(ns: argparse.Namespace, repo: Path, app_dir: Path, names: list[str]) -> int:
    """Spec 124 (AC-124.15): the one promotion into dev, a pin back to a tag dev ran before (git history decides)."""
    if ns.all or len(names) != 1:
        raise PlatformError("a dev rollback is for one component: cplat instance promote <component> --to dev --version <tag>")
    n = names[0]
    tag = ns.versions.get(n) if ns.versions is not None else ns.version
    m = model.load_dir(app_dir)
    if m.component(n) is None:
        raise PlatformError(f"{n} is not a component of {m.system}", hint="components: " + ", ".join(c.name for c in m.components))
    if m.instance(n, "dev") is None:
        raise PlatformError(f"{n} has no instance in dev")
    if tag not in _dev_pins_before(repo, app_dir, n):
        raise PlatformError(f"{tag} is not a version dev ran before; dev follows main (a rollback pins only a previous dev version)")
    previous = model.read_pin(app_dir, "dev", n)
    r = Report(title=f"rollback {n}: dev → {tag} ({app_dir.name})")
    r.will_do.append(f"{n}: dev {previous} → {tag} (rollback)")
    r.data.update({"previous": previous, "version": tag, "pins": {n: tag}})
    if ns.pr:
        r.will_do.append("[outward] open a pull request (branch promote/…)")
    if ns.dry_run:
        r.emit(True, ns.json)
        return 0
    model.write_pin(app_dir, "dev", n, tag)
    r.did.append(f"pinned {n}={tag}")
    if ns.pr:
        title = f"chore(promote): rollback {n} dev to {tag}"
        body = f"- {n}: `{tag}` (rollback, was `{previous}`)"
        r.did.append("opened " + gitops.open_pr(repo, f"promote/{gitops.slug(n)}-dev-rollback", title, body))
        r.next_steps.append("review and merge; Argo rolls dev after the merge")
    else:
        r.next_steps.append("review `git diff`, then commit (or re-run with --pr)")
    r.undo.append(f"promote {n} --to dev --version {previous} (the tag dev ran before)")
    r.emit(False, ns.json)
    return 0


def parse_versions(value: str) -> dict[str, str]:
    """#505: `api=v0.1.0,web=v0.1.0` → {component: version}, so one prod PR carries a release of several components."""
    out: dict[str, str] = {}
    for part in value.split(","):
        n, sep, v = part.strip().partition("=")
        if not (sep and n.strip() and v.strip()):
            raise PlatformError(f"--version: '{part.strip()}' is not <component>=vX.Y.Z", hint="e.g. --version api=v0.1.0,web=v0.1.0")
        if n.strip() in out:
            raise PlatformError(f"--version names {n.strip()} twice")
        out[n.strip()] = v.strip()
    return out


def component_clone(repo: Path, slug: str) -> Path:
    """The component's clone next to the gitops repo (where `/system:ship` keeps it), cloned when missing (tests replace this)."""
    path = repo.parent / slug.split("/")[-1]
    if not path.exists():
        run(["gh", "repo", "clone", slug, str(path), "--", "-q"], cwd=repo.parent)
    return path


def _smoke_staging(ns: argparse.Namespace, repo: Path, app_dir: Path, names: list[str]) -> int:
    """#503: after a promotion to staging is merged, the same steps as the automatic one (spec 093): wait until staging runs
    the pins (`cplat system wait`), then the staging smoke of each component from its repo, recorded in the run store like
    `cplat instance verify staging`, so the prod evidence finds it. Exit code: the wait's when not READY, else the worst smoke's."""
    import envwait
    import smoke
    import waits
    if ns.to != "staging" or ns.pr or ns.dry_run:
        raise PlatformError("--smoke is a step of its own after the staging promotion was merged",
                            hint="cplat instance promote <component...> --to staging --smoke [--refresh]")
    m = model.load_dir(app_dir)
    if ns.all:
        names = [c.name for c in m.components if c.type != "library" and m.instance(c.name, "staging")]
    for n in names:
        if m.component(n) is None:
            raise PlatformError(f"{n} is not a component of {m.system}", hint="components: " + ", ".join(c.name for c in m.components))
        if m.instance(n, "staging") is None:
            raise PlatformError(f"{n} has no instance in staging", hint="merge its promotion PR first")
    command = shlex.join(["cplat", "instance", "promote", *names, "--to", "staging", "--smoke"])
    wait = argparse.Namespace(revision=None, system=ns.app, env="staging", components=names, context=ns.context, refresh=ns.refresh,
                              timeout=ns.timeout or waits.DEFAULT_TIMEOUT, interval=10.0)
    code, lines = envwait.system_wait(repo, wait, command)
    print("\n".join(lines), flush=True)
    if code != waits.REACHED:
        return code
    worst = 0
    for n in names:
        slug = m.component(n).repo
        try:
            clone = component_clone(repo, slug)
        except PlatformError as e:
            print(f"Smoke (staging) {n}: not run: cannot clone {slug}: {str(e).splitlines()[0]}", flush=True)
            worst = max(worst, 3)
            continue
        print(f"staging smoke of {n} ({clone}):", flush=True)
        worst = max(worst, smoke.main(["run", "staging", "--repo", str(clone)]))
    return worst


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    names = list(ns.items)
    ns.versions = None
    if ns.version and "=" in ns.version:
        ns.versions = parse_versions(ns.version)
        if not names and not ns.all:
            names = list(ns.versions)
    if not ns.to or (not names and not ns.all):
        raise PlatformError("promote names its target with --to: cplat instance promote <component...|--all> --to <env>")
    to = ns.to
    if to not in model.ENVIRONMENTS:
        raise PlatformError(f"unknown environment '{to}' (environments: {', '.join(model.ENVIRONMENTS)})")
    if to == model.ENVIRONMENTS[0] and not ns.version:
        raise PlatformError(f"{to} is the first environment: nothing is promoted to it (dev follows main)")
    frm = model.ENVIRONMENTS[model.ENVIRONMENTS.index(to) - 1]
    if ns.all and names:
        raise PlatformError("--all and explicit components are mutually exclusive")
    if ns.accept_digest_mismatch is not None and not _reason_ok(ns.accept_digest_mismatch):
        raise PlatformError("--accept-digest-mismatch needs a reason of at least one sentence (3 or more words, ending in . ! or ?)",
                            hint='e.g. --accept-digest-mismatch "The release was rebuilt on purpose."')
    if ns.version and ns.versions is None and len(names) > 1:
        raise PlatformError("--version vX.Y.Z names the release of one component",
                            hint="several in one PR: --version api=v0.1.0,web=v0.1.0, or leave --version out to pin each "
                                 "component's newest release")

    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.app)
    if ns.smoke:
        return _smoke_staging(ns, repo, app_dir, names)
    if not ns.dry_run:
        gitops.require_clean(repo)
    if to == model.ENVIRONMENTS[0]:
        return _rollback_dev(ns, repo, app_dir, names)
    y, data = gitops.load(app_dir)
    m = model.load_dir(app_dir)
    by_name = {}
    for c in m.components:
        if c.type == "library":
            continue
        by_name[c.name] = {"name": c.name, "repo": c.repo, "image": c.image}
    if ns.all:
        names = [c for c in by_name if m.instance(c, frm)]
        if not names:
            raise PlatformError(f"no component is in {frm}")
    if ns.versions is not None and (extra := sorted(set(ns.versions) - set(names))):
        raise PlatformError(f"--version names {', '.join(extra)}, which this promotion does not include",
                            hint="name each component once, with its version: --version api=v0.1.0,web=v0.1.0")
    r = Report(title=f"promote {', '.join(names)}: {frm} → {to} ({app_dir.name})")
    plan: list[tuple[str, str]] = []
    checks: dict[str, dict] = {}
    problems: list[str] = []
    overridden = False
    if to == "prod" and ns.no_verify:
        print("image identity not verified (--no-verify)", file=sys.stderr if ns.json else sys.stdout)
    summaries: dict[str, evidence.Evidence] = {}
    for n in names:
        svc = by_name.get(n)
        if m.instance(n, frm) is None:
            runs = ", ".join(i.environment for i in m.instances_of(n)) or "none"
            if m.component(n) is None:
                raise PlatformError(f"{n} is not a component of {m.system}", hint="components: " + ", ".join(c.name for c in m.components))
            raise PlatformError(f"{n} has no instance in {frm} (it runs in: {runs})", hint=f"promote it through {frm} first")
        tag, what = pick_tag(svc, to, ns)
        if not ns.no_verify and to == "staging":
            have = image_tags(svc["image"])
            if tag not in have and f"sha-{tag[4:11]}" in have:    # built before spec 078: only the short tag exists
                tag = f"sha-{tag[4:11]}"
            if tag not in have:
                raise PlatformError(f"image {svc['image']}:{tag} does not exist yet", hint=f"wait for CI on {svc['repo']}'s main to finish (it publishes sha-<40> tags), or pass --sha of a built commit")
        elif not ns.no_verify and to == "prod" and tag not in image_tags(svc["image"]):
            raise PlatformError(f"image {svc['image']}:{tag} does not exist", hint=f"the release v{tag} must have been built by CI in {svc['repo']}")
        staging_tag = (inst.tag if (inst := m.instance(n, "staging")) else None) if to == "prod" else None
        rec = None
        if to == "prod" and not ns.no_verify:
            rec = checks[n] = _check_digests(svc, staging_tag, tag)
            if rec.get("problem") and (rec.get("fatal") or ns.accept_digest_mismatch is None):
                problems.append(rec["problem"])
            elif rec["result"] == "mismatch":
                overridden = True
        if to == "prod":    # spec 093: what the release has been through; it never blocks
            summaries[n] = evidence.summary(svc, f"v{tag}", staging_tag)
            if rec and rec["result"] == "match":
                summaries[n].shared_digest = rec["staging_digest"]
        plan.append((n, tag))
        r.will_do.append(f"{n}: {to} → {svc['image']}:{tag} ({what})" + ("   [PRODUCTION]" if to == "prod" else ""))
    if checks:
        r.data["digests"] = {n: {k: v for k, v in c.items() if k not in ("problem", "fatal")} for n, c in checks.items()}
        for n, c in checks.items():
            r.will_do.append(f"{n} staging: {c['staging_tag']} {c['staging_digest'] or 'not found'}")
            r.will_do.append(f"{n} prod: {c['release_tag']} {c['release_digest'] or 'not found'}   [{c['result']}]")
    accepted = ""
    if overridden:
        accepted = "\n".join(f"digest mismatch accepted: {ns.accept_digest_mismatch}   ({n}: staging {c['staging_digest']}, "
                             f"release {c['release_digest']})" for n, c in checks.items() if c["result"] == "mismatch")
        r.will_do.append(accepted)
    if problems:
        if ns.dry_run:
            r.will_do += [f"REFUSED: {m}" for m in problems]
            r.emit(True, ns.json)
            return 1
        raise PlatformError("\n".join(problems), hint="re-publish the release from the tested image with the release job (it re-tags "
                            "the staging sha-<40> image), or promote the release whose image is the staging one; "
                            "a mismatch alone can be accepted with --accept-digest-mismatch \"<reason>\"")
    r.will_do.append(f"add `instances.{to}` to each component, regenerate manifests, pin the tag")
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
        entry = gitops.components_of(data)[n]
        if entry.get("instances") is None:
            entry["instances"] = {"dev": {}}
        if to not in entry["instances"]:
            entry["instances"][to] = {}
    try:
        gitops.save(app_dir, y, data)
        gitops.render(repo)
        for n, tag in plan:  # render created the overlay at `latest`; pin the tag (render preserves it from now on)
            model.write_pin(app_dir, to, n, tag)
        gitops.render(repo)  # idempotent: proves the pin survives a re-render
    except PlatformError:
        gitops.discard_changes(repo)            # spec 142 (AC-142.5): a failed promotion leaves no edit behind
        raise
    if accepted:
        r.did.append(accepted)
    r.did.append("pinned " + ", ".join(f"{n}={t}" for n, t in plan))
    if ns.pr:
        title = f"chore(promote): {' '.join(n for n, _ in plan)} {frm}→{to}"
        body = "\n".join(f"- {n}: `{t}`" for n, t in plan) + ("\n\n**Production promotion — review carefully.**" if to == "prod" else "")
        if accepted:
            body += "\n\n" + accepted
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
