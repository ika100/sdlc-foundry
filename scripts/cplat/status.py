"""`system status`: one table for a system — per component and environment what is pinned, how CI is doing, and Argo's view."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import backupstate
import core
import gitops
import model
from core import PlatformError, run


def sh(cmd: list[str]) -> str | None:
    """Run a command; None when the tool is missing or fails (status is best-effort and must never crash)."""
    try:
        p = run(cmd, check=False, timeout=30)
    except PlatformError:
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def pinned_tag(app_dir: Path, env: str, name: str) -> str | None:
    return model.read_pin(app_dir, env, name)


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


def read_argo(context: str | None) -> dict[str, str] | None:
    """Argo application -> "sync/health"; None when the cluster cannot be read."""
    if not context:
        return {}
    out = sh(["kubectl", "--context", context, "-n", "argocd", "get", "applications", "-o", "json"])
    if not out:
        return None
    try:
        items = json.loads(out).get("items", [])
        return {i["metadata"]["name"]: f"{i['status'].get('sync', {}).get('status', '?')}/{i['status'].get('health', {}).get('status', '?')}" for i in items}
    except (ValueError, KeyError, AttributeError, TypeError):
        return None


def argo_state(context: str | None) -> dict[str, str]:
    return read_argo(context) or {}


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


def parse_contexts(values: list[str] | None, envs: list[str]) -> dict[str, str]:
    """`--context CTX` (all environments) and `--context ENV=CTX` (one environment) -> environment -> context."""
    out: dict[str, str] = {}
    plain = []
    for v in values or []:
        env, sep, ctx = v.partition("=")
        if sep and env in envs:
            out[env] = ctx
        else:
            plain.append(v)
    for v in plain:
        out.update({e: v for e in envs if e not in out})
    return out


def _smoke(repo: str, tag: str | None, env: str) -> dict | None:
    """The run-store smoke record of the pinned commit in `env` (dev or staging); None when there is none or it cannot be read."""
    import evidence
    import runs
    if env not in ("dev", "staging") or not tag or not runs.configured_repo():
        return None
    try:
        m = re.fullmatch(r"sha-([0-9a-f]{7,40})", tag)
        sha = m.group(1) if m else (evidence._release_commit(repo, tag)[1] or "")
        if not sha:
            return None
        dev, stg, _ = evidence._records(repo, {f"sha-{sha}", f"sha-{sha[:7]}"}, 30)
        return dev if env == "dev" else stg
    except Exception:  # noqa: BLE001  (status is best-effort)
        return None


def _alerts(repo: str | None) -> set[str]:
    """Environments with an open `alert` issue labelled `env:<env>` in the component repo."""
    if not repo:
        return set()
    try:
        rows = json.loads(sh(["gh", "issue", "list", "-R", repo, "--state", "open", "--label", "alert", "--json", "number,title,labels", "--limit", "50"]) or "[]")
    except ValueError:
        return set()
    return {n[4:] for r in rows if isinstance(r, dict) for n in (lb.get("name", "") for lb in r.get("labels") or []) if n.startswith("env:")}


def _green() -> set[str]:
    import evidence
    return evidence.GREEN


def cell_state(readable: bool, alert: bool, smoke: dict | None, argo: str | None) -> str:
    """unknown (Argo unreadable) > alert > NOT VERIFIED > verified > healthy > pinned."""
    if not readable:
        return "unknown"
    if alert:
        return "alert"
    outcome = (smoke or {}).get("outcome")
    if outcome:
        return "verified" if outcome in _green() else "NOT VERIFIED"
    return "healthy" if argo == "Synced/Healthy" else "pinned"


def _release_candidate(c, cell: dict, smoke: dict | None) -> dict | None:
    """Set when staging is verified and its commit is newer than the last release (AC-122.47)."""
    import evidence
    import releases
    if not c.repo or cell["state"] != "verified" or cell.get("release"):
        return None
    last = sh(["gh", "release", "view", "-R", c.repo, "--json", "tagName", "-q", ".tagName"])
    m = re.fullmatch(r"sha-([0-9a-f]{7,40})", cell["tag"] or "")
    commit = m.group(1) if m else evidence._release_commit(c.repo, cell["tag"] or "")[1]
    if not last or not commit:
        return None
    diff = releases.between(c.repo, last, commit)
    if not diff.get("commits"):
        return None
    return {"version": releases.next_version(last, diff.get("subjects") or []), "commits": diff["commits"], "specs": diff["specs"],
            "fixes": diff["fixes"], "digest": (smoke or {}).get("digest")}


def load(repo: Path, app: str | None) -> tuple[Path, model.Model]:
    app_dir = gitops.find_app(repo, app)
    return app_dir, model.load_dir(app_dir)


def collect_all(repo: Path, app: str | None, contexts: list[str] | str | None,
                loaded: tuple[Path, model.Model] | None = None) -> dict:
    """Everything `system status --json` reports except `backups`; `collect` is its 4-tuple view."""
    app_dir, m = loaded or load(repo, app)
    envs = [e.name for e in m.environments]
    if isinstance(contexts, str):
        contexts = [contexts]
    by_env = parse_contexts(contexts, envs)
    cache: dict[str, dict[str, str] | None] = {}
    argo: dict[str, dict[str, str]] = {}
    unreadable: set[str] = set()
    unavailable = []
    for env, ctx in by_env.items():
        if ctx not in cache:
            cache[ctx] = read_argo(ctx)
        if cache[ctx] is None:
            unreadable.add(env)
            unavailable.append({"source": f"cluster:{env}", "error": f"cannot read ArgoCD applications from context {ctx}"})
        else:
            argo[env] = cache[ctx] or {}
    pins = pin_prs(repo)
    latest = core.platform_version()
    libs = [c for c in m.components if c.type == "library"]
    rows = []
    for c in m.components:
        if c.type == "library":
            continue
        ci = ci_state(c.repo) if c.repo else "?"
        plat = platform_of(c.repo, latest) if c.repo else "-"
        alerts = _alerts(c.repo)
        cells: dict[str, dict | None] = {}
        candidate = None
        for env in envs:
            inst = m.instance(c.name, env)
            if inst is None:
                cells[env] = None
                continue
            miss = "unknown" if env in unreadable else ("-" if env not in by_env else "missing")
            seen = argo.get(env, {}).get(inst.argo_application, miss)
            inst.observed.update(argo=seen, ci=ci)
            smoke = _smoke(c.repo or "", inst.tag, env)
            tag = _short(inst.tag)
            pin = inst.tag or ""
            cells[env] = {"tag": tag, "ci": ci, "argo": seen, "pin_pr": pins.get(c.name) if env == "dev" else None,
                          "version": tag, "state": cell_state(env not in unreadable, env in alerts, smoke, seen),
                          "digest": (smoke or {}).get("digest") or (pin if pin.startswith("sha256:") else None),
                          "release": pin if re.fullmatch(r"v?\d+\.\d+\.\d+", pin) else None}
            if env == "staging":
                candidate = _release_candidate(c, cells[env], smoke)
        row = {"component": c.name, "type": c.type, "platform": plat, "cells": cells}
        if candidate:
            row["release_candidate"] = candidate
        rows.append(row)
    miss_of = lambda env: "unknown" if env in unreadable else ("-" if env not in by_env else "missing")  # noqa: E731
    def res_cell(env: str, app_name: str | None, external: bool = False) -> dict:
        seen = "external" if external else argo.get(env, {}).get(app_name or "", miss_of(env))
        return {"argo": seen}
    resources = []
    for r in m.resources:
        by = {ri.environment: ri for ri in m.resource_instances_of(r.name)}
        if by:
            resources.append({"resource": r.name, "cells": {
                env: (res_cell(env, by[env].argo_application, by[env].external) if env in by else None) for env in envs}})
    obs = {e.name: e.observability.argo_application for e in m.environments if e.observability and m.instances_in(e.name)}
    if obs:
        resources.append({"resource": "observability", "cells": {env: (res_cell(env, obs[env]) if env in obs else None) for env in envs}})
    rules = [{"name": e.name, "promote": None if i == 0 else e.promotion, "policy": e.policy} for i, e in enumerate(m.environments)]
    libraries = [{"component": lb.name, "used_by": [c.name for c in m.components if lb.name in c.uses or lb.name in c.libraries]} for lb in libs]
    return {"system": app_dir.name, "environments": envs, "environment_rules": rules, "rows": rows, "libraries": libraries,
            "resources": resources, "unavailable": unavailable}


def collect(repo: Path, app: str | None, context: list[str] | str | None) -> tuple[str, list[str], list[dict], list[dict]]:
    """(system, environment names, component rows, resource rows); cells are None where there is no instance."""
    d = collect_all(repo, app, context)
    return d["system"], d["environments"], d["rows"], d["resources"]


def collect_backups(repo: Path, app: str | None, contexts: list[str] | str | None,
                    loaded: tuple[Path, model.Model] | None = None) -> dict:
    """Spec 117: backup state of every database instance and environment. The cluster is read (through backupstate's kubectl seam)
    only when the system has a backup or a restore-state.yaml; otherwise every row is `off` and nothing is read."""
    app_dir, m = loaded or load(repo, app)
    by_env = parse_contexts([contexts] if isinstance(contexts, str) else contexts, [e.name for e in m.environments])
    dbs = [ri for ri in m.resource_instances if ri.type == "database"]
    states: dict[tuple[str, str], dict | None] = {}
    for ri in dbs:
        try:
            states[(ri.resource, ri.environment)] = backupstate.restore_state(app_dir, ri.environment, ri.resource)
        except backupstate.StateError:
            states[(ri.resource, ri.environment)] = None
    wanted = any(e.backup for e in m.environments) or any(ri.backup for ri in dbs if not ri.external) \
        or any(v is not None for v in states.values())
    out: dict = {"resource_instances": [], "environments": [], "_read": wanted, "_contexts": sorted(set(by_env.values()))}
    for ri in dbs:
        if wanted:
            row = backupstate.database_state(m.system, ri.resource, ri.environment, by_env.get(ri.environment), backup=bool(ri.backup),
                                             external=ri.external, state=states[(ri.resource, ri.environment)])
        else:
            row = backupstate.database_state(m.system, ri.resource, ri.environment, None, backup=False, external=ri.external)
        out["resource_instances"].append(row)
    for e in m.environments:
        out["environments"].append(backupstate.environment_state(m.system, e.name, by_env.get(e.name), backup=bool(wanted and e.backup)))
    return out


def public_backups(b: dict) -> dict:
    """The `backups` JSON: the contract fields only."""
    return {"resource_instances": [{"resource": r["resource"], "environment": r["environment"], "cluster": r["cluster"],
                                    "backup": r["backup"], "restored": r["restored"], "previous": r["previous"]}
                                   for r in b["resource_instances"]],
            "environments": b["environments"]}


def backup_lines(b: dict) -> list[str]:
    """The `Backups (...)` text section; [] when nothing has backup or a restore state."""
    if not b["_read"]:
        return []
    rows: list[tuple[str, str]] = []
    for r in b["resource_instances"]:
        label, x = f"{r['resource']}/{r['environment']}", r["backup"]
        st = x["state"]
        if st == "off":
            rows.append((label, "off"))
        elif st == "external":
            rows.append((label, "external (backed up by its provider)"))
        elif st == "unknown":
            rows.append((label, f"unknown ({x['error']})"))
        elif st == "pending":
            rows.append((label, f"last base backup never (first backup pending)  archiving ok  restore points "
                                f"{x['earliest'] + ' … ' + (x['latest'] or x['earliest']) if x['earliest'] else 'none'}"))
        else:
            arch = {"ok": "archiving ok", "failing": f"archiving failing ({x['error']})" if x["error"] else "archiving failing"}.get(
                x["archiving"] or "", "archiving unknown")
            pts = f"{x['earliest']} … {x['latest'] or x['earliest']}" if x["earliest"] else "none"
            rows.append((label, f"last base backup {x['last_success'] or 'never'}  {arch}  restore points {pts}"))
        if r["restored"]:
            why = "" if r["restored"]["ready"] else f" (not ready: {r['restored_phase']})" if r.get("restored_phase") else " (not ready)"
            rows.append((label, f"restored {r['restored']['name']}{why}"))
        if r["previous"]:
            rows.append((label, f"previous {r['previous']['name']}"))
    for e in b["environments"]:
        x, label = e["backup"], f"environment {e['environment']}"
        if x["state"] == "off":
            rows.append((label, "off"))
        elif x["state"] == "unknown":
            rows.append((label, f"unknown ({x['reason']})"))
        else:
            tail = f"{x['state']} ({x['reason']})" if x["reason"] else x["state"]
            rows.append((label, f"last backup {x['last_success'] or 'never'}  {tail}  {x['kept']} kept"))
    # The column follows the database labels (design.md's example); a longer `environment <env>` label keeps two spaces.
    db_labels = [label for label, _ in rows if not label.startswith("environment ")] or [label for label, _ in rows]
    w = max(map(len, db_labels)) + 2 if rows else 0
    shown = ", ".join(b["_contexts"]) or backupstate_current() or "the current kube context"
    return ["", f"Backups (read from the cluster {shown} now):", *(f"  {label.ljust(w - 2)}  {text}" for label, text in rows)]


def backupstate_current() -> str | None:
    return sh(["kubectl", "config", "current-context"])


def _short(tag: str | None) -> str:
    m = re.fullmatch(r"sha-([0-9a-f]{40})", tag or "")
    return f"sha-{m.group(1)[:7]}" if m else (tag or "?")


def _cell(c: dict | None) -> str:
    if c is None:
        return "-"
    if "tag" not in c:
        return f"argo {c['argo']}"
    out = f"{c['state'] + ' ' if c.get('state') else ''}{c['tag']} ci {c['ci']} argo {c['argo']}"
    return out + (f"  pin PR {c['pin_pr']}" if c.get("pin_pr") else "")


def _grid(header: list[str], body: list[list[str]]) -> list[str]:
    w = [max(len(h), *(len(r[i]) for r in body)) if body else len(h) for i, h in enumerate(header)]
    fmt = lambda r: "  " + "  ".join(v.ljust(w[i]) for i, v in enumerate(r)).rstrip()  # noqa: E731
    return [fmt(header), fmt(["-" * x for x in w]), *map(fmt, body)]


def render_table(app: str, envs: list[str], rows: list[dict], resources: list[dict], stamp: dict, context: object,
                 backups: dict | None = None) -> str:
    lines = [f"## {app} (system) — platform {core.platform_version()} available, repo stamped {stamp.get('platform', 'none')}", ""]
    if rows:
        lines += _grid(["component", *envs, "platform"], [[r["component"], *(_cell(r["cells"].get(e)) for e in envs), r["platform"]] for r in rows])
    else:
        lines.append("  (no components yet — /component:add <component>)")
    if resources:
        lines += [""] + _grid(["resource", *envs], [[r["resource"], *(_cell(r["cells"].get(e)) for e in envs)] for r in resources])
    if backups:
        lines += backup_lines(backups)
    if not context:
        lines += ["", "Argo column empty? pass --context <kube-context> (e.g. k3d-" + app + "-local)."]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat system status", description=__doc__)
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--system")
    ap.add_argument("--context", action="append", help="kube context to read ArgoCD applications from; ENV=CTX per environment (repeatable)")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    repo = Path(ns.repo_dir).resolve()
    loaded = load(repo, ns.system)
    d = collect_all(repo, ns.system, ns.context, loaded)
    backups = collect_backups(repo, ns.system, ns.context, loaded)
    if ns.json:
        print(json.dumps({**d, "backups": public_backups(backups)}, indent=2))
    else:
        print(render_table(d["system"], d["environments"], d["rows"], d["resources"], core.read_stamp(repo), ns.context, backups))
    return 0
