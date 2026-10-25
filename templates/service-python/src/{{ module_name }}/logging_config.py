{%- if not needs_observability -%}
# Observability scaffolding was disabled at template time. Run `/shared:update-service`
# with --data needs_observability=true to enable structlog, metrics and OTel.
{%- else -%}
"""Structured JSON logging via structlog."""

from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structured JSON logging for the application."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
{%- endif %}
