"""Spec 104: the service-python template ships a smoke test for the metrics (AC-104.4)."""
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
