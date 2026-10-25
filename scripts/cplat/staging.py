"""Decide whether a build that passed its dev smoke is promoted to staging (spec 093, ADR-041).

`decide` reads the linked gitops-app through `gh api` (as `smoke.dev_url` does) and returns a `Decision`: promote, or skip with
the reason that `cplat ship deploy` prints as `Promotion (staging): not promoted: <reason>`. It never raises. The dispatch and the
wait for the pin PR live in `staging_deploy`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

import runs
import smoke
from core import PlatformError, run

SHA40 = re.compile(r"^sha-([0-9a-f]{40})$")
SHA7 = re.compile(r"^sha-([0-9a-f]{7})$")
RELEASE = re.compile(r"^\d+\.\d+\.\d+$")
WORKFLOW = ".github/workflows/pin-staging.yml"


def gh(args: list[str], *, cwd: Path | None = None, check: bool = False) -> str:
    """`gh` wrapper (tests replace this)."""
    return run(["gh", *args], cwd=cwd, check=check).stdout


@dataclass
class Decision:
    action: str                  # "promote" | "skip"
    reason: str | None
    app: str | None
    app_dir: str | None
    service: str
    tag: str
    previous: str | None
    workflow: bool

    @property
    def promote(self) -> bool:
        return self.action == "promote"


def effective(app_cfg: dict, entry: dict) -> bool:
    """The service's `promotion.staging`, else app.yaml's, else manual. True only for `auto`."""
    for conf in (entry, app_cfg):
        p = (conf or {}).get("promotion")
        if isinstance(p, dict) and p.get("staging") is not None:
            return p["staging"] == "auto"
    return False


def pr_branch(svc: str, tag: str) -> str:
    return f"pin/staging-{svc}-{tag.removeprefix('sha-')[:7]}"


def run_name(svc: str, tag: str) -> str:
    return f"pin-staging {svc} {tag}"


def record_url(run_id: str | None) -> str | None:
    store = runs.configured_repo()
    if not store or not run_id:
        return None
    return f"https://github.com/{store}/blob/HEAD/runs/{datetime.now(timezone.utc):%Y/%m/%d}/{run_id}.json"


# ---------------- reading the gitops-app ----------------

def _try(args: list[str], repo: Path) -> str:
    try:
        return gh(args, cwd=repo) or ""
    except PlatformError:
        return ""


def _read(slug: str, path: str, repo: Path) -> dict | None:
    text = _try(["api", f"repos/{slug}/contents/{path}", "-H", "Accept: application/vnd.github.raw"], repo)
    try:
        data = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _app_dirs(slug: str, repo: Path) -> list[str] | None:
    try:
        data = json.loads(_try(["api", f"repos/{slug}/contents/applications"], repo) or "null")
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return [e["name"] for e in data if isinstance(e, dict) and e.get("type") == "dir" and e.get("name")]


def staging_tag(slug: str, app_dir: str, svc: str, repo: Path | None = None) -> str | None:
    doc = _read(slug, f"{app_dir}/overlays/staging/{svc}/kustomization.yaml", repo or Path.cwd())
    images = (doc or {}).get("images")
    if isinstance(images, list) and images and isinstance(images[0], dict) and images[0].get("newTag"):
        return str(images[0]["newTag"])
    return None


def resolve(service_slug: str, tag: str | None, repo: Path | None = None) -> str | None:
    """The commit sha a staging tag names: sha-<40>, sha-<7> and X.Y.Z (through the release tag)."""
    if not tag:
        return None
    if m := SHA40.match(tag):
        return m.group(1)
    if m := SHA7.match(tag):
        ref = m.group(1)
    elif RELEASE.match(tag):
        ref = f"v{tag}"
    else:
        return None
    out = _try(["api", f"repos/{service_slug}/commits/{ref}", "--jq", ".sha"], repo or Path.cwd()).strip()
    return out if re.fullmatch(r"[0-9a-f]{40}", out) else None


def newer(service_slug: str, build: str, staging: str, repo: Path | None = None) -> str:
    """The compare status of `build...staging`: `ahead` means staging is already past the build."""
    return _try(["api", f"repos/{service_slug}/compare/{build}...{staging}", "--jq", ".status"], repo or Path.cwd()).strip()


def has_workflow(slug: str, repo: Path | None = None) -> bool:
    text = _try(["api", f"repos/{slug}/contents/{WORKFLOW}", "-H", "Accept: application/vnd.github.raw"], repo or Path.cwd())
    return bool(text.strip())


# ---------------- the decision ----------------

def _find(repo: Path, apps: list[str], svc: str):
    """(slug, app dir, entry, app.yaml) of the first linked gitops-app that lists the service, like `smoke.dev_url`."""
    me = smoke._slug(repo)
    for slug in apps:
        for a in _app_dirs(slug, repo) or []:
            services = _read(slug, f"applications/{a}/services.yaml", repo)
            entries = [e for e in (services or {}).get("services") or [] if isinstance(e, dict)]
            entry = next((e for e in entries if e.get("repo") == me), None) or next((e for e in entries if e.get("name") == svc), None)
            if entry is not None:
                return slug, f"applications/{a}", entry, _read(slug, f"applications/{a}/app.yaml", repo) or {}, me
    return None


def decide(repo: Path, st: dict, apps: list[str], svc: str, dev: smoke.SmokeResult) -> Decision:
    tag = str(st.get("deployed") or "")

    def skip(reason, **kw) -> Decision:
        base = {"app": None, "app_dir": None, "previous": None, "workflow": False}
        return Decision("skip", reason, service=svc, tag=tag, **{**base, **kw})

    if dev.outcome in {"red", "timed-out"}:
        return skip("dev smoke red")
    if dev.outcome == "not-run":
        return skip(f"dev smoke not run: {dev.reason}")
    try:
        found = _find(repo, apps or [], svc)
        if found is None:
            return skip(f"{svc} is not in the linked gitops-app")
        slug, app_dir, entry, app_cfg, me = found
        name = entry.get("name") or svc
        where = {"app": slug, "app_dir": app_dir}
        if not effective(app_cfg, entry):
            return skip(f"automatic promotion to staging is off for {name}", **where)
        if "staging" not in (entry.get("environments") or ["dev"]):
            return skip(f"{name} is not in staging yet: the first promotion is manual: /gitops:promote {name} dev staging", **where)
        previous = staging_tag(slug, app_dir, name, repo)
        where["previous"] = previous
        build = SHA40.match(tag).group(1) if SHA40.match(tag) else None
        have = resolve(me, previous, repo)
        if build and have:
            if have == build:
                return skip(f"staging already runs {tag}: nothing pinned", **where)
            if newer(me, build, have, repo) == "ahead":
                return skip(f"staging already runs a newer build of {name} ({have[:7]}): nothing pinned", **where)
        if not has_workflow(slug, repo):
            return skip(f"the gitops-app {app_dir.split('/', 1)[1]} has no pin-staging workflow (update it with /shared:update-service)", **where)
        return Decision("promote", None, slug, app_dir, name, tag, previous, True)
    except (PlatformError, OSError, ValueError) as e:
        return skip(f"{svc} is not in the linked gitops-app" if not isinstance(e, ValueError) else f"promote: {e}")
