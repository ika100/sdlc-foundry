"""Spec 104: the service-python template ships a smoke test for the metrics (AC-104.4)."""
import importlib.util
import itertools
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "service-python"


def test_template_smoke_test_reads_metrics_from_a_running_service():
    """AC-104.4 (smoke): the rendered smoke test calls /health and an unknown path, then reads /metrics."""
    text = (TEMPLATE / "tests" / "test_smoke_metrics.py").read_text()
    assert "@pytest.mark.smoke" in text and "AC-104.4" in text
    assert "smoke_base_url" in text and '"/metrics"' in text and 'route="unmatched"' in text


def test_smoke_metrics_test_is_left_out_without_observability():
    """AC-104.4 (smoke): without observability there is no /metrics, so the smoke test is excluded."""
    assert "tests/test_smoke_metrics.py" in (TEMPLATE / "copier.yml").read_text()


def test_template_metrics_tests_cover_the_route_error_and_scrape_criteria():
    """AC-104.5, AC-104.6, AC-104.7: the template's own tests (run in its CI job) name and cover them."""
    text = (TEMPLATE / "tests" / "test_metrics.py").read_text()
    for ac in ("AC-104.4", "AC-104.5", "AC-104.6", "AC-104.7"):
        assert ac in text


def test_smoke_metrics_test_passes_behind_two_instances():
    """#520: each instance counts only its own requests; round-robin across two must still pass."""
    counts = [{}, {}]
    turn = itertools.cycle([0, 1])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            mine = counts[next(turn)]
            if self.path == "/metrics":
                body = "".join(f'http_requests_total{{method="GET",route="{r}",status_code="{c}"}} {n}\n'
                               for (r, c), n in mine.items()).encode()
                self.send_response(200)
            else:
                route, code = ("/health", 200) if self.path == "/health" else ("unmatched", 404)
                mine[(route, code)] = mine.get((route, code), 0) + 1
                body = b""
                self.send_response(code)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        spec_ = importlib.util.spec_from_file_location("smoke_metrics", TEMPLATE / "tests" / "test_smoke_metrics.py")
        mod = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(mod)
        mod.test_requests_are_counted_in_metrics(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
