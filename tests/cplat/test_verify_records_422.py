"""#422: a build that reached staging by hand (`/instance:promote`) and passed `cplat instance verify staging` still showed
"no staging smoke record" in the prod evidence, because only ship records were read. `instance verify` now writes a
`verify` record to the run store, and the evidence reads it next to ship records."""
import smoke
from test_staging_093_evidence import LINK, E, dev_rec, ev, stg, summary  # noqa: F401  (ev: pytest fixture)


def verify_rec(rid, env, image, outcome="passed", at="2026-10-24T18:52:00Z", repo="acme/shop-api"):
    sec = {**stg(outcome, image, at=at), "env": env}
    return {"run_id": rid, "kind": "verify", "repo": repo, "ended_at": at, "outcome": "done", "smoke": sec}


def test_a_verify_record_is_staging_evidence(ev):  # noqa: F811
    ev.records.update({"runs/2026/10/24/v1.json": verify_rec("v1", "staging", f"sha-{E}")})
    s = summary()
    assert s.staging["outcome"] == "passed" and s.staging["link"] == LINK.format("v1")
    assert not any(ln.startswith("WARNING") for ln in s.lines())


def test_a_verify_record_of_another_build_or_env_does_not_count(ev):  # noqa: F811
    ev.records.update({"runs/2026/10/24/v1.json": verify_rec("v1", "staging", "sha-" + "b" * 40),
                       "runs/2026/10/24/v2.json": verify_rec("v2", "prod", f"sha-{E}")})
    assert summary().staging["outcome"] is None


def test_the_newest_of_ship_and_verify_records_wins(ev):  # noqa: F811
    ev.records.update({"runs/2026/10/24/r1.json": dev_rec("r1", f"sha-{E}", staging=stg("red", f"sha-{E}", failing=["t"])),
                       "runs/2026/10/24/v1.json": verify_rec("v1", "staging", f"sha-{E}", at="2026-10-24T19:00:00Z")})
    assert summary().staging["outcome"] == "passed"


class Res:
    outcome, ok, env = "passed", True, "staging"

    def section(self):
        return {"env": "staging", "outcome": "passed", "passed": 1, "failed": 0}


def test_instance_verify_writes_a_verify_record(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(smoke.runs, "start", lambda kind, **kw: calls.append(("start", kind, kw)) or "rid")
    monkeypatch.setattr(smoke.runs, "repo_slug", lambda repo: "acme/shop-api")
    monkeypatch.setattr(smoke.runs, "set_section", lambda rid, name, value: calls.append(("section", name, value)))
    monkeypatch.setattr(smoke.runs, "finish", lambda rid, outcome, **kw: calls.append(("finish", outcome)))
    smoke.record(tmp_path, Res(), f"sha-{E}", "001-tasks")
    assert calls[0] == ("start", "verify", {"repo": "acme/shop-api", "spec": "001-tasks"})
    assert calls[1][1] == "smoke" and calls[1][2]["image"] == f"sha-{E}" and calls[1][2]["env"] == "staging"
    assert calls[2] == ("finish", "done")


def test_a_named_base_url_is_not_recorded(monkeypatch, tmp_path):
    recorded = []
    monkeypatch.setattr(smoke, "run_smoke", lambda *a, **kw: Res())
    monkeypatch.setattr(smoke, "record", lambda *a, **kw: recorded.append(a))
    monkeypatch.setattr(Res, "lines", lambda self: ["passed"], raising=False)
    assert smoke.main(["run", "--repo", str(tmp_path), "staging", "--base-url", "http://x"]) == 0
    assert recorded == []
