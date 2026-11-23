"""#926: the first in-cluster bucket of a system installs the SeaweedFS operator in the same rollout; the bucket's Seaweed object hit
the operator's mutating webhook before it ran and before its CA was patched in (x509), and Argo CD retried for ~14 min.

The bucket's PreSync credentials Job (wave 1, before the Seaweed in the Sync phase) now waits for the operator's webhook when this repo
installs the operator. The rendered plan is checked here, and the program runs against the fake API of credentials_fixtures with a
listening or a closed port on 127.0.0.1."""
import socket
import threading
import time

import pytest

from credentials_fixtures import FakeKube, addon, bucket_plan, cred, plan_of, run_script
from resources_fixtures import ENVS, comp, ok, platform_render_module, system


def bsys() -> dict:
    return system({"files": {"type": "bucket"}}, {"api": comp("api", ["files"])})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def kube():
    k = FakeKube()
    yield k
    k.close()


def test_the_bucket_plan_waits_for_the_operator_webhook_this_repo_installs(tmp_path):
    r = platform_render_module("render_926")
    g = ok(tmp_path, bsys())
    for env in ENVS:
        hook = plan_of(g, addon(env, "files"))["webhook"]
        assert hook == {"host": "seaweedfs-operator-webhook.seaweedfs-operator.svc", "port": 443,
                        "seconds": r.WEBHOOK_WAIT_SECONDS, "settle": r.WEBHOOK_SETTLE_SECONDS}, env
    # the wait and the settle time fit in the credentials Job's deadline with time left to write the Secret (#1004)
    deadline = cred(g, addon("dev", "files"))["credentials-job.yaml"]["spec"]["activeDeadlineSeconds"]
    assert deadline >= r.WEBHOOK_WAIT_SECONDS + r.WEBHOOK_SETTLE_SECONDS + 5 * 2
    # the operator's own install took 8 min in journey 27 (#1004): the wait covers it
    assert r.WEBHOOK_WAIT_SECONDS >= 480
    assert r.credentials_deadline({}) == 300


def test_an_owner_managed_environment_does_not_wait_for_a_webhook_it_does_not_know(tmp_path):
    doc = bsys()
    doc["environments"]["prod"]["operators"] = "owner"
    g = ok(tmp_path, doc)
    assert "webhook" in plan_of(g, addon("dev", "files"))
    assert "webhook" not in plan_of(g, addon("prod", "files"))


def test_the_renderer_copies_stay_identical():
    from system_fixtures import ROOT
    a = (ROOT / "templates/gitops-app/scripts/render.py").read_text()
    assert a == (ROOT / "templates/cluster-gitops/scripts/system_render.py").read_text()
    assert "def wait_webhook(plan):" in a and "    wait_webhook(plan)\n" in a


def test_a_webhook_that_answers_at_once_costs_no_settle_time(tmp_path, kube):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    try:
        plan = {**bucket_plan(), "webhook": {"host": "127.0.0.1", "port": srv.getsockname()[1], "seconds": 20, "settle": 30}}
        t0 = time.time()
        p = run_script(tmp_path, kube, plan)
        assert p.returncode == 0, p.stdout + p.stderr
        assert time.time() - t0 < 15
        assert "answers" in p.stdout and "waiting" not in p.stdout
        assert "shop-files-app" in kube.secrets, "the Secret is written before the wait"
    finally:
        srv.close()


def test_a_webhook_that_starts_late_is_waited_for_then_settled(tmp_path, kube):
    port = free_port()
    srv = socket.socket()

    def start():
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(8)

    timer = threading.Timer(0.8, start)     # the script starts and finds the port closed first
    timer.start()
    try:
        plan = {**bucket_plan(), "webhook": {"host": "127.0.0.1", "port": port, "seconds": 30, "settle": 1, "interval": 0.2}}
        p = run_script(tmp_path, kube, plan)
        timer.join()
        assert p.returncode == 0, p.stdout + p.stderr
        assert "waiting for the operator webhook" in p.stdout and "waiting 1 s for its CA" in p.stdout
    finally:
        srv.close()


def test_a_webhook_that_never_answers_lets_the_job_go_on(tmp_path, kube):
    plan = {**bucket_plan(), "webhook": {"host": "127.0.0.1", "port": free_port(), "seconds": 1, "settle": 30, "interval": 0.2}}
    p = run_script(tmp_path, kube, plan)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "still does not answer" in p.stdout and "going on without it" in p.stdout
    assert "shop-files-app" in kube.secrets
