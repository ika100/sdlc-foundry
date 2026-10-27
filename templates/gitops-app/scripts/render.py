#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Render ApplicationSets, overlays and Kubernetes manifests from system.yaml (ADR-014, ADR-017, ADR-054).

The GitOps repo owns every manifest. applications/<system>/system.yaml is the only hand-edited file of a system; this script derives:
  applications/<system>/applicationset.yaml                    one ApplicationSet per environment (dev/staging/prod)
  applications/<system>/overlays/<env>/<component>/            deployment.yaml, service.yaml, [httproute.yaml], kustomization.yaml
  applications/<system>/addons/<env>/<resource>/               cluster.yaml, kustomization.yaml (only where a running component `uses` the resource)
  applications/<system>/policies/<env>/                        policy.yaml, kustomization.yaml (Kyverno guard rails, unless `policy: off`)
  applications/<system>/autonomy.json                         only when system.yaml declares autonomy (spec 124): what an engine reads
  bootstrap/<system>-root.yaml                                 root Argo Application (app-of-apps), applied once by a human

A component only runs in the environments that are keys of its `instances` (none = dev), so a new component never reaches
staging/prod before `/instance:promote` adds the key. Image pins (`newTag`) live in the overlays and are preserved on re-render:
versions never appear in system.yaml. A directory that still has app.yaml or services.yaml is not rendered: run
`cplat platform update --migrate`.

system.yaml (every value explicit and reviewable; the model is described in docs/DOMAIN-MODEL.md):
  system: todo                       # required; equals the directory name
  owner: acme                        # required: a non-empty string
  gateway: {name: traefik-gateway, namespace: kube-system}         # optional (default as shown)
  secretStore: {name: platform-secrets, kind: ClusterSecretStore}   # optional: where `remote` secrets are read from
  registries: [docker.io/library/]   # optional: extra image prefixes the guard rails accept
  environments:                      # required: exactly dev, staging, prod, in this order (the promotion order)
    dev:
      host: "{component}.{system}-dev.localhost"   # placeholders {component} (expose.host or the name), {system}, {env}; none = not exposed
      url: "http://{host}:8088"                     # read by smoke/ship/verify, not by render: the URL smoke tests use
      policy: audit                                 # audit | enforce | off (default audit in dev and staging, enforce in prod)
      observability:                                # optional: this environment gets the OpenTelemetry collector (ADR-021)
        ui: lgtm                                    # none | lgtm; or exportTo: https://otlp.example.com (+ headersSecret: <secret>)
        alerts: true                                # alert issues (spec 092): false = the poll skips this environment
        rules: [{name: HighErrorRate, query: "<PromQL>", severity: warning, summary: "optional"}]   # critical | warning | info
        queryURL: https://prom.example.com/api/prom # optional; querySecret: <name> or <namespace>/<name> (key AUTHORIZATION)
        alertmanagerURL: https://am.example.com     # optional
      operators: owner                              # optional, the only value: the platform installs no operator here (spec 115)
    staging:
      promote: after-dev-smoke       # after-dev-smoke | manual (default); dev takes none; prod is always promoted by hand
    prod: {}
  autonomy: {paused: true}           # optional: every environment acts as observe (the only key; spec 124)
  # environments.<env>.autonomy (optional; prod at most act; every omitted field has its default; changes no manifest):
  #   level: act                       # observe (default) | advise | propose | act | improve
  #   engine: https://ai-ops.example.com   # http(s) URL of the engine serving this environment
  #   autoMerge: {routes: [fix], maxCriticality: low}                    # low | medium | high
  #   riskGate: {maxFiles: 5, maxLines: 200, regressionTest: true, secondReview: true}
  #   budget: {runsPerDay: 5, mergesPerDay: 2, perRun: {minutes: 60, invocations: 20, reruns: 2, cost: 3}}
  #   window: {days: [mon, tue, wed, thu, fri], from: "09:00", to: "17:00", timezone: UTC}
  #   undoWindow: 24h                  # <n>m | <n>h | <n>d
  # components.<c>.instances.<env>.autonomy: {max: propose}   # caps the instance below its environment
  components:
    todo-api:
      type: service                  # service | website | library, required with lang
      lang: python                   # python | java | go | typescript (website) | unknown (migrated 4.x entries)
      repo: org/todo-api             # where the image is built
      image: ghcr.io/org/todo-api    # no tag: the tag is pinned in the overlay (dev: latest)
      port: 8080
      probes: {liveness: /health, readiness: /ready}
      user: 65532                    # numeric non-root UID the image runs as
      volumes: {tmp: /tmp}           # writable emptyDirs (root filesystem is read-only)
      env: {LOG_LEVEL: INFO}         # non-secret wiring, e.g. API_URL: http://todo-api
      metrics: /metrics              # optional: the collector scrapes it
      secretRefs: []                 # names of existing Secrets exposed as env vars
      secrets:                       # Secrets created by External Secrets Operator (never values in git, ADR-018)
        - {name: todo-api-auth, generate: [JWT_KEY]}              # random values generated in the cluster; optional `length` (32)
        - {name: todo-api-stripe, remote: {keys: [STRIPE_KEY]}}   # read from the secret store; optional `path`, `refreshInterval`
                                     # path placeholders {system}, {env}, {secret}, {component}; default {system}-{env}-{secret}
      replicas: 1                    # one number
      resources: {requests: {cpu: 50m, memory: 128Mi}, limits: {memory: 512Mi}}
      expose: {host: api}            # optional: publish through the Gateway (the environment needs `host`)
      provides: [todo-api-rest]      # APIs declared under `apis:` (exactly one provider each)
      consumes: []
      uses: [postgres, todo-lib]     # resources of the system and library components (a library changes no manifest)
      instances:                     # the keys are the environments it runs in; absent = dev only
        dev: {}
        staging: {promote: manual}
        prod: {replicas: 2, env: {LOG_LEVEL: WARN}}    # replicas, resources, env (merged), promote, secrets (replace declared fields by name)
    todo-lib: {type: library, lang: python, repo: org/todo-lib}    # a library has no instances and renders nothing
  apis:
    todo-api-rest: {type: openapi}   # openapi | grpc | graphql | events; changes no manifest
  resources:                         # any number, each named, typed (database, bucket; cache, broker come with specs 118-119)
    orders-db:                       # name: lowercase letters, digits, hyphens; at most 30 characters; not a component name
      type: database                 # required
      version: 17                    # 15 | 16 | 17 | 18 (default 17)
      replicas: 1
      storage: 1Gi
      resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi}}
      instances: {prod: {replicas: 3, storage: 20Gi}}   # per-environment overrides: external, remote, replicas, storage, resources
    billing-db:                      # external: runs nothing, its connection Secret is synced from the secretStore
      type: database
      external: true                 # true | false (default false); per environment under instances.<env>.external
      remote: {path: "{system}-{env}-{resource}", refreshInterval: 1h}    # both optional; placeholders {system}, {env}, {resource}
    files:                           # a bucket (spec 116): the bucket is <system>-files; at most 45 characters in-cluster
      type: bucket
      storage: 10Gi                  # default 10Gi
      versioning: false              # true | false (default false)
      instances: {dev: {versioning: true}, prod: {external: true}}   # per environment: external, remote, storage, versioning

External component (spec 069, ADR-029): a component whose manifests this generator cannot express (CronJobs, volumes,
a login proxy, a Helm chart with CRDs). The package is owned by this repo or pinned to the component repo's chart;
render.py only wires it into the environments and pins its image, so pin-dev, /instance:promote and /system:status work.
It takes only type, lang, repo, image, external, provides, consumes and instances (an instance sets only `promote`):
  stock-manager:
    {type: service, lang: unknown, repo: org/stock-manager, image: ghcr.io/org/stock-manager,
     external: {kustomize: external/stock-manager, namespace: stock-manager},   # {env} allowed in the path
     instances: {dev: {}}}
  ai-ops (a chart):
    external: {helm: {repoURL: https://github.com/org/ai-ops, path: charts/ai-ops, revision: main, imageTag: image.tag},
               namespace: ai-ops, values: {replicas: 1}, envValues: {prod: {replicas: 2}}}

Usage:
  render.py            write files
  render.py --check    exit 1 if the tree differs from what would be rendered (CI / quality gate)
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

ROOT = Path(__file__).resolve().parent.parent
ENVS = ["dev", "staging", "prod"]
NOT_MIGRATED = "not migrated to 5.0: run `cplat platform update --migrate`"
MANAGED_FILES = {"deployment.yaml", "service.yaml", "httproute.yaml", "kustomization.yaml", "password-generator.yaml", "application.yaml"}
MANAGED_PREFIXES = ("externalsecret-",)
TOP_KEYS = ["system", "owner", "environments", "components", "apis", "resources", "gateway", "secretStore", "registries", "autonomy"]
ENV_KEYS = ["host", "url", "policy", "promote", "observability", "operators", "autonomy"]
# Valid type/lang pairs (the languages of shapes.yml); service/unknown is what the migration writes for a 4.x entry without a known shape.
VALID_PAIRS = [("service", "python"), ("service", "java"), ("service", "go"), ("website", "typescript"), ("library", "python"),
               ("service", "unknown")]
PAIR_TEXT = ", ".join(f"{t}/{lang}" for t, lang in VALID_PAIRS if lang != "unknown")
COMMON_KEYS = ["type", "lang", "repo"]
SERVICE_KEYS = [*COMMON_KEYS, "image", "port", "probes", "user", "volumes", "env", "secretRefs", "secrets", "replicas", "resources",
                "expose", "metrics", "provides", "consumes", "uses", "instances"]
# Keys an external component may carry: its package owns ports, probes, secrets and exposure (spec 069).
EXTERNAL_KEYS = [*COMMON_KEYS, "image", "external", "provides", "consumes", "instances"]
LIBRARY_KEYS = [*COMMON_KEYS, "provides", "consumes"]
INSTANCE_KEYS = ["replicas", "resources", "env", "promote", "secrets", "autonomy"]
RESOURCE_TYPES = ("database", "bucket", "cache", "broker")
PLANNED_TYPES = {"cache": 118, "broker": 119}     # types no release runs yet: the spec that brings each
RESOURCE_KEYS = ["type", "external", "remote", "version", "replicas", "storage", "resources", "instances"]
RESOURCE_INSTANCE_KEYS = ["external", "remote", "replicas", "storage", "resources"]
SIZING_KEYS = ["version", "replicas", "storage", "resources"]      # an external resource runs nothing: none of these
BUCKET_KEYS = ["type", "external", "remote", "storage", "versioning", "instances"]
BUCKET_INSTANCE_KEYS = ["external", "remote", "storage", "versioning"]
BUCKET_SIZING_KEYS = ["storage", "versioning"]
# The cluster objects an in-cluster bucket's SeaweedFS creates, next to `<system>-<name>` itself (design.md).
BUCKET_SUFFIXES = ("-app", "-master", "-master-peer", "-volume", "-volume-0", "-volume-peer", "-filer", "-filer-peer", "-access-key",
                   "-secret-key")
STORAGE_SIZE = re.compile(r"^[0-9]+(\.[0-9]+)?(Ki|Mi|Gi|Ti|Pi|Ei)?$")    # a Kubernetes size; scripts/cplat/addon.py uses the same pattern
S3_BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
BUCKET_NAME_MAX = 45     # the StatefulSet `<name>-volume` plus a pod revision hash must fit a 63-character label
REMOTE_KEYS = ["path", "refreshInterval"]
RESOURCE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
SUPPORTED_VERSIONS = (15, 16, 17, 18)
CNPG_SUFFIXES = ("-app", "-ca", "-replication", "-server", "-superuser", "-rw", "-ro", "-r", "-primary")
# Contract per resource type (ADR-057): the keys of the connection Secret `<system>-<name>-app` and the variables a using component gets.
TYPES = {
    "database": {"keys": ["uri", "host", "port", "dbname", "user", "password"],  # pragma: allowlist secret
                 "env": {"DATABASE_URL": "uri", "PGHOST": "host", "PGPORT": "port", "PGDATABASE": "dbname", "PGUSER": "user",
                         "PGPASSWORD": "password"}},  # pragma: allowlist secret
    "bucket": {"keys": ["endpoint", "bucket", "region", "forcePathStyle", "accessKeyId", "secretAccessKey"],
               "env": {"S3_ENDPOINT": "endpoint", "S3_BUCKET": "bucket", "S3_REGION": "region", "S3_FORCE_PATH_STYLE": "forcePathStyle",
                       "AWS_ACCESS_KEY_ID": "accessKeyId", "AWS_SECRET_ACCESS_KEY": "secretAccessKey", "AWS_REGION": "region",  # pragma: allowlist secret
                       "AWS_ENDPOINT_URL_S3": "endpoint"}},
}
API_TYPES = ["openapi", "grpc", "graphql", "events"]
POLICY_VALUES = {"audit": "Audit", "enforce": "Enforce", "off": "Off"}     # system.yaml policy -> the 4.x mode
# Pinned versions (ADR-058). Changing a pin follows spec 121. A database image is `ghcr.io/cloudnative-pg/postgresql:<major>.<minor>`
# (optionally with an `@sha256:` digest); the operator row is the CloudNativePG chart and the operator version it installs.
POSTGRES_IMAGES = {
    15: "ghcr.io/cloudnative-pg/postgresql:15.19",
    16: "ghcr.io/cloudnative-pg/postgresql:16.15",
    17: "ghcr.io/cloudnative-pg/postgresql:17.11",
    18: "ghcr.io/cloudnative-pg/postgresql:18.6",
}
SEAWEEDFS_IMAGE = "chrislusf/seaweedfs:4.51"     # every in-cluster bucket runs its own SeaweedFS of this image
OPERATORS = {
    "cloudnative-pg": {"repo_url": "https://cloudnative-pg.github.io/charts", "chart": "cloudnative-pg", "chart_version": "0.29.1",
                       "operator_version": "1.30.1", "namespace": "cnpg-system", "release": "cnpg", "crd": "clusters.postgresql.cnpg.io"},
    "seaweedfs": {"repo_url": "https://seaweedfs.github.io/seaweedfs-operator", "chart": "seaweedfs-operator", "chart_version": "0.1.45",
                  "operator_version": "1.0.42", "namespace": "seaweedfs-operator", "release": "seaweedfs-operator",
                  "crd": "buckets.seaweed.seaweedfs.com"},
}
OPERATOR_OF_TYPE = {"database": "cloudnative-pg", "bucket": "seaweedfs"}
DB_DEFAULT_RESOURCES = {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"memory": "512Mi"}}
# Resource contract (ADR-020, ADR-057): what a component gets when it `uses` a resource is in TYPES. Components never see the implementation.
ADDONS = {
    # OpenTelemetry base (ADR-021): applies to every component of an environment that has `observability`. A collector per environment
    # receives OTLP and scrapes the components' Prometheus endpoints; a UI/backend is optional (`ui: lgtm`, or `exportTo`).
    "observability": {
        "scope": "all",
        "prune": True,                      # configuration only: removing it removes the collector (a database keeps its data)
        "image": "otel/opentelemetry-collector-contrib:0.162.0",
        "defaults": {"ui": "none"},
    },
}
LEVELS = ["observe", "advise", "propose", "act", "improve"]      # autonomy levels (spec 124); each includes the ones before
LEVEL_CAP = {"dev": "improve", "staging": "improve", "prod": "act"}
AUTONOMY_KEYS = ["level", "autoMerge", "riskGate", "budget", "window", "undoWindow", "engine"]
AUTONOMY_DEFAULTS = {
    "autoMerge": {"routes": ["fix"], "maxCriticality": "low"},
    "riskGate": {"maxFiles": 5, "maxLines": 200, "regressionTest": True, "secondReview": True},
    "budget": {"runsPerDay": 5, "mergesPerDay": 2, "perRun": {"minutes": 60, "invocations": 20, "reruns": 2, "cost": 3}},
    "window": {"days": ["mon", "tue", "wed", "thu", "fri"], "from": "09:00", "to": "17:00", "timezone": "UTC"},
    "undoWindow": "24h",
}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
CRITICALITIES = ["low", "medium", "high"]
DURATION = re.compile(r"^([1-9][0-9]{0,3})[mhd]$")
HHMM = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
POLICY_API = "policies.kyverno.io/v1"
POLICY_MODES = {"Audit": "Audit", "Enforce": "Deny"}     # mode -> Kyverno validationActions
LGTM_ENDPOINT = "http://lgtm.observability.svc:4318"    # the shared all-in-one UI stack `cluster-up` installs for `ui: lgtm`
ADDON_FILES = {"cluster.yaml", "kustomization.yaml"}
ESO_API = "external-secrets.io/v1"
GEN_API = "generators.external-secrets.io/v1alpha1"
DEFAULT_STORE = {"name": "platform-secrets", "kind": "ClusterSecretStore"}
DEFAULT_GATEWAY = {"name": "traefik-gateway", "namespace": "kube-system"}
SECRET_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LITERAL_SECRET = re.compile(r"(PASSWORD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|CREDENTIAL)", re.I)
ALERT_SEVERITIES = ("critical", "warning", "info")
DNS_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class RenderError(Exception):
    pass


def fail(text: str):
    raise RenderError(text)


def dump(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)


def answers() -> dict:
    f = ROOT / ".copier-answers.yml"
    return yaml.safe_load(f.read_text()) if f.is_file() else {}


def existing_tag(kfile: Path) -> str | None:
    """Image tag already pinned in an overlay kustomization, if any."""
    if not kfile.is_file():
        return None
    doc = yaml.safe_load(kfile.read_text()) or {}
    for img in doc.get("images", []):
        if img.get("newTag"):
            return img["newTag"]
    return None


# ---------------- loading and validating system.yaml ----------------

def check_placeholders(where: str, template, allowed: list[str]) -> None:
    if not isinstance(template, str):
        fail(f"{where} must be a string")
    for name in re.findall(r"\{([^{}]*)\}", template):
        if name == "service":
            fail(f"{where}: {{service}} is {{component}} in 5.0")
        if name == "app":
            fail(f"{where}: {{app}} is {{system}} in 5.0")
        if name not in allowed:
            fail(f"{where}: unknown placeholder {{{name}}} (allowed: {', '.join('{' + a + '}' for a in allowed)})")


def check_promote(where: str, env: str, value) -> None:
    """`where` ends in `.promote`. dev follows main; staging may follow the dev smoke test; prod is always manual."""
    if env == "dev":
        fail(f"{where}: dev follows main and takes no promote")
    if env == "staging" and value not in ("after-dev-smoke", "manual"):
        fail(f"{where} must be after-dev-smoke or manual, got '{value}'")
    if env == "prod" and value != "manual":
        fail(f"{where}: prod is always promoted by hand (manual), got '{value}'")


def check_level(where: str, value) -> None:
    if not isinstance(value, str) or value not in LEVELS:
        fail(f"{where} must be one of {', '.join(LEVELS)}, got '{value}'")


def check_keys(where: str, block, allowed: list[str]) -> dict:
    if not isinstance(block, dict):
        fail(f"{where} must be a mapping")
    for k in block:
        if k not in allowed:
            fail(f"{where}: unknown key '{k}' (allowed: {', '.join(allowed)})")
    return block


def check_int(where: str, value, low: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        fail(f"{where} must be a whole number of at least {low}, got '{value}'")


def check_flag(where: str, value) -> None:
    if not isinstance(value, bool):
        fail(f"{where} must be true or false, got '{value}'")


def clock(where: str, value) -> str:
    """`"HH:MM"`; YAML 1.1 reads an unquoted `17:00` as the number 1020 (minutes), which is accepted as that time."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 1440:
        return f"{value // 60:02d}:{value % 60:02d}"
    if not isinstance(value, str) or not HHMM.match(value):
        fail(f'{where} must be "HH:MM", got \'{value}\'')
    return value


def validate_window(where: str, block) -> dict:
    block = check_keys(where, block, list(AUTONOMY_DEFAULTS["window"]))
    win = {**AUTONOMY_DEFAULTS["window"], **block}
    days = win["days"]
    if (not isinstance(days, list) or not days or len(set(map(str, days))) != len(days)
            or any(not isinstance(d, str) or d not in WEEKDAYS for d in days)):
        fail(f"{where}.days must be a non-empty list of {', '.join(WEEKDAYS)} without duplicates, got '{days}'")
    win["from"], win["to"] = clock(f"{where}.from", win["from"]), clock(f"{where}.to", win["to"])
    if win["from"] == win["to"]:
        fail(f"{where}: from and to must differ, got '{win['from']}' twice")
    tz = win["timezone"]
    try:
        if not isinstance(tz, str) or not tz or tz.startswith("/") or ".." in tz:
            raise ValueError(tz)
        ZoneInfo(tz)
    except (ValueError, ZoneInfoNotFoundError, OSError):
        fail(f"{where}.timezone must be an IANA time zone like Europe/Berlin, got '{tz}'")
    return win


def validate_autonomy(env: str, block) -> dict:
    """`environments.<env>.autonomy` (spec 124): the declared level, engine and guardrails, every omitted field at its default."""
    where = f"environments.{env}.autonomy"
    block = check_keys(where, {} if block is None else block, AUTONOMY_KEYS)
    level = block.get("level", "observe")
    check_level(f"{where}.level", level)
    if level == "improve" and LEVEL_CAP[env] == "act":
        fail(f"{where}.level: act is the highest level allowed in {env}, got '{level}'")
    engine = block.get("engine")
    if "engine" in block and (not isinstance(engine, str) or not re.match(r"^https?://[^\s/]+\S*$", engine)):
        fail(f"{where}.engine must be an http(s) URL, got '{engine}'")
    merge = check_keys(f"{where}.autoMerge", block.get("autoMerge", {}), list(AUTONOMY_DEFAULTS["autoMerge"]))
    routes = merge.get("routes", ["fix"])
    if not isinstance(routes, list):
        fail(f"{where}.autoMerge.routes must be a list (allowed: fix)")
    for r in routes:
        if r == "spec":
            fail(f"{where}.autoMerge.routes: spec is refused: a spec always needs a person's approval (allowed: fix)")
        if r != "fix":
            fail(f"{where}.autoMerge.routes: '{r}' is not a route (allowed: fix)")
    crit = merge.get("maxCriticality", "low")
    if crit not in CRITICALITIES:
        fail(f"{where}.autoMerge.maxCriticality must be one of {', '.join(CRITICALITIES)}, got '{crit}'")
    risk = check_keys(f"{where}.riskGate", block.get("riskGate", {}), list(AUTONOMY_DEFAULTS["riskGate"]))
    for k in ("maxFiles", "maxLines"):
        if k in risk:
            check_int(f"{where}.riskGate.{k}", risk[k], 1)
    for k in ("regressionTest", "secondReview"):
        if k in risk:
            check_flag(f"{where}.riskGate.{k}", risk[k])
    budget = check_keys(f"{where}.budget", block.get("budget", {}), list(AUTONOMY_DEFAULTS["budget"]))
    for k in ("runsPerDay", "mergesPerDay"):
        if k in budget:
            check_int(f"{where}.budget.{k}", budget[k], 0)
    per_run = check_keys(f"{where}.budget.perRun", budget.get("perRun", {}), list(AUTONOMY_DEFAULTS["budget"]["perRun"]))
    for k, v in per_run.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            fail(f"{where}.budget.perRun.{k} must be a number above 0, got '{v}'")
    undo = block.get("undoWindow", "24h")
    if not isinstance(undo, str) or not DURATION.match(undo):
        fail(f"{where}.undoWindow must be a duration like 24h, 90m or 2d, got '{undo}'")
    d = AUTONOMY_DEFAULTS
    return {"declared": level, "engine": engine,
            "autoMerge": {**d["autoMerge"], **merge, "routes": list(routes), "maxCriticality": crit},
            "riskGate": {**d["riskGate"], **risk},
            "budget": {**d["budget"], **budget, "perRun": {**d["budget"]["perRun"], **per_run}},
            "window": validate_window(f"{where}.window", block.get("window", {})), "undoWindow": undo}


def validate_pause(doc: dict) -> bool:
    """The top-level `autonomy: {paused: true}`."""
    block = check_keys("autonomy", {} if doc.get("autonomy") is None else doc["autonomy"], ["paused"])
    if "paused" in block and not isinstance(block["paused"], bool):
        fail("autonomy.paused must be true or false")
    return block.get("paused", False)


def lower_level(a: str, b: str) -> str:
    return a if LEVELS.index(a) <= LEVELS.index(b) else b


def autonomy_json(system: str, paused: bool, envs: dict, promote: dict, services: list[dict]) -> str:
    """The rendered `autonomy.json` an engine reads (equal to the autonomy part of `cplat model show --json`)."""
    out_envs: dict[str, dict] = {}
    for e in ENVS:
        declared = envs[e]["declared"]
        effective = "observe" if paused else "act" if declared == "improve" else declared
        out_envs[e] = {**envs[e], "effective": effective, "cap": LEVEL_CAP[e], "paused": paused,
                       "promotion": "main" if e == "dev" else promote.get(e, "manual")}
    instances = {}
    for s in services:
        for e in s["environments"]:
            top = s["_eff"][e].get("autonomy_max")
            eff = out_envs[e]["effective"]
            instances[f"{s['name']}/{e}"] = {"max": top, "effective": eff if top is None else lower_level(eff, top)}
    doc = {"schema": 1, "system": system, "paused": paused, "levels": LEVELS, "environments": out_envs, "instances": instances}
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def validate_alerts(obs: dict, where: str) -> None:
    """Alert settings of an environment's observability (spec 092). Only the poll reads them; the manifests do not change."""
    if "alerts" in obs and not isinstance(obs["alerts"], bool):
        fail(f"{where}.alerts must be true or false")
    for key in ("queryURL", "alertmanagerURL"):
        if key in obs and not (isinstance(obs[key], str) and obs[key].startswith(("http://", "https://"))):
            fail(f"{where}.{key} must be an http(s) URL")
    if "querySecret" in obs:
        parts = str(obs["querySecret"]).split("/") if isinstance(obs["querySecret"], str) else []
        if not 1 <= len(parts) <= 2 or not all(DNS_LABEL.match(p) for p in parts):
            fail(f"{where}.querySecret must be <name> or <namespace>/<name>")
    if "rules" not in obs or obs["rules"] is None:
        return
    shape = f"{where}.rules must be a list of {{name, query, severity, summary}}"
    if not isinstance(obs["rules"], list):
        fail(shape)
    seen: set[str] = set()
    for i, rule in enumerate(obs["rules"]):
        if not isinstance(rule, dict):
            fail(f"{where}.rules[{i}] (no name): rules must be a list of {{name, query, severity, summary}}")
        name = rule.get("name")
        label = name if isinstance(name, str) and name.strip() else "no name"

        def bad(problem: str) -> RenderError:
            return RenderError(f"{where}.rules[{i}] ({label}): {problem}")

        if label == "no name":
            raise bad("a rule needs a name")
        if rule.get("severity") not in ALERT_SEVERITIES:
            raise bad(f"severity '{rule.get('severity')}' must be one of {', '.join(ALERT_SEVERITIES)}")
        if name in seen:
            raise bad(f"the name '{name}' is used twice")
        seen.add(name)
        if not isinstance(rule.get("query"), str) or not rule["query"].strip():
            raise bad("query must be a non-empty string (PromQL)")
        if "summary" in rule and not isinstance(rule["summary"], str):
            raise bad("summary must be a string")


def validate_observability(env: str, obs) -> dict:
    where = f"environments.{env}.observability"
    obs = {} if obs is None else obs
    if not isinstance(obs, dict):
        fail(f"{where} must be a mapping, e.g. {{ui: lgtm}}")
    if obs.get("ui", "none") not in ("none", "lgtm"):
        fail(f"{where}.ui must be none or lgtm, got '{obs.get('ui')}'")
    if obs.get("ui") == "lgtm" and obs.get("exportTo"):
        fail(f"{where}: choose either `ui: lgtm` or `exportTo`, not both")
    if obs.get("exportTo") and not str(obs["exportTo"]).startswith(("http://", "https://")):
        fail(f"{where}.exportTo must be an http(s) OTLP/HTTP endpoint")
    if obs.get("headersSecret") and not obs.get("exportTo"):
        fail(f"{where}.headersSecret needs exportTo")
    validate_alerts(obs, where)
    return obs


def validate_environments(doc: dict) -> tuple[dict, dict]:
    """Returns (hosts, per-environment settings): policy mode, observability conf."""
    envs = doc.get("environments")
    names = list(envs) if isinstance(envs, dict) else []
    if names != ENVS:
        fail(f"environments must be dev, staging, prod in this order (the promotion order), got {', '.join(map(str, names)) or 'none'}")
    hosts: dict[str, str] = {}
    conf: dict = {"policy": {}, "observability": {}, "operators": {}, "autonomy": {}, "promote": {}, "declared": False}
    for e in ENVS:
        c = envs[e] if envs[e] is not None else {}
        if not isinstance(c, dict):
            fail(f"environments.{e} must be a mapping")
        for k in c:
            if k not in ENV_KEYS:
                fail(f"environments.{e}: unknown key '{k}' (allowed: {', '.join(ENV_KEYS)})")
        if c.get("host") is not None:
            check_placeholders(f"environments.{e}.host", c["host"], ["component", "system", "env"])
            hosts[e] = c["host"]
        if c.get("url") is not None and not isinstance(c["url"], str):
            fail(f"environments.{e}.url must be a string")
        v = c.get("policy")
        if v is None:
            conf["policy"][e] = "Enforce" if e == "prod" else "Audit"
        elif v is False or (isinstance(v, str) and v in POLICY_VALUES):    # YAML 1.1 reads an unquoted `off` as false
            conf["policy"][e] = POLICY_VALUES["off" if v is False else v]
        else:
            fail(f"environments.{e}.policy must be audit, enforce or off, got '{v}'")
        if "promote" in c:
            check_promote(f"environments.{e}.promote", e, c["promote"])
        if "observability" in c:
            conf["observability"][e] = validate_observability(e, c["observability"])
        if "operators" in c:
            if c["operators"] != "owner":
                fail(f"environments.{e}.operators must be owner, got '{c['operators']}'")
            conf["operators"][e] = "owner"
        conf["autonomy"][e] = validate_autonomy(e, c.get("autonomy"))
        conf["declared"] = conf["declared"] or "autonomy" in c
        if "promote" in c:
            conf["promote"][e] = c["promote"]
    return hosts, conf


def validate_secrets(label: str, secrets: list) -> None:
    seen = set()
    for sec in secrets:
        if not isinstance(sec, dict):
            fail(f"{label}: secrets entries need a name and `generate` or `remote`")
        sn = sec.get("name", "")
        if not isinstance(sn, str) or not SECRET_NAME.match(sn) or len(sn) > 63:
            fail(f"{label}: secret name '{sn}' must be a lowercase DNS label")
        if sn in seen:
            fail(f"{label}: duplicate secret '{sn}'")
        seen.add(sn)
        gen, rem = sec.get("generate") or [], (sec.get("remote") or {}).get("keys") or []
        if bool(gen) == bool(rem):
            fail(f"{label}: secret '{sn}' needs exactly one of `generate: [KEY...]` or `remote: {{keys: [KEY...]}}` "
                 "(generated values must not be refreshed together with fetched ones: use two secrets)")
        for k in [*gen, *rem]:
            if not ENV_KEY.match(str(k)):
                fail(f"{label}: secret '{sn}': '{k}' is not a valid environment variable name")
        if sec.get("remote") and sec["remote"].get("path") is not None:
            check_placeholders(f"{label}.secrets.{sn}.remote.path", sec["remote"]["path"], ["system", "env", "secret", "component"])


def validate_env_vars(label: str, env) -> None:
    if env is not None and not isinstance(env, dict):
        fail(f"{label}: env must be a mapping of names to values")
    for k, v in (env or {}).items():
        if LITERAL_SECRET.search(k) and str(v).strip():
            fail(f"{label}: env {k} looks like a secret; values in system.yaml are committed to git. "
                 f"Declare it under `secrets:` (generate: [{k}] or remote: {{keys: [{k}]}}) instead")


def validate_external(app_dir: Path, s: dict) -> None:
    n = s["name"]
    ext = s["external"] or {}
    if not isinstance(ext, dict):
        fail(f"components.{n}: external needs exactly one of `kustomize: <path>` or `helm: {{repoURL, path}}`")
    kinds = [k for k in ("kustomize", "helm") if k in ext]
    if len(kinds) != 1:
        fail(f"components.{n}: external needs exactly one of `kustomize: <path>` or `helm: {{repoURL, path}}`")
    if "kustomize" in ext:
        for env in s["environments"]:
            pkg = app_dir / str(ext["kustomize"]).format(env=env)
            if not (pkg / "kustomization.yaml").is_file():
                fail(f"components.{n}: {pkg.relative_to(ROOT)}/kustomization.yaml does not exist")
    else:
        helm = ext["helm"] or {}
        for k in ("repoURL", "path"):
            if not helm.get(k):
                fail(f"components.{n}: external.helm needs `{k}`")
    ns = ext.get("namespace")
    if ns is not None and not SECRET_NAME.match(str(ns)):
        fail(f"components.{n}: external.namespace '{ns}' must be a lowercase DNS label")


def names_list(items) -> str:
    return ", ".join(items) or "none"


def str_list(label: str, key: str, value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        fail(f"{label}: {key} must be a list of names")
    return value


def validate_instances(c: str, spec: dict, external: bool) -> dict:
    """The effective settings of every instance: {env: {replicas, resources, env, secrets}}; keys = where the component runs."""
    inst = spec.get("instances")
    if inst is None:
        inst = {}
    if not isinstance(inst, dict):
        fail(f"components.{c}.instances must be a mapping of environments to settings")
    for e in inst:
        if e not in ENVS:
            fail(f"components.{c}.instances: '{e}' is not an environment (environments: {', '.join(ENVS)})")
    declared = [x.get("name") for x in spec.get("secrets") or [] if isinstance(x, dict)]
    out: dict[str, dict] = {}
    for e in (inst or {"dev": {}}):
        i = inst.get(e) if inst else {}
        i = {} if i is None else i
        label = f"components.{c}.instances.{e}"
        if not isinstance(i, dict):
            fail(f"{label} must be a mapping")
        allowed = ["promote", "autonomy"] if external else INSTANCE_KEYS
        for k in i:
            if k not in allowed:
                fail(f"{label}: unknown key '{k}' (allowed: {', '.join(allowed)})")
        if "promote" in i:
            check_promote(f"{label}.promote", e, i["promote"])
        eff: dict = {}
        if "autonomy" in i:
            block = check_keys(f"{label}.autonomy", i["autonomy"] if i["autonomy"] is not None else {}, ["max"])
            if "max" in block:
                check_level(f"{label}.autonomy.max", block["max"])
            eff["autonomy_max"] = block.get("max")
        if external:
            out[e] = eff
            continue
        replicas = i.get("replicas", spec.get("replicas"))
        if replicas is not None:
            if isinstance(replicas, bool) or not isinstance(replicas, int):
                fail(f"{label}.replicas must be a number")
            eff["replicas"] = replicas
        resources = i.get("resources", spec.get("resources"))
        if resources is not None:
            eff["resources"] = resources
        env = {**(spec.get("env") or {}), **(i.get("env") or {})}
        validate_env_vars(label, i.get("env"))
        eff["env"] = env
        secrets = [dict(x) for x in spec.get("secrets") or []]
        override = i.get("secrets") or []
        if not isinstance(override, list):
            fail(f"{label}.secrets must be a list of secrets by name")
        for entry in override:
            name = entry.get("name") if isinstance(entry, dict) else None
            if name not in declared:
                fail(f"{label}.secrets: '{name}' is not a secret of {c} (declared: {names_list(map(str, declared))})")
            at = declared.index(name)
            merged = {**secrets[at], **entry}
            if "generate" in entry and "remote" not in entry:
                merged.pop("remote", None)
            if "remote" in entry and "generate" not in entry:
                merged.pop("generate", None)
            secrets[at] = merged
        validate_secrets(label, secrets)
        eff["secrets"] = secrets
        out[e] = eff
    return out


def validate_component(app_dir: Path, c: str, spec) -> dict:
    """One component as the 4.x service shape plus `environments` (where it runs) and `_eff` (per-environment settings).
    A library comes back with type `library` and none of that."""
    if not isinstance(c, str) or not SECRET_NAME.match(c):
        fail(f"components.{c}: the name must be a lowercase DNS label")
    if not isinstance(spec, dict):
        fail(f"components.{c} must be a mapping")
    if "shape" in spec:
        fail(f"components.{c}: shape is replaced by type and lang in 5.0 (e.g. type: service, lang: python)")
    if "environments" in spec:
        fail(f"components.{c}: environments is replaced by instances in 5.0 (its keys are the environments it runs in)")
    if "promotion" in spec:
        fail(f"components.{c}: promotion is replaced by instances.<env>.promote in 5.0")
    if "replicas" in spec and (isinstance(spec["replicas"], bool) or not isinstance(spec["replicas"], int)):
        fail(f"components.{c}: replicas is one number; per-environment replicas go under instances.<env>.replicas")
    image = spec.get("image")
    last = image.rsplit("/", 1)[-1] if isinstance(image, str) else ""
    if "tag" in spec or "version" in spec or ":" in last or "@" in last:
        what = "tag" if "tag" in spec else "version" if "version" in spec else "the tag of image"
        fail(f"components.{c}: versions are pinned in the overlays, not in system.yaml (remove {what})")
    t, lang = spec.get("type"), spec.get("lang")
    if t is None or lang is None:
        fail(f"components.{c}: type and lang are required (valid: {PAIR_TEXT})")
    if (t, lang) not in VALID_PAIRS:
        fail(f"components.{c}: {t}/{lang} is not a valid type/lang pair (valid: {PAIR_TEXT})")
    provides, consumes = str_list(f"components.{c}", "provides", spec.get("provides")), str_list(f"components.{c}", "consumes", spec.get("consumes"))
    base = {"name": c, "type": t, "lang": lang, "repo": spec.get("repo"), "provides": provides, "consumes": consumes}
    if t == "library":
        bad = [k for k in ("instances", "image", "port", "expose") if k in spec]
        if bad:
            fail(f"components.{c}: a library has no instances (remove {', '.join(bad)})")
        for k in spec:
            if k not in LIBRARY_KEYS:
                fail(f"components.{c}: unknown key '{k}' (allowed: {', '.join(LIBRARY_KEYS)})")
        return base
    external = "external" in spec
    allowed = EXTERNAL_KEYS if external else SERVICE_KEYS
    if external:
        extra = sorted(k for k in spec if k not in allowed)
        if extra:
            fail(f"components.{c} is external: {', '.join(extra)} belongs in its package, not in system.yaml")
        if "image" not in spec:
            fail(f"components.{c}: missing 'image' (the pin applies to it)")
    else:
        for k in spec:
            if k not in allowed:
                fail(f"components.{c}: unknown key '{k}' (allowed: {', '.join(allowed)})")
        for k in ("image", "port", "probes"):
            if k not in spec:
                fail(f"components.{c}: missing '{k}'")
        if not isinstance(spec["probes"], dict) or set(spec["probes"]) != {"liveness", "readiness"}:
            fail(f"components.{c}: probes needs liveness and readiness")
        validate_secrets(f"components.{c}", spec.get("secrets") or [])
        validate_env_vars(f"components.{c}", spec.get("env"))
    svc = {**base, "image": image, "uses": str_list(f"components.{c}", "uses", spec.get("uses"))}
    for k in ("port", "probes", "user", "volumes", "secretRefs", "expose", "metrics", "external"):
        if k in spec:
            svc[k] = spec[k]
    eff = validate_instances(c, spec, external)
    svc["environments"] = list(eff)
    svc["_eff"] = eff
    if external:
        validate_external(app_dir, svc)
    return svc


def validate_apis(doc: dict, comps: list[dict]) -> None:
    apis = doc.get("apis") or {}
    if not isinstance(apis, dict):
        fail("apis must be a mapping of names to {type}")
    for a, conf in apis.items():
        if not isinstance(conf, dict) or conf.get("type") not in API_TYPES:
            fail(f"apis.{a}: type must be openapi, grpc, graphql or events")
        for k in conf:
            if k != "type":
                fail(f"apis.{a}: unknown key '{k}' (allowed: type)")
    for c in comps:
        for key in ("provides", "consumes"):
            for a in c[key]:
                if a not in apis:
                    fail(f"components.{c['name']}: {key} '{a}', which apis: does not declare")
    for a in apis:
        providers = [c["name"] for c in comps if a in c["provides"]]
        if len(providers) != 1:
            fail(f"apis.{a}: provided by {len(providers)} components ({names_list(providers)}); an API has exactly one provider")


def check_remote(where: str, remote) -> dict:
    """`remote` of a resource or of one of its instances: {path, refreshInterval}, both optional."""
    if remote is None:
        return {}
    if not isinstance(remote, dict):
        fail(f"{where} must be a mapping, e.g. {{path: prod/{{resource}}}}")
    for k in remote:
        if k not in REMOTE_KEYS:
            fail(f"{where}: unknown key '{k}' (allowed: {', '.join(REMOTE_KEYS)})")
    if remote.get("path") is not None:
        check_placeholders(f"{where}.path", remote["path"], ["system", "env", "resource"])
    if remote.get("refreshInterval") is not None and not isinstance(remote["refreshInterval"], str):
        fail(f"{where}.refreshInterval must be a string, e.g. 1h")
    return remote


def check_replicas(where: str, replicas) -> None:
    if isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 1:
        fail(f"{where}: replicas must be a number of at least 1")


def database_version(r: str, value) -> int:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or value not in SUPPORTED_VERSIONS:
        fail(f"resources.{r}: version '{value}' is not a supported database version ({', '.join(map(str, SUPPORTED_VERSIONS))})")
    return value


def check_bucket(system: str, r: str, rc: dict, inst: dict, in_cluster: bool) -> None:
    """Value checks of a bucket (design.md, Render errors): versioning, storage, then the S3 name and length rule."""
    for where, conf in [(f"resources.{r}", rc), *[(f"resources.{r}.instances.{e}", i) for e, i in inst.items()]]:
        if "versioning" in conf and not isinstance(conf["versioning"], bool):
            fail(f"{where}: versioning must be true or false")
        if "storage" in conf and not (isinstance(conf["storage"], str) and STORAGE_SIZE.match(conf["storage"])):
            fail(f"{where}: storage must be a size such as 10Gi")
    if in_cluster:
        name = f"{system}-{r}"
        if not S3_BUCKET_NAME.match(name):
            fail(f"resources.{r}: '{name}' is not a valid S3 bucket name (3 to 63 characters, lowercase letters, digits and hyphens, "
                 "starting and ending with a letter or digit)")
        if len(name) > BUCKET_NAME_MAX:
            fail(f"resources.{r}: '{name}' is too long for the in-cluster store (at most {BUCKET_NAME_MAX} characters)")


def validate_resource(doc: dict, r: str, rc) -> dict:
    """One resource, in the check order of design.md; returns {type, external, envs: {env: effective values}}."""
    types = f"({', '.join(RESOURCE_TYPES[:-1])} or {RESOURCE_TYPES[-1]})"
    if r == "observability":
        fail("resources.observability: observability is set per environment under environments.<env>.observability")
    if not isinstance(r, str) or not RESOURCE_NAME.match(r) or len(r) > 30:
        fail(f"resources.{r}: the name must start with a lowercase letter and contain only lowercase letters, digits and hyphens "
             "(at most 30 characters)")
    if not isinstance(rc, dict) or rc.get("type") is None:
        fail(f"resources.{r}: type is required {types}")
    typ = rc["type"]
    if typ not in RESOURCE_TYPES:
        fail(f"resources.{r}: type '{typ}' is not a resource type {types}")
    if typ in PLANNED_TYPES:
        fail(f"resources.{r}: type {typ} is not available yet: spec {PLANNED_TYPES[typ]} brings it")
    bucket = typ == "bucket"
    keys = BUCKET_KEYS if bucket else RESOURCE_KEYS
    instance_keys = BUCKET_INSTANCE_KEYS if bucket else RESOURCE_INSTANCE_KEYS
    sizing_keys = BUCKET_SIZING_KEYS if bucket else SIZING_KEYS
    for k in rc:
        if k not in keys:
            fail(f"resources.{r}: unknown key '{k}' (allowed: {', '.join(keys)})")
    if "external" in rc and not isinstance(rc["external"], bool):
        fail(f"resources.{r}: external must be true or false")
    inst = rc.get("instances")
    inst = {} if inst is None else inst
    if not isinstance(inst, dict):
        fail(f"resources.{r}.instances must be a mapping of environments to {{{', '.join(instance_keys)}}}")
    base_external = rc.get("external", False)
    external: dict[str, bool] = {}
    for e, i in inst.items():
        if e not in ENVS:
            fail(f"resources.{r}.instances: '{e}' is not an environment (environments: {', '.join(ENVS)})")
        where = f"resources.{r}.instances.{e}"
        if i is not None and not isinstance(i, dict):
            fail(f"{where} must be a mapping")
        i = i or {}
        if "external" in i and not isinstance(i["external"], bool):
            fail(f"{where}: external must be true or false")
        if i.get("external", base_external):
            for k in sizing_keys:
                if k in i:
                    fail(f"{where}: an external {typ} is sized and configured at its provider (remove {k})" if bucket
                         else f"{where}: an external resource runs nothing (remove {k})")
        for k in i:
            if k not in instance_keys:
                fail(f"{where}: unknown key '{k}' (allowed: {', '.join(instance_keys)})")
    inst = {e: i or {} for e, i in inst.items()}
    for e in ENVS:
        external[e] = inst.get(e, {}).get("external", base_external)
    if all(external.values()):
        for k in sizing_keys:
            if k in rc:
                fail(f"resources.{r}: external in every environment: an external {typ} is sized and configured at its provider "
                     f"(remove {k})" if bucket else
                     f"resources.{r}: external in every environment: an external resource runs nothing (remove {k})")
    if "remote" in rc and not any(external.values()):
        fail(f"resources.{r}: remote needs external: true")
    for e, i in inst.items():
        if "remote" in i and not external[e]:
            fail(f"resources.{r}.instances.{e}: remote needs external: true in {e}")
    check_remote(f"resources.{r}.remote", rc.get("remote"))
    for e, i in inst.items():
        check_remote(f"resources.{r}.instances.{e}.remote", i.get("remote"))
    first = next((e for e in ENVS if external[e]), None)
    if first and not doc.get("secretStore"):
        fail(f"resources.{r}: external in {first} needs the system's secretStore (declare secretStore: {{name, kind}})")
    version = None
    if bucket:
        check_bucket(system=str(doc.get("system")), r=r, rc=rc, inst=inst, in_cluster=not all(external.values()))
    elif not all(external.values()):
        version = database_version(r, rc.get("version", 17))
    for where, conf in [(f"resources.{r}", rc), *[(f"resources.{r}.instances.{e}", i) for e, i in inst.items()]]:
        if "replicas" in conf:
            check_replicas(f"resources.{r}", conf["replicas"])
    envs: dict[str, dict] = {}
    for e in ENVS:
        i = inst.get(e, {})
        if external[e]:
            remote = {**(check_remote("", rc.get("remote"))), **check_remote("", i.get("remote"))}
            key = str(remote.get("path") or "{system}-{env}-{resource}").format(system=str(doc.get("system")), env=e, resource=r)
            envs[e] = {"external": True, "version": None, "replicas": None, "storage": None, "resources": None,
                       "store_key": key, "refreshInterval": str(remote.get("refreshInterval") or "1h")}
            if bucket:
                envs[e]["versioning"] = None
            continue
        if bucket:
            envs[e] = {"external": False, "version": None, "replicas": None, "storage": str(i.get("storage", rc.get("storage", "10Gi"))),
                       "resources": None, "versioning": i.get("versioning", rc.get("versioning", False)),
                       "store_key": None, "refreshInterval": None}
            continue
        storage = i.get("storage", rc.get("storage"))
        envs[e] = {"external": False, "version": version, "replicas": int(i.get("replicas", rc.get("replicas", 1))),
                   "storage": "1Gi" if storage is None else str(storage), "resources": i.get("resources", rc.get("resources")),
                   "store_key": None, "refreshInterval": None}
    return {"type": typ, "external": bool(base_external), "envs": envs}


def validate_resources(doc: dict) -> dict:
    """The normalised resources: {name: {type, external, envs: {env: {external, version, replicas, storage, resources, store_key,
    refreshInterval}}}}, with the effective values of all three environments (design.md, Renderer API)."""
    res = doc.get("resources") or {}
    if not isinstance(res, dict):
        fail("resources must be a mapping of names to resources")
    return {r: validate_resource(doc, r, rc) for r, rc in res.items()}


def object_names(system: str, r: str, typ: str) -> list[str]:
    """The cluster objects a resource creates (design.md): a database the CloudNativePG family, any other type the object and its Secret."""
    base = f"{system}-{r}"
    return [base, *(base + s for s in (CNPG_SUFFIXES if typ == "database" else BUCKET_SUFFIXES if typ == "bucket" else ("-app",)))]


def check_resource_clashes(system: str, resources: dict, comps_doc: dict, comps: list[dict]) -> None:
    for r in resources:
        if r in comps_doc:
            fail(f"resources.{r}: components.{r} has the same name; a resource and a component need different names")
    names = list(resources)
    for n, a in enumerate(names):
        for b in names[n + 1:]:
            both = [o for o in object_names(system, a, resources[a]["type"]) if o in object_names(system, b, resources[b]["type"])]
            if both:
                fail(f"resources.{a} and resources.{b} would both create the object {both[0]}; rename one")
    connection = {f"{system}-{r}-app": r for r in resources}
    for c in comps:
        for sec in (comps_doc.get(c["name"]) or {}).get("secrets") or []:
            if isinstance(sec, dict) and sec.get("name") in connection:
                fail(f"components.{c['name']}: secret '{sec['name']}' is the connection Secret of resources.{connection[sec['name']]}; rename it")


def variable_names(uses: list[str], resources: dict) -> list[tuple[str, list[str]]]:
    """(resource, variable names) per used resource in `uses` order: the bare names when the component uses one resource of that type,
    otherwise `<NAME>_<VAR>` (AC-115.8)."""
    used = [u for u in uses if u in resources]
    out = []
    for u in used:
        typ = resources[u]["type"]
        many = sum(1 for x in used if resources[x]["type"] == typ) > 1
        prefix = u.upper().replace("-", "_") + "_" if many else ""
        out.append((u, [prefix + v for v in TYPES[typ]["env"]]))
    return out


def validate_uses(comps: list[dict], resources: dict) -> None:
    libs = [c["name"] for c in comps if c["type"] == "library"]
    for s in comps:
        for u in s.get("uses") or []:
            if u not in resources and u not in libs:
                fail(f"components.{s['name']}: uses '{u}', which is neither a resource nor a library of the system "
                     f"(resources: {names_list(resources)}; libraries: {names_list(libs)})")
        for u in s.get("uses") or []:
            if u not in resources:
                continue
            names = dict(variable_names(s.get("uses") or [], resources))[u]
            for env, eff in (s.get("_eff") or {}).items():
                clash = [k for k in names if k in (eff.get("env") or {})]
                if clash:
                    fail(f"components.{s['name']}: env {', '.join(clash)} is provided by the '{u}' resource; remove it from `env`")


def load_system(app_dir: Path) -> dict:
    """Parse and validate applications/<system>/system.yaml; returns the normalized system:
    `services` (components in the 4.x service shape, libraries left out), `cfg` (gateway, secretStore, hosts, policy and observability per
    environment, resources per environment, registries), `libraries`, `system` and `owner`."""
    try:
        return _load_system(app_dir)
    except RenderError as e:
        raise RenderError(f"applications/{app_dir.name}/system.yaml: {e}") from None


def _load_system(app_dir: Path) -> dict:
    d = app_dir.name
    try:
        doc = yaml.safe_load((app_dir / "system.yaml").read_text())
    except yaml.YAMLError as e:
        fail(f"is not valid YAML ({str(e).splitlines()[0] if str(e) else e})")
    if not isinstance(doc, dict):
        fail(f"must be a mapping with {', '.join(TOP_KEYS[:4])}")
    for k in doc:
        if k not in TOP_KEYS:
            fail(f"unknown key '{k}' (allowed: {', '.join(TOP_KEYS)})")
    if doc.get("system") is None:
        fail(f"system is required (the directory is {d})")
    if str(doc["system"]) != d:
        fail(f"system '{doc['system']}' does not match the directory {d}")
    if not isinstance(doc.get("owner"), str) or not doc["owner"].strip():
        fail("owner is required: a non-empty string")
    hosts, env_conf = validate_environments(doc)
    paused = validate_pause(doc)
    comps_doc = doc.get("components") or {}
    if not isinstance(comps_doc, dict):
        fail("components must be a mapping of names to components")
    comps = [validate_component(app_dir, str(c), spec) for c, spec in comps_doc.items()]
    validate_apis(doc, comps)
    resources = validate_resources(doc)
    check_resource_clashes(d, resources, comps_doc, comps)
    validate_uses(comps, resources)
    registries = doc.get("registries") or []
    if not isinstance(registries, list):
        fail("registries must be a list of image prefixes, e.g. [ghcr.io/acme/]")
    services = [{**c, "uses": [u for u in c.get("uses") or [] if u in resources]} for c in comps if c["type"] != "library"]
    cfg = {"gateway": doc.get("gateway"), "secretStore": doc.get("secretStore"), "hosts": hosts, "registries": [str(r) for r in registries],
           "policy": env_conf["policy"], "observability": env_conf["observability"], "operators": env_conf["operators"],
           "resources": resources}
    declared = "autonomy" in doc or env_conf["declared"] or any("autonomy_max" in s["_eff"][e] for s in services for e in s["environments"])
    autonomy = autonomy_json(d, paused, env_conf["autonomy"], env_conf["promote"], services) if declared else None
    return {"system": d, "owner": doc["owner"], "autonomy": autonomy, "services": services, "libraries": [c["name"] for c in comps if c["type"] == "library"], "cfg": cfg}


# ---------------- manifests ----------------

def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def set_path(doc: dict, dotted: str, value) -> dict:
    """`image.tag` -> {"image": {"tag": value}} merged into doc."""
    keys = dotted.split(".")
    nested: dict = {keys[-1]: value}
    for k in reversed(keys[:-1]):
        nested = {k: nested}
    return deep_merge(doc, nested)


def external_files(app: str, svc: dict, env: str, tag: str, server: str) -> dict[str, dict]:
    """The overlay of an external component: its package (kustomize) or an Argo Application for its chart (helm)."""
    ext = svc["external"]
    image = {"name": svc["image"], "newTag": tag}
    kust: dict = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization"}
    if "kustomize" in ext:
        kust["resources"] = ["../../../" + str(ext["kustomize"]).format(env=env).strip("/")]
        if ext.get("namespace"):
            kust["namespace"] = ext["namespace"]
        kust["images"] = [image]
        return {"kustomization.yaml": kust}
    helm = ext["helm"]
    values = deep_merge(ext.get("values") or {}, (ext.get("envValues") or {}).get(env) or {})
    values = set_path(values, str(helm.get("imageTag") or "image.tag"), tag)
    application = {
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": f"{svc['name']}-{env}-chart", "namespace": "argocd",
                     "labels": {"app.kubernetes.io/part-of": app, "app.kubernetes.io/managed-by": "gitops-app"}},
        "spec": {
            "project": "default",
            "source": {"repoURL": helm["repoURL"], "path": helm["path"], "targetRevision": str(helm.get("revision") or "main"),
                       "helm": {"releaseName": str(helm.get("releaseName") or svc["name"]), "valuesObject": values}},
            "destination": {"server": server, "namespace": ext.get("namespace") or f"{app}-{env}"},
            "syncPolicy": {"automated": {"prune": True, "selfHeal": True},
                           "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"]},
        },
    }
    kust["resources"] = ["application.yaml"]
    kust["images"] = [image]        # not used by kustomize here; it is where pin.py, promote and status read the pin
    return {"application.yaml": application, "kustomization.yaml": kust}


def per_env(value, env: str, default):
    """A scalar, or a per-environment map ({dev: 1, prod: 3}); missing environments fall back to `default`."""
    return value.get(env, default) if isinstance(value, dict) else (default if value is None else value)


def addons_in(services: list[dict], env: str, cfg: dict) -> list[str]:
    names = {a for s in services if env in envs_of(s) for a in s.get("uses") or [] if not cfg["resources"][a]["envs"][env]["external"]}
    if env in cfg["observability"] and any(env in envs_of(s) for s in services):
        names.add("observability")
    return sorted(names)


def resource_instances(system: dict) -> list[tuple[str, str, str, bool]]:
    """(name, env, type, external) for each used resource instance, in resource order then ENVS order."""
    services, resources = system["services"], system["cfg"]["resources"]
    return [(r, e, rc["type"], rc["envs"][e]["external"]) for r, rc in resources.items() for e in ENVS
            if any(e in envs_of(s) and r in (s.get("uses") or []) for s in services)]


def allowed_registries(services: list[dict], cfg: dict, env: str) -> list[str]:
    """Image prefixes the guard rails accept: where our components' images live, the collector's (if the environment has one), and extras."""
    prefixes = {s["image"].rsplit("/", 1)[0] + "/" for s in services}
    if env in cfg["observability"]:
        prefixes.add(ADDONS["observability"]["image"].split("/", 1)[0] + "/")
    prefixes |= set(cfg["registries"])
    return sorted(prefixes)


def guardrail_policy(app: str, env: str, mode: str, registries: list[str]) -> dict:
    """Namespaced Kyverno (CEL) policy every rendered Deployment satisfies; a violation means someone bypassed render.py."""
    import json
    pod = "variables.pod"
    sc = "c.?securityContext"
    rules = [
        ("containers must run as a numeric non-root user (runAsNonRoot: true, runAsUser > 0)",
         f"{pod}.containers.all(c, {sc}.?runAsNonRoot.orValue({pod}.?securityContext.?runAsNonRoot.orValue(false)) && {sc}.?runAsUser.orValue(0) > 0)"),
        ("containers need readOnlyRootFilesystem: true", f"{pod}.containers.all(c, {sc}.?readOnlyRootFilesystem.orValue(false))"),
        ("containers need allowPrivilegeEscalation: false and must drop ALL capabilities",
         f'{pod}.containers.all(c, !{sc}.?allowPrivilegeEscalation.orValue(true) && {sc}.?capabilities.?drop.orValue([]).exists(d, d == "ALL"))'),
        ("privileged containers, host namespaces and hostPath volumes are not allowed",
         f"!{pod}.?hostNetwork.orValue(false) && !{pod}.?hostPID.orValue(false) && {pod}.containers.all(c, !{sc}.?privileged.orValue(false)) && "
         f"{pod}.?volumes.orValue([]).all(v, !has(v.hostPath))"),
        ("containers need CPU and memory requests and a memory limit",
         f"{pod}.containers.all(c, c.?resources.?requests.?cpu.hasValue() && c.?resources.?requests.?memory.hasValue() && c.?resources.?limits.?memory.hasValue())"),
        ("workloads need the label app.kubernetes.io/part-of", 'object.metadata.?labels["app.kubernetes.io/part-of"].hasValue()'),
        ("images must come from an allowed registry: " + ", ".join(registries),
         f"{pod}.containers.all(c, variables.registries.exists(r, c.image.startsWith(r)))"),
    ]
    if env != "dev":
        rules.append(("images must be pinned to a tag other than latest", f'{pod}.containers.all(c, c.image.contains(":") && !c.image.endsWith(":latest"))'))
    return {
        "apiVersion": POLICY_API, "kind": "NamespacedValidatingPolicy",
        "metadata": {"name": "platform-guardrails", "namespace": f"{app}-{env}",
                     "labels": {"app.kubernetes.io/part-of": app, "app.kubernetes.io/managed-by": "gitops-app"}},
        "spec": {
            "validationActions": [POLICY_MODES[mode]],
            "matchConstraints": {"resourceRules": [{"apiGroups": ["apps"], "apiVersions": ["v1"], "operations": ["CREATE", "UPDATE"], "resources": ["deployments"]}]},
            "variables": [{"name": "pod", "expression": "object.spec.template.spec"}, {"name": "registries", "expression": json.dumps(registries)}],
            "validations": [{"expression": e, "message": m} for m, e in rules],
        },
    }


def policy_envs(services: list[dict], cfg: dict) -> list[str]:
    return [env for env in ENVS if cfg["policy"][env] != "Off" and any(env in envs_of(s) for s in services)]


def envs_of(svc: dict) -> list[str]:
    return svc["environments"]


def at(svc: dict, env: str) -> dict:
    """The component as it runs in `env`: instance settings over the component's."""
    return {**svc, **svc["_eff"][env]}


def labels_for(app: str, svc: dict) -> dict:
    # `app` is also the (immutable) selector: it matches what v1 manifests used, so migrating a running Deployment is an in-place update.
    return {"app": svc["name"], "app.kubernetes.io/name": svc["name"], "app.kubernetes.io/part-of": app, "app.kubernetes.io/managed-by": "gitops-app"}


def replicas_for(svc: dict, env: str) -> int:
    return int(svc.get("replicas", 1))


def addon_env(app: str, svc: dict, resources: dict) -> list[dict]:
    """Connection settings of the resources a component uses, read from the resource's Secret `<system>-<name>-app` (never copied into git)."""
    out = []
    for u, names in variable_names(svc.get("uses") or [], resources):
        env = TYPES[resources[u]["type"]]["env"]
        out += [{"name": name, "valueFrom": {"secretKeyRef": {"name": f"{app}-{u}-app", "key": key}}} for name, key in zip(names, env.values())]
    return out


def obs_env(app: str, svc: dict, env: str) -> dict[str, str]:
    """Standard OTel variables pointing at the environment's collector (the component's `env` still wins)."""
    return {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4318", "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "OTEL_SERVICE_NAME": svc["name"], "OTEL_RESOURCE_ATTRIBUTES": f"service.namespace={app},deployment.environment={env}",
            "OTEL_SDK_DISABLED": "false"}


def deployment(app: str, svc: dict, env: str, obs: bool = False, resources: dict | None = None) -> dict:
    labels = labels_for(app, svc)
    selector = {"app": svc["name"]}
    env_vars = {"PORT": str(svc["port"]), **(obs_env(app, svc, env) if obs else {}), **{k: str(v) for k, v in (svc.get("env") or {}).items()}}
    container: dict = {
        "name": "app",
        "image": svc["image"],
        "ports": [{"name": "http", "containerPort": int(svc["port"])}],
        "env": [{"name": k, "value": v} for k, v in sorted(env_vars.items())] + addon_env(app, svc, resources or {}),
    }
    secret_names = [*(svc.get("secretRefs") or []), *[x["name"] for x in svc.get("secrets") or []]]
    if secret_names:
        container["envFrom"] = [{"secretRef": {"name": n}} for n in secret_names]
    if svc.get("resources"):
        container["resources"] = svc["resources"]
    http = lambda path: {"httpGet": {"path": path, "port": "http"}}  # noqa: E731
    container["startupProbe"] = {**http(svc["probes"]["liveness"]), "periodSeconds": 3, "failureThreshold": 40}  # up to 2 min (JVM)
    container["livenessProbe"] = {**http(svc["probes"]["liveness"]), "periodSeconds": 10}
    container["readinessProbe"] = {**http(svc["probes"]["readiness"]), "periodSeconds": 5}
    sc: dict = {"runAsNonRoot": True, "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
    if svc.get("user"):
        sc["runAsUser"] = int(svc["user"])
    container["securityContext"] = sc
    volumes = svc.get("volumes") or {}
    pod: dict = {"securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}}, "containers": [container]}
    if volumes:
        container["volumeMounts"] = [{"name": n, "mountPath": p} for n, p in sorted(volumes.items())]
        pod["volumes"] = [{"name": n, "emptyDir": {}} for n in sorted(volumes)]
    return {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": svc["name"], "labels": labels},
        "spec": {"replicas": replicas_for(svc, env), "selector": {"matchLabels": selector},
                 "template": {"metadata": {"labels": labels}, "spec": pod}},
    }


def service(app: str, svc: dict) -> dict:
    return {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": svc["name"], "labels": labels_for(app, svc)},
        "spec": {"type": "ClusterIP", "selector": {"app": svc["name"]},
                 "ports": [{"name": "http", "port": 80, "targetPort": "http"}]},
    }


def httproute(app: str, svc: dict, env: str, cfg: dict) -> dict | None:
    expose = svc.get("expose")
    template = cfg["hosts"].get(env)
    if not expose or not template:
        return None
    host = template.format(component=(expose.get("host") if isinstance(expose, dict) else None) or svc["name"], system=app, env=env)
    gw = cfg.get("gateway") or DEFAULT_GATEWAY
    return {
        "apiVersion": "gateway.networking.k8s.io/v1", "kind": "HTTPRoute",
        "metadata": {"name": svc["name"], "labels": labels_for(app, svc)},
        "spec": {"parentRefs": [{"name": gw["name"], "namespace": gw.get("namespace", "kube-system")}], "hostnames": [host],
                 "rules": [{"matches": [{"path": {"type": "PathPrefix", "value": (expose.get("path", "/") if isinstance(expose, dict) else "/")}}],
                            "backendRefs": [{"name": svc["name"], "port": 80}]}]},
    }


def secret_manifests(app: str, svc: dict, env: str, cfg: dict) -> dict[str, dict]:
    """ExternalSecrets (+ one Password generator per component) for `secrets:`; values never appear in git."""
    out: dict[str, dict] = {}
    labels = labels_for(app, svc)
    store = cfg.get("secretStore") or DEFAULT_STORE
    for sec in svc.get("secrets") or []:
        name = sec["name"]
        meta = {"name": name, "labels": labels}
        target = {"name": name, "creationPolicy": "Owner", "deletionPolicy": "Retain"}
        if sec.get("generate"):
            gen_ref = {"apiVersion": GEN_API, "kind": "Password", "name": f"{svc['name']}-password"}
            spec = {"refreshInterval": "0", "target": target, "dataFrom": [
                {"sourceRef": {"generatorRef": dict(gen_ref)}, "rewrite": [{"regexp": {"source": "^password$", "target": k}}]}
                for k in sec["generate"]]}
            out[f"externalsecret-{name}.yaml"] = {"apiVersion": ESO_API, "kind": "ExternalSecret", "metadata": meta, "spec": spec}
            out["password-generator.yaml"] = {
                "apiVersion": GEN_API, "kind": "Password", "metadata": {"name": f"{svc['name']}-password", "labels": labels},
                "spec": {"length": int(sec.get("length", 32)), "digits": 5, "symbols": 0, "noUpper": False, "allowRepeat": True}}
        else:
            remote = sec["remote"]
            key = str(remote.get("path") or "{system}-{env}-{secret}").format(system=app, env=env, secret=name, component=svc["name"])
            spec = {"refreshInterval": str(remote.get("refreshInterval", "1h")),
                    "secretStoreRef": {"name": store["name"], "kind": store.get("kind", "ClusterSecretStore")},
                    "target": target,
                    "data": [{"secretKey": k, "remoteRef": {"key": key, "property": k}} for k in remote["keys"]]}
            out[f"externalsecret-{name}.yaml"] = {"apiVersion": ESO_API, "kind": "ExternalSecret", "metadata": meta, "spec": spec}
    return out


def external_secrets(app: str, env: str, services: list[dict], cfg: dict) -> dict[str, dict[str, dict]]:
    """{component: {file name: ExternalSecret}} for the external resource instances of `env`.

    One ExternalSecret `<system>-<name>-app` per instance, in the overlay of the alphabetically first running component that uses it."""
    store = cfg.get("secretStore") or DEFAULT_STORE
    out: dict[str, dict[str, dict]] = {}
    for name, rc in cfg["resources"].items():
        conf = rc["envs"][env]
        if not conf["external"]:
            continue
        users = sorted(s["name"] for s in services if env in envs_of(s) and "external" not in s and name in (s.get("uses") or []))
        if not users:
            continue
        secret = f"{app}-{name}-app"
        doc = {"apiVersion": ESO_API, "kind": "ExternalSecret",
               "metadata": {"name": secret, "labels": {"app.kubernetes.io/name": name, "app.kubernetes.io/part-of": app,
                                                       "app.kubernetes.io/managed-by": "gitops-app"}},
               "spec": {"refreshInterval": conf["refreshInterval"],
                        "secretStoreRef": {"name": store["name"], "kind": store.get("kind", "ClusterSecretStore")},
                        "target": {"name": secret, "creationPolicy": "Orphan", "deletionPolicy": "Retain"},
                        "data": [{"secretKey": k, "remoteRef": {"key": conf["store_key"], "property": k}}
                                 for k in TYPES[rc["type"]]["keys"]]}}
        out.setdefault(users[0], {})[f"externalsecret-{secret}.yaml"] = doc
    return out


def database_cluster(app: str, name: str, env: str, conf: dict) -> dict:
    db = app.replace("-", "_")
    return {
        "apiVersion": "postgresql.cnpg.io/v1", "kind": "Cluster",
        "metadata": {"name": f"{app}-{name}", "labels": {"app.kubernetes.io/name": name, "app.kubernetes.io/part-of": app, "app.kubernetes.io/managed-by": "gitops-app"}},
        "spec": {
            "instances": conf["replicas"],
            "imageName": POSTGRES_IMAGES[conf["version"]],
            "storage": {"size": conf["storage"]},
            "enableSuperuserAccess": False,
            "bootstrap": {"initdb": {"database": db, "owner": db}},
            "resources": conf["resources"] or DB_DEFAULT_RESOURCES,
        },
    }


def bucket_files(app: str, name: str, env: str, conf: dict) -> dict[str, dict | str]:
    """The in-cluster bucket instance (ADR-059): its own SeaweedFS, a Bucket, an identity limited to it and generated keys.

    Argo CD never deletes any of it (`Delete=false`, `reclaimPolicy: Retain`). No credential value is rendered: the keys come from
    External Secrets `Password` generators and are written once to `<system>-<name>-app`."""
    n = f"{app}-{name}"
    labels = {"app.kubernetes.io/name": name, "app.kubernetes.io/part-of": app, "app.kubernetes.io/managed-by": "gitops-app"}
    keep = {"argocd.argoproj.io/sync-options": "Delete=false"}

    def meta(obj: str, wave: str | None = None) -> dict:
        ann = {**keep, **({"argocd.argoproj.io/sync-wave": wave} if wave else {})}
        return {"name": obj, "labels": dict(labels), "annotations": ann}

    seaweed_api = "seaweed.seaweedfs.com/v1"
    gen_api = "generators.external-secrets.io/v1alpha1"
    volume = lambda: {"enabled": True, "resources": {"requests": {"storage": "1Gi"}}}  # noqa: E731  (fresh dicts: no YAML anchors)

    def generator(suffix: str, length: int, digits: int) -> dict:
        return {"apiVersion": gen_api, "kind": "Password", "metadata": meta(f"{n}-{suffix}", "-1"),
                "spec": {"length": length, "digits": digits, "symbols": 0, "noUpper": False, "allowRepeat": True}}

    def source(suffix: str, key: str) -> dict:
        return {"sourceRef": {"generatorRef": {"apiVersion": gen_api, "kind": "Password", "name": f"{n}-{suffix}"}},
                "rewrite": [{"regexp": {"source": "^password$", "target": key}}]}

    files: dict[str, dict | str] = {
        "seaweed.yaml": {
            "apiVersion": seaweed_api, "kind": "Seaweed", "metadata": meta(n),
            "spec": {"image": SEAWEEDFS_IMAGE, "volumeServerDiskCount": 1,
                     "master": {"replicas": 1, "volumeSizeLimitMB": 1024, "persistence": volume()},
                     "volume": {"replicas": 1, "requests": {"storage": conf["storage"]}},
                     "filer": {"replicas": 1, "persistence": volume(), "s3": {"enabled": True},
                               "config": '[leveldb2]\nenabled = true\ndir = "/data/filerldb2"\n'}}},
        "bucket.yaml": {
            "apiVersion": seaweed_api, "kind": "Bucket", "metadata": meta(n),
            "spec": {"name": n, "clusterRef": {"name": n}, "reclaimPolicy": "Retain",
                     "versioning": "Enabled" if conf["versioning"] else "Suspended", "owner": n,
                     "access": [{"user": n, "actions": ["Read", "Write", "List", "Tagging"]}]}},
        "identity.yaml": {"apiVersion": seaweed_api, "kind": "S3Identity", "metadata": meta(n), "spec": {"seaweedRef": {"name": n}}},
        "credentials.yaml": {
            "apiVersion": seaweed_api, "kind": "S3Credentials", "metadata": meta(n, "1"),
            "spec": {"seaweedRef": {"name": n}, "identityRef": {"name": n},
                     "secretRef": {"name": f"{n}-app", "accessKeyField": "accessKeyId", "secretKeyField": "secretAccessKey"},  # pragma: allowlist secret
                     "reclaimPolicy": "Retain"}},
        "access-key-generator.yaml": generator("access-key", 20, 5),
        "secret-key-generator.yaml": generator("secret-key", 40, 10),
        "externalsecret.yaml": {
            "apiVersion": ESO_API, "kind": "ExternalSecret", "metadata": meta(f"{n}-app", "-1"),
            "spec": {"refreshInterval": "0",
                     "target": {"name": f"{n}-app", "creationPolicy": "Owner", "deletionPolicy": "Retain",
                                "template": {"engineVersion": "v2", "data": {
                                    "endpoint": f"http://{n}-filer.{app}-{env}.svc:8333", "bucket": n, "region": "us-east-1",
                                    "forcePathStyle": "true", "accessKeyId": "{{ .accessKeyId }}",
                                    "secretAccessKey": "{{ .secretAccessKey }}"}}},  # pragma: allowlist secret
                     "dataFrom": [source("access-key", "accessKeyId"), source("secret-key", "secretAccessKey")]}},  # pragma: allowlist secret
    }
    files["kustomization.yaml"] = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                                   "resources": ["access-key-generator.yaml", "bucket.yaml", "credentials.yaml", "externalsecret.yaml",
                                                 "identity.yaml", "seaweed.yaml", "secret-key-generator.yaml"]}
    return files


def collector_config(app: str, env: str, conf: dict, services: list[dict]) -> dict:
    scrape = [{"job_name": s["name"], "scrape_interval": "30s", "metrics_path": s["metrics"],
               "static_configs": [{"targets": [f"{s['name']}.{app}-{env}.svc:80"]}]}
              for s in services if env in envs_of(s) and s.get("metrics")]
    receivers: dict = {"otlp": {"protocols": {"grpc": {"endpoint": "0.0.0.0:4317"}, "http": {"endpoint": "0.0.0.0:4318"}}}}
    if scrape:
        receivers["prometheus"] = {"config": {"scrape_configs": scrape}}
    endpoint = LGTM_ENDPOINT if conf.get("ui") == "lgtm" else conf.get("exportTo")
    exporters: dict = {"debug": {"verbosity": "basic"}}
    names = ["debug"]
    if endpoint:
        backend: dict = {"endpoint": endpoint}
        if conf.get("headersSecret"):
            backend["headers"] = {"Authorization": "${env:AUTHORIZATION}"}
        exporters["otlphttp/backend"] = backend
        names.append("otlphttp/backend")
    processors = {"memory_limiter": {"check_interval": "1s", "limit_percentage": 80, "spike_limit_percentage": 25}, "batch": {},
                  "resource": {"attributes": [{"key": "deployment.environment", "value": env, "action": "upsert"},
                                              {"key": "service.namespace", "value": app, "action": "upsert"}]}}
    chain = lambda: {"processors": ["memory_limiter", "resource", "batch"], "exporters": list(names)}  # noqa: E731  (fresh lists: no YAML anchors)
    return {"extensions": {"health_check": {"endpoint": "0.0.0.0:13133"}}, "receivers": receivers, "processors": processors, "exporters": exporters,
            "service": {"extensions": ["health_check"], "pipelines": {
                "traces": {"receivers": ["otlp"], **chain()},
                "metrics": {"receivers": ["otlp", *(["prometheus"] if scrape else [])], **chain()},
                "logs": {"receivers": ["otlp"], **chain()}}}}


def observability_files(app: str, env: str, conf: dict, services: list[dict]) -> dict[str, dict | str]:
    import hashlib
    labels = {"app.kubernetes.io/name": "otel-collector", "app.kubernetes.io/part-of": app, "app.kubernetes.io/managed-by": "gitops-app"}
    config = dump(collector_config(app, env, conf, services))
    container: dict = {
        "name": "collector", "image": ADDONS["observability"]["image"], "args": ["--config=/conf/config.yaml"],
        "ports": [{"name": "otlp-grpc", "containerPort": 4317}, {"name": "otlp-http", "containerPort": 4318}, {"name": "health", "containerPort": 13133}],
        "readinessProbe": {"httpGet": {"path": "/", "port": "health"}, "periodSeconds": 5},
        "livenessProbe": {"httpGet": {"path": "/", "port": "health"}, "periodSeconds": 10},
        "resources": {"requests": {"cpu": "50m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "256Mi"}},
        "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
        "volumeMounts": [{"name": "conf", "mountPath": "/conf"}],
    }
    if conf.get("headersSecret"):
        container["envFrom"] = [{"secretRef": {"name": conf["headersSecret"]}}]
    deploy = {
        "apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "otel-collector", "labels": labels},
        "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "otel-collector"}},
                 "template": {"metadata": {"labels": {**labels, "app": "otel-collector"},
                                           "annotations": {"checksum/config": hashlib.sha256(config.encode()).hexdigest()[:16]}},
                              "spec": {"securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                                       "containers": [container], "volumes": [{"name": "conf", "configMap": {"name": "otel-collector"}}]}}},
    }
    return {
        "configmap.yaml": {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "otel-collector", "labels": labels}, "data": {"config.yaml": config}},
        "collector.yaml": deploy,
        "service.yaml": {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "otel-collector", "labels": labels},
                         "spec": {"type": "ClusterIP", "selector": {"app": "otel-collector"},
                                  "ports": [{"name": "otlp-grpc", "port": 4317, "targetPort": "otlp-grpc"}, {"name": "otlp-http", "port": 4318, "targetPort": "otlp-http"}]}},
        "kustomization.yaml": {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": ["configmap.yaml", "collector.yaml", "service.yaml"]},
    }


def addon_files(app: str, name: str, env: str, cfg: dict, services: list[dict]) -> dict[str, dict | str]:
    if name == "observability":
        return observability_files(app, env, cfg["observability"][env], services)
    res = cfg["resources"][name]
    if res["type"] == "bucket":
        return bucket_files(app, name, env, res["envs"][env])
    files = {"cluster.yaml": database_cluster(app, name, env, res["envs"][env])}   # database; cache and broker are not built yet
    files["kustomization.yaml"] = {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": ["cluster.yaml"]}
    return files


def render_app(app_dir: Path, ans: dict) -> dict[Path, str]:
    app = app_dir.name
    system = load_system(app_dir)
    services, cfg = system["services"], system["cfg"]
    org = ans.get("github_org", "ika100")
    server = ans.get("cluster_server", "https://kubernetes.default.svc")
    gitops_repo = f"https://github.com/{org}/{ans.get('project_name', app + '-gitops')}"
    out: dict[Path, str] = {}

    docs = []
    for env in ENVS:
        docs.append({
            "apiVersion": "argoproj.io/v1alpha1", "kind": "ApplicationSet",
            "metadata": {"name": f"{app}-{env}", "namespace": "argocd"},
            "spec": {
                "generators": [{"list": {"elements": [{"name": s["name"]} for s in services if env in envs_of(s)]}}],
                "template": {
                    "metadata": {"name": "{{name}}-" + env},
                    "spec": {
                        "project": "default",
                        "source": {"repoURL": gitops_repo, "targetRevision": "main", "path": f"applications/{app}/overlays/{env}/" + "{{name}}"},
                        "destination": {"server": server, "namespace": f"{app}-{env}"},
                        "syncPolicy": {"automated": {"prune": True, "selfHeal": True}, "syncOptions": ["CreateNamespace=true"]},
                    },
                },
            },
        })
    for env in ENVS:
        names = addons_in(services, env, cfg)
        if not names:
            continue
        # one ApplicationSet per prune policy: stateful resources (databases) are never pruned, config-only ones are
        for prune, suffix in ((False, "addons"), (True, "addons-config")):
            group = [n for n in names if (n == "observability") is prune]
            if not group:
                continue
            docs.append({
                "apiVersion": "argoproj.io/v1alpha1", "kind": "ApplicationSet",
                "metadata": {"name": f"{app}-{suffix}-{env}", "namespace": "argocd"},
                "spec": {
                    "generators": [{"list": {"elements": [{"name": n} for n in group]}}],
                    "template": {
                        "metadata": {"name": "addon-{{name}}-" + env},
                        "spec": {
                            "project": "default",
                            "source": {"repoURL": gitops_repo, "targetRevision": "main", "path": f"applications/{app}/addons/{env}/" + "{{name}}"},
                            "destination": {"server": server, "namespace": f"{app}-{env}"},
                            "syncPolicy": {"automated": {"prune": prune, "selfHeal": True}, "syncOptions": ["CreateNamespace=true"]},
                        },
                    },
                },
            })
        for n in names:
            for fname, doc in addon_files(app, n, env, cfg, services).items():
                out[app_dir / "addons" / env / n / fname] = dump(doc) if not isinstance(doc, str) else doc
    for env in policy_envs(services, cfg):
        docs.append({
            "apiVersion": "argoproj.io/v1alpha1", "kind": "ApplicationSet",
            "metadata": {"name": f"{app}-policies-{env}", "namespace": "argocd"},
            "spec": {
                "generators": [{"list": {"elements": [{"name": "guardrails"}]}}],
                "template": {
                    "metadata": {"name": "policy-{{name}}-" + env},
                    "spec": {
                        "project": "default",
                        "source": {"repoURL": gitops_repo, "targetRevision": "main", "path": f"applications/{app}/policies/{env}"},
                        "destination": {"server": server, "namespace": f"{app}-{env}"},
                        "syncPolicy": {"automated": {"prune": True, "selfHeal": True}, "syncOptions": ["CreateNamespace=true"]},
                    },
                },
            },
        })
        base = app_dir / "policies" / env
        out[base / "policy.yaml"] = dump(guardrail_policy(app, env, cfg["policy"][env], allowed_registries(services, cfg, env)))
        out[base / "kustomization.yaml"] = dump({"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": ["policy.yaml"]})
    out[app_dir / "applicationset.yaml"] = "---\n".join(dump(d) for d in docs)

    out[ROOT / "bootstrap" / f"{app}-root.yaml"] = dump({
        "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
        "metadata": {"name": f"{app}-root", "namespace": "argocd"},
        "spec": {
            "project": "default",
            "source": {"repoURL": gitops_repo, "targetRevision": "main", "path": f"applications/{app}", "directory": {"include": "applicationset.yaml"}},
            "destination": {"server": server, "namespace": "argocd"},
            "syncPolicy": {"automated": {"prune": True, "selfHeal": True}},
        },
    })

    for env in ENVS:
        ext_secrets = external_secrets(app, env, services, cfg)
        for comp in services:
            if env not in envs_of(comp):
                continue
            s = at(comp, env)
            base = app_dir / "overlays" / env / s["name"]
            if "external" in s:
                tag = existing_tag(base / "kustomization.yaml") or "latest"
                for fname, doc in external_files(app, s, env, tag, server).items():
                    out[base / fname] = dump(doc)
                continue
            files = {"deployment.yaml": deployment(app, s, env, env in cfg["observability"], cfg["resources"]), "service.yaml": service(app, s)}
            route = httproute(app, s, env, cfg)
            if route:
                files["httproute.yaml"] = route
            files.update(secret_manifests(app, s, env, cfg))
            files.update(ext_secrets.get(s["name"], {}))
            for fname, doc in files.items():
                out[base / fname] = dump(doc)
            tag = existing_tag(base / "kustomization.yaml") or "latest"
            out[base / "kustomization.yaml"] = dump({
                "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                "resources": sorted(files), "images": [{"name": s["image"], "newTag": tag}],
            })
    if system["autonomy"] is not None:
        out[app_dir / "autonomy.json"] = system["autonomy"]
    return out


def operator_files(apps: list[Path], ans: dict) -> dict[Path, str]:
    """operators/ (AC-115.18): cluster-level, outside every system's tree; only when an in-cluster database runs in an environment
    whose operators are not owned by the cluster's owner."""
    needed: set[str] = set()
    for app_dir in apps:
        system = load_system(app_dir)
        owned = system["cfg"]["operators"]
        for _, env, typ, ext in resource_instances(system):
            if not ext and env not in owned and typ in OPERATOR_OF_TYPE:
                needed.add(OPERATOR_OF_TYPE[typ])
    if not needed:
        return {}
    server = ans.get("cluster_server", "https://kubernetes.default.svc")
    org = ans.get("github_org", "ika100")
    repo = f"https://github.com/{org}/{ans.get('project_name', apps[0].name + '-gitops')}"
    base = ROOT / "operators"
    files = {
        base / "root.yaml": dump({
            "apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": "platform-operators", "namespace": "argocd"},
            "spec": {"project": "default", "source": {"repoURL": repo, "targetRevision": "main", "path": "operators/apps"},
                     "destination": {"server": server, "namespace": "argocd"},
                     "syncPolicy": {"automated": {"prune": True, "selfHeal": True}}}}),
    }
    for name in OPERATORS:
        if name not in needed:
            continue
        op = OPERATORS[name]
        files[base / "apps" / f"{name}.yaml"] = dump({
            "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
            "metadata": {"name": f"operator-{name}", "namespace": "argocd",
                         "labels": {"app.kubernetes.io/managed-by": "gitops-app", "app.kubernetes.io/component": "operator"}},
            "spec": {"project": "default",
                     "source": {"repoURL": op["repo_url"], "chart": op["chart"], "targetRevision": op["chart_version"],
                                "helm": {"releaseName": op["release"]}},
                     "destination": {"server": server, "namespace": op["namespace"]},
                     "syncPolicy": {"automated": {"prune": True, "selfHeal": True},
                                    "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"]}}})
    return files


def stale_paths(app_dir: Path, wanted: set[Path]) -> list[Path]:
    """Overlay component dirs for components/envs no longer declared, and generated files no longer produced."""
    stale: list[Path] = []
    if (app_dir / "autonomy.json").is_file() and app_dir / "autonomy.json" not in wanted:
        stale.append(app_dir / "autonomy.json")
    for env in ENVS:
        base = app_dir / "overlays" / env
        if not base.is_dir():
            continue
        for d in base.iterdir():
            if not d.is_dir():
                continue
            if not any(p.parent == d for p in wanted):
                stale.append(d)
                continue
            stale += [f for f in d.iterdir() if (f.name in MANAGED_FILES or f.name.startswith(MANAGED_PREFIXES)) and f not in wanted]
    for kind in ("addons", "policies"):
        top = app_dir / kind
        if top.is_dir() and not any(top in p.parents for p in wanted):
            stale.append(top)          # nothing of this kind is wanted any more: remove the whole directory
            continue
        for env in ENVS:
            base = app_dir / kind / env
            if not base.is_dir():
                continue
            if kind == "policies":
                if not any(p.parent == base for p in wanted):
                    stale.append(base)
                continue
            for d in base.iterdir():
                if d.is_dir() and not any(p.parent == d for p in wanted):
                    stale.append(d)
    return stale


def unmigrated_dirs() -> list[Path]:
    top = ROOT / "applications"
    if not top.is_dir():
        return []
    return sorted(p for p in top.iterdir() if p.is_dir() and ((p / "app.yaml").is_file() or (p / "services.yaml").is_file()))


def main() -> int:
    check = "--check" in sys.argv[1:]
    old = unmigrated_dirs()
    if old:
        for d in old:
            print(f"ERROR: applications/{d.name}: {NOT_MIGRATED}", file=sys.stderr)
        return 1
    ans = answers()
    apps = sorted(p.parent for p in (ROOT / "applications").glob("*/system.yaml"))
    if not apps:
        print("ERROR: no applications/*/system.yaml found", file=sys.stderr)
        return 1
    drift: list[str] = []
    try:
        plans = [(app_dir, render_app(app_dir, ans)) for app_dir in apps]     # every system is validated before anything is written
        operators = operator_files(apps, ans)
    except RenderError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    for app_dir, rendered in plans:
        for path, content in rendered.items():
            if not path.is_file() or path.read_text() != content:
                drift.append(str(path.relative_to(ROOT)))
                if not check:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
        for st in stale_paths(app_dir, set(rendered)):
            drift.append(f"{st.relative_to(ROOT)} (stale)")
            if not check:
                shutil.rmtree(st) if st.is_dir() else st.unlink()
    for path, content in operators.items():
        if not path.is_file() or path.read_text() != content:
            drift.append(str(path.relative_to(ROOT)))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
    op_dir = ROOT / "operators"
    if op_dir.is_dir():
        for f in sorted(p for p in op_dir.rglob("*") if p.is_file() and p not in operators):
            drift.append(f"{f.relative_to(ROOT)} (stale)")
            if not check:
                f.unlink()
        if not check:
            for d in sorted((p for p in op_dir.rglob("*") if p.is_dir()), reverse=True) + [op_dir]:
                if not any(d.iterdir()):
                    d.rmdir()
    if check and drift:
        print("ERROR: rendered files are out of date — run `devbox run render`:", file=sys.stderr)
        for d in drift:
            print(f"  {d}", file=sys.stderr)
        return 1
    print("OK: up to date" if check else f"rendered ({len(drift)} file(s) changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
