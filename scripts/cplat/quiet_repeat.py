"""Spec 172 (AC-172.5): `cplat quiet test-fast --repeat N -- <tests>` runs the named tests N times at once, so a test that
only fails under load shows before the pull request. A failed test runs once more alone: it passes (flaky under load, exit 3,
never 0) or fails (a real failure, exit 1).
"""
from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path

import failsum
import flaky

MAX_LOAD_TESTS = 20   # more failing tests than this under load is not a flake


def _print_failure(summary, on: bool, reason: str, title: str, lines: list[str]) -> None:
    import quiet
    print(summary.render() if on else failsum.raw(title, "\n".join(lines), reason, quiet.TAIL))


def run(cwd: Path, n: int, args: list[str], *, raw: bool, on: bool) -> int:
    import quiet
    cmd = ["devbox", "run", "test-fast", "--", *args]
    logs = [quiet._log_path(cwd, f"test-fast-repeat-{i}") for i in range(1, n + 1)]
    fhs = [lg.open("wb") for lg in logs]
    try:
        procs = [subprocess.Popen(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                                  env={**os.environ, "CPLAT_REPEAT_RUN": str(i)}) for i, fh in enumerate(fhs, 1)]
        rcs = [p.wait() for p in procs]
    finally:
        for fh in fhs:
            fh.close()
    if not any(rcs):
        print(f"ok: {n} runs at once of devbox run test-fast passed (logs: {' '.join(str(lg) for lg in logs)})")
        return 0
    reason = "--raw" if raw else ""
    failed = [(lg, rc) for lg, rc in zip(logs, rcs) if rc]
    summaries, texts = [], []
    for lg, rc in failed:
        lines = lg.read_text(errors="replace").splitlines()
        texts.append(lines)
        title = f"FAILED (exit {rc}): devbox run test-fast -- {' '.join(args)} (log: {lg})"
        summaries.append((title, failsum.summarize("\n".join(lines), title=title, check="test-fast",
                                                   command=" ".join(cmd[:3] + ["--", *args]), exit_code=rc, log=lg,
                                                   root=cwd)))
    found = [flaky.failed_tests(s, limit=MAX_LOAD_TESTS) for _, s in summaries]
    if any(f is None for f in found) or len({f[0] for f in found}) != 1:
        title, s = summaries[0]
        _print_failure(s, on, reason, title, texts[0])
        print("FAILED under load: a failure not attributable to named tests")
        return 1
    tool = found[0][0]
    in_logs: dict[str, list[Path]] = {}
    for (lg, _), (_, tests) in zip(failed, found):
        for t in dict.fromkeys(tests):
            in_logs.setdefault(t, []).append(lg)
    counts = Counter({t: len(v) for t, v in in_logs.items()})
    flaky_n = real = 0
    for j, t in enumerate(sorted(counts), 1):
        rargs = flaky.rerun_args(tool, [t])
        log = quiet._log_path(cwd, f"test-fast-alone-{j}")
        with log.open("wb") as fh:
            rc = subprocess.run(["devbox", "run", "test-fast", "--", *rargs], cwd=cwd, stdout=fh,
                                stderr=subprocess.STDOUT).returncode
        if rc == 0:
            flaky_n += 1
            print(f"flaky under load: {t} (failed in {counts[t]} of {n} runs)")
            print(f"  failed in: {', '.join(str(x) for x in in_logs[t])}")
            try:
                import runs
                runs.add_to(runs.current_run(cwd), "flaky_tests",
                            {"test": t, "script": "test-fast", "repeat": n, "failed_runs": counts[t]})
            except Exception:  # noqa: BLE001  (recording never changes the result)
                pass
            continue
        real += 1
        lines = log.read_text(errors="replace").splitlines()
        title = f"FAILED (exit {rc}): devbox run test-fast -- {' '.join(rargs)} (log: {log})"
        s = failsum.summarize("\n".join(lines), title=title, check="test-fast",
                              command="devbox run test-fast -- " + " ".join(rargs), exit_code=rc, log=log, root=cwd)
        _print_failure(s, on, reason, title, lines)
    if real:
        return 1
    print(f"FLAKY: {flaky_n} test(s) failed under load and passed alone; fix the harness before the pull request")
    return 3
