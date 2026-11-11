"""Spec 183 acceptance test: a reader that closes stdout early ends a cplat command with 141 and a quiet stderr (AC-183.7).

The command runs in a child Python (the fd 1 redirect of the fix must not touch pytest's own capture). A stand-in command
registered in `cplat.PLUMBING` writes a line, waits until the reader is gone and writes again; the crash handler is replaced
by one that leaves a marker file, so a filed issue or hint shows."""
import subprocess
import sys
import textwrap
import time

import core

CHILD = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {scripts!r})
    sys.path.insert(0, {fake!r})
    import cplat
    cplat.PLUMBING["fakecmd"] = "fakecmd"
    def crash(argv, exc):
        open({marker!r}, "w").write(repr(exc))
        return ["crash handler reached"]
    cplat._file_crash = crash
    sys.exit(cplat.main(["fakecmd"]))
""")

FAKE = textwrap.dedent("""
    import sys, time

    def main(argv):
        print("first line", flush=True)
        time.sleep(1.5)
        for i in range(2000):
            print("more output", i)
        return 0
""")


def test_a_closed_pipe_exits_141_without_a_traceback_ac_183_7(tmp_path):  # AC-183.7
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "fakecmd.py").write_text(FAKE)
    marker = tmp_path / "crashed"
    script = CHILD.format(scripts=str(core.PLATFORM_ROOT / "scripts" / "cplat"), fake=str(fake), marker=str(marker))
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "first line"
    proc.stdout.close()
    started = time.time()
    err = proc.stderr.read()
    rc = proc.wait(timeout=30)
    assert rc == 141, err
    assert err == ""
    assert not marker.exists()
    assert time.time() - started < 25
