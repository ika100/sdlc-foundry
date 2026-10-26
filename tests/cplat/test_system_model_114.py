"""Spec 114 acceptance tests: the model of spec 113 is loaded from `system.yaml` (schema 2) — AC-114.6 (URL rule), AC-114.23
(unmigrated detection), AC-114.58 (type/lang helpers), AC-114.69 and AC-114.70.

Contract: design.md "Contract — the model (model.py, schema 2)" and "cplat model show". Files are built by hand
(system_fixtures.write_system); nothing renders. The "same as 4.7" comparison runs the pre-5.0 `cplat model show --json` (git
commit V4_REF, the last 4.x state) on the 4.7 files of the same system and applies the mapping the design names."""
import copy
import importlib.util
import json
import subprocess
import sys
import tarfile
import io
from pathlib import Path

import pytest

import cplat
from system_fixtures import FULL5, NOT_MIGRATED, PINS, RENDER5, ROOT, SHA, V4_REF, mod, rich5, tiny, write_old, write_system


@pytest.fixture()
def app(tmp_path):
    return write_system(tmp_path, rich5(), pins={**PINS, ("dev", "shop-web"): "latest"})


@pytest.fixture()
def m(app):
    return mod("model").load_dir(app)


def show(tmp_path, *args, capsys):
    rc = cplat.main(["model", "show", "--repo-dir", str(tmp_path), *args])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


# ---------------- AC-114.69: the model is loaded from system.yaml ----------------

def test_the_system_environments_and_their_rules_come_from_system_yaml_ac_114_69(m):  # AC-114.69
    assert m.system == "shop" and m.owner == "acme"
    assert [e.name for e in m.environments] == ["dev", "staging", "prod"]
    dev, staging, prod = m.environments
    assert (dev.policy, staging.policy, prod.policy) == ("audit", "off", "enforce")
    assert (dev.promotion, staging.promotion, prod.promotion) == ("main", "after-dev-smoke", "manual")
    assert dev.host == "{component}.{system}-dev.localhost" and dev.url_template == "http://{host}:8088" and prod.host is None
    assert dev.observability.ui == "lgtm" and dev.observability.argo_application == "addon-observability-dev"


def test_components_apis_libraries_and_owner_ac_114_69(m):  # AC-114.69
    api, web, lib, stock = (m.component(n) for n in ("shop-api", "shop-web", "shop-lib", "stock"))
    assert (api.type, api.lang, api.shape) == ("service", "python", "service-python")
    assert (web.type, web.lang, web.shape) == ("website", "typescript", "web-nextjs")
    assert (lib.type, lib.lang) == ("library", "python") and lib.environments == ()
    assert (stock.type, stock.lang, stock.shape) == ("service", "unknown", None)
    assert api.provides == ("shop-api-rest",) and api.consumes == () and web.consumes == ("shop-api-rest",)
    assert api.uses == ("postgres",) and api.libraries == ("shop-lib",)
    assert api.environments == ("dev", "staging", "prod") and web.environments == ("dev", "staging") and stock.environments == ("dev",)
    [a] = list(m.apis)
    assert (a.name, a.type, a.provider, tuple(a.consumers)) == ("shop-api-rest", "openapi", "shop-api", ("shop-web",))
    assert m.instances_of("shop-lib") == []


def test_instances_carry_tag_replicas_namespace_argo_url_and_promotion_ac_114_69(m):  # AC-114.69
    dev, staging, prod = (m.instance("shop-api", e) for e in ("dev", "staging", "prod"))
    assert (dev.tag, staging.tag, prod.tag) == ("sha-" + SHA, "1.2.0", None)
    assert (dev.replicas, staging.replicas, prod.replicas) == (1, 2, 3)
    assert (dev.namespace, staging.namespace, prod.namespace) == ("shop-dev", "shop-staging", "shop-prod")
    assert (dev.argo_application, prod.argo_application) == ("shop-api-dev", "shop-api-prod")
    assert dev.url == "http://api.shop-dev.localhost:8088" and staging.url == "https://api.shop.example.com" and prod.url is None
    assert m.promoted_from(dev) is None
    assert m.promoted_from(staging).environment == "dev" and m.promoted_from(prod).environment == "staging"
    assert m.instance("stock", "dev").replicas is None
    assert m.instance("shop-web", "prod") is None
    assert m.staging_promotion(m.component("shop-api")) == "manual" and m.staging_promotion(m.component("shop-web")) == "after-dev-smoke"


def test_instance_secrets_apply_the_instances_overrides_ac_114_69(m):  # AC-114.69
    dev = {s.name: s for s in m.secrets("shop-api", "dev")}
    prod = {s.name: s for s in m.secrets("shop-api", "prod")}
    assert dev["api-keys"].store_key == "shop-dev-api-keys" and dev["api-pay"].store_key == "shop-api/dev/api-pay"
    assert dev["api-auth"].store_key is None and dev["api-auth"].kind == "generate"
    assert prod["api-pay"].store_key == "prod/api-pay" and prod["api-pay"].overridden is True
    assert prod["api-keys"].overridden is False and dev["api-pay"].overridden is False


def test_resource_instances_carry_the_sizing_with_replicas_ac_114_69(m):  # AC-114.69
    sizing = {ri.environment: dict(ri.sizing) for ri in m.resource_instances_of("postgres")}
    assert sizing == {"dev": {"replicas": 1, "version": 17, "storage": "1Gi"}, "staging": {"replicas": 1, "version": 17, "storage": "1Gi"},
                      "prod": {"replicas": 3, "version": 17, "storage": "20Gi"}}
    ri = m.resource_instances_of("postgres")[0]
    assert ri.argo_application == f"addon-postgres-{ri.environment}" and ri.secret == "shop-postgres-app"
    assert [r.name for r in m.resources] == ["postgres"] and m.resources[0].type == "database"
    assert not hasattr(m, "declared_addons")


def test_the_json_is_schema_2_with_the_new_nouns_ac_114_69(app, tmp_path, capsys):  # AC-114.69
    rc, out, err = show(tmp_path, "--json", capsys=capsys)
    assert rc == 0 and err == ""
    d = json.loads(out)
    assert d["schema"] == 2
    assert d["system"]["owner"] == "acme" and d["system"]["apis"] == ["shop-api-rest"]
    assert d["apis"] == [{"name": "shop-api-rest", "type": "openapi", "provider": "shop-api", "consumers": ["shop-web"]}]
    envs = {e["name"]: e for e in d["environments"]}
    assert (envs["dev"]["policy"], envs["staging"]["promotion"], envs["prod"]["policy"]) == ("audit", "after-dev-smoke", "enforce")
    assert {"headersSecret", "querySecret"} <= set(envs["dev"]["observability"])
    comps = {c["name"]: c for c in d["components"]}
    assert comps["shop-api"]["provides"] == ["shop-api-rest"] and comps["shop-api"]["libraries"] == ["shop-lib"]
    assert comps["shop-web"]["consumes"] == ["shop-api-rest"] and comps["shop-lib"]["used_by"] == ["shop-api"] and comps["shop-api"]["used_by"] == []
    insts = {(i["component"], i["environment"]): i for i in d["instances"]}
    assert all("overridden" in s for s in insts[("shop-api", "prod")]["secrets"])
    assert {s["name"]: s["overridden"] for s in insts[("shop-api", "prod")]["secrets"]}["api-pay"] is True
    assert {ri["environment"]: ri["sizing"]["replicas"] for ri in d["resource_instances"]} == {"dev": 1, "staging": 1, "prod": 3}
    rel = d["relations"]
    assert {"type": "part_of", "from": "api:shop-api-rest", "to": "system:shop"} in rel
    assert {"type": "provides", "from": "component:shop-api", "to": "api:shop-api-rest"} in rel
    assert {"type": "consumes", "from": "component:shop-web", "to": "api:shop-api-rest"} in rel
    assert {"type": "uses", "from": "component:shop-api", "to": "component:shop-lib"} in rel
    assert {"type": "uses", "from": "component:shop-api", "to": "resource:postgres"} in rel


def test_the_text_shows_owner_policy_promote_apis_and_replicas_ac_114_69(app, tmp_path, capsys):  # AC-114.69
    rc, out, _ = show(tmp_path, capsys=capsys)
    assert rc == 0
    lines = out.splitlines()
    assert lines[0] == "System: shop" and lines[1] == "Owner: acme"
    assert "policy audit  promote follows main" in out and "policy off  promote after-dev-smoke" in out and "policy enforce  promote manual" in out
    api = next(ln for ln in lines if ln.startswith("  shop-api  type service"))
    assert api.endswith("  provides shop-api-rest  consumes -  libraries shop-lib")
    web = next(ln for ln in lines if ln.startswith("  shop-web  type website"))
    assert web.endswith("  provides -  consumes shop-api-rest  libraries -")
    assert out.index("Components:") < out.index("APIs:")
    assert "  shop-api-rest  type openapi  provider shop-api  consumers shop-web" in out
    assert "replicas 3" in out and "instances 3" not in out


def test_a_system_without_apis_prints_none_ac_114_69(tmp_path, capsys):  # AC-114.69
    write_system(tmp_path, tiny())
    rc, out, _ = show(tmp_path, capsys=capsys)
    assert rc == 0 and "APIs:\n  (none)" in out


def test_schema_2_equals_4x_for_the_same_system_after_the_design_mapping_ac_114_69(tmp_path_factory, capsys):  # AC-114.69
    old, new = tmp_path_factory.mktemp("old"), tmp_path_factory.mktemp("new")
    pins = {**PINS, ("dev", "shop-web"): "latest"}
    write_old(old, pins=pins)
    write_system(new, FULL5, pins=pins)
    before = pre_5_model_json(old, tmp_path_factory)
    rc, out, _ = show(new, "--json", capsys=capsys)
    assert rc == 0
    after = json.loads(out)
    assert before["schema"] == 1 and after["schema"] == 2
    assert normalize_4x(before) == normalize_5(after)


def pre_5_model_json(repo: Path, tmp_path_factory) -> dict:
    """`cplat model show --json` of the last 4.x state of this checkout on 4.7 files."""
    src = tmp_path_factory.mktemp("cplat-4x")
    got = subprocess.run(["git", "archive", V4_REF, "scripts", "shapes.yml", "docs/CHANGELOG.md"], cwd=ROOT, capture_output=True)
    if got.returncode != 0:
        pytest.skip(f"commit {V4_REF} is not available in this checkout")
    tarfile.open(fileobj=io.BytesIO(got.stdout)).extractall(src)
    p = subprocess.run([sys.executable, str(src / "scripts/cplat/cplat.py"), "model", "show", "--json", "--repo-dir", str(repo)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _ph(text):
    return text.replace("{service}", "{component}").replace("{app}", "{system}") if isinstance(text, str) else text


def _env4(e):
    e = dict(e)
    e["policy"] = e["policy"].lower()
    e["promotion"] = "after-dev-smoke" if e["promotion"] == "auto" else e["promotion"]
    e["host"], e["url"] = _ph(e["host"]), _ph(e["url"])
    e["observability"] = {k: v for k, v in (e["observability"] or {}).items() if k not in ("headersSecret", "querySecret")} or None
    return e


def normalize_4x(d: dict) -> dict:
    out = {"system": d["system"], "environments": [_env4(e) for e in d["environments"]]}
    out["components"] = [{k: v for k, v in c.items()} for c in d["components"]]
    for c in out["components"]:
        c["promotion"] = {"staging": ("after-dev-smoke" if c["promotion"]["staging"] == "auto" else c["promotion"]["staging"])}
    out["resources"], out["instances"] = d["resources"], d["instances"]
    for i in out["instances"]:
        i["secrets"] = [{k: v for k, v in s.items()} for s in i["secrets"]]
    out["resource_instances"] = [{**r, "sizing": {("replicas" if k == "instances" else k): v for k, v in r["sizing"].items()}} for r in d["resource_instances"]]
    out["relations"] = d["relations"]
    return out


def normalize_5(d: dict) -> dict:
    out = {"system": {k: v for k, v in d["system"].items() if k in ("name", "components", "resources")}}
    out["environments"] = [{**e, "observability": {k: v for k, v in (e["observability"] or {}).items() if k not in ("headersSecret", "querySecret")} or None}
                           for e in d["environments"]]
    out["components"] = [{k: v for k, v in c.items() if k not in ("provides", "consumes", "libraries", "used_by")} for c in d["components"]]
    out["resources"] = d["resources"]
    out["instances"] = [{**i, "secrets": [{k: v for k, v in s.items() if k != "overridden"} for s in i["secrets"]]} for i in d["instances"]]
    out["resource_instances"] = d["resource_instances"]
    out["relations"] = [r for r in d["relations"] if r["type"] not in ("provides", "consumes") and not r["to"].startswith(("api:",))
                        and not r["from"].startswith("api:")]
    return out


# ---------------- AC-114.23 / AC-114.69: unmigrated detection ----------------

@pytest.mark.parametrize("files", [("services.yaml",), ("app.yaml",), ("app.yaml", "services.yaml")])
def test_load_dir_refuses_old_files_with_the_one_message_ac_114_23(tmp_path, files):  # AC-114.23
    model = mod("model")
    d = write_system(tmp_path, FULL5)
    for f in files:
        (d / f).write_text("services: []\n" if f == "services.yaml" else "{}\n")
    assert model.NOT_MIGRATED == NOT_MIGRATED
    with pytest.raises(model.NotMigrated) as e:
        model.load_dir(d)
    assert NOT_MIGRATED in str(e.value) and isinstance(e.value, model.ModelError)


def test_model_show_in_an_unmigrated_repo_exits_1_with_the_message_ac_114_23(tmp_path, capsys):  # AC-114.23
    write_old(tmp_path)
    rc, out, err = show(tmp_path, capsys=capsys)
    assert rc == 1 and out == "" and NOT_MIGRATED in err


def test_load_remote_reads_system_yaml_and_refuses_services_yaml_ac_114_23(tmp_path):  # AC-114.23
    model = mod("model")
    doc = tiny()
    seen = []

    def read(path):
        seen.append(path)
        return doc if path == "applications/shop/system.yaml" else None
    assert model.load_remote("shop", read).system == "shop" and seen[0] == "applications/shop/system.yaml"

    def old(path):
        return {"services": []} if path == "applications/shop/services.yaml" else None
    with pytest.raises(model.NotMigrated):
        model.load_remote("shop", old)


def test_build_takes_a_system_document_leniently_ac_114_23(tmp_path):  # AC-114.23
    model = mod("model")
    m = model.build(tiny(), "shop")
    assert [c.name for c in m.components] == ["api"] and m.instance("api", "dev").namespace == "shop-dev"
    assert model.build(None, "shop").components == ()
    assert [c.name for c in model.build({"components": {"x": "not a mapping", "ok": {"type": "service", "lang": "go"}}}, "shop").components] == ["ok"]


def test_the_ac_113_13_guard_still_holds_for_the_5_0_modules_ac_114_69(tmp_path):  # AC-114.69
    from test_model_guard import CPLAT, findings
    scanned = {"migrate5.py", "apilist.py", "status.py", "promote.py", "smoke.py", "staging.py", "alertsources.py", "compose.py"}
    present = {p.name for p in CPLAT.glob("*.py")}
    assert scanned <= present, f"missing modules: {sorted(scanned - present)}"
    bad = {p.name: findings(p.read_text()) for p in CPLAT.glob("*.py") if p.name != "model.py" and findings(p.read_text())}
    assert bad == {}, bad


# ---------------- AC-114.6: environment URLs ----------------

def test_the_url_template_fills_host_component_system_and_env_ac_114_6(tmp_path):  # AC-114.6
    doc = copy.deepcopy(FULL5)
    doc["environments"]["staging"]["url"] = "https://{host}/{component}/{system}/{env}"
    m = mod("model").build(doc, "shop")
    assert m.url("shop-api", "staging") == ("https://api.shop.example.com/shop-api/shop/staging", None)
    assert m.url("shop-web", "dev") == ("http://shop-web.shop-dev.localhost:8088", None)


def test_without_url_the_host_gives_the_4x_url_ac_114_6(tmp_path, monkeypatch):  # AC-114.6
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)
    doc = copy.deepcopy(FULL5)
    del doc["environments"]["dev"]["url"]
    m = mod("model").build(doc, "shop")
    assert m.url("shop-api", "dev")[0] == f"http://api.shop-dev.localhost:{mod('model').DEFAULT_LOCAL_PORT}"
    assert m.url("shop-api", "staging")[0] == "https://api.shop.example.com"
    assert m.url("shop-api", "prod") == (None, "not exposed in prod")


def test_dev_url_of_the_smoke_run_follows_system_yaml_ac_114_6(tmp_path, monkeypatch):  # AC-114.6
    import smoke
    app = write_system(tmp_path, FULL5)
    monkeypatch.setattr(smoke, "_slug", lambda repo: "acme/shop-api")
    monkeypatch.setattr(smoke, "_app_dirs", lambda slug, repo: ["shop"])
    monkeypatch.setattr(smoke, "_read", lambda slug, path, repo: __import__("yaml").safe_load((tmp_path / path).read_text()) if (tmp_path / path).is_file() else None)
    assert smoke.dev_url(tmp_path, ["acme/shop-gitops"], "shop-api") == ("http://api.shop-dev.localhost:8088", None)
    assert smoke.dev_url(tmp_path, ["acme/shop-gitops"], "shop-api", env="staging") == ("https://api.shop.example.com", None)
    assert app.is_dir()


# ---------------- AC-114.58: type and lang helpers ----------------

def test_type_lang_pairs_come_from_the_registry_plus_service_unknown_ac_114_58(tmp_path):  # AC-114.58
    model = mod("model")
    assert set(model.TYPE_LANGS) == {("service", "python"), ("service", "java"), ("service", "go"), ("website", "typescript"),
                                     ("library", "python"), ("service", "unknown")}


@pytest.mark.parametrize("shape, pair", [("service-python", ("service", "python")), ("service-java", ("service", "java")),
                                         ("service-go", ("service", "go")), ("web-nextjs", ("website", "typescript")),
                                         ("library-python", ("library", "python")), (None, ("service", "unknown")),
                                         ("service-cobol", ("service", "unknown"))])
def test_a_4x_shape_maps_to_type_and_lang_ac_114_58(shape, pair):  # AC-114.58
    assert mod("model").type_lang(shape) == pair


@pytest.mark.parametrize("pair, shape", [(("service", "java"), "service-java"), (("website", "typescript"), "web-nextjs"),
                                         (("library", "python"), "library-python"), (("service", "unknown"), None)])
def test_type_and_lang_map_back_to_the_shape_ac_114_58(pair, shape):  # AC-114.58
    assert mod("model").shape_for(*pair) == shape


def test_the_renderers_pairs_equal_the_models_ac_114_58(tmp_path):  # AC-114.58
    model = mod("model")
    spec = importlib.util.spec_from_file_location("render_pairs", RENDER5)
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    wanted = {("service", "python"), ("service", "unknown")}
    held = [v for v in vars(r).values() if isinstance(v, (tuple, list, set, frozenset))
            and wanted <= {tuple(x) for x in v if isinstance(x, (tuple, list))}]
    assert held, "render.py holds the valid type/lang pairs as a constant"
    assert {tuple(x) for x in held[0]} == set(model.TYPE_LANGS)


# ---------------- AC-114.70: the model as the renderer's comparison point ----------------

def test_the_model_lists_the_instances_the_instance_keys_declare_ac_114_70(m):  # AC-114.70
    assert sorted((i.component, i.environment) for i in m.instances) == [
        ("shop-api", "dev"), ("shop-api", "prod"), ("shop-api", "staging"), ("shop-web", "dev"), ("shop-web", "staging"), ("stock", "dev")]
    assert sorted(ri.environment for ri in m.resource_instances) == ["dev", "prod", "staging"]
    assert [i.component for i in mod("model").build(tiny(), "shop").instances] == ["api"]       # no instances: dev only
