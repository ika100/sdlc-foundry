"""Spec 128 acceptance tests, the renderer part: every generated credential (cache, broker, bucket, generated component secrets) is written
exactly once by a credentials Job (AC-128.1 .. .8 render side, AC-128.12).

Contract: design.md "Rendered files", "plan.json". The renderer runs as a script in a hand-built checkout; nothing touches a cluster. The
behaviour of the Job's program is in test_credentials_128_script.py. A test names its criterion in a `# AC-128.n` comment."""
import yaml

from broker_fixtures import bdir, broker, bsys, wide
from cache_fixtures import cache, csys, labels as cache_labels
from credentials_fixtures import (CRED_FILES, GONE, addon, all_docs, check_no_files, check_owner_files, cred, files_in, generator_backed,
                                  overlay, plan_of, written_twice)
from resources_fixtures import ENVS, comp, ok, system

NS = "shop-{}"


def bucket_sys(**top):
    return system({"files": {"type": "bucket"}}, {"api": comp("api", ["files"])}, **top)


def gen_sys(replicas=2, **secret):
    sec = {"name": "api-auth", "generate": ["JWT_KEY", "SESSION_KEY"], **secret}
    return system(None, {"api": comp("api", secrets=[sec, {"name": "api-pay", "remote": {"keys": ["PAY_KEY"]}}],
                                     instances={e: {"replicas": replicas} for e in ENVS})})


# ---------------- cache: AC-128.1, .3 ----------------

def test_a_cache_renders_the_five_credentials_files_in_every_environment_ac_128_1(tmp_path):  # AC-128.1
    g = ok(tmp_path, csys())
    for env in ENVS:
        check_owner_files(g, addon(env, "sessions"), "shop-sessions", NS.format(env), cache_labels(), ["shop-sessions-app"],
                          ["shop-sessions-password"], ["shop-sessions-0"])


def test_the_cache_plan_creates_the_secret_with_the_password_and_the_url_ac_128_1(tmp_path):  # AC-128.1
    g = ok(tmp_path, csys())
    for env in ENVS:
        ns = NS.format(env)
        assert plan_of(g, addon(env, "sessions")) == {
            "namespace": ns,
            "secrets": [{"name": "shop-sessions-app", "labels": cache_labels(), "generate": {"password": 32},
                         "data": {"url": "redis://default:{{ .password }}@" + f"shop-sessions.{ns}.svc:6379/0", "host": f"shop-sessions.{ns}.svc", "port": "6379"}}],
            "retire": {"externalSecrets": ["shop-sessions-app"], "generators": ["shop-sessions-password"]},
            "verify": {"engine": "valkey", "port": 6379, "pods": ["shop-sessions-0"],
                       "users": [{"secret": "shop-sessions-app", "key": "password", "user": "default", "env": "VALKEY_PASSWORD"}]}}


def test_the_cache_server_still_reads_its_password_by_secret_key_ref_ac_128_1(tmp_path):  # AC-128.1
    g = ok(tmp_path, csys())
    sts = yaml.safe_load(g[f"{addon('dev', 'sessions')}/statefulset.yaml"])
    env = sts["spec"]["template"]["spec"]["containers"][0]["env"]
    assert {"name": "VALKEY_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "shop-sessions-app", "key": "password"}}} in env
    assert "credentials-job.yaml" in files_in(g, addon("dev", "sessions")), "the Job that writes the Secret is rendered with the server"


def test_the_cache_stops_rendering_the_generator_backed_objects_ac_128_3(tmp_path):  # AC-128.3
    g = ok(tmp_path, csys())
    for env in ENVS:
        check_no_files(g, addon(env, "sessions"), GONE["cache"])
        assert "credentials-job.yaml" in files_in(g, addon(env, "sessions"))


def test_two_caches_get_a_job_each_with_their_own_names_ac_128_1(tmp_path):  # AC-128.1
    g = ok(tmp_path, csys({"sessions": cache(), "ratelimit": cache(persistence=True)}, {"api": comp("api", ["sessions", "ratelimit"])}))
    for n in ("sessions", "ratelimit"):
        docs = cred(g, addon("dev", n))
        assert docs["credentials-job.yaml"]["metadata"]["name"].startswith(f"shop-{n}-credentials-")
        assert plan_of(g, addon("dev", n))["secrets"][0]["name"] == f"shop-{n}-app"


def test_an_external_cache_has_no_credentials_job_ac_128_3(tmp_path):  # AC-128.3
    g = ok(tmp_path, csys({"sessions": cache(instances={"prod": {"external": True}})}))
    assert "credentials-job.yaml" in files_in(g, addon("dev", "sessions"))
    assert not [p for p in g if "/prod/" in p and "/credentials-" in p]


def test_the_job_name_changes_with_the_plan_ac_128_3(tmp_path):  # AC-128.3
    a = ok(tmp_path / "a", csys())
    b = ok(tmp_path / "b", csys({"sessions": cache(persistence=True)}))
    other = ok(tmp_path / "c", csys({"sessions": cache()}))
    name = lambda g: cred(g, addon("dev", "sessions"))["credentials-job.yaml"]["metadata"]["name"]
    assert name(a) == name(other), "the same inputs render the same Job"
    assert name(a).split("-")[-1] == name(b).split("-")[-1], "a sizing change leaves the plan, so the hash"


# ---------------- broker: AC-128.4, .5, .6 ----------------

def broker_pods(n):
    return [f"shop-bus-{i}" for i in range(n)]


def test_a_broker_renders_the_five_credentials_files_in_every_environment_ac_128_4(tmp_path):  # AC-128.4
    g = ok(tmp_path, bsys({"bus": broker(replicas=3)}))
    for env in ENVS:
        docs = cred(g, bdir(env))
        assert sorted(docs) == sorted(CRED_FILES)
        rules = docs["credentials-role.yaml"]["rules"]
        names = sorted(rules[1]["resourceNames"])
        assert names == ["shop-bus-api-app", "shop-bus-nack", "shop-bus-web-app"]
        assert sorted(rules[-1]["resourceNames"]) == broker_pods(3) and rules[-1]["resources"] == ["pods"]
        assert rules[0] == {"apiGroups": [""], "resources": ["secrets"], "verbs": ["create"]}
        lab = docs["credentials-job.yaml"]["metadata"]["labels"]
        check_owner_files(g, bdir(env), "shop-bus", NS.format(env), lab, names, ["shop-bus-password"], broker_pods(3))


def test_the_broker_plan_holds_the_nack_and_every_component_user_ac_128_4(tmp_path):  # AC-128.4
    g = ok(tmp_path, bsys({"bus": broker(replicas=3)}))
    for env in ENVS:
        ns = NS.format(env)
        plan = plan_of(g, bdir(env))
        by = {s["name"]: s for s in plan["secrets"]}
        assert sorted(by) == ["shop-bus-api-app", "shop-bus-nack", "shop-bus-web-app"]
        assert by["shop-bus-nack"]["generate"] == {"password": 32} and by["shop-bus-nack"]["data"] == {"user": "_nack"}
        for c in ("api", "web"):
            s = by[f"shop-bus-{c}-app"]
            assert s["generate"] == {"password": 32} and s["data"] == {"url": f"nats://shop-bus.{ns}.svc:4222", "user": c}
        assert plan["retire"]["generators"] == ["shop-bus-password"]
        assert sorted(plan["retire"]["externalSecrets"]) == sorted(by)
        v = plan["verify"]
        assert (v["engine"], v["port"], v["pods"]) == ("nats", 4222, broker_pods(3))
        users = {u["secret"]: u for u in v["users"]}
        assert users["shop-bus-nack"] == {"secret": "shop-bus-nack", "key": "password", "user": "_nack", "env": "ADMIN_PASSWORD"}
        assert users["shop-bus-web-app"] == {"secret": "shop-bus-web-app", "key": "password", "user": "web", "env": "USER_WEB_PASSWORD"}
        assert len(users) == 3


def test_the_broker_stops_rendering_generator_backed_objects_ac_128_6(tmp_path):  # AC-128.6
    g = ok(tmp_path, bsys())
    for env in ENVS:
        check_no_files(g, bdir(env), GONE["broker"])


def test_a_component_added_to_a_broker_is_one_more_secret_in_the_plan_ac_128_5(tmp_path):  # AC-128.5
    before = ok(tmp_path / "a", bsys())
    after = ok(tmp_path / "b", wide())
    names = lambda g: sorted(s["name"] for s in plan_of(g, bdir("dev"))["secrets"])
    assert names(after) == ["shop-bus-api-app", "shop-bus-nack", "shop-bus-web-app", "shop-bus-worker-app"]
    assert names(before) == ["shop-bus-api-app", "shop-bus-nack", "shop-bus-web-app"]
    assert (job := cred(after, bdir("dev"))["credentials-job.yaml"]["metadata"]["name"]) != cred(before, bdir("dev"))["credentials-job.yaml"]["metadata"]["name"], job
    assert "shop-bus-worker-app" in cred(after, bdir("dev"))["credentials-role.yaml"]["rules"][1]["resourceNames"]


def test_the_broker_server_keeps_reading_its_passwords_from_secrets_ac_128_5(tmp_path):  # AC-128.5
    g = ok(tmp_path, bsys())
    text = g[f"{bdir('dev')}/server.yaml"]
    assert "shop-bus-nack" in text and "shop-bus-api-app" in text and "shop-bus-web-app" in text
    assert "credentials-job.yaml" in files_in(g, bdir("dev"))


# ---------------- bucket: AC-128.7 ----------------

def test_a_bucket_renders_the_five_credentials_files_without_a_verify_ac_128_7(tmp_path):  # AC-128.7
    g = ok(tmp_path, bucket_sys())
    for env in ENVS:
        ns = NS.format(env)
        docs = cred(g, addon(env, "files"))
        lab = docs["credentials-job.yaml"]["metadata"]["labels"]
        check_owner_files(g, addon(env, "files"), "shop-files", ns, lab, ["shop-files-app"], ["shop-files-access-key", "shop-files-secret-key"])
        plan = plan_of(g, addon(env, "files"))
        assert "verify" not in plan
        assert plan["secrets"] == [{"name": "shop-files-app", "labels": {}, "generate": {"accessKeyId": 20, "secretAccessKey": 40},
                                    "data": {"endpoint": f"http://shop-files-filer.{ns}.svc:8333", "bucket": "shop-files", "region": "us-east-1",
                                             "forcePathStyle": "true"}}]
        assert plan["retire"] == {"externalSecrets": ["shop-files-app"], "generators": ["shop-files-access-key", "shop-files-secret-key"]}
        assert not [r for r in docs["credentials-role.yaml"]["rules"] if r["resources"] == ["pods"]]


def test_the_bucket_stops_rendering_generator_backed_objects_ac_128_7(tmp_path):  # AC-128.7
    g = ok(tmp_path, bucket_sys())
    for env in ENVS:
        check_no_files(g, addon(env, "files"), GONE["bucket"])


def test_the_backup_target_bucket_secret_keeps_the_labels_velero_reads_ac_128_7(tmp_path):  # AC-128.7
    doc = bucket_sys()
    doc["environments"]["dev"]["backup"] = {"to": "files"}
    g = ok(tmp_path, doc)
    secret = plan_of(g, addon("dev", "files"))["secrets"][0]
    assert secret["labels"] == {"app.kubernetes.io/name": "files", "app.kubernetes.io/part-of": "shop", "app.kubernetes.io/managed-by": "gitops-app"}
    assert plan_of(g, addon("staging", "files"))["secrets"][0]["labels"] == {}


# ---------------- generated component secrets: AC-128.8 ----------------

def test_a_component_with_a_generated_secret_gets_the_credentials_files_ac_128_8(tmp_path):  # AC-128.8
    g = ok(tmp_path, gen_sys())
    for env in ENVS:
        docs = cred(g, overlay(env, "api"))
        lab = docs["credentials-job.yaml"]["metadata"]["labels"]
        check_owner_files(g, overlay(env, "api"), "api", NS.format(env), lab, ["api-auth"], ["api-password"])
        plan = plan_of(g, overlay(env, "api"))
        assert [s["name"] for s in plan["secrets"]] == ["api-auth"]
        assert plan["secrets"][0]["generate"] == {"JWT_KEY": 32, "SESSION_KEY": 32}
        assert not plan["secrets"][0].get("data")
        assert plan["retire"] == {"externalSecrets": ["api-auth"], "generators": ["api-password"]}
        assert "verify" not in plan


def test_a_generated_secret_length_is_the_length_of_every_key_ac_128_8(tmp_path):  # AC-128.8
    g = ok(tmp_path, gen_sys(length=48))
    assert plan_of(g, overlay("dev", "api"))["secrets"][0]["generate"] == {"JWT_KEY": 48, "SESSION_KEY": 48}


def test_the_replicas_read_the_one_secret_by_name_ac_128_8(tmp_path):  # AC-128.8
    g = ok(tmp_path, gen_sys(replicas=3))
    dep = yaml.safe_load(g[f"{overlay('dev', 'api')}/deployment.yaml"])
    assert dep["spec"]["replicas"] == 3
    assert "credentials-job.yaml" in files_in(g, overlay("dev", "api")), "one Job writes the Secret, not one writer per replica"
    text = yaml.safe_dump(dep)
    assert "api-auth" in text


def test_the_generated_secret_files_are_gone_and_the_remote_one_stays_ac_128_8(tmp_path):  # AC-128.8
    g = ok(tmp_path, gen_sys())
    fs = files_in(g, overlay("dev", "api"))
    assert "externalsecret-api-auth.yaml" not in fs and "password-generator.yaml" not in fs
    es = yaml.safe_load(fs["externalsecret-api-pay.yaml"])
    assert es["kind"] == "ExternalSecret" and not generator_backed(es)
    kz = yaml.safe_load(fs["kustomization.yaml"])
    assert "externalsecret-api-pay.yaml" in kz["resources"] and "externalsecret-api-auth.yaml" not in kz["resources"]
    assert all(f in kz["resources"] for f in CRED_FILES)


def test_a_component_without_a_generated_secret_gets_no_credentials_files_ac_128_8(tmp_path):  # AC-128.8
    g = ok(tmp_path, system(None, {"api": comp("api", secrets=[{"name": "api-pay", "remote": {"keys": ["PAY_KEY"]}}]),
                                   "web": comp("web", secrets=[{"name": "web-auth", "generate": ["K"]}])}))
    assert "credentials-job.yaml" in files_in(g, overlay("dev", "web"))
    assert not [p for p in g if "/overlays/dev/api/credentials-" in p]
    assert "externalsecret-api-pay.yaml" in files_in(g, overlay("dev", "api"))


# ---------------- AC-128.12: nothing generator-backed writes a credential, anywhere ----------------

CASES = {"cache": (lambda: csys(), "sessions"), "broker": (lambda: bsys(), "bus"), "bucket": (lambda: bucket_sys(), "files")}


def test_no_generator_backed_object_is_rendered_for_a_cache_a_broker_or_a_bucket_ac_128_12(tmp_path):  # AC-128.12
    for typ, (build, name) in CASES.items():
        g = ok(tmp_path / typ, build())
        assert not written_twice(g, f"applications/shop/addons"), (typ, written_twice(g, "applications/shop/addons"))
        for env in ENVS:
            assert "credentials-job.yaml" in files_in(g, addon(env, name)), (typ, env)


def test_no_generator_backed_object_is_rendered_for_a_generated_component_secret_ac_128_12(tmp_path):  # AC-128.12
    g = ok(tmp_path, gen_sys())
    assert not written_twice(g, "applications/shop/overlays"), written_twice(g, "applications/shop/overlays")
    assert "credentials-job.yaml" in files_in(g, overlay("dev", "api"))


def test_no_rendered_object_of_any_kind_is_a_password_generator_ac_128_12(tmp_path):  # AC-128.12
    g = ok(tmp_path, system({"sessions": cache(), "bus": broker(), "files": {"type": "bucket"}},
                            {"api": comp("api", ["sessions", "files"], provides=["orders"], secrets=[{"name": "api-auth", "generate": ["K"]}]),
                             "web": comp("web", consumes=["orders"])}, apis={"orders": {"type": "events"}}))
    assert not [p for p, d in all_docs(g) if d.get("kind") == "Password"]
    assert not [p for p, d in all_docs(g) if generator_backed(d)]
    assert len(written_twice(OLD_FORM, addon("dev", "sessions"))) == 2, "the check does flag the 5.4 form"


def _old():
    from cache_fixtures import expected_externalsecret, expected_generator, expected_statefulset
    return {f"{addon('dev', 'sessions')}/externalsecret.yaml": yaml.safe_dump(expected_externalsecret()),
            f"{addon('dev', 'sessions')}/password-generator.yaml": yaml.safe_dump(expected_generator()),
            f"{addon('dev', 'sessions')}/statefulset.yaml": yaml.safe_dump(expected_statefulset())}


OLD_FORM = _old()


def test_every_generated_credential_has_one_writer_the_job_ac_128_12(tmp_path):  # AC-128.12
    """A Secret named in a plan is not the target of any other rendered object, so only the Job writes it."""
    comps = {"api": comp("api", ["sessions", "files"], provides=["orders"]), "web": comp("web", consumes=["orders"])}   # unused resources render nothing
    g = ok(tmp_path, bsys({"bus": broker(), "sessions": cache(), "files": {"type": "bucket"}}, comps))
    planned = set()
    for env in ENVS:
        for name in ("bus", "sessions", "files"):
            planned |= {s["name"] for s in plan_of(g, addon(env, name))["secrets"]}
    assert planned
    for path, d in all_docs(g):
        if d.get("kind") == "ExternalSecret":
            assert d["spec"]["target"]["name"] not in planned, path
        if d.get("kind") == "Secret":
            assert d["metadata"]["name"] not in planned, f"{path}: a rendered Secret manifest also writes a planned credential"
