"""AC-125.7: `cluster add` tells a readable repo without applications/ from an unreadable one."""
import pytest

import cplat
from cluster_fixtures import ORG, base, cluster_repo, git_repo, render_ok, stubs
from system_fixtures import files


def run(*argv, capsys):
    try:
        rc = cplat.main(["cluster", *map(str, argv)])
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


@pytest.fixture()
def world(shared_renders, tmp_path, monkeypatch):
    repo = cluster_repo(shared_renders, tmp_path / "w")
    s = stubs(tmp_path, monkeypatch)
    render_ok(repo, base())
    git_repo(repo, tmp_path)
    s["repo"] = repo
    return s


def test_ac_125_7_a_readable_repo_without_applications_is_not_a_gitops_repo(world, capsys):  # AC-125.7
    svc = world["fixtures"] / f"{ORG}__service"
    svc.mkdir()
    (svc / "README.md").write_text("a service repo")
    before = files(world["repo"])
    rc, out, err = run("add", f"{ORG}/service", "--repo-dir", world["repo"], capsys=capsys)
    assert rc == 1
    assert f"{ORG}/service is not a system's gitops repo: no applications/<system>/system.yaml on main" in err
    assert "cannot read" not in err
    assert files(world["repo"]) == before


def test_ac_125_7_an_unreadable_repo_fails_as_cannot_read(world, capsys):  # AC-125.7
    before = files(world["repo"])
    rc, out, err = run("add", f"{ORG}/ghost", "--repo-dir", world["repo"], capsys=capsys)
    assert rc == 1
    assert f"cannot read {ORG}/ghost: " in err and "check the name and that your gh login can read it" in err
    assert "not a system's gitops repo" not in err
    assert files(world["repo"]) == before
