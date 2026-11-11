"""Spec 184: a second process that holds a repo slot (not a test file).

A flock is held by an open file of the process that took it, so a test that needs a slot taken against itself starts a process
that runs `run_slot.held` and keeps it until the test writes a release file.
"""
import subprocess
import sys

import core
from waiting import wait_for, wait_process

SCRIPTS = str(core.PLATFORM_ROOT / "scripts" / "cplat")
HOLDER = r'''
import sys, time
from pathlib import Path
sys.path.insert(0, %(scripts)r)
import run_slot
repo, command, ready, release = sys.argv[1:5]
with run_slot.held(Path(repo), command):
    Path(ready).write_text("held")
    while not Path(release).exists():
        time.sleep(0.05)  # fake-delay: holds the slot until the test writes the release file
'''


class Held:
    def __init__(self, proc, release):
        self.proc, self.release_file = proc, release
        self.pid = proc.pid

    def end(self):
        self.release_file.write_text("")
        wait_process(self.proc)


class Holders:
    def __init__(self, tmp_path):
        self.tmp, self.procs, self.n = tmp_path, [], 0

    def start(self, repo, command="/component:ship 182") -> Held:
        self.n += 1
        ready, release = self.tmp / f"ready{self.n}", self.tmp / f"release{self.n}"
        script = self.tmp / "holder.py"
        script.write_text(HOLDER % {"scripts": SCRIPTS})
        proc = subprocess.Popen([sys.executable, str(script), str(repo), command, str(ready), str(release)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.procs.append((proc, release))
        wait_for(lambda: ready.exists() or proc.poll() is not None, what="the holder to take its slot")
        assert ready.exists(), proc.communicate()[0]
        return Held(proc, release)

    def close(self):
        for proc, release in self.procs:
            release.write_text("")
            try:
                wait_process(proc, 20)
            except AssertionError:
                proc.kill()
