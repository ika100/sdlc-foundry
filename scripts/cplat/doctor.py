"""`doctor`: preflight checks with a concrete fix for every problem."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import core
import settings
import shapecmd
from core import PLATFORM_ROOT, run

OK, WARN, FAIL = "ok", "warn", "fail"
ICON = {OK: "✓", WARN: "!", FAIL: "✗"}
LOCAL_CONTEXT_PREFIXES = ("k3d-", "kind-", "docker-desktop", "minikube", "rancher-desktop", "orbstack")


def check(status: str, name: str, detail: str, fix: str | None = None) -> dict:
    return {"status": status, "name": name, "detail": detail, "fix": fix}


def check_tools() -> list[dict]:
    out = []
    for tool, required in (("git", True), ("uv", True), ("gh", True), ("devbox", False), ("docker", False)):
        if shutil.which(tool):
            out.append(check(OK, tool, shutil.which(tool)))
        else:
            out.append(check(FAIL if required else WARN, tool, "not found", core.install_hint(tool)))
    copier = shutil.which("copier") or (str(Path.home() / ".local/bin/copier") if (Path.home() / ".local/bin/copier").is_file() else None)
    out.append(check(OK, "copier", copier) if copier else check(WARN, "copier", "not installed (uv will run it ephemerally)", "uv tool install copier"))
    return out


def check_gh() -> list[dict]:
    if not shutil.which("gh"):
        return []
    p = run(["gh", "auth", "status"], check=False)
    text = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        return [check(FAIL, "gh login", "not logged in", "gh auth login")]
    out = [check(OK, "gh login", "logged in")]
    scopes = text.split("Token scopes:")[-1].splitlines()[0] if "Token scopes:" in text else ""
    for needed, why in (("repo", "create repos / PRs"), ("workflow", "push CI workflows")):
        out.append(check(OK if needed in scopes else FAIL, f"gh scope {needed}", why, None if needed in scopes else f"gh auth refresh -s {needed}"))
    pk = "packages" in scopes
    out.append(check(OK if pk else WARN, "gh scope read/write:packages", "pull private images locally (cluster-up)", None if pk else "gh auth refresh -s read:packages"))
    return out


def check_docker() -> list[dict]:
    if not shutil.which("docker"):
        return []
    p = run(["docker", "info", "--format", "{{.ServerVersion}}"], check=False, timeout=15)
    if p.returncode == 0:
        return [check(OK, "docker daemon", f"running (server {p.stdout.strip()})")]
    return [check(WARN, "docker daemon", "not running", "open -a Docker   (needed for image builds and cluster-up)")]


def check_kube() -> list[dict]:
    if not shutil.which("kubectl"):
        return []
    cur = run(["kubectl", "config", "current-context"], check=False).stdout.strip()
    if not cur:
        return [check(OK, "kube context", "none set")]
    if cur.startswith(LOCAL_CONTEXT_PREFIXES):
        return [check(OK, "kube context", f"{cur} (local)")]
    return [check(WARN, "kube context", f"{cur} looks like a NON-local cluster", "scripts always pass an explicit --context; never run kubectl apply by hand here")]


MARKETPLACE = "sdlc-foundry"
LEGACY_MARKETPLACE = "ika100-claude"   # the marketplace id before the v3.0.0 rename


def _plugins_of(marketplace: str) -> dict[str, str]:
    f = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    if not f.is_file():
        return {}
    data = json.loads(f.read_text())
    data = data.get("plugins", data)
    return {k.split("@")[0]: v[0].get("version", "?") for k, v in data.items() if k.endswith(f"@{marketplace}") and v}


def installed_plugins() -> dict[str, str]:
    return _plugins_of(MARKETPLACE)


def legacy_plugins() -> dict[str, str]:
    """Plugins still installed from the pre-v3.0.0 marketplace id (they never receive updates)."""
    return _plugins_of(LEGACY_MARKETPLACE)


def check_plugins() -> list[dict]:
    market = json.loads((PLATFORM_ROOT / ".claude-plugin" / "marketplace.json").read_text())
    avail = {p["name"]: p["version"] for p in market["plugins"]}
    have = installed_plugins()
    legacy = legacy_plugins()
    out_legacy = []
    if legacy:
        reinstall = " && ".join(f"/plugin install {n}@{MARKETPLACE}" for n in sorted(legacy))
        out_legacy.append(check(WARN, "plugins (old marketplace)", f"installed from '{LEGACY_MARKETPLACE}', renamed to '{MARKETPLACE}' in v3.0.0: {', '.join(sorted(legacy))}",
                                f"/plugin marketplace remove {LEGACY_MARKETPLACE} && /plugin marketplace add ika100/{MARKETPLACE} && {reinstall}, then RESTART Claude Code"))
    if not have:
        return out_legacy or [check(WARN, "plugins", f"none installed from {MARKETPLACE}", f"/plugin marketplace add ika100/{MARKETPLACE} && /plugin install shared@{MARKETPLACE}")]
    stale = {n: (have[n], avail[n]) for n in have if n in avail and core.vtuple(have[n]) < core.vtuple(avail[n])}
    out = list(out_legacy)
    if stale:
        names = ", ".join(f"{n} {a}→{b}" for n, (a, b) in stale.items())
        out.append(check(WARN, "plugins", f"outdated: {names}", "claude plugin marketplace update sdlc-foundry && claude plugin update <name>@sdlc-foundry, then RESTART Claude Code (a running session keeps the old prompts)"))
    else:
        out.append(check(OK, "plugins", ", ".join(f"{n} {v}" for n, v in sorted(have.items()))))
    missing = sorted(set(avail) - set(have))
    if missing:
        out.append(check(OK, "plugins not installed", ", ".join(missing) + " (install the ones your shapes need)"))
    return out


def check_platform_source() -> list[dict]:
    """Which platform copy the commands run (plugins/shared/bin/cplat sets CPLAT_SOURCE, STORY-042)."""
    src = os.environ.get("CPLAT_SOURCE", "")
    kind, _, where = src.partition(" ")
    if not src:
        return [check(WARN, "platform scripts", f"run directly from {PLATFORM_ROOT} (not through the `cplat` launcher)",
                      "update the shared plugin (0.11+) so commands call `cplat` at your plugins' version instead of fetching main")]
    if kind == "main":
        return [check(WARN, "platform scripts", f"fetched main into {where}: no marketplace checkout found next to the installed plugins",
                      f"/plugin marketplace add ika100/{MARKETPLACE} (the commands then run the version your plugins came from, offline)")]
    return [check(OK, "platform scripts", f"{kind}: {where} (v{core.platform_version()})")]


def check_repo(repo: Path) -> list[dict]:
    if not (repo / ".git").exists():
        return []
    out = []
    try:
        declared = settings.declared_shape(repo) and shapecmd.resolve(repo)   # resolve also refuses a conflicting .copier-answers.yml
    except settings.ShapeDeclarationError as e:
        return [check(FAIL, "repo shape", str(e), getattr(e, "hint", None))]
    if declared:
        out.append(check(OK, "repo shape", declared))
        try:
            out.append(check(OK, "repo platform version", f"platform source at v{core.platform_version(repo)}"))
        except OSError:
            out.append(check(WARN, "repo platform version", "platform source has no docs/CHANGELOG.md"))
        out += check_addons(repo)
        out += check_policies(repo)
        return out
    det = run(["bash", str(PLATFORM_ROOT / "scripts" / "detect-shape.sh"), str(repo)], check=False)
    shape = det.stdout.strip()
    out.append(check(OK, "repo shape", shape) if shape else check(WARN, "repo shape", "not a platform repo (no .copier-answers.yml / known markers)"))
    stamp = core.read_stamp(repo)
    if shape:
        cur = core.platform_version()
        if not stamp:
            out.append(check(WARN, "repo platform version", "no .platform-version stamp", "/platform:update"))
        elif core.vtuple(stamp.get("platform", "0.0.0")) < core.vtuple(cur):
            out.append(check(WARN, "repo platform version", f"{stamp['platform']} (platform is {cur})", "/platform:update"))
        else:
            out.append(check(OK, "repo platform version", stamp.get("platform", "?")))
    out += check_addons(repo)
    out += check_policies(repo)
    return out


def check_migration(repo: Path) -> list[dict]:
    """AC-114.39: the 4.x plugins or files are still in place; the fix is the migration."""
    fix = "cplat platform update --migrate"
    out = []
    old: list[str] = []
    for f in (repo / ".claude" / "settings.json", Path.home() / ".claude" / "settings.json"):
        try:
            enabled = (json.loads(f.read_text()) or {}).get("enabledPlugins") or {}
        except (OSError, ValueError, AttributeError):
            continue
        old += [k for k in ("app@sdlc-foundry", "gitops@sdlc-foundry") if enabled.get(k) is True and k not in old]
    if old:
        out.append(check(WARN, "plugins (4.x)", f"{', '.join(old)} enabled: these plugins hold only tombstones in 5.0", fix))
    files = sorted(str(p.relative_to(repo)) for n in ("app.yaml", "services.yaml") for p in (repo / "applications").glob(f"*/{n}"))
    if files:
        out.append(check(WARN, "system.yaml", f"4.x files still in place: {', '.join(files)}", fix))
    return out


def _models(repo: Path) -> list:
    """The model of every system in the repo; an unmigrated or unreadable one is skipped (check_migration warns)."""
    import model
    out = []
    for f in sorted((repo / "applications").glob("*/system.yaml")):
        try:
            out.append(model.load_dir(f.parent))
        except model.ModelError:
            continue
    return out


def check_addons(repo: Path) -> list[dict]:
    """A gitops-app repo that declares postgres or the lgtm dev stack needs their cluster-side parts in the cluster the user is pointed at."""
    models = _models(repo)
    postgres = any(r.type == "postgres" for m in models for r in m.resources)
    lgtm = any(e.observability is not None and e.observability.ui == "lgtm" for m in models for e in m.environments)
    if not (postgres or lgtm) or not shutil.which("kubectl"):
        return []
    out = []
    if postgres:
        have = run(["kubectl", "get", "crd", "clusters.postgresql.cnpg.io"], check=False).returncode == 0
        out.append(check(OK, "addon postgres", "CloudNativePG operator is installed in the current kube context") if have else
                   check(WARN, "addon postgres", "CloudNativePG operator not found in the current kube context", "local: devbox run cluster-up; real clusters: install the cloudnative-pg chart"))
    if lgtm:
        have = run(["kubectl", "-n", "observability", "get", "deploy", "lgtm"], check=False).returncode == 0
        out.append(check(OK, "addon observability", "the Grafana dev stack (lgtm) is installed") if have else
                   check(WARN, "addon observability", "`ui: lgtm` is declared but the dev stack is missing in the current kube context", "local: devbox run cluster-up"))
    return out


def check_policies(repo: Path) -> list[dict]:
    """An environment policy other than `off` needs Kyverno (and its CEL policy CRDs) in the cluster the user is pointed at."""
    if not shutil.which("kubectl") or not any(e.policy != "off" for m in _models(repo) for e in m.environments):
        return []
    have = run(["kubectl", "get", "crd", "namespacedvalidatingpolicies.policies.kyverno.io"], check=False).returncode == 0
    return [check(OK, "policies", "Kyverno is installed in the current kube context")] if have else \
        [check(WARN, "policies", "system.yaml sets an environment `policy` but Kyverno (1.17+) is missing in the current kube context", "local: devbox run cluster-up; real clusters: install the kyverno chart")]


def check_gitops_token(repo: Path) -> list[dict]:
    """Spec 077: a repo linked to a gitops-app needs GITOPS_TOKEN, or dev is never pinned."""
    import ship
    if not (repo / ".platform-app.yml").is_file() or not shutil.which("gh"):
        return []
    if ship.missing_gitops_token(repo):
        return [check(FAIL, "secret GITOPS_TOKEN", "not set: merges build images but dev is never pinned",
                      ship.GITOPS_TOKEN_FIX.format(slug=ship.service_slug(repo)))]
    return [check(OK, "secret GITOPS_TOKEN", "set (or not readable with this token)")]


SERVICE_REPOS_TOKEN_FIX = ("create a fine-grained token with Contents: read on every component repo in system.yaml, then: "
                           "gh secret set SERVICE_REPOS_READ_TOKEN -R {slug}")


def check_service_repos_token(repo: Path) -> list[dict]:
    """Spec 098: a gitops-app needs SERVICE_REPOS_READ_TOKEN to check PRs that carry a Service-ref marker. Warns only."""
    import ship
    name = "secret SERVICE_REPOS_READ_TOKEN"
    shape = run(["bash", str(PLATFORM_ROOT / "scripts" / "detect-shape.sh"), str(repo)], check=False).stdout.strip()
    if shape != "gitops-app":
        return []
    try:
        names = {s.get("name") for s in json.loads(ship.gh(["secret", "list", "--json", "name"], cwd=repo, check=False) or "")}
    except Exception:  # noqa: BLE001 - any unreadable list is a warning, never a failure
        names = None
    fix = SERVICE_REPOS_TOKEN_FIX.format(slug=ship.service_slug(repo))
    if names is None:
        return [check(WARN, name, "could not be read with this gh login", fix)]
    if "SERVICE_REPOS_READ_TOKEN" not in names:
        return [check(WARN, name, "not set: gitops PRs with a Service-ref marker (opened by /component:ship) fail their CRD check", fix)]
    return [check(OK, name, "set: gitops CI can read the service repos named by Service-ref markers")]


ALERTS_TOKEN_FIX = ("create a fine-grained token with Issues: read and write on every component repo in system.yaml, then: "
                    "gh secret set ALERTS_TOKEN -R {slug}")


def check_alerts_token(repo: Path) -> list[dict]:
    """Spec 092: the alert poll files issues in the service repos with ALERTS_TOKEN; without it they land in the gitops repo."""
    import ship
    name = "secret ALERTS_TOKEN"
    shape = run(["bash", str(PLATFORM_ROOT / "scripts" / "detect-shape.sh"), str(repo)], check=False).stdout.strip()
    if shape != "gitops-app":
        return []
    models = _models(repo)
    polled = any(e.observability is not None and e.observability.alerts is not False for m in models for e in m.environments)
    has_repo = any(c.repo for m in models for c in m.components)
    if not (polled and has_repo):
        return []
    try:
        names = {s.get("name") for s in json.loads(ship.gh(["secret", "list", "--json", "name"], cwd=repo, check=False) or "")}
    except Exception:  # noqa: BLE001 - any unreadable list is a warning, never a failure
        names = None
    slug = ship.service_slug(repo)
    fix = ALERTS_TOKEN_FIX.format(slug=slug)
    if names is None:
        return [check(WARN, name, "could not be read with this gh login", fix)]
    if "ALERTS_TOKEN" not in names:
        return [check(WARN, name, f"not set: alert issues for the service repos land in {slug} instead", fix)]
    return [check(OK, name, "set: alert issues go to the service repos")]


def run_store_check(st) -> dict:
    """Map a run store status (runs.StoreStatus) to a check; `cplat retro` takes its hint from here."""
    name = "run store"
    if st.state == "unset":
        return check(WARN, name, "not configured", "cplat runs init <owner/name>")
    if st.state == "public":
        return check(FAIL, name, f"{st.slug} is public: records are only written to a private repo",
                     f"gh repo edit {st.slug} --visibility private --accept-visibility-change-consequences")
    if st.state == "unreachable":
        return check(WARN, name, f"{st.slug} unreachable: {st.detail}", f"gh repo view {st.slug}")
    if st.buffered or st.pending:
        return check(WARN, name, f"{st.slug}: {st.buffered} buffered record(s), {st.pending} pending filing(s)", "cplat runs flush")
    return check(OK, name, st.slug)


def check_run_store() -> dict:
    """The private run store (spec 087): only a public store fails."""
    import runs
    try:
        st = runs.store_status(timeout=10.0)
    except Exception as e:  # noqa: BLE001
        return check(WARN, "run store", f"could not check: {e}", "cplat runs flush")
    return run_store_check(st)


def check_retro_schedule() -> list[dict]:
    """The weekly retro schedule and its secrets in the run store repo (spec 090). Never fails."""
    import autoissue
    import retro_setup
    import runs
    name = "retro schedule"
    try:
        st = runs.store_status(timeout=10.0)
        if st.state != "ok":
            return []
        slug = st.slug
        miss = retro_setup.missing(runs.open_store(slug), slug)
    except Exception as e:  # noqa: BLE001
        return [check(WARN, name, f"could not check: {e}", "cplat runs init <owner/name>")]
    if miss is None:
        return [check(WARN, name, f"secrets of {slug} could not be read with this gh login", "gh auth status")]
    if not miss:
        return [check(OK, name, f"{slug}: weekly retro scheduled (Mondays 06:00 UTC)")]
    fixes = []
    if any(m.startswith("no retro schedule") for m in miss):
        fixes.append(f"cplat runs init {slug}")
    if any("Claude" in m for m in miss):
        fixes.append(f"claude setup-token, then gh secret set CLAUDE_CODE_OAUTH_TOKEN -R {slug}")
    if any(retro_setup.GH_SECRET in m for m in miss):
        fixes.append(f"gh secret set RETRO_GH_TOKEN -R {slug}   (fine-grained: Issues read/write on "
                     f"{autoissue.default_repo()}, Contents read/write on {slug})")
    return [check(WARN, name, f"{slug}: " + "; ".join(miss), " ; ".join(fixes))]


def run_checks(repo: Path) -> list[dict]:
    import gates
    return [*check_tools(), *check_gh(), *check_docker(), *check_kube(), *check_plugins(), *check_platform_source(), *check_migration(repo), *check_repo(repo),
            *gates.check_gates(repo), *check_gitops_token(repo),
            *check_service_repos_token(repo), *check_alerts_token(repo), check_run_store(), *check_retro_schedule()]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cplat platform doctor", description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    results = run_checks(Path(ns.repo).resolve())
    if ns.json:
        print(json.dumps(results, indent=2))
    else:
        print("## Platform doctor\n")
        for c in results:
            print(f"  {ICON[c['status']]} {c['name']}: {c['detail']}")
            if c["fix"] and c["status"] != OK:
                print(f"      fix: {c['fix']}")
        bad = sum(c["status"] == FAIL for c in results)
        warn = sum(c["status"] == WARN for c in results)
        print(f"\n{'All good.' if not bad and not warn else f'{bad} problem(s), {warn} warning(s).'}")
    return 1 if any(c["status"] == FAIL for c in results) else 0
