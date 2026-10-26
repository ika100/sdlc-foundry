---
spec_id: 115-resources-are-named-typed-and-may-be
title: Resources are named, typed and may be external
status: draft
priority: P1
---

# 115 — Resources are named, typed and may be external

## Problem

In 5.0 (spec 114) a system can have exactly one resource, a database named `postgres`. A system whose components each own their data (orders, users) has to share that one database, and a team that runs its production database outside the cluster (a managed database service) cannot say so: the platform always runs the database itself, in every environment. The resources the series brings next (object storage, cache, message broker in specs 116, 118 and 119) cannot be declared at all. This spec is the foundation for them: a resource gets a name of its own and a type, each type gives the components that use it a fixed set of environment variables, and any resource instance may be external, so the platform runs nothing and the components read the same variables from the secret store. It ships as a 5.x minor release; every 5.0 `system.yaml` keeps rendering as before (only the database image becomes exactly pinned).

Spec 114 stays as approved. This spec adds to the closed lists of 114 without amending it: the resource names and types of AC-114.19 (one `postgres` database becomes any number of named, typed resources), the variables `uses` injects in AC-114.15, the environment keys of AC-114.4 (adds `operators`), the arguments of `/resource:add|remove` in AC-114.36, and the resource fields of `cplat model show` in AC-114.69. The top-level keys of AC-114.2 do not change.

## Stories

- As a product owner, I want to declare `orders-db` and `users-db` as two databases of my system, so that each component owns its data without sharing one database.
- As a developer, I want a component that uses a resource to get the same environment variables whether the platform runs the resource or it is external, so that my code does not change between dev and prod.
- As an operator, I want the prod database to be a managed database outside the cluster while dev and staging run in it, so that prod gets the provider's backups and availability without changing dev.
- As the owner of a 5.0 system, I want my existing `resources.postgres` to keep its cluster names and render byte-identically, so that the upgrade moves or recreates nothing.
- As a user, I want a clear message when I declare a resource type the platform does not run yet, so that I know which spec brings it.

## Acceptance criteria

### Names and types

- **AC-115.1** Given an entry under `resources:`, when `system.yaml` is rendered, then `type` is required and must be `database`, `bucket`, `cache` or `broker`; a missing `type` fails naming the resource and the four types, and any other value fails naming the resource, the value and the four types.
- **AC-115.2** Given a resource of type `bucket`, `cache` or `broker` in a release that does not yet run that type, when it is rendered or added with `/resource:add`, then it writes nothing and fails with one line naming the type and the spec that brings it (`bucket`: spec 116, `cache`: spec 118, `broker`: spec 119).
- **AC-115.3** Given a resource name, when it is rendered, then it must start with a lowercase letter, contain only lowercase letters, digits and hyphens, and be at most 30 characters long; a resource with the same name as a component fails naming both, and a resource named `observability` still fails pointing to `environments.<env>.observability` (AC-114.19).
- **AC-115.4** Given two or more resources of type `database` (for example `orders-db` and `users-db`), each with `version`, `replicas`, `storage`, `resources` and `instances.<env>` overrides, when they are rendered, then every environment where a running component uses a database gets one CloudNativePG cluster per used database, with that database's own values; changing one database's values changes no manifest of another.
- **AC-115.5** Given a resource `<name>` of any type, in-cluster or external, when it is rendered, then its connection Secret is `<system>-<name>-app` (so `postgres` keeps `<system>-postgres-app`) and an in-cluster resource instance's Argo application is `addon-<name>-<env>` (so `postgres` keeps `addon-postgres-<env>`); these names never change while the resource keeps its name, and no two resources of a system share a cluster object name.
- **AC-115.6** Given any `system.yaml` that 5.0 accepts (including `resources.postgres` of `type: database`), when this release renders it, then the rendered tree is byte-identical to the 5.0 render except the database image reference, which AC-115.17 pins; and `cplat platform update --migrate` on a 4.7 repo writes the same `system.yaml` and the same rendered tree as 5.0 did.

### What a using component gets

- **AC-115.7** Given a component that uses exactly one resource of type `database`, whatever its name, when it is rendered, then the component gets `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and `PGPASSWORD` from that database's Secret (keys `uri`, `host`, `port`, `dbname`, `user`, `password`), exactly as 5.0 injects them for `postgres`.
- **AC-115.8** Given a component that uses two or more resources of the same type (for example `orders-db` and `users-db`), when it is rendered, then each of that type's variables is injected once per resource with the prefix `<NAME>_`, where `<NAME>` is the resource name upper-cased with `-` replaced by `_` (`ORDERS_DB_DATABASE_URL`, `USERS_DB_PGHOST`), no unprefixed variable of that type is injected, and resources of other types used by the same component keep their unprefixed names.

### External resources

- **AC-115.9** Given a resource with `external: true` and `remote` (optional `path` with the placeholders `{system}`, `{env}` and `{resource}`, default `{system}-{env}-{resource}`, and optional `refreshInterval`), when it is rendered, then no CloudNativePG cluster and no Argo application exist for it in any environment, and every environment where a running component uses it gets the Secret `<system>-<name>-app` synced from the system's `secretStore` with the keys of the type's contract (database: `uri`, `host`, `port`, `dbname`, `user`, `password`); the using component gets the same variables as in AC-115.7 and AC-115.8.
- **AC-115.10** Given a resource with `instances.<env>.external` (`true` or `false`, optionally with `instances.<env>.remote`), when it is rendered, then that value overrides the resource's `external` in that environment only: with the database in-cluster and `instances.prod.external: true`, dev and staging get the CloudNativePG cluster and prod gets only the synced Secret, and the using component's variable names are the same in all three environments.
- **AC-115.11** Given an external resource instance, when it is rendered, then it fails naming the resource, the environment and the key if: the system has no `secretStore` (naming `secretStore`); the instance sets `version`, `replicas`, `storage` or `resources`, or the resource sets them at the top level while every instance is external (saying "an external resource runs nothing"); and given `remote` on a resource or instance that is not external, or an `external` that is not `true` or `false`, then it fails naming the resource and the key.
- **AC-115.12** Given an external resource instance whose store entry lacks one of the contract's keys, when it is synced in the cluster, then the Secret `<system>-<name>-app` is not created with partial values, the sync status names the missing key, and the using component's instance does not become healthy.

### Versions

- **AC-115.17** Given a database resource with `version: N`, when it is rendered, then the CloudNativePG cluster runs an image the platform pins to an exact version (a full patch version or a digest, never a major-only or floating tag such as `postgresql:17`), and the operator and chart versions it relies on are pinned exactly per platform release; changing `version` or any of these pins follows the upgrade rules of spec 121, and an existing 5.0 cluster moves from its major-only tag to the pinned image under those same rules.
- **AC-115.18** Given a system with at least one in-cluster database resource instance, when it is rendered for a cluster, then that cluster gets the CloudNativePG operator as an Argo CD application pinned to the version of spec 121's versions table, once per cluster; a cluster on which no environment of the system has an in-cluster database gets no operator application. Given `environments.<env>.operators: owner`, then the platform installs and upgrades no operator for that environment, and `/platform:doctor` lists, per operator the environment needs, the installed and the expected version and warns when one is missing or differs; any value of `operators` other than `owner` fails naming the environment and `owner`.

### Commands and the model

- **AC-115.13** Given `/resource:add <name> --type database [--version N] [--external [--path <path>]]`, when it runs, then it adds `resources.<name>` and renders in one PR as 5.0 `/resource:add postgres` did; `/resource:add postgres` without `--type` still adds a database; another name without `--type` fails listing the four types; a name that already exists, an invalid name (AC-115.3) or a type of AC-115.2 changes nothing and fails naming the reason.
- **AC-115.14** Given `/resource:remove <name>` for a resource that one or more components use, when it runs, then it changes nothing, exits 1 and names every component using it; for an unused resource it removes the entry and its resource instances in one PR with the same data handling as 5.0 `/resource:remove postgres`; an unknown name fails listing the system's resources.
- **AC-115.15** Given a system with named, typed and external resources, when `cplat model show` runs, then it lists each resource with its name, type and `external` flag, and each resource instance with its environment, type, `external` flag, Secret name and (in-cluster only) Argo application; `--json` keeps `schema` 2 and adds these fields, and the renderer-model check of AC-114.70 also compares the resource instances, their type and their `external` flag.
- **AC-115.16** Given this release, when it is published, then `docs/DOMAIN-MODEL.md` documents `resources.<name>` with `type`, the four types with the spec that brings each, `external` with `remote` and the per-instance override, and the prefix rule of AC-115.8 with an example; `docs/CHANGELOG.md` lists the change in a minor-version section not marked BREAKING; and the changed plugins get a minor version bump in their manifest and the marketplace.

## Non-goals

- The resource types `bucket`, `cache` and `broker` themselves: their contracts and what the platform runs for them are specs 116, 118 and 119; this spec only reserves the type names.
- Backups of databases (spec 117) and scaling of instances (spec 120).
- The upgrade procedure for resource versions and pins (rollout order, backups before a major upgrade, refused downgrades): spec 121.
- Moving data when a resource instance switches between in-cluster and external, or between two databases.
- Creating or provisioning the external resource (the managed database, its users, network access); the platform only reads its connection details from the store.
- A `/resource:set` command or a command that lists resources; per-instance overrides are edited in `system.yaml`, and resources are listed by `cplat model show`.
- Renaming the cluster objects of the resource `postgres` (Secret, Argo application, CloudNativePG cluster).
- Off-the-shelf components (Node-RED and similar), for this whole series.
- Any change to the 4.x → 5.0 migration.
- Amending spec 114: this spec only adds to its closed lists.
- Setting an external resource's store values through `/instance:secret set`; they are set in the store directly.

## Open questions

- ~~How do the variables of a component that uses two resources of the same type get distinct names?~~ Answered: an automatic `<NAME>_` prefix for every resource of that type once there are two or more. See AC-115.8.
- ~~Which cluster names do databases other than `postgres` get?~~ Answered: Secret `<system>-<name>-app` for every resource type, Argo application `addon-<name>-<env>`; never changes. See AC-115.5.
- ~~Confirm: resource names are lowercase DNS-style, at most 30 characters, and may not equal a component name.~~ Answered: yes. See AC-115.3.
- ~~Which key names must the store entry of an external database hold?~~ Answered: the keys of the in-cluster Secret (`uri`, `host`, `port`, `dbname`, `user`, `password`). See AC-115.9 and AC-115.12.
- ~~Confirm: the default store path of an external resource is `{system}-{env}-{resource}`.~~ Answered: yes. See AC-115.9.
- ~~Should `/instance:secret set` set the store values of an external resource?~~ Answered: not in this spec. See Non-goals.
- ~~Confirm: no `/resource:set`.~~ Answered: yes, the override is edited in `system.yaml`. See Non-goals.
- ~~Confirm: `cplat model show --json` stays at `schema` 2 and only adds fields.~~ Answered: yes. See AC-115.15.
- ~~Accept the exact database image pin as the one difference from the 5.0 render?~~ Answered: yes; existing clusters move to the pinned image under spec 121. See AC-115.6 and AC-115.17.
- ~~Confirm: the message for a type not built yet names the spec, not a release version.~~ Answered: yes. See AC-115.2.
- ~~Who installs and upgrades the operators a resource needs?~~ Answered (series decision): the platform, as pinned Argo CD applications per cluster, only when needed; `environments.<env>.operators: owner` opts out and `/platform:doctor` compares versions. See AC-115.18.

## Changelog

- 2026-10-26 created
- 2026-10-26 amended: open questions answered as suggested; added exact version pins (AC-115.17) and operator installation with the `operators: owner` opt-out (AC-115.18); one Secret rule for all types (AC-115.5); named the AC-114 lists this spec extends
