"""Spec 098: templates/gitops-app/scripts/check-service-crds.py validates Components against the CRDs of the service
ref named by a `Service-ref:` PR body marker (AC-098.3-AC-098.13); the gitops-app CI step and recipes (AC-098.10,
AC-098.13-AC-098.15, AC-098.17). Fully offline: the GitHub API is a fake HTTP server on 127.0.0.1."""
import base64
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import urllib.parse
from pathlib import Path

import pytest
import yaml

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "gitops-app"
SCRIPT = TEMPLATE / "scripts" / "check-service-crds.py"
TOKEN = "ghp_SecretTokenValue0123456789abcdef"  # pragma: allowlist secret
SHA = "abcdef1234567890abcdef1234567890abcdef12"
MAIN_SHA = "1234567fedcba0987654321fedcba0987654321f"
HINT = "Expected one line: Service-ref: <owner>/<repo>@<branch>"

CRD = {
    "apiVersion": "apiextensions.k8s.io/v1", "kind": "CustomResourceDefinition",
    "metadata": {"name": "components.example.io"},
    "spec": {
        "group": "example.io", "names": {"kind": "Component", "plural": "components"}, "scope": "Namespaced",
        "versions": [
            {"name": "v1alpha1", "served": True, "storage": True, "schema": {"openAPIV3Schema": {
                "type": "object",
                "properties": {"spec": {
                    "type": "object", "required": ["build"],
                    "properties": {
                        "build": {"type": "object", "required": ["namespace"],
                                  "properties": {"namespace": {"type": "string"}, "replicas": {"type": "integer"}}},
                        "steps": {"type": "array", "items": {"type": "object", "properties": {"image": {"type": "string"}}}},
                        "port": {"x-kubernetes-int-or-string": True},
                    }}}}}},
            {"name": "v1beta1", "served": False, "storage": False, "schema": {"openAPIV3Schema": {"type": "object"}}},
        ],
    },
}
PIPELINE_CRD = {**CRD, "metadata": {"name": "pipelines.example.io"},
                "spec": {**CRD["spec"], "names": {"kind": "Pipeline", "plural": "pipelines"}}}


def dump(obj):
    return yaml.safe_dump(obj)


def component(name="web", *, kind="Component", api="example.io/v1alpha1", spec=None):
    spec = {"build": {"namespace": "ns"}} if spec is None else spec
    return dump({"apiVersion": api, "kind": kind, "metadata": {"name": name}, "spec": spec})


class Fake:
    """A GitHub API fake serving /repos/{o}/{r}, /branches/{b} and /contents/{path}?ref= from dicts."""

    def __init__(self, slug="acme/shop-api"):
        self.slug = slug
        self.default = "main"
        self.branches = {"feature/x": SHA, "main": MAIN_SHA}
        self.files: dict[str, str] = {"charts/app/crds/component.yaml": dump(CRD)}
        self.status: dict[str, int] = {}            # path suffix -> forced status
        self.requests: list[tuple[str, str]] = []   # (raw path, Authorization header)
        self.server = None

    def tree(self, path):
        pre = path.strip("/") + "/"
        kids = {}
        for f in self.files:
            if f.startswith(pre):
                head, _, rest = f[len(pre):].partition("/")
                kids[head] = "dir" if rest else "file"
        return [{"name": n, "path": pre + n, "type": t} for n, t in sorted(kids.items())]

    def handle(self, raw):
        parsed = urllib.parse.urlparse(raw)
        path = urllib.parse.unquote(parsed.path)
        for suffix, code in self.status.items():
            if path.endswith(suffix) or path == suffix:
                return code, {"message": "forced"}
        base = f"/repos/{self.slug}"
        if path.lower() == base.lower():
            return 200, {"default_branch": self.default}
        if path.lower().startswith(base.lower() + "/branches/"):
            b = path[len(base) + len("/branches/"):]
            return (200, {"name": b, "commit": {"sha": self.branches[b]}}) if b in self.branches else (404, {"message": "Branch not found"})
        if path.lower().startswith(base.lower() + "/contents/"):
            p = path[len(base) + len("/contents/"):].strip("/")
            ref = urllib.parse.parse_qs(parsed.query).get("ref", [""])[0]
            if ref not in self.branches.values():
                return 422, {"message": f"No commit found for the ref {ref}"}
            if p in self.files:
                data = base64.encodebytes(self.files[p].encode()).decode()
                return 200, {"type": "file", "path": p, "encoding": "base64", "content": data, "size": len(self.files[p])}
            kids = self.tree(p)
            return (200, kids) if kids else (404, {"message": "Not Found"})
        return 404, {"message": "Not Found"}

    def __enter__(self):
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                fake.requests.append((self.path, self.headers.get("Authorization", "")))
                code, payload = fake.handle(self.path)
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def gitops(tmp_path):
    root = tmp_path / "gitops"
    (root / "scripts").mkdir(parents=True)
    if SCRIPT.is_file():
        shutil.copy(SCRIPT, root / "scripts" / "check-service-crds.py")
    app = root / "applications" / "shop"
    app.mkdir(parents=True)
    (app / "services.yaml").write_text(dump({"services": [{"name": "api", "repo": "acme/shop-api", "shape": "service-go"}]}))
    return root


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def run(root, *, body="Service-ref: acme/shop-api@feature/x", token=TOKEN, url=None, github_env=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "PR_BODY", "SERVICE_REPOS"))}
    if body is not None:
        env["PR_BODY"] = body
    if token is not None:
        env["SERVICE_REPOS_READ_TOKEN"] = token
    if url:
        env["GITHUB_API_URL"] = url
    env_file, summary = root.parent / "github_env", root.parent / "summary.md"
    env_file.write_text("")
    summary.write_text("")
    if github_env:
        env["GITHUB_ENV"], env["GITHUB_STEP_SUMMARY"] = str(env_file), str(summary)
    p = subprocess.run(["uv", "run", "scripts/check-service-crds.py"], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    p.github_env, p.summary = env_file.read_text(), summary.read_text()
    p.lines = p.stderr.splitlines()
    return p


def never_leaks(p, token=TOKEN):
    for text in (p.stdout, p.stderr, p.github_env, p.summary):
        assert token not in text


def with_fake(gitops, fake_setup=None, **kw):
    with Fake() as fake:
        if fake_setup:
            fake_setup(fake)
        p = run(gitops, url=fake.url, **kw)
    return p, fake


REF = "acme/shop-api@feature/x"


# --- AC-098.3 / .4 / .5: validation against the service ref's CRD ---

def test_ac_098_5_valid_components_pass_and_the_log_lists_the_kinds(gitops):
    """AC-098.5: pass; log lists each CRD kind used with its source; stdout is the skip list."""
    write(gitops, "applications/shop/pkg/a.yaml", component("a"))
    write(gitops, "applications/shop/pkg/b.yaml", component("b") + "---\n" + component("c", spec={"build": {"namespace": "n", "replicas": 2}, "port": 80}))
    p, _ = with_fake(gitops)
    assert p.returncode == 0, p.stderr
    assert f"OK: Component (example.io) from {REF}: 3 resource(s) valid" in p.lines
    assert f"service CRDs from {REF} (commit {SHA[:7]}): Component" in p.lines
    assert p.stdout.strip() == "example.io/v1alpha1/Component"
    assert "SERVICE_CRD_SKIP=example.io/v1alpha1/Component" in p.github_env
    assert "Component" in p.summary and REF in p.summary
    never_leaks(p)


def test_ac_098_3_every_component_is_validated_and_other_manifests_are_not(gitops):
    """AC-098.3: changed or not, anywhere under applications/; other kinds, other groups and patches are left alone."""
    write(gitops, "applications/shop/overlays/dev/api/ok.yaml", component("ok"))
    write(gitops, "applications/shop/external/pkg/bad.yaml", component("bad", spec={"build": {}}))
    write(gitops, "applications/shop/other.yaml", component("other-group", api="other.io/v1", spec={"nonsense": 1}))
    write(gitops, "applications/shop/deploy.yaml", dump({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "d"}, "spec": {"zzz": 1}}))
    write(gitops, "applications/shop/pkg2/kustomization.yaml", dump({"patches": [{"path": "patch.yaml"}], "patchesStrategicMerge": ["old.yaml"]}))
    write(gitops, "applications/shop/pkg2/patch.yaml", component("patch", spec={"bogus": 1}))
    write(gitops, "applications/shop/pkg2/old.yaml", component("old", spec={"bogus": 1}))
    write(gitops, "applications/shop/broken.yaml", "a: [unclosed\n")
    p, _ = with_fake(gitops)
    assert p.returncode == 1
    errors = [line for line in p.lines if line.startswith("ERROR")]
    assert errors == [f"ERROR: applications/shop/external/pkg/bad.yaml: Component bad (example.io/v1alpha1) does not match the CRD from {REF}: spec.build.namespace: missing required field"]


def test_ac_098_3_the_skip_list_names_every_served_version_of_every_service_crd(gitops):
    """AC-098.3: SERVICE_CRD_SKIP carries <apiVersion>/<Kind> for all served versions (unserved ones are not listed)."""
    def setup(f):
        f.files["charts/app/crds/pipeline.yaml"] = dump({**PIPELINE_CRD, "spec": {**PIPELINE_CRD["spec"], "versions": [
            {**PIPELINE_CRD["spec"]["versions"][0], "name": "v1"}, {**PIPELINE_CRD["spec"]["versions"][0], "name": "v2"}]}})
    p, _ = with_fake(gitops, setup)
    assert p.returncode == 0, p.stderr
    assert set(p.stdout.strip().split(",")) == {"example.io/v1alpha1/Component", "example.io/v1/Pipeline", "example.io/v2/Pipeline"}


def test_ac_098_3_an_unserved_version_is_an_error(gitops):
    """AC-098.3/4: a Component of a version the CRD does not serve fails."""
    write(gitops, "applications/shop/a.yaml", component("a", api="example.io/v1beta1"))
    p, _ = with_fake(gitops)
    assert p.returncode == 1
    assert f"ERROR: applications/shop/a.yaml: Component a (example.io/v1beta1) does not match the CRD from {REF}: (root): version v1beta1 is not served by the CRD (served: v1alpha1)" in p.lines


def test_ac_098_3_crds_come_from_chart_crds_and_untemplated_templates(gitops):
    """AC-098.3: <chart>/crds plus untemplated CRD files under <chart>/templates; other templates are ignored."""
    def setup(f):
        f.files = {"charts/app/crds/x.yaml": dump(CRD),
                   "charts/app/templates/pipeline-crd.yaml": dump(PIPELINE_CRD),
                   "charts/app/templates/deployment.yaml": "kind: Deployment\nmetadata: {name: {{ .Release.Name }}}\n"}
    p, _ = with_fake(gitops, setup)
    assert p.returncode == 0, p.stderr
    assert set(p.stdout.strip().split(",")) == {"example.io/v1alpha1/Component", "example.io/v1alpha1/Pipeline"}


def test_ac_098_3_external_helm_path_selects_the_chart(gitops):
    """AC-098.3: <chart> is external.helm.path of the marker repo's services; other charts are not read."""
    write(gitops, "applications/shop/services.yaml", dump({"services": [{
        "name": "api", "repo": "acme/shop-api", "shape": "service-go",
        "external": {"helm": {"repoURL": "https://github.com/acme/shop-api", "path": "charts/api", "revision": "main"}}}]}))
    def setup(f):
        f.files = {"charts/other/crds/p.yaml": dump(PIPELINE_CRD), "charts/api/crds/c.yaml": dump(CRD)}
    p, fake = with_fake(gitops, setup)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "example.io/v1alpha1/Component"
    assert not any("charts/other" in r for r, _ in fake.requests)


def test_ac_098_3_reads_are_pinned_to_the_branch_commit(gitops):
    """AC-098.3: the branch is URL-quoted and every contents read uses the commit sha."""
    p, fake = with_fake(gitops)
    assert p.returncode == 0, p.stderr
    paths = [r for r, _ in fake.requests]
    assert any("/branches/feature%2Fx" in r for r in paths)
    contents = [r for r in paths if "/contents/" in r]
    assert contents and all(f"ref={SHA}" in r for r in contents)


@pytest.mark.parametrize("spec_, field, problem", [
    ({"build": {"namespace": "n", "extra": 1}}, "spec.build.extra", "unknown field"),
    ({"build": {"namespace": "n", "replicas": "two"}}, "spec.build.replicas", "wrong type (want integer, got string)"),
    ({"build": {}}, "spec.build.namespace", "missing required field"),
    ({"build": {"namespace": "n"}, "steps": [{"image": "a"}, {"image": "b"}, {"image": 3}]}, "spec.steps[2].image", "wrong type (want string, got integer)"),
])
def test_ac_098_4_a_component_that_does_not_match_fails_with_file_kind_field_and_ref(gitops, spec_, field, problem):
    """AC-098.4: unknown field (strict), wrong type, missing required field; the log names file, kind, field and ref."""
    write(gitops, "applications/shop/web.yaml", component("web", spec=spec_))
    p, _ = with_fake(gitops)
    assert p.returncode == 1
    assert (f"ERROR: applications/shop/web.yaml: Component web (example.io/v1alpha1) does not match the CRD from {REF}: "
            f"{field}: {problem}") in p.lines
    assert not any(line.startswith("OK:") for line in p.lines)
    never_leaks(p)


def test_ac_098_4_unknown_top_level_field_is_reported_at_the_root(gitops):
    """AC-098.4: strict checking also applies to the document itself."""
    write(gitops, "applications/shop/web.yaml", component("web") + "bogus: 1\n")
    p, _ = with_fake(gitops)
    assert p.returncode == 1
    assert any("does not match the CRD" in line and line.endswith("bogus: unknown field") for line in p.lines)


def test_ac_098_4_int_or_string_accepts_both(gitops):
    """AC-098.4/3: x-kubernetes-int-or-string is converted, not rejected."""
    write(gitops, "applications/shop/a.yaml", component("a", spec={"build": {"namespace": "n"}, "port": 80}))
    write(gitops, "applications/shop/b.yaml", component("b", spec={"build": {"namespace": "n"}, "port": "http"}))
    p, _ = with_fake(gitops)
    assert p.returncode == 0, p.stderr
    assert f"OK: Component (example.io) from {REF}: 2 resource(s) valid" in p.lines


# --- AC-098.6 / .7: ref resolution, no CRDs ---

def test_ac_098_6_a_missing_branch_falls_back_to_the_default_branch_and_says_so(gitops):
    """AC-098.6: validate against the default branch; log names both."""
    write(gitops, "applications/shop/web.yaml", component("web", spec={"build": {}}))
    def setup(f):
        del f.branches["feature/x"]
    p, fake = with_fake(gitops, setup)
    assert (f"WARNING: branch feature/x no longer exists in acme/shop-api; validating against its default branch main") in p.lines
    assert p.returncode == 1
    assert any("does not match the CRD from acme/shop-api@main" in line for line in p.lines)
    assert all(f"ref={MAIN_SHA}" in r for r, _ in fake.requests if "/contents/" in r)


def test_ac_098_6_the_fallback_passes_when_components_match(gitops):
    """AC-098.6: a pass with the fallback still reports the default branch as the source."""
    write(gitops, "applications/shop/web.yaml", component("web"))
    p, _ = with_fake(gitops, lambda f: f.branches.pop("feature/x"))
    assert p.returncode == 0, p.stderr
    assert f"service CRDs from acme/shop-api@main (commit {MAIN_SHA[:7]}): Component" in p.lines


def test_ac_098_7_a_ref_without_crds_changes_nothing(gitops):
    """AC-098.7: log says it defines no CRDs; exit 0; empty stdout; Components are not validated."""
    write(gitops, "applications/shop/web.yaml", component("web", spec={"nonsense": 1}))
    p, _ = with_fake(gitops, lambda f: f.files.clear() or f.files.update({"charts/app/templates/deployment.yaml": "kind: Deployment\n", "README.md": "x"}))
    assert p.returncode == 0, p.stderr
    assert "service CRDs: acme/shop-api@feature/x defines no CRDs; manifests are validated as before" in p.lines
    assert p.stdout == "" and p.github_env == ""


# --- AC-098.8 / .9 / .10: stop before any fetch ---

def test_ac_098_8_a_repo_that_is_not_a_service_fails_and_nothing_is_fetched(gitops):
    """AC-098.8"""
    p, fake = with_fake(gitops, body="Service-ref: acme/elsewhere@main")
    assert p.returncode == 1 and p.stdout == ""
    assert ("ERROR: Service-ref names acme/elsewhere, which is not a service repo in applications/*/services.yaml; "
            "nothing was fetched") in p.lines
    assert fake.requests == []
    never_leaks(p)


def test_ac_098_8_the_repo_comparison_ignores_case(gitops):
    """AC-098.8: services.yaml is compared case-insensitively."""
    p, fake = with_fake(gitops, body="Service-ref: ACME/Shop-API@feature/x")
    assert p.returncode == 0, p.stderr
    assert fake.requests


@pytest.mark.parametrize("body, reason", [
    ("Service-ref: nonsense", "malformed Service-ref line 'Service-ref: nonsense'"),
    ("Service-ref: acme/shop-api", "malformed Service-ref line 'Service-ref: acme/shop-api'"),
    ("Service-ref: acme/shop-api@", "malformed Service-ref line 'Service-ref: acme/shop-api@'"),
    ("service-ref: acme/shop-api@main", "malformed Service-ref line 'service-ref: acme/shop-api@main'"),
    ("  Service-Ref : acme/shop-api@main", "malformed Service-ref line '  Service-Ref : acme/shop-api@main'"),
    ("Service-ref: acme/shop-api@-x", "malformed Service-ref line 'Service-ref: acme/shop-api@-x'"),
    ("Service-ref: acme/shop-api@a..b", "malformed Service-ref line 'Service-ref: acme/shop-api@a..b'"),
    ("Service-ref: acme/shop-api@a//b", "malformed Service-ref line 'Service-ref: acme/shop-api@a//b'"),
    ("Service-ref: acme/shop-api@x.lock", "malformed Service-ref line 'Service-ref: acme/shop-api@x.lock'"),
    ("Service-ref: acme/shop-api@x/", "malformed Service-ref line 'Service-ref: acme/shop-api@x/'"),
    ("Service-ref: acme/shop-api@/x", "malformed Service-ref line 'Service-ref: acme/shop-api@/x'"),
    ("Service-ref: acme/shop-api@main\nService-ref: acme/shop-api@main", "2 Service-ref lines (one per PR)"),
    ("text\nService-ref: acme/shop-api@main\nService-ref: other/x@y\n", "2 Service-ref lines (one per PR)"),
])
def test_ac_098_9_a_malformed_or_repeated_marker_fails_with_the_expected_form(gitops, body, reason):
    """AC-098.9: the hint is the expected form; nothing is fetched (not even with a token)."""
    p, fake = with_fake(gitops, body=body)
    assert p.returncode == 1 and p.stdout == ""
    assert f"ERROR: {reason}. {HINT}" in p.lines
    assert fake.requests == []


def test_ac_098_9_a_valid_marker_with_crlf_and_trailing_space_is_accepted(gitops):
    """AC-098.9: the valid form is matched after stripping a trailing \\r and whitespace."""
    p, _ = with_fake(gitops, body="## What\r\n\r\nService-ref: acme/shop-api@feature/x  \r\nrest\r\n")
    assert p.returncode == 0, p.stderr
    assert f"service CRDs from {REF} (commit {SHA[:7]}): Component" in p.lines


def test_ac_098_10_a_marker_without_the_token_fails_with_a_hint_and_fetches_nothing(gitops):
    """AC-098.10: names SERVICE_REPOS_READ_TOKEN and cplat doctor; never skips silently."""
    p, fake = with_fake(gitops, token=None)
    assert p.returncode == 1 and p.stdout == ""
    assert ("ERROR: Service-ref acme/shop-api@feature/x needs the secret SERVICE_REPOS_READ_TOKEN to read acme/shop-api; "
            "add it (run cplat doctor in this repo for how)") in p.lines
    assert fake.requests == []


def test_ac_098_10_an_empty_token_counts_as_missing(gitops):
    """AC-098.10: the secret is empty when it is not set in the repo."""
    p, fake = with_fake(gitops, token="")
    assert p.returncode == 1 and "SERVICE_REPOS_READ_TOKEN" in p.stderr and fake.requests == []


# --- AC-098.11: unreadable repo ---

@pytest.mark.parametrize("code, reason", [
    (401, "HTTP 401 (the token is invalid or expired)"),
    (403, "HTTP 403 (the token may not read this repo, or the rate limit is exhausted)"),
    (404, "HTTP 404 (repository not found, or the token has no access to it)"),
    (418, "HTTP 418"),
])
def test_ac_098_11_a_repo_that_cannot_be_read_fails_naming_repo_and_reason(gitops, code, reason):
    """AC-098.11"""
    p, _ = with_fake(gitops, lambda f: f.status.update({"/repos/acme/shop-api": code}))
    assert p.returncode == 1 and p.stdout == ""
    assert f"ERROR: cannot read acme/shop-api: {reason}" in p.lines
    never_leaks(p)


def test_ac_098_11_a_forbidden_contents_read_also_fails(gitops):
    """AC-098.11: a failure later than the repo lookup is not skipped either."""
    p, _ = with_fake(gitops, lambda f: f.status.update({"/contents/charts/app/crds": 403}))
    assert p.returncode == 1
    assert any(line.startswith("ERROR: cannot read acme/shop-api: HTTP 403") for line in p.lines)


def test_ac_098_11_a_server_error_is_retried_once(gitops):
    """AC-098.11: one retry for 5xx, then HTTP <code>."""
    p, fake = with_fake(gitops, lambda f: f.status.update({"/repos/acme/shop-api": 503}))
    assert p.returncode == 1
    assert "ERROR: cannot read acme/shop-api: HTTP 503" in p.lines
    assert [r for r, _ in fake.requests].count("/repos/acme/shop-api") == 2


def test_ac_098_11_a_network_failure_fails_naming_repo_and_reason(gitops):
    """AC-098.11: a closed port."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    p = run(gitops, url=f"http://127.0.0.1:{port}")
    assert p.returncode == 1 and p.stdout == ""
    assert any(line.startswith("ERROR: cannot read acme/shop-api: network error: ") for line in p.lines)
    never_leaks(p)


# --- AC-098.12: CRDs that cannot become schemas ---

def test_ac_098_12_invalid_yaml_in_a_crd_file_fails_naming_file_and_ref(gitops):
    """AC-098.12"""
    p, _ = with_fake(gitops, lambda f: f.files.update({"charts/app/crds/bad.yaml": "kind: CustomResourceDefinition\nx: [unclosed\n"}))
    assert p.returncode == 1 and p.stdout == ""
    assert any(line.startswith(f"ERROR: {REF}: charts/app/crds/bad.yaml: invalid YAML: ") for line in p.lines)


def test_ac_098_12_a_crd_without_an_openapi_schema_fails(gitops):
    """AC-098.12"""
    bad = {**CRD, "spec": {**CRD["spec"], "versions": [{"name": "v1alpha1", "served": True, "storage": True}]}}
    p, _ = with_fake(gitops, lambda f: f.files.update({"charts/app/crds/component.yaml": dump(bad)}))
    assert p.returncode == 1
    assert f"ERROR: {REF}: charts/app/crds/component.yaml: no openAPIV3Schema for version v1alpha1" in p.lines


def test_ac_098_12_a_templated_crd_fails(gitops):
    """AC-098.12"""
    tpl = "apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\nmetadata:\n  name: {{ .Values.name }}\n"
    p, _ = with_fake(gitops, lambda f: f.files.update({"charts/app/templates/crd.yaml": tpl}))
    assert p.returncode == 1
    assert f"ERROR: {REF}: charts/app/templates/crd.yaml: templated CRD (contains {{{{ }}}}): ship it in crds/" in p.lines


# --- AC-098.13: the token never shows ---

def test_ac_098_13_the_token_is_redacted_everywhere_and_sent_only_to_the_api(gitops):
    """AC-098.13: a CRD whose content echoes the token into the parser message, plus an invalid Component."""
    write(gitops, "applications/shop/web.yaml", component("web", spec={"build": {}}))
    p, fake = with_fake(gitops, lambda f: f.files.update({"charts/app/crds/leak.yaml": f"kind: CustomResourceDefinition\n{TOKEN}: [{TOKEN}\n"}))
    assert p.returncode == 1
    never_leaks(p)
    assert fake.requests and all(auth == f"Bearer {TOKEN}" for _, auth in fake.requests)
    assert all(r.startswith("/repos/acme/shop-api") for r, _ in fake.requests)


def test_ac_098_13_the_token_is_redacted_when_it_appears_in_a_marker_error(gitops):
    """AC-098.13: all output passes through the redaction, also the parse errors of the PR body."""
    p, fake = with_fake(gitops, body=f"Service-ref: {TOKEN}")
    assert p.returncode == 1 and fake.requests == []
    never_leaks(p)
    assert "***" in p.stderr


def test_ac_098_13_the_token_is_redacted_in_a_network_error(gitops):
    """AC-098.13: a closed port with the token in the URL path of the API base."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    p = run(gitops, url=f"http://127.0.0.1:{port}/{TOKEN}")
    assert p.returncode == 1
    never_leaks(p)


# --- AC-098.14 / .17: no marker, nothing changes ---

@pytest.mark.parametrize("body", [None, "", "just a hand-written PR\n\nServicing the ref: no\n", "```\nnot a Service-ref marker?\n```"])
def test_ac_098_14_without_a_marker_the_script_does_nothing_and_needs_no_token(gitops, body):
    """AC-098.14 / AC-098.17: exit 0, empty stdout, nothing fetched, no skip list exported, no token needed."""
    write(gitops, "applications/shop/web.yaml", component("web", spec={"nonsense": 1}))
    if body and "Service-ref" in body:
        body = "no marker here"
    with Fake() as fake:
        p = run(gitops, body=body, token=None, url=fake.url)
    assert p.returncode == 0, p.stderr
    assert p.stdout == "" and p.github_env == ""
    assert "service CRDs: no Service-ref marker; manifests are validated as before" in p.lines
    assert fake.requests == []


def test_ac_098_14_without_a_marker_nothing_is_read_even_with_a_token(gitops):
    """AC-098.14: the token is read only when there is a marker."""
    with Fake() as fake:
        p = run(gitops, body="no marker", token=TOKEN, url=fake.url)
    assert p.returncode == 0 and p.stdout == "" and fake.requests == []
    never_leaks(p)


# --- CI step and recipes (AC-098.10, .13, .14, .15, .17) ---

def ci():
    return yaml.safe_load((TEMPLATE / ".github" / "workflows" / "ci.yml").read_text())


def quality_steps():
    return ci()["jobs"]["quality"]["steps"]


def test_ac_098_14_the_crd_step_runs_only_on_pull_requests_and_before_quality():
    """AC-098.14: if: pull_request; sits between the devbox install and `devbox run quality`."""
    steps = quality_steps()
    idx = [i for i, s in enumerate(steps) if s.get("run") == "devbox run service-crds"]
    assert len(idx) == 1, "the quality job needs one `devbox run service-crds` step"
    step = steps[idx[0]]
    assert step["if"] == "github.event_name == 'pull_request'"
    q = next(i for i, s in enumerate(steps) if s.get("run") == "devbox run quality")
    install = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("jetify-com/devbox-install-action"))
    assert install < idx[0] < q


def test_ac_098_10_the_step_gets_the_body_and_the_token_through_env():
    """AC-098.10 / AC-098.13: PR_BODY and the secret reach the step only as environment variables."""
    step = next(s for s in quality_steps() if s.get("run") == "devbox run service-crds")
    assert step["env"]["PR_BODY"] == "${{ github.event.pull_request.body }}"
    assert step["env"]["SERVICE_REPOS_READ_TOKEN"] == "${{ secrets.SERVICE_REPOS_READ_TOKEN }}"
    assert set(step["env"]) == {"PR_BODY", "SERVICE_REPOS_READ_TOKEN"}
    assert "github.event.pull_request.body" not in step["run"]


def test_ac_098_13_the_token_appears_only_in_the_crd_step():
    """AC-098.13: the quality step (and every other step) never sees the secret."""
    text = (TEMPLATE / ".github" / "workflows" / "ci.yml").read_text()
    assert text.count("secrets.SERVICE_REPOS_READ_TOKEN") == 1
    assert text.count("github.event.pull_request.body") == 1
    q = next(s for s in quality_steps() if s.get("run") == "devbox run quality")
    assert "env" not in q or "SERVICE_REPOS_READ_TOKEN" not in q["env"]


def test_ac_098_15_a_body_edit_runs_ci_again_in_its_own_concurrency_group():
    """AC-098.15: `edited` stays a trigger; edit runs have their own group so they never cancel a push run."""
    wf = ci()
    triggers = wf.get("on", wf.get(True))
    assert "edited" in triggers["pull_request"]["types"]
    assert "'-edited'" in wf["concurrency"]["group"]
    assert wf["jobs"]["quality"]["name"].startswith("quality (")


def test_ac_098_17_triggers_and_job_names_are_unchanged():
    """AC-098.17: push to main, workflow_dispatch and pin-dev's workflow_call run as before."""
    wf = ci()
    triggers = wf.get("on", wf.get(True))
    assert triggers["push"]["branches"] == ["main"] and "workflow_dispatch" in triggers and "workflow_call" in triggers
    assert set(wf["jobs"]) == {"quality", "security", "ci-extra", "pr-title"}  # ci-extra: spec 086
    assert any(s.get("run") == "devbox run quality" for s in quality_steps())


def devbox():
    return json.loads((TEMPLATE / "devbox.json").read_text())["shell"]["scripts"]


def test_ac_098_14_the_devbox_recipe_runs_the_script():
    """AC-098.14: `devbox run service-crds`."""
    assert devbox()["service-crds"] == "uv run scripts/check-service-crds.py"


OLD_ARGS = ["-strict", "-ignore-missing-schemas", "-schema-location", "default", "-schema-location",
            "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json",
            "-summary", "x.yaml"]


def kubeconform_args(tmp_path, skip):
    m = re.search(r"kubeconform -strict.*?-summary \"\$f\"", devbox()["validate"])
    assert m, "validate no longer calls kubeconform with -strict ... -summary"
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    fake = bin_ / "kubeconform"
    fake.write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done\n')
    fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "SERVICE_CRD_SKIP"}
    env["PATH"] = f"{bin_}:{env['PATH']}"
    if skip is not None:
        env["SERVICE_CRD_SKIP"] = skip
    out = subprocess.run(["sh", "-c", f'f=x.yaml; {m.group(0)}'], env=env, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def test_ac_098_17_without_a_skip_list_kubeconform_gets_the_previous_arguments(tmp_path):
    """AC-098.17 / AC-098.14: SERVICE_CRD_SKIP unset gives the argument list from before this spec."""
    assert kubeconform_args(tmp_path, None) == OLD_ARGS
    assert kubeconform_args(tmp_path, "") == OLD_ARGS


def test_ac_098_3_the_skip_list_reaches_kubeconform_as_one_skip_argument(tmp_path):
    """AC-098.3: the catalog schema is replaced for the service CRD kinds by `-skip`."""
    skip = "example.io/v1alpha1/Component,example.io/v1alpha1/Pipeline"
    args = kubeconform_args(tmp_path, skip)
    assert args[args.index("-skip") + 1] == skip
    assert [a for i, a in enumerate(args) if a != "-skip" and not (i and args[i - 1] == "-skip")] == OLD_ARGS
    assert args.index("-ignore-missing-schemas") < args.index("-skip") < args.index("-schema-location")


def test_ac_098_17_the_rest_of_validate_is_unchanged():
    """AC-098.17: the other validate steps and recipes still exist."""
    v = devbox()["validate"]
    for part in ("render.py --check", "plan.py validate", "check-k8s-labels.py", "kustomize build", "check-policies.sh"):
        assert part in v
    assert devbox()["quality"] == "devbox run validate"
