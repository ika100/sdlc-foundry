# sdlc-foundry

[![CI](https://github.com/ika100/sdlc-foundry/actions/workflows/ci.yml/badge.svg)](https://github.com/ika100/sdlc-foundry/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-ika100.github.io-4f46e5)](https://ika100.github.io/sdlc-foundry/)
[![Release](https://img.shields.io/github/v/release/ika100/sdlc-foundry)](https://github.com/ika100/sdlc-foundry/releases)

**An agentic SDLC platform: Claude Code agents, slash commands and Copier templates that take a product from idea to "running in Kubernetes via GitOps".**

> Formerly *claude-platform*. Renamed in v3.0.0 to stay clear of a third-party trademark; GitHub redirects the old repository URL. Installed plugins must be reinstalled from the new marketplace: see the [changelog](docs/CHANGELOG.md) and run `/shared:doctor`.

You describe what you want in Claude Code; the platform scaffolds the repos (Python, Java, Go and Next.js services, plus a GitOps repo), builds and publishes multi-arch images, and renders every Kubernetes manifest from one declarative file in the GitOps repo. Secrets, a Postgres addon, OpenTelemetry observability and Kyverno guard rails are one declaration each; promotion between environments is a reviewed pull request. Everything that can be code is a tested script (`cplat`), and agents only orchestrate it.

- **Documentation site:** <https://ika100.github.io/sdlc-foundry/> has the vision, the problem statement, client value, usage scenarios and the full user documentation with search.
- **Start here:** [docs/USER-JOURNEY.md](docs/USER-JOURNEY.md) (end-to-end walk-through) and [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) (diagrams).
- **Needs:** [Claude Code](https://claude.com/claude-code), `git`, `gh`, `uv`, [devbox](https://www.jetify.com/devbox) and Docker for local clusters; run `/shared:doctor` to check.
- **Status:** used end to end on a real test application; see the [changelog](docs/CHANGELOG.md) and [ADRs](docs/adr).

## What's here

```
.
├── .claude-plugin/marketplace.json    Claude Code marketplace catalog
├── plugins/
│   ├── svc/                           Orchestrators (/svc:*), PM, architect + Python agents
│   ├── web/                           Next.js agents (coder, tester, deployment, observability, release)
│   ├── svc-java/                      Spring Boot agents
│   ├── svc-go/                        Go agents
│   ├── gitops/                        Platform GitOps + gitops-app agents (deployment, promote, compose)
│   ├── app/                           Product specs across repos (/app:spec, plan, build, specs)
│   └── shared/                        Quality, security, /new-service
├── shapes.yml                         Shape registry (single source of truth)
├── templates/
│   ├── service-python/                Python service
│   ├── library-python/                Python library (no Docker)
│   ├── web-nextjs/                    Next.js App Router web app
│   ├── gitops-app/                    Product-scoped GitOps repo: owns all manifests (ADR-017)
│   ├── service-java/                  Spring Boot 3 / JDK 21 service
│   └── service-go/                    Go (chi) service
├── scripts/                           detect-shape.sh, shapes.py, tests
└── docs/
    ├── USER-JOURNEY.md                End-to-end walk-through (start here to explain the setup)
    ├── AGENTS.md                      Orchestration model
    ├── ADOPTING.md                    How to bring an existing repo onto the platform
    ├── ARCHITECTURE.md                Why the platform looks the way it does
    ├── templates.md                   How to add a new shape
    ├── requirements/                  Platform vision PRD
    └── adr/                           Architecture decision records
```

## Install in a new repo

```
/shared:new-service payments-api Stripe webhooks to Postgres            # service-python (default)
/shared:new-service my-saas-web  Marketing site and app --web           # web-nextjs
/shared:new-service my-saas      GitOps for my-saas --gitops            # gitops-app
/shared:new-service billing      Billing service --type service-java    # or service-go, library-python
```

`/shared:new-service` resolves the shape from `shapes.yml` and:

1. Runs `copier copy` from `templates/<shape>`
2. `git init` + commit
3. `gh repo create --private` under your GitHub account
4. `gh repo edit --add-topic deployable-service` (deployable shapes only) so ArgoCD discovers it

See `docs/requirements/platform-vision.md` §7 for the end-to-end product flow (`--gitops` repo → services → `/gitops:compose` → `/gitops:promote`).

## Install in an existing repo

```
/plugin marketplace add ika100/sdlc-foundry
/plugin install svc@sdlc-foundry        # + web / svc-java / svc-go / gitops / app as your shapes need
/plugin install shared@sdlc-foundry
```

…or pre-wire it by adding to `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "sdlc-foundry": {
      "source": { "source": "github", "repo": "ika100/sdlc-foundry", "ref": "main" }
    }
  },
  "enabledPlugins": {
    "svc@sdlc-foundry": true,
    "shared@sdlc-foundry": true
  }
}
```

See `docs/ADOPTING.md` for the full migration guide.

## Slash commands

| Command | Plugin | Purpose |
|---|---|---|
| `/svc:spec <desc>` | svc | Feature spec with acceptance criteria `AC-<NNN>.<n>`; asks you its open questions; `approve <id>`, `--amend <id>`, `--from-plan` for multi-repo plans |
| `/svc:plan <id>` | svc | Architect: `design.md` + `plan.md` for an approved spec, checked by `cplat spec` |
| `/svc:build <id>` | svc | Failing acceptance tests → parallel coders → quality ‖ tests ‖ security → reviewer verifies the spec → image → PR (shape-aware, resumable) |
| `/svc:ship <id> [--no-merge]` | svc | Unattended: plan → build → PR → merge after green CI → wait until `dev` runs it; resumable, kept going by the Stop hook ([ADR-028](docs/adr/028-unattended-delivery-without-branch-protection.md)) |
| `/svc:verify [<id>]` · `/svc:specs` | svc | Check code against a spec · list specs with the next step, migrate legacy stories |
| `/svc:quick-task <desc>` | svc | Lightweight: coder → quality → tester → PR |
| `/svc:fix-bug <desc>` | svc | Diagnose → fix → regression test → PR |
| `/svc:release` | svc | Quality gate → test gate → security gate → version bump → tag → close issues |
| `/gitops:promote <svc...> <from> <to> [version]` | gitops | Pin service versions in an environment overlay (platform or gitops-app repo), open one PR |
| `/gitops:compose add\|set\|remove <svc...>` | gitops | gitops-app repos: declare the application's services; `set` changes env, exposure, addons or replicas of one already composed |
| `/gitops:addon add\|remove\|list <postgres\|observability>` | gitops | Backing services and observability for the application (CloudNativePG, OpenTelemetry collector, optional Grafana dev stack) |
| `/gitops:secret set\|list …` | gitops | Values of store-backed secrets in the local cluster (generated secrets need nothing) |
| `/app:spec <desc>` · `/app:plan <id>` | app | gitops-app repos: product spec, then every criterion assigned to a repo with the contract (topo-sorted, validated) |
| `/app:build <id>` · `/app:specs` | app | Build ready repos in parallel, each through its own spec slice, ending at PRs · progress |
| `/shared:doctor` | shared | Preflight: tools, `gh` scopes, Docker, kube context, plugin versions, repo platform version, with a fix per problem |
| `/shared:status` | shared | One table for a gitops-app: image pins per environment, service CI, Argo sync/health, addons |
| `/shared:report-issue [what]` | shared | Draft a platform issue with diagnostics (secrets removed) and file it after your OK |
| `/shared:check-quality` | shared | Read-only quality + security audit |
| `/shared:update-service [--ref <tag>]` | shared | Pull the latest skeleton (CI, devbox, Dockerfile, CLAUDE.md…) into an existing repo on a review branch |
| `/shared:new-service <name>` | shared | Bootstrap a new repo of any registered shape (`shapes.yml`; default `service-python`, `--type <shape>` to choose), with `main` protected by its CI checks |

Every generated repo also checks its specs in CI (warn-only `specs` workflow, `devbox run spec-check`): all specs valid, and every criterion of a spec being built named by a test. Unattended runs (`claude -p`, `/loop`, `/schedule`): see [ADOPTING.md → Unattended runs](docs/ADOPTING.md#unattended-runs).

## Updates

- **Agent / command changes:** bump the version in `plugins/<name>/.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`, tag, and push. Consumers run `/plugin marketplace update`.
- **Template changes:** edit `templates/<shape>/`, commit, tag. Consumers run `/shared:update-service` (optionally `--ref <tag>`) in their repo: it re-applies the template on a review branch and leaves project-owned files alone.

These two channels are independent — you can ship new agents without forcing all repos to run `/shared:update-service`, and vice versa.

## Using it for your own organisation

The marketplace is published as `ika100/sdlc-foundry` and installs as `sdlc-foundry`. Generated repositories use the `github_org` you are asked for (it defaults to the account `gh` is logged in as), so nothing in the output is tied to this repository's owner. To run your own variant, fork the repository, change the owner in `.claude-plugin/marketplace.json`, and add your fork with `/plugin marketplace add <you>/sdlc-foundry`. Code generated from the templates is yours; this repository's license does not apply to it.

## Disclaimer, privacy, AI-assisted development

- **Not affiliated.** sdlc-foundry is an independent open-source project, not affiliated with, sponsored by or endorsed by Anthropic or the owners of the other product names it mentions (see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). *Claude* and *Claude Code* are trademarks of Anthropic, PBC.
- **No warranty.** The software is provided "as is" under the [Apache License 2.0](LICENSE) (sections 7 and 8). Review what it generates (manifests, workflows, policies) before it touches a production cluster; the platform never runs `kubectl apply` on its own, and humans bootstrap real clusters.
- **No telemetry.** The plugins and the `cplat` CLI send nothing anywhere on their own. Network access is what you would expect: `git`/`gh` against GitHub, package registries, GHCR. Generated applications export telemetry only to the endpoint you configure. `/shared:report-issue` shows you the full text first and files it only after your OK; **issues on this repository are public**, and the draft already has tokens, e-mail addresses and home-directory names removed.
- **AI-assisted.** Much of this repository was written with Claude Code and reviewed, tested and committed by the maintainer (commits carry a `Co-Authored-By` trailer). Licensing is the maintainer's: AI-generated parts may be subject to limited copyright protection depending on jurisdiction.

## Contributing, security, support

- [CONTRIBUTING.md](CONTRIBUTING.md): how to set up, which checks to run, PR rules. [Code of Conduct](CODE_OF_CONDUCT.md).
- [SECURITY.md](SECURITY.md): report vulnerabilities privately. [SUPPORT.md](SUPPORT.md): where to ask questions.

## Reporting problems

If something in a template, script, command or agent misbehaves, run **`/shared:report-issue`** in Claude Code. It drafts a GitHub issue with your platform and plugin versions, OS, tool availability and the error output, removes tokens, e-mail addresses and home-directory names, shows you the draft and files it only after your OK (without `gh` it prints a prefilled link). The agents suggest it themselves when a step fails for a platform reason. You can also open an issue by hand: [new issue](https://github.com/ika100/sdlc-foundry/issues/new/choose).

## License

[Apache License 2.0](LICENSE). Copyright 2026 Eike Hensler.
