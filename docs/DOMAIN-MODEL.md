# Domain model

The nouns the platform is built around: what a product is made of, where it runs, and how it changes. The model takes [Backstage's system model](https://backstage.io/docs/features/software-catalog/system-model) for the first part and adds environments and the delivery process. It is a model only: the platform does not use or need Backstage. Decisions and the migration path are in [ADR-053](adr/053-domain-model.md).

**Status:** this is the target model of sdlc-foundry 5.0. The internal core (spec 113) lands in 4.x without changing any command or file; the user-facing switch to `system.yaml` and noun-based commands (spec 114) is the 5.0 release. Until then, [The model today](#the-model-today) shows the names you use now, and [Today's features on the model](#todays-features-on-the-model) maps every command onto the nouns.

## Three questions

| You ask | The model answers with |
|---|---|
| What is my product made of? | the **System** and its parts: **Components**, **APIs**, **Resources**, and its **Owner** |
| Where does it run, at which version? | **Environments** × parts: each cell is an **Instance** (or a **Resource instance**) |
| How does it change? | an **Issue** becomes a **Spec**; a **Run** ships it; a **Release** goes to prod |

## The system model

![System model: what it is, where it runs, how it changes](img/model-system.svg)

Three layers:

- **What it is** is Backstage's system model, reduced to the kinds a user needs. An Owner owns a System; Components, APIs and Resources are part of it. A Component provides or consumes APIs, uses Resources, and may use a library (another Component).
- **Where it runs** adds environments. Every Component and Resource exists once per Environment as an Instance (Resource instance). Environments are ordered (`promotes to`), so each Instance knows the Instance its version was promoted from.
- **Work** connects changes to the model: a Spec changes the System or one Component, and the Run that ships it updates Instances, starting in dev.

A library has no Instances; other Components use it.

## An example: the todo system

![The todo system: parts on the left, one instance per environment on the right](img/model-example.svg)

Read the left column as "what the product is" and the grid as "where each part runs right now". A row is one part across environments; promoting moves a version one cell to the right. Versions and states in the picture are example values. The platform writes versions when it pins and promotes; health and smoke results are looked up when you ask (`/shared:status`), never stored.

## The delivery model

![Delivery model: issue, spec, criterion, test, plan, verification, run, pull request, image, release, attached to the core model](img/model-delivery.svg)

The documented SDLC (specs per [ADR-026](adr/026-feature-specs.md), [unattended delivery](unattended-delivery.md), the deploy gate, the feedback loops) attaches to the core model:

- Specs have the model's two levels. A **system spec** (today `/app:spec`) is split by a **Plan** into **component specs** (`/svc:spec --from-plan`), and the plan is where an API contract is set (spec 110).
- A **Criterion** (`AC-<NNN>.<n>`) is traced by a **Test** in the component's repo and judged in the **Verification**. A `(smoke)` criterion is checked on an Instance in an Environment, not in a repo.
- A **Run** ships a spec: it opens a **Pull request**, CI builds an **Image** (`sha-<40>` and its digest), the image is pinned in dev and promoted as an Instance, and a **Release** tag goes to prod with the digest staging verified.
- Every feedback loop ends as an **Issue** about a model object: a firing alert or a smoke failure is about an Instance; a platform failure or a retro proposal is about the platform.

Following the arrows from Issue to Instance is the evidence chain of spec 109.

## Lifecycles

![Lifecycles of a spec, a run and a version](img/model-lifecycles.svg)

Thick borders are where you decide: approving a spec, an escalation, promoting to prod. Everything else runs unattended. The run's `deploy` phase takes a version from "dev pinned" to "dev verified"; `staging` covers the automatic staging promotion. A smoke that did not run is `NOT VERIFIED` and promotes nothing.

## The nouns

| Noun | What it means | Example | Today |
|---|---|---|---|
| System | A product: everything below, delivered together | todo | product, app, gitops-app repo |
| Component | Something you build, in its own repo: a service, a website or a library | todo-api | service, shape |
| API | What a component offers others, and who uses it | todo-api REST | plan `## Contract` (prose) |
| Resource | Something you use but don't build; the platform runs it | postgres | addon |
| Owner | Who is responsible for the system and its parts | team-todo | not modelled |
| Environment | A stage the system passes through, with its own rules for getting in | staging | env key in several files |
| Instance | One component running in one environment, at one version | todo-api in staging | pin, overlay, Argo app |
| Resource instance | One resource in one environment | the staging database | `addons/<env>/<addon>/` |
| Issue | Something to look at: a request, a failure, an alert, a proposal | alert in todo-api/prod | GitHub issue |
| Spec | What should change in a system or a component, with numbered criteria | spec 110 | product spec, spec |
| Plan | How a system spec is split across its components, with the contract between them | `docs/plan/110.md` | plan, design |
| Run | An agent shipping a spec or a fix, within a budget | ship of spec 110 | run, ship |
| Release | A tagged version of a component that may go to prod | todo-api 1.4.0 | release, tag |

Test, Verification, Pull request and Image are evidence you can look at; they need no commands of their own.

Three placements are decided ([ADR-053](adr/053-domain-model.md)):

- **Observability** (the OpenTelemetry collector, alert rules, the UI) is a property of an Environment, not a Resource: every component in the environment gets it.
- **Secrets** are declared on the Component (generated or read from the store) and can be overridden per Instance; their values are set per Instance.
- **Names in the cluster do not change**: the namespace `<system>-<env>`, the Argo application `<component>-<env>`, the database Secret `<system>-postgres-app`. The model maps onto them.

## One file per system (5.0)

In 5.0, `system.yaml` replaces `app.yaml` and `services.yaml`. Each environment's rules live in one place; versions are not in the file, the platform writes them when it pins and promotes. A sketch, not the final schema (spec 114 fixes it):

```yaml
system: todo
owner: team-todo

environments:                  # in promotion order
  dev:     {host: "{component}.todo-dev.localhost", policy: audit, observability: {ui: lgtm}}
  staging: {promote: after-dev-smoke, policy: audit}
  prod:    {promote: manual, policy: enforce}

components:
  todo-api:
    type: service
    lang: python
    provides: [todo-api-rest]
    uses: [postgres]
    secrets: [{name: api-keys, remote: {keys: [STRIPE_KEY]}}]
    instances: {prod: {replicas: 2}}
  todo-web:
    type: website
    lang: typescript
    consumes: [todo-api-rest]
    expose: true

apis:
  todo-api-rest: {type: openapi}

resources:
  postgres:
    type: database
    version: 17
    instances: {prod: {size: 3, storage: 20Gi}}
```

## Commands follow the nouns (5.0)

Every command names the thing it acts on; the same verbs work for a system and for a component.

| Noun | Verbs |
|---|---|
| `system` | `new` · `status` · `spec` · `plan` · `ship` |
| `component` | `new` · `add` · `set` · `remove` · `spec` · `plan` · `build` · `verify` · `ship` · `fix` · `release` |
| `api` | `list` · `check` |
| `resource` | `add` · `remove` |
| `instance` | `promote <component> --to <env>` · `secret set <component>/<env>` · `verify` |
| `issue` | `triage` · `report` |
| `platform` | `doctor` · `update` · `fleet` · `runs` · `retro` |

## Today's features on the model

| Layer | Feature today | Acts on | In 5.0 |
|---|---|---|---|
| What it is | `/shared:new-app` | System and its components | `system new` |
| | `/shared:new-service` | Component (a System with `--gitops`) | `component new` |
| | `/gitops:compose` | Component in a System | `component add \| set \| remove` |
| | `/gitops:addon add postgres` | Resource | `resource add` |
| | `/gitops:addon add observability` | Environment property | `environments:` in system.yaml |
| | spec 110 contract check | API | `api check` |
| Where it runs | `/gitops:promote`, digest check (spec 106) | Instance, next Environment; Release for prod | `instance promote --to` |
| | `/gitops:secret` | Instance | `instance secret` |
| | `/shared:status` | every Instance of a System | `system status` |
| | `cplat smoke`, deploy gate (spec 105) | Instance | `instance verify` |
| | `promotion:` (spec 093), Kyverno policies | Environment rules | `environments:` in system.yaml |
| Delivery | `/shared:triage`, `/shared:report-issue` | Issue | `issue triage \| report` |
| | `/app:spec`, `/svc:spec` | Spec of a System or a Component | `system spec`, `component spec` |
| | `/app:plan`, `/svc:plan` | Plan | `system plan`, `component plan` |
| | `/svc:build`, `/svc:verify` | Criterion, Test, Verification | `component build \| verify` |
| | `/svc:ship`, `/app:ship`, budgets (spec 102) | Run | `component ship`, `system ship` |
| | `/svc:quick-task`, `/svc:fix-bug` | Run without a spec | `component fix` |
| | `/svc:release` | Release | `component release` |
| Feedback | run records, agent metrics, weekly retro | Runs as data; proposals as Issues | `platform runs \| retro` |
| | alert poll (spec 092), smoke failures (spec 091) | Instance → Issue | automatic |
| Platform | `/shared:doctor`, `/shared:update-service`, `/shared:fleet` | your setup, repo skeletons | `platform doctor \| update \| fleet` |

## The model today

![The domain model as built in 4.7.0](img/model-today.svg)

As built in 4.7.0, in the platform's own names:

- **Composition is solid.** Product, Service, Shape, Repo, Addon and Secret each have a file, a schema and an identity. The work there is naming, not structure.
- **Names drift in four places:** product, app and application for one thing; service in `services.yaml` but component in the `/shared:new-app` manifest; addon and backing service; pin and image tag.
- **Environment is the gap.** It is the axis every delivery command works on (pin, promote, smoke, status, alerts), yet `ENVS = dev, staging, prod` is hard-coded in `render.py` and an environment's settings are spread over `hosts`, `urls`, `policies` and `promotion` in `app.yaml`, per-environment maps in `services.yaml` and the overlay paths. Service × environment and addon × environment have no names.
- **Three relations are missing:** which services use a library, which services provide or consume an API (only prose in the plan), and who owns what.

| Concept today | Names in use | Defined in | Model noun |
|---|---|---|---|
| Product | product, app, application | gitops-app repo, `app.yaml`; `app:` in the new-app manifest | System |
| Service | service; component in the new-app manifest | `services.yaml` entry, generated or `external:` | Component |
| Shape | shape | `shapes.yml`, `.copier-answers.yml` | Component `type` + `lang` |
| Library | library | a `library-python` repo | Component, type library |
| Addon | addon, backing service | `app.yaml addons:`, `uses:` | Resource (postgres) or Environment property (observability) |
| Secret | secrets, secretRefs | `services.yaml`, External Secrets | Component config, per Instance |
| Environment | env, environment | `ENVS` in `render.py`; keys in `app.yaml`, `services.yaml`, overlays | Environment |
| Pin | pin, image tag | `overlays/<env>/<svc>/kustomization.yaml` | Instance version |
| Addon instance | (no name) | `addons/<env>/<addon>/` | Resource instance |
| Contract | contract | plan `## Contract`, prose | API |
