"""Spec 201 acceptance tests, `/platform:update` in a cluster repo with clusters (AC-201.7): only the first cluster takes the release, a
later cluster's tree stays byte for byte and the repo keeps the renderer that produces it.

Contract: design.md section 6. A cluster repo is a Copier copy of templates/cluster-gitops with an older operator pin in its own
`scripts/system_render.py` and an older stamp; the update runs for real (Copier, then the re-render) on that git repo."""
import subprocess

import pytest
import yaml

import core
import update
from cluster_fixtures import cluster_repo, git, git_repo, script
from support_201 import HOME, LOCAL, multi, setup, stdout_lines

OLD = "5.0.0"
OLD_PIN, NEW_PIN = '"chart_version": "0.28.0"', '"chart_version": "0.29.1"'


def old_world(shared_renders, tmp_path, monkeypatch, clusters=(LOCAL, HOME), old_pin=True):
    repo = cluster_repo(shared_renders, tmp_path / "w")
    sysr = repo / "scripts" / "system_render.py"
    text = sysr.read_text()
    assert NEW_PIN in text, "the template pins cloudnative-pg 0.29.1 (this test changes the pin of an older release)"
    if old_pin:
        sysr.write_text(text.replace(NEW_PIN, OLD_PIN, 1))
    setup(repo, multi(clusters=clusters, operators=["cloudnative-pg"]))
    (repo / ".platform-version").write_text(f"# Written by /component:new and /platform:update; read by /platform:doctor.\nplatform: {OLD}\nshape: cluster-gitops\nref: main\n")
    p = script(repo, "render.py")
    assert p.returncode == 0, p.stdout + p.stderr
    git_repo(repo, tmp_path / "w")
    monkeypatch.setattr(update, "refresh_devbox_lock", lambda *a, **k: None)
    return repo


def snapshot(repo, top):
    return {p.relative_to(repo).as_posix(): p.read_bytes() for p in sorted((repo / top).rglob("*")) if p.is_file()}


def run_update(repo):
    req = update.resolve(["--repo", str(repo)])
    return update.execute(req)


def test_ac_201_7_an_update_that_changes_the_pins_changes_only_the_first_cluster(shared_renders, tmp_path, monkeypatch):  # AC-201.7
    repo = old_world(shared_renders, tmp_path, monkeypatch)
    home_before, local_before = snapshot(repo, "cluster/home"), snapshot(repo, "cluster/local")
    old_renderers = {n: (repo / "scripts" / n).read_bytes() for n in ("render.py", "system_render.py")}
    assert OLD_PIN.split(": ")[1].strip('"') in (repo / "cluster/local/operators/cloudnative-pg.yaml").read_text()
    report = run_update(repo)
    assert snapshot(repo, "cluster/home") == home_before, "the later cluster's tree is byte for byte as it was"
    assert snapshot(repo, "cluster/local") != local_before and "0.29.1" in (repo / "cluster/local/operators/cloudnative-pg.yaml").read_text()
    assert yaml.safe_load((repo / "clusters/home/release.yaml").read_text()) == {"platform": OLD}
    assert not (repo / "clusters/local/release.yaml").exists()
    kept = repo / ".platform" / "releases" / OLD
    assert {n: (kept / n).read_bytes() for n in old_renderers} == old_renderers, "the repo keeps the renderer that produces the later tree"
    assert f"kept cluster home at platform {OLD}; promote it with /cluster:promote home" in report.did


def test_ac_201_7_after_the_update_render_names_the_cluster_that_is_behind_and_the_tree_stays(shared_renders, tmp_path, monkeypatch):  # AC-201.7
    repo = old_world(shared_renders, tmp_path, monkeypatch)
    run_update(repo)
    new = core.platform_version()
    p = script(repo, "render.py")
    assert p.returncode == 0, p.stdout + p.stderr
    assert [ln for ln in stdout_lines(p) if ln.startswith("BEHIND")] == [
        f"BEHIND: cluster home runs platform {OLD}, cluster local runs {new}; promote it with /cluster:promote home"]
    assert stdout_lines(p)[-1] == "rendered (0 file(s) changed)"
    chk = script(repo, "check.py")
    assert chk.returncode == 0 and f"BEHIND: cluster home runs platform {OLD}" in chk.stdout


def test_ac_201_7_a_release_that_leaves_the_later_tree_unchanged_freezes_nothing(shared_renders, tmp_path, monkeypatch):  # AC-201.7
    repo = old_world(shared_renders, tmp_path, monkeypatch, old_pin=False)
    report = run_update(repo)
    assert not (repo / "clusters/home/release.yaml").exists()
    assert not (repo / ".platform" / "releases" / OLD).exists()
    assert not [d for d in report.did if d.startswith("kept cluster")]
    assert not [ln for ln in stdout_lines(script(repo, "render.py")) if ln.startswith("BEHIND")]


def test_ac_201_7_a_repo_with_one_listed_cluster_is_updated_as_before(shared_renders, tmp_path, monkeypatch):  # AC-201.7
    repo = old_world(shared_renders, tmp_path, monkeypatch, clusters=(LOCAL,))
    run_update(repo)
    assert not (repo / "clusters" / LOCAL / "release.yaml").exists() and not (repo / ".platform").exists()
    assert "0.29.1" in (repo / "cluster/local/operators/cloudnative-pg.yaml").read_text()


def test_ac_201_7_without_a_stamp_the_update_stops_before_anything_changes(shared_renders, tmp_path, monkeypatch):  # AC-201.7
    repo = old_world(shared_renders, tmp_path, monkeypatch)
    req = update.resolve(["--repo", str(repo)])
    req["old"] = None
    with pytest.raises(core.PlatformError) as e:
        update.execute(req)
    assert "cannot keep the later clusters at their release: this repo has no .platform-version" in str(e.value)
    assert "restore .platform-version from git history (git log -- .platform-version), then run the update again" in (e.value.hint or "")
    assert git(repo, "status", "--porcelain").strip() == ""


def test_ac_201_7_the_dry_run_names_the_clusters_it_would_keep(shared_renders, tmp_path, monkeypatch):  # AC-201.7
    repo = old_world(shared_renders, tmp_path, monkeypatch)
    plan = update.plan(update.resolve(["--repo", str(repo)]))
    assert f"keep the later clusters (home) at platform {OLD} unless the release leaves their trees unchanged" in plan.will_do
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout.strip() == ""
