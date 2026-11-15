"""Spec 199 acceptance tests AC-199.2: `cplat system ship land` (dev smoke, then the staging smoke of the staging PR) and
`cplat instance promote --smoke` use the port the k3d cluster's Gateway really got, record their results, and the prod
promotion's evidence then shows the staging smoke record without the "no staging smoke record" warning.

Worlds: the joint system ship of spec 144 (real git, fake `gh`/`kubectl`/`devbox`) with `.localhost` hosts, and the promote
world of #503. A fake `docker` reports 8089 for `k3d-shop-local-serverlb`, LOCAL_HTTP_PORT is unset, and the environment answers
only on that port: a smoke against another port is "not run" (before the fix: 8088, so the system ship escalated)."""
import pytest

import envwait
import promote
import smoke
import test_144_joint_pr as joint
import waits
from docker199_support import PORT, FakeDocker
from test_144_joint_pr import JointWorld
from test_gitops import SHA, commit, composed, gh, gitops_repo  # noqa: F401  (fixtures)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from test_smoke_091_run import GitopsApi, link, make_service
from test_staging_093_evidence import E, ev, summary  # noqa: F401  (fixtures)

LOCAL_SYSTEM = joint.SYSTEM.replace("{component}.dev.example.test", "{component}.shop-dev.localhost").replace(
    "{component}.staging.example.test", "{component}.shop-staging.localhost")


def answers_only_on_the_reported_port(world):
    """`smoke.run_smoke` of the world, but an environment that answers only on PORT; another URL is not reachable."""
    real = world.run_smoke

    def run_smoke(repo, base_url, *, env="dev", spec=None, **kw):
        if f":{PORT}" not in base_url:
            world.smoked.append((repo.name, env, base_url))
            return smoke.not_run(env, f"{env} URL {base_url} is not reachable: connection refused", [])
        return real(repo, base_url, env=env, spec=spec, **kw)
    return run_smoke


@pytest.fixture()
def land(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(joint, "SYSTEM", LOCAL_SYSTEM)
    world = JointWorld(tmp_path, monkeypatch, capsys)
    docker = FakeDocker(tmp_path, monkeypatch).reports("shop-local")
    monkeypatch.setattr(smoke, "run_smoke", answers_only_on_the_reported_port(world))
    results = []
    monkeypatch.setattr(smoke, "record", lambda repo, res, image, spec_id: results.append((repo.name, res, image)) or "rid")
    world.docker, world.results = docker, results
    return world


# ---------------- AC-199.2: system ship land ----------------

def test_land_smokes_dev_and_staging_on_the_reported_port_ac_199_2(land):  # AC-199.2
    land.to_land()
    r = land.app("land")
    assert r.rc == 0, r.out
    assert [(n, e, u) for n, e, u in land.smoked if e == "dev"] == [
        ("shop-api", "dev", f"http://shop-api.shop-dev.localhost:{PORT}"), ("shop-web", "dev", f"http://shop-web.shop-dev.localhost:{PORT}")]
    assert [(n, e, u) for n, e, u in land.smoked if e == "staging"] == [
        ("shop-api", "staging", f"http://shop-api.shop-staging.localhost:{PORT}"),
        ("shop-web", "staging", f"http://shop-web.shop-staging.localhost:{PORT}")]
    assert "Smoke (dev) shop-api: 3/3 passed" in r.out and "Smoke (staging) shop-api: 3/3 passed" in r.out


def test_land_does_not_escalate_for_an_unreachable_environment_ac_199_2(land):  # AC-199.2
    land.to_land()
    r = land.app("land")
    assert r.rc == 0, r.out
    st = land.state()
    assert not st.get("escalated") and st.get("cause") != "environment"
    assert all(rep["state"] != "escalated" for rep in st["repos"].values())
    assert "smoke not run in dev" not in r.out


def test_land_records_the_results_ac_199_2(land):  # AC-199.2
    land.to_land()
    assert land.app("land").rc == 0
    got = {(name, res.env): res for name, res, image in land.results}
    for name in ("shop-api", "shop-web"):
        for env in ("dev", "staging"):
            res = got[(name, env)]
            assert res.outcome == "passed" and res.base_url == f"http://{name}.shop-{env}.localhost:{PORT}"


def test_land_asks_docker_once_for_the_whole_invocation_ac_199_5(land):  # AC-199.5
    import localport
    land.to_land()
    localport.reset()
    land.docker.clear()
    assert land.app("land").rc == 0
    assert len(land.docker.asked("shop-local")) == 1


def test_the_prod_evidence_shows_the_staging_smoke_without_a_warning_ac_199_2(land, ev):  # AC-199.2  # noqa: F811
    land.to_land()
    assert land.app("land").rc == 0
    (stg,) = [(res, image) for name, res, image in land.results if name == "shop-api" and res.env == "staging"]
    res, _ = stg
    at = "2026-10-24T14:20:00Z"
    ev.records["runs/2026/10/24/v1.json"] = {
        "run_id": "v1", "kind": "verify", "repo": "acme/shop-api", "ended_at": at, "outcome": "done",
        "smoke": {**res.section(), "image": f"sha-{E}", "at": at}}
    s = summary()
    assert s.staging["outcome"] == "passed" and str(PORT) in s.staging["base_url"]
    assert not any(ln.startswith("WARNING") for ln in s.lines())
    assert not any("no staging smoke record" in ln for ln in s.lines())


# ---------------- AC-199.2: instance promote --smoke ----------------

TOP = {"gateway": {"name": "traefik-gateway", "namespace": "kube-system"},
       "environments": {"dev": {"host": "{component}.{system}-dev.localhost"},
                        "staging": {"host": "{component}.{system}-staging.localhost"}}}
COMPONENTS = {"shop-api": {"type": "service", "lang": "python", "repo": "acme/shop-api", "port": 8080,
                           "expose": {"host": "shop-api"}, "instances": {"dev": {}, "staging": {}}}}


@pytest.fixture()
def promoted(gitops_repo, gh, tmp_path, monkeypatch):  # noqa: F811
    """A staging promotion merged by hand, then `cplat instance promote --smoke`: the clone is a service repo linked to a
    gitops-app whose staging host is local; smoke.main is the real one (URL, run, record), the run itself is faked."""
    gh.image_tags["todo-web"].add("sha-" + SHA)
    composed(gitops_repo, "todo-api")
    composed(gitops_repo, "todo-web")
    promote.main(["--all", "--to", "staging", "--repo-dir", str(gitops_repo)])
    commit(gitops_repo, "promote")
    svc = make_service(tmp_path, "shop-api")
    link(svc)
    docker = FakeDocker(tmp_path, monkeypatch).reports("shop-local")
    monkeypatch.setattr(envwait, "system_wait", lambda repo, ns, command: (waits.REACHED, ["READY: 1 app(s) in staging"]))
    monkeypatch.setattr(promote, "component_clone", lambda repo, slug: svc)
    monkeypatch.setattr(smoke, "gh", GitopsApi(COMPONENTS, TOP))
    monkeypatch.setattr(smoke, "pinned_image", lambda repo, apps, service, env: f"sha-{E}")
    monkeypatch.setattr(smoke, "liveness_probe", lambda repo: None)
    seen, recorded = [], []

    def run_smoke(repo, base_url, *, env="dev", spec=None, **kw):
        seen.append((env, base_url))
        if f":{PORT}" not in base_url:
            return smoke.not_run(env, f"{env} URL {base_url} is not reachable: connection refused", [])
        return smoke.SmokeResult(env=env, outcome="passed", base_url=base_url, passed=3)
    monkeypatch.setattr(smoke, "run_smoke", run_smoke)
    monkeypatch.setattr(smoke, "record", lambda repo, res, image, spec_id: recorded.append((res, image)) or "v1")
    return gitops_repo, seen, recorded, docker


def test_promote_smoke_runs_on_the_reported_port_and_records_ac_199_2(promoted, capsys):  # AC-199.2
    repo, seen, recorded, docker = promoted
    assert promote.main(["todo-api", "--to", "staging", "--smoke", "--repo-dir", str(repo)]) == 0
    assert seen == [("staging", f"http://shop-api.shop-staging.localhost:{PORT}")]
    ((res, image),) = recorded
    assert (res.env, res.outcome, res.base_url) == ("staging", "passed", f"http://shop-api.shop-staging.localhost:{PORT}")
    assert docker.asked("shop-local")


def test_the_promote_smoke_record_is_prod_evidence_ac_199_2(promoted, ev):  # AC-199.2  # noqa: F811
    repo, seen, recorded, docker = promoted
    assert promote.main(["todo-api", "--to", "staging", "--smoke", "--repo-dir", str(repo)]) == 0
    ((res, image),) = recorded
    at = "2026-10-24T14:20:00Z"
    ev.records["runs/2026/10/24/v1.json"] = {
        "run_id": "v1", "kind": "verify", "repo": "acme/shop-api", "ended_at": at, "outcome": "done",
        "smoke": {**res.section(), "image": image, "at": at}}
    s = summary()
    assert s.staging["outcome"] == "passed"
    assert not any("no staging smoke record" in ln for ln in s.lines())

