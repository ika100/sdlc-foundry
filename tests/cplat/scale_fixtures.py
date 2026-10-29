"""Shared helpers of the spec 120 acceptance tests (not a test module, never collected).

Contract: docs/specs/120-.../design.md. Builds systems with `scale` on top of resources_fixtures, broker_fixtures and cache_fixtures
and spells out the designed documents (HPA, ScaledObject, TriggerAuthentication, the environment ApplicationSet's ignore rules, the
keda and metrics-server Applications) with their key order. Nothing here touches the network or a cluster."""
from broker_fixtures import RETRY, broker, events, shape, tree_digest  # noqa: F401  (re-exported for the tests)
from cache_fixtures import cache
from resources_fixtures import APP, ENVS, comp, db, system  # noqa: F401  (re-exported for the tests)

P = "applications/shop/system.yaml: "
ON_FORMS = "{cpu: <percent>}, {memory: <percent>}, {consumes: <api>, lag: <n>} or {cache: <resource>, list: <key>, length: <n>}"
SCALE_EXAMPLE = "{min: 1, max: 5, on: {cpu: 70}}"
RES = {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}}
WAVE = "argocd.argoproj.io/sync-wave"
OPTS = "argocd.argoproj.io/sync-options"
SKIP_DRY = "SkipDryRunOnMissingResource=true"
SERVICE_KEYS = ("type, lang, repo, image, port, probes, user, volumes, env, secretRefs, secrets, replicas, resources, expose, metrics, provides, "
                "consumes, uses, instances, scale")
INSTANCE_KEYS = "replicas, resources, env, promote, secrets, autonomy, scale"
ENV_KEYS = "host, url, policy, promote, observability, operators, backup, autonomy"
KEDA = {"repo_url": "https://kedacore.github.io/charts", "chart": "keda", "chart_version": "2.19.0", "operator_version": "2.19.0", "namespace": "keda",
        "release": "keda", "crd": "scaledobjects.keda.sh", "selector": "app.kubernetes.io/name=keda-operator"}
METRICS = {"repo_url": "https://kubernetes-sigs.github.io/metrics-server", "chart": "metrics-server", "chart_version": "3.14.0",
           "operator_version": "0.9.0", "namespace": "kube-system", "release": "metrics-server", "crd": None,
           "selector": "app.kubernetes.io/name=metrics-server"}
AUTOSCALER_FILES = ("hpa.yaml", "scaledobject.yaml", "triggerauthentication.yaml")


# ---------------- systems ----------------

def sdoc(scale=None, replicas=None, **inst) -> dict:
    """The api component with resources; `scale`/`replicas` on the component, anything else per instance (dev=..., staging=...)."""
    extra = {}
    if scale is not None:
        extra["scale"] = scale
    if replicas is not None:
        extra["replicas"] = replicas
    c = comp("api", resources=RES, **extra)
    for env, conf in inst.items():
        c["instances"][env] = conf
    return system(None, {"api": c})


def cpu(max=5, **kw) -> dict:
    return {"max": max, "on": {"cpu": 70}, **kw}


def queue_system(scale=None, instances=None, resources=None, comps=None, apis=None, **top) -> dict:
    """bus (default broker) carries the events API `jobs`: api provides it, worker consumes it and scales as `scale` says."""
    worker = comp("worker", consumes=["jobs"], resources=RES)
    if scale is not None:
        worker["scale"] = scale
    for env, conf in (instances or {}).items():
        worker["instances"][env] = conf
    return system({"bus": broker()} if resources is None else resources,
                  comps if comps is not None else {"api": comp("api", provides=["jobs"]), "worker": worker},
                  apis=events("jobs") if apis is None else apis, **top)


def lag(n=10, **kw) -> dict:
    return {"max": 5, "on": {"consumes": "jobs", "lag": n}, **kw}


def cache_system(scale=None, instances=None, resources=None, **top) -> dict:
    """sessions (a cache) is used by worker, which scales as `scale` says."""
    worker = comp("worker", ["sessions"], resources=RES)
    if scale is not None:
        worker["scale"] = scale
    for env, conf in (instances or {}).items():
        worker["instances"][env] = conf
    return system({"sessions": cache()} if resources is None else resources, {"worker": worker}, **top)


def length(n=10, key="jobs", **kw) -> dict:
    return {"max": 5, "on": {"cache": "sessions", "list": key, "length": n}, **kw}


# ---------------- paths ----------------

def odir(env: str, name: str = "api") -> str:
    return f"{APP}/overlays/{env}/{name}"


def files_of(g: dict, env: str, name: str = "api") -> list[str]:
    return sorted(k.rsplit("/", 1)[-1] for k in g if k.startswith(odir(env, name) + "/"))


# ---------------- designed documents ----------------

def labels(name: str) -> dict:
    return {"app": name, "app.kubernetes.io/name": name, "app.kubernetes.io/part-of": "shop", "app.kubernetes.io/managed-by": "gitops-app"}


def target(name: str) -> dict:
    return {"apiVersion": "apps/v1", "kind": "Deployment", "name": name}


def expected_hpa(name="api", mn=1, mx=5, resource="cpu", percent=70) -> dict:
    return {"apiVersion": "autoscaling/v2", "kind": "HorizontalPodAutoscaler", "metadata": {"name": name, "labels": labels(name)},
            "spec": {"scaleTargetRef": target(name), "minReplicas": mn, "maxReplicas": mx,
                     "metrics": [{"type": "Resource", "resource": {"name": resource, "target": {"type": "Utilization", "averageUtilization": percent}}}]}}


def nats_trigger(component="worker", api="jobs", bus="bus", env="dev", n=10) -> dict:
    return {"type": "nats-jetstream",
            "metadata": {"natsServerMonitoringEndpoint": f"shop-{bus}.shop-{env}.svc:8222", "account": "$G", "stream": f"shop-{api}", "consumer": component,
                         "lagThreshold": str(n), "activationLagThreshold": "0", "useHttps": "false"}}


def redis_trigger(component="worker", key="jobs", n=10) -> dict:
    return {"type": "redis", "metadata": {"listName": key, "listLength": str(n), "activationListLength": "0", "databaseIndex": "0"},
            "authenticationRef": {"name": component, "kind": "TriggerAuthentication"}}


def expected_scaledobject(trigger: dict, name="worker", mn=1, mx=5) -> dict:
    return {"apiVersion": "keda.sh/v1alpha1", "kind": "ScaledObject",
            "metadata": {"name": name, "labels": labels(name), "annotations": {WAVE: "1", OPTS: SKIP_DRY}},
            "spec": {"scaleTargetRef": target(name), "pollingInterval": 15, "cooldownPeriod": 315, "minReplicaCount": mn, "maxReplicaCount": mx,
                     "advanced": {"horizontalPodAutoscalerConfig": {"behavior": {"scaleDown": {
                         "stabilizationWindowSeconds": 345, "policies": [{"type": "Percent", "value": 100, "periodSeconds": 15}]}}}},
                     "triggers": [trigger]}}


def expected_trigger_auth(name="worker", cache_name="sessions") -> dict:
    secret = f"shop-{cache_name}-app"
    return {"apiVersion": "keda.sh/v1alpha1", "kind": "TriggerAuthentication",
            "metadata": {"name": name, "labels": labels(name), "annotations": {OPTS: SKIP_DRY}},
            "spec": {"secretTargetRef": [{"parameter": k, "name": secret, "key": k} for k in ("host", "port", "password")]}}


def ignore_entry(name: str) -> dict:
    return {"group": "apps", "kind": "Deployment", "name": name, "jsonPointers": ["/spec/replicas"]}


def expected_operator(op: dict, server="https://kubernetes.default.svc") -> dict:
    return {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
            "metadata": {"name": f"operator-{op['chart']}", "namespace": "argocd",
                         "labels": {"app.kubernetes.io/managed-by": "gitops-app", "app.kubernetes.io/component": "operator"},
                         "annotations": {"argocd.argoproj.io/compare-options": "ServerSideDiff=true"}},
            "spec": {"project": "default",
                     "source": {"repoURL": op["repo_url"], "chart": op["chart"], "targetRevision": op["chart_version"], "helm": {"releaseName": op["release"]}},
                     "destination": {"server": server, "namespace": op["namespace"]},
                     "syncPolicy": {"automated": {"prune": True, "selfHeal": True}, "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"]}}}
