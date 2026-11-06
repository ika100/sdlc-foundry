"""#503: a promotion to staging made by hand waits for staging and records its smoke itself (`--smoke` after the merge), like the
automatic after-dev-smoke promotion, so the prod evidence finds a staging smoke record instead of warning "no staging smoke record"."""
import pytest

import core
import envwait
import promote
import smoke
import waits
from test_gitops import SHA, commit, composed, gh, gitops_repo  # noqa: F401  (fixtures)


@pytest.fixture()
def in_staging(gitops_repo, gh):  # noqa: F811
    gh.image_tags["todo-web"].add("sha-" + SHA)
    composed(gitops_repo, "todo-api")
    composed(gitops_repo, "todo-web")
    promote.main(["--all", "--to", "staging", "--repo-dir", str(gitops_repo)])
    commit(gitops_repo, "promote")
    return gitops_repo


@pytest.fixture()
def seams(monkeypatch, tmp_path):
    calls = {"wait": [], "smoke": [], "clone": [], "root": tmp_path}
    result = {"wait": (waits.REACHED, ["READY: 2 app(s) in staging run abc1234"]), "smoke": 0}

    def wait(repo, ns, command):
        calls["wait"].append((ns.env, list(ns.components), ns.refresh, command))
        return result["wait"]

    def clone(repo, slug):
        calls["clone"].append(slug)
        return tmp_path / slug.split("/")[-1]

    def run_smoke(argv):
        calls["smoke"].append(argv)
        return result["smoke"]
    monkeypatch.setattr(envwait, "system_wait", wait)
    monkeypatch.setattr(promote, "component_clone", clone)
    monkeypatch.setattr(smoke, "main", run_smoke)
    return calls, result


def test_smoke_waits_for_staging_then_runs_and_records_each_staging_smoke(in_staging, seams, capsys):
    calls, _ = seams
    assert promote.main(["--all", "--to", "staging", "--smoke", "--refresh", "--repo-dir", str(in_staging)]) == 0
    assert calls["wait"] == [("staging", ["todo-api", "todo-web"], True,
                              "cplat instance promote todo-api todo-web --to staging --smoke")]
    assert calls["clone"] == ["acme/todo-api", "acme/todo-web"]
    # the very call `cplat instance verify staging` makes in the component repo: it runs the smoke and writes the verify record
    assert calls["smoke"] == [["run", "staging", "--repo", str(calls["root"] / n)] for n in ("todo-api", "todo-web")]
    assert "READY:" in capsys.readouterr().out


def test_no_smoke_runs_when_staging_is_not_ready(in_staging, seams, capsys):
    calls, result = seams
    result["wait"] = (waits.TIMEOUT, ["TIMEOUT: 1 of 1 app(s) in staging not ready after 540s (wanted revision abc1234)"])
    assert promote.main(["todo-api", "--to", "staging", "--smoke", "--repo-dir", str(in_staging)]) == waits.TIMEOUT
    assert calls["smoke"] == [] and "TIMEOUT:" in capsys.readouterr().out


def test_a_red_staging_smoke_is_the_exit_code(in_staging, seams):
    _, result = seams
    result["smoke"] = 1
    assert promote.main(["todo-api", "--to", "staging", "--smoke", "--repo-dir", str(in_staging)]) == 1


@pytest.mark.parametrize("argv,msg", [
    (["todo-api", "--to", "prod", "--smoke"], "a step of its own"),
    (["todo-api", "--to", "staging", "--smoke", "--pr"], "a step of its own"),
])
def test_smoke_is_only_the_step_after_a_staging_merge(in_staging, seams, argv, msg):
    with pytest.raises(core.PlatformError, match=msg):
        promote.main([*argv, "--repo-dir", str(in_staging)])


def test_smoke_refuses_a_component_not_in_staging(gitops_repo, gh, seams):  # noqa: F811
    composed(gitops_repo, "todo-api")
    with pytest.raises(core.PlatformError, match="no instance in staging"):
        promote.main(["todo-api", "--to", "staging", "--smoke", "--repo-dir", str(gitops_repo)])
