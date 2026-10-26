---
title: "Ship a system from zero"
slug: scenarios/ship-a-system
description: "From an idea to a running, promoted system: GitOps repo, components, first environment."
---

**Situation.** You are starting "Shop": a Java API and a Next.js web app. You have no repositories.

## Steps

Describe the system once and let the platform create every repository:

```yaml
# shop.yml
system: shop
owner: team-shop
components:
  - {name: shop-api, description: Catalog and orders API, type: service, lang: java}
  - {name: shop-web, description: Storefront, type: website, lang: typescript}
```

```text
/system:new shop.yml
```

It creates the GitOps repository `shop` and both services from their templates (CI, Dockerfile, `devbox` recipes, agent instructions), protects each `main` with its CI checks, and opens one pull request in `shop` that composes the services. Merge it. (One repository at a time works too: `/component:new shop-api "Catalog and orders API" --type service --lang java --system acme/shop`, then `/component:add shop-api` in `shop`.)

Build the first feature across the system, spec first, in `shop`:

```text
/system:spec "customers browse the catalog and place an order"   # answer its questions, approve
/system:plan 001                                                  # which repo does what, the contract between them
/system:ship 001                                                # every repo in plan order, each shipped through its own slice
```

The plan also carries the system wiring: exposing `shop-web`, `API_URL` for it, a Postgres database for `shop-api`. `/system:ship` applies that in `shop` first (the PR marked **merge first**), then builds each component from its own slice of the spec. See [Build a feature](/sdlc-foundry/scenarios/build-a-feature/). Merge the pull requests, then run the system locally:

```bash
devbox run cluster-up      # k3d, ArgoCD, Gateway API, your GitHub credentials, the root Application
```

To run the whole thing unattended, ship the approved spec:

```text
/system:ship 001                                                # spec and plan PR merged on green, every repo shipped in plan order
```

`/system:ship` runs one `/component:ship` per repository, starting each once the repositories it depends on passed their gate (a service is Synced/Healthy in dev and, if exposed, passes its smoke test). Pull requests in `shop` merge one at a time. A repository that escalates stops only its dependents, and it needs a kube context for the system's cluster ([ADR-042](/sdlc-foundry/reference/adr/042/)).

## What you get

- Two repositories that build, test, scan and publish `linux/amd64` and `linux/arm64` images on every merge to `main`, with `main` protected by those checks.
- Specs in `docs/specs/` that say what the system does, with every criterion traced to a test.
- A GitOps repository containing the generated Deployments, Services and routes for the `dev` environment, synced by ArgoCD.
- `http://shop-web.shop-dev.localhost:8088/` once the pods are ready (`cluster-up` prints the port it chose if 8088 was taken; `*.localhost` needs no DNS setup); `/system:status` shows the pinned image per environment.

## Check it

`/platform:doctor` reports missing tools or `gh` scopes with a fix for each. If something fails because a template or script misbehaves, `/issue:report` drafts an issue for you.

Next: [Promote to production safely](/sdlc-foundry/scenarios/promote-safely/).
