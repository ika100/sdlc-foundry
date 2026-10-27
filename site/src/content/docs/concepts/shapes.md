---
title: "Shapes"
description: "A shape is a kind of repository; it decides the template and the agents."
sidebar:
  order: 2
---

Every repository has a **shape**: `service-python`, `service-java`, `service-go`, `web-nextjs`, `library-python` or `gitops-app`. In the [domain model](/sdlc-foundry/concepts/domain-model/) a shape is a component's `type` and `lang` in `system.yaml` (`service` + `java` is `service-java`, `website` + `typescript` is `web-nextjs`); `gitops-app` is the repository of the system itself. The shape decides:

- which **template** creates the repository (CI, Dockerfile, `devbox` recipes, agent instructions),
- which **agents** work on it (a Java coder knows Maven and Spring; a web tester knows Vitest and Playwright),
- the **runtime defaults** the GitOps repository uses when it composes the service: port, probes, user, writable volumes, resources, metrics path.

The orchestration commands (`/component:spec`, `/component:plan`, `/component:build` and friends) are the same for every shape; the shape is detected from the repository and the right agents are routed in. All shapes share the same `devbox run` recipes, so humans, CI and agents behave identically.

The registry is `shapes.yml`, the single source of truth, validated by `scripts/shapes.py check`. See the generated [shapes table](/sdlc-foundry/reference/shapes/) and [how to add one](/sdlc-foundry/guides/add-a-shape/).
