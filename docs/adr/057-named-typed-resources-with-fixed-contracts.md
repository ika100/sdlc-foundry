# ADR-057: Resources are named and typed; each type has a fixed contract; any resource instance may be external

**Status:** Accepted (2026-10-26)
**Builds on:** [ADR-018](018-secrets-with-external-secrets-operator.md) (secrets from External Secrets Operator), [ADR-020](020-addons-contract.md) (the addon contract), [ADR-053](053-domain-model.md) (domain model), [ADR-054](054-five-zero-interface-and-proved-migration.md) (5.0 interface), spec 115

## Context

5.0 knows one resource, a database named `postgres`. Systems need several databases (one per owning component), and the next specs of the 5.x series add object storage, a cache and a message broker (specs 116, 118, 119). Some teams run a resource outside the cluster in some environments (a managed prod database). Components must not change between those cases, and the cluster names of 5.0 must not move.

## Decision

1. **A resource is `resources.<name>` with a required `type`**: `database`, `bucket`, `cache` or `broker`. The name is a lowercase label of at most 30 characters that no component of the system uses. A type that no release runs yet is refused with the spec that brings it.
2. **Each type has one fixed contract**: a list of Secret keys and the environment variables a using component gets from them. The contract is the same whether the platform runs the resource or not. For `database` the keys are `uri`, `host`, `port`, `dbname`, `user`, `password`, and the variables `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`. Later types add their own row; a row never changes once released.
3. **One naming rule for every type**: the connection Secret is `<system>-<name>-app`, an in-cluster instance's Argo application is `addon-<name>-<env>`. `postgres` keeps its 5.0 names. A resource keeps these names as long as it keeps its name.
4. **Two resources of one type in one component get a prefix**: when a component uses two or more resources of one type, every variable of that type is injected once per resource as `<NAME>_<VAR>` (`<NAME>` = the resource name upper-cased, `-` → `_`), and none unprefixed. A component that uses one resource of a type keeps the bare names.
5. **External is a per-environment property of a resource instance**: `external: true` on the resource (default for all environments) or on `instances.<env>` (that environment only). An external instance runs nothing: no operator object and no Argo application. The contract's keys are synced from the system's `secretStore` into the same Secret `<system>-<name>-app` by one ExternalSecret that has one `data` entry per key, so a missing key fails the sync and no partial Secret is written. The store path is `remote.path` (placeholders `{system}`, `{env}`, `{resource}`), default `{system}-{env}-{resource}`.
6. **The ExternalSecret lives in one component overlay per environment**: the alphabetically first running component that uses the resource there. It uses `creationPolicy: Orphan` so that a change of that component never deletes the Secret the other users read.

## Consequences

- Specs 116, 118 and 119 add a contract row and what the platform runs for their type. The naming, prefix and external rules apply to them unchanged.
- Adding a second database to a component renames its variables (the prefix rule). The `/component:set --uses` report says so, and the code has to read the new names.
- Moving an instance between in-cluster and external keeps the Secret name and the variable names. The data does not move; that is the owner's job.
- Removing a resource removes its declarations. The data, and the Secret of an external instance, stay in the cluster.

## Not included

Provisioning external resources, setting their store values through `/instance:secret`, moving data, and the upgrade procedure (spec 121).
