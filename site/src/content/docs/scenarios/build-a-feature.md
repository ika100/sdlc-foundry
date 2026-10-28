---
title: "Build a feature with the agent pipeline"
description: "Turn a request into an approved spec, failing acceptance tests, code that passes them and a verified pull request, in any shape."
---

**Situation.** `shop-api` exists; you want "customers can save a wishlist".

## Steps

Pick the command by size:

| Size | Command | What runs |
|---|---|---|
| Small, clear change | `/component:fix add a wishlist count to the profile endpoint` | Coder, quality, tester with a fix loop, then a pull request |
| Real feature, step 1 | `/component:spec customers can save a wishlist` | Product manager writes `docs/specs/<NNN>-wishlist/spec.md` with acceptance criteria `AC-<NNN>.<n>`; you answer its open questions and approve |
| Real feature, step 2 | `/component:plan <NNN>` | Architect: `design.md` (contract) and `plan.md` (tasks covering every criterion) |
| Real feature, step 3 | `/component:build <NNN>` | Failing acceptance tests first, parallel coders until they pass, quality, tester and security in parallel, a reviewer checks every criterion, image check, pull request |
| Bug | `/component:fix saving twice duplicates the entry` | Coder and tester in a tight loop with a regression test |

The commands detect the repository's shape (Python, Java, Go, Next.js) and route to the matching coder, tester, deployment, observability and release agents. Every phase runs `devbox run <recipe>`, so CI and agents see the same results.

To go from an approved spec to a running feature without babysitting, use `/component:ship <NNN>`: it plans, builds, merges on green CI and waits until dev runs it. A criterion written with `(smoke)` at the end is then checked against the deployed dev service with `devbox run smoke`; a red smoke escalates and files a `smoke-failure` issue instead of promoting ([ADR-040](/sdlc-foundry/reference/adr/040/)). Runs start on a Sonnet coordinator, so a small change costs cents, not dollars. A ship stays within one budget (180 minutes, 60 invocations, $15) and stops after two equivalent failures; measured on a LAN cluster it cost $1.20 to $1.60 per run. It uses `CPLAT_KUBE_CONTEXT` (or `kube_context` in `.platform-settings.yml`) for the deploy step and switches to the feature branch itself.

## What you get

- A branch with a conventional commit history and a pull request whose body lists exactly which checks ran.
- A spec you approved, acceptance tests written from it before the code, and `verification.md` showing each criterion with its test and code; the security and image checks are part of `/component:build`. `/component:spec` with no description shows where every spec stands.
- Nothing is pushed without your confirmation.

## Across repositories

In the GitOps repository, `/system:spec` writes a system spec, `/system:plan` assigns each of its criteria to a component (a validated, topologically sorted plan with the contract between components) and `/system:spec` with no description tracks it. `/system:ship` builds every ready repository in plan order, each through its own slice of the spec (`/component:spec --from-plan` → `/component:plan` → `/component:build`); nothing merges without you ([ADR-007](/sdlc-foundry/reference/adr/007/), [ADR-023](/sdlc-foundry/reference/adr/023/)).

See the [agent model](/sdlc-foundry/guides/agents/) for how the phases fit together.
