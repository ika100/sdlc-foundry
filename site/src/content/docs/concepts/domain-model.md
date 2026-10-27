---
title: "The domain model"
description: "A dozen nouns in three layers: what a system is made of, where it runs, and how it changes. Every command acts on one of them."
sidebar:
  order: 1
---

The platform is built around a small set of nouns you can hold in your head. They answer three questions:

| You ask | The model answers with |
|---|---|
| What is my system made of? | the **System** and its parts: **Components**, **APIs**, **Resources**, and its **Owner** |
| Where does it run, at which version? | **Environments** × parts: each cell is an **Instance**; the environments run on a **Cluster** that several systems may share |
| How does it change? | an **Issue** becomes a **Spec**; a **Run** ships it; a **Release** goes to prod |

The first part is [Backstage's system model](https://backstage.io/docs/features/software-catalog/system-model), reduced to what a user needs; the platform adds environments and the delivery process on top. It is a model only: you do not need Backstage.

## Three layers

![System model: what it is, where it runs, how it changes](/sdlc-foundry/img/model-system.svg)

- **What it is.** An Owner owns a System. Components (a service, a website or a library, each in its own repo), APIs and Resources (a database or a bucket, run by the platform or external) are part of it. A component provides or consumes APIs, uses resources and may use a library.
- **Where it runs.** Every component and resource exists once per environment as an **Instance**. Environments are ordered (dev, staging, prod), so each instance knows where its version came from. A library has no instances.
- **On which cluster.** Every environment of a system runs on one **Cluster**. A cluster hosts one or more systems and owns what they share: the operators that manage the resource instances (CloudNativePG, SeaweedFS), External Secrets with the secret store, and the Kyverno engine. Its own repo lists the systems it hosts (`/cluster:add`) and fails its check when a system needs an operator the cluster does not list. Components never refer to the cluster, so a system renders the same either way. See [the domain model guide](/sdlc-foundry/guides/domain-model/#cluster) and the [cluster guide](/sdlc-foundry/guides/clusters/).
- **How it changes.** A Spec changes the system or one component; the Run that ships it updates instances, starting in dev.

## An example: the todo system

![The todo system: parts on the left, one instance per environment on the right](/sdlc-foundry/img/model-example.svg)

Read the left column as "what the system is" and the grid as "where each part runs right now". A row is one part across environments; promoting moves a version one cell to the right. The platform writes versions when it pins and promotes; health and smoke results are looked up when you ask (`/system:status`), never stored.

## One file per system

Everything in the first two layers is declared in one file, `applications/<system>/system.yaml` in the system's [GitOps repository](/sdlc-foundry/concepts/gitops-model/). Versions are never in it.

```yaml title="applications/todo/system.yaml"
system: todo
owner: team-todo

environments:                  # dev, staging, prod, in promotion order
  dev:     {policy: audit, observability: {ui: lgtm}}
  staging: {promote: after-dev-smoke}
  prod:    {promote: manual, policy: enforce}

components:
  todo-api:
    type: service
    lang: python
    provides: [todo-api-rest]
    uses: [postgres]
    instances: {dev: {}, staging: {}, prod: {replicas: 2}}
  todo-web:
    type: website
    lang: typescript
    consumes: [todo-api-rest]
    expose: true
    instances: {dev: {}, staging: {}}

apis:
  todo-api-rest: {type: openapi}

resources:
  postgres:
    type: database
    instances: {prod: {replicas: 3, storage: 20Gi}}
```

## Commands follow the nouns

Every slash command names the noun it acts on, and the same verbs work for a system and for a component.

| Noun | Verbs |
|---|---|
| `system` | `new` · `set` · `status` · `spec` · `plan` · `ship` · `restore` |
| `component` | `new` · `add` · `set` · `remove` · `spec` · `plan` · `build` · `verify` · `check` · `ship` · `fix` · `release` |
| `api` | `list` |
| `resource` | `add` · `remove` · `backup` · `restore` |
| `cluster` | `new` · `add` · `remove` |
| `instance` | `promote <component> --to <env>` · `secret set <component>/<env>` · `verify` |
| `issue` | `triage` · `report` |
| `platform` | `doctor` · `update` · `fleet` · `runs` · `retro` · `ui` |

`cplat model show` prints a system in these nouns. The [slash command reference](/sdlc-foundry/reference/commands/) is grouped the same way.

## How a change moves through it

![Lifecycles of a spec, a run and a version](/sdlc-foundry/img/model-lifecycles.svg)

Thick borders are where you decide: approving a spec, an escalation, promoting to prod. Everything else runs unattended. A smoke that did not run is NOT VERIFIED and promotes nothing, and prod runs the exact image staging verified.

The full model (the delivery nouns from Issue to Release, every `system.yaml` key and its semantics, and how the 4.x names map onto the nouns) is in the [domain model guide](/sdlc-foundry/guides/domain-model/).
