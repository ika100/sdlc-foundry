"""Shared helpers of the spec 130 acceptance tests (not a test module, never collected).

Contract: docs/specs/130-quality-gates-fail-when-they-checked/design.md ("Contract"). The helpers render a template once per process
(ADR-052 shared renders, copied privately per test) and run its recipes exactly as `devbox run <recipe>` would: `sh -c "<recipe text>"`
in the rendered repo, with stub tools first on PATH. The stubs are small POSIX shell scripts steered by STUB_* environment variables:

  uv          `uv run python -m pytest ...` / `uv run pytest ...` -> a JUnit XML at --junitxml=; `uv run <script>.py` -> the platform's own
              interpreter (so scripts/render.py, plan.py ... run for real); anything else exits 0.
              STUB_RENDER_EMPTY=1 runs `scripts/render.py --check` with render_files() patched to return {} (a render that compares 0 files).
  go, mvn, pnpm   report tests per STUB_GO / STUB_MVN / STUB_VITEST (see each script).
  kustomize, kubeconform   print STUB_KUSTOMIZE / the STUB_KUBECONFORM summary (default: nothing / 0 resources).
  detect-secrets-hook, kyverno   exit 0; the first one is logged so a test can see that it never ran.
  devbox      `devbox run <name>`: the gates and composites (test, test-fast, validate, render-check, secrets-scan, ci, quality, security)
              run their recipe text from ./devbox.json; every other recipe (lint, typecheck, audit ...) is a stub that passes.

Everything the feature adds is reached inside test bodies, so a missing gate.sh, recipe or doc fails the test, never the collection."""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
GATE_SOURCE = TEMPLATES / "gitops-app" / "scripts" / "gate.sh"

# AC-130.14: the coverage table. template -> covered gates (recipes). Keep equal to the templates of shapes.yml.
TEST_TEMPLATES = ["service-python", "library-python", "service-go", "service-java", "web-nextjs"]
GITOPS_TEMPLATES = ["gitops-app", "cluster-gitops"]
COVERED = {t: ["test", "test-fast", "secrets-scan"] for t in TEST_TEMPLATES}
COVERED.update({t: ["test", "test-fast", "validate", "render-check", "secrets-scan"] for t in GITOPS_TEMPLATES})

# <fix> texts of the contract table
FIX_TESTS = "add at least one test"
FIX_VALIDATE_APP = "run `devbox run render` and check that the system has components"
FIX_VALIDATE_CLUSTER = "run `devbox run render` and check that cluster/kustomization.yaml lists resources"
FIX_RENDER_APP = "run `devbox run render` and check that applications/<system>/system.yaml exists"
FIX_RENDER_CLUSTER = "run `devbox run render` and check cluster.yaml"
FIX_SECRETS = "commit at least one file that the scan does not exclude (`git add`)"

SECRET_FLAGS = "--baseline .secrets.baseline.json --disable-filter detect_secrets.filters.gibberish.should_exclude_secret"
# the pathspec of each template's secrets-scan and a file that pathspec excludes
SECRET_PATHSPEC = {"service-python": "':!*.lock'", "library-python": "':!*.lock'", "service-go": "':!go.sum'",
                   "web-nextjs": "':!pnpm-lock.yaml'"}
EXCLUDED_FILE = {"service-python": "uv.lock", "library-python": "uv.lock", "service-go": "go.sum", "web-nextjs": "pnpm-lock.yaml"}


def line(gate: str, what: str, fix: str) -> str:
    """The AC-130.1 line."""
    return f"{gate}: checked nothing: {what} - {fix}"


def no_tests_line(gate: str) -> str:
    return line(gate, "0 tests ran", FIX_TESTS)


def secrets_line() -> str:
    return line("secrets-scan", "0 files to scan", FIX_SECRETS)


def validate_line(template: str, gate: str = "validate") -> str:
    return line(gate, "0 resources", FIX_VALIDATE_APP if template == "gitops-app" else FIX_VALIDATE_CLUSTER)


def render_line(template: str, gate: str) -> str:
    return line(gate, "0 files compared", FIX_RENDER_APP if template == "gitops-app" else FIX_RENDER_CLUSTER)


# ---------------- stub tools ----------------

_COMMON = '''#!/bin/sh
log() { [ -n "$STUB_LOG" ] && printf '%s\\n' "$*" >> "$STUB_LOG"; return 0; }
'''

UV = _COMMON + '''
PY="@PY@"
junit() { printf '<?xml version="1.0" encoding="utf-8"?>\\n<testsuites name="pytest tests"><testsuite name="pytest" errors="0" failures="%s" skipped="%s" tests="%s" time="0.01"></testsuite></testsuites>\\n' "$4" "$3" "$2" > "$1"; }
stub_pytest() {
  xml=""
  for a in "$@"; do case "$a" in --junitxml=*) xml=${a#--junitxml=};; esac; done
  log "pytest $*"
  case "${STUB_PYTEST:-empty}" in
    empty)   [ -n "$xml" ] && junit "$xml" 0 0 0; echo "no tests ran in 0.01s"; exit "${STUB_PYTEST_EXIT:-5}";;
    skipped) [ -n "$xml" ] && junit "$xml" 3 3 0; echo "3 skipped in 0.01s"; exit 0;;
    pass)    [ -n "$xml" ] && junit "$xml" 2 0 0; echo "2 passed in 0.01s"; exit 0;;
    mixed)   [ -n "$xml" ] && junit "$xml" 5 2 0; echo "3 passed, 2 skipped in 0.01s"; exit 0;;
    fail)    [ -n "$xml" ] && junit "$xml" 2 0 1; echo "1 failed, 1 passed in 0.01s"; exit "${STUB_FAIL_EXIT:-1}";;
    broken)  echo "ImportError: cannot import name x" >&2; exit "${STUB_BROKEN_EXIT:-1}";;
  esac
}
[ "$1" = run ] && shift
log "uv $*"
case "$1" in
  python)
    shift
    if [ "$1" = "-m" ] && [ "$2" = "pytest" ]; then shift 2; stub_pytest "$@"; fi
    exec "$PY" "$@";;
  pytest) shift; stub_pytest "$@";;
  scripts/render.py)
    if [ -n "$STUB_RENDER_EMPTY" ] && [ "$2" = "--check" ]; then exec "$PY" "$(dirname "$0")/render_empty.py"; fi
    exec "$PY" "$@";;
  *.py) exec "$PY" "$@";;
  *) exit 0;;
esac
'''

RENDER_EMPTY = '''import sys
sys.path.insert(0, "scripts")
import render
render.render_files = lambda *a, **k: {}
sys.argv = ["render.py", "--check"]
sys.exit(render.main())
'''

GO = _COMMON + '''
[ "$1" = test ] || exit 0
shift
log "go test $*"
case "${STUB_GO:-empty}" in
  empty)   printf '?   \\tdemo/cmd\\t[no test files]\\nok  \\tdemo/internal\\t0.004s [no tests to run]\\n'; exit 0;;
  skipped) printf '=== RUN   TestA\\n--- SKIP: TestA (0.00s)\\n    a_test.go:5: skipping\\nPASS\\nok  \\tdemo/internal\\t0.004s\\n'; exit 0;;
  pass)    printf '=== RUN   TestA\\n--- PASS: TestA (0.00s)\\n=== RUN   TestB\\n    --- PASS: TestB/sub (0.00s)\\n--- PASS: TestB (0.00s)\\nPASS\\nok  \\tdemo/internal\\t0.004s\\n'; exit 0;;
  fail)    printf '=== RUN   TestA\\n--- FAIL: TestA (0.00s)\\nFAIL\\nFAIL\\tdemo/internal\\t0.004s\\n'; exit "${STUB_FAIL_EXIT:-1}";;
  broken)  echo "FAIL	demo/internal [build failed]"; echo "undefined: x" >&2; exit "${STUB_BROKEN_EXIT:-1}";;
esac
'''

MVN = _COMMON + '''
log "mvn $*"
report() { mkdir -p target/surefire-reports; printf '<?xml version="1.0" encoding="UTF-8"?>\\n<testsuite name="demo.DemoTest" time="0.01" tests="%s" errors="0" skipped="%s" failures="%s">\\n<testcase name="a" classname="demo.DemoTest" time="0"/>\\n</testsuite>\\n' "$1" "$2" "$3" > target/surefire-reports/TEST-demo.DemoTest.xml; }
case "${STUB_MVN:-empty}" in
  empty)   echo "[INFO] No tests to run."; echo "[INFO] BUILD SUCCESS"; exit 0;;
  skipped) report 2 2 0; echo "[WARNING] Tests run: 2, Failures: 0, Errors: 0, Skipped: 2"; echo "[INFO] BUILD SUCCESS"; exit 0;;
  pass)    report 2 0 0; echo "[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0"; echo "[INFO] BUILD SUCCESS"; exit 0;;
  fail)    report 2 0 1; echo "[ERROR] Tests run: 2, Failures: 1"; echo "[INFO] BUILD FAILURE"; exit "${STUB_FAIL_EXIT:-1}";;
  broken)  echo "[ERROR] COMPILATION ERROR"; echo "[INFO] BUILD FAILURE"; exit "${STUB_BROKEN_EXIT:-1}";;
esac
'''

PNPM = _COMMON + '''
case "$1" in test|test:fast) ;; *) exit 0;; esac
log "pnpm $*"
need_report() { [ -n "$VITEST_GATE_REPORT" ] || { echo "stub pnpm: VITEST_GATE_REPORT is not set" >&2; exit 97; }; }
json() {   # passed failed pending
  need_report
  total=$(($1 + $2 + $3))
  if [ "${STUB_VITEST_FORMAT:-pretty}" = compact ]; then
    printf '{"numTotalTestSuites":1,"numPassedTestSuites":1,"numFailedTestSuites":0,"numTotalTests":%s,"numPassedTests":%s,"numFailedTests":%s,"numPendingTests":%s,"numTodoTests":0,"success":true,"testResults":[]}\\n' "$total" "$1" "$2" "$3" > "$VITEST_GATE_REPORT"
  else
    printf '{\\n  "numTotalTestSuites": 1,\\n  "numPassedTestSuites": 1,\\n  "numFailedTestSuites": 0,\\n  "numPendingTestSuites": 0,\\n  "numTotalTests": %s,\\n  "numPassedTests": %s,\\n  "numFailedTests": %s,\\n  "numPendingTests": %s,\\n  "numTodoTests": 0,\\n  "success": true,\\n  "testResults": []\\n}\\n' "$total" "$1" "$2" "$3" > "$VITEST_GATE_REPORT"
  fi
}
case "${STUB_VITEST:-nofiles}" in
  nofiles) echo "No test files found, exiting with code 1"; exit 1;;
  zero)    json 0 0 0; echo "no tests"; exit 0;;
  skipped) json 0 0 3; echo "3 skipped"; exit 0;;
  pass)    json 2 0 0; echo "2 passed"; exit 0;;
  fail)    json 1 1 0; echo "1 failed | 1 passed"; exit "${STUB_FAIL_EXIT:-1}";;
  broken)  echo "error: cannot load config" >&2; exit "${STUB_BROKEN_EXIT:-1}";;
esac
'''

KUSTOMIZE = _COMMON + '''
[ "$1" = build ] || exit 0
log "kustomize $*"
[ -n "$STUB_KUSTOMIZE" ] && printf '%s\\n' "$STUB_KUSTOMIZE"
exit 0
'''

KUBECONFORM = _COMMON + '''
log "kubeconform $*"
echo "${STUB_KUBECONFORM:-Summary: 0 resources found in 1 file - Valid: 0, Invalid: 0, Errors: 0, Skipped: 0}"
exit "${STUB_KUBECONFORM_EXIT:-0}"
'''

DETECT = _COMMON + '''
log "detect-secrets-hook $*"
exit 0
'''

KYVERNO = _COMMON + '''
exit 0
'''

DEVBOX = _COMMON + '''
PY="@PY@"
[ "$1" = run ] || { echo "stub devbox: only 'run' is supported" >&2; exit 64; }
name=$2
case "$name" in
  test|test-fast|validate|render-check|secrets-scan|ci|quality|security) ;;
  *) log "devbox run $name (stub: passes)"; exit 0;;
esac
recipe=$("$PY" -c 'import json,sys; print(json.load(open("devbox.json"))["shell"]["scripts"][sys.argv[1]])' "$name") || exit 65
log "devbox run $name"
exec sh -c "$recipe"
'''

STUBS = {"uv": UV, "go": GO, "mvn": MVN, "pnpm": PNPM, "kustomize": KUSTOMIZE, "kubeconform": KUBECONFORM,
         "detect-secrets-hook": DETECT, "kyverno": KYVERNO, "devbox": DEVBOX}


def make_stubs(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for name, text in STUBS.items():
        f = dest / name
        f.write_text(text.replace("@PY@", sys.executable))
        f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (dest / "render_empty.py").write_text(RENDER_EMPTY)
    return dest


def clean_env(stubs: Path, extra: dict | None = None, **more: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("STUB_", "GATE_", "VITEST_")) and k not in ("SMOKE_BASE_URL",)}
    env["PATH"] = f"{stubs}{os.pathsep}{os.environ['PATH']}"
    env.update(extra or {})
    env.update(more)
    return env


def run_sh(recipe: str, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    """`devbox run <recipe>`: the recipe text under sh -c in the repo."""
    return subprocess.run(["sh", "-c", recipe], cwd=cwd, env=env, capture_output=True, text=True, timeout=180)


def recipes(repo: Path) -> dict:
    return json.loads((repo / "devbox.json").read_text())["shell"]["scripts"]


def recipe_of(repo: Path, name: str) -> str:
    return recipes(repo)[name]


def stderr_lines(proc: subprocess.CompletedProcess) -> list[str]:
    return proc.stderr.splitlines()


def nothing_lines(proc: subprocess.CompletedProcess) -> list[str]:
    return [ln for ln in stderr_lines(proc) if re.search(r": checked nothing: ", ln)]


# ---------------- rendering ----------------

def copier_data(template: str) -> dict:
    data = {"project_name": "demo-app", "github_org": "acme", "description": "check"}
    if template in ("service-python", "library-python"):
        data["module_name"] = "demo_app"
    if template == "gitops-app":
        data["app_name"] = "demo"
    return data


def render_template(template: str, dest: Path) -> Path:
    import core
    cmd = [*core.find_copier(), "copy", str(TEMPLATES / template), str(dest), "--defaults", "--trust", "--skip-tasks"]
    for k, v in copier_data(template).items():
        cmd += ["--data", f"{k}={v}"]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return dest


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True)


def rendered_repo(shared_renders, template: str, dest: Path, track: str | bool = True) -> Path:
    """A private copy of the template rendered with default answers (once per process), as a git repo.
    track=True stages everything (a normal repo), False leaves the index empty, a string stages only that file (created if missing)."""
    repo = shared_renders.copy(f"130 {template}", lambda workdir: render_template(template, workdir / "demo-app"), dest)
    git(repo, "init", "-q")
    if track is True:
        git(repo, "add", "-A")
    elif track:
        f = repo / track
        if not f.exists():
            f.write_text("")
        git(repo, "add", "--", track)
    return repo
