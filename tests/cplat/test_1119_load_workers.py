"""#1119: test-fast sizes pytest workers by the machine load, and a give-up under high load names the machine."""
import quiet_limit


def fake(monkeypatch, cpus, load):
    monkeypatch.setattr(quiet_limit, "cpus", lambda: cpus)
    monkeypatch.setattr(quiet_limit, "load", lambda: load)


def test_workers_shrink_with_load(monkeypatch):
    fake(monkeypatch, 16, 2.0)
    assert quiet_limit.workers() == 14
    fake(monkeypatch, 16, 118.0)
    assert quiet_limit.workers() == 2
    fake(monkeypatch, 16, 0.0)
    assert quiet_limit.workers() == 16


def test_progress_env_carries_workers(monkeypatch, tmp_path):
    fake(monkeypatch, 8, 4.0)
    env, _ = quiet_limit.progress_env(tmp_path / "log")
    assert env[quiet_limit.WORKERS_ENV] == "4"


def test_give_up_under_load_names_the_machine(monkeypatch, tmp_path):
    fake(monkeypatch, 16, 275.0)
    lines = quiet_limit.gave_up_lines("test-fast", tmp_path / "log", tmp_path / "none")
    assert "environment: machine overloaded (load 275)" in "\n".join(lines)


def test_give_up_on_idle_machine_stays_plain(monkeypatch, tmp_path):
    fake(monkeypatch, 16, 3.0)
    lines = quiet_limit.gave_up_lines("test-fast", tmp_path / "log", tmp_path / "none")
    assert not any("overloaded" in ln for ln in lines)
