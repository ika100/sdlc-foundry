# ADR-053: A domain model based on Backstage's system model, with environments

**Status:** Accepted (2026-10-26)
**Builds on:** [ADR-014](014-gitops-app-composition-spec.md) (composition), [ADR-017](017-gitops-owns-manifests.md) (the gitops-app owns manifests), [ADR-020](020-addons-contract.md) (addons), [ADR-026](026-feature-specs.md) (specs)

## Context

The platform has grown its nouns one feature at a time. One product is called product, app and application; a deployable is a service in `services.yaml` but a component in the new-app manifest; postgres and the OpenTelemetry collector are both addons although only one is something a service uses. The environment, the axis every delivery command works on (pin, promote, smoke, status, alerts), has no entity at all: `ENVS` is a list in `render.py`, and an environment's settings are spread over four keys in `app.yaml`, maps in `services.yaml` and the overlay paths. `status`, `promote`, `pin` and `smoke` each work out "this service in that environment" on their own. APIs between components exist only as prose in a plan, and nothing records ownership. Users find the model hard to follow (the review that led to this ADR, see [DOMAIN-MODEL](../DOMAIN-MODEL.md#the-model-today)).

## Options

1. **Keep the names, document a glossary.** Cheap, but the interface keeps contradicting the model (`new-service --gitops` creates a product; `promote x dev staging` restates what the order already says).
2. **Adopt Backstage itself** (catalog, portal). Out of scope by [ARCHITECTURE](../ARCHITECTURE.md#what-this-is-not): no portal, git stays the only store.
3. **Adopt Backstage's system model as the vocabulary, extended by environments, and make the platform speak it (chosen).**
4. **A new platform built around the model.** Rejected: the model changes the interface, not the delivery core (merge on green without branch protection, the deploy gate, digest rules, budgets, run records), which a rewrite would have to relearn.

## Decision

1. **Nouns.** What it is: System, Component (type service, website or library), API, Resource, Owner, as in Backstage's system model, without Domain, Group/User or Location. Where it runs: Environment, Instance (one component in one environment), Resource instance. How it changes: Issue, Spec, Plan, Run, Release. Test, Verification, Pull request and Image are evidence, not nouns with commands. [DOMAIN-MODEL](../DOMAIN-MODEL.md) is the reference.
2. **Relations.** Component, API and Resource are part of a System; a Component provides and consumes APIs, uses Resources and libraries; an Instance is an instance of a Component and runs in an Environment; Environments are ordered and an Instance is promoted from the Instance before it; a Spec targets a System or a Component, a Plan splits a system spec into component specs and sets the API contract, a Run ships a Spec.
3. **Placements.** Observability is an Environment property, not a Resource. Secrets are declared on the Component and can be overridden per Instance; values are set per Instance. A library has no Instances.
4. **Declared and observed state stay apart.** Declared state (pinned image, replicas, sizing, rules) comes from git. Observed state (running image and digest, Argo sync and health, smoke result, firing alerts) is computed when asked and never written back to git.
5. **Cluster names do not change.** Namespace `<system>-<env>`, Argo applications `<component>-<env>` and `addon-<addon>-<env>`, the Secret `<system>-postgres-app`, the `app.kubernetes.io/part-of` label. The model maps onto them; renaming them would recreate applications and, for postgres, start an empty database.
6. **Two steps.** First an internal model in `cplat` (spec 113, a 4.x minor): one module loads the current files into these nouns, and the commands that work on a component in an environment use it; no command, flag or file changes. Then the user-facing switch (spec 114, release 5.0): `system.yaml` replaces `app.yaml` and `services.yaml`, commands are grouped by noun, a migration converts existing repos, and `/shared:fleet` rolls it out. Per [CLAUDE.md](../../CLAUDE.md) there are no aliases for the old commands; an old command name fails with the new one in its message.
7. **The platform keeps its name and its repo.** Only the major version changes.

## Consequences

- One vocabulary for docs, agent prompts and commands; the evidence chain of spec 109 becomes a path through the model, and spec 110's contract becomes an API entity.
- Commands that each computed service × environment share one tested module, so a rule such as "prod runs the digest staging verified" (spec 106) is a check on two Instances.
- 5.0 is a breaking release: every gitops-app and component repo needs the migration, and history (specs, ADRs, run records) keeps the old terms. [DOMAIN-MODEL](../DOMAIN-MODEL.md) maps old names to new.
- Backstage stays optional: entities can later be generated from `system.yaml` for a Backstage catalog, but nothing depends on it.
