"""Spec 208: the e2e scripts run their inline scripts with a throwaway uv cache and leave the developer's cache as it was (AC-208.2).

No cluster is needed: the scripts run with stubs for the tools they check for, and a `docker` stub that records the environment it
sees and then says docker is not running, so each script ends through its own `cleanup` trap right after its checks.
"""
import os
import re
import stat
import subprocess

import pytest

from runtemp_support import snapshot
from system_fixtures import ROOT
from waiting import with_prelude

LIB = ROOT / "tests" / "e2e" / "lib" / "uv-cache.sh"
SCRIPTS = ["run.sh", "cluster.sh", "upgrade.sh"]
TOOLS = ["k3d", "kubectl", "uv", "curl", "git", "python3"]


def stub(path, body):
    path.write_text(with_prelude("#!/bin/sh\n" + body))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def world(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for t in TOOLS:
        stub(bin_dir / t, "exit 0\n")
    seen = tmp_path / "seen.txt"
    stub(bin_dir / "docker", f'echo "$UV_CACHE_DIR" > {seen}\n[ -d "$UV_CACHE_DIR" ] && echo exists >> {seen}\nexit 1\n')
    dev = tmp_path / "dev-uv-cache"
    (dev / "environments-v2" / "keep").mkdir(parents=True)
    (dev / "environments-v2" / "keep" / "pyvenv.cfg").write_text("x")
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmpdir), "E2E_WORK": str(work),
           "UV_CACHE_DIR": str(dev)}
    return env, dev, tmpdir, seen


def bash_lib(snippet, env=None):
    return subprocess.run(["bash", "-c", f'. "{LIB}"\n{snippet}'], capture_output=True, text=True, timeout=60,
                          env=env or {"PATH": "/usr/bin:/bin"})


@pytest.mark.parametrize("script", SCRIPTS)
def test_a_script_that_fails_early_leaves_the_developers_cache_and_removes_its_own_ac_208_2(world, script):  # AC-208.2
    env, dev, tmpdir, seen = world
    before = snapshot(dev)
    p = subprocess.run(["bash", str(ROOT / "tests" / "e2e" / script)], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode != 0 and "docker is not running" in p.stderr, p.stdout + p.stderr
    lines = seen.read_text().split()
    used = lines[0]
    assert used != str(dev), "the script's inline-script runs do not use the developer's cache"
    assert lines[1:] == ["exists"], "the cache was started before the first uv"
    assert not os.path.exists(used), "the cache the script used is gone"
    assert snapshot(dev) == before
    assert not list(tmpdir.glob("e2e-uv-cache.*"))


def test_the_lib_starts_a_fresh_cache_outside_the_work_dir_and_ends_it_ac_208_2(tmp_path):  # AC-208.2
    p = bash_lib('''
export TMPDIR=%s
e2e_uv_cache_start
d="$UV_CACHE_DIR"
echo "$d"
[ -d "$d" ] || exit 11
mkdir -p "$d/environments-v2/x" && echo y > "$d/environments-v2/x/f" && chmod -R a-w "$d/environments-v2"   # uv keeps read-only files
e2e_uv_cache_end
[ ! -e "$d" ] || exit 12
e2e_uv_cache_end   # twice is fine
''' % tmp_path)
    assert p.returncode == 0, p.stderr
    assert p.stdout.split()[0].startswith(str(tmp_path) + "/e2e-uv-cache.")


def test_the_lib_overrides_a_developers_own_cache_location_ac_208_2(tmp_path):  # AC-208.2 (A6)
    mine = tmp_path / "mine"
    mine.mkdir()
    p = bash_lib('e2e_uv_cache_start\n[ "$UV_CACHE_DIR" != "$MINE" ] || exit 11\ne2e_uv_cache_end\n',
                 {"PATH": "/usr/bin:/bin", "UV_CACHE_DIR": str(mine), "MINE": str(mine), "TMPDIR": str(tmp_path)})
    assert p.returncode == 0, p.stderr
    assert mine.is_dir() and snapshot(mine) == {}


def test_the_lib_end_without_start_does_nothing_and_never_fails_ac_208_2():  # AC-208.2
    p = bash_lib("set -e\nunset E2E_UV_CACHE\ne2e_uv_cache_end\necho ok\n")
    assert p.returncode == 0 and p.stdout.strip() == "ok", p.stderr


@pytest.mark.parametrize("script", SCRIPTS)
def test_each_script_sources_the_lib_and_ends_the_cache_in_cleanup_ac_208_2(script):  # AC-208.2
    lines = (ROOT / "tests" / "e2e" / script).read_text().splitlines()
    source = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith((". ", "source ")) and "lib/uv-cache.sh" in ln)
    work = next(i for i, ln in enumerate(lines) if ln.startswith("work="))
    start = next(i for i, ln in enumerate(lines) if re.search(r"\be2e_uv_cache_start\b", ln) and not ln.lstrip().startswith("#"))
    checks = next(i for i, ln in enumerate(lines) if "command -v $t" in ln)
    assert source < work < start < checks, "the cache starts right after work=, before the first tool runs"
    c0 = next(i for i, ln in enumerate(lines) if ln.startswith("cleanup()"))
    c1 = next(i for i in range(c0, len(lines)) if lines[i] == "}")
    body = lines[c0:c1]
    end_at = next(i for i, ln in enumerate(body) if re.search(r"\be2e_uv_cache_end\b", ln) and not ln.lstrip().startswith("#"))
    assert end_at < next(i for i, ln in enumerate(body) if ln.strip() == "exit $rc")
    keep = [i for i, ln in enumerate(body) if 'E2E_KEEP:-0}" != 1' in ln]
    for k in keep:   # whatever E2E_KEEP says: the call is not inside the E2E_KEEP block
        fi = next(i for i in range(k, len(body)) if body[i].strip() == "fi")
        assert not k < end_at < fi


@pytest.mark.parametrize("script", SCRIPTS)
def test_each_script_still_parses_ac_208_2(script):  # AC-208.2
    p = subprocess.run(["bash", "-n", str(ROOT / "tests" / "e2e" / script)], capture_output=True, text=True)
    assert LIB.is_file() and p.returncode == 0, p.stderr
