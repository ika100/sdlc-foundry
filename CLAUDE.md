# CLAUDE.md

This file is for Claude Code working inside the `ika100/sdlc-foundry` repo itself.

## Purpose

This repo is **the source of truth** for Claude Code agents, slash commands, and Copier templates used by every repository generated from it. Changes here propagate to many downstream repos — be careful.

## Layout

| Path | What it is |
|---|---|
| `.claude-plugin/marketplace.json` | Marketplace catalog. Bump plugin versions here when a plugin changes. |
| `plugins/<name>/.claude-plugin/plugin.json` | Per-plugin manifest. Mirror the version in the marketplace catalog. |
| `plugins/<name>/agents/*.md` | Subagent definitions (YAML frontmatter + system prompt). |
| `plugins/<name>/commands/*.md` | Slash commands (description frontmatter + body using `$ARGUMENTS`). Commands stay thin: they run `cplat <command>` (the launcher in `plugins/shared/bin/`, which runs `scripts/cplat`) and relay its output. |
| `plugins/<name>/hooks/hooks.json` | Plugin-scoped hooks (e.g. the SessionStart hook that checks devbox and runs `devbox install`). |
| `plugins/<name>/settings.json` | Plugin-scoped permission allowlists. |
| `shapes.yml` | The shape registry: one entry per template/plugin pair, validated by `scripts/shapes.py check`. The `platform` entry has no template: this repo declares `shape: platform` in the committed `.platform-settings.yml` (ADR-056). |
| `templates/<shape>/` | Copier templates: `service-python`, `library-python`, `service-java`, `service-go`, `web-nextjs`, `gitops-app`. Only `*.jinja` files are rendered in the newer templates (see each `copier.yml`). |
| `scripts/cplat/` | The tested CLI behind the commands (`system`, `component`, `api`, `resource`, `instance`, `issue`, `platform`, `feedback`). |
| `scripts/*.py`, `scripts/ci-local.sh` | Repository checks: shape registry, pinned Actions, Markdown links, local CI. |
| `tests/cplat/`, `tests/e2e/` | pytest suite for the CLI and renderer; the full-stack cluster test. |
| `devbox.json` | Repo-root devbox env + smoke-test scripts (`validate`, `smoke-*`, `ci-local`). |
| `docs/specs/` | The platform's own feature specs (ADR-026), indexed by the generated table in `docs/backlog.md`. |
| `docs/` | Guides, `docs/adr/` (decisions, indexed in its README), `docs/CHANGELOG.md`, `docs/AGENTS.md` (orchestration model: read before changing agents or commands). |

## Conventions

- **Don't break the marketplace schema.** `marketplace.json` is consumed by every project that pins this repo. Validate locally before pushing — see `.github/workflows/ci.yml`.
- **Bump versions in both places.** When a plugin changes, update both `marketplace.json` and `plugins/<name>/.claude-plugin/plugin.json`. Use semver — major bump only for breaking changes consumers must react to (renamed commands, removed agents).
- **Template Jinja gotcha.** GitHub Actions uses `${{ var }}` syntax, which Copier (Jinja) would otherwise interpret. The escape pattern is `${{ '{{' }} var {{ '}}' }}` — already applied in the existing CI workflows. Don't unescape it.
- **Don't put project-specific content in plugin agents.** Agents are shared across repos. Anything project-specific belongs in the Copier template (which gets parameterised per-repo) or in the consumer's own `CLAUDE.md`.
- **Platform changes start with a spec.** Run `/component:spec <description>` here (the repo declares `shape: platform`, so spec, plan, build, verify and ship work as in a component repo; releases follow CONTRIBUTING.md, Releases), write an ADR for decisions that outlive the change, and keep `cplat spec check` green.
- **Wait for CI with `cplat pr wait <pr> [-R owner/repo] [--merge]`** (spec 079), never a hand-written polling loop: it reports each check, stops at the first red one and reruns stuck or transient runs once.
- **No backwards-compat hacks for old marketplace ref.** When breaking, ship a new major version and document the migration in `docs/CHANGELOG.md`.

## Common changes

### Add an agent

1. Decide which plugin (`component` / `system` / `platform` / `svc` / `shared`; the `app` and `gitops` plugins hold only tombstones).
2. Write `plugins/<plugin>/agents/<name>.md` with YAML frontmatter (`name`, `description`, `tools`, `model`).
3. Update the plugin's README.
4. Bump `plugins/<plugin>/.claude-plugin/plugin.json` version (minor for additions, patch for fixes).
5. Bump the matching entry in `.claude-plugin/marketplace.json`.

### Add a slash command

1. Write `plugins/<plugin>/commands/<name>.md` with `description:` frontmatter and `$ARGUMENTS` in the body.
2. The command will be available as `/<plugin>:<name>` in consumer repos after version bump + `/plugin marketplace update`.

### Change a Copier template

1. Edit files under `templates/<template>/`.
2. Test locally: `copier copy ./templates/service-python /tmp/test --defaults --data project_name=test-svc --data module_name=test_svc`.
3. Add to `_skip_if_exists` in `copier.yml` if the file should NOT be overwritten by `/platform:update` (project-owned files).
4. Tag a release in the platform repo.
5. Downstream repos run `/platform:update` to pull the change.

## Smoke test before pushing

This repo itself ships a `devbox.json` so the smoke-test runs through the same `devbox run <script>` entry point used everywhere else.

```bash
devbox install          # one-time: pulls jq, uv, python, gh, copier
devbox run validate     # jq-checks marketplace.json + every plugin.json + every hook.json
devbox run smoke-service  # copier copy → devbox install → devbox run quality
devbox run smoke-library  # same, for the library template
devbox run smoke        # all of the above
devbox run test-fast    # cplat tests; also `quality` (static checks), `ci` (= ci-local.sh), `lint-fix` (no-op) for /component:ship and /component:build
```

(`devbox` must be available on the host — everything else is provided by `devbox install`. Host install: `curl -fsSL https://get.jetify.com/devbox/install.sh | bash`.)
