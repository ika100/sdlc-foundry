"""Spec 182 acceptance tests, the cluster test (AC-182.5; the in-cluster side of AC-182.1 to AC-182.3).

tests/e2e/run.sh needs a cluster, so test-fast checks what the script does by reading it: dev gets `ui: lgtm`, it queries Loki for the
component's line within 120 s, names the missing piece when it fails, and checks the collector's permissions with `kubectl auth can-i`.
Contract: docs/specs/182-logs-reach-loki/design.md "Cluster test". A test names its criterion in a `# AC-182.n` comment."""
import re
from pathlib import Path

import pytest

RUN = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "run.sh"


@pytest.fixture(scope="module")
def run_sh():
    return RUN.read_text()


def test_dev_runs_with_the_lgtm_log_backend_ac_182_5(run_sh):  # AC-182.5
    assert re.search(r'envs\["dev"\]\["observability"\]\s*=\s*\{\s*["\']ui["\']\s*:\s*["\']lgtm["\']\s*\}', run_sh)


def test_the_script_asks_loki_for_the_components_line_by_service_and_namespace_ac_182_5(run_sh):  # AC-182.5
    assert "query_range" in run_sh
    assert "service_name" in run_sh and "k8s_namespace_name" in run_sh
    assert "e2e-api" in run_sh and "info requested" in run_sh
    assert "traceparent" in run_sh, "the request carries a trace id the log line must reach (AC-182.2)"


def test_the_script_waits_at_most_120_seconds_for_the_line_ac_182_5(run_sh):  # AC-182.5
    assert "query_range" in run_sh and "within 120 s" in run_sh
    at = run_sh.index("query_range")
    assert re.search(r"\b120\b", run_sh[max(0, at - 2500):at + 2500])


@pytest.mark.parametrize("pattern", [r"no stream for service_name=e2e-api", r"no line .*within 120 s"])
def test_the_failure_messages_name_the_missing_label_or_line_ac_182_5(run_sh, pattern):  # AC-182.5
    fails = [line for line in run_sh.splitlines() if "fail" in line and re.search(pattern, line)]
    assert fails, f"no fail call matches {pattern!r}"


def test_the_script_checks_pod_and_environment_labels_and_the_trace_id_in_loki_ac_182_1(run_sh):  # AC-182.1
    assert "k8s_pod_name" in run_sh and "deployment_environment" in run_sh
    assert "trace_id" in run_sh
    assert "/api/traces/" in run_sh, "Tempo returns the trace of the request (AC-182.2)"


def test_the_script_checks_the_grafana_link_between_trace_and_logs_ac_182_2(run_sh):  # AC-182.2
    # Grafana links a log entry to its trace and the trace to "logs for this span" through the provisioned Tempo/Loki data sources
    assert "/api/datasources" in run_sh, "the script reads the Grafana data sources"
    assert "tracesToLogsV2" in run_sh, "the Tempo data source links its spans to Loki (logs for this span)"
    assert "derivedFields" in run_sh and "trace_id" in run_sh[run_sh.index("derivedFields"):], (
        "the Loki data source links a log entry's trace_id to Tempo")


def test_the_collectors_own_lines_never_reach_loki_ac_182_4(run_sh):  # AC-182.4
    assert 'service_name="otel-collector"' in run_sh.replace("\\\"", '"').replace("'", "")


def test_the_script_proves_the_collectors_permission_is_limited_to_its_namespace_ac_182_3(run_sh):  # AC-182.3
    assert "auth can-i" in run_sh and "get pods/log" in run_sh
    assert "system:serviceaccount:e2e-dev:otel-collector" in run_sh
    for ns in ("e2e-staging", "kube-system"):
        assert ns in run_sh[run_sh.index("auth can-i"):]
    assert "DaemonSet" in run_sh or "daemonset" in run_sh, "no node-level collector (AC-182.3)"
