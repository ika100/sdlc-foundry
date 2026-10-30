"""compose + promote against a real rendered gitops-app repo with `gh` faked."""
import base64
import copy
import json
import subprocess

import pytest
import yaml

import compose
import core
import promote

JAVA_ANSWERS = "_src_path: gh:ika100/sdlc-foundry/templates/service-java\nport: 8080\n"
WEB_ANSWERS = "_src_path: gh:ika100/sdlc-foundry/templates/web-nextjs\nport: 3000\n"
OLD_K8S = """
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: app
          ports: [{containerPort: 3000}]
          env: [{name: PORT, value: "3000"}, {name: API_URL, value: "http://todo-api"}]
          livenessProbe: {httpGet: {path: /api/health, port: http}}
          readinessProbe: {httpGet: {path: /api/ready, port: http}}
          resources: {requests: {cpu: 10m, memory: 10Mi}}
"""
SHA = "a" * 40


@pytest.fixture()
def gitops_repo(tmp_path, new_service):
    return new_service(["todo-gitops", "d", "--shape", "gitops-app", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])


def composed_todo_api(tmp_path, new_service, shared_renders):
    """Spec 112: a gitops repo with `compose add todo-api` committed, rendered once per process and copied per test."""
    def build(workdir):
        repo = new_service(["todo-gitops", "d", "--shape", "gitops-app", "--no-github", "--skip-tasks", "--dir", str(workdir), "--org", "acme"])
        with pytest.MonkeyPatch.context() as mp:
            fake = FakeGh()
            mp.setattr(compose, "gh", fake)
            mp.setattr(promote, "gh", fake)
            run_compose(repo, "add", "todo-api")
        commit(repo, "service")
        return repo

    return shared_renders.copy("gitops todo-gitops + compose add todo-api", build, tmp_path / "todo-gitops")


class FakeGh:
    """Canned GitHub: repos with topics/answers/files, GHCR tags, git tags."""

    def __init__(self):
        self.topics = {"acme/todo-api": ["deployable-service"], "acme/todo-web": ["deployable-service"], "acme/nodeploy": []}
        self.files = {("acme/todo-api", ".copier-answers.yml"): JAVA_ANSWERS, ("acme/todo-web", ".copier-answers.yml"): WEB_ANSWERS,
                      ("acme/todo-web", "k8s/base/deployment.yaml"): OLD_K8S}
        self.image_tags = {"todo-api": {"latest", "sha-" + SHA[:7], "1.2.0", "1.3.0"}, "todo-web": {"latest", "sha-" + SHA[:7]}}
        self.git_tags = {"acme/todo-api": ["v1.3.1", "v1.3.0", "v1.2.0", "not-semver"], "acme/todo-web": []}

    def __call__(self, args):
        if args[:2] == ["repo", "view"]:
            slug = args[2]
            if slug not in self.topics:
                raise core.PlatformError("not found")
            return json.dumps({"repositoryTopics": [{"name": t} for t in self.topics[slug]]})
        if args[0] == "api":
            path = args[1].split("?")[0].lstrip("/")
            if path.startswith("repos/") and "/contents/" in path:
                slug, f = path[len("repos/"):].split("/contents/")
                if (slug, f) not in self.files:
                    raise core.PlatformError("404")
                return base64.b64encode(self.files[(slug, f)].encode()).decode()
            if path.endswith("/commits/main"):
                return SHA + "\n"
            if path.endswith("/tags"):
                return json.dumps(self.git_tags[path[len("repos/"):-len("/tags")]])
            if "/packages/container/" in path:
                pkg = path.split("/packages/container/")[1].split("/")[0]
                return json.dumps(sorted(self.image_tags.get(pkg, [])))
        raise AssertionError(f"unexpected gh call {args}")


@pytest.fixture()
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(compose, "gh", fake)
    monkeypatch.setattr(promote, "gh", fake)
    return fake


def matching_registry(monkeypatch, fake):
    """Spec 106: every tag the fake GHCR knows (and the full-sha staging build) is one image, so prod promotions find matching digests."""
    import registry
    tags = sorted(set().union(*fake.image_tags.values()) | {"sha-" + SHA})
    version = [{"name": "sha256:" + "1" * 64, "metadata": {"container": {"tags": tags}}}]
    monkeypatch.setattr(registry, "gh", lambda args: json.dumps(version))


def system_file(repo):
    return repo / "applications/todo/system.yaml"


def components(repo) -> dict:
    """The `components` of the repo's system.yaml (5.0: the one input file)."""
    return yaml.safe_load(system_file(repo).read_text()).get("components") or {}


def run_compose(repo, *args):
    return compose.main([*args, "--repo-dir", str(repo)])


def render_check(repo):
    return subprocess.run(["uv", "run", "scripts/render.py", "--check"], cwd=repo, capture_output=True, text=True)


def commit(repo, msg="x"):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg], cwd=repo, check=True)


# ---------------- compose ----------------

def test_add_writes_a_complete_explicit_entry_and_renders(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api")
    s = components(gitops_repo)["todo-api"]
    assert (s["type"], s["lang"]) == ("service", "java") and s["image"] == "ghcr.io/acme/todo-api"
    assert s["port"] == 8080 and s["user"] == 65532 and list(s["instances"]) == ["dev"]
    assert s["probes"]["readiness"] == "/actuator/health/readiness"
    dev = gitops_repo / "applications/todo/overlays/dev/todo-api"
    assert {p.name for p in dev.iterdir()} == {"deployment.yaml", "service.yaml", "kustomization.yaml"}
    assert not (gitops_repo / "applications/todo/overlays/staging/todo-api").exists()   # new services start in dev only
    assert render_check(gitops_repo).returncode == 0


def test_system_yaml_comments_survive(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api")
    text = system_file(gitops_repo).read_text()
    assert "# components: add with `/component:new`" in text and "# The todo system (read by scripts/render.py)" in text


def test_env_wiring_and_expose(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-web", "--env", "API_URL=http://todo-api", "--expose", "web", "--replicas", "2")
    s = components(gitops_repo)["todo-web"]
    assert s["env"]["API_URL"] == "http://todo-api" and s["env"]["NODE_ENV"] == "production" and s["replicas"] == 2
    assert s["expose"] == {"host": "web"} and s["port"] == 3000
    route = yaml.safe_load((gitops_repo / "applications/todo/overlays/dev/todo-web/httproute.yaml").read_text())
    assert route["spec"]["hostnames"] == ["web.todo-dev.localhost"]


def test_from_k8s_seeds_a_v1_service(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-web", "--from-k8s")
    s = components(gitops_repo)["todo-web"]
    assert s["env"]["API_URL"] == "http://todo-api" and s["replicas"] == 2 and "PORT" not in s["env"]


@pytest.mark.parametrize("args,msg", [
    (["add", "missing"], "not found"),
    (["add", "nodeploy"], "deployable-service"),
])
def test_add_rejects_bad_repos(gitops_repo, gh, args, msg):
    with pytest.raises(core.PlatformError, match=msg):
        run_compose(gitops_repo, *args)


def test_duplicate_and_unknown_removal(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api")
    commit(gitops_repo)
    with pytest.raises(core.PlatformError, match="already in"):
        run_compose(gitops_repo, "add", "todo-api")
    with pytest.raises(core.PlatformError, match="not in system.yaml"):
        run_compose(gitops_repo, "remove", "ghost")


def test_remove_prunes_generated_files(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api")
    commit(gitops_repo)
    run_compose(gitops_repo, "remove", "todo-api")
    assert not components(gitops_repo)
    assert not (gitops_repo / "applications/todo/overlays/dev/todo-api").exists()


def test_dry_run_changes_nothing(gitops_repo, gh):
    before = system_file(gitops_repo).read_text()
    run_compose(gitops_repo, "add", "todo-api", "--dry-run")
    assert system_file(gitops_repo).read_text() == before


# ---------------- promote ----------------

def composed(repo, *args):
    run_compose(repo, "add", *args)
    commit(repo, "compose")


def pin(repo, env, svc):
    k = yaml.safe_load((repo / f"applications/todo/overlays/{env}/{svc}/kustomization.yaml").read_text())
    return k["images"][0]["newTag"]


def test_promote_to_staging_pins_sha_tag_and_adds_the_environment(gitops_repo, gh):
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "--to", "staging", "--repo-dir", str(gitops_repo)])
    assert pin(gitops_repo, "staging", "todo-api") == "sha-" + SHA[:7]       # image tag only; no git ref anywhere
    assert list(components(gitops_repo)["todo-api"]["instances"]) == ["dev", "staging"]
    assert render_check(gitops_repo).returncode == 0                         # the pin survives a re-render


def test_promote_refuses_an_image_that_does_not_exist(gitops_repo, gh):
    composed(gitops_repo, "todo-web")
    with pytest.raises(core.PlatformError, match="does not exist yet"):
        promote.main(["todo-web", "--to", "staging", "--sha", "b" * 40, "--repo-dir", str(gitops_repo)])


def test_prod_pins_release_without_v_and_picks_newest_with_an_image(gitops_repo, gh, monkeypatch):
    matching_registry(monkeypatch, gh)
    gh.image_tags["todo-api"].add("sha-" + SHA)
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "--to", "staging", "--repo-dir", str(gitops_repo)])
    commit(gitops_repo, "promote")
    promote.main(["todo-api", "--to", "prod", "--repo-dir", str(gitops_repo)])
    # v1.3.1 has no image yet, so v1.3.0 wins; the pinned tag is 1.3.0 (CI publishes X.Y.Z, not vX.Y.Z)
    assert pin(gitops_repo, "prod", "todo-api") == "1.3.0"


def test_prod_with_explicit_version(gitops_repo, gh, monkeypatch):
    matching_registry(monkeypatch, gh)
    gh.image_tags["todo-api"].add("sha-" + SHA)
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "--to", "staging", "--repo-dir", str(gitops_repo)])
    commit(gitops_repo, "promote")
    promote.main(["todo-api", "--to", "prod", "--version", "v1.2.0", "--repo-dir", str(gitops_repo)])
    assert pin(gitops_repo, "prod", "todo-api") == "1.2.0"


@pytest.mark.parametrize("argv,msg", [      # 5.0: the source environment is the one before --to, so a move backwards cannot be named
    (["todo-api", "--to", "dev"], "nothing is promoted to it"),
    (["todo-api", "--to", "mars"], "unknown environment"),
    (["todo-api", "--to", "prod"], "has no instance in staging"),
    (["ghost", "--to", "staging"], "is not a component of"),
])
def test_promote_rejects_invalid_moves(gitops_repo, gh, argv, msg):
    composed(gitops_repo, "todo-api")
    with pytest.raises(core.PlatformError, match=msg):
        promote.main([*argv, "--repo-dir", str(gitops_repo)])


def test_promote_all_moves_every_service_in_the_source_env(gitops_repo, gh):
    composed(gitops_repo, "todo-api")
    composed(gitops_repo, "todo-web")
    promote.main(["--all", "--to", "staging", "--repo-dir", str(gitops_repo)])
    assert pin(gitops_repo, "staging", "todo-api").startswith("sha-") and pin(gitops_repo, "staging", "todo-web").startswith("sha-")


HALF_WEB = {"type": "website", "lang": "typescript", "repo": "acme/todo-web", "instances": {"dev": {}, "staging": {}}}


def write_components(repo, comps: dict) -> None:
    doc = yaml.safe_load(system_file(repo).read_text())
    doc["components"] = comps
    system_file(repo).write_text(yaml.safe_dump(doc, sort_keys=False))


def test_a_half_written_entry_is_completed_in_place_keeping_environments_and_pins(gitops_repo, gh):
    """5.0 form of the v1 migration: an entry without port and probes (what a running v1 product looks like) is completed by
    `component add --from-k8s`, keeping its instances and image pins."""
    app = gitops_repo / "applications/todo"
    write_components(gitops_repo, {"todo-web": HALF_WEB})
    for env, tag in (("dev", "latest"), ("staging", "sha-1234567")):
        d = app / "overlays" / env / "todo-web"
        d.mkdir(parents=True)
        (d / "kustomization.yaml").write_text(
            "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n- https://github.com/acme/todo-web//k8s/base?ref=main\n"
            f"images:\n- name: ghcr.io/acme/todo-web\n  newTag: {tag}\n")
    commit(gitops_repo, "v1 product")
    r = subprocess.run(["uv", "run", "scripts/render.py"], cwd=gitops_repo, capture_output=True, text=True)
    assert r.returncode == 1 and "components.todo-web" in r.stderr          # the incomplete entry is rejected
    run_compose(gitops_repo, "add", "todo-web", "--from-k8s")
    s = components(gitops_repo)["todo-web"]
    assert list(s["instances"]) == ["dev", "staging"] and s["env"]["API_URL"] == "http://todo-api" and "path" not in s
    assert pin(gitops_repo, "staging", "todo-web") == "sha-1234567"             # pins survive the completion
    assert not (app / "overlays/prod/todo-web").exists()
    assert (app / "overlays/dev/todo-web/deployment.yaml").is_file()


def test_status_table_reads_pins_ci_and_argo(gitops_repo, gh, monkeypatch):
    import status
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "--to", "staging", "--repo-dir", str(gitops_repo)])
    answers = {
        ("gh", "run"): "completed success",
        ("kubectl", "--context"): json.dumps({"items": [{"metadata": {"name": "todo-api-dev"}, "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}}]}),
    }
    monkeypatch.setattr(status, "sh", lambda cmd: answers.get((cmd[0], cmd[1])))
    app, envs, rows, resources = status.collect(gitops_repo, None, "k3d-x")
    cells = {r["component"]: r["cells"] for r in rows}["todo-api"]       # 5.0: one row per component, one cell per environment
    assert cells["dev"]["tag"] == "latest" and cells["dev"]["argo"] == "Synced/Healthy"
    assert cells["staging"]["tag"].startswith("sha-") and cells["staging"]["argo"] == "missing"
    assert cells["dev"]["ci"] == "ok"
    assert cells["prod"] is None
    table = status.render_table(app, envs, rows, resources, {"platform": "2.0.0"}, "k3d-x")
    assert "todo-api" in table and "Synced/Healthy" in table


def test_status_degrades_when_tools_are_missing(gitops_repo, gh, monkeypatch):
    import status
    composed(gitops_repo, "todo-api")
    monkeypatch.setattr(status, "sh", lambda cmd: None)
    _, _, rows, _ = status.collect(gitops_repo, None, None)
    assert rows[0]["cells"]["dev"]["ci"] == "?" and rows[0]["cells"]["dev"]["argo"] == "-"


# ---------------- secrets (ESO, ADR-018) ----------------

def dev_dir(repo, svc="todo-api"):
    return repo / "applications/todo/overlays/dev" / svc


def test_generate_and_remote_secrets_render_externalsecrets_and_envfrom(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api", "--generate", "todo-api-auth=DB_PASSWORD,JWT_KEY", "--secret", "todo-api-stripe=STRIPE_KEY")
    d = dev_dir(gitops_repo)
    assert not (d / "externalsecret-todo-api-auth.yaml").exists() and not (d / "password-generator.yaml").exists()   # spec 128
    files = ["credentials-configmap.yaml", "credentials-job.yaml", "credentials-role.yaml", "credentials-rolebinding.yaml", "credentials-serviceaccount.yaml"]
    assert all((d / f).is_file() for f in files)
    plan = json.loads(yaml.safe_load((d / "credentials-configmap.yaml").read_text())["data"]["plan.json"])
    assert plan["secrets"] == [{"name": "todo-api-auth", "generate": {"DB_PASSWORD": 32, "JWT_KEY": 32}, "data": {},
                                "labels": yaml.safe_load((d / "credentials-job.yaml").read_text())["metadata"]["labels"]}]
    rem = yaml.safe_load((d / "externalsecret-todo-api-stripe.yaml").read_text())
    assert rem["spec"]["secretStoreRef"] == {"name": "platform-secrets", "kind": "ClusterSecretStore"}
    assert rem["spec"]["data"] == [{"secretKey": "STRIPE_KEY", "remoteRef": {"key": "todo-dev-todo-api-stripe", "property": "STRIPE_KEY"}}]
    dep = yaml.safe_load((d / "deployment.yaml").read_text())
    assert [e["secretRef"]["name"] for e in dep["spec"]["template"]["spec"]["containers"][0]["envFrom"]] == ["todo-api-auth", "todo-api-stripe"]
    kust = yaml.safe_load((d / "kustomization.yaml").read_text())
    assert set(files) <= set(kust["resources"]) and "externalsecret-todo-api-stripe.yaml" in kust["resources"]
    assert "externalsecret-todo-api-auth.yaml" not in kust["resources"] and "password-generator.yaml" not in kust["resources"]
    assert render_check(gitops_repo).returncode == 0


def test_no_secrets_means_no_extra_files(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api")
    assert {p.name for p in dev_dir(gitops_repo).iterdir()} == {"deployment.yaml", "service.yaml", "kustomization.yaml"}


def test_removed_secret_files_are_pruned(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api", "--generate", "todo-api-auth=DB_PASSWORD")
    commit(gitops_repo)
    f = system_file(gitops_repo)
    data = yaml.safe_load(f.read_text())
    del data["components"]["todo-api"]["secrets"]
    f.write_text(yaml.safe_dump(data, sort_keys=False))
    subprocess.run(["uv", "run", "scripts/render.py"], cwd=gitops_repo, check=True, capture_output=True)
    assert not list(dev_dir(gitops_repo).glob("externalsecret-*")) and not (dev_dir(gitops_repo) / "password-generator.yaml").exists()
    assert not list(dev_dir(gitops_repo).glob("credentials-*"))   # spec 128


@pytest.mark.parametrize("secret,msg", [
    ({"name": "x", "generate": ["A"], "remote": {"keys": ["B"]}}, "exactly one of"),
    ({"name": "x"}, "exactly one of"),
    ({"name": "Bad_Name", "generate": ["A"]}, "DNS label"),
    ({"name": "x", "generate": ["1BAD"]}, "environment variable name"),
])
def test_invalid_secret_declarations_are_rejected(gitops_repo, gh, secret, msg):
    run_compose(gitops_repo, "add", "todo-api")
    f = system_file(gitops_repo)
    data = yaml.safe_load(f.read_text())
    data["components"]["todo-api"]["secrets"] = [secret]
    f.write_text(yaml.safe_dump(data, sort_keys=False))
    p = subprocess.run(["uv", "run", "scripts/render.py"], cwd=gitops_repo, capture_output=True, text=True)
    assert p.returncode == 1 and msg in p.stderr


def test_literal_secret_in_env_is_rejected(gitops_repo, gh):
    p_before = run_compose(gitops_repo, "add", "todo-api")
    assert p_before == 0
    f = system_file(gitops_repo)
    data = yaml.safe_load(f.read_text())
    data["components"]["todo-api"]["env"]["DB_PASSWORD"] = "hunter2"
    f.write_text(yaml.safe_dump(data, sort_keys=False))
    p = subprocess.run(["uv", "run", "scripts/render.py"], cwd=gitops_repo, capture_output=True, text=True)
    assert p.returncode == 1 and "looks like a secret" in p.stderr and "generate: [DB_PASSWORD]" in p.stderr


def test_secret_flags_need_a_single_service_and_valid_syntax(gitops_repo, gh):
    with pytest.raises(core.PlatformError, match="exactly one component"):
        run_compose(gitops_repo, "add", "todo-api", "todo-web", "--generate", "a=B")
    with pytest.raises(core.PlatformError, match="SECRET=KEY"):
        run_compose(gitops_repo, "add", "todo-api", "--generate", "nokeys")


class FakeKubectl:
    def __init__(self):
        self.secrets: dict[str, dict] = {}
        self.calls: list[list[str]] = []

    def __call__(self, args, input_text=None):
        self.calls.append(args)
        a = [x for x in args if x not in ("--context",)]
        if "get" in a:
            name = a[a.index("secret") + 1]
            if name not in self.secrets:
                raise core.PlatformError("NotFound")
            return json.dumps({"data": {k: "x" for k in self.secrets[name]}})
        if "create" in a:
            self.secrets[a[a.index("generic") + 1]] = {}
            return ""
        if "patch" in a:
            name = a[a.index("secret") + 1]
            self.secrets[name].update(json.loads(input_text)["stringData"])
            return ""
        raise AssertionError(args)


def test_secret_set_and_list(gitops_repo, gh, monkeypatch, capsys):
    import secret
    run_compose(gitops_repo, "add", "todo-api", "--generate", "todo-api-auth=DB_PASSWORD", "--secret", "todo-api-stripe=STRIPE_KEY")
    k = FakeKubectl()
    monkeypatch.setattr(secret, "kubectl", k)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("sk_test_1\n"))
    base = ["--repo-dir", str(gitops_repo)]
    assert secret.main(["list", *base]) == 0
    assert "STRIPE_KEY: MISSING" in capsys.readouterr().out
    assert secret.main(["set", "todo-api/dev", "todo-api-stripe", "STRIPE_KEY", "--value-stdin", *base]) == 0
    assert k.secrets["todo-dev-todo-api-stripe"] == {"STRIPE_KEY": "sk_test_1"}
    out = capsys.readouterr().out
    assert "sk_test_1" not in out
    assert secret.main(["list", *base]) == 0
    out = capsys.readouterr().out
    assert "STRIPE_KEY: set" in out and "generated by External Secrets Operator" in out
    assert not any("sk_test_1" in " ".join(c) for c in k.calls)   # never on a command line
    with pytest.raises(core.PlatformError, match="has no remote secret 'todo-api-auth'"):       # 5.0: a generated secret has nothing to set
        secret.main(["set", "todo-api/dev", "todo-api-auth", "DB_PASSWORD", "--value-stdin", *base])


def test_secret_ref_exposes_another_services_generated_secret(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api", "--generate", "todo-api-auth=API_KEY")
    commit(gitops_repo)
    run_compose(gitops_repo, "add", "todo-web", "--secret-ref", "todo-api-auth")
    web = components(gitops_repo)["todo-web"]
    assert web["secretRefs"] == ["todo-api-auth"]
    dep = yaml.safe_load((gitops_repo / "applications/todo/overlays/dev/todo-web/deployment.yaml").read_text())
    assert dep["spec"]["template"]["spec"]["containers"][0]["envFrom"] == [{"secretRef": {"name": "todo-api-auth"}}]
    assert render_check(gitops_repo).returncode == 0


def test_secret_ref_rejects_bad_names_and_multiple_services(gitops_repo, gh):
    with pytest.raises(core.PlatformError, match="not a valid Secret name"):
        run_compose(gitops_repo, "add", "todo-api", "--secret-ref", "Bad_Name")
    with pytest.raises(core.PlatformError, match="exactly one component"):
        run_compose(gitops_repo, "add", "todo-api", "todo-web", "--secret-ref", "x")


# ---------------- spec 045: `compose set` changes a service that is already composed ----------------

def test_set_adds_env_and_exposure_to_an_existing_service(gitops_repo, gh):
    """AC-045.1: the gitops entry of a product plan wires services that already run."""
    run_compose(gitops_repo, "add", "todo-web")
    commit(gitops_repo)
    assert run_compose(gitops_repo, "set", "todo-web", "--env", "TODO_API_URL=http://todo-api", "--expose", "todo-web") == 0
    s = components(gitops_repo)["todo-web"]
    assert s["env"]["TODO_API_URL"] == "http://todo-api" and s["env"]["NODE_ENV"] == "production"   # merged, not replaced
    assert s["expose"] == {"host": "todo-web"}
    route = yaml.safe_load((gitops_repo / "applications/todo/overlays/dev/todo-web/httproute.yaml").read_text())
    assert route["spec"]["hostnames"] == ["todo-web.todo-dev.localhost"]
    assert render_check(gitops_repo).returncode == 0


def test_set_adds_an_addon_to_an_existing_service(gitops_repo, gh):
    """AC-045.1: `{uses: postgres, service: todo-api}` after `{addon: postgres}`."""
    import addon
    run_compose(gitops_repo, "add", "todo-api")
    commit(gitops_repo)
    addon.main(["add", "postgres", "--repo-dir", str(gitops_repo)])
    commit(gitops_repo)
    run_compose(gitops_repo, "set", "todo-api", "--uses", "postgres")
    assert components(gitops_repo)["todo-api"]["uses"] == ["postgres"]
    dep = yaml.safe_load((gitops_repo / "applications/todo/overlays/dev/todo-api/deployment.yaml").read_text())
    assert "DATABASE_URL" in {e["name"] for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}


@pytest.mark.parametrize("argv, msg", [
    (["set", "todo-x", "--env", "A=b"], "is not in system.yaml"),
    (["set", "todo-api", "todo-web", "--env", "A=b"], "exactly one component"),
    (["set", "todo-api"], "nothing to change"),
])
def test_set_refuses_unknown_services_and_empty_changes(gitops_repo, gh, argv, msg):
    """AC-045.1"""
    run_compose(gitops_repo, "add", "todo-api")
    commit(gitops_repo)
    with pytest.raises(core.PlatformError, match=msg):
        run_compose(gitops_repo, *argv)


def test_set_dry_run_changes_nothing(gitops_repo, gh):
    """AC-045.1"""
    run_compose(gitops_repo, "add", "todo-api")
    commit(gitops_repo)
    before = system_file(gitops_repo).read_text()
    run_compose(gitops_repo, "set", "todo-api", "--env", "A=b", "--dry-run")
    assert system_file(gitops_repo).read_text() == before


def test_the_component_plugin_offers_add_set_and_remove():
    """AC-045.1: `set` is reachable through /component:set (5.0: one command per verb), not only from /system:ship."""
    for verb in ("add", "set", "remove"):
        text = (core.PLATFORM_ROOT / "plugins" / "component" / "commands" / f"{verb}.md").read_text()
        assert f"cplat component {verb}" in text
    assert "`set <component>`" in (core.PLATFORM_ROOT / "plugins" / "component" / "commands" / "set.md").read_text()


# ---------------- spec 062: dev runs every merged build ----------------

def run_pin(repo, *args):
    return subprocess.run(["uv", "run", "scripts/pin.py", *args], cwd=repo, capture_output=True, text=True)


def test_pin_sets_an_immutable_dev_tag_that_survives_a_render(gitops_repo, gh):
    """AC-062.2: dev is pinned to sha-<7> in git, and a re-render keeps it."""
    composed(gitops_repo, "todo-api")
    out = run_pin(gitops_repo, "dev", "todo-api", "sha-abc1234")
    assert out.returncode == 0, out.stderr
    k = yaml.safe_load((dev_dir(gitops_repo) / "kustomization.yaml").read_text())
    assert k["images"][0]["newTag"] == "sha-abc1234"
    assert subprocess.run(["uv", "run", "scripts/render.py"], cwd=gitops_repo, capture_output=True).returncode == 0
    assert yaml.safe_load((dev_dir(gitops_repo) / "kustomization.yaml").read_text())["images"][0]["newTag"] == "sha-abc1234"
    assert render_check(gitops_repo).returncode == 0


@pytest.mark.parametrize("args, msg", [
    (["dev", "todo-x", "sha-abc1234"], "unknown component"),
    (["staging", "todo-api", "sha-abc1234"], "does not run in staging"),
    (["dev", "todo-api", "latest"], "immutable"),
    (["dev", "todo-api", "sha-xyz"], "immutable"),
])
def test_pin_refuses_what_it_cannot_pin(gitops_repo, gh, args, msg):
    """AC-062.2: only immutable tags of composed services in their environments."""
    composed(gitops_repo, "todo-api")
    out = run_pin(gitops_repo, *args)
    assert out.returncode != 0 and msg in out.stderr


def _workflow(repo, name):
    return yaml.safe_load((repo / ".github" / "workflows" / name).read_text())


def test_the_pin_workflow_opens_an_auto_merging_pr_checked_by_ci(gitops_repo):
    """AC-062.1: a dispatched {service, tag} becomes a PR that CI checks and that merges itself."""
    wf = _workflow(gitops_repo, "pin-dev.yml")
    on = wf.get("on", wf.get(True))
    assert on["repository_dispatch"]["types"] == ["pin-dev"]
    perms = wf["permissions"]
    assert perms["contents"] == "write" and perms["pull-requests"] == "write" and perms["actions"] == "write"
    run = "\n".join(s.get("run", "") for job in wf["jobs"].values() for s in job.get("steps") or [])
    assert "scripts/pin.py dev" in run and "render.py --check" in run
    assert "gh pr create" in run and "gh pr merge" in run
    assert wf["jobs"]["ci"]["uses"] == "./.github/workflows/ci.yml"     # spec 065: CI runs on the pin branch, then merge
    assert "workflow_dispatch" in (_workflow(gitops_repo, "ci.yml").get("on") or _workflow(gitops_repo, "ci.yml")[True])


def _ci_on(repo):
    wf = _workflow(repo, "ci.yml")
    return wf.get("on", wf.get(True))


def test_pin_prs_merge_after_green_ci_without_branch_protection(gitops_repo):
    """AC-065.1: pin-dev runs the gitops CI on the pin branch and merges the PR itself only when that CI passed."""
    wf = _workflow(gitops_repo, "pin-dev.yml")
    jobs = wf["jobs"]
    assert jobs["ci"]["needs"] == "pin" and jobs["ci"]["with"]["ref"] == "${{ needs.pin.outputs.branch }}"
    assert jobs["merge"]["needs"] == ["pin", "ci"]
    merge = jobs["merge"]["steps"][0]
    assert merge["env"]["CI_RESULT"] == "${{ needs.ci.result }}"
    script = merge["run"]
    gate = script.index('if [ "$CI_RESULT" != "success" ]')
    first_merge = script.index('gh pr merge "$PR" --squash --delete-branch')
    assert gate < first_merge, "the merge must come after the CI result check"
    assert "--admin" not in script and "push origin main" not in script
    ci_call = _ci_on(gitops_repo)["workflow_call"]["inputs"]["ref"]
    assert ci_call["type"] == "string"
    ci = _workflow(gitops_repo, "ci.yml")
    for name in ("quality", "security"):
        checkout = ci["jobs"][name]["steps"][0]
        assert checkout["uses"].startswith("actions/checkout@") and checkout["with"]["ref"] == "${{ inputs.ref }}"
    assert "inputs.ref" in ci["concurrency"]["group"]          # two pins never share (and cancel) one concurrency group


def test_a_red_pin_stays_open_with_a_comment(gitops_repo):
    """AC-065.2: a failed CI leaves the PR open, comments the run and fails the workflow; dev keeps the old image."""
    script = _workflow(gitops_repo, "pin-dev.yml")["jobs"]["merge"]["steps"][0]["run"]
    red = script[script.index('if [ "$CI_RESULT" != "success" ]'):script.index("fi\n")]
    assert "gh pr comment" in red and "$RUN_URL" in red and "exit 1" in red and "gh pr merge" not in red


def test_protected_repos_fall_back_to_auto_merge(gitops_repo):
    """AC-065.3: where branch protection blocks the direct merge, CI runs on the PR and auto-merge waits for it."""
    script = _workflow(gitops_repo, "pin-dev.yml")["jobs"]["merge"]["steps"][0]["run"]
    tail = script[script.index('if gh pr merge "$PR" --squash --delete-branch; then'):]
    assert 'gh workflow run ci.yml --ref "$BRANCH"' in tail and 'gh pr merge "$PR" --auto --squash --delete-branch' in tail


def test_a_failing_pin_never_reaches_main(gitops_repo):
    """AC-062.6: the pin only lands through the PR, merged after CI passed (spec 065), never pushed to main."""
    text = (gitops_repo / ".github" / "workflows" / "pin-dev.yml").read_text()
    assert "HEAD:main" not in text and "push origin main" not in text and "--admin" not in text
    assert "pin/dev-" in text and ("Signed-off-by" in text or "--signoff" in text)


def test_status_shows_the_intended_pin_when_dev_is_unhealthy(gitops_repo, gh, monkeypatch):
    """AC-062.3: a pinned build whose rollout fails shows its tag and that it is not healthy; an open pin PR is visible."""
    import status
    composed(gitops_repo, "todo-api")
    assert run_pin(gitops_repo, "dev", "todo-api", "sha-abc1234").returncode == 0
    answers = {
        ("gh", "run"): "completed success",
        ("git", "-C"): "https://github.com/acme/todo-gitops.git",
        ("gh", "pr"): json.dumps([{"number": 12, "headRefName": "pin/dev-todo-api-def5678"},
                                  {"number": 9, "headRefName": "feature/x"}]),
        ("kubectl", "--context"): json.dumps({"items": [{"metadata": {"name": "todo-api-dev"},
                                                         "status": {"sync": {"status": "Synced"}, "health": {"status": "Degraded"}}}]}),
    }
    monkeypatch.setattr(status, "sh", lambda cmd: answers.get((cmd[0], cmd[1])))
    app, envs, rows, resources = status.collect(gitops_repo, None, "k3d-x")
    dev = next(r for r in rows if r["component"] == "todo-api")["cells"]["dev"]
    assert dev["tag"] == "sha-abc1234" and dev["argo"] == "Synced/Degraded" and dev["pin_pr"] == "#12 sha-def5678"
    table = status.render_table(app, envs, rows, resources, {"platform": "4.1.0"}, "k3d-x")
    assert "pin PR" in table and "#12 sha-def5678" in table and "Degraded" in table


# ---------------- spec 069: external services ----------------

STOCK = {"stock-manager": {
    "type": "service", "lang": "unknown", "repo": "acme/stock-manager", "image": "ghcr.io/acme/stock-manager",
    "external": {"kustomize": "external/stock-manager", "namespace": "stock-manager"}, "instances": {"dev": {}}}}
AIOPS = {"ai-ops": {
    "type": "service", "lang": "unknown", "repo": "acme/ai-ops", "image": "ghcr.io/acme/ai-ops",
    "external": {"helm": {"repoURL": "https://github.com/acme/ai-ops", "path": "charts/ai-ops", "revision": "main", "imageTag": "image.tag"},
                 "namespace": "ai-ops", "values": {"replicas": 1, "autonomy": {"ceiling": "L1"}}, "envValues": {"staging": {"replicas": 2}}},
    "instances": {"dev": {}}}}


def add_external(repo, *entries):
    pkg = repo / "applications/todo/external/stock-manager"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "kustomization.yaml").write_text("resources: [cronjobs.yaml]\n")
    (pkg / "cronjobs.yaml").write_text("apiVersion: batch/v1\nkind: CronJob\nmetadata: {name: daily}\n")
    write_components(repo, {k: v for e in entries for k, v in e.items()})
    out = subprocess.run(["uv", "run", "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    commit(repo, "external")


def overlay(repo, env, svc, name="kustomization.yaml"):
    return yaml.safe_load((repo / f"applications/todo/overlays/{env}/{svc}/{name}").read_text())


def test_an_external_kustomize_package_is_wired_and_pinned_like_a_service(gitops_repo):
    """AC-069.1: the overlay includes the package, sets its namespace and pins the image; the ApplicationSet lists it."""
    add_external(gitops_repo, STOCK)
    k = overlay(gitops_repo, "dev", "stock-manager")
    assert k["resources"] == ["../../../external/stock-manager"] and k["namespace"] == "stock-manager"
    assert k["images"] == [{"name": "ghcr.io/acme/stock-manager", "newTag": "latest"}]
    appset = (gitops_repo / "applications/todo/applicationset.yaml").read_text()
    assert "name: stock-manager" in appset
    assert not (gitops_repo / "applications/todo/overlays/dev/stock-manager/deployment.yaml").exists()


def test_an_external_helm_chart_gets_an_argo_application_with_the_pinned_tag(gitops_repo):
    """AC-069.2: a chart from the service repo, values per environment, the image tag at imageTag."""
    add_external(gitops_repo, AIOPS)
    app = overlay(gitops_repo, "dev", "ai-ops", "application.yaml")
    assert app["kind"] == "Application" and app["metadata"]["namespace"] == "argocd" and app["metadata"]["name"] == "ai-ops-dev-chart"
    src = app["spec"]["source"]
    assert src["repoURL"] == "https://github.com/acme/ai-ops" and src["path"] == "charts/ai-ops" and src["targetRevision"] == "main"
    assert src["helm"]["valuesObject"] == {"replicas": 1, "autonomy": {"ceiling": "L1"}, "image": {"tag": "latest"}}
    assert src["helm"]["releaseName"] == "ai-ops"   # not the Application name: chart selectors use the release name
    assert app["spec"]["destination"]["namespace"] == "ai-ops" and "ServerSideApply=true" in app["spec"]["syncPolicy"]["syncOptions"]
    assert overlay(gitops_repo, "dev", "ai-ops")["resources"] == ["application.yaml"]


def test_pin_and_promote_move_external_services(gitops_repo, gh):
    """AC-069.3: pin.py (pin-dev) and /gitops:promote pin external services; render --check stays green."""
    add_external(gitops_repo, STOCK, AIOPS)
    for svc in ("stock-manager", "ai-ops"):
        out = run_pin(gitops_repo, "dev", svc, "sha-abc1234")
        assert out.returncode == 0, out.stderr
    assert overlay(gitops_repo, "dev", "stock-manager")["images"][0]["newTag"] == "sha-abc1234"
    assert overlay(gitops_repo, "dev", "ai-ops", "application.yaml")["spec"]["source"]["helm"]["valuesObject"]["image"]["tag"] == "sha-abc1234"
    assert render_check(gitops_repo).returncode == 0
    commit(gitops_repo, "pin")
    assert promote.main(["ai-ops", "--to", "staging", "--sha", SHA, "--no-verify", "--repo-dir", str(gitops_repo)]) == 0
    staged = overlay(gitops_repo, "staging", "ai-ops", "application.yaml")["spec"]["source"]["helm"]["valuesObject"]
    assert staged["image"]["tag"] == "sha-" + SHA and staged["replicas"] == 2   # spec 078: the full sha
    assert render_check(gitops_repo).returncode == 0


def test_status_reads_the_pin_of_external_services(gitops_repo):
    """AC-069.3: /shared:status shows external services with their pin."""
    import status
    add_external(gitops_repo, STOCK)
    assert run_pin(gitops_repo, "dev", "stock-manager", "sha-abc1234").returncode == 0
    assert status.pinned_tag(gitops_repo / "applications/todo", "dev", "stock-manager") == "sha-abc1234"


def _stock(**over):
    entry = copy.deepcopy(STOCK)
    entry["stock-manager"].update(over)
    return entry


def _stock_external(**over):
    entry = copy.deepcopy(STOCK)
    entry["stock-manager"]["external"] = {**entry["stock-manager"]["external"], **over}
    return entry


def _aiops_without_path():
    entry = copy.deepcopy(AIOPS)
    del entry["ai-ops"]["external"]["helm"]["path"]
    return entry


def _stock_without_kustomize():
    entry = copy.deepcopy(STOCK)
    del entry["stock-manager"]["external"]["kustomize"]
    return entry


@pytest.mark.parametrize("entry, error", [
    (_stock(port=8080), "port belongs in its package"),
    (_stock_external(kustomize="external/missing"), "kustomization.yaml does not exist"),
    (_aiops_without_path(), "external.helm needs `path`"),
    (_stock_without_kustomize(), "exactly one of"),
])
def test_external_entries_are_validated(gitops_repo, entry, error):
    """AC-069.4: wrong external entries fail render with a message that names the problem."""
    pkg = gitops_repo / "applications/todo/external/stock-manager"
    pkg.mkdir(parents=True)
    (pkg / "kustomization.yaml").write_text("resources: []\n")
    write_components(gitops_repo, entry)
    out = subprocess.run(["uv", "run", "scripts/render.py"], cwd=gitops_repo, capture_output=True, text=True)
    assert out.returncode == 1 and error in out.stderr
