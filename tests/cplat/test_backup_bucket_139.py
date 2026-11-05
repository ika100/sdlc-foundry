"""Spec 139 acceptance tests: a bucket that is a backup target gets its instance in that environment without a using component
(AC-139.1 .. AC-139.5).

Contract: docs/specs/139-a-backup-bucket-without-a-using-component/design.md, "Decisions" and "Contract". The renderer runs as a
script in a hand-built checkout (resources_fixtures.ok), the model is loaded from the same system.yaml; nothing touches a cluster.
The e2e proof (AC-139.4) is checked in the text of tests/e2e/run.sh, which runs in the e2e workflow."""
import re

from backup_fixtures import S3, bdoc, ext_prod_bucket
from resources_fixtures import (
    APP,
    LABELS,
    addon_names,
    comp,
    external_secret,
    ok,
    platform_render_module,
    sets,
    tree,
    y,
)
from system_fixtures import ROOT, mod, write_system

DEV = {"to": "backups"}
BUCKET_VARS = re.compile(r"^(S3_|AWS_)")
BUCKET_KEYS = ["endpoint", "bucket", "region", "forcePathStyle", "accessKeyId", "secretAccessKey"]
SEAWEED_CORE = {"bucket.yaml", "credentials.yaml", "identity.yaml", "kustomization.yaml", "seaweed.yaml"}


def no_user(dbb=None, envb=None, bucket_kw=None, envs=("dev", "staging", "prod")) -> dict:
    """orders-db used by `api`; the bucket `backups` is used by no component."""
    return bdoc(dbb=dbb, envb=envb, bucket_kw=bucket_kw, comps={"api": comp("api", ["orders-db"], envs=envs)})


def used_files(tmp_path, env="prod") -> list[str]:
    """The addon files a bucket that `api` uses gets in `env`: what a backup-only in-cluster bucket must get too."""
    return files_of(ok(tmp_path / "used", bdoc(dbb={env: DEV})), env)


def files_of(g, env, name="backups") -> list[str]:
    base = f"{APP}/addons/{env}/{name}/"
    return sorted(k[len(base):] for k in g if k.startswith(base))


def bucket_vars(g, env, name="api") -> list[str]:
    containers = y(g, f"{APP}/overlays/{env}/{name}/deployment.yaml")["spec"]["template"]["spec"]["containers"]
    names = [e["name"] for c in containers for e in c.get("env") or []]
    refs = [e["valueFrom"]["secretKeyRef"]["name"] for c in containers for e in c.get("env") or []
            if "secretKeyRef" in (e.get("valueFrom") or {})]
    refs += [f["secretRef"]["name"] for c in containers for f in c.get("envFrom") or [] if "secretRef" in f]
    return [n for n in names if BUCKET_VARS.match(n)] + [r for r in refs if r == "shop-backups-app"]


def ext_secret_doc(env="prod", labels=False) -> dict:
    doc = external_secret("backups", f"shop-{env}-backups")
    doc["spec"]["data"] = [{"secretKey": k, "remoteRef": {"key": f"shop-{env}-backups", "property": k}} for k in BUCKET_KEYS]
    if labels:
        doc["spec"]["target"]["template"] = {"engineVersion": "v2", "mergePolicy": "Merge",
                                             "metadata": {"labels": {"app.kubernetes.io/name": "backups", **LABELS}}}
    return doc


# ---------------- AC-139.1: the instance and its credentials exist for the backup machinery ----------------

def test_a_database_backup_to_a_bucket_no_component_uses_renders_ac_139_1(tmp_path):  # AC-139.1
    g = ok(tmp_path, no_user(dbb={"prod": DEV}))
    assert SEAWEED_CORE <= set(files_of(g, "prod")) and files_of(g, "prod") == used_files(tmp_path)
    assert "backups" in addon_names(g, "prod")
    store = y(g, f"{APP}/addons/prod/orders-db/objectstore.yaml")["spec"]["configuration"]
    assert store["s3Credentials"]["accessKeyId"] == {"name": "shop-backups-app", "key": "accessKeyId"}
    assert store["endpointURL"] == "http://shop-backups-filer.shop-prod.svc:8333"


def test_the_backup_only_bucket_is_the_same_addon_a_using_component_gets_ac_139_1(tmp_path):  # AC-139.1
    g = ok(tmp_path / "a", no_user(dbb={"prod": DEV}))
    used = ok(tmp_path / "b", bdoc(dbb={"prod": DEV}))
    for f in used_files(tmp_path):
        assert g[f"{APP}/addons/prod/backups/{f}"] == used[f"{APP}/addons/prod/backups/{f}"], f


def test_an_environment_backup_to_a_bucket_no_component_uses_renders_ac_139_1(tmp_path):  # AC-139.1
    g = ok(tmp_path, no_user(envb={"prod": DEV}))
    assert SEAWEED_CORE <= set(files_of(g, "prod"))
    assert y(g, f"{APP}/addons/prod/backups/credentials.yaml")["metadata"]["labels"] == {"app.kubernetes.io/name": "backups", **LABELS}
    assert f"{APP}/backup/prod/schedule.yaml" in g
    ext = y(g, f"{APP}/backup/prod/externalsecret.yaml")
    assert {d["remoteRef"]["key"] for d in ext["spec"]["data"]} == {"shop-backups-app"}


def test_the_bucket_has_no_instance_where_it_is_neither_used_nor_a_target_ac_139_1(tmp_path):  # AC-139.1
    g = ok(tmp_path, no_user(dbb={"prod": DEV}))
    for env in ("dev", "staging"):
        assert files_of(g, env) == [] and "backups" not in addon_names(g, env), env


def test_a_database_backup_where_no_component_runs_creates_no_bucket_ac_139_1(tmp_path):  # AC-139.1 (non-goal: no instance without a component)
    g = ok(tmp_path, no_user(dbb={"prod": DEV}, envs=("dev", "staging")))
    assert files_of(g, "prod") == [] and files_of(g, "prod", "orders-db") == []


def test_an_external_backup_only_bucket_gets_its_external_secret_in_the_addon_directory_ac_139_1(tmp_path):  # AC-139.1, AC-139.4
    g = ok(tmp_path, no_user(dbb={"prod": DEV}, bucket_kw=ext_prod_bucket()))
    assert files_of(g, "prod") == ["externalsecret-shop-backups-app.yaml", "kustomization.yaml"]
    assert y(g, f"{APP}/addons/prod/backups/externalsecret-shop-backups-app.yaml") == ext_secret_doc()
    assert y(g, f"{APP}/addons/prod/backups/kustomization.yaml") == {
        "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": ["externalsecret-shop-backups-app.yaml"]}
    assert "backups" in addon_names(g, "prod")
    assert not [k for k in g if k.startswith(f"{APP}/overlays/prod/") and k.endswith("externalsecret-shop-backups-app.yaml")]
    c = y(g, f"{APP}/addons/prod/orders-db/objectstore.yaml")["spec"]["configuration"]
    assert c["destinationPath"] == "s3://acme-backups/databases" and c["endpointURL"] == S3["endpoint"]


def test_an_external_environment_target_carries_the_velero_labels_ac_139_1(tmp_path):  # AC-139.1, AC-139.4
    g = ok(tmp_path, no_user(envb={"prod": DEV}, bucket_kw=ext_prod_bucket()))
    assert y(g, f"{APP}/addons/prod/backups/externalsecret-shop-backups-app.yaml") == ext_secret_doc(labels=True)


def test_an_external_bucket_a_component_uses_keeps_its_external_secret_in_the_overlay_ac_139_1(tmp_path):  # AC-139.1
    g = ok(tmp_path, bdoc(dbb={"prod": DEV}, bucket_kw=ext_prod_bucket()))
    assert f"{APP}/overlays/prod/api/externalsecret-shop-backups-app.yaml" in g
    assert files_of(g, "prod") == [] and "backups" not in addon_names(g, "prod")


def test_the_backup_only_bucket_needs_its_operator_ac_139_1(tmp_path):  # AC-139.1
    g = ok(tmp_path, no_user(dbb={"prod": DEV}))
    assert "operators/apps/seaweedfs.yaml" in g


# ---------------- AC-139.2: the app gets none of the bucket's variables ----------------

def test_a_component_that_does_not_use_the_backup_bucket_gets_none_of_its_variables_ac_139_2(tmp_path):  # AC-139.2
    g = ok(tmp_path, no_user(dbb={"prod": DEV, "dev": DEV}, envb={"staging": DEV}))
    for env in ("dev", "staging", "prod"):
        assert bucket_vars(g, env) == [], env


def test_a_component_that_uses_the_bucket_still_gets_its_variables_ac_139_2(tmp_path):  # AC-139.2
    g = ok(tmp_path, bdoc(dbb={"prod": DEV}))
    assert "AWS_ACCESS_KEY_ID" in bucket_vars(g, "prod")


# ---------------- AC-139.3: removing the uses keeps render and backups working ----------------

def test_removing_the_uses_changes_only_the_component_overlay_where_the_backups_are_ac_139_3(tmp_path):  # AC-139.3
    before = ok(tmp_path / "a", bdoc(dbb={"prod": DEV}, envb={"prod": DEV}))
    after = ok(tmp_path / "b", no_user(dbb={"prod": DEV}, envb={"prod": DEV}))
    prod = [k for k in set(before) | set(after) if "/prod/" in k or k.startswith("operators/")]
    changed = sorted(k for k in prod if before.get(k) != after.get(k))
    assert changed == [f"{APP}/overlays/prod/api/deployment.yaml"], changed
    assert sets(after)["shop-addons-prod"] == sets(before)["shop-addons-prod"]
    assert sets(after)["shop-backup-prod"] == sets(before)["shop-backup-prod"]


def test_the_restore_and_status_model_still_has_the_database_and_bucket_ac_139_3(tmp_path):  # AC-139.3, AC-139.5
    write_system(tmp_path, no_user(dbb={"prod": DEV}))
    m = mod("model").load_dir(tmp_path / APP)
    ri = {(r.resource, r.environment): r for r in m.resource_instances}
    assert ri[("orders-db", "prod")].backup == {"to": "backups", "schedule": "0 3 * * *", "retention": "30d"}
    assert ("backups", "prod") in ri


def test_the_changelog_fragment_says_how_to_migrate_ac_139_3():  # AC-139.3
    frags = list((ROOT / "docs" / "changelog.d").glob("139-*.fixed.md"))
    assert len(frags) == 1, frags
    text = frags[0].read_text()
    assert "(#418)" in text and "`uses`" in text and "**Action:**" in text


def test_the_backup_guide_no_longer_asks_for_a_using_component_ac_139_3():  # AC-139.3
    text = (ROOT / "docs" / "BACKUP-AND-RESTORE.md").read_text()
    assert "a component that runs there uses it" not in text
    assert "no component needs to use" in text


# ---------------- AC-139.4: frozen render and the e2e ----------------

def test_the_rendered_backup_only_system_is_stable_ac_139_4(tmp_path):  # AC-139.4
    doc = no_user(dbb={"prod": DEV}, envb={"prod": DEV})
    first = ok(tmp_path / "a", doc)
    assert ok(tmp_path / "b", doc) == first
    assert y(first, f"{APP}/addons/prod/backups/kustomization.yaml")["resources"] == [f for f in files_of(first, "prod") if f != "kustomization.yaml"]


def test_the_e2e_backs_up_into_a_bucket_no_component_uses_ac_139_4():  # AC-139.4 (needs a cluster)
    text = (ROOT / "tests" / "e2e" / "run.sh").read_text()
    block = text[text.index('if in_part "backups and restores (spec 117)" backups; then'):]
    assert not re.search(r'\["uses"\][^\n]*"backups"', block) and "must be used by a component" not in block
    assert re.search(r"e2e-web.*(S3_|AWS_)|(S3_|AWS_).*e2e-web", block), "the e2e checks e2e-web has none of the bucket's variables"


# ---------------- AC-139.5: the model agrees with render ----------------

def test_the_model_lists_the_backup_only_bucket_instance_where_render_creates_it_ac_139_5(tmp_path):  # AC-139.5
    write_system(tmp_path, no_user(dbb={"prod": DEV}, envb={"staging": DEV}))
    r = platform_render_module("render_139_model")
    system = r.load_system(tmp_path / APP)
    rendered = {(n, e) for n, e, _, _ in r.resource_instances(system)}
    m = mod("model").load_dir(tmp_path / APP)
    assert {(ri.resource, ri.environment) for ri in m.resource_instances} == rendered
    assert {e for n, e in rendered if n == "backups"} == {"staging", "prod"}


def test_the_model_names_the_addon_application_of_an_external_backup_only_bucket_ac_139_5(tmp_path):  # AC-139.5
    write_system(tmp_path, no_user(dbb={"prod": DEV}, bucket_kw=ext_prod_bucket()))
    m = mod("model").load_dir(tmp_path / APP)
    ri = {(r.resource, r.environment): r for r in m.resource_instances}
    assert ri[("backups", "prod")].external is True
    assert ri[("backups", "prod")].argo_application == "addon-backups-prod"


def test_nothing_is_written_outside_the_tree_ac_139_1(tmp_path):  # AC-139.1
    g = ok(tmp_path, no_user(dbb={"prod": DEV}))
    assert g == tree(tmp_path)
