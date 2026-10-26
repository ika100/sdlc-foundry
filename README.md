# sdlc-foundry

[![CI](https://github.com/ika100/sdlc-foundry/actions/workflows/ci.yml/badge.svg)](https://github.com/ika100/sdlc-foundry/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-ika100.github.io-4f46e5)](https://ika100.github.io/sdlc-foundry/)
[![Release](https://img.shields.io/github/v/release/ika100/sdlc-foundry)](https://github.com/ika100/sdlc-foundry/releases)

**An agentic SDLC platform: Claude Code agents, slash commands and Copier templates that take a system from idea to "running in Kubernetes via GitOps".**

> Formerly *claude-platform*. Renamed in v3.0.0 to stay clear of a third-party trademark; GitHub redirects the old repository URL. Installed plugins must be reinstalled from the new marketplace: see the [changelog](docs/CHANGELOG.md) and run `/platform:doctor`.

You describe what you want in Claude Code; the platform scaffolds the repos (Python, Java, Go and Next.js services, plus a GitOps repo), builds and publishes multi-arch images, and renders every Kubernetes manifest from one declarative file in the GitOps repo. Secrets, a Postgres resource, OpenTelemetry observability and Kyverno guard rails are one declaration each; promotion between environments is a reviewed pull request. Everything that can be code is a tested script (`cplat`), and agents only orchestrate it.

- **Documentation site:** <https://ika100.github.io/sdlc-foundry/> has the vision, the problem statement, client value, usage scenarios and the full user documentation with search.
- **Start here:** [docs/USER-JOURNEY.md](docs/USER-JOURNEY.md) (end-to-end walk-through) and [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) (diagrams).
- **Needs:** [Claude Code](https://claude.com/claude-code), `git`, `gh`, `uv`, [devbox](https://www.jetify.com/devbox) and Docker for local clusters; run `/platform:doctor` to check.
- **Status:** used end to end on a real test application; see the [changelog](docs/CHANGELOG.md) and [ADRs](docs/adr).

## What's here

```
.
├── .claude-plugin/marketplace.json    Claude Code marketplace catalog
├── plugins/
│   ├── component/                     Component commands (/component:*): new, spec, plan, build, ship, release, add, set, remove ...
│   ├── svc/                           PM, architect, reviewer + Python agents, spec skills
│   ├── web/                           Next.js agents (coder, tester, deployment, observability, release)
│   ├── svc-java/                      Spring Boot agents
│   ├── svc-go/                        Go agents
│   ├── system/                        System specs across repos (/system:new, spec, plan, ship, status)
│   ├── api/ resource/ instance/       /api:list, /resource:add|remove, /instance:promote|secret|verify
│   ├── issue/ platform/               /issue:triage|report, /platform:doctor|update|fleet|runs|retro
│   └── shared/                        cplat on the PATH, hooks, quality and security agents
├── shapes.yml                         Shape registry (single source of truth)
├── templates/
│   ├── service-python/                Python service
│   ├── library-python/                Python library (no Docker)
│   ├── web-nextjs/                    Next.js App Router web app
│   ├── gitops-app/                    System-scoped GitOps repo: owns all manifests (ADR-017)
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
/component:new payments-api Stripe webhooks to Postgres                        # service in python (default)
/component:new my-saas-web  Marketing site and app --type website              # website in typescript (web-nextjs)
/component:new billing      Billing service --type service --lang java        # or --lang go; --type library
/system:new my-saas.yaml                                                       # a system: its gitops repo plus every component repo
```

`/component:new` resolves the shape from `shapes.yml` (type and language) and:

1. Runs `copier copy` from `templates/<shape>`
2. `git init` + commit
3. `gh repo create --private` under your GitHub account
4. `gh repo edit --add-topic deployable-service` (deployable shapes only) so ArgoCD discovers it

See `docs/requirements/platform-vision.md` §7 for the end-to-end system flow (`/system:new` → components → `/component:add` → `/instance:promote`).

## Install in an existing repo

```
/plugin marketplace add ika100/sdlc-foundry
/plugin install component@sdlc-foundry        # + web / svc-java / svc-go / system as your shapes need
/plugin install svc@sdlc-foundry
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
    "component@sdlc-foundry": true,
    "svc@sdlc-foundry": true,
    "shared@sdlc-foundry": true
  }
}
```

See `docs/ADOPTING.md` for the full migration guide.

## Slash commands

| Command | Plugin | Purpose |
|---|---|---|
| `/component:spec <desc>` | component | Feature spec with acceptance criteria `AC-<NNN>.<n>`; asks you its open questions; `approve <id>`, `--amend <id>`, `--from-plan` for multi-repo plans; `index` lists specs with the next step, `migrate` converts legacy stories |
| `/component:plan <id>` | component | Architect: `design.md` + `plan.md` for an approved spec, checked by `cplat spec` |
| `/component:build <id>` | component | Failing acceptance tests → parallel coders → quality ‖ tests ‖ security → reviewer verifies the spec → image → PR (shape-aware, resumable) |
| `/component:ship <id> [--no-merge]` | component | Unattended: plan → build → PR → merge after green CI → wait until `dev` runs it; resumable, kept going by the Stop hook ([ADR-028](docs/adr/028-unattended-delivery-without-branch-protection.md)) |
| `/component:verify [<id>]` | component | Check code against a spec |
| `/component:fix <desc>` | component | Lightweight and bug fixes: coder → quality → tester → PR |
| `/component:release` | component | Quality gate → test gate → security gate → version bump → tag → close issues |
| `/component:check` | component | Read-only quality + security audit |
| `/component:new <name> <desc> [--type T --lang L]` | component | Bootstrap a new component repo (`shapes.yml` resolves type and language to a template; default service in python), with `main` protected by its CI checks |
| `/component:add\|set\|remove <component...>` | component | In a system's gitops repo: declare components in `system.yaml`; `set` changes env, exposure, resources or replicas of one already declared |
| `/system:new <manifest>` | system | A whole system: its gitops repo plus every component repo |
| `/system:spec <desc>` · `/system:plan <id>` | system | System spec, then every criterion assigned to a repo with the contract (topo-sorted, validated) |
| `/system:ship <id>` · `/system:status` | system | Ship ready repos in parallel, each through its own spec slice, ending at PRs and a running dev · one table: image pins per environment, component CI, Argo sync/health, resources |
| `/api:list` | api | The APIs the system declares, with provider and consumers |
| `/resource:add\|remove <name>` | resource | A named, typed resource of the system (a database on CloudNativePG, or an external one); observability is set per environment in `system.yaml` |
| `/instance:promote <component...\|--all> --to <env> [--version]` | instance | Pin component versions in an environment, open one PR |
| `/instance:secret set\|list …` | instance | Values of store-backed secrets in the local cluster (generated secrets need nothing) |
| `/instance:verify [<env>]` | instance | Smoke tests against a deployed instance |
| `/platform:doctor` | platform | Preflight: tools, `gh` scopes, Docker, kube context, plugin versions, repo platform version, with a fix per problem |
| `/platform:update [--ref <tag>] [--migrate]` | platform | Pull the latest skeleton (CI, devbox, Dockerfile, CLAUDE.md…) into an existing repo on a review branch; `--migrate` converts a 4.x repo |
| `/platform:fleet update` · `/platform:runs` · `/platform:retro` | platform | Update every repo built from the platform · run records and cost · the weekly retro |
| `/issue:report [what]` | issue | Draft a platform issue with diagnostics (secrets removed) and file it after your OK |
| `/issue:triage` | issue | Route GitHub issues to specs, fixes or replies |

Every generated repo also checks its specs in CI (warn-only `specs` workflow, `devbox run spec-check`): all specs valid, and every criterion of a spec being built named by a test. Unattended runs (`claude -p`, `/loop`, `/schedule`): see [ADOPTING.md → Unattended runs](docs/ADOPTING.md#unattended-runs).

## Updates

- **Agent / command changes:** bump the version in `plugins/<name>/.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`, tag, and push. Consumers run `/plugin marketplace update`.
- **Template changes:** edit `templates/<shape>/`, commit, tag. Consumers run `/platform:update` (optionally `--ref <tag>`) in their repo: it re-applies the template on a review branch and leaves project-owned files alone.

These two channels are independent — you can ship new agents without forcing all repos to run `/platform:update`, and vice versa.

## Using it for your own organisation

The marketplace is published as `ika100/sdlc-foundry` and installs as `sdlc-foundry`. Generated repositories use the `github_org` you are asked for (it defaults to the account `gh` is logged in as), so nothing in the output is tied to this repository's owner. To run your own variant, fork the repository, change the owner in `.claude-plugin/marketplace.json`, and add your fork with `/plugin marketplace add <you>/sdlc-foundry`. Code generated from the templates is yours; this repository's license does not apply to it.

## Disclaimer, privacy, AI-assisted development

- **Not affiliated.** sdlc-foundry is an independent open-source project, not affiliated with, sponsored by or endorsed by Anthropic or the owners of the other names it mentions (see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)). *Claude* and *Claude Code* are trademarks of Anthropic, PBC.
- **No warranty.** The software is provided "as is" under the [Apache License 2.0](LICENSE) (sections 7 and 8). Review what it generates (manifests, workflows, policies) before it touches a production cluster; the platform never runs `kubectl apply` on its own, and humans bootstrap real clusters.
- **No telemetry.** The plugins and the `cplat` CLI send nothing anywhere on their own. Network access is what you would expect: `git`/`gh` against GitHub, package registries, GHCR. Generated applications export telemetry only to the endpoint you configure. `/issue:report` shows you the full text first and files it only after your OK; **issues on this repository are public**, and the draft already has tokens, e-mail addresses and home-directory names removed.
- **AI-assisted.** Much of this repository was written with Claude Code and reviewed, tested and committed by the maintainer (commits carry a `Co-Authored-By` trailer). Licensing is the maintainer's: AI-generated parts may be subject to limited copyright protection depending on jurisdiction.

## Contributing, security, support

- [CONTRIBUTING.md](CONTRIBUTING.md): how to set up, which checks to run, PR rules. [Code of Conduct](CODE_OF_CONDUCT.md).
- [SECURITY.md](SECURITY.md): report vulnerabilities privately. [SUPPORT.md](SUPPORT.md): where to ask questions.

## Reporting problems

If something in a template, script, command or agent misbehaves, run **`/issue:report`** in Claude Code. It drafts a GitHub issue with your platform and plugin versions, OS, tool availability and the error output, removes tokens, e-mail addresses and home-directory names, shows you the draft and files it only after your OK (without `gh` it prints a prefilled link). The agents suggest it themselves when a step fails for a platform reason. You can also open an issue by hand: [new issue](https://github.com/ika100/sdlc-foundry/issues/new/choose).

## License

[Apache License 2.0](LICENSE). Copyright 2026 Eike Hensler.
