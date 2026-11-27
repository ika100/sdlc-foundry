"""#1074: the dispatcher shows the platform checkout it runs on and moves a clean, detached one to origin/main."""
import subprocess

import pytest

import dispatch_platform as dp


def _g(path, *args):
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("CPLAT_PLATFORM", raising=False)
    origin, work = tmp_path / "origin", tmp_path / "work"
    for p in (origin, work):
        p.mkdir()
        _g(p, "init", "-q", "-b", "main")
        _g(p, "config", "user.email", "a@b.c")
        _g(p, "config", "user.name", "t")
    (origin / "a").write_text("1")
    _g(origin, "add", "-A")
    _g(origin, "commit", "-q", "-m", "one")
    _g(work, "remote", "add", "origin", str(origin))
    _g(work, "pull", "-q", "origin", "main")
    (work / ".platform-settings.yml").write_text("shape: platform\n")
    _g(work, "checkout", "-q", "--detach")
    (origin / "a").write_text("2")
    _g(origin, "commit", "-q", "-am", "two")
    return origin, work


def test_a_clean_detached_checkout_moves_to_origin_main_before_a_unit(world):
    origin, work = world
    assert dp.state(work, fetch=True)["behind"] == 1
    [line] = dp.advance(work)
    assert "1 commits" in line
    assert _g(work, "rev-parse", "HEAD") == _g(origin, "rev-parse", "HEAD")
    assert dp.advance(work) == []


def test_a_dirty_checkout_is_left_alone_and_named(world):
    _, work = world
    (work / "a").write_text("local")
    assert dp.advance(work) == []
    assert "local changes" in dp.line(dp.state(work))
    assert "local changes" in dp.note(work) and "1 commits behind" in dp.note(work)


def test_a_branch_checkout_is_left_alone_and_named(world):
    _, work = world
    _g(work, "checkout", "-q", "-b", "wip")
    assert dp.advance(work) == []
    assert "on branch wip" in dp.line(dp.state(work))


def test_no_platform_checkout_shows_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("CPLAT_PLATFORM", raising=False)
    assert dp.state(tmp_path) is None and dp.advance(tmp_path) == [] and dp.note(tmp_path) == "" and dp.line(None) == ""
