"""FastAPI entry point for {{ project_name }}."""

from __future__ import annotations

{% if needs_observability %}import os

{% endif %}from fastapi import FastAPI
{%- if needs_observability %}
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
{%- endif %}
from pydantic import BaseModel
{%- if needs_observability %}

from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()
{%- endif %}

app = FastAPI(title="{{ project_name }}", version="0.1.0")
{%- if needs_observability %}
app.add_middleware(MetricsMiddleware)
{%- endif %}


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — returns 200 as long as the process is responding."""
    return HealthResponse(status="ok")


@app.get("/ready", response_model=HealthResponse)
def ready() -> HealthResponse:
    """Readiness probe — returns 200 when the service is ready to accept traffic."""
    return HealthResponse(status="ready")


@app.get("/ping")
def ping() -> dict[str, str]:
    """Simple ping endpoint."""
    return {"pong": "{{ project_name }}"}
{%- if needs_observability %}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
{%- endif %}
