"""Spec 128 acceptance tests, the program of the credentials Job (render.py's CREDENTIALS_SCRIPT, `create.py`): retire, create or keep,
the JSON patch rules, verify, probe and restart (AC-128.1, .3, .4, .6, .7, .8, .10).

Contract: design.md "create.py behaviour". The program runs as a subprocess against a fake Kubernetes API (an http.server;
CREDENTIALS_API_URL=http://…, CREDENTIALS_SA_DIR with a token) and fake valkey and NATS servers on 127.0.0.1 (credentials_fixtures)."""
import json
import re

import pytest

from credentials_fixtures import ALNUM, FakeKube, FakeNats, FakeValkey, bucket_plan, cache_plan, nats_plan, run_script


@pytest.fixture
def kube():
    k = FakeKube()
    yield k
    k.close()


def out(p) -> str:
    return p.stdout + p.stderr


def no_values_printed(p, kube):
    text = out(p)
    for name in kube.secrets:
        for v in kube.values(name).values():
            if len(v) >= 16:
                assert v not in text, f"a value of {name} was printed"


# ---------------- create ----------------

def test_a_missing_secret_is_created_with_a_32_character_password_and_the_url_ac_128_1(tmp_path, kube):  # AC-128.1
    p = run_script(tmp_path, kube, cache_plan())
    assert p.returncode == 0, out(p)
    v = kube.values("shop-sessions-app")
    assert len(v["password"]) == 32 and ALNUM.match(v["password"])
    assert v["url"] == f"redis://default:{v['password']}@shop-sessions.shop-dev.svc:6379/0"
    assert (v["host"], v["port"]) == ("shop-sessions.shop-dev.svc", "6379")
    meta = kube.secrets["shop-sessions-app"]["metadata"]
    assert meta["labels"] == {"app.kubernetes.io/name": "sessions"} and kube.secrets["shop-sessions-app"]["type"] == "Opaque"
    assert "created shop-sessions-app" in out(p)
    no_values_printed(p, kube)


def test_every_request_carries_the_bearer_token_ac_128_1(tmp_path, kube):  # AC-128.1
    run_script(tmp_path, kube, cache_plan())
    assert kube.log and all(c["auth"] == f"Bearer {kube.token}" for c in kube.log)


def test_each_generated_key_is_independent_and_has_its_length_ac_128_7(tmp_path, kube):  # AC-128.7
    p = run_script(tmp_path, kube, bucket_plan())
    assert p.returncode == 0, out(p)
    v = kube.values("shop-files-app")
    assert len(v["accessKeyId"]) == 20 and len(v["secretAccessKey"]) == 40
    assert ALNUM.match(v["accessKeyId"]) and ALNUM.match(v["secretAccessKey"])
    assert v["secretAccessKey"][:20] != v["accessKeyId"]
    assert (v["endpoint"], v["bucket"], v["region"], v["forcePathStyle"]) == ("http://shop-files-filer.shop-dev.svc:8333", "shop-files", "us-east-1", "true")


def test_two_generated_secrets_get_different_values_ac_128_8(tmp_path, kube):  # AC-128.8
    plan = {"namespace": "shop-dev", "secrets": [{"name": "api-auth", "labels": {}, "generate": {"JWT_KEY": 32, "SESSION_KEY": 32}, "data": {}},
                                                 {"name": "api-other", "labels": {}, "generate": {"JWT_KEY": 32}, "data": {}}],
            "retire": {"externalSecrets": ["api-auth", "api-other"], "generators": ["api-password"]}}
    p = run_script(tmp_path, kube, plan)
    assert p.returncode == 0, out(p)
    a, b = kube.values("api-auth"), kube.values("api-other")
    assert len({a["JWT_KEY"], a["SESSION_KEY"], b["JWT_KEY"]}) == 3


def test_a_secret_that_exists_keeps_its_values_and_is_not_written_ac_128_3(tmp_path, kube):  # AC-128.3
    kube.put_secret("shop-sessions-app", {"password": "old-password", "url": "redis://default:old-password@shop-sessions.shop-dev.svc:6379/0",
                                          "host": "shop-sessions.shop-dev.svc", "port": "6379"}, labels={"app.kubernetes.io/name": "sessions"})
    before = kube.secrets["shop-sessions-app"]
    rv = before["metadata"]["resourceVersion"]
    data = dict(before["data"])
    p = run_script(tmp_path, kube, cache_plan())
    assert p.returncode == 0, out(p)
    assert kube.secrets["shop-sessions-app"]["data"] == data and kube.secrets["shop-sessions-app"]["metadata"]["resourceVersion"] == rv
    assert not kube.calls("PATCH") and not kube.calls("DELETE", "/secrets/")
    assert "kept shop-sessions-app" in out(p)


def test_running_again_after_a_create_changes_nothing_ac_128_3(tmp_path, kube):  # AC-128.3
    assert run_script(tmp_path, kube, cache_plan()).returncode == 0
    first, rv = kube.values("shop-sessions-app"), kube.secrets["shop-sessions-app"]["metadata"]["resourceVersion"]
    for _ in range(2):
        p = run_script(tmp_path, kube, cache_plan())
        assert p.returncode == 0 and "kept shop-sessions-app" in out(p)
    assert kube.values("shop-sessions-app") == first and kube.secrets["shop-sessions-app"]["metadata"]["resourceVersion"] == rv
    assert not kube.calls("PATCH")


def test_a_broker_secret_that_exists_keeps_its_passwords_on_a_second_run_ac_128_6(tmp_path, kube):  # AC-128.6
    n = FakeNats({})
    try:
        plan = nats_plan(n.port)
        del plan["verify"]
        assert run_script(tmp_path, kube, plan).returncode == 0
        first = {s: kube.values(s) for s in kube.secrets}
        assert run_script(tmp_path, kube, plan).returncode == 0
        assert {s: kube.values(s) for s in kube.secrets} == first and not kube.calls("PATCH")
    finally:
        n.close()


# ---------------- keep: the JSON patch ----------------

def patches(kube):
    return [c for c in kube.calls("PATCH")]


def test_a_missing_key_is_added_and_no_existing_value_is_touched_ac_128_6(tmp_path, kube):  # AC-128.6
    kube.put_secret("shop-bus-api-app", {"password": "pw-api-kept-value"}, labels={})
    plan = nats_plan(1, comps=("api",))
    del plan["verify"]
    p = run_script(tmp_path, kube, plan)
    assert p.returncode == 0, out(p)
    v = kube.values("shop-bus-api-app")
    assert v["password"] == "pw-api-kept-value" and v["user"] == "api" and v["url"] == "nats://shop-bus.shop-dev.svc:4222"
    ps = patches(kube)
    assert len(ps) == 1 and ps[0]["ctype"] == "application/json-patch+json"
    ops = ps[0]["body"]
    assert ops[0] == {"op": "test", "path": "/metadata/resourceVersion", "value": "101"} or ops[0]["op"] == "test" and ops[0]["path"] == "/metadata/resourceVersion"
    assert not [o for o in ops if o["path"] == "/data/password"], ops
    assert {o["path"] for o in ops[1:]} >= {"/data/url", "/data/user"}
    assert all(o["op"] in ("test", "add", "remove", "replace") for o in ops)
    assert "kept shop-bus-api-app" in out(p) and "added keys" in out(p)


def test_a_missing_generated_key_gets_a_new_value_and_the_others_stay_ac_128_8(tmp_path, kube):  # AC-128.8
    kube.put_secret("api-auth", {"JWT_KEY": "j" * 32})
    plan = {"namespace": "shop-dev", "secrets": [{"name": "api-auth", "labels": {}, "generate": {"JWT_KEY": 32, "SESSION_KEY": 32}, "data": {}}],
            "retire": {"externalSecrets": ["api-auth"], "generators": ["api-password"]}}
    assert run_script(tmp_path, kube, plan).returncode == 0
    v = kube.values("api-auth")
    assert v["JWT_KEY"] == "j" * 32 and len(v["SESSION_KEY"]) == 32 and ALNUM.match(v["SESSION_KEY"])


def test_a_secret_written_by_an_externalsecret_is_adopted_by_metadata_only_ac_128_3(tmp_path, kube):  # AC-128.3
    ref = {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret", "name": "shop-sessions-app", "uid": "u1"}
    other = {"apiVersion": "v1", "kind": "ConfigMap", "name": "owner", "uid": "u2"}
    kube.put_secret("shop-sessions-app", {"password": "pw-kept-value", "url": "u", "host": "h", "port": "6379"}, labels={"app.kubernetes.io/instance": "shop-dev"},
                    annotations={"argocd.argoproj.io/tracking-id": "shop-dev:/Secret:shop-dev/shop-sessions-app", "keep": "me"}, owner_refs=[ref, other])
    p = run_script(tmp_path, kube, cache_plan())
    assert p.returncode == 0, out(p)
    meta = kube.secrets["shop-sessions-app"]["metadata"]
    assert "app.kubernetes.io/instance" not in meta["labels"] and meta["labels"]["app.kubernetes.io/name"] == "sessions"
    assert "argocd.argoproj.io/tracking-id" not in meta.get("annotations", {}) and meta["annotations"]["keep"] == "me"
    assert meta["ownerReferences"] == [other]
    assert kube.value("shop-sessions-app", "password") == "pw-kept-value"
    ops = patches(kube)[0]["body"]
    assert ops[0]["op"] == "test" and not [o for o in ops if o["path"].startswith("/data/")]
    assert "adopted (metadata)" in out(p)


def test_owner_references_of_an_externalsecret_alone_are_removed_ac_128_3(tmp_path, kube):  # AC-128.3
    ref = {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret", "name": "x", "uid": "u1"}
    kube.put_secret("shop-sessions-app", {"password": "p" * 32, "url": "u", "host": "h", "port": "6379"}, labels={"app.kubernetes.io/name": "sessions"}, owner_refs=[ref])
    assert run_script(tmp_path, kube, cache_plan()).returncode == 0
    assert not kube.secrets["shop-sessions-app"]["metadata"].get("ownerReferences")


def test_a_conflict_on_the_patch_is_read_again_and_rebuilt_ac_128_6(tmp_path, kube):  # AC-128.6
    kube.put_secret("shop-sessions-app", {"password": "p" * 32}, labels={})
    real = kube.patch
    state = {"n": 0}

    def flaky(name, ops):
        state["n"] += 1
        if state["n"] == 1:
            kube.rv += 1
            kube.secrets[name]["metadata"]["resourceVersion"] = str(kube.rv)   # somebody wrote in between
        return real(name, ops)

    kube.patch = flaky
    p = run_script(tmp_path, kube, cache_plan())
    assert p.returncode == 0, out(p)
    assert state["n"] == 2 and kube.value("shop-sessions-app", "port") == "6379" and kube.value("shop-sessions-app", "password") == "p" * 32


def test_no_request_is_an_update_a_list_or_a_watch_ac_128_6(tmp_path, kube):  # AC-128.6
    kube.put_secret("shop-sessions-app", {"password": "p" * 32}, labels={})
    run_script(tmp_path, kube, cache_plan())
    assert kube.log
    for c in kube.log:
        assert c["method"] in ("GET", "POST", "PATCH", "DELETE"), c
        assert "watch=" not in c["path"] and "?" not in c["path"], c
        if c["method"] == "POST":
            assert c["path"].endswith("/namespaces/shop-dev/secrets"), c


# ---------------- retire ----------------

def test_a_generator_backed_externalsecret_is_deleted_orphaning_the_secret_before_anything_is_written_ac_128_3(tmp_path, kube):  # AC-128.3
    kube.put_generated_es("shop-sessions-app")
    kube.generators.add("shop-sessions-password")
    kube.put_secret("shop-sessions-app", {"password": "p" * 32, "url": "u", "host": "h", "port": "6379"}, labels={"app.kubernetes.io/name": "sessions"})
    p = run_script(tmp_path, kube, cache_plan())
    assert p.returncode == 0, out(p)
    assert "shop-sessions-app" not in kube.externalsecrets and "shop-sessions-password" not in kube.generators
    dele = kube.calls("DELETE", "/externalsecrets/shop-sessions-app")
    assert len(dele) == 1 and dele[0]["body"] == {"apiVersion": "v1", "kind": "DeleteOptions", "propagationPolicy": "Orphan"}
    assert "retired ExternalSecret shop-sessions-app" in out(p) and "retired Password generator shop-sessions-password" in out(p)
    assert kube.value("shop-sessions-app", "password") == "p" * 32
    methods = [(c["method"], c["path"]) for c in kube.log]
    i_del = next(i for i, (m, pth) in enumerate(methods) if m == "DELETE" and "externalsecrets" in pth)
    i_gen = next(i for i, (m, pth) in enumerate(methods) if m == "DELETE" and "passwords" in pth)
    assert i_del < i_gen < next(i for i, (m, pth) in enumerate(methods) if m == "POST")


def test_the_externalsecret_is_polled_until_it_is_gone_ac_128_3(tmp_path, kube):  # AC-128.3
    kube.put_generated_es("shop-sessions-app")
    real = kube.route
    seen = {"gone": 0}

    def slow(method, path, body):
        if method == "DELETE" and "externalsecrets" in path:
            return 200, {"kind": "Status"}            # accepted, still there for two more reads
        if method == "GET" and "externalsecrets" in path and seen["gone"] < 2:
            seen["gone"] += 1
            return 200, kube.externalsecrets["shop-sessions-app"]
        if method == "GET" and "externalsecrets" in path:
            return 404, None
        return real(method, path, body)

    kube.route = slow
    p = run_script(tmp_path, kube, cache_plan())
    assert p.returncode == 0, out(p)
    gets = kube.calls("GET", "/externalsecrets/")
    assert len(gets) >= 3 and kube.calls("POST", "/secrets")


def test_an_externalsecret_without_a_generator_ref_stops_the_job_before_any_secret_is_written_ac_128_3(tmp_path, kube):  # AC-128.3
    kube.externalsecrets["shop-sessions-app"] = {"kind": "ExternalSecret", "metadata": {"name": "shop-sessions-app"},
                                                 "spec": {"data": [{"secretKey": "password", "remoteRef": {"key": "k"}}]}}
    p = run_script(tmp_path, kube, cache_plan())
    assert p.returncode == 1
    assert "ExternalSecret shop-sessions-app is not generator-backed; it writes this Secret, so the credentials Job does not" in out(p)
    assert not kube.calls("POST") and not kube.calls("PATCH") and "shop-sessions-app" in kube.externalsecrets
    assert not kube.calls("DELETE", "/externalsecrets/")


def test_a_missing_externalsecret_and_generator_are_fine_ac_128_3(tmp_path, kube):  # AC-128.3
    p = run_script(tmp_path, kube, cache_plan())
    assert p.returncode == 0, out(p)
    assert "retired" not in out(p)


def test_a_transient_403_and_a_503_are_retried_ac_128_1(tmp_path, kube):  # AC-128.1
    kube.faults = [403, 503]
    p = run_script(tmp_path, kube, cache_plan())
    assert p.returncode == 0, out(p)
    assert "shop-sessions-app" in kube.secrets and len(kube.log) >= 5


# ---------------- verify: valkey ----------------

def valkey_world(kube, server_password, secret_password):
    srv = FakeValkey(server_password)
    kube.put_secret("shop-sessions-app", {"password": secret_password, "url": "u", "host": "h", "port": "6379"}, labels={"app.kubernetes.io/name": "sessions"})
    kube.put_pod("shop-sessions-0", env={"VALKEY_PASSWORD": "shop-sessions-app"})
    return srv


def test_a_server_that_accepts_the_secrets_password_is_not_restarted_ac_128_1(tmp_path, kube):  # AC-128.1
    srv = valkey_world(kube, "same-password-value", "same-password-value")
    try:
        p = run_script(tmp_path, kube, cache_plan(port=srv.port))
        assert p.returncode == 0, out(p)
        assert not kube.calls("DELETE", "/pods/") and "verified shop-sessions-0" in out(p)
        assert srv.auths == [("default", "same-password-value")]
        no_values_printed(p, kube)
    finally:
        srv.close()


def test_a_server_that_refuses_the_secrets_password_restarts_once_and_then_accepts_ac_128_10(tmp_path, kube):  # AC-128.10
    srv = valkey_world(kube, "the-wrong-old-password", "the-secrets-password-value")
    kube.on_pod_delete = lambda name: setattr(srv, "password", kube.value("shop-sessions-app", "password"))
    try:
        p = run_script(tmp_path, kube, cache_plan(port=srv.port))
        assert p.returncode == 0, out(p)
        assert len(kube.calls("DELETE", "/pods/shop-sessions-0")) == 1
        assert "restarted shop-sessions-0: it refused the password of shop-sessions-app" in out(p)
        assert "verified shop-sessions-0" in out(p)
        assert kube.value("shop-sessions-app", "password") == "the-secrets-password-value"
        assert srv.auths[-1] == ("default", "the-secrets-password-value")
        assert "the-wrong-old-password" not in out(p) and "the-secrets-password-value" not in out(p)
    finally:
        srv.close()


def test_a_server_that_still_refuses_after_the_restart_exits_2_ac_128_10(tmp_path, kube):  # AC-128.10
    srv = valkey_world(kube, "the-wrong-old-password", "the-secrets-password-value")
    try:
        p = run_script(tmp_path, kube, cache_plan(port=srv.port))
        assert p.returncode == 2, out(p)
        assert "shop-sessions-0 still refuses the password of shop-sessions-app after a restart" in out(p)
    finally:
        srv.close()


def test_a_socket_error_is_unknown_and_never_restarts_ac_128_10(tmp_path, kube):  # AC-128.10
    srv = valkey_world(kube, "x", "y")
    port = srv.port
    srv.close()
    p = run_script(tmp_path, kube, cache_plan(port=port))
    assert p.returncode == 0, out(p)
    assert not kube.calls("DELETE", "/pods/")


def test_an_absent_or_unready_pod_is_skipped_ac_128_10(tmp_path, kube):  # AC-128.10
    srv = FakeValkey("nope")
    try:
        kube.put_secret("shop-sessions-app", {"password": "p" * 32, "url": "u", "host": "h", "port": "6379"}, labels={"app.kubernetes.io/name": "sessions"})
        p = run_script(tmp_path, kube, cache_plan(port=srv.port))      # no pod at all
        assert p.returncode == 0 and "skipped shop-sessions-0:" in out(p)
        kube.put_pod("shop-sessions-0", ready=False, env={"VALKEY_PASSWORD": "shop-sessions-app"})
        p = run_script(tmp_path, kube, cache_plan(port=srv.port))
        assert p.returncode == 0 and "skipped shop-sessions-0:" in out(p)
        assert not kube.calls("DELETE", "/pods/") and not srv.auths
    finally:
        srv.close()


def test_a_pod_that_does_not_read_the_secret_is_not_probed_ac_128_10(tmp_path, kube):  # AC-128.10
    srv = FakeValkey("nope")
    try:
        kube.put_secret("shop-sessions-app", {"password": "p" * 32, "url": "u", "host": "h", "port": "6379"}, labels={"app.kubernetes.io/name": "sessions"})
        kube.put_pod("shop-sessions-0", env={"VALKEY_PASSWORD": "some-other-secret"})
        assert run_script(tmp_path, kube, cache_plan(port=srv.port)).returncode == 0
        assert not srv.auths and not kube.calls("DELETE", "/pods/")
    finally:
        srv.close()


# ---------------- verify: nats ----------------

def test_each_nats_user_is_probed_and_a_server_that_refuses_one_restarts_once_ac_128_4(tmp_path, kube):  # AC-128.4
    srv = FakeNats({})
    plan = nats_plan(srv.port, comps=("api", "web"))
    for s in plan["secrets"]:
        kube.put_secret(s["name"], {"password": f"pw-of-{s['name']}-xxxxxxxx", **s["data"]}, labels={})
    srv.users = {"_nack": kube.value("shop-bus-nack", "password"), "api": "stale-password-value", "web": kube.value("shop-bus-web-app", "password")}
    kube.put_pod("shop-bus-0", env={"ADMIN_PASSWORD": "shop-bus-nack", "USER_API_PASSWORD": "shop-bus-api-app", "USER_WEB_PASSWORD": "shop-bus-web-app"})

    def restart(name):
        srv.users = {"_nack": kube.value("shop-bus-nack", "password"), "api": kube.value("shop-bus-api-app", "password"),
                     "web": kube.value("shop-bus-web-app", "password")}

    kube.on_pod_delete = restart
    try:
        p = run_script(tmp_path, kube, plan)
        assert p.returncode == 0, out(p)
        assert sorted(set(srv.connects[:3])) == ["_nack", "api", "web"]
        assert len(kube.calls("DELETE", "/pods/shop-bus-0")) == 1
        assert "restarted shop-bus-0: it refused the password of shop-bus-api-app" in out(p)
        assert "verified shop-bus-0" in out(p)
    finally:
        srv.close()


def test_a_nats_server_that_accepts_every_user_is_left_alone_ac_128_4(tmp_path, kube):  # AC-128.4
    srv = FakeNats({})
    plan = nats_plan(srv.port, comps=("api",))
    for s in plan["secrets"]:
        kube.put_secret(s["name"], {"password": f"pw-of-{s['name']}-xxxxxxxx", **s["data"]}, labels={})
    srv.users = {"_nack": kube.value("shop-bus-nack", "password"), "api": kube.value("shop-bus-api-app", "password")}
    kube.put_pod("shop-bus-0", env={"ADMIN_PASSWORD": "shop-bus-nack", "USER_API_PASSWORD": "shop-bus-api-app"})
    try:
        p = run_script(tmp_path, kube, plan)
        assert p.returncode == 0, out(p)
        assert not kube.calls("DELETE", "/pods/") and "verified shop-bus-0" in out(p)
    finally:
        srv.close()


def test_a_nats_user_the_pod_does_not_declare_is_not_probed_ac_128_5(tmp_path, kube):  # AC-128.5
    srv = FakeNats({})
    plan = nats_plan(srv.port, comps=("api", "web"))
    for s in plan["secrets"]:
        kube.put_secret(s["name"], {"password": f"pw-of-{s['name']}-xxxxxxxx", **s["data"]}, labels={})
    srv.users = {"_nack": kube.value("shop-bus-nack", "password"), "api": kube.value("shop-bus-api-app", "password")}
    kube.put_pod("shop-bus-0", env={"ADMIN_PASSWORD": "shop-bus-nack", "USER_API_PASSWORD": "shop-bus-api-app"})   # web is not in the server yet
    try:
        assert run_script(tmp_path, kube, plan).returncode == 0
        assert "web" not in srv.connects and not kube.calls("DELETE", "/pods/")
    finally:
        srv.close()


def test_the_scripts_plan_may_be_read_from_the_path_given_as_the_argument_ac_128_1(tmp_path, kube):  # AC-128.1
    plan = cache_plan()
    p = run_script(tmp_path, kube, plan)
    assert p.returncode == 0 and json.loads((tmp_path / "creds" / "plan.json").read_text()) == plan
    assert not re.search(r"Traceback", out(p))
