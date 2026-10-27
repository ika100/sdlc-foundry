"""Spec 122 acceptance tests: `cplat ui` starts a local server (AC-122.1) and sends nothing anywhere else (AC-122.2).

Contract: design.md Decisions, plan t12. The command runs as a real subprocess with an empty PATH (no gh, kubectl or claude), so
nothing can reach a network."""
import http.client
import os
import queue
import re
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import cplat
from console_support import CPLAT, ROOT, STATIC
from system_fixtures import rich5, write_system


@pytest.fixture()
def gitops(tmp_path):
    d = tmp_path / "shop-gitops"
    write_system(d, rich5())
    return d


def env_for(tmp_path, **extra):
    bindir = tmp_path / "emptybin"
    bindir.mkdir(exist_ok=True)
    e = {"PATH": str(bindir), "HOME": str(tmp_path / "home"), "XDG_STATE_HOME": str(tmp_path / "state"), "XDG_CACHE_HOME": str(tmp_path / "cache"),
         "XDG_CONFIG_HOME": str(tmp_path / "config"), "PYTHONUNBUFFERED": "1"}
    e.update(extra)
    return e


class Ui:
    def __init__(self, tmp_path, gitops, *args, **env):
        self.p = subprocess.Popen([sys.executable, str(CPLAT), "ui", "--repo-dir", str(gitops), "--no-notify", *args], env=env_for(tmp_path, **env),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.lines = queue.Queue()
        threading.Thread(target=lambda: [self.lines.put(ln) for ln in self.p.stdout], daemon=True).start()
        end = time.time() + 30
        self.url = None
        while time.time() < end and self.url is None:
            try:
                ln = self.lines.get(timeout=0.5)
            except queue.Empty:
                assert self.p.poll() is None, self.p.stderr.read()
                continue
            m = re.search(r"http://127\.0\.0\.1:(\d+)/?", ln)
            if m:
                self.url, self.port = m.group(0), int(m.group(1))
        assert self.url, "no URL printed"

    def get(self, path="/"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request("GET", path)
        r = c.getresponse()
        return r.status, r.read()

    def stop(self):
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGTERM)
            try:
                self.p.wait(15)
            except subprocess.TimeoutExpired:
                self.p.kill()


@pytest.fixture()
def ui(tmp_path, gitops):
    started = []

    def start(*args, **env):
        u = Ui(tmp_path, gitops, *args, **env)
        started.append(u)
        return u

    yield start
    for u in started:
        u.stop()


def test_ui_prints_its_url_on_127_0_0_1_and_serves_ac_122_1(ui):  # AC-122.1
    u = ui("--no-open")
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/?", u.url)
    status, _ = u.get("/inbox")
    assert status == 200


def test_ui_takes_a_free_port_each_time_ac_122_1(ui):  # AC-122.1
    a, b = ui("--no-open"), ui("--no-open")
    assert a.port != b.port


def test_ui_opens_the_url_in_the_default_browser_ac_122_1(tmp_path, ui):  # AC-122.1
    opener = tmp_path / "opener.sh"
    seen = tmp_path / "opened.txt"
    opener.write_text(f"#!/bin/sh\necho \"$1\" >> {seen}\n")
    opener.chmod(opener.stat().st_mode | stat.S_IEXEC)
    u = ui(BROWSER=f"{opener} %s")
    end = time.time() + 15
    while time.time() < end and not seen.exists():
        time.sleep(0.2)
    assert seen.exists() and f"127.0.0.1:{u.port}" in seen.read_text()


def test_no_open_skips_the_browser_ac_122_1(tmp_path, ui):  # AC-122.1
    opener = tmp_path / "opener.sh"
    seen = tmp_path / "opened.txt"
    opener.write_text(f"#!/bin/sh\necho \"$1\" >> {seen}\n")
    opener.chmod(opener.stat().st_mode | stat.S_IEXEC)
    ui("--no-open", BROWSER=f"{opener} %s")
    time.sleep(2)
    assert not seen.exists()


def test_outside_a_gitops_repo_it_fails_naming_system_yaml_and_the_directory_ac_122_1(tmp_path, capsys):  # AC-122.1
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    rc = cplat.main(["ui", "--repo-dir", str(empty), "--no-open", "--no-notify"])
    err = capsys.readouterr().err
    assert rc == 1 and "system.yaml" in err and str(empty) in err


def test_platform_ui_is_an_alias_ac_122_1(tmp_path, capsys):  # AC-122.1
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    assert cplat.main(["platform", "ui", "--repo-dir", str(empty), "--no-open", "--no-notify"]) == 1
    assert "system.yaml" in capsys.readouterr().err


def test_the_slash_command_runs_cplat_platform_ui_ac_122_1():  # AC-122.1
    import yaml
    text = (ROOT / "plugins" / "platform" / "commands" / "ui.md").read_text()
    fm = yaml.safe_load(re.match(r"^---\n(.*?)\n---", text, re.S).group(1))
    assert "Usage: /platform:ui" in fm["description"] and len(fm["description"]) <= 260
    assert "cplat platform ui" in text and "$ARGUMENTS" in text


# ---------------- AC-122.2: local only, no telemetry ----------------

def test_the_server_listens_on_localhost_only_ac_122_2(tmp_path, console):  # AC-122.2
    c = console()
    assert c.httpd.server_address[0] == "127.0.0.1"


def test_the_console_code_opens_no_connection_of_its_own_ac_122_2():  # AC-122.2
    """Only GitHub (through gh), the clusters (through the cplat subprocesses) and the notification endpoints (notify.py) are reached."""
    banned = re.compile(r"urllib\.request|http\.client|import requests|import httpx|aiohttp|smtplib|socket\.create_connection|websocket")
    files = sorted((ROOT / "scripts" / "cplat" / "console").glob("*.py")) + [ROOT / "scripts" / "cplat" / "ui.py"]
    assert len(files) > 3
    offenders = [f.name for f in files if banned.search(f.read_text())]
    assert offenders == []


def test_the_browser_files_name_no_external_host_ac_122_2():  # AC-122.2
    for name in ("console.js", "console.css"):
        text = (STATIC / name).read_text()
        assert not re.search(r"https?://", text), name
        assert "XMLHttpRequest" not in text and "sendBeacon" not in text and "WebSocket" not in text


def test_a_page_loads_nothing_from_outside_ac_122_2(console):  # AC-122.2
    from console_support import q
    c = console()
    for path in ("/inbox", "/board", "/system"):
        root, _ = c.page(path)
        loaded = [n.attrs.get("src") for n in q(root, "script") + q(root, "img") + q(root, "iframe") if n.attrs.get("src")]
        loaded += [n.attrs["href"] for n in q(root, "link") if n.attrs.get("href")]
        assert loaded and all(r.startswith("/static/") for r in loaded), (path, loaded)
