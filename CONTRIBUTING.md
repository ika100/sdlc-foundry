# Contributing to sdlc-foundry

Thanks for helping. sdlc-foundry is a marketplace of Claude Code plugins (agents and slash commands), Copier templates and a small tested CLI (`cplat`) that together take a system from "new repo" to "running in Kubernetes via GitOps". Changes here reach every repo generated from it, so we favour small, tested, well-explained pull requests.

By contributing you agree that your contribution is licensed under the [Apache License 2.0](LICENSE) (inbound = outbound; no CLA) and that you have the right to submit it: sign your commits as described under [Sign your commits](#sign-your-commits-dco). Please read the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a problem or an idea.** In Claude Code run `/issue:report`: it drafts the issue with your versions and the error output and removes secrets before anything is sent. Or [open an issue](https://github.com/ika100/sdlc-foundry/issues/new/choose) yourself.
- **Ask a question or share a use case** in [Discussions](https://github.com/ika100/sdlc-foundry/discussions).
- **Fix a bug, improve docs, add a template, agent or command** with a pull request (below). For anything larger than a fix, open an issue first so we can agree on the approach.
- **Security issues** go through [SECURITY.md](SECURITY.md), not public issues.

## Repository map

| Path | What lives there |
|---|---|
| `plugins/<name>/` | Claude Code plugins: `agents/*.md`, `commands/*.md`, `.claude-plugin/plugin.json` |
| `.claude-plugin/marketplace.json` | Marketplace catalog; plugin versions must match each `plugin.json` |
| `templates/<shape>/` | Copier templates (`service-python`, `service-java`, `service-go`, `web-nextjs`, `library-python`, `gitops-app`) |
| `shapes.yml` | The shape registry (single source of truth, validated by `scripts/shapes.py`) |
| `scripts/cplat/` | The tested CLI behind the commands (`component`, `system`, `resource`, `instance`, `platform`, `feedback`, ...) |
| `tests/` | `tests/cplat` (pytest), `tests/e2e` (full cluster test), fixtures |
| `docs/` | Guides, ADRs (`docs/adr`), the changelog |

Read [CLAUDE.md](CLAUDE.md) (conventions and "how to add X" recipes), [docs/AGENTS.md](docs/AGENTS.md) (orchestration model) and [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) before changing agents, commands or templates.

## Development setup

You need `git`, [`uv`](https://docs.astral.sh/uv/) and `copier` (`uv tool install copier`). Docker, `kubectl` and `k3d` are only needed for the end-to-end test. [`devbox`](https://www.jetify.com/devbox) provides the same tools in one shell (`devbox shell`).

```bash
git clone https://github.com/ika100/sdlc-foundry && cd sdlc-foundry
```

## Checks to run before you open a PR

```bash
uv run scripts/shapes.py check                                              # registry, templates, plugins, descriptions
python3 scripts/pin-actions.py --check                                      # every GitHub Action pinned by SHA, workflows have permissions
python3 scripts/check-links.py                                               # relative Markdown links resolve
uvx --from "reuse[charset-normalizer]" reuse lint                           # every file has license + copyright metadata (REUSE)
uv run --with-requirements requirements-test.txt pytest tests/cplat -q # CLI + render tests (3 tests need the Kyverno CLI and skip without it)
copier copy ./templates/web-nextjs /tmp/try --defaults --trust --skip-tasks --data project_name=try   # render a template you touched
bash tests/e2e/run.sh                                                       # whole stack on a local k3d cluster (Docker, k3d, kubectl)
```

`bash scripts/ci-local.sh` (or `devbox run ci-local`; add `--render` to render every template) runs the first five in one go. The same checks are devbox scripts for the `/component:*` gates: `devbox run test-fast` (cplat tests), `quality` (static checks, no tests), `ci` (= `ci-local.sh`), `lint-fix` (no-op, no formatter here).

CI runs the same checks plus a smoke test per template (generated repos must pass their own `quality` and `test` recipes). Pull requests that only touch documentation run a reduced set of jobs.

## Documentation site

The site at <https://ika100.github.io/sdlc-foundry/> is built from `site/` (Astro Starlight). Narrative pages (vision, problem, value, scenarios, concepts, get started) live in `site/src/content/docs`; the guides, ADRs, changelog and community pages are **synced from the repository's Markdown** at build time, and the command, shape, configuration and CLI reference pages are **generated from the code**, so edit the source (`docs/`, `plugins/`, `shapes.yml`, `render.py`), not the copies. Preview locally:

```bash
cd site && npm ci --ignore-scripts && npm run dev      # http://localhost:4321/sdlc-foundry/
npm test && npm run build                              # unit tests, then a full build that fails on a broken internal link
```

CI builds the site on pull requests that touch its inputs; merging to `main` publishes it.

## Legal and privacy

- **Your license grant.** Submitting a contribution licenses it under Apache-2.0 (section 5 of the license); you keep your copyright. Only contribute work you have the right to contribute: no code copied from sources with an incompatible or unknown license, and nothing your employer owns without their permission.
- **AI-assisted contributions are welcome**, under the same rule: you are responsible for what you submit. Mention substantial AI assistance in the PR description and check generated code for copied snippets.
- **Third-party material** (code, icons, fonts, text) needs its license text in `LICENSES/`, an entry in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and an override in `REUSE.toml`; `reuse lint` (in CI) enforces that every file has license and copyright information.
- **Privacy.** Commit author names and e-mail addresses are public and permanent. Use your GitHub `@users.noreply.github.com` address if you do not want to publish a personal one.

## Sign your commits (DCO)

Every commit of a pull request needs a `Signed-off-by: Your Name <you@example.com>` line, which certifies the [Developer Certificate of Origin](https://developercertificate.org/): you wrote the change or otherwise have the right to submit it under this project's license. Git adds the line with `-s`:

```bash
git commit -s -m "feat(web): ..."          # new commits
git rebase --signoff origin/main           # sign off the commits of an existing branch, then force-push your branch
```

The sign-off e-mail must be the commit's author or committer e-mail (use your GitHub `@users.noreply.github.com` address if you prefer). The `DCO sign-off` CI job (`scripts/check-dco.py`) checks every non-merge commit of the PR; bots such as Dependabot are exempt. Commits the maintainer makes with Claude Code are signed off by the maintainer, who reviews them.

## Pull request rules

- **Conventional Commits** for the PR title (`feat(web): ...`, `fix(cplat): ...`, `docs: ...`); the title is checked and becomes the squash-commit message. Use branch names like `feat/...`, `fix/...`, `docs/...`.
- **One logical change per PR**, with tests. Behaviour in `scripts/cplat` needs a test in `tests/cplat`; a template change needs the template's own tests to pass when rendered.
- **Plugins**: when you change anything under `plugins/<name>/`, bump the version in both `plugins/<name>/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (semver: patch for fixes, minor for additions, major for breaking changes).
- **Keep always-on text small.** Agent and command `description:` front matter is loaded into every session (max 260 characters, enforced). Put detail in the body.
- **Changelog**: add a line under `## [Unreleased]` in `docs/CHANGELOG.md` for anything users can notice.
- **Decisions**: a change that alters how the platform works gets an ADR in `docs/adr/` (next free number; context, decision, consequences, what is not included) and a row in `docs/adr/README.md`.
- **GitHub Actions** must be pinned by commit SHA with a `# vX` comment (`python3 scripts/pin-actions.py` does it for you) and every workflow needs top-level `permissions:`.
- **No secrets** in code, tests or fixtures; build token-shaped test strings at runtime so scanners stay quiet.

## Releases

Maintainers release: move `[Unreleased]` under a new `## [x.y.z] - date` heading in `docs/CHANGELOG.md` (the platform version is read from the first such heading), make sure plugin and marketplace versions match, merge, tag `vX.Y.Z` and publish a GitHub release with the changelog section as notes. `/component:release` refuses in this repo (it has no release role); this section is the procedure.

CI runs `uv run scripts/release-check.py rows` on every PR: the `docs/CHANGELOG.md` section that will be released must list every changed row of the versions table, and an operator major move, a removed CRD version or a dropped resource major needs a major platform release. Before `git tag`, run `uv run scripts/release-check.py gate <merge sha>` and tag only when it passes: it needs a green upgrade e2e (`e2e upgrade (previous release → candidate)`) on that commit. The release gate workflow turns a tag push without one red; a maintainer then deletes that tag (no workflow creates, moves or deletes a tag).

## CI cost

CI is free for this public repository, but forks and private copies may pay per minute. A `changes` job decides which template smoke tests a PR needs (docs-only PRs skip them but still run the cplat tests, which read the changelog, specs and guides; only image and repository-metadata changes skip those too), the cluster test runs only when the GitOps template, the CLI or the e2e files change (plus nightly), superseded runs of the same PR are cancelled, and Dependabot batches its updates monthly. The only required status is `ci-success`, which passes when every job that ran passed (skipped jobs count as passed). The `tests/cplat` suite runs in 4 round-robin shards (`pytest --shard I/N`), and the `cplat shards cover the suite` job fails when a test runs in no shard or in two; a failing shard does not cancel the others. Tests that only need a rendered repo take the `new_service` or `shared_renders` fixture (one shared render, private copies); tests whose subject is the rendering itself still render (ADR-052). Run `scripts/ci-local.sh` (unsharded) to avoid waiting for CI.
