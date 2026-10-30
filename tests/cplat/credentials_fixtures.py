"""Shared helpers of the spec 128 acceptance tests (not a test module, never collected).

Contract: docs/specs/128-.../design.md. Spells out the designed credentials files and plans of the rendered owners, and gives the
behaviour tests of `create.py` (render.py's CREDENTIALS_SCRIPT) a local fake Kubernetes API (an http.server) and fake valkey and NATS
servers on 127.0.0.1. Nothing here touches the network beyond the loopback interface or a cluster."""
import base64
import copy
import hashlib
import json
import re
import socketserver
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from resources_fixtures import APP, platform_render_module

HOOK = "argocd.argoproj.io/hook"
WAVE = "argocd.argoproj.io/sync-wave"
DELETE_POLICY = "argocd.argoproj.io/hook-delete-policy"
CRED_FILES = ["credentials-configmap.yaml", "credentials-job.yaml", "credentials-role.yaml", "credentials-rolebinding.yaml",
              "credentials-serviceaccount.yaml"]
KINDS = {"credentials-serviceaccount.yaml": ("v1", "ServiceAccount"), "credentials-role.yaml": ("rbac.authorization.k8s.io/v1", "Role"),
         "credentials-rolebinding.yaml": ("rbac.authorization.k8s.io/v1", "RoleBinding"), "credentials-configmap.yaml": ("v1", "ConfigMap"),
         "credentials-job.yaml": ("batch/v1", "Job")}
GONE = {"cache": ["externalsecret.yaml", "password-generator.yaml"],
        "broker": ["password-generator.yaml", "nack-secret.yaml", "externalsecret-api.yaml", "externalsecret-web.yaml"],
        "bucket": ["externalsecret.yaml", "access-key-generator.yaml", "secret-key-generator.yaml"]}
ALNUM = re.compile(r"^[A-Za-z0-9]+$")


def renderer(name="render_128"):
    return platform_render_module(name)


def script_text() -> str:
    text = getattr(renderer("render_128_script"), "CREDENTIALS_SCRIPT", None)
    assert isinstance(text, str) and text, "render.py has CREDENTIALS_SCRIPT"
    return text


def image() -> str:
    text = getattr(renderer("render_128_image"), "CREDENTIALS_IMAGE", None)
    assert isinstance(text, str) and text, "render.py has CREDENTIALS_IMAGE"
    return text


def files_in(g: dict, directory: str) -> dict[str, str]:
    pre = directory + "/"
    return {p[len(pre):]: t for p, t in g.items() if p.startswith(pre) and "/" not in p[len(pre):]}


def cred(g: dict, directory: str) -> dict[str, dict]:
    """The parsed credentials-*.yaml files of an owner directory (every one must exist)."""
    fs = files_in(g, directory)
    missing = [f for f in CRED_FILES if f not in fs]
    assert not missing, f"{directory}: missing {missing}"
    return {f: yaml.safe_load(fs[f]) for f in CRED_FILES}


def plan_of(g: dict, directory: str) -> dict:
    return json.loads(cred(g, directory)["credentials-configmap.yaml"]["data"]["plan.json"])


def addon(env: str, name: str) -> str:
    return f"{APP}/addons/{env}/{name}"


def overlay(env: str, name: str) -> str:
    return f"{APP}/overlays/{env}/{name}"


def job_name(owner: str, plan_text: str) -> str:
    h = hashlib.sha256((plan_text + script_text() + image()).encode()).hexdigest()[:8]
    return f"{owner[:42]}-credentials-{h}"


def role_rules(secrets, retired_generators, pods=None, retire_es=None) -> list[dict]:
    secrets = sorted(secrets)
    rules = [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["create"]},
             {"apiGroups": [""], "resources": ["secrets"], "resourceNames": secrets, "verbs": ["get", "patch"]},
             {"apiGroups": ["external-secrets.io"], "resources": ["externalsecrets"], "resourceNames": sorted(retire_es or secrets), "verbs": ["get", "delete"]},
             {"apiGroups": ["generators.external-secrets.io"], "resources": ["passwords"], "resourceNames": sorted(retired_generators), "verbs": ["delete"]}]
    if pods:
        rules.append({"apiGroups": [""], "resources": ["pods"], "resourceNames": sorted(pods), "verbs": ["get", "delete"]})
    return rules


def normalised_rules(rules: list[dict]) -> list[dict]:
    out = copy.deepcopy(rules)
    for r in out:
        if "resourceNames" in r:
            r["resourceNames"] = sorted(r["resourceNames"])
    return out


def expected_job(owner: str, name: str, labels: dict) -> dict:
    return {"backoffLimit": 2, "activeDeadlineSeconds": 300, "ttlSecondsAfterFinished": 600,
            "template": {"metadata": {"labels": labels},
                         "spec": {"serviceAccountName": f"{owner}-credentials", "automountServiceAccountToken": True, "restartPolicy": "Never",
                                  "securityContext": {"runAsNonRoot": True, "runAsUser": 65534, "runAsGroup": 65534, "seccompProfile": {"type": "RuntimeDefault"}},
                                  "containers": [{"name": "credentials", "image": image(),
                                                  "command": ["python3", "/credentials/create.py", "/credentials/plan.json"],
                                                  "env": [{"name": "PYTHONDONTWRITEBYTECODE", "value": "1"}],
                                                  "resources": {"requests": {"cpu": "10m", "memory": "32Mi"}, "limits": {"memory": "64Mi"}},
                                                  "securityContext": {"runAsNonRoot": True, "runAsUser": 65534, "allowPrivilegeEscalation": False,
                                                                      "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                                                  "volumeMounts": [{"name": "credentials", "mountPath": "/credentials", "readOnly": True}]}],
                                  "volumes": [{"name": "credentials", "configMap": {"name": f"{owner}-credentials"}}]}}}


def check_owner_files(g: dict, directory: str, owner: str, ns: str, labels: dict, secrets, retired_generators, pods=None):
    """The five credentials files of one owner as the contract spells them."""
    docs = cred(g, directory)
    for f, (api, kind) in KINDS.items():
        d = docs[f]
        assert (d["apiVersion"], d["kind"]) == (api, kind), f
        ann = d["metadata"]["annotations"]
        assert ann[HOOK] == "PreSync", f
        assert ann[WAVE] == ("1" if kind == "Job" else "0"), f
        assert ann[DELETE_POLICY] == ("BeforeHookCreation,HookSucceeded" if kind == "Job" else "BeforeHookCreation"), f
        assert d["metadata"]["labels"] == labels, f
        if kind != "Job":
            assert d["metadata"]["name"] == f"{owner}-credentials", f
    assert normalised_rules(docs["credentials-role.yaml"]["rules"]) == normalised_rules(role_rules(secrets, retired_generators, pods))
    rb = docs["credentials-rolebinding.yaml"]
    assert rb["subjects"] == [{"kind": "ServiceAccount", "name": f"{owner}-credentials", "namespace": ns}]
    assert rb["roleRef"] == {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": f"{owner}-credentials"}
    cm = docs["credentials-configmap.yaml"]["data"]
    assert cm["create.py"] == script_text()
    assert cm["plan.json"] == json.dumps(json.loads(cm["plan.json"]), indent=2, sort_keys=True)
    job = docs["credentials-job.yaml"]
    assert job["metadata"]["name"] == job_name(owner, cm["plan.json"])
    assert job["spec"] == expected_job(owner, job["metadata"]["name"], labels)
    kz = yaml.safe_load(files_in(g, directory)["kustomization.yaml"])
    assert all(f in kz["resources"] for f in CRED_FILES), kz["resources"]
    assert kz["resources"] == sorted(kz["resources"])


def check_no_files(g: dict, directory: str, names) -> None:
    fs = files_in(g, directory)
    assert fs, f"{directory} renders"
    for n in names:
        assert n not in fs, f"{directory}/{n} is still rendered"
    kz = yaml.safe_load(fs["kustomization.yaml"])
    for n in names:
        assert n not in kz["resources"], f"{directory}/kustomization.yaml still lists {n}"


# ---------------- reading rendered objects for AC-128.12 ----------------

def all_docs(g: dict) -> list[tuple[str, dict]]:
    out = []
    for path, text in g.items():
        if path.endswith((".yaml", ".yml")):
            try:
                for d in yaml.safe_load_all(text):
                    if isinstance(d, dict):
                        out.append((path, d))
            except yaml.YAMLError:
                pass
    return out


def generator_backed(doc: dict) -> bool:
    if doc.get("kind") != "ExternalSecret":
        return False
    return any("generatorRef" in (x.get("sourceRef") or {}) for x in doc.get("spec", {}).get("dataFrom") or [])


def written_twice(g: dict, prefix: str) -> list[str]:
    """Paths under `prefix` of every generator-backed ExternalSecret or Password generator: a generated credential that something may write again."""
    bad = []
    for path, d in all_docs(g):
        if path.startswith(prefix) and (generator_backed(d) or (d.get("kind") == "Password" and "generators.external-secrets.io" in d.get("apiVersion", ""))):
            bad.append(f"{path}: {d['kind']} {d['metadata']['name']}")
    return bad


# ---------------- fake servers ----------------

class _Tcp(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class FakeValkey:
    """Accepts `AUTH <user> <password>` with the server's current password (RESP array or inline)."""

    def __init__(self, password: str):
        self.password = password
        self.auths: list[tuple[str, str]] = []
        outer = self

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(3)
                try:
                    data = self.request.recv(4096).decode(errors="replace")
                except OSError:
                    return
                toks = [t for t in re.split(r"[\r\n ]+", data) if t and t[0] not in "*$"]
                if toks and toks[0].upper() == "AUTH" and len(toks) >= 3:
                    outer.auths.append((toks[1], toks[2]))
                    self.request.sendall(b"+OK\r\n" if toks[2] == outer.password else b"-WRONGPASS invalid username-password pair or user is disabled.\r\n")
                else:
                    self.request.sendall(b"-ERR unknown command\r\n")

        self.srv = _Tcp(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class FakeNats:
    """Sends INFO, reads CONNECT + PING and answers PONG or -ERR 'Authorization Violation' by the server's user table."""

    def __init__(self, users: dict[str, str]):
        self.users = dict(users)
        self.connects: list[str] = []
        outer = self

        class H(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(3)
                try:
                    self.request.sendall(b'INFO {"server_id":"x","tls_required":false,"auth_required":true}\r\n')
                    buf = b""
                    while b"PING" not in buf:
                        chunk = self.request.recv(4096)
                        if not chunk:
                            return
                        buf += chunk
                except OSError:
                    return
                m = re.search(rb"CONNECT (\{.*?\})\r\n", buf)
                opts = json.loads(m.group(1)) if m else {}
                outer.connects.append(opts.get("user", ""))
                ok = outer.users.get(opts.get("user")) == opts.get("pass")
                self.request.sendall(b"PONG\r\n" if ok else b"-ERR 'Authorization Violation'\r\n")

        self.srv = _Tcp(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def unb64(s: str) -> str:
    return base64.b64decode(s).decode()


class FakeKube:
    """Just enough of the Kubernetes API for create.py: secrets, ExternalSecrets, Password generators and pods in one namespace."""

    def __init__(self, ns="shop-dev"):
        self.ns = ns
        self.secrets: dict[str, dict] = {}
        self.externalsecrets: dict[str, dict] = {}
        self.generators: set[str] = set()
        self.pods: dict[str, dict] = {}
        self.log: list[dict] = []
        self.faults: list[int] = []          # statuses returned (in order) for the next requests
        self.on_pod_delete = None            # callable(name) after a pod was deleted and re-created
        self.rv = 100
        self.lock = threading.Lock()
        self.token = "tok-" + hashlib.sha1(b"fake").hexdigest()[:8]
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None):
                body = json.dumps(obj if obj is not None else {"kind": "Status", "code": code}).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                body = json.loads(raw) if raw else None
                with outer.lock:
                    outer.log.append({"method": method, "path": self.path, "body": body, "ctype": self.headers.get("Content-Type"),
                                      "auth": self.headers.get("Authorization")})
                    if outer.faults:
                        return self._send(outer.faults.pop(0))
                    code, obj = outer.route(method, self.path, body)
                self._send(code, obj)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_DELETE(self):
                self._handle("DELETE")

            def do_PATCH(self):
                self._handle("PATCH")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    # ---- state helpers ----
    def put_secret(self, name, data: dict, labels=None, annotations=None, owner_refs=None):
        self.rv += 1
        meta = {"name": name, "namespace": self.ns, "resourceVersion": str(self.rv), "labels": dict(labels or {})}
        if annotations:
            meta["annotations"] = dict(annotations)
        if owner_refs:
            meta["ownerReferences"] = owner_refs
        self.secrets[name] = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque", "metadata": meta, "data": {k: b64(v) for k, v in data.items()}}

    def value(self, secret, key) -> str:
        return unb64(self.secrets[secret]["data"][key])

    def values(self, secret) -> dict:
        return {k: unb64(v) for k, v in self.secrets[secret]["data"].items()}

    def put_generated_es(self, name):
        self.externalsecrets[name] = {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret", "metadata": {"name": name},
                                      "spec": {"dataFrom": [{"sourceRef": {"generatorRef": {"kind": "Password", "name": "g"}}}]}}

    def put_pod(self, name, ip="127.0.0.1", ready=True, env=None, uid=None):
        """env: {container variable: secret name}"""
        envs = [{"name": k, "valueFrom": {"secretKeyRef": {"name": s, "key": "password"}}} for k, s in (env or {}).items()]
        self.pods[name] = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "uid": uid or f"uid-{name}-0"},
                           "spec": {"containers": [{"name": "c", "env": envs}]},
                           "status": {"podIP": ip, "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}

    def calls(self, method=None, contains=""):
        return [c for c in self.log if (method is None or c["method"] == method) and contains in c["path"]]

    def writes(self):
        return [c for c in self.log if c["method"] in ("POST", "PATCH", "PUT") or (c["method"] == "DELETE")]

    # ---- routing ----
    def route(self, method, path, body):
        m = re.match(r"^/apis/external-secrets\.io/v1/namespaces/([^/]+)/externalsecrets/([^/]+)$", path)
        if m:
            name = m.group(2)
            if method == "GET":
                return (200, self.externalsecrets[name]) if name in self.externalsecrets else (404, None)
            if method == "DELETE":
                return (200, self.externalsecrets.pop(name)) if name in self.externalsecrets else (404, None)
        m = re.match(r"^/apis/generators\.external-secrets\.io/v1alpha1/namespaces/([^/]+)/passwords/([^/]+)$", path)
        if m and method == "DELETE":
            if m.group(2) in self.generators:
                self.generators.discard(m.group(2))
                return 200, {"kind": "Status", "code": 200}
            return 404, None
        if re.match(r"^/api/v1/namespaces/[^/]+/secrets$", path) and method == "POST":
            name = body["metadata"]["name"]
            if name in self.secrets:
                return 409, {"kind": "Status", "reason": "AlreadyExists", "code": 409}
            self.rv += 1
            body = copy.deepcopy(body)
            body["metadata"]["resourceVersion"] = str(self.rv)
            self.secrets[name] = body
            return 201, body
        m = re.match(r"^/api/v1/namespaces/([^/]+)/secrets/([^/]+)$", path)
        if m:
            name = m.group(2)
            if name not in self.secrets:
                return 404, None
            if method == "GET":
                return 200, self.secrets[name]
            if method == "PATCH":
                return self.patch(name, body)
        m = re.match(r"^/api/v1/namespaces/([^/]+)/pods/([^/]+)$", path)
        if m:
            name = m.group(2)
            if name not in self.pods:
                return 404, None
            if method == "GET":
                return 200, self.pods[name]
            if method == "DELETE":
                old = self.pods[name]
                n = int(old["metadata"]["uid"].rsplit("-", 1)[1]) + 1
                new = copy.deepcopy(old)
                new["metadata"]["uid"] = f"uid-{name}-{n}"
                self.pods[name] = new
                if self.on_pod_delete:
                    self.on_pod_delete(name)
                return 200, old
        return 404, None

    def patch(self, name, ops):
        sec = copy.deepcopy(self.secrets[name])
        for op in ops:
            parts = [p.replace("~1", "/").replace("~0", "~") for p in op["path"].split("/")[1:]]
            node = sec
            for p in parts[:-1]:
                node = node.setdefault(p, {}) if op["op"] in ("add", "replace") else node[p]
            last = parts[-1]
            if op["op"] == "test":
                if node.get(last) != op["value"]:
                    return 409, {"kind": "Status", "reason": "Conflict", "code": 409}
            elif op["op"] in ("add", "replace"):
                node[last] = op["value"]
            elif op["op"] == "remove":
                if last not in node:
                    return 422, {"kind": "Status", "reason": "Invalid", "code": 422}
                del node[last]
            else:
                return 422, {"kind": "Status", "reason": "Invalid", "code": 422}
        self.rv += 1
        sec["metadata"]["resourceVersion"] = str(self.rv)
        self.secrets[name] = sec
        return 200, sec


def run_script(tmp_path: Path, kube: FakeKube, plan: dict, timeout=170) -> subprocess.CompletedProcess:
    """Run render.py's CREDENTIALS_SCRIPT with a plan against the fake API."""
    d = tmp_path / "creds"
    sa = d / "sa"
    sa.mkdir(parents=True, exist_ok=True)
    (sa / "token").write_text(kube.token)
    (d / "create.py").write_text(script_text())
    (d / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True))
    env = {"PATH": "/usr/bin:/bin", "CREDENTIALS_API_URL": kube.url, "CREDENTIALS_SA_DIR": str(sa), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-I", str(d / "create.py"), str(d / "plan.json")], env=env, capture_output=True, text=True, timeout=timeout)


def cache_plan(ns="shop-dev", name="shop-sessions", port=0, pods=None, labels=None) -> dict:
    plan = {"namespace": ns,
            "secrets": [{"name": f"{name}-app", "labels": labels or {"app.kubernetes.io/name": "sessions"}, "generate": {"password": 32},
                         "data": {"url": "redis://default:{{ .password }}@" + f"{name}.{ns}.svc:6379/0", "host": f"{name}.{ns}.svc", "port": "6379"}}],
            "retire": {"externalSecrets": [f"{name}-app"], "generators": [f"{name}-password"]}}
    if port:
        plan["verify"] = {"engine": "valkey", "port": port, "pods": pods or [f"{name}-0"],
                          "users": [{"secret": f"{name}-app", "key": "password", "user": "default", "env": "VALKEY_PASSWORD"}]}
    return plan


def nats_plan(port, ns="shop-dev", name="shop-bus", comps=("api", "web"), pods=None) -> dict:
    secrets = [{"name": f"{name}-nack", "labels": {}, "generate": {"password": 32}, "data": {"user": "_nack"}}]
    users = [{"secret": f"{name}-nack", "key": "password", "user": "_nack", "env": "ADMIN_PASSWORD"}]
    for c in comps:
        secrets.append({"name": f"{name}-{c}-app", "labels": {}, "generate": {"password": 32}, "data": {"url": f"nats://{name}.{ns}.svc:4222", "user": c}})
        users.append({"secret": f"{name}-{c}-app", "key": "password", "user": c, "env": f"USER_{c.upper()}_PASSWORD"})
    return {"namespace": ns, "secrets": secrets,
            "retire": {"externalSecrets": [s["name"] for s in secrets], "generators": [f"{name}-password"]},
            "verify": {"engine": "nats", "port": port, "pods": pods or [f"{name}-0"], "users": users}}


def bucket_plan(ns="shop-dev", name="shop-files") -> dict:
    return {"namespace": ns,
            "secrets": [{"name": f"{name}-app", "labels": {}, "generate": {"accessKeyId": 20, "secretAccessKey": 40},
                         "data": {"endpoint": f"http://{name}-filer.{ns}.svc:8333", "bucket": name, "region": "us-east-1", "forcePathStyle": "true"}}],
            "retire": {"externalSecrets": [f"{name}-app"], "generators": [f"{name}-access-key", f"{name}-secret-key"]}}
