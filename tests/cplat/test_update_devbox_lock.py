"""`cplat update-service` keeps devbox.lock in step with the merged devbox.json, so the next devbox run does not dirty the tree."""
from types import SimpleNamespace

import update


def refresh(repo, changed):
    return update.REAL_REFRESH_DEVBOX_LOCK(repo, changed)


def test_nothing_to_do_without_a_devbox_change_or_a_lock(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(update, "run", lambda *a, **k: calls.append(a))
    assert refresh(tmp_path, ["devbox.json"]) is None            # no devbox.lock in the repo
    (tmp_path / "devbox.lock").write_text("{}")
    assert refresh(tmp_path, ["Dockerfile"]) is None             # devbox.json unchanged
    assert calls == []


def test_a_changed_devbox_json_runs_devbox_install(tmp_path, monkeypatch):
    (tmp_path / "devbox.lock").write_text("{}")
    calls = []
    monkeypatch.setattr(update.shutil, "which", lambda name: "/usr/bin/devbox")
    monkeypatch.setattr(update, "run", lambda cmd, **k: calls.append((cmd, k["cwd"])) or SimpleNamespace(returncode=0))
    assert refresh(tmp_path, ["devbox.json", "Dockerfile"]) is None
    assert calls == [(["devbox", "install"], tmp_path)]


def test_without_devbox_or_on_failure_the_report_says_what_to_do(tmp_path, monkeypatch):
    (tmp_path / "devbox.lock").write_text("{}")
    monkeypatch.setattr(update.shutil, "which", lambda name: None)
    assert "devbox install" in refresh(tmp_path, ["devbox.json"]) and "not installed" in refresh(tmp_path, ["devbox.json"])
    monkeypatch.setattr(update.shutil, "which", lambda name: "/usr/bin/devbox")
    monkeypatch.setattr(update, "run", lambda cmd, **k: SimpleNamespace(returncode=1))
    assert "failed (exit 1)" in refresh(tmp_path, ["devbox.json"])


def test_the_update_refreshes_the_lock_before_its_commit():
    """Wiring: the refresh runs on the changed files before the skeleton commit, so the lock lands in that commit."""
    src = open(update.__file__).read()
    assert src.index("refresh_devbox_lock(repo, changed)") < src.index('"commit", "-q", "-m", f"chore: update skeleton')
