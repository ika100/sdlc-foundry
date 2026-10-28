"""Shared helpers of the spec 119 acceptance tests (not a test module, never collected).

Contract: docs/specs/119-.../design.md. Builds systems with `broker` resources and events APIs on top of resources_fixtures and spells out
the designed documents of an in-cluster broker instance (key order as designed). Nothing here touches the network or a cluster."""
import hashlib

from resources_fixtures import APP, STORE, comp, system

P = "applications/shop/system.yaml: "
WAVE = "argocd.argoproj.io/sync-wave"
OPTS = "argocd.argoproj.io/sync-options"
COMPARE = "argocd.argoproj.io/compare-options"
BKEYS = ["url", "user", "password"]
BVARS = {"NATS_URL": "url", "NATS_USER": "user", "NATS_PASSWORD": "password"}
ALLOWED_TOP = "type, external, remote, version, replicas, storage, resources, instances"
ALLOWED_INST = "external, remote, replicas, storage, resources, version"  # spec 121: version is an instance key
SIZING = ["version", "replicas", "storage", "resources"]
DEFAULT_RESOURCES = {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"memory": "512Mi"}}
CHART = {"repo_url": "https://nats-io.github.io/k8s/helm/charts", "chart": "nats", "chart_version": "2.15.1"}
NATS_IMAGES = {"2.14": "nats:2.14.9-alpine@sha256:127c5ccbc538a93f53ebb19461dc193130df386c2d6dab8199661a28a30d85bd",
              "2.15": "nats:2.15.2-alpine@sha256:823e7f1d6d8ffe3b30dbd73d4a06bbb939acf94929f7fdf224404da7a05bafb5"}  # spec 121: the designed digests
NACK = {"repo_url": "https://nats-io.github.io/k8s/helm/charts", "chart": "nack", "chart_version": "0.35.0", "operator_version": "0.24.0",
        "namespace": "nack", "release": "nack", "crd": "streams.jetstream.nats.io",
        "selector": "app=nack"}  # spec 119 CI: the chart's legacy names label the Deployment app: nack
RETRY = {"limit": 10, "backoff": {"duration": "30s", "factor": 2, "maxDuration": "10m"}}
SEC_CTX = {"runAsNonRoot": True, "runAsUser": 1000, "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
# the files of the default system's broker directory (users api and web, stream orders, consumer web), sorted
FILES = ["account.yaml", "consumer-orders.web.yaml", "externalsecret-api.yaml", "externalsecret-web.yaml", "kustomization.yaml", "nack-secret.yaml",
         "password-generator.yaml", "server.yaml", "stream-orders.yaml"]


def broker(**kw) -> dict:
    return {"type": "broker", **kw}


def events(*names) -> dict:
    return {n: {"type": "events"} for n in names}


def ext_comp(name, **extra) -> dict:
    c = {"type": "service", "lang": "unknown", "repo": f"acme/{name}", "image": f"ghcr.io/acme/{name}", "external": {"kustomize": f"external/{name}"},
         "instances": {"dev": {}}}
    c.update(extra)
    return c


def lib_comp(name, **extra) -> dict:
    return {"type": "library", "lang": "python", "repo": f"acme/{name}", **extra}


def bsys(resources=None, comps=None, apis=None, **top) -> dict:
    """bus (default broker), orders (events): api provides it, web consumes it."""
    if resources is None:
        resources = {"bus": broker()}
    if comps is None:
        comps = {"api": comp("api", provides=["orders"]), "web": comp("web", consumes=["orders"])}
    return system(resources, comps, apis=events("orders") if apis is None else apis, **top)


def wide(resources=None, **top) -> dict:
    """orders and audit: api provides orders; web consumes orders and provides audit; worker consumes both."""
    comps = {"api": comp("api", provides=["orders"]),
             "web": comp("web", consumes=["orders"], provides=["audit"]),
             "worker": comp("worker", consumes=["orders", "audit"])}
    return bsys(resources, comps, events("orders", "audit"), **top)


def bdir(env: str = "dev", name: str = "bus") -> str:
    return f"{APP}/addons/{env}/{name}"


def bdoc(g, env, file, name="bus"):
    import yaml
    return yaml.safe_load(g[f"{bdir(env, name)}/{file}"])


def L(name="bus") -> dict:
    return {"app.kubernetes.io/name": name, "app.kubernetes.io/part-of": "shop", "app.kubernetes.io/managed-by": "gitops-app"}


def shape(doc):
    """Nested key order of a document, so equality also proves the designed key order (design.md: 'key order as written')."""
    if isinstance(doc, dict):
        return [(k, shape(v)) for k, v in doc.items()]
    if isinstance(doc, list):
        return [shape(v) for v in doc]
    return doc


def contract(resource: str, component: str, prefix: str = "") -> dict:
    return {prefix + v: (f"shop-{resource}-{component}-app", k) for v, k in BVARS.items()}


def upper(name: str) -> str:
    return name.upper().replace("-", "_")


def expected_generator(name="bus") -> dict:
    return {"apiVersion": "generators.external-secrets.io/v1alpha1", "kind": "Password",
            "metadata": {"name": f"shop-{name}-password", "labels": L(name), "annotations": {WAVE: "-1"}},
            "spec": {"length": 32, "digits": 5, "symbols": 0, "noUpper": False, "allowRepeat": True}}


def _es(name, secret, data, bus) -> dict:
    return {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret",
            "metadata": {"name": secret, "labels": L(bus), "annotations": {WAVE: "-1"}},
            "spec": {"refreshPolicy": "CreatedOnce",
                     "target": {"name": secret, "creationPolicy": "Owner", "deletionPolicy": "Retain",
                                "template": {"engineVersion": "v2", "metadata": {"labels": L(bus)}, "data": data}},
                     "dataFrom": [{"sourceRef": {"generatorRef": {"apiVersion": "generators.external-secrets.io/v1alpha1", "kind": "Password",
                                                                  "name": f"shop-{bus}-password"}}}]}}


def expected_nack_secret(name="bus") -> dict:
    return _es(f"shop-{name}-nack", f"shop-{name}-nack", {"user": "_nack", "password": "{{ .password }}"}, name)


def expected_user_secret(component, env="dev", name="bus") -> dict:
    url = f"nats://shop-{name}.shop-{env}.svc:4222"
    return _es(f"shop-{name}-{component}-app", f"shop-{name}-{component}-app", {"url": url, "user": component, "password": "{{ .password }}"}, name)


def publish_list(component, provides, consumes) -> list:
    """Design: for each API it provides `<system>.<api>.>`; then for each API it consumes the four consumer subjects (APIs in apis: order)."""
    out = [f"shop.{a}.>" for a in provides]
    for a in consumes:
        s = f"shop-{a}"
        out += [f"$JS.API.CONSUMER.INFO.{s}.{component}", f"$JS.API.CONSUMER.MSG.NEXT.{s}.{component}", f"$JS.ACK.{s}.{component}.>",
                f"$JS.ACK.*.*.{s}.{component}.>"]
    return out


def expected_server(users, name="bus", env="dev", replicas=1, storage="1Gi", resources=None, version="2.15", server="https://kubernetes.default.svc") -> dict:
    """`users`: [(component, provides, consumes)] in components: order."""
    n, ns = f"shop-{name}", f"shop-{env}"
    repository, tag = (lambda r, d: (r.rsplit(":", 1)[0], r.rsplit(":", 1)[1] + "@" + d))(*NATS_IMAGES[version].split("@"))  # spec 121: the digest rides on the tag
    cluster = {"enabled": True, "replicas": 3} if replicas == 3 else {"enabled": False}
    auth = [{"user": "_nack", "password": "<< $ADMIN_PASSWORD >>"}]
    cenv = {"ADMIN_PASSWORD": {"valueFrom": {"secretKeyRef": {"name": f"{n}-nack", "key": "password"}}}}
    for c, prov, cons in users:
        auth.append({"user": c, "password": f"<< $USER_{upper(c)}_PASSWORD >>",
                     "permissions": {"publish": {"allow": publish_list(c, prov, cons)}, "subscribe": {"allow": [f"_INBOX.{c}.>"]}}})
        cenv[f"USER_{upper(c)}_PASSWORD"] = {"valueFrom": {"secretKeyRef": {"name": f"{n}-{c}-app", "key": "password"}}}
    return {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
            "metadata": {"name": f"shop-{name}-{env}-nats", "namespace": "argocd", "labels": L(name)},
            "spec": {"project": "default",
                     "source": {"repoURL": CHART["repo_url"], "chart": "nats", "targetRevision": CHART["chart_version"],
                                "helm": {"releaseName": n,
                                         "valuesObject": {
                                             "nameOverride": name, "fullnameOverride": n,
                                             "global": {"labels": {"app.kubernetes.io/part-of": "shop"}},
                                             "config": {"cluster": cluster,
                                                        "jetstream": {"enabled": True, "fileStore": {"enabled": True, "pvc": {"enabled": True, "size": storage}},
                                                                      "memoryStore": {"enabled": False}},
                                                        "monitor": {"enabled": True, "port": 8222},
                                                        "merge": {"authorization": {"users": auth}}},
                                             "container": {"image": {"repository": repository, "tag": tag}, "env": cenv,
                                                           "merge": {"resources": resources or DEFAULT_RESOURCES, "securityContext": dict(SEC_CTX)}},
                                             "reloader": {"enabled": True, "merge": {"securityContext": dict(SEC_CTX)}},
                                             "podTemplate": {"merge": {"spec": {"automountServiceAccountToken": False,
                                                                                "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000,
                                                                                                    "fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}}}}},
                                             "service": {"ports": {"monitor": {"enabled": True}}},
                                             "natsBox": {"enabled": False}}}},
                     "destination": {"server": server, "namespace": ns},
                     "syncPolicy": {"automated": {"prune": True, "selfHeal": True}}}}


def expected_account(env="dev", name="bus") -> dict:
    n = f"shop-{name}"
    return {"apiVersion": "jetstream.nats.io/v1beta2", "kind": "Account",
            "metadata": {"name": n, "labels": L(name), "annotations": {WAVE: "1", OPTS: "SkipDryRunOnMissingResource=true"}},
            "spec": {"name": n, "servers": [f"nats://{n}.shop-{env}.svc:4222"], "user": {"secret": {"name": f"{n}-nack"}, "user": "user", "password": "password"}}}


def expected_stream(api="orders", replicas=1, name="bus") -> dict:
    return {"apiVersion": "jetstream.nats.io/v1beta2", "kind": "Stream",
            "metadata": {"name": f"shop-{api}", "labels": L(name),
                         "annotations": {WAVE: "2", OPTS: "Delete=false,SkipDryRunOnMissingResource=true", COMPARE: "IgnoreExtraneous"}},
            "spec": {"name": f"shop-{api}", "subjects": [f"shop.{api}.>"], "storage": "file", "replicas": replicas, "retention": "limits",
                     "discard": "old", "maxAge": "168h", "account": f"shop-{name}", "preventDelete": True}}


def expected_consumer(api, component, name="bus") -> dict:
    return {"apiVersion": "jetstream.nats.io/v1beta2", "kind": "Consumer",
            "metadata": {"name": f"shop-{api}.{component}", "labels": L(name),
                         "annotations": {WAVE: "3", OPTS: "Delete=false,SkipDryRunOnMissingResource=true", COMPARE: "IgnoreExtraneous"}},
            "spec": {"streamName": f"shop-{api}", "durableName": component, "deliverPolicy": "all", "ackPolicy": "explicit", "ackWait": "30s",
                     "maxDeliver": -1, "account": f"shop-{name}", "preventDelete": True}}


def expected_kustomization(files) -> dict:
    return {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": sorted(files)}


def expected_nack_application(server="https://kubernetes.default.svc") -> dict:
    return {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
            "metadata": {"name": "operator-nack", "namespace": "argocd",
                         "labels": {"app.kubernetes.io/managed-by": "gitops-app", "app.kubernetes.io/component": "operator"}},
            "spec": {"project": "default",
                     "source": {"repoURL": NACK["repo_url"], "chart": "nack", "targetRevision": "0.35.0", "helm": {"releaseName": "nack"}},
                     "destination": {"server": server, "namespace": "nack"},
                     "syncPolicy": {"automated": {"prune": True, "selfHeal": True}, "syncOptions": ["CreateNamespace=true", "ServerSideApply=true"]}}}


def expected_external_secret(component, store_key, name="bus", refresh="1h") -> dict:
    secret = f"shop-{name}-{component}-app"
    return {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret", "metadata": {"name": secret, "labels": L(name)},
            "spec": {"refreshInterval": refresh, "secretStoreRef": {"name": STORE["name"], "kind": STORE["kind"]},
                     "target": {"name": secret, "creationPolicy": "Orphan", "deletionPolicy": "Retain"},
                     "data": [{"secretKey": k, "remoteRef": {"key": store_key, "property": k}} for k in BKEYS]}}


def tree_digest(g: dict) -> str:
    h = hashlib.sha256()
    for path in sorted(g):
        h.update(path.encode() + b"\0" + g[path].encode() + b"\0")
    return h.hexdigest()
