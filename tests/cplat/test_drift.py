"""Spec 083: /shared:status shows each service repo's platform version and whether it is behind."""
import core
import status
from test_gitops import composed, gh, gitops_repo  # noqa: F401  (fixtures)


def test_status_shows_the_platform_version_of_each_service(gitops_repo, gh, monkeypatch):
    """AC-083.1: behind, current and missing stamps."""
    composed(gitops_repo, "todo-api")
    latest = core.platform_version()
    stamps = {"acme/todo-api": "# stamp\nplatform: 0.0.1\nshape: service-java\n"}

    def sh(cmd):
        if cmd[:2] == ["gh", "api"] and cmd[2].endswith("/contents/.platform-version"):
            return stamps.get(cmd[2][len("repos/"):-len("/contents/.platform-version")])
        return None
    monkeypatch.setattr(status, "sh", sh)
    _, rows = status.collect(gitops_repo, None, None)
    row = next(r for r in rows if r["service"] == "todo-api")
    assert row["platform"] == "0.0.1 (behind)"
    stamps["acme/todo-api"] = f"platform: {latest}\n"
    assert next(r for r in status.collect(gitops_repo, None, None)[1] if r["service"] == "todo-api")["platform"] == latest
    stamps.clear()
    _, rows = status.collect(gitops_repo, None, None)
    assert next(r for r in rows if r["service"] == "todo-api")["platform"] == "none"
    assert "platform" in status.render_table("todo", rows, {}, None).splitlines()[2]


# ---------------- spec 084 (kept here: both are about the platform's own repo) ----------------

def test_the_suite_runs_in_parallel_locally_and_in_ci():
    """AC-084.1: `pytest -n auto` with pytest-xdist in scripts/ci-local.sh and the platform CI."""
    for f in ("scripts/ci-local.sh", ".github/workflows/ci.yml"):
        text = (core.PLATFORM_ROOT / f).read_text()
        assert "--with pytest-xdist" in text and "pytest tests/cplat -q -n auto" in text, f


def test_smoke_matrices_run_to_the_end_and_maven_retries():
    """AC-084.2: no matrix job cancels its siblings; the Java smoke jobs retry downloads."""
    import yaml
    jobs = yaml.safe_load((core.PLATFORM_ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"]
    matrices = {k: v for k, v in jobs.items() if (v.get("strategy") or {}).get("matrix")}
    assert matrices and all(v["strategy"].get("fail-fast") is False for v in matrices.values()), list(matrices)
    assert "retryHandler.count=3" in jobs["smoke-test-service-java"]["env"]["MAVEN_OPTS"]
