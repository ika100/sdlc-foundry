# {{ project_name }}

{{ description }}

Owned by {{ owner_team }}.

## Quick start

```bash
devbox shell                  # enter the dev environment
devbox run quality            # ruff + mypy
devbox run test               # pytest with coverage
devbox run -- uv run uvicorn {{ module_name }}.main:app --reload --port {{ port }}
```

Then `curl http://localhost:{{ port }}/ping`.

## Conventions

- Config from environment variables only
- `/health` (liveness) and `/ready` (readiness) on every HTTP service
- Structured JSON logging
- `devbox run <script>` is the only sanctioned entry point for tooling

See `CLAUDE.md` for the full agent workflow and `devbox.json` for the canonical recipes.

## Deploy

| Target | Command |
|---|---|
| Staging / prod | Open a PR in the platform gitops repo or `/instance:promote {{ project_name }} --to <env>` |

Image: `{{ docker_registry }}/{{ project_name }}` — built and tagged automatically by CI.
