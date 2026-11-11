"""Spec 182 acceptance tests, AC-182.6: with observability on, every JSON log line a generated component writes inside an active span
carries `trace_id` (32 hex) and `span_id` (16 hex) equal to the span's ids, and a line outside any span carries neither.

copier is not part of the platform's test-fast environment, so the template files are read raw (Jinja markup included) or rendered with
jinja2 with the answers `needs_observability=true`; the Python template's logging also runs against an in-memory OpenTelemetry span.
Contract: docs/specs/182-logs-reach-loki/design.md "Component log lines". A test names its criterion in a `# AC-182.6` comment."""
import json
import re
import types
from pathlib import Path

import pytest
import yaml

T = Path(__file__).resolve().parents[2] / "templates"
PY = T / "service-python" / "src" / "{{ module_name }}"
GO = T / "service-go" / "internal" / "server"
JAVA = T / "service-java" / "src" / "main"


def text(path: Path) -> str:
    assert path.is_file(), f"missing template file: {path.relative_to(T)}"
    return path.read_text()


def first(*paths: Path) -> str:
    for p in paths:
        if p.is_file():
            return p.read_text()
    raise AssertionError("missing template file: " + " or ".join(str(p.relative_to(T)) for p in paths))


def jinja(source: str) -> str:
    """The template with the Jinja markup removed (jinja2 is not in the test environment): every `{% %}` tag goes, every `{{ }}`
    becomes `x`; the `needs_observability` else branch of logging_config.py (the 'disabled' stub) is cut first."""
    if "{%- else -%}" in source:
        source = source.split("{%- else -%}", 1)[1]
    source = re.sub(r"\{%.*?%\}", "", source, flags=re.S)
    return re.sub(r"\{\{.*?\}\}", "x", source, flags=re.S)


# ---------------- service-python ----------------

def test_python_logging_has_an_add_trace_ids_processor_before_the_json_renderer_ac_182_6():  # AC-182.6
    src = text(PY / "logging_config.py")
    assert "def add_trace_ids" in src
    body = src[src.index("processors=["):]
    assert "add_trace_ids" in body and body.index("add_trace_ids") < body.index("JSONRenderer")
    assert "trace_id" in src and "span_id" in src and "is_valid" in src


def test_python_main_instruments_fastapi_when_tracing_is_enabled_ac_182_6():  # AC-182.6
    src = text(PY / "main.py")
    assert "FastAPIInstrumentor" in src and "instrument_app(app)" in src
    guarded = src[src.index("tracing_enabled()"):]
    assert "instrument_app" in guarded


def python_logging():
    pytest.importorskip("structlog")
    pytest.importorskip("opentelemetry.sdk.trace")
    module = types.ModuleType("logging_config_182")
    exec(compile(jinja(text(PY / "logging_config.py")), "logging_config.py", "exec"), module.__dict__)
    return module


def lines(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def test_python_log_lines_inside_a_span_carry_the_span_ids_ac_182_6(capsys):  # AC-182.6
    module = python_logging()
    from opentelemetry.sdk.trace import TracerProvider
    import structlog
    module.configure_logging("INFO")
    tracer = TracerProvider().get_tracer("t182")
    with tracer.start_as_current_span("handling") as span:
        structlog.get_logger().info("inside")
        ctx = span.get_span_context()
    (line,) = lines(capsys)
    assert line["trace_id"] == format(ctx.trace_id, "032x") and re.fullmatch(r"[0-9a-f]{32}", line["trace_id"])
    assert line["span_id"] == format(ctx.span_id, "016x") and re.fullmatch(r"[0-9a-f]{16}", line["span_id"])
    assert line["level"] == "info" and line["event"] == "inside"


def test_python_log_lines_outside_a_span_carry_neither_id_ac_182_6(capsys):  # AC-182.6
    module = python_logging()
    import structlog
    module.configure_logging("INFO")
    structlog.get_logger().info("outside")
    (line,) = lines(capsys)
    assert "trace_id" not in line and "span_id" not in line and line["level"] == "info"


# ---------------- service-go ----------------

def go_trace() -> str:
    return first(GO / "tracelog.go", GO / "tracelog.go.jinja")


def test_go_has_the_trace_context_middleware_and_the_slog_handler_wrapper_ac_182_6():  # AC-182.6
    src = go_trace()
    assert "func TraceContext(next http.Handler) http.Handler" in src
    assert "func NewTraceHandler(h slog.Handler) slog.Handler" in src
    assert "func TraceIDs(ctx context.Context) (traceID, spanID string, ok bool)" in src
    assert "traceparent" in src and '"trace_id"' in src and '"span_id"' in src
    assert "slog.Handler" in src and "Handle(ctx context.Context" in src


def test_go_validates_the_traceparent_header_ac_182_6():  # AC-182.6
    src = go_trace()
    assert re.search(r"\[0-9a-f\]\{32\}", src) and re.search(r"\[0-9a-f\]\{16\}", src), "32 and 16 hex characters are checked"
    assert '"00"' in src or "00-" in src, "version 00"


def test_go_request_logger_logs_with_the_request_context_and_main_wraps_the_handler_ac_182_6():  # AC-182.6
    server = first(GO / "server.go.jinja", GO / "server.go")
    assert "TraceContext" in server and "InfoContext(" in server and "req.Context()" in server.replace("r.Context()", "req.Context()")
    main = first(T / "service-go" / "cmd" / "{{ project_name }}" / "main.go.jinja")
    assert "server.NewTraceHandler(" in main and "NewJSONHandler" in main


# ---------------- service-java ----------------

def test_java_logs_json_with_the_logstash_format_ac_182_6():  # AC-182.6
    conf = yaml.safe_load(jinja(text(JAVA / "resources" / "application.yml.jinja")))
    assert conf["logging"]["structured"]["format"]["console"] == "logstash"
    assert conf["logging"]["level"]["root"] == "${LOG_LEVEL:INFO}", "the level setting stays"


def test_java_info_endpoint_logs_one_line_per_request_ac_182_6():  # AC-182.6
    src = jinja(text(JAVA / "java" / "{{ package_path }}" / "InfoController.java.jinja"))
    assert '"info requested"' in src
    assert re.search(r"\.info\(\s*\"info requested\"", src)
    assert re.search(r"(Logger|LoggerFactory)", src)


# ---------------- web-nextjs ----------------

def test_nextjs_logger_exports_levels_and_reads_the_active_span_ac_182_6():  # AC-182.6
    src = text(T / "web-nextjs" / "lib" / "logger.ts")
    assert "export const logger" in src
    for level in ("debug", "info", "warn", "error"):
        assert re.search(rf"\b{level}\b", src)
    assert "@opentelemetry/api" in src and "getActiveSpan" in src and "isSpanContextValid" in src
    assert "trace_id" in src and "span_id" in src and "JSON.stringify" in src
    assert re.search(r"\blevel\b", src) and "time" in src and "msg" in src


# ---------------- wiring of the three templates whose code does not run in test-fast ----------------
# `go`, a JVM and node are not part of the platform's test environment, so the generated component's own behaviour tests (which run
# in its CI) must exist and pin both ids and their absence; the wiring is checked here: the right id into the right field, not swapped.

def test_go_wires_trace_id_from_the_32_hex_group_and_span_id_from_the_16_hex_group_ac_182_6():  # AC-182.6
    src = go_trace()
    assert re.search(r"\(\[0-9a-f\]\{32\}\)-\(\[0-9a-f\]\{16\}\)", src), "traceparent: version-(32 hex trace id)-(16 hex span id)"
    assert re.search(r"traceID,\s*spanID\s*=\s*m\[1\],\s*m\[2\]", src), "m[1] is the trace id, m[2] the span id"
    assert re.search(r'slog\.String\("trace_id",\s*t\),\s*slog\.String\("span_id",\s*s\)', src), "trace_id gets t, span_id gets s"
    assert re.search(r"if t, s, ok := TraceIDs\(ctx\); ok", src), "both ids are added only when the context carries them"
    assert re.search(r"traceIDs\{t, s\}", src) and re.search(r"parseTraceparent\(req\.Header\.Get\(\"traceparent\"\)\)", src)
    assert re.search(r"return v\.traceID, v\.spanID, true", src), "TraceIDs returns (trace, span) in that order"


def test_go_own_behaviour_test_pins_both_ids_and_their_absence_ac_182_6():  # AC-182.6
    src = text(GO / "tracelog_test.go")
    assert '"4bf92f3577b34da6a3ce929d0e0e4736"' in src and '"00f067aa0ba902b7"' in src, "known ids in a traceparent"
    assert re.search(r'm\["trace_id"\]\s*!=\s*"4bf92f3577b34da6a3ce929d0e0e4736"', src), "trace_id is compared with the trace id"
    assert re.search(r'm\["span_id"\]\s*!=\s*"00f067aa0ba902b7"', src), "span_id is compared with the span id"
    assert "TestNoOrInvalidTraceparentLogsNothing" in src
    assert '_, ok := m["trace_id"]' in src and '_, ok := m["span_id"]' in src, "a line outside a span carries neither"


def test_java_own_behaviour_test_pins_both_ids_and_their_absence_ac_182_6():  # AC-182.6
    src = text(JAVA.parent / "test" / "java" / "{{ package_path }}" / "LogFormatTest.java.jinja")
    assert re.search(r'TRACE_ID\s*=\s*"[0-9a-f]{32}"', src) and re.search(r'SPAN_ID\s*=\s*"[0-9a-f]{16}"', src), "32 and 16 hex ids"
    assert 'MDC.put("trace_id", TRACE_ID)' in src and 'MDC.put("span_id", SPAN_ID)' in src, "the agent's MDC keys, not swapped"
    assert '"\\"trace_id\\":\\"" + TRACE_ID + "\\""' in src and '"\\"span_id\\":\\"" + SPAN_ID + "\\""' in src
    assert re.search(r'doesNotContain\("trace_id"\)\.doesNotContain\("span_id"\)', src), "outside a span carries neither"
    assert "OutputCaptureExtension" in src and "@SpringBootTest" in src, "the real logging configuration is exercised"


def test_java_agent_is_attached_with_observability_and_logs_through_the_json_encoder_ac_182_6():  # AC-182.6
    dockerfile = text(T / "service-java" / "Dockerfile.jinja")
    assert re.search(r'needs_observability %\}, "-javaagent:/otel/opentelemetry-javaagent\.jar"', dockerfile), "the agent fills the MDC"
    conf = yaml.safe_load(jinja(text(JAVA / "resources" / "application.yml.jinja")))
    assert conf["logging"]["structured"]["format"]["console"] == "logstash", "the MDC keys become top-level JSON fields"


def test_nextjs_wires_trace_id_to_the_span_trace_id_and_span_id_to_the_span_span_id_ac_182_6():  # AC-182.6
    src = text(T / "web-nextjs" / "lib" / "logger.ts")
    assert re.search(r"trace_id:\s*spanContext\.traceId\s*,\s*span_id:\s*spanContext\.spanId", src), "not swapped"
    assert re.search(r"spanContext\s*&&\s*isSpanContextValid\(spanContext\)\s*\?\s*\{[^}]*\}\s*:\s*\{\}", src), "no ids without a valid span"
    assert re.search(r"\.\.\.fields,\s*\.\.\.ids", src), "a caller's field cannot replace the span ids"


def test_nextjs_own_behaviour_test_pins_both_ids_and_their_absence_ac_182_6():  # AC-182.6
    src = text(T / "web-nextjs" / "tests" / "logger.test.ts")
    assert re.search(r'TRACE_ID\s*=\s*"[0-9a-f]{32}"', src) and re.search(r'SPAN_ID\s*=\s*"[0-9a-f]{16}"', src), "32 and 16 hex ids"
    assert "expect(line.trace_id).toBe(TRACE_ID)" in src and "expect(line.span_id).toBe(SPAN_ID)" in src
    assert 'expect(line).not.toHaveProperty("trace_id")' in src and 'expect(line).not.toHaveProperty("span_id")' in src
