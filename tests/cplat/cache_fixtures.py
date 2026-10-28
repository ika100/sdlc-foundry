"""Shared helpers of the spec 118 acceptance tests (not a test module, never collected).

Contract: docs/specs/118-.../design.md. Builds systems with `cache` resources on top of resources_fixtures and spells out the
designed documents of an in-cluster cache instance (key order as designed). Nothing here touches the network or a cluster."""
import hashlib

from resources_fixtures import APP, LABELS, comp, system

P = "applications/shop/system.yaml: "
CKEYS = ["url", "host", "port", "password"]
CVARS = {"REDIS_URL": "url", "REDIS_HOST": "host", "REDIS_PORT": "port", "REDIS_PASSWORD": "password"}
POLICIES = ["noeviction", "allkeys-lru", "allkeys-lfu", "allkeys-random", "volatile-lru", "volatile-lfu", "volatile-random", "volatile-ttl"]
ALLOWED_TOP = "type, external, remote, version, memory, maxmemoryPolicy, persistence, storage, instances"
ALLOWED_INST = "external, remote, memory, maxmemoryPolicy, persistence, storage, version"  # spec 121: version is an instance key
SIZING = ["memory", "maxmemoryPolicy", "persistence", "storage"]
WAVE = "argocd.argoproj.io/sync-wave"
FILES = ["externalsecret.yaml", "kustomization.yaml", "password-generator.yaml", "service.yaml", "statefulset.yaml"]
IMAGES = {8: "valkey/valkey:8.1.11@sha256:8f836008e0986c36adf50da714c7060cf689dbb335f61fe077939d90fa650809",
          9: "valkey/valkey:9.1.3@sha256:3add1a336a920ea54770a001ab6feb3da5fceea96a40373a3a2cd469b815f0b7"}  # spec 121: the designed digests
CONTAINER_KEYS = ["name", "image", "command", "args", "env", "ports", "resources", "readinessProbe", "livenessProbe", "securityContext", "volumeMounts"]


def cache(**kw) -> dict:
    return {"type": "cache", **kw}


def csys(resources=None, comps=None, **top) -> dict:
    if resources is None:
        resources = {"sessions": cache()}
    if comps is None:
        comps = {"api": comp("api", ["sessions"])}
    return system(resources, comps, **top)


def cdir(env: str = "dev", name: str = "sessions") -> str:
    return f"{APP}/addons/{env}/{name}"


def cdoc(g, env, file, name="sessions"):
    import yaml
    return yaml.safe_load(g[f"{cdir(env, name)}/{file}"])


def labels(name="sessions") -> dict:
    return {"app.kubernetes.io/name": name, **LABELS}


def selector(name="sessions") -> dict:
    return {"app.kubernetes.io/name": name, "app.kubernetes.io/part-of": "shop"}


def contract(resource: str, prefix: str = "") -> dict:
    return {prefix + v: (f"shop-{resource}-app", k) for v, k in CVARS.items()}


def quantity_maxmemory(nbytes: int) -> int:
    return nbytes * 4 // 5


def expected_generator(env="dev", name="sessions") -> dict:
    return {"apiVersion": "generators.external-secrets.io/v1alpha1", "kind": "Password",
            "metadata": {"name": f"shop-{name}-password", "labels": labels(name), "annotations": {WAVE: "-1"}},
            "spec": {"length": 32, "digits": 5, "symbols": 0, "noUpper": False, "allowRepeat": True}}


def expected_externalsecret(env="dev", name="sessions") -> dict:
    n, ns = f"shop-{name}", f"shop-{env}"
    return {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret",
            "metadata": {"name": f"{n}-app", "labels": labels(name), "annotations": {WAVE: "-1"}},
            "spec": {"refreshPolicy": "CreatedOnce",
                     "target": {"name": f"{n}-app", "creationPolicy": "Owner", "deletionPolicy": "Retain",
                               "template": {"engineVersion": "v2", "metadata": {"labels": labels(name)},
                                            "data": {"url": "redis://:{{ .password }}@" + f"{n}.{ns}.svc:6379/0", "host": f"{n}.{ns}.svc",
                                                     "port": "6379", "password": "{{ .password }}"}}},
                     "dataFrom": [{"sourceRef": {"generatorRef": {"apiVersion": "generators.external-secrets.io/v1alpha1", "kind": "Password",
                                                                  "name": f"{n}-password"}}}]}}


def expected_service(name="sessions") -> dict:
    return {"apiVersion": "v1", "kind": "Service", "metadata": {"name": f"shop-{name}", "labels": labels(name)},
            "spec": {"type": "ClusterIP", "selector": selector(name), "ports": [{"name": "redis", "port": 6379, "targetPort": "redis"}]}}


def expected_statefulset(name="sessions", version=9, memory="256Mi", maxmemory=214748364, policy="allkeys-lru", persistence=False, storage="1Gi") -> dict:
    n = f"shop-{name}"
    args = ["--port", "6379", "--requirepass", "$(VALKEY_PASSWORD)", "--maxmemory", str(maxmemory), "--maxmemory-policy", policy,
            "--save", "", "--dir", "/data", "--appendonly", "yes" if persistence else "no"]
    if persistence:
        args += ["--appendfsync", "everysec"]
    container = {
        "name": "valkey", "image": IMAGES[version], "command": ["valkey-server"], "args": args,
        "env": [{"name": "VALKEY_PASSWORD", "valueFrom": {"secretKeyRef": {"name": f"{n}-app", "key": "password"}}}],
        "ports": [{"name": "redis", "containerPort": 6379}],
        "resources": {"requests": {"cpu": "50m", "memory": str(memory)}, "limits": {"memory": str(memory)}},
        "readinessProbe": {"exec": {"command": ["sh", "-c", 'valkey-cli --no-auth-warning -a "$VALKEY_PASSWORD" ping | grep -q PONG']}, "periodSeconds": 5},
        "livenessProbe": {"tcpSocket": {"port": "redis"}, "initialDelaySeconds": 10, "periodSeconds": 10},
        "securityContext": {"runAsNonRoot": True, "runAsUser": 999, "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]}}}
    if persistence:
        container["volumeMounts"] = [{"name": "data", "mountPath": "/data"}]
    spec = {"replicas": 1, "serviceName": n, "selector": {"matchLabels": selector(name)},
            "template": {"metadata": {"labels": labels(name)},
                         "spec": {"automountServiceAccountToken": False,
                                  "securityContext": {"runAsNonRoot": True, "runAsUser": 999, "runAsGroup": 999, "fsGroup": 999,
                                                      "seccompProfile": {"type": "RuntimeDefault"}},
                                  "containers": [container]}}}
    if persistence:
        spec["volumeClaimTemplates"] = [{"metadata": {"name": "data", "labels": labels(name)},
                                         "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": storage}}}}]
    return {"apiVersion": "apps/v1", "kind": "StatefulSet",
            "metadata": {"name": n, "labels": labels(name)},  # spec 118 review: no Force/Replace sync option (design decision 8)
            "spec": spec}


def expected_kustomization() -> dict:
    return {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
            "resources": ["externalsecret.yaml", "password-generator.yaml", "service.yaml", "statefulset.yaml"]}


def tree_digest(g: dict) -> str:
    h = hashlib.sha256()
    for path in sorted(g):
        h.update(path.encode() + b"\0" + g[path].encode() + b"\0")
    return h.hexdigest()

