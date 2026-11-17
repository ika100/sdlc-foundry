"""Spec 110 acceptance test, AC-110.9: the gitops-app job `contract-pins` (templates/gitops-app/scripts/check-contract-pins.py,
design 6) compares the copy of the rules at the commit a PR pins with the plan's current contract. Fully offline: the GitHub API is
a fake HTTP server on 127.0.0.1 (as in spec 098's tests) and the gitops-app repo is a real git repo with a base and a pin commit."""
import base64
import copy
import http.server
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
from pathlib import Path

import pytest
import yaml
from support_110 import ROOT, commit_all, copy_doc, git, plan_file, plan_text, world

SCRIPT = ROOT / "templates" / "gitops-app" / "scripts" / "check-contract-pins.py"
TOKEN = "ghp_SecretTokenValue0123456789abcdef"  # pragma: allowlist secret
OLD, NEW = "a" * 40, "b" * 40
SHA7 = "bbbbbbb"
PINNED_API = f"acme/todo-api@{SHA7}"
PINNED_WEB = f"acme/todo-web@{SHA7}"


class Fake:
    """A GitHub API fake: /repos/<slug>/contents/<path>?ref=<ref> from {(slug, ref): {path: text}}."""

    def __init__(self):
        self.files: dict[tuple[str, str], dict[str, str]] = {}
        self.requests: list[tuple[str, str]] = []

    def serve(self, slug, ref, doc):
        self.files[(slug, ref)] = {f"contract/{doc['plan_id']}.json": json.dumps(doc, sort_keys=True, indent=2) + "\n"}

    def handle(self, raw):
        parsed = urllib.parse.urlparse(raw)
        m = re.match(r"/repos/([^/]+/[^/]+)/contents/(.+)", urllib.parse.unquote(parsed.path))
        ref = urllib.parse.parse_qs(parsed.query).get("ref", [""])[0]
        if m:
            files = self.files.get((m.group(1), ref)) or next((f for (s, r), f in self.files.items() if s == m.group(1) and r[:7] == ref[:7]), None)
            if files is not None and m.group(2) in files:
                text = files[m.group(2)]
                return 200, {"type": "file", "path": m.group(2), "encoding": "base64", "size": len(text),
                             "content": base64.encodebytes(text.encode()).decode()}
        return 404, {"message": "Not Found"}

    def __enter__(self):
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
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

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


def overlay(root, component, tag):
    d = root / "applications" / "shop" / "overlays" / "dev" / component
    d.mkdir(parents=True, exist_ok=True)
    (d / "kustomization.yaml").write_text(yaml.safe_dump({"resources": ["deployment.yaml"],
                                                          "images": [{"name": f"ghcr.io/acme/{component}", "newTag": tag}]}))


@pytest.fixture()
def gitops(tmp_path):
    """The base on `main` pins every component at OLD; the checkout is on a branch with no change yet."""
    root = world(tmp_path)
    (root / "scripts" / "check-contract-pins.py").parent.mkdir(exist_ok=True)
    if SCRIPT.is_file():
        shutil.copy(SCRIPT, root / "scripts" / "check-contract-pins.py")
    components = {name: {"type": "service", "lang": "python", "repo": f"acme/{name}"} for name in ("todo-api", "todo-web", "todo-docs")}
    (root / "applications" / "shop").mkdir(parents=True)
    (root / "applications" / "shop" / "system.yaml").write_text(yaml.safe_dump(
        {"system": "shop", "owner": "acme", "environments": {"dev": {}, "staging": {}, "prod": {}}, "components": components}))
    for name in components:
        overlay(root, name, f"sha-{OLD}")
    commit_all(root, "base")
    git(root, "checkout", "-q", "-b", "pin")
    return root


def pin(root, component, tag=f"sha-{NEW}"):
    overlay(root, component, tag)
    commit_all(root, f"pin {component}")


def run(root, fake, *, token=TOKEN):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "SERVICE_REPOS", "BASE_REF"))}
    env.update(BASE_REF="main", GITHUB_API_URL=fake.url, GITHUB_STEP_SUMMARY=str(root.parent / "summary.md"))
    if token is not None:
        env["SERVICE_REPOS_READ_TOKEN"] = token
    assert SCRIPT.is_file(), "missing template file: templates/gitops-app/scripts/check-contract-pins.py"
    proc = subprocess.run(["uv", "run", "scripts/check-contract-pins.py"], cwd=root, env=env, capture_output=True, text=True, timeout=180)
    proc.lines = (proc.stdout + proc.stderr).splitlines()
    return proc


def errors(proc):
    return [ln for ln in proc.lines if ln.startswith("ERROR:")]


def rule_of(doc, rule_id):
    return next(r for r in doc["rules"] if r["id"] == rule_id)


def test_a_pinned_copy_that_matches_the_plan_passes_ac_110_9(gitops):  # AC-110.9
    pin(gitops, "todo-api")
    with Fake() as fake:
        fake.serve("acme/todo-api", NEW, copy_doc("todo-api", "provider"))
        proc = run(gitops, fake)
    assert proc.returncode == 0, proc.lines
    assert f"contract pins: todo-api@{SHA7} matches plan 003-todos (3 rules)" in proc.lines
    assert not errors(proc)
    assert any(path.startswith("/repos/acme/todo-api/contents/contract/003-todos.json") and f"ref={NEW}" in path
               for path, _ in fake.requests)
    assert all(TOKEN in auth for _, auth in fake.requests)                  # the read token is sent
    assert all(TOKEN not in ln for ln in proc.lines)                        # and never printed


def test_a_copy_with_another_value_fails_naming_service_rule_and_both_values_ac_110_9(gitops):  # AC-110.9
    pin(gitops, "todo-api")
    doc = copy_doc("todo-api", "provider")
    rule_of(doc, "title-max")["value"] = 120
    with Fake() as fake:
        fake.serve("acme/todo-api", NEW, doc)
        proc = run(gitops, fake)
    assert proc.returncode == 1
    assert errors(proc) == [f"ERROR: todo-api: plan 003-todos rule title-max: plan value=200, pinned {PINNED_API} value=120"], proc.lines


def test_the_consumer_copy_is_checked_too_ac_110_9(gitops):  # AC-110.9
    pin(gitops, "todo-web")
    doc = copy_doc("todo-web", "consumer")
    rule_of(doc, "status-values")["value"] = ["open", "done", "archived"]
    rule_of(doc, "title-required")["status"] = 400
    with Fake() as fake:
        fake.serve("acme/todo-web", NEW, doc)
        proc = run(gitops, fake)
    assert proc.returncode == 1
    assert sorted(errors(proc)) == [
        f'ERROR: todo-web: plan 003-todos rule status-values: plan value=["open", "done"], pinned {PINNED_WEB} value=["open", "done", "archived"]',
        f"ERROR: todo-web: plan 003-todos rule title-required: plan status=422, pinned {PINNED_WEB} status=400"], proc.lines


def test_a_difference_in_the_error_contract_fails_ac_110_9(gitops):  # AC-110.9
    pin(gitops, "todo-api")
    doc = copy_doc("todo-api", "provider")
    doc["errors"]["status"] = 400
    doc["errors"]["unlisted"]["message"] = "Oops"
    with Fake() as fake:
        fake.serve("acme/todo-api", NEW, doc)
        proc = run(gitops, fake)
    assert proc.returncode == 1
    lines = errors(proc)
    assert any(re.fullmatch(rf"ERROR: todo-api: plan 003-todos rule errors: plan (errors\.)?status=422, pinned {PINNED_API} "
                            r"(errors\.)?status=400", ln) for ln in lines), lines
    assert any(ln.startswith("ERROR: todo-api: plan 003-todos rule errors: ") and "Something went wrong. Please try again." in ln
               and '"Oops"' in ln for ln in lines), lines


def test_a_rule_missing_from_or_only_in_the_copy_fails_ac_110_9(gitops):  # AC-110.9
    pin(gitops, "todo-api")
    doc = copy_doc("todo-api", "provider")
    doc["rules"] = [r for r in doc["rules"] if r["id"] != "status-values"]
    extra = copy.deepcopy(rule_of(doc, "title-max"))
    extra["id"] = "extra-rule"
    doc["rules"].append(extra)
    with Fake() as fake:
        fake.serve("acme/todo-api", NEW, doc)
        proc = run(gitops, fake)
    assert proc.returncode == 1
    lines = errors(proc)
    assert any(ln.startswith("ERROR: todo-api: plan 003-todos rule status-values: plan ") and f"pinned {PINNED_API} " in ln
               and "(missing)" in ln for ln in lines), lines
    assert any(ln.startswith("ERROR: todo-api: plan 003-todos rule extra-rule: plan (none)") and f"pinned {PINNED_API} " in ln
               for ln in lines), lines


def test_a_repo_with_no_copy_fails_when_the_plan_assigns_it_a_rule_ac_110_9(gitops):  # AC-110.9
    pin(gitops, "todo-api")
    with Fake() as fake:                                                    # the repo has no contract/003-todos.json
        proc = run(gitops, fake)
    assert proc.returncode == 1
    (line,) = errors(proc)
    assert line.startswith("ERROR: todo-api: plan 003-todos assigns it rule(s) ")
    assert all(rule in line for rule in ("status-values", "title-max", "title-required"))
    assert line.endswith(f", but {PINNED_API} has no contract/003-todos.json: run /component:spec --from-plan "
                         "docs/plan/003-todos.md todo-api in acme/todo-api")


def test_a_repo_in_no_rule_is_not_checked_ac_110_9(gitops):  # AC-110.9
    pin(gitops, "todo-docs")
    with Fake() as fake:
        proc = run(gitops, fake, token=None)                                # not even the secret is needed
    assert proc.returncode == 0, proc.lines
    assert "contract pins: todo-docs takes part in no rule: not checked" in proc.lines
    assert fake.requests == []


def test_an_abandoned_plan_assigns_no_rules_ac_110_9(gitops):  # AC-110.9
    plan_file(gitops).write_text(plan_text(status="abandoned"))
    commit_all(gitops, "abandon the plan")
    pin(gitops, "todo-api")
    with Fake() as fake:
        proc = run(gitops, fake)
    assert proc.returncode == 0, proc.lines
    assert "contract pins: todo-api takes part in no rule: not checked" in proc.lines


def test_a_release_tag_is_read_at_the_git_tag_of_the_version_ac_110_9(gitops):  # AC-110.9
    pin(gitops, "todo-api", tag="1.2.3")
    doc = copy_doc("todo-api", "provider")
    rule_of(doc, "title-max")["value"] = 120
    with Fake() as fake:
        fake.serve("acme/todo-api", "v1.2.3", doc)
        proc = run(gitops, fake)
    assert proc.returncode == 1
    assert any(ln.startswith("ERROR: todo-api: plan 003-todos rule title-max: plan value=200, pinned acme/todo-api@")
               and ln.endswith("value=120") for ln in errors(proc)), proc.lines
    assert any("ref=v1.2.3" in path for path, _ in fake.requests)


def test_a_pr_that_changes_no_pin_has_nothing_to_check_ac_110_9(gitops):  # AC-110.9
    with Fake() as fake:
        proc = run(gitops, fake)
    assert proc.returncode == 0, proc.lines
    assert "contract pins: no component pin changed: nothing to check" in proc.lines


def test_a_checked_repo_needs_the_read_token_ac_110_9(gitops):  # AC-110.9
    pin(gitops, "todo-api")
    with Fake() as fake:
        proc = run(gitops, fake, token=None)
    assert proc.returncode == 1
    assert errors(proc) == ["ERROR: contract pins: todo-api needs the secret SERVICE_REPOS_READ_TOKEN to read acme/todo-api; "
                            "add it (run cplat doctor in this repo for how)"]


def test_the_job_is_wired_into_the_gitops_app_ci_ac_110_9():  # AC-110.9
    template = ROOT / "templates" / "gitops-app"
    devbox = json.loads((template / "devbox.json").read_text())["shell"]["scripts"]
    assert devbox.get("contract-pins") == "uv run scripts/check-contract-pins.py"
    workflow = yaml.safe_load((template / ".github" / "workflows" / "ci.yml").read_text())
    job = workflow["jobs"]["contract-pins"]
    steps = json.dumps(job)
    assert "devbox run contract-pins" in steps and "BASE_REF" in steps and "SERVICE_REPOS_READ_TOKEN" in steps
    assert next((s["with"]["fetch-depth"] for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")), None) == 0
