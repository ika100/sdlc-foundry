"""Spec 210 acceptance tests: the status line sensor (AC-210.5).

Contract: design.md "Usage files", "Sensor" (`sensor install`/`remove`, `U/sensor.py`, `readings.json`, `sensor.json`). The status line
inputs are fixtures fed to the installed command through a shell on stdin, as Claude Code does; `HOME`, `XDG_STATE_HOME` and
`CLAUDE_CONFIG_DIR` are in the test's temp dir; `CPLAT_SENSOR_NOW` sets the clock. No subscription, no network.
"""
import json
import re

import pytest

from waiting import with_prelude
from dispatch_world import world  # noqa: F401  (fixture)
from support_210 import M, read_json, run_status_line, sensor_env, status_input, usage_dir


@pytest.fixture()
def cfg(world, monkeypatch):
    d = world.tmp / "claude-config"
    d.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(d))
    return d / "settings.json"


def _install(world):
    r = world.run("sensor", "install")
    assert r.rc == 0, r
    return r


def _command(settings):
    return json.loads(settings.read_text())["statusLine"]["command"]


def _readings(world):
    return read_json(usage_dir(world) / "readings.json")


def test_install_points_the_status_line_at_the_copied_sensor_ac_210_5(world, cfg):  # AC-210.5
    r = _install(world)
    assert f"sensor installed: {cfg}" in r.out
    line = json.loads(cfg.read_text())["statusLine"]
    assert line["type"] == "command" and str(usage_dir(world) / "sensor.py") in line["command"]
    assert (usage_dir(world) / "sensor.py").is_file()
    rec = read_json(usage_dir(world) / "sensor.json")
    assert rec["previous"] is None and rec["settings"] == str(cfg)


def test_a_status_line_input_with_both_windows_records_a_reading_with_the_time_ac_210_5(world, cfg):  # AC-210.5
    _install(world)
    now = world.now
    p = run_status_line(_command(cfg), status_input(five=(83.5, 1763466300), seven=(41, 1763900000)), sensor_env(world, now))
    assert p.returncode == 0, p.stderr
    doc = _readings(world)
    assert doc["five_hour"]["last"] == {"at": pytest.approx(now.timestamp()), "used": 83.5, "resets_at": 1763466300}
    assert doc["seven_day"]["last"] == {"at": pytest.approx(now.timestamp()), "used": 41, "resets_at": 1763900000}


def test_without_a_previous_status_line_the_sensor_prints_the_short_line_ac_210_5(world, cfg):  # AC-210.5
    _install(world)
    p = run_status_line(_command(cfg), status_input(five=(83, 1763466300), seven=(41, 1763900000)), sensor_env(world, world.now))
    assert p.stdout.decode().strip() == "5h 83 % · 7d 41 %"


def test_input_without_rate_limits_leaves_the_last_readings_in_place_ac_210_5(world, cfg):  # AC-210.5
    _install(world)
    run_status_line(_command(cfg), status_input(five=(83, 1763466300), seven=(41, 1763900000)), sensor_env(world, world.now))
    before = _readings(world)
    for payload in (status_input(), "not json at all", ""):
        p = run_status_line(_command(cfg), payload, sensor_env(world, world.now + 10 * M))
        assert p.returncode == 0                                   # the status line never breaks
    assert _readings(world) == before


def test_input_with_one_window_keeps_the_other_windows_last_reading_ac_210_5(world, cfg):  # AC-210.5
    _install(world)
    run_status_line(_command(cfg), status_input(five=(83, 1763466300), seven=(41, 1763900000)), sensor_env(world, world.now))
    later = world.now + 20 * M
    run_status_line(_command(cfg), status_input(five=(90, 1763466300)), sensor_env(world, later))
    doc = _readings(world)
    assert doc["five_hour"]["last"]["used"] == 90 and doc["five_hour"]["last"]["at"] == pytest.approx(later.timestamp())
    assert doc["seven_day"]["last"] == {"at": pytest.approx(world.now.timestamp()), "used": 41, "resets_at": 1763900000}
    run_status_line(_command(cfg), status_input(seven=(44, 1763900000)), sensor_env(world, later + 5 * M))
    assert _readings(world)["five_hour"]["last"]["used"] == 90 and _readings(world)["seven_day"]["last"]["used"] == 44


def test_the_status_line_the_user_had_prints_its_output_unchanged_after_the_install_ac_210_5(world, cfg):  # AC-210.5
    cfg.write_text(json.dumps({"theme": "dark", "statusLine": {"type": "command", "command": "cat > /dev/null; printf 'my line\\033[1m bold'", "padding": 2}}))
    r = _install(world)
    assert "earlier status line kept" in r.out
    doc = json.loads(cfg.read_text())
    assert doc["theme"] == "dark" and doc["statusLine"]["padding"] == 2 and doc["statusLine"]["command"] != "cat > /dev/null; printf 'my line\\033[1m bold'"
    p = run_status_line(doc["statusLine"]["command"], status_input(five=(12, 1763466300), seven=(5, 1763900000)), sensor_env(world, world.now))
    assert p.returncode == 0
    assert p.stdout == b"my line\x1b[1m bold"
    assert _readings(world)["five_hour"]["last"]["used"] == 12                 # and the reading was still taken


def test_the_earlier_status_line_gets_the_same_input_on_stdin_ac_210_5(world, cfg):  # AC-210.5
    cfg.write_text(json.dumps({"statusLine": {"type": "command", "command": "python3 -c \"import json,sys; print(json.load(sys.stdin)['model']['display_name'])\""}}))
    _install(world)
    p = run_status_line(_command(cfg), status_input(five=(1, 1763466300)), sensor_env(world, world.now))
    assert p.stdout.decode().strip() == "Opus"


def test_remove_restores_the_earlier_configuration_ac_210_5(world, cfg):  # AC-210.5
    earlier = {"theme": "dark", "statusLine": {"type": "command", "command": "echo hi", "padding": 1}}
    cfg.write_text(json.dumps(earlier))
    _install(world)
    r = world.run("sensor", "remove")
    assert r.rc == 0 and f"sensor removed: {cfg}" in r.out, r
    assert json.loads(cfg.read_text()) == earlier
    assert not (usage_dir(world) / "sensor.json").exists() and not (usage_dir(world) / "sensor.py").exists()


def test_install_twice_keeps_the_first_earlier_configuration_ac_210_5(world, cfg):  # AC-210.5
    earlier = {"statusLine": {"type": "command", "command": "echo hi"}}
    cfg.write_text(json.dumps(earlier))
    _install(world)
    _install(world)
    world.run("sensor", "remove")
    assert json.loads(cfg.read_text()) == earlier


def test_remove_without_an_earlier_status_line_deletes_the_entry_ac_210_5(world, cfg):  # AC-210.5
    cfg.write_text(json.dumps({"theme": "dark"}))
    _install(world)
    assert "statusLine" in json.loads(cfg.read_text())
    assert world.run("sensor", "remove").rc == 0
    assert json.loads(cfg.read_text()) == {"theme": "dark"}


def test_remove_leaves_a_status_line_changed_since_the_install_alone_ac_210_5(world, cfg):  # AC-210.5
    _install(world)
    doc = json.loads(cfg.read_text())
    doc["statusLine"] = {"type": "command", "command": "echo changed"}
    cfg.write_text(json.dumps(doc))
    r = world.run("sensor", "remove")
    assert r.rc == 0 and "the status line was changed since the install; left unchanged" in r.out, r
    assert json.loads(cfg.read_text())["statusLine"]["command"] == "echo changed"


def test_remove_without_an_install_says_so_and_exits_0_ac_210_5(world, cfg):  # AC-210.5
    r = world.run("sensor", "remove")
    assert r.rc == 0 and "no sensor installed" in r.out, r


def test_a_settings_file_that_is_no_json_object_is_refused_and_not_written_ac_210_5(world, cfg):  # AC-210.5
    cfg.write_text("[1, 2]")
    r = world.run("sensor", "install")
    assert r.rc == 1 and str(cfg) in r.err, r
    assert cfg.read_text() == "[1, 2]" and not (usage_dir(world) / "sensor.py").exists()


def test_plan_shows_the_reading_the_sensor_recorded_ac_210_5(world, cfg):  # AC-210.5
    world.policy(budget={"mode": "plan"})
    _install(world)
    at = world.now - 4 * M
    five_reset, seven_reset = world.now.replace(hour=15, minute=45), world.now.replace(hour=15, minute=45) + 3 * 24 * 60 * M
    run_status_line(_command(cfg), status_input(five=(33, int(five_reset.timestamp())), seven=(12, int(seven_reset.timestamp()))),
                    sensor_env(world, at))
    doc = world.plan()["plan"]
    assert doc["source"] == "reading"
    assert doc["five_hour"]["used"] == 33 and doc["seven_day"]["used"] == 12
    assert re.search(r"plan usage: 5h 33 % .*week 12 % .*reading 4 min old", world.run("plan").out), world.run("plan").out


def test_install_skips_uv_cache_pythons_and_refuses_a_command_that_does_not_run(world, cfg, monkeypatch, tmp_path):  # issue #1095
    import dispatch_sensor as dsn
    tmp = tmp_path / "uv" / "builds-v0" / ".tmpX" / "bin"
    tmp.mkdir(parents=True)
    (tmp / "python3").write_text(with_prelude("#!/bin/sh\nexit 1\n"))
    (tmp / "python3").chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp}:{__import__('os').environ['PATH']}")
    assert "builds-v0" not in dsn._stable_python()
    _install(world)
    assert "builds-v0" not in _command(cfg)
    monkeypatch.setattr(dsn, "_stable_python", lambda: "/nonexistent/python3")
    r = world.run("sensor", "install")
    assert r.rc != 0, r
