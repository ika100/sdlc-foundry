# ADR-000: Bootstrap

## Status

Accepted on bootstrap.

## Context

`{{ project_name }}` was created from the `service-python` Copier template at `ika100/sdlc-foundry`. The template encodes a set of conventions every service in the fleet shares:

- Python {{ python_version }} via devbox
- FastAPI for HTTP
- pytest with ≥80% coverage gate
- ruff + mypy for quality
- pip-audit + detect-secrets + bandit + trivy for security
- Multi-stage Docker build → `{{ docker_registry }}/{{ project_name }}`
- No Kubernetes manifests here: the system's gitops-app repo owns them (platform ADR-017); this repo ships a container image
- GitHub topic `deployable-service` for ArgoCD auto-discovery
- Claude Code agents from the `sdlc-foundry` marketplace (`svc` + `shared`)
{%- if needs_observability %}
- structlog + Prometheus + OTel for observability
{%- endif %}
{%- if needs_migrations %}
- Alembic for database migrations
{%- endif %}

## Decision

We adopt the platform conventions verbatim. Any deviation must be justified in a new ADR.

The platform marketplace is pinned to `{{ platform_marketplace_ref }}` in `.claude/settings.json` — bump that ref to pull updated agents/commands. Skeleton updates (CI workflow, devbox recipes) come via `copier update`.

## Consequences

**Positive:** zero per-service plumbing decisions; consistent quality bar; agents work identically across the fleet; new contributors learn one shape and apply it everywhere.

**Negative:** drift requires deliberate work — if `{{ project_name }}` needs a tool that's not in the template, the right answer is to upstream it to the template, not work around it locally.
