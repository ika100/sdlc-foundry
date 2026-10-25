# syntax=docker/dockerfile:1.7

FROM python:{{ python_version }}-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY README.md ./
RUN uv sync --locked --no-dev


FROM python:{{ python_version }}-slim AS runtime
# Links the GHCR package to this repository, so CI's GITHUB_TOKEN can push to it (no manual "Manage Actions access" step).
LABEL org.opencontainers.image.source="https://github.com/{{ github_org }}/{{ project_name }}" \
      org.opencontainers.image.description="{{ description | replace('"', '') | replace('\\', '') }}"

# Fixed numeric IDs: Kubernetes cannot verify runAsNonRoot for a named user.
RUN groupadd -r -g 10001 app && useradd -r -u 10001 -g app -d /app -s /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT={{ port }}

USER 10001:10001

EXPOSE {{ port }}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; urllib.request.urlopen('http://localhost:{{ port }}/health', timeout=3); sys.exit(0)" || exit 1

CMD ["uvicorn", "{{ module_name }}.main:app", "--host", "0.0.0.0", "--port", "{{ port }}"]
