"""Resource contract (ADR-020, 5.0): system.yaml `resources` + component `uses` → CloudNativePG Cluster and env wiring."""
import subprocess

import pytest
import yaml

import addon
import compose
import core
from test_gitops import commit, components, gh, gitops_repo, render_check, run_compose, system_file  # noqa: F401  (fixtures)

APP = "applications/todo"


def system_doc(repo):
    return yaml.safe_load(system_file(repo).read_text())


def write_system(repo, doc):
    system_file(repo).write_text(yaml.safe_dump(doc, sort_keys=False))


def render(repo):
    return subprocess.run(["uv", "run", "scripts/render.py"], cwd=repo, capture_output=True, text=True)


def declare(repo, **kw):
    assert addon.main(["add", "postgres", "--repo-dir", str(repo), *kw.get("extra", [])]) == 0
    commit(repo, "addon")


def dev_deploy(repo, svc="todo-api"):
    return yaml.safe_load((repo / APP / "overlays/dev" / svc / "deployment.yaml").read_text())


def test_addon_add_declares_it_and_keeps_comments(gitops_repo, gh):
    declare(gitops_repo, extra=["--version", "16"])
    pg = system_doc(gitops_repo)["resources"]["postgres"]
    assert pg["type"] == "database" and pg["version"] == 16 and pg["instances"] == {"prod": {"replicas": 3, "storage": "20Gi"}}
    assert pg["replicas"] == 1 and pg["storage"] == "1Gi"
    assert "# components: add with `/component:new`" in system_file(gitops_repo).read_text()


def test_service_uses_postgres_gets_env_from_the_operator_secret_and_a_cluster_is_rendered(gitops_repo, gh):
    declare(gitops_repo)
    run_compose(gitops_repo, "add", "todo-api", "--uses", "postgres")
    env = {e["name"]: e for e in dev_deploy(gitops_repo)["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["DATABASE_URL"]["valueFrom"]["secretKeyRef"] == {"name": "todo-postgres-app", "key": "uri"}
    assert env["PGPASSWORD"]["valueFrom"]["secretKeyRef"]["key"] == "password"
    cluster = yaml.safe_load((gitops_repo / APP / "addons/dev/postgres/cluster.yaml").read_text())
    assert cluster["kind"] == "Cluster" and cluster["metadata"]["name"] == "todo-postgres"
    assert cluster["spec"]["instances"] == 1 and cluster["spec"]["storage"]["size"] == "1Gi"
    assert cluster["spec"]["imageName"].endswith("postgresql:17") and cluster["spec"]["enableSuperuserAccess"] is False
    assert cluster["spec"]["bootstrap"]["initdb"] == {"database": "todo", "owner": "todo"}
    sets = yaml.safe_load_all((gitops_repo / APP / "applicationset.yaml").read_text())
    names = [d["metadata"]["name"] for d in sets]
    assert "todo-addons-dev" in names and "todo-addons-prod" not in names
    assert render_check(gitops_repo).returncode == 0


def test_values_can_differ_per_environment(gitops_repo, gh):
    declare(gitops_repo)
    run_compose(gitops_repo, "add", "todo-api", "--uses", "postgres")
    d = system_doc(gitops_repo)
    d["components"]["todo-api"]["instances"] = {"dev": {}, "prod": {}}
    write_system(gitops_repo, d)
    assert render(gitops_repo).returncode == 0
    prod = yaml.safe_load((gitops_repo / APP / "addons/prod/postgres/cluster.yaml").read_text())
    assert prod["spec"]["instances"] == 3 and prod["spec"]["storage"]["size"] == "20Gi"


def test_nothing_is_rendered_without_users_of_the_addon(gitops_repo, gh):
    declare(gitops_repo)
    run_compose(gitops_repo, "add", "todo-api")
    assert not (gitops_repo / APP / "addons").exists()


def test_removing_the_use_prunes_the_addon_files(gitops_repo, gh):
    declare(gitops_repo)
    run_compose(gitops_repo, "add", "todo-api", "--uses", "postgres")
    commit(gitops_repo)
    d = system_doc(gitops_repo)
    del d["components"]["todo-api"]["uses"]
    write_system(gitops_repo, d)
    assert render(gitops_repo).returncode == 0
    assert not (gitops_repo / APP / "addons/dev/postgres").exists()


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["components"]["todo-api"].update(uses=["postgres"]) or d.pop("resources", None), "uses 'postgres', which is neither a resource nor a library"),
    (lambda d: d["components"]["todo-api"].update(uses=["redis"]), "uses 'redis', which is neither a resource nor a library"),
    (lambda d: d.update(resources={"mysql": {"type": "database"}}), "resources.mysql: 5.0 supports one database resource named postgres"),
    (lambda d: (d.update(resources={"postgres": {"type": "database"}}), d["components"]["todo-api"].update(uses=["postgres"]),
                d["components"]["todo-api"]["env"].update(DATABASE_URL="x")), "is provided by the 'postgres' resource"),
])
def test_invalid_resource_wiring_is_rejected(gitops_repo, gh, mutate, msg):
    run_compose(gitops_repo, "add", "todo-api")
    d = system_doc(gitops_repo)
    mutate(d)
    write_system(gitops_repo, d)
    p = render(gitops_repo)
    assert p.returncode == 1 and msg in p.stderr


def test_addon_remove_refuses_while_in_use_and_never_touches_data(gitops_repo, gh):
    declare(gitops_repo)
    run_compose(gitops_repo, "add", "todo-api", "--uses", "postgres")
    commit(gitops_repo)
    with pytest.raises(core.PlatformError, match="still used by todo-api"):
        addon.main(["remove", "postgres", "--repo-dir", str(gitops_repo)])
    d = system_doc(gitops_repo)
    del d["components"]["todo-api"]["uses"]
    write_system(gitops_repo, d)
    commit(gitops_repo, "no use")
    assert addon.main(["remove", "postgres", "--repo-dir", str(gitops_repo)]) == 0
    assert "postgres" not in (system_doc(gitops_repo).get("resources") or {})


def test_unknown_or_duplicate_resource_is_an_error(gitops_repo, gh):
    with pytest.raises(core.PlatformError, match="unknown resource 'redis'"):
        addon.main(["add", "redis", "--repo-dir", str(gitops_repo)])
    declare(gitops_repo)
    with pytest.raises(core.PlatformError, match="already declared"):
        addon.main(["add", "postgres", "--repo-dir", str(gitops_repo)])


def test_uses_flag_needs_a_single_service(gitops_repo, gh):
    with pytest.raises(core.PlatformError, match="exactly one component"):
        run_compose(gitops_repo, "add", "todo-api", "todo-web", "--uses", "postgres")


# ---------------- observability: OpenTelemetry base (ADR-021) ----------------

def obs(repo, **conf):
    """5.0: observability is set per environment; the 4.x addon applied to all of them."""
    cfg = system_doc(repo)
    for env in cfg["environments"].values():
        env["observability"] = dict(conf)
    write_system(repo, cfg)
    commit(repo, "obs")


def collector(repo, env="dev"):
    d = repo / APP / "addons" / env / "observability"
    return d, yaml.safe_load(yaml.safe_load((d / "configmap.yaml").read_text())["data"]["config.yaml"])


def test_observability_renders_a_collector_scraping_every_service_with_a_metrics_path(gitops_repo, gh):
    obs(gitops_repo)
    run_compose(gitops_repo, "add", "todo-api")
    d, cfg = collector(gitops_repo)
    assert {p.name for p in d.iterdir()} == {"configmap.yaml", "collector.yaml", "service.yaml", "kustomization.yaml"}
    jobs = cfg["receivers"]["prometheus"]["config"]["scrape_configs"]
    assert jobs == [{"job_name": "todo-api", "scrape_interval": "30s", "metrics_path": "/actuator/prometheus", "static_configs": [{"targets": ["todo-api.todo-dev.svc:80"]}]}]
    assert list(cfg["exporters"]) == ["debug"] and cfg["service"]["pipelines"]["traces"]["exporters"] == ["debug"]
    res = {r["key"]: r["value"] for r in cfg["processors"]["resource"]["attributes"]}
    assert res == {"deployment.environment": "dev", "service.namespace": "todo"}
    dep = yaml.safe_load((d / "collector.yaml").read_text())
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert c["securityContext"]["runAsUser"] == 10001 and c["securityContext"]["readOnlyRootFilesystem"] is True
    assert dep["spec"]["template"]["metadata"]["annotations"]["checksum/config"]
    assert render_check(gitops_repo).returncode == 0


def test_every_service_gets_otel_variables_and_service_env_still_wins(gitops_repo, gh):
    obs(gitops_repo)
    run_compose(gitops_repo, "add", "todo-api", "--env", "OTEL_SDK_DISABLED=true")
    env = {e["name"]: e.get("value") for e in dev_deploy(gitops_repo)["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://otel-collector:4318"
    assert env["OTEL_SERVICE_NAME"] == "todo-api" and env["OTEL_RESOURCE_ATTRIBUTES"] == "service.namespace=todo,deployment.environment=dev"
    assert env["OTEL_SDK_DISABLED"] == "true"


def test_without_the_addon_nothing_is_wired(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api")
    env = {e["name"] for e in dev_deploy(gitops_repo)["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert not any(n.startswith("OTEL_") for n in env) and not (gitops_repo / APP / "addons").exists()


@pytest.mark.parametrize("conf,exporter", [
    ({"ui": "lgtm"}, "http://lgtm.observability.svc:4318"),
    ({"exportTo": "https://otlp.example.com"}, "https://otlp.example.com"),
])
def test_backend_selection(gitops_repo, gh, conf, exporter):
    obs(gitops_repo, **conf)
    run_compose(gitops_repo, "add", "todo-api")
    _, cfg = collector(gitops_repo)
    assert cfg["exporters"]["otlphttp/backend"]["endpoint"] == exporter
    assert cfg["service"]["pipelines"]["metrics"]["exporters"] == ["debug", "otlphttp/backend"]


def test_headers_come_from_a_secret_never_from_git(gitops_repo, gh):
    obs(gitops_repo, exportTo="https://otlp.example.com", headersSecret="otlp-auth")
    run_compose(gitops_repo, "add", "todo-api")
    d, cfg = collector(gitops_repo)
    assert cfg["exporters"]["otlphttp/backend"]["headers"] == {"Authorization": "${env:AUTHORIZATION}"}
    dep = yaml.safe_load((d / "collector.yaml").read_text())
    assert dep["spec"]["template"]["spec"]["containers"][0]["envFrom"] == [{"secretRef": {"name": "otlp-auth"}}]


@pytest.mark.parametrize("conf,msg", [
    ({"ui": "grafana"}, "must be none or lgtm"),
    ({"ui": "lgtm", "exportTo": "https://x.example.com"}, "either `ui: lgtm` or `exportTo`"),
    ({"exportTo": "otlp.example.com"}, "http(s) OTLP/HTTP"),
    ({"headersSecret": "s"}, "needs exportTo"),
])
def test_invalid_observability_config_is_rejected(gitops_repo, gh, conf, msg):
    run_compose(gitops_repo, "add", "todo-api")
    commit(gitops_repo)
    obs(gitops_repo, **conf)
    p = render(gitops_repo)
    assert p.returncode == 1 and msg in p.stderr


def test_uses_observability_is_an_error(gitops_repo, gh):
    obs(gitops_repo)
    run_compose(gitops_repo, "add", "todo-api")
    d = system_doc(gitops_repo)
    d["components"]["todo-api"]["uses"] = ["observability"]
    write_system(gitops_repo, d)
    p = render(gitops_repo)
    assert p.returncode == 1 and "uses 'observability', which is neither a resource nor a library" in p.stderr


def test_config_addons_are_pruned_but_databases_are_not(gitops_repo, gh):
    declare(gitops_repo)
    obs(gitops_repo)
    run_compose(gitops_repo, "add", "todo-api", "--uses", "postgres")
    sets = {d["metadata"]["name"]: d for d in yaml.safe_load_all((gitops_repo / APP / "applicationset.yaml").read_text())}
    assert sets["todo-addons-dev"]["spec"]["template"]["spec"]["syncPolicy"]["automated"]["prune"] is False
    assert sets["todo-addons-config-dev"]["spec"]["template"]["spec"]["syncPolicy"]["automated"]["prune"] is True
    assert [e["name"] for e in sets["todo-addons-dev"]["spec"]["generators"][0]["list"]["elements"]] == ["postgres"]
    assert [e["name"] for e in sets["todo-addons-config-dev"]["spec"]["generators"][0]["list"]["elements"]] == ["observability"]


def test_resource_add_observability_points_to_the_environment_setting(gitops_repo, gh):
    """5.0: observability is no resource (the 4.x `addon add observability --ui lgtm` is `environments.<env>.observability`)."""
    before = system_file(gitops_repo).read_text()
    with pytest.raises(core.PlatformError, match=r"observability is set per environment under environments\.<env>\.observability in system\.yaml"):
        addon.main(["add", "observability", "--repo-dir", str(gitops_repo)])
    assert system_file(gitops_repo).read_text() == before


def test_compose_seeds_the_metrics_path_per_shape(gitops_repo, gh):
    run_compose(gitops_repo, "add", "todo-api", "todo-web")
    assert {n: c["metrics"] for n, c in components(gitops_repo).items()} == {"todo-api": "/actuator/prometheus", "todo-web": "/api/metrics"}


def test_collector_config_has_no_yaml_anchors(gitops_repo, gh):
    obs(gitops_repo, ui="lgtm")
    run_compose(gitops_repo, "add", "todo-api")
    text = yaml.safe_load((gitops_repo / APP / "addons/dev/observability/configmap.yaml").read_text())["data"]["config.yaml"]
    assert "&id" not in text and "*id" not in text
