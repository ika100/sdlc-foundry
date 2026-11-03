"""Spec 134: tests/e2e/run.sh runs as one sequence (E2E_PART=all) or as one of three parts (AC-134.5, AC-134.7).

The cluster run itself happens only in the e2e workflow; here the guards are read from the script and the part selection is run in bash.
"""
import re
import subprocess

import pytest

from system_fixtures import ROOT

RUN_SH = ROOT / "tests" / "e2e" / "run.sh"
PARTS = {"core", "scaling", "backups"}
GUARD = re.compile(r'^if in_part "([^"]+)" ([a-z ]+); then\b')
END = re.compile(r"^fi\s+# end part\b")
STEP = re.compile(r'^\s*[cnsb]?step "([^"]+)"')


def steps_with_parts() -> list[tuple[str, set[str]]]:
    """Every step of run.sh with the parts that run it (the intersection of the guards around it)."""
    stack: list[set[str]] = []
    out = []
    for line in RUN_SH.read_text().splitlines():
        if m := GUARD.match(line):
            stack.append(set(m[2].split()))
        elif END.match(line):
            assert stack, "an `fi  # end part` without its guard"
            stack.pop()
        elif m := STEP.match(line):
            out.append((m[1], set.intersection(PARTS, *stack) if stack else set(PARTS)))
    assert not stack, "a part guard is not closed with `fi  # end part`"
    return out


def parts_of(prefix: str) -> list[set[str]]:
    got = [p for name, p in steps_with_parts() if name.startswith(prefix)]
    assert got, f"no step starts with {prefix!r}"
    return got


def in_part(part: str, *args: str) -> subprocess.CompletedProcess:
    text = RUN_SH.read_text()
    m = re.search(r"^in_part\(\) \{.*?^\}", text, re.S | re.M)
    assert m, "run.sh defines in_part() { ... }"
    script = m[0] + '\nin_part "$@"\n'
    return subprocess.run(["bash", "-c", script, "in_part", *args], env={"E2E_PART": part, "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True)


def test_an_unknown_part_fails_before_the_cluster_starts_ac_134_5(tmp_path):  # AC-134.5
    p = subprocess.run(["bash", str(RUN_SH)], env={"E2E_PART": "nightly", "PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                                                   "E2E_WORK": str(tmp_path)}, capture_output=True, text=True, timeout=60)
    assert p.returncode == 1
    assert "E2E FAIL: E2E_PART must be one of all core scaling backups (got nightly)" in p.stderr
    assert "docker" not in p.stderr and "==> " not in p.stdout


@pytest.mark.parametrize("part, args, ok", [
    ("all", ["bucket checks", "core"], True),
    ("core", ["bucket checks", "core"], True),
    ("scaling", ["the broker", "core", "scaling"], True),
    ("backups", ["the broker", "core", "scaling"], False),
    ("scaling", ["backups", "backups"], False),
])
def test_in_part_selects_a_block_for_all_or_a_listed_part_ac_134_5(part, args, ok):  # AC-134.5
    p = in_part(part, *args)
    assert (p.returncode == 0) is ok, p
    if ok:
        assert p.stdout == ""
    else:
        assert f"==> skip [{part}] {args[0]} (parts: {' '.join(args[1:])})" in p.stdout.splitlines()


def test_the_shared_setup_runs_in_every_part_ac_134_5():  # AC-134.5
    for prefix in ("Create the system", "Start the local cluster", "Build and push the images", "Describe the components",
                   "Apply the guard rails", "Apply the Postgres addon", "Apply the bucket addon", "Apply the generated manifests",
                   "Probe through the Gateway", "Generated secrets", "Kyverno:", "External database", "External bucket", "Caches:"):
        assert all(p == PARTS for p in parts_of(prefix)), prefix


@pytest.mark.parametrize("prefix, want", [
    ("Bucket: e2e-api writes", {"core"}), ("Bucket versioning", {"core"}), ("Bucket: delete the store", {"core"}),
    ("Bucket: syncing", {"core"}), ("Broker:", {"core", "scaling"}), ("Scaling:", {"scaling"}),
    ("Write and approve a spec", {"core"}), ("Verify dev", {"core"}), ("Promote the built commit", {"core"}),
    ("Bucket in staging", {"core"}), ("End the ship run", {"core"}),
    ("Backups:", {"backups"}), ("Database ", {"backups"}), ("Environment ", {"backups"}),
])
def test_each_scenario_runs_in_its_parts_ac_134_5(prefix, want):  # AC-134.5
    assert all(p == want for p in parts_of(prefix)), (prefix, parts_of(prefix))


def test_every_step_runs_in_at_least_one_part_ac_134_5():  # AC-134.5
    missing = [name for name, parts in steps_with_parts() if not parts]
    assert not missing, missing


def test_the_two_longest_scenarios_run_in_different_parts_and_not_in_core_ac_134_7():  # AC-134.7
    scaling = set.union(*parts_of("Scaling:"))
    backups = set.union(*parts_of("Backups:"), *parts_of("Database "), *parts_of("Environment "))
    assert not scaling & backups and "core" not in scaling | backups
