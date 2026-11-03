"""#323: sturdier e2e probes. scripts/check-e2e-probes.py rejects "$$" in strings the e2e scripts send as a pod command, and
tests/e2e/lib/probe.sh (probe_run) builds the probe pods of run.sh and upgrade.sh: it copies Secret references and plain values and
resolves prefixed names. probe_run runs here against a fake kubectl (a shell function) that records the Pod it is given."""
import json
import shutil
import subprocess
import sys

import pytest

from system_fixtures import ROOT

LINT = ROOT / "scripts" / "check-e2e-probes.py"
LIB = ROOT / "tests" / "e2e" / "lib" / "probe.sh"


def lint(*files):
    return subprocess.run([sys.executable, str(LINT), *map(str, files)], capture_output=True, text=True, timeout=60)


def test_the_e2e_scripts_send_no_double_dollar_to_a_pod_323():
    """#323: the repository's e2e scripts pass the lint."""
    p = lint()
    assert p.returncode == 0, p.stdout + p.stderr


@pytest.mark.parametrize("line, kind", [
    ("crun 'v=FOO; echo \"${!v}\" $$'", "single-quoted"),
    ("crun \"echo \\$\\$\"", "escaped dollars"),
    ("z=$'a$$b'", "single-quoted"),
], ids=["single", "escaped", "ansi-c"])
def test_the_lint_rejects_a_literal_double_dollar_323(tmp_path, line, kind):
    """#323: a "$$" the local shell does not expand is a finding, with file and line."""
    f = tmp_path / "bad.sh"
    f.write_text(f"#!/usr/bin/env bash\necho ok\n{line}\n")
    p = lint(f)
    assert p.returncode == 1 and f"bad.sh:3:" in p.stdout and kind in p.stdout, p.stdout


def test_the_lint_rejects_a_double_dollar_in_a_quoted_heredoc_323(tmp_path):
    """#323: the body of <<'PY' is literal, so its "$$" would reach the pod."""
    f = tmp_path / "bad.sh"
    f.write_text("x=$(cat <<'PY'\nprint('$$')\nPY\n)\n")
    p = lint(f)
    assert p.returncode == 1 and "bad.sh:2:" in p.stdout and "quoted heredoc" in p.stdout, p.stdout


def test_the_lint_allows_the_local_pid_comments_and_here_strings_323(tmp_path):
    """#323: an unquoted or double-quoted "$$" is the local PID; comments, here-strings and unquoted heredocs are not commands."""
    f = tmp_path / "ok.sh"
    f.write_text("# no '$$' here\nkill -0 $$\necho \"pid $$ $(kc get x -o jsonpath='{.a}') it's\"\n"
                 "grep -q x <<< \"$out\"\ncat <<EOF\n$$\nEOF\ny='plain'\n")
    p = lint(f)
    assert p.returncode == 0, p.stdout


FAKE = r"""
set -euo pipefail
. "$LIB"
fail() { echo "FAIL: $*"; exit 3; }
kc() {
  case "$1 $2" in
    "get deployments.apps") cat "$DEP";;
    "apply -f") cat > "$OUT/pod-$(ls "$OUT" | wc -l | tr -d ' ').json";;
    "get pods/"*) echo "$PHASE";;
    "logs pods/"*) echo "hello from the probe";;
    *) :;;
  esac
}
"""


def probe(tmp_path, args, phase="Succeeded"):
    if not shutil.which("bash"):
        pytest.skip("bash is required")
    dep = {"spec": {"template": {"spec": {"containers": [{"env": [
        {"name": "S3_BUCKET", "valueFrom": {"secretKeyRef": {"name": "a", "key": "bucket"}}},
        {"name": "FILES_S3_BUCKET", "valueFrom": {"secretKeyRef": {"name": "f", "key": "bucket"}}},
        {"name": "FILES_S3_REGION", "value": "us-east-1"},
        {"name": "EVENTS_ORDERS_SUBJECT_PREFIX", "value": "e2e.orders"},
        {"name": "OTHER", "value": "x"}]}]}}}}
    (tmp_path / "dep.json").write_text(json.dumps(dep))
    out = tmp_path / "out"
    out.mkdir()
    script = FAKE + f"probe_run {args} && echo \"RC=0 OUT=$PROBE_OUT\" || echo \"RC=$? OUT=$PROBE_OUT\"\n"
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "LIB": str(LIB), "DEP": str(tmp_path / "dep.json"), "OUT": str(out), "PHASE": phase}
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60)
    pods = [json.loads(f.read_text()) for f in sorted(out.iterdir())]
    return p, pods


def test_probe_run_copies_secret_refs_and_plain_values_and_resolves_the_prefix_323(tmp_path):
    """#323: Secret references and plain values are copied; with -p FILES_ the prefixed names win over the bare ones."""
    p, pods = probe(tmp_path, "-k kc -d api -i img -m '(FILES_)?(S3|AWS|EVENTS)_' -p FILES_ -w 2:0 -e HOME=/tmp 'echo \"$S3_BUCKET\"'")
    assert "RC=0 OUT=hello from the probe" in p.stdout, p.stdout + p.stderr
    c = pods[0]["spec"]["containers"][0]
    env = {e["name"]: e for e in c["env"]}
    assert set(env) == {"S3_BUCKET", "S3_REGION", "EVENTS_ORDERS_SUBJECT_PREFIX", "HOME"}
    assert env["S3_BUCKET"]["valueFrom"]["secretKeyRef"]["name"] == "f"
    assert env["S3_REGION"]["value"] == "us-east-1" and env["EVENTS_ORDERS_SUBJECT_PREFIX"]["value"] == "e2e.orders"
    assert c["command"] == ["sh", "-c", 'echo "$S3_BUCKET"']
    assert "securityContext" not in pods[0]["spec"]


def test_probe_run_restricted_python_pod_from_an_env_file_323(tmp_path):
    """#323: -f, -c python and -u give the nats probe of run.sh: a non-root, restricted pod running python -c."""
    (tmp_path / "env.json").write_text(json.dumps([{"name": "NATS_URL", "value": "nats://bus:4222"}]))
    p, pods = probe(tmp_path, f"-k kc -f {tmp_path / 'env.json'} -i img -c python -u 1000 -l natsprobe -w 2:0 'print(1)'")
    assert "RC=0" in p.stdout, p.stdout + p.stderr
    pod = pods[0]
    assert pod["metadata"]["labels"] == {"app": "natsprobe"} and pod["metadata"]["name"].startswith("natsprobe-")
    assert pod["spec"]["securityContext"]["runAsUser"] == 1000 and pod["spec"]["containers"][0]["command"] == ["python", "-c", "print(1)"]
    assert pod["spec"]["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True


def test_probe_run_reports_a_failed_pod_with_its_phase_323(tmp_path):
    """#323: a pod that does not succeed returns non-zero and names its phase in PROBE_OUT."""
    p, _ = probe(tmp_path, "-k kc -d api -i img -w 2:0 'exit 1'", phase="Failed")
    assert "RC=1 OUT=hello from the probe (pod phase: Failed;" in p.stdout, p.stdout + p.stderr
