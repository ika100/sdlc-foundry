"""Spec 113 acceptance tests: `cplat model show [--json] [--app] [--repo-dir]` (AC-113.14 .. AC-113.16).

Contract: design.md "Contract — cplat model show". Run through `cplat.main`, like every command. The command module
(`modelcmd`) does not exist before the feature."""
import json
import subprocess

import pytest

import cplat
from model_fixtures import BARE_ENV, SHA, SMALL_TEXT, rich, small, snapshot, write_app


def show(tmp_path, *args, capsys):
    rc = cplat.main(["model", "show", "--repo-dir", str(tmp_path), *args])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


@pytest.fixture(autouse=True)
def local_port(monkeypatch):
    monkeypatch.delenv("LOCAL_HTTP_PORT", raising=False)


# ---------------- AC-113.14: the text ----------------

def test_the_text_prints_the_five_sections_exactly_ac_113_14(tmp_path, capsys):  # AC-113.14
    small(tmp_path)
    rc, out, err = show(tmp_path, capsys=capsys)
    assert rc == 0 and err == ""
    assert out.rstrip("\n") == SMALL_TEXT.rstrip("\n")


def test_the_sections_come_in_the_documented_order_for_a_rich_app_ac_113_14(tmp_path, capsys):  # AC-113.14
    rich(tmp_path)
    rc, out, _ = show(tmp_path, capsys=capsys)
    assert rc == 0
    heads = [out.index(h) for h in ("System: shop", "Environments (promotion order):", "Components:", "Instances:", "Resources:")]
    assert heads == sorted(heads)
    assert out.index("  dev  host") < out.index("  staging  host") < out.index("  prod  host")
    assert "  shop-api  dev  sha-" + SHA in out
    assert "  shop-api  staging  not pinned" in out
    assert "  shop-web  prod  1.2.0  replicas 3  namespace shop-prod  url -" in out
    assert "  ai-ops  prod  not pinned  replicas -  namespace shop-prod  url -" in out
    assert "external helm" in out and "external kustomize" in out
    assert "secrets api-keys,api-pay,api-auth" in out


def test_environment_rules_are_printed_ac_113_14(tmp_path, capsys):  # AC-113.14
    rich(tmp_path)
    _, out, _ = show(tmp_path, capsys=capsys)
    lines = {ln.split("  ")[1]: ln for ln in out.splitlines() if ln.startswith(("  dev  host", "  staging  host", "  prod  host"))}
    assert "host {service}.staging.example.com  url-template https://{host}/{service}  policy Off  promotion auto" in lines["staging"]
    assert "policy Enforce  promotion manual" in lines["prod"] and "host -  url-template -" in lines["prod"]
    assert "observability ui=lgtm export=https://otlp.example.com alerts=off rules=1" in lines["dev"]


def test_an_empty_section_prints_none_ac_113_14(tmp_path, capsys):  # AC-113.14
    write_app(tmp_path, [], None)
    rc, out, _ = show(tmp_path, capsys=capsys)
    assert rc == 0
    assert "Components:\n  (none)\n\nInstances:\n  (none)\n\nResources:\n  (none)" in out
    assert "observability -" in out


def test_a_resource_without_a_resource_instance_prints_only_its_line_ac_113_14(tmp_path, capsys):  # AC-113.14
    write_app(tmp_path, [{"name": "api", "repo": "acme/api", "image": "i", "shape": "service-python"}], {"addons": {"postgres": {}}})
    _, out, _ = show(tmp_path, capsys=capsys)
    tail = out.split("Resources:\n")[1].rstrip("\n").splitlines()
    assert len(tail) == 1 and tail[0].startswith("  postgres  type database")


def test_no_observed_state_and_no_file_change_ac_113_14(tmp_path, capsys, monkeypatch):  # AC-113.14
    rich(tmp_path)
    before = snapshot(tmp_path)

    def refuse(*a, **k):
        raise AssertionError("cplat model show made an outside call")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    rc, out, _ = show(tmp_path, capsys=capsys)
    assert rc == 0 and snapshot(tmp_path) == before
    for word in ("Synced", "Healthy", "Degraded", "digest", "sha256", "smoke", "firing"):
        assert word not in out


# ---------------- AC-113.15: the JSON ----------------

@pytest.fixture()
def doc(tmp_path, capsys):
    rich(tmp_path)
    rc, out, _ = show(tmp_path, "--json", capsys=capsys)
    assert rc == 0
    return json.loads(out)


def test_the_json_is_one_object_with_the_documented_keys_ac_113_15(tmp_path, capsys):  # AC-113.15
    small(tmp_path)
    rc, out, err = show(tmp_path, "--json", capsys=capsys)
    assert rc == 0 and err == ""
    d = json.loads(out)                                             # the whole stdout is one JSON object
    assert set(d) == {"schema", "system", "environments", "components", "resources", "instances", "resource_instances", "relations"}
    assert d["schema"] == 1
    assert d["system"] == {"name": "shop", "components": ["shop-api", "stock"], "resources": ["postgres"]}


def test_environments_are_a_list_in_promotion_order_ac_113_15(doc):  # AC-113.15
    assert [e["name"] for e in doc["environments"]] == ["dev", "staging", "prod"]
    dev, staging, prod = doc["environments"]
    assert (dev["host"], dev["url"], dev["policy"], dev["promotion"]) == ("{service}.{app}-dev.localhost", None, "Audit", "main")
    assert (staging["url"], staging["promotion"], prod["promotion"], prod["host"]) == ("https://{host}/{service}", "auto", "manual", None)
    assert set(dev["observability"]) >= {"ui", "exportTo", "alerts", "rules", "queryURL", "alertmanagerURL"}
    assert dev["observability"]["ui"] == "lgtm" and dev["observability"]["queryURL"] == "http://q.example.com"


def test_every_instance_has_the_documented_fields_ac_113_15(doc):  # AC-113.15
    fields = {"component", "environment", "image", "tag", "replicas", "namespace", "argo_application", "url", "promoted_from", "secrets"}
    assert doc["instances"] and all(fields <= set(i) for i in doc["instances"])
    by = {(i["component"], i["environment"]): i for i in doc["instances"]}
    staging = by[("shop-api", "staging")]
    assert (staging["tag"], staging["replicas"], staging["namespace"], staging["argo_application"]) == (None, 2, "shop-staging", "shop-api-staging")
    assert staging["promoted_from"] == "shop-api/dev" and by[("shop-api", "dev")]["promoted_from"] is None
    assert by[("shop-api", "dev")]["tag"] == "sha-" + SHA and by[("shop-api", "dev")]["url"] == "http://api.shop-dev.localhost:8088"
    assert by[("ai-ops", "prod")]["promoted_from"] is None and by[("stock", "dev")]["replicas"] is None
    assert by[("stock", "dev")]["namespace"] == "stock"


def test_secrets_list_names_and_keys_never_values_ac_113_15(doc):  # AC-113.15
    by = {(i["component"], i["environment"]): i for i in doc["instances"]}
    assert by[("shop-api", "staging")]["secrets"] == [
        {"name": "api-keys", "kind": "remote", "keys": ["STRIPE_KEY", "STRIPE_HOOK"], "store_key": "shop-staging-api-keys"},
        {"name": "api-pay", "kind": "remote", "keys": ["PAY_KEY"], "store_key": "shop-api/staging/api-pay"},
        {"name": "api-auth", "kind": "generate", "keys": ["DB_PASSWORD", "JWT_KEY"], "store_key": None}]
    comp = next(c for c in doc["components"] if c["name"] == "shop-api")
    assert [s["name"] for s in comp["secrets"]] == ["api-keys", "api-pay", "api-auth"] and comp["secret_refs"] == ["shared-config"]
    assert all(set(s) <= {"name", "kind", "keys", "store_key", "path"} for i in doc["instances"] for s in i["secrets"])


def test_components_resources_and_resource_instances_ac_113_15(doc):  # AC-113.15
    api = next(c for c in doc["components"] if c["name"] == "shop-api")
    assert (api["type"], api["lang"], api["shape"], api["repo"], api["uses"], api["environments"]) == (
        "service", "python", "service-python", "acme/shop-api", ["postgres"], ["dev", "staging"])
    assert api["external"] is None and api["metrics"] == "/metrics" and api["expose"] is True and api["promotion"] == {"staging": "manual"}
    stock = next(c for c in doc["components"] if c["name"] == "stock")
    assert stock["external"] == {"kind": "kustomize", "namespace": "stock"}
    assert doc["resources"] == [{"name": "postgres", "type": "database", "used_by": ["shop-api"]}]
    assert [(r["resource"], r["environment"], r["argo_application"], r["secret"]) for r in doc["resource_instances"]] == [
        ("postgres", "dev", "addon-postgres-dev", "shop-postgres-app"), ("postgres", "staging", "addon-postgres-staging", "shop-postgres-app")]
    assert doc["resource_instances"][0]["sizing"] == {"instances": 1, "version": 17, "storage": "1Gi"}


def test_relations_have_type_from_and_to_ac_113_15(doc):  # AC-113.15
    assert doc["relations"] and all(set(r) == {"type", "from", "to"} for r in doc["relations"])
    assert {r["type"] for r in doc["relations"]} == {"part_of", "uses", "instance_of", "runs_in", "promoted_from", "promotes_to"}
    assert {"type": "promoted_from", "from": "instance:shop-api/staging", "to": "instance:shop-api/dev"} in doc["relations"]


def test_the_json_has_no_observed_state_anywhere_ac_113_15(doc):  # AC-113.15
    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)
    assert not set(keys(doc)) & set(BARE_ENV)


# ---------------- AC-113.16: errors, options ----------------

def test_outside_a_gitops_app_it_fails_like_status_ac_113_16(tmp_path, capsys):  # AC-113.16
    rc = cplat.main(["status", "--repo-dir", str(tmp_path)])
    want = capsys.readouterr()
    assert rc == 1 and "fix:" in want.err
    rc, out, err = show(tmp_path, capsys=capsys)
    assert (rc, out, err) == (1, "", want.err)


def test_several_applications_need_app_and_app_picks_one_ac_113_16(tmp_path, capsys):  # AC-113.16
    small(tmp_path)
    write_app(tmp_path, [{"name": "blog", "repo": "acme/blog", "image": "i", "shape": "service-python"}], None, name="blog")
    rc, out, err = show(tmp_path, capsys=capsys)
    assert rc == 1 and out == "" and "shop" in err and "blog" in err
    rc, out, _ = show(tmp_path, "--app", "blog", capsys=capsys)
    assert rc == 0 and out.startswith("System: blog\n") and "shop-api" not in out
    rc, out, _ = show(tmp_path, "--app", "shop", "--json", capsys=capsys)
    assert rc == 0 and json.loads(out)["system"]["name"] == "shop"


def test_an_unknown_app_fails_like_status_ac_113_16(tmp_path, capsys):  # AC-113.16
    small(tmp_path)
    cplat.main(["status", "--repo-dir", str(tmp_path), "--app", "nope"])
    want = capsys.readouterr()
    assert show(tmp_path, "--app", "nope", capsys=capsys) == (1, "", want.err)


def test_repo_dir_is_resolved_like_status_ac_113_16(tmp_path, capsys, monkeypatch):  # AC-113.16
    small(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cplat.main(["model", "show"]) == 0
    assert "System: shop" in capsys.readouterr().out
    assert cplat.main(["model", "show", "--repo-dir", "."]) == 0


@pytest.mark.parametrize("fname", ["services.yaml", "app.yaml"])
def test_an_unparseable_file_exits_1_naming_it_ac_113_16(tmp_path, capsys, fname):  # AC-113.16
    d = small(tmp_path)
    (d / fname).write_text("services: [unclosed\n")
    before = snapshot(tmp_path)
    rc, out, err = show(tmp_path, capsys=capsys)
    assert rc == 1 and out == "" and f"ERROR: cannot parse applications/shop/{fname}" in err
    assert snapshot(tmp_path) == before


def test_an_unknown_environment_is_a_warning_not_an_error_ac_113_16(tmp_path, capsys):  # AC-113.16
    rich(tmp_path)
    rc, out, err = show(tmp_path, capsys=capsys)
    assert rc == 0
    assert err.strip().splitlines() == ["warning: batch lists unknown environment 'qa': no Instance"]
    assert "  batch  dev" in out and "batch  qa" not in out


def test_the_warning_does_not_break_the_json_on_stdout_ac_113_16(tmp_path, capsys):  # AC-113.16
    rich(tmp_path)
    rc, out, err = show(tmp_path, "--json", capsys=capsys)
    assert rc == 0 and json.loads(out)["schema"] == 1
    assert "warning: batch lists unknown environment 'qa'" in err
    assert not any(i["environment"] == "qa" for i in json.loads(out)["instances"])
