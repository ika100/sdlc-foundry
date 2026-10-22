"""`status`: one table for a product — what each environment pins, how the service's CI is doing, and Argo's view."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

import core
import gitops
from core import PlatformError, Report, run

ENVS = gitops.ENVS


def sh(cmd: list[str]) -> str | None:
    """Run a command; None when the tool is missing or fails (status is best-effort and must never crash)."""
    try:
        p = run(cmd, check=False, timeout=30)
    except PlatformError:
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def pinned_tag(app_dir: Path, env: str, name: str) -> str | None:
    f = app_dir / "overlays" / env / name / "kustomization.yaml"
    if not f.is_file():
        return None
    for img in (yaml.safe_load(f.read_text()) or {}).get("images", []):
        if img.get("newTag"):
            return img["newTag"]
    return None


def ci_state(slug: str) -> str:
    out = sh(["gh", "run", "list", "-R", slug, "--branch", "main", "--workflow", "ci", "--limit", "1", "--json", "status,conclusion", "-q", '.[0]|"\\(.status) \\(.conclusion)"'])
    if not out:
        return "?"
    status, _, concl = out.partition(" ")
    return "running" if status != "completed" else ("ok" if concl == "success" else concl or "?")


def platform_of(slug: str, latest: str) -> str:
    """Spec 083: the service repo's stamped platform version, marked when it is behind `latest`."""
    out = sh(["gh", "api", f"repos/{slug}/contents/.platform-version", "-H", "Accept: application/vnd.github.raw"])
    if out is None:
        return "none"
    m = re.search(r"^platform:\s*(\d+\.\d+\.\d+)", out, re.M)
    if not m:
        return "none"
    v = m.group(1)
    try:
        return f"{v} (behind)" if core.vtuple(v) < core.vtuple(latest) else v
    except ValueError:
        return v


def argo_state(context: str | None) -> dict[str, str]:
    if not context:
        return {}
    out = sh(["kubectl", "--context", context, "-n", "argocd", "get", "applications", "-o", "json"])
    if not out:
        return {}
    items = json.loads(out).get("items", [])
    return {i["metadata"]["name"]: f"{i['status'].get('sync', {}).get('status', '?')}/{i['status'].get('health', {}).get('status', '?')}" for i in items}


def pin_prs(repo: Path) -> dict[str, str]:
    """Spec 062: open pin/dev-<service>-<sha7> PRs in the gitops-app repo -> "#<n> sha-<sha7>" per service."""
    url = sh(["git", "-C", str(repo), "remote", "get-url", "origin"]) or ""
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    if not m:
        return {}
    out = sh(["gh", "pr", "list", "-R", m.group(1), "--state", "open", "--json", "number,headRefName", "--limit", "100"])
    found: dict[str, str] = {}
    for pr in json.loads(out) if out else []:
        m = re.match(r"pin/dev-(.+)-([0-9a-f]{7})$", pr.get("headRefName", ""))
        if m:
            found.setdefault(m.group(1), f"#{pr['number']} sha-{m.group(2)}")
    return found


def collect(repo: Path, app: str | None, context: str | None) -> tuple[str, list[dict]]:
    app_dir = gitops.find_app(repo, app)
    data = yaml.safe_load((app_dir / "services.yaml").read_text()) or {}
    argo = argo_state(context)
    pins = pin_prs(repo)
    latest = core.platform_version()
    rows = []
    for s in data.get("services") or []:
        envs = s.get("environments") or ["dev"]
        ci = ci_state(s["repo"]) if s.get("repo") else "?"
        plat = platform_of(s["repo"], latest) if s.get("repo") else "-"
        for env in ENVS:
            if env not in envs:
                continue
            rows.append({"service": s["name"], "env": env, "tag": pinned_tag(app_dir, env, s["name"]) or "?",
                         "ci": ci, "argo": argo.get(f"{s['name']}-{env}", "-" if not context else "missing"),
                         "exposed": bool(s.get("expose")), "pin_pr": pins.get(s["name"], "-") if env == "dev" else "-",
                         "platform": plat})
    cfg_file = app_dir / "app.yaml"
    declared = list(((yaml.safe_load(cfg_file.read_text()) or {}).get("addons") or {})) if cfg_file.is_file() else []
    for name in declared:   # an addon runs in every environment where a service uses it
        for env in ENVS:
            if any((name == "observability" or name in (s.get("uses") or [])) and env in (s.get("environments") or ["dev"]) for s in data.get("services") or []):
                rows.append({"service": f"{name} (addon)", "env": env, "tag": "-", "ci": "-",
                             "argo": argo.get(f"addon-{name}-{env}", "-" if not context else "missing"), "exposed": False, "pin_pr": "-",
                             "platform": "-"})
    return app_dir.name, rows


def render_table(app: str, rows: list[dict], stamp: dict, context: str | None) -> str:
    head = f"## {app} (gitops-app) — platform {core.platform_version()} available, repo stamped {stamp.get('platform', 'none')}"
    cols = ["service", "env", "tag", "ci", "argo", "pin_pr", "platform"]
    title = {"pin_pr": "pin PR"}
    widths = {c: max(len(title.get(c, c)), *(len(str(r.get(c, "-"))) for r in rows)) if rows else len(title.get(c, c)) for c in cols}
    lines = [head, ""] + ["  " + "  ".join(title.get(c, c).ljust(widths[c]) for c in cols), "  " + "  ".join("-" * widths[c] for c in cols)]
    for r in rows:
        lines.append("  " + "  ".join(str(r.get(c, "-")).ljust(widths[c]) for c in cols))
    if not rows:
        lines.append("  (no services yet — /gitops:compose add <service>)")
    if not context:
        lines += ["", "Argo column empty? pass --context <kube-context> (e.g. k3d-" + app + "-local)."]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat status", description=__doc__)
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--app")
    ap.add_argument("--context", help="kube context to read ArgoCD applications from")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    repo = Path(ns.repo_dir).resolve()
    app, rows = collect(repo, ns.app, ns.context)
    if ns.json:
        print(json.dumps({"app": app, "rows": rows}, indent=2))
    else:
        print(render_table(app, rows, core.read_stamp(repo), ns.context))
    return 0
