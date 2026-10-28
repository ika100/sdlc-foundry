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
    for tool, required in (("git", True), ("uv", True), ("gh", True), ("devbox", False), ("docker", False), ("claude", False)):
        if tool == "gh" and shutil.which(tool):
            continue   # `check_gh` reports the one `gh` row (installed and logged in)
        if shutil.which(tool):
            out.append(check(OK, tool, shutil.which(tool)))
        elif tool == "claude":
            out.append(check(WARN, tool, "not found", "install Claude Code: https://docs.anthropic.com/claude-code"))
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
        return [check(FAIL, "gh", "installed, not logged in", "gh auth login")]
    out = [check(OK, "gh", "logged in")]
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


def _contexts() -> set[str]:
    return set(run(["kubectl", "config", "get-contexts", "-o", "name"], check=False).stdout.split())


def check_kube_envs(repo: Path) -> list[dict]:
    """One `kube:<env>` row per environment of the system in `repo`: the context `status` would use (spec 122, AC-122.41).

    That is CPLAT_KUBE_CONTEXT or `kube_context:` of the settings files, else the current context; ok when kubectl knows it."""
    if not shutil.which("kubectl"):
        return []
    try:
        import gitops
        import model
        envs = [e.name for e in model.load_dir(gitops.find_app(repo, None)).environments]
        ctx = settings.kube_context(repo)[0] or run(["kubectl", "config", "current-context"], check=False).stdout.strip()
        known = _contexts() if ctx else set()
    except Exception:  # noqa: BLE001  (not a gitops-app repo, or an unreadable settings file: nothing to report)
        return []
    out = []
    for env in envs:
        if ctx and ctx in known:
            out.append(check(OK, f"kube:{env}", f"{ctx}"))
        elif ctx:
            out.append(check(WARN, f"kube:{env}", f"context {ctx} is not in the kubeconfig", f"kubectl config use-context <the {env} context>"))
        else:
            out.append(check(WARN, f"kube:{env}", "no kube context set",
                             f"kubectl config use-context <the {env} context>, or set kube_context in .platform-settings.yml"))
    return out


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
        out += check_operators(repo)
        out += check_brokers(repo)
        out += check_backups(repo)
        out += check_policies(repo)
        if declared == "cluster-gitops":
            out += check_cluster(repo)
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
    out += check_operators(repo)
    out += check_brokers(repo)
    out += check_backups(repo)
    out += check_policies(repo)
    if shape == "cluster-gitops":
        out += check_cluster(repo)
    return out


def check_cluster(repo: Path) -> list[dict]:
    """AC-125.13: per listed operator installed vs expected version, per registered system its application's sync and health."""
    if not shutil.which("kubectl"):
        return []
    import yaml
    try:
        data = yaml.safe_load((repo / "cluster.yaml").read_text()) or {}
        operators = [str(o) for o in (data.get("operators") or [])]
        systems = [str(s) for s in (data.get("systems") or {})]
        table = _operators()
        for o in operators:
            table[o]
    except (OSError, ValueError, AttributeError, KeyError, TypeError, yaml.YAMLError):
        return [check(WARN, "cluster.yaml", "unreadable or not valid", "devbox run render")]
    ctx = (run(["kubectl", "config", "current-context"], check=False).stdout or "").strip() or "<ctx>"
    bootstrap = f"KUBE_CONTEXT={ctx} devbox run bootstrap"
    out = []
    for op_name in operators:
        op = table[op_name]
        want = op["operator_version"]
        selector = op.get("selector") or f"app.kubernetes.io/name={op['chart']}"
        p = run(["kubectl", "get", "deploy", "-A", "-l", selector, "-o",
                 "jsonpath={.items[*].spec.template.spec.containers[*].image}"], check=False)
        images = (p.stdout or "").split()
        ref = images[0].split("@")[0] if images else ""
        have = ref.rsplit(":", 1)[-1].removeprefix("v") if ":" in ref.rsplit("/", 1)[-1] else None
        name = f"operator {op_name}"
        if have == want:
            out.append(check(OK, name, f"installed {have}, expected {want} (cluster.yaml)"))
        elif have is None:
            out.append(check(WARN, name, f"not installed in the current kube context, expected {want} (cluster.yaml)",
                             f"{bootstrap} (local: devbox run cluster-up)"))
        else:
            out.append(check(WARN, name, f"installed {have}, expected {want} (cluster.yaml)", f"sync operator-{op_name} in Argo CD"))
    for s in systems:
        p = run(["kubectl", "-n", "argocd", "get", "application", f"system-{s}", "-o",
                 "jsonpath={.status.sync.status} {.status.health.status}"], check=False)
        name = f"system {s}"
        if p.returncode != 0:
            out.append(check(WARN, name, f"system-{s}: no such application in the current kube context", bootstrap))
            continue
        sync, _, health = (p.stdout or "").strip().partition(" ")
        if (sync, health) == ("Synced", "Healthy"):
            out.append(check(OK, name, f"system-{s}: Synced, Healthy"))
        else:
            out.append(check(WARN, name, f"system-{s}: {sync or '?'}, {health or '?'}", f"kubectl -n argocd get application system-{s} -o yaml"))
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
    """A gitops-app repo that declares the lgtm dev stack needs its cluster-side parts in the cluster the user is pointed at.

    The database operator is `check_operators`' row.
    """
    models = _models(repo)
    lgtm = any(e.observability is not None and e.observability.ui == "lgtm" for m in models for e in m.environments)
    if not lgtm or not shutil.which("kubectl"):
        return []
    out = []
    if lgtm:
        have = run(["kubectl", "-n", "observability", "get", "deploy", "lgtm"], check=False).returncode == 0
        out.append(check(OK, "addon observability", "the Grafana dev stack (lgtm) is installed") if have else
                   check(WARN, "addon observability", "`ui: lgtm` is declared but the dev stack is missing in the current kube context", "local: devbox run cluster-up"))
    return out


def _operators() -> dict:
    """OPERATORS of the platform's render.py (the expected operator versions)."""
    import importlib.util
    path = PLATFORM_ROOT / "templates" / "gitops-app" / "scripts" / "render.py"
    spec = importlib.util.spec_from_file_location("cplat_doctor_render", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.OPERATORS


def check_operators(repo: Path) -> list[dict]:
    """AC-115.18, AC-116.19, AC-117.30: the operators the in-cluster resources and backups need: installed vs expected version."""
    if not shutil.which("kubectl"):
        return []
    models = _models(repo)
    out = []
    for op_name, chart_name in (("cloudnative-pg", "cloudnative-pg"), ("seaweedfs", "seaweedfs-operator"),
                                ("plugin-barman-cloud", "plugin-barman-cloud"), ("cert-manager", "cert-manager"), ("velero", "velero"),
                                ("nack", "nack")):
        needs = _operator_needs(models, op_name)
        if needs:
            out += _operator_row(models, needs, op_name, chart_name)
    return out


def _nats_expected() -> tuple[str, dict]:
    """NATS_CHART's chart version and NATS_IMAGES of the platform's render.py."""
    import importlib.util
    path = PLATFORM_ROOT / "templates" / "gitops-app" / "scripts" / "render.py"
    spec = importlib.util.spec_from_file_location("cplat_doctor_render", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.NATS_CHART["chart_version"], mod.NATS_IMAGES


def check_brokers(repo: Path) -> list[dict]:
    """AC-119.22: one row per in-cluster broker instance: the running NATS chart and server image vs render.py's pins."""
    if not shutil.which("kubectl"):
        return []
    models = _models(repo)
    chart_want, images = _nats_expected()
    out = []
    for m in models:
        pre = f"{m.system}/" if len(models) > 1 else ""
        for ri in m.resource_instances:
            if ri.type != "broker" or ri.external:
                continue
            n = f"{m.system}-{ri.resource}"
            version = ri.sizing.get("version", "2.15")
            name = f"broker {pre}{ri.resource} ({ri.environment})"
            image_want = images.get(str(version))
            if image_want is None:
                out.append(check(WARN, name, f"unsupported NATS version {version}; supported: {', '.join(images)}",
                                 "set the broker's version in system.yaml to a supported one"))
                continue
            expected = f"nats chart {chart_want}, server {image_want}"
            app = f"{n}-{ri.environment}-nats"
            p = run(["kubectl", "-n", f"{m.system}-{ri.environment}", "get", "statefulsets.apps", n, "-o",
                     'jsonpath={.metadata.labels.helm\\.sh/chart} {.spec.template.spec.containers[?(@.name=="nats")].image}'], check=False)
            parts = (p.stdout or "").split() if p.returncode == 0 else []
            if not parts:
                out.append(check(WARN, name, f"not running in the current kube context; expected {expected}",
                                 f"sync the Argo CD application {app} (local: devbox run cluster-up)"))
                continue
            chart_have = parts[0].removeprefix("nats-").removeprefix("v")
            image_have = parts[1] if len(parts) > 1 else "-"
            if chart_have == chart_want.removeprefix("v") and image_have == image_want:
                out.append(check(OK, name, f"{expected} (expected)"))
            else:
                out.append(check(WARN, name, f"nats chart {chart_have}, server {image_have}; expected {expected}",
                                 f"sync the Argo CD application {app}"))
    return out


def _operator_needs(models: list, op_name: str) -> list[str]:
    """The environments that need operator `op_name` (design.md, versions section)."""
    envs: set[str] = set()
    for m in models:
        if op_name == "velero":
            envs |= {e.name for e in m.environments if e.backup}
        elif op_name in ("plugin-barman-cloud", "cert-manager"):
            envs |= {ri.environment for ri in m.resource_instances if ri.type == "database" and not ri.external and ri.backup}
        else:
            rtype = {"cloudnative-pg": "database", "nack": "broker"}.get(op_name, "bucket")
            envs |= {ri.environment for ri in m.resource_instances if ri.type == rtype and not ri.external}
    return sorted(envs)


def check_backups(repo: Path) -> list[dict]:
    """AC-117.23, AC-117.29: prod without backup, and prod backups that live in the cluster they protect (models only, no kubectl)."""
    import model
    prod = model.ENVIRONMENTS[-1]
    models = _models(repo)
    missing: list[str] = []
    same: list[str] = []
    fix_items: list[str] = []
    for m in models:
        pre = f"{m.system}: " if len(models) > 1 else ""
        env = next((e for e in m.environments if e.name == prod), None)
        dbs = [ri for ri in m.resource_instances if ri.environment == prod and ri.type == "database" and not ri.external]
        if any(i.environment == prod for i in m.instances):
            if env is None or not env.backup:
                missing.append(f"{pre}environment {prod}")
                fix_items.append(f"environments.{prod}.backup")
            for ri in dbs:
                if not ri.backup:
                    missing.append(f"{pre}{ri.resource}/{prod}")
                    fix_items.append(f"resources.{ri.resource}.instances.{prod}.backup")
        local = {ri.resource for ri in m.resource_instances if ri.environment == prod and not ri.external}
        same += [f"{pre}{ri.resource}/{prod} (to {ri.backup['to']})" for ri in dbs if ri.backup and ri.backup.get("to") in local]
        if env is not None and env.backup and env.backup.get("to") in local:
            same.append(f"{pre}environment {prod} (to {env.backup['to']})")
    out = []
    if missing:
        out.append(check(WARN, f"backup {prod}", f"{prod} has no backup: {', '.join(missing)}",
                         f"set {' and '.join(dict.fromkeys(fix_items))} in system.yaml (docs/BACKUP-AND-RESTORE.md)"))
    if same:
        out.append(check(WARN, "backup location", f"{prod} backups live in the same cluster: {', '.join(same)}",
                         f"use an external bucket as to for {prod}"))
    return out


def _operator_row(models: list, needs: list[str], op_name: str, chart_name: str) -> list[dict]:
    owner_envs = sorted({e.name for m in models for e in m.environments if e.name in needs and e.operators == "owner"})
    op = _operators()[op_name]
    want, chart = op["operator_version"], op["chart_version"]
    name = f"operator {op_name}"
    p = run(["kubectl", "get", "deploy", "-A", "-l", f"app.kubernetes.io/name={chart_name}", "-o",
             "jsonpath={.items[*].spec.template.spec.containers[*].image}"], check=False)
    images = (p.stdout or "").split()
    have = images[0].split("@")[0].rsplit(":", 1)[-1] if images and ":" in images[0].split("@")[0].rsplit("/", 1)[-1] else None
    have = have.removeprefix("v") if have else have
    owner = owner_envs == needs
    where = f"operators: owner in {', '.join(owner_envs)}" if owner else f"Argo CD application operator-{op_name}"
    if have == want:
        return [check(OK, name, f"installed {have}, expected {want} ({where})")]
    if have is None:
        detail = f"not installed in the current kube context, expected {want} ({where})"
        if owner:
            return [check(WARN, name, detail, f"install the {chart_name} chart {chart} (operator {want})")]
        ctx = (run(["kubectl", "config", "current-context"], check=False).stdout or "").strip() or "<ctx>"
        return [check(WARN, name, detail, f"apply operators/root.yaml once: KUBE_CONTEXT={ctx} devbox run bootstrap (local: devbox run cluster-up)")]
    detail = f"installed {have}, expected {want} ({where})"
    return [check(WARN, name, detail, f"move the {chart_name} chart to {chart} (operator {want})" if owner else f"sync operator-{op_name} in Argo CD")]


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
    import notify_config
    return [*check_tools(), *check_gh(), *check_docker(), *check_kube(), *check_kube_envs(repo), *check_plugins(), *check_platform_source(), *check_migration(repo), *check_repo(repo),
            *gates.check_gates(repo), *check_gitops_token(repo),
            *check_service_repos_token(repo), *check_alerts_token(repo), check_run_store(), *check_retro_schedule(), *notify_config.doctor_checks()]


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
