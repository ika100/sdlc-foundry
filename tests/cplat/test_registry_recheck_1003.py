"""#1003: a registry "not found" for an image that resolves is a transient pull failure, not a missing pin.

1. `cplat system wait`: a database pod whose pull fails with "not found" for over 60 s is RED only when the registry, asked from this
   host, does not have the image either; an image that resolves, or a registry this host cannot reach, waits for the kubelet's retry
   and says so on the progress line. The registry is asked at most once a minute per image. A component's pod likewise.
2. `envwait.resolves`: an anonymous OCI manifest request (the registry's Bearer token flow) answers found, missing, unreachable, or
   None when it cannot tell (a private image).

Seams: the scripted Argo CD and pods of test_db_pull_visible_925 / test_867_pod_failfast, `envwait.resolves` (the conftest answers
"missing"), `urllib.request.urlopen` for the real request.
"""
import io
import json
import subprocess
import urllib.error

import pytest

import envwait
from test_143_envwait import World, block
from test_867_pod_failfast import stuck
from test_db_pull_visible_925 import MISSING, PG, Pods, db_lines, db_pod, db_waits, evs, w  # noqa: F401  (fixture)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)


def registry(w, answer):
    asked = []
    w.mp.setattr(envwait, "resolves", lambda image: asked.append((w.t["now"], image)) or answer)
    return asked


@pytest.fixture()
def component_world(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(envwait, "wallclock", lambda: 0.0)
    monkeypatch.setattr(envwait, "gh", lambda args: subprocess.CompletedProcess(args, 0, "[]", ""))  # #892: no CI run builds it
    return world


# ---------------- part 1: the wait ----------------

def test_a_pinned_image_that_resolves_waits_for_the_kubelets_retry(w):
    db_waits(w)
    Pods(w, [db_pod("ImagePullBackOff")], evs(MISSING))
    asked = registry(w, "found")
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 2 and not any(ln.startswith("RED:") for ln in out)                       # never RED: the pin is right
    assert "the registry answered not found, but the image resolves from this host" in db_lines(out)[-1]
    assert {image for _, image in asked} == {PG}
    times = [t for t, _ in asked]
    assert all(b - a >= envwait.REGISTRY_RECHECK for a, b in zip(times, times[1:]))


def test_a_pull_that_recovers_after_the_transient_not_found_ends_ready(w):
    db_waits(w)
    w.argo.polls = w.argo.polls * 20 + [w.ready()]
    Pods(w, lambda now: [db_pod("ErrImagePull", message=MISSING)] if now < 1150 else [], evs(MISSING))
    registry(w, "found")
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 0 and any("resolves from this host" in ln for ln in db_lines(out))


def test_a_registry_this_host_cannot_reach_either_waits_for_the_network(w):
    db_waits(w)
    Pods(w, [db_pod("ImagePullBackOff")], evs(MISSING))
    registry(w, "unreachable")
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "300")
    assert rc == 2 and "this host cannot reach the registry either" in db_lines(out)[-1]


@pytest.mark.parametrize("answer", ["missing", None])
def test_an_image_the_registry_does_not_have_is_red(w, answer):
    db_waits(w)
    Pods(w, [db_pod("ImagePullBackOff")], evs(MISSING))
    registry(w, answer)
    rc, out, _, _ = w.wait("--env", "dev", "--timeout", "600")
    assert rc == 1 and "the image tag does not exist in the registry" in block(out, "RED:")[0]


def test_the_registry_is_not_asked_before_60_seconds_or_for_a_network_error(w):
    db_waits(w)
    Pods(w, [db_pod("ErrImagePull", message="dial tcp 140.82.121.33:443: i/o timeout")], evs())
    asked = registry(w, "found")
    w.wait("--env", "dev", "--timeout", "200")
    assert asked == []


def test_a_component_pod_whose_image_resolves_is_not_stuck(component_world):
    stuck(component_world, "ImagePullBackOff")
    registry(component_world, "found")
    rc, out, _, _ = component_world.wait("--env", "dev", "--timeout", "300")
    assert rc == 2 and not any(ln.startswith("RED:") for ln in out)


# ---------------- part 2: the registry request ----------------

class Registry:
    """Answers urlopen: the manifest URL by `manifest` (status codes in order), the token realm by `token`."""

    def __init__(self, manifest, token=(200, {"token": "t0k"})):
        self.manifest, self.token, self.calls = list(manifest), token, []

    def __call__(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        auth = None if isinstance(req, str) else req.get_header("Authorization")
        self.calls.append((url, auth))
        if isinstance(self.token, Exception) and "/token" in url:
            raise self.token
        if "/token" in url:
            code, body = self.token
            if code != 200:
                raise urllib.error.HTTPError(url, code, "denied", {}, io.BytesIO(b""))
            return io.BytesIO(json.dumps(body).encode())
        code = self.manifest.pop(0)
        if isinstance(code, Exception):
            raise code
        if code == 200:
            return io.BytesIO(b"")
        headers = {"WWW-Authenticate": 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:cloudnative-pg/postgresql:pull"'}
        raise urllib.error.HTTPError(url, code, "no", headers if code == 401 else {}, io.BytesIO(b""))


@pytest.mark.parametrize("manifest,token,answer", [
    ([401, 200], (200, {"token": "t0k"}), "found"),
    ([401, 404], (200, {"token": "t0k"}), "missing"),
    ([urllib.error.URLError("network is down")], None, "unreachable"),
    ([401], urllib.error.URLError("TLS handshake timeout"), "unreachable"),
    ([401, 401], (200, {"token": "t0k"}), None),                     # a private image: the anonymous token does not open it
    ([401], (403, {}), None),
    ([500], None, None)])
def test_the_request_answers_what_the_registry_says(monkeypatch, manifest, token, answer):
    fake = Registry(manifest, token)
    monkeypatch.setattr(envwait.urllib.request, "urlopen", fake)
    assert envwait.REAL_RESOLVES(PG) == answer
    url, auth = fake.calls[0]
    assert url == "https://ghcr.io/v2/cloudnative-pg/postgresql/manifests/sha256:" + "e" * 64 and auth is None
    if answer in ("found", "missing"):
        assert fake.calls[1][0] == "https://ghcr.io/token?service=ghcr.io&scope=repository%3Acloudnative-pg%2Fpostgresql%3Apull"
        assert fake.calls[2][1] == "Bearer t0k"


@pytest.mark.parametrize("image,ref", [
    (PG, ("ghcr.io", "cloudnative-pg/postgresql", "sha256:" + "e" * 64)),
    ("ghcr.io/acme/todo-api:sha-4f2a91c", ("ghcr.io", "acme/todo-api", "sha-4f2a91c")),
    ("postgres:17", ("registry-1.docker.io", "library/postgres", "17")),
    ("docker.io/bitnami/redis", ("registry-1.docker.io", "bitnami/redis", "latest")),
    ("localhost:5000/app:1", ("localhost:5000", "app", "1"))])
def test_an_image_reference_is_split_as_the_kubelet_reads_it(image, ref):
    assert envwait._reference(image) == ref
