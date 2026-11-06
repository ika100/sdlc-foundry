"""#507: the first scheduled backup of a database ran before its in-cluster backup bucket answered, failed, and CloudNativePG never
retried it; `/system:status` showed the failure only as a plain line. The rendered setup now waits for the bucket (a Sync hook in
wave 1, the ScheduledBackup in wave 2), and the status says when the last base backup fails."""
import http.server
import os
import subprocess
import sys
import threading

import yaml

import status
from backup_fixtures import bdoc, cnpg_backup, ext_prod_bucket, kube  # noqa: F401  (kube is a fixture)
from resources_fixtures import APP, ok, platform_render_module, y

DEV = {"to": "backups"}


def dd(env="dev") -> str:
    return f"{APP}/addons/{env}/orders-db"


def job(g, env="dev") -> dict:
    return y(g, f"{dd(env)}/bucket-wait-job.yaml")


# ---------------- the render ----------------

def test_a_database_backed_up_to_an_in_cluster_bucket_waits_for_it_before_the_scheduled_backup_507(tmp_path):
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    j = job(g)
    assert j["apiVersion"] == "batch/v1" and j["kind"] == "Job" and j["metadata"]["name"] == "shop-orders-db-bucket-wait"
    ann = j["metadata"]["annotations"]
    assert ann == {"argocd.argoproj.io/hook": "Sync", "argocd.argoproj.io/sync-wave": "1",
                   "argocd.argoproj.io/hook-delete-policy": "BeforeHookCreation,HookSucceeded"}
    sched = y(g, f"{dd()}/scheduledbackup.yaml")
    assert int(sched["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]) > int(ann["argocd.argoproj.io/sync-wave"])
    assert sched["spec"]["immediate"] is True, "the first base backup still runs at once, only after the bucket answers"
    assert "bucket-wait-job.yaml" in y(g, f"{dd()}/kustomization.yaml")["resources"]


def test_the_wait_uses_the_object_stores_endpoint_bucket_and_credentials_507(tmp_path):
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    conf = y(g, f"{dd()}/objectstore.yaml")["spec"]["configuration"]
    c = job(g)["spec"]["template"]["spec"]["containers"][0]
    env = {e["name"]: e.get("value", e.get("valueFrom")) for e in c["env"]}
    assert env["BUCKET_ENDPOINT"] == conf["endpointURL"]
    assert f"s3://{env['BUCKET_NAME']}/databases" == conf["destinationPath"]
    creds = conf["s3Credentials"]
    assert env["AWS_ACCESS_KEY_ID"] == {"secretKeyRef": creds["accessKeyId"]}
    assert env["AWS_SECRET_ACCESS_KEY"] == {"secretKeyRef": creds["secretAccessKey"]}
    assert env["BUCKET_REGION"] == {"secretKeyRef": creds["region"]}
    assert not [e for e in c["env"] if "value" in e and e["name"].startswith("AWS_")], "no credential value is rendered"


def test_the_wait_job_runs_like_the_credentials_job_507(tmp_path):
    g = ok(tmp_path, bdoc(dbb={"dev": DEV}))
    r = platform_render_module("render_507")
    spec = job(g)["spec"]
    pod = spec["template"]["spec"]
    c = pod["containers"][0]
    assert c["image"] == r.CREDENTIALS_IMAGE, "no new image to pin: the credentials Job's stdlib python"
    assert c["command"][:2] == ["python3", "-c"] and c["command"][2] == r.BUCKET_WAIT_SCRIPT
    assert pod["restartPolicy"] == "Never" and pod["automountServiceAccountToken"] is False
    assert c["securityContext"] == {"runAsNonRoot": True, "runAsUser": 65534, "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
    assert c["resources"]["requests"] and c["resources"]["limits"]["memory"]
    assert spec["activeDeadlineSeconds"] > r.BUCKET_WAIT_SECONDS
    assert "app.kubernetes.io/name" in spec["template"]["metadata"]["labels"]
    assert spec["template"]["metadata"]["labels"]["app.kubernetes.io/name"] != "orders-db", "the pod is not selected as the database"


def test_an_external_backup_target_renders_no_wait_507(tmp_path):
    g = ok(tmp_path, bdoc(dbb={"dev": DEV, "prod": DEV}, bucket_kw=ext_prod_bucket()))
    assert f"{dd('prod')}/bucket-wait-job.yaml" not in g
    assert "annotations" not in y(g, f"{dd('prod')}/scheduledbackup.yaml")["metadata"]
    assert f"{dd('dev')}/bucket-wait-job.yaml" in g


def test_removing_the_backup_removes_the_wait_507(tmp_path):
    ok(tmp_path, bdoc(dbb={"dev": DEV}))
    g = ok(tmp_path, bdoc())
    assert f"{dd()}/bucket-wait-job.yaml" not in g
    assert not (tmp_path / dd() / "bucket-wait-job.yaml").exists()


# ---------------- the wait script ----------------

def script_ns() -> dict:
    ns: dict = {"__name__": "bucket_wait"}
    exec(compile(platform_render_module("render_507s").BUCKET_WAIT_SCRIPT, "bucket-wait", "exec"), ns)  # noqa: S102
    return ns


def test_the_signature_matches_the_aws_sigv4_test_suite_507():
    # AWS Signature Version 4 test suite, get-vanilla
    auth = script_ns()["authorization"]("GET", "https://example.amazonaws.com/", {"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"},
                                        "us-east-1", "service", "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")  # pragma: allowlist secret
    assert auth == ("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, SignedHeaders=host;x-amz-date, "
                    "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31")


class Bucket(http.server.BaseHTTPRequestHandler):
    answers: list[int] = []
    seen: list[dict] = []

    def do_HEAD(self):  # noqa: N802
        type(self).seen.append({"path": self.path, **{k.lower(): v for k, v in self.headers.items()}})
        code = type(self).answers.pop(0) if len(type(self).answers) > 1 else type(self).answers[0]
        self.send_response(code)
        self.end_headers()

    def log_message(self, *args):
        pass


def run_wait(tmp_path, answers: list[int], seconds="30") -> tuple[subprocess.CompletedProcess, list[dict]]:
    Bucket.answers, Bucket.seen = list(answers), []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Bucket)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    script = tmp_path / "wait.py"
    script.write_text(platform_render_module("render_507r").BUCKET_WAIT_SCRIPT)
    env = {**os.environ, "BUCKET_ENDPOINT": f"http://127.0.0.1:{server.server_address[1]}", "BUCKET_NAME": "shop-backups",
           "BUCKET_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "id", "AWS_SECRET_ACCESS_KEY": "key",  # pragma: allowlist secret
           "BUCKET_WAIT_SECONDS": seconds, "BUCKET_WAIT_INTERVAL": "0.05"}
    try:
        p = subprocess.run([sys.executable, "-I", str(script)], env=env, capture_output=True, text=True, timeout=60, check=False)
    finally:
        server.shutdown()
    return p, Bucket.seen


def test_the_wait_ends_when_the_bucket_answers_200_507(tmp_path):
    p, seen = run_wait(tmp_path, [404, 403, 200])
    assert p.returncode == 0 and "bucket shop-backups answers" in p.stdout
    assert "waiting for bucket shop-backups: HTTP 404" in p.stdout and "HTTP 403" in p.stdout
    assert len(seen) == 3 and all(s["path"] == "/shop-backups" for s in seen)
    auth = seen[-1]["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=id/") and "/us-east-1/s3/aws4_request" in auth
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in auth
    assert "key" not in p.stdout + p.stderr.replace("KeyError", "")


def test_a_bucket_that_never_answers_lets_the_backup_go_on_after_the_wait_507(tmp_path):
    p, seen = run_wait(tmp_path, [404], seconds="0.3")
    assert p.returncode == 0 and "still does not answer (HTTP 404); going on without it" in p.stdout
    assert p.stdout.count("waiting for bucket") == 1, "one line per change, not per try"


# ---------------- the status ----------------

def test_status_says_the_last_base_backup_fails_while_archiving_works_507(kube):  # noqa: F811
    import backupstate
    kube.healthy_database(windows={}, backups=[cnpg_backup("shop-orders-db-20261027030000", phase="failed", stopped="2026-10-27T03:00:05Z",
                                                           error="can't upload: NoSuchBucket")])
    r = backupstate.database_state("shop", "orders-db", "dev", None, backup=True)
    assert r["backup"]["state"] == "failing" and r["backup"]["archiving"] == "ok"
    lines = status.backup_lines({"_read": True, "_contexts": ["k3d-x"], "resource_instances": [r], "environments": []})
    assert lines[-1] == ("  orders-db/dev  last base backup never  archiving ok  restore points none"
                         "  backup failing (can't upload: NoSuchBucket)")


def test_status_of_a_working_backup_is_unchanged_507(kube):  # noqa: F811
    import backupstate
    kube.healthy_database(windows={}, backups=[cnpg_backup("b1")])
    r = backupstate.database_state("shop", "orders-db", "dev", None, backup=True)
    line = status.backup_lines({"_read": True, "_contexts": ["k3d-x"], "resource_instances": [r], "environments": []})[-1]
    assert "failing" not in line and line.startswith("  orders-db/dev  last base backup 2026-10-27T03:00:12Z  archiving ok")


def test_the_rendered_wait_parses_as_yaml_with_the_script_as_a_block_507(tmp_path):
    ok(tmp_path, bdoc(dbb={"dev": DEV}))
    text = (tmp_path / dd() / "bucket-wait-job.yaml").read_text()
    assert yaml.safe_load(text)["kind"] == "Job" and "- |" in text
