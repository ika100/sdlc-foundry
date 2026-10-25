---
title: "Ship a product from zero"
description: "From an idea to a running, promoted application: GitOps repo, services, first environment."
---

**Situation.** You are starting "Shop": a Java API and a Next.js web app. You have no repositories.

## Steps

Describe the product once and let the platform create every repository:

```yaml
# shop.yml
app: shop
components:
  - {name: shop-api, description: Catalog and orders API, shape: service-java}
  - {name: shop-web, description: Storefront, shape: web-nextjs}
```

```text
/shared:new-app shop.yml
```

It creates the GitOps repository `shop` and both services from their templates (CI, Dockerfile, `devbox` recipes, agent instructions), protects each `main` with its CI checks, and opens one pull request in `shop` that composes the services. Merge it. (One repository at a time works too: `/shared:new-service shop-api Catalog and orders API --type service-java`, then `/gitops:compose add shop-api` in `shop`.)

Build the first feature across the product, spec first, in `shop`:

```text
/app:spec "customers browse the catalog and place an order"   # answer its questions, approve
/app:plan 001                                                  # which repo does what, the contract between them
/app:build 001                                                 # every repo in parallel, each ending at an open PR
```

The plan also carries the product wiring: exposing `shop-web`, `API_URL` for it, a Postgres database for `shop-api`. `/app:build` applies that in `shop` first (the PR marked **merge first**), then builds each service from its own slice of the spec. See [Build a feature](/sdlc-foundry/scenarios/build-a-feature/). Merge the pull requests, then run the product locally:

```bash
devbox run cluster-up      # k3d, ArgoCD, Gateway API, your GitHub credentials, the root Application
```

To run the whole thing unattended, ship the approved spec instead of building it:

```text
/app:ship 001                                                  # spec and plan PR merged on green, every repo shipped in plan order
```

`/app:ship` runs one `/svc:ship` per repository, starting each once the repositories it depends on passed their gate (a service is Synced/Healthy in dev and, if exposed, passes its smoke test). Pull requests in `shop` merge one at a time. A repository that escalates stops only its dependents, and it needs a kube context for the product's cluster ([ADR-042](/sdlc-foundry/reference/adr/042/)).

## What you get

- Two repositories that build, test, scan and publish `linux/amd64` and `linux/arm64` images on every merge to `main`, with `main` protected by those checks.
- Specs in `docs/specs/` that say what the product does, with every criterion traced to a test.
- A GitOps repository containing the generated Deployments, Services and routes for the `dev` environment, synced by ArgoCD.
- `http://shop-web.shop-dev.localhost:8088/` once the pods are ready (`cluster-up` prints the port it chose if 8088 was taken; `*.localhost` needs no DNS setup); `/shared:status` shows the pinned image per environment.

## Check it

`/shared:doctor` reports missing tools or `gh` scopes with a fix for each. If something fails because a template or script misbehaves, `/shared:report-issue` drafts an issue for you.

Next: [Promote to production safely](/sdlc-foundry/scenarios/promote-safely/).
