---
title: "Your first system"
description: "Install the plugins, check your setup and create a first system in about fifteen minutes."
---

<p class="lead">You need Claude Code, a GitHub account and a few tools. Everything else is created for you.</p>

## 1. Prerequisites

| Tool | Why | Check |
|---|---|---|
| [Claude Code](https://claude.com/claude-code) | runs the agents and slash commands | `claude --version` |
| `git` and [`gh`](https://cli.github.com), logged in | creates repositories, pull requests, reads image tags | `gh auth status` (scopes `repo`, `workflow`; add `read:packages` for local clusters: `gh auth refresh -s read:packages`) |
| [`uv`](https://docs.astral.sh/uv/) | runs the tested `cplat` CLI | `uv --version` |
| [`devbox`](https://www.jetify.com/devbox) | every recipe (`quality`, `test`, `cluster-up`) runs through it | `devbox version` |
| Docker | image builds and the local cluster | `docker info` |

`k3d`, `kubectl` and the other cluster tools come with the GitOps repository's own `devbox` environment; you do not install them separately.

## 2. Install the plugins

In Claude Code:

```text
/plugin marketplace add ika100/sdlc-foundry
/plugin install system@sdlc-foundry
/plugin install component@sdlc-foundry
/plugin install instance@sdlc-foundry
/plugin install platform@sdlc-foundry
```

Add `resource`, `api`, `issue`, `web`, `svc-java` and `svc-go` for the shapes you use. After installing or updating plugins, **restart Claude Code**: a running session keeps the old prompts.

## 3. Check your setup

```text
/platform:doctor
```

It checks the tools above, `gh` scopes, Docker, your kube context (and warns when it is not local), plugin versions and the platform version of the current repository, and prints a concrete fix for every problem.

## 4. Create the system

```text
/system:new shop.yml
/component:new shop-api Catalog and orders API --lang java --system you/shop
/component:new shop-web Storefront --type website --system you/shop
```

Each command shows what it will do and asks before anything outward-facing (creating the GitHub repository, pushing). `/system:new` reads a manifest and creates the GitOps repository with its `system.yaml` plus a repository per component. The default is a Python service; `--type` and `--lang` pick the kind and language of a component; the registered [shapes](/sdlc-foundry/reference/shapes/) decide the template.

## 5. Build, add, run

1. In a component repository: `/component:spec <what you want>`, then `/component:plan <NNN>` and `/component:build <NNN>` (or `/component:fix` for a bug). See [Build a feature](/sdlc-foundry/scenarios/build-a-feature/).
2. When CI has published the first image: `/component:add shop-api` in the GitOps repository, then merge the pull request.
3. [Run it on your laptop](/sdlc-foundry/get-started/local-cluster/).

## 6. Optional: the console

Everything above runs in Claude Code; you never need a UI. If you like an overview, run `/platform:ui` in the GitOps repository: a local page shows what waits for your decision, every change by stage, and where each component runs. Every button there runs one of the same slash commands. See [The local console](/sdlc-foundry/guides/console/).

## Where to go next

- The whole story with every command: [User journey](/sdlc-foundry/guides/user-journey/).
- Concepts in five minutes: [Concepts](/sdlc-foundry/concepts/).
- Something broke: [Troubleshooting](/sdlc-foundry/guides/adopting/#troubleshooting) or `/issue:report`.
