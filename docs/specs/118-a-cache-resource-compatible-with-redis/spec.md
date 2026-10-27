---
spec_id: 118-a-cache-resource-compatible-with-redis
title: A cache resource compatible with Redis
status: building
priority: P1
---

# 118 — A cache resource compatible with Redis

## Problem

Almost every web product needs a fast key-value store for sessions, rate limits, short-lived results or a simple job queue. Today a system can declare only a `postgres` database (spec 114), so teams either misuse the database for that work, or run a Redis themselves outside the system and handle its address and password by hand in every environment. Spec 115 makes resources named, typed and optionally external; this spec adds the second resource type, `cache`. It speaks the Redis protocol so every Redis client library works, and it runs Valkey because Valkey keeps a BSD licence while Redis 8 is offered only under AGPLv3, RSAL or SSPL. Users will ask for "redis"; the platform calls the type `cache` and answers them in those words.

## Stories

- As a developer, I want to add a Redis-compatible cache to my system with one command and get `REDIS_URL` in my component, so that I can use any Redis client without running or wiring a server myself.
- As a product owner, I want to size the cache per environment (memory, eviction, whether it survives a restart), so that dev stays cheap and prod behaves as the product needs.
- As an operator, I want a cache in staging or prod to be a managed service (ElastiCache, Memorystore, Upstash) while dev runs in the cluster, so that components see the same variables everywhere.
- As the author of the scaling spec (120), I want the cache's address and password in a Secret with a stable name and stable keys, so that a scaler can read a list length without the component's help.

## Acceptance criteria

### Declaring and running a cache

- **AC-118.1** Given a gitops-app repo on 5.0 with spec 115, when `/resource:add <name> --type cache` runs, then `resources.<name>` with `type: cache` is added to `system.yaml` and rendered in one PR as other resources are (spec 115); the entry carries no explicit sizing, so the defaults of AC-118.3 apply.
- **AC-118.2** Given a resource of `type: cache`, when it is rendered, then its allowed keys are `version`, `memory`, `maxmemoryPolicy`, `persistence`, `storage` and `instances.<env>` (overriding `memory`, `maxmemoryPolicy`, `persistence` and `storage`) plus the external keys of spec 115; any other key fails naming the resource, the key and the allowed keys.
- **AC-118.3** Given a cache resource without sizing keys, when it is rendered, then each of its instances runs Valkey of the default major version as one node, with a memory limit of `256Mi`, `maxmemoryPolicy: allkeys-lru` and `persistence: false`.
- **AC-118.4** Given a cache resource, when it is rendered, then a `version` that is not a supported Valkey major (`8` or `9`), a `memory` that is not a Kubernetes quantity, a `maxmemoryPolicy` outside `noeviction`, `allkeys-lru`, `allkeys-lfu`, `allkeys-random`, `volatile-lru`, `volatile-lfu`, `volatile-random` and `volatile-ttl`, a non-boolean `persistence`, or a `storage` with `persistence: false` fails naming the resource, the key and the allowed values; nothing is written.
- **AC-118.5** Given a cache resource with `type: redis` or `type: valkey`, when it is rendered, then it fails with "the type is `cache` (Redis-compatible, runs Valkey)" and nothing is written.
- **AC-118.6** Given a cache instance with `memory: M`, when it runs, then its container memory limit is M, the server reports `maxmemory` as 80 % of M and the configured `maxmemory-policy`; with `allkeys-lru`, writing past `maxmemory` evicts keys and the server is not killed for lack of memory, and with `noeviction` such a write is answered with an out-of-memory error to the client.
- **AC-118.7** Given a cache instance with `persistence: false`, when its pod is deleted and comes back, then it has no volume and starts empty; given `persistence: true` (with `storage`, default `1Gi`), then keys written at least one second before the pod was deleted are present after it is back.
- **AC-118.8** Given a cache instance, when anything outside the cluster tries to reach it, then it is not reachable: the render creates no route, no `LoadBalancer` and no `NodePort` for it, and inside the cluster it serves on the Redis port `6379`.

### The connection contract

- ~~**AC-118.9**~~ withdrawn 2026-10-26: the resource Secret is named `<system>-<name>-app` and the prefix rule of spec 115 is settled; replaced by AC-118.18.
- ~~**AC-118.10**~~ withdrawn 2026-10-26: Secret renamed to `<system>-<name>-app`; replaced by AC-118.19.
- **AC-118.11** Given a running cache instance, when a client connects without a password or with a wrong one, then every command except `AUTH` and `HELLO` is refused (`NOAUTH` or `WRONGPASS`); with the password from the Secret, `PING` answers `PONG`.
- ~~**AC-118.12**~~ withdrawn 2026-10-26: Secret renamed to `<system>-<name>-app`; replaced by AC-118.20.
- **AC-118.18** Given a component whose `uses` lists one cache resource `<name>`, when it is rendered in an environment, then the component gets `REDIS_URL` (`redis://:<password>@<host>:6379/0`), `REDIS_HOST`, `REDIS_PORT` and `REDIS_PASSWORD`, each read with `secretKeyRef` from the keys `url`, `host`, `port` and `password` of the Secret `<system>-<name>-app` in that environment's namespace; given a component that uses two or more cache resources, then every one of them gets the four variables prefixed with `<NAME>_` by the rule of spec 115 (for a resource `sessions`: `SESSIONS_REDIS_URL`, `SESSIONS_REDIS_HOST`, `SESSIONS_REDIS_PORT`, `SESSIONS_REDIS_PASSWORD`), and all components that use one cache share database `0` and one password.
- **AC-118.19** Given a cache instance, when the Secret `<system>-<name>-app` is created, then its password is generated (32 characters) and never appears in git, and later renders, syncs, restarts and upgrades of the cache keep the same Secret name, keys and password.
- **AC-118.20** Given a cache resource marked external in an environment with the mechanism of spec 115, when it is rendered, then no Valkey runs in that environment, the Secret `<system>-<name>-app` is filled from the secret store keys `url`, `host`, `port` and `password` of that resource (the same keys as the in-cluster Secret), and the component gets the same variables as in AC-118.18; a `url` starting with `rediss://` (TLS, as ElastiCache, Memorystore and Upstash use) is passed unchanged.
- **AC-118.13** Given `/resource:remove <name>` for a cache resource that a component still uses, when it runs, then it changes nothing and fails naming the components that use it.

### Backups, docs and the local cluster

- **AC-118.14** Given a system with a cache resource and the backups of spec 117, when the backup schedules are rendered, then no cache instance (with or without `persistence`) is part of any backup, and the resource docs say that cache data is not backed up.
- **AC-118.15** Given the local cluster from `cluster-up` with nothing installed beyond the platform's prerequisites, when the end-to-end test deploys a system with a cache resource and a component that uses it to dev, then the component SETs a key and GETs the same value back through `REDIS_URL`, and `/platform:doctor` reports no missing prerequisite for the cache.
- ~~**AC-118.16**~~ withdrawn 2026-10-26: Secret renamed to `<system>-<name>-app`; replaced by AC-118.21.
- **AC-118.21** Given `docs/DOMAIN-MODEL.md` and the resource docs after this spec is built, when they are read, then they list `cache` as a resource type that speaks the Redis protocol and runs Valkey (with the licence reason), its keys and defaults, the four variables and their `<NAME>_` prefix rule, the Secret `<system>-<name>-app` and its keys as the contract other specs (such as 120) may rely on, and that the type is not called `redis`.

### Place in 5.x

- **AC-118.22** Given spec 114 as approved, when this spec is built, then it is an additive 5.x extension of the closed list of resource types in AC-114.19 (as opened by spec 115) and of the `/resource:add` types of AC-114.36: `cache` is accepted there, every other type and message of those criteria is unchanged, and no criterion of spec 114 is amended.
- **AC-118.23** Given a cache instance in any environment, when it runs, then it is one Valkey StatefulSet rendered by the platform from the official Valkey image whose exact release is listed in the versions table of spec 121, with no operator, CRD or Helm chart; `environments.<env>.operators: owner` changes nothing for a cache, and `/platform:doctor` reports no prerequisite for it on any cluster.

### Upgrades

- **AC-118.17** Given a cache resource with `version: N`, when it is rendered, then its instances run one exact Valkey release of major N pinned by the platform (no floating tag such as `9` or `latest`); a change of `version`, or of the pinned release by a platform update, is rolled out under the upgrade rules of spec 121 (through the environments in order, a downgrade refused), and the fresh-backup precondition of spec 121 for a major upgrade does not apply to a cache, because cache data is not backed up (AC-118.14).

## Non-goals

- High availability: replicas, Sentinel, cluster mode or sharding. One node per environment.
- Running Redis itself, or offering a choice between Redis and Valkey.
- Backups or restores of cache data, and copying cache data between environments.
- Per-component isolation inside one cache (separate users, ACLs or database numbers); every component that uses a cache shares database `0`.
- TLS between components and an in-cluster cache; password rotation.
- Valkey modules (search, JSON, Bloom) and server settings beyond those of AC-118.2.
- Exposing a cache outside the cluster.
- Off-the-shelf components (for example a Redis admin UI) as part of this series.
- Scaling a component on a cache metric: that is spec 120.
- The upgrade procedure for resource versions: that is spec 121.

## Open questions

- ~~How does a cache instance run?~~ Answered: a single-node Valkey StatefulSet rendered by the platform from the official image, no operator or chart. See AC-118.3 and AC-118.23.
- ~~Which variables does a using component get?~~ Answered: `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, prefixed `<NAME>_` by spec 115's rule when a component uses two or more caches. See AC-118.18.
- ~~Confirm the Secret name.~~ Answered: one rule for every resource type, `<system>-<name>-app`, keys `url`, `host`, `port`, `password`. See AC-118.18, AC-118.19, AC-118.20 and AC-118.21.
- ~~Confirm the defaults.~~ Answered: yes (one node, `256Mi`, `allkeys-lru`, persistence off, `1Gi` when on, `maxmemory` 80 %). See AC-118.3, AC-118.6 and AC-118.7.
- ~~Which Valkey versions are supported?~~ Answered: majors `8` and `9`, default `9`. See AC-118.4 and AC-118.17.
- ~~How does `persistence: true` persist?~~ Answered: append-only file synced every second. See AC-118.7.
- ~~Should `type: redis` be an alias?~~ Answered: no, an error naming `cache`. See AC-118.5.
- ~~Confirm: components share one cache.~~ Answered: yes, database `0` and one password. See AC-118.18 and Non-goals.

## Changelog

- 2026-10-26 created
- 2026-10-26 open questions answered: Secret `<system>-<name>-app` (AC-118.9, .10, .12, .16 withdrawn, replaced by AC-118.18 to .21), `<NAME>_` prefix rule of spec 115, extension of AC-114.19 and AC-114.36 (AC-118.22), no operator and image pinned in spec 121's table (AC-118.23)
- 2026-10-26 approved
- 2026-10-27 building
