# Domain model

The nouns the platform is built around: what a system is made of, where it runs, and how it changes. The model takes [Backstage's system model](https://backstage.io/docs/features/software-catalog/system-model) for the first part and adds environments and the delivery process. It is a model only: the platform does not use or need Backstage. Decisions and the migration path are in [ADR-053](adr/053-domain-model.md).

**Status:** 5.0 is current. `system.yaml` and the noun-based commands described below are what the platform runs (spec 114, [ADR-054](adr/054-five-zero-interface-and-proved-migration.md)); `cplat model show` prints a system in these nouns (JSON `schema: 2`). A repo from 4.x moves over with `cplat platform update --migrate` ([Migrating from 4.x to 5.0](ADOPTING.md#migrating-from-4x-to-50)). [The model in 4.7](#the-model-in-47) and [4.7 features on the model](#47-features-on-the-model) keep the old names as history.

## Three questions

| You ask | The model answers with |
|---|---|
| What is my product made of? | the **System** and its parts: **Components**, **APIs**, **Resources**, and its **Owner** |
| Where does it run, at which version? | **Environments** × parts: each cell is an **Instance** (or a **Resource instance**); the environments run on a **Cluster** that several systems share |
| How does it change? | an **Issue** becomes a **Spec**; a **Run** ships it; a **Release** goes to prod |

## The system model

![System model: what it is, where it runs, how it changes](img/model-system.svg)

Three layers:

- **What it is** is Backstage's system model, reduced to the kinds a user needs. An Owner owns a System; Components, APIs and Resources are part of it. A Component provides or consumes APIs, uses Resources, and may use a library (another Component).
- **Where it runs** adds environments and the cluster. Every Component and Resource exists once per Environment as an Instance (Resource instance). Environments are ordered (`promotes to`), so each Instance knows the Instance its version was promoted from. Every Environment runs on a Cluster; the Cluster hosts the System and runs the shared operators that manage its Resource instances (see [Cluster](#cluster)).
- **Work** connects changes to the model: a Spec changes the System or one Component, and the Run that ships it updates Instances, starting in dev.

A library has no Instances; other Components use it.

## An example: the todo system

![The todo system: parts on the left, one instance per environment on the right](img/model-example.svg)

Read the left column as "what the system is" and the grid as "where each part runs right now". A row is one part across environments; promoting moves a version one cell to the right. Versions and states in the picture are example values. The platform writes versions when it pins and promotes; health and smoke results are looked up when you ask (`/system:status`), never stored.

## The delivery model

![Delivery model: issue, spec, criterion, test, plan, verification, run, pull request, image, release, attached to the core model](img/model-delivery.svg)

The documented SDLC (specs per [ADR-026](adr/026-feature-specs.md), [unattended delivery](unattended-delivery.md), the deploy gate, the feedback loops) attaches to the core model:

- Specs have the model's two levels. A **system spec** (`/system:spec`) is split by a **Plan** into **component specs** (`/component:spec`), and the plan is where an API contract is set (spec 110).
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
| Resource | Something you use but don't build; named and typed, run by the platform or external | users-db (database) | addon |
| Cluster | The place systems run, with its shared operators, External Secrets with the secret store, the Kyverno engine and the list of its systems | home | cluster repo, `operators/` |
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
- **Names in the cluster do not change**: the namespace `<system>-<env>`, the Argo application `<component>-<env>`, every resource's Secret `<system>-<name>-app` (so `<system>-postgres-app` for a resource called `postgres`). The model maps onto them.

### Cluster

A Cluster is the place systems run. Its own repo (`cluster.yaml`, shape `cluster-gitops`) owns what several systems share: the operators (for example CloudNativePG), External Secrets with the secret store, and the Kyverno engine. The decision is [ADR-060](adr/060-a-cluster-repo-owns-shared-services.md); the steps are in [CLUSTERS.md](CLUSTERS.md).

Its relations to the rest of the model:

- **A Cluster hosts Systems.** `cluster.yaml` lists each system by its gitops repo, and the cluster repo renders one Argo application `system-<name>` per system (`/cluster:add`, `/cluster:remove`). A System is hosted by one Cluster; a cluster without a cluster repo hosts just the one system that installs its own operators.
- **An Environment runs on its System's Cluster.** All environments of a system run on the same cluster, each in its namespace `<system>-<env>`. Spreading one system's environments over several clusters is not modelled yet.
- **A Resource instance is managed by the Cluster's operators.** An in-cluster database instance is run by CloudNativePG, a bucket instance by the SeaweedFS operator, and an external resource's Secret is filled by External Secrets through the cluster's secret store. The cluster repo's check fails when a hosted system needs an operator that `cluster.yaml` does not list.
- **A System hands its operators to the Cluster** by setting `operators: owner` in every environment; it then no longer renders `operators/`. Kyverno policies stay with each System; only the engine is the Cluster's.
- **Components and their Instances do not know the Cluster.** Names in the cluster stay the same, so a system renders the same manifests whether it shares a cluster or has its own.

## One file per system

`system.yaml` is the only file you edit by hand in a system's GitOps repo (`applications/<system>/system.yaml`). Each environment's rules live in one place. Versions are never in the file: the platform writes them when it pins and promotes. `render.py` checks the file and refuses unknown keys with a message that names the key.

```yaml
system: todo
owner: team-todo

environments:                  # exactly dev, staging, prod, in promotion order
  dev:     {host: "{component}.todo-dev.localhost", policy: audit, observability: {ui: lgtm}}
  staging: {promote: after-dev-smoke, policy: audit}
  prod:    {promote: manual, policy: enforce}

components:
  todo-api:
    type: service
    lang: python
    repo: team-todo/todo-api
    provides: [todo-api-rest]
    uses: [postgres]
    secrets: [{name: api-keys, remote: {keys: [STRIPE_KEY]}}]
    instances:                 # the environments it runs in
      dev: {}
      staging: {}
      prod: {replicas: 2}
  todo-web:
    type: website
    lang: typescript
    repo: team-todo/todo-web
    consumes: [todo-api-rest]
    expose: true
    instances: {dev: {}, staging: {}, prod: {}}
  todo-lib: {type: library, lang: python, repo: team-todo/todo-lib}

apis:
  todo-api-rest: {type: openapi}

resources:
  postgres:
    type: database
    version: 17
    replicas: 1
    storage: 1Gi
    instances: {prod: {replicas: 3, storage: 20Gi}}
  users-db:
    type: database
    external: true            # the database lives outside the cluster
    remote: {path: "{system}-{env}-{resource}"}
```

### Keys

| Where | Allowed keys |
|---|---|
| top level | `system`, `owner` (required, non-empty), `environments`, `components`, `apis`, `resources`, `gateway`, `secretStore`, `registries`, `autonomy` (only `paused`) |
| `environments.<env>` | `host`, `url`, `policy`, `promote`, `observability`, `operators`, `backup`, `autonomy` |
| service or website component | `type`, `lang`, `repo`, `image`, `port`, `probes`, `user`, `volumes`, `env`, `secretRefs`, `secrets`, `replicas`, `resources`, `expose`, `metrics`, `provides`, `consumes`, `uses`, `instances` |
| external component | `type`, `lang`, `repo`, `image`, `external`, `provides`, `consumes`, `instances` (an instance sets only `promote` and `autonomy`) |
| library component | `type`, `lang`, `repo`, `provides`, `consumes` |
| `components.<c>.instances.<env>` | `replicas`, `resources`, `env`, `promote`, `secrets`, `autonomy` (only `max`) |
| `apis.<api>` | `type`: `openapi`, `grpc`, `graphql` or `events`; an events API also takes `broker` (`apis.<api>.broker`, the name of a broker resource) |
| `resources.<name>` | `type`, `external`, `remote`, `version`, `replicas`, `storage`, `resources`, `instances` |
| `resources.<name>.remote` | `path`, `refreshInterval`; on a bucket also `s3` (`endpoint`, `bucket`, `region`, `forcePathStyle`) |
| database `resources.<name>.instances.<env>` | `external`, `remote`, `replicas`, `storage`, `resources`, `backup` |
| `backup` (environment or database instance) | `to`, `schedule`, `retention` |
| bucket `resources.<name>` (`type: bucket`) | `type`, `external`, `remote`, `storage`, `versioning`, `instances` |
| bucket `resources.<name>.instances.<env>` | `external`, `remote`, `storage`, `versioning` |
| cache `resources.<name>` (`type: cache`) | `type`, `external`, `remote`, `version`, `memory`, `maxmemoryPolicy`, `persistence`, `storage`, `instances` |
| cache `resources.<name>.instances.<env>` | `external`, `remote`, `memory`, `maxmemoryPolicy`, `persistence`, `storage` |
| broker `resources.<name>` (`type: broker`) | `type`, `external`, `remote`, `version`, `replicas`, `storage`, `resources`, `instances` |
| broker `resources.<name>.instances.<env>` | `external`, `remote`, `replicas`, `storage`, `resources` |

Valid `type`/`lang` pairs: `service/python`, `service/java`, `service/go`, `website/typescript`, `library/python`, and `service/unknown` for a migrated component without a known shape.

### Semantics

- A component runs in exactly the environments that are keys of its `instances`; without `instances` it runs in dev only; a library has none. Instance `env` is merged over the component's (the instance wins); `replicas` and `resources` replace; instance `secrets` override the fields of the same-named declared secret in that environment only.
- `host` placeholders: `{component}`, `{system}`, `{env}`. `url` placeholders: `{host}`, `{component}`, `{system}`, `{env}`; a `url` is read by `instance verify` and ignored by the renderer.
- `policy` is `audit`, `enforce` or `off` (default `audit` in dev and staging, `enforce` in prod).
- `observability` on an environment gives that environment the collector and gives every instance there the `OTEL_*` variables.
- `backup` on an environment backs up its persistent volumes and objects (Velero); on a database instance it backs up that database with continuous archiving and point-in-time restore. `to` is a bucket resource with an instance in that environment, `schedule` a five-field UTC cron (default `0 3 * * *`), `retention` `<n>d` or `<n>w` (default `30d`); an external bucket as target declares `remote.s3`. Databases are restored only with `/resource:restore`. See [BACKUP-AND-RESTORE.md](BACKUP-AND-RESTORE.md) (spec 117).
- `promote`: `after-dev-smoke` or `manual` on staging (default `manual`), only `manual` on prod, none on dev. An instance value wins over the environment's.
- `resources.<name>` declares any number of named, typed resources. `type` is required in `system.yaml`, `postgres` included (`/resource:add postgres` fills in `type: database` when `--type` is left out). The types are `database`, `bucket`, `cache` and `broker` (all rendered; the bucket is spec 116, the cache spec 118, the broker spec 119). A resource is rendered in every environment where a running component uses it. Database instances take `replicas` (default 1), `storage` (default `1Gi`) and `version` (default 17; the supported majors are 15, 16, 17 and 18), with per-environment overrides under `instances.<env>`. The Argo application is `addon-<name>-<env>` and the Secret is `<system>-<name>-app`.
- `type: bucket` is an S3-compatible object store for files and backups (spec 116). It takes `storage` (default `10Gi`) and `versioning` (default `false`; `true` keeps earlier versions of an overwritten object, `false` renders the S3 state `Suspended`), at the resource level or per instance under `instances.<env>`. For an in-cluster bucket the name `<system>-<name>` is the bucket name and may be at most 45 characters. Each bucket instance runs its own SeaweedFS, managed by the SeaweedFS operator that the platform installs from `operators/`. The component gets eight variables from the Secret `<system>-<name>-app` (keys `endpoint`, `bucket`, `region`, `forcePathStyle`, `accessKeyId`, `secretAccessKey`): `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION`, `S3_FORCE_PATH_STYLE` (`true` in-cluster), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` and `AWS_ENDPOINT_URL_S3`. With two or more buckets the prefix rule applies, for example `UPLOADS_S3_BUCKET`, and no bare `S3_*` or `AWS_*` variable is set. An `external: true` bucket renders no store; its secret store entry (default path `{system}-{env}-{resource}`) carries the same keys as the Secret: `endpoint`, `bucket`, `region`, `forcePathStyle`, `accessKeyId` and `secretAccessKey`; `storage` and `versioning` are refused there, since an external bucket is sized and configured at its provider. Removing a bucket resource keeps the in-cluster bucket and its data until a human deletes them.
- `type: cache` is an in-memory cache that speaks the Redis protocol (spec 118). It runs Valkey, not Redis: Valkey has a BSD licence, while Redis 8 is licensed only under AGPLv3, RSAL or SSPL. The type is called `cache`, not `redis`; `type: redis` and `type: valkey` fail the render with a message that names `cache`. Keys and defaults: `version` (Valkey major 8 or 9, default 9), `memory` (default `256Mi`, at least `64Mi`; the container's request and limit), `maxmemoryPolicy` (default `allkeys-lru`), `persistence` (default `false`) and `storage` (default `1Gi`, only with `persistence: true`), at the resource level or per instance under `instances.<env>`. The server gets `maxmemory` of 80 % of `memory`, which leaves room for its own overhead. With `persistence: true` the data is written to an append-only file on a volume of `storage` size; with `false` there is no volume. Each in-cluster instance is one StatefulSet that the renderer writes itself, with a ClusterIP Service on port 6379 and no route. It needs no operator, so `operators: owner` changes nothing for it and `/platform:doctor` has no row for it. The component gets four variables from the Secret `<system>-<name>-app`, whose keys `url`, `host`, `port` and `password` are the contract that later specs (spec 120, the scaler) rely on: `REDIS_URL`, `REDIS_HOST`, `REDIS_PORT` and `REDIS_PASSWORD`. All use database `0`, shared by every component that uses the cache, with one password that External Secrets generates once in the cluster. With two or more caches the prefix rule applies, for example `SESSIONS_REDIS_URL`. An `external: true` cache renders no server; its secret store entry (default path `{system}-{env}-{resource}`) carries the keys `url`, `host`, `port` and `password`, and `memory`, `maxmemoryPolicy`, `persistence` and `storage` are refused there, since an external cache is sized and configured at its provider. Cache data is not backed up, with or without `persistence`: the environment backup leaves caches out by name (see [BACKUP-AND-RESTORE.md](BACKUP-AND-RESTORE.md)). Three limits to know: a write-heavy persistent cache near `maxmemory` can need more than the 20 % headroom while the append-only file is rewritten, so give persistent caches more `memory`; going down a major (`version: 9` to `8`) is not refused before spec 121, and with `persistence: true` the pod then crash-loops until its volume is deleted, because version 8 may not read version 9's file; and `persistence` or `storage` cannot change on a running cache in place: delete its StatefulSet with `kubectl delete statefulsets.apps <system>-<name> -n <system>-<env> --cascade=orphan`, then sync (the pod restarts; an existing volume is reused, and a larger `storage` does not resize it).
- `type: broker` is a message broker for events APIs (spec 119). It runs NATS with JetStream, the persistent messaging layer of NATS. Keys and defaults: `version` (`"2.14"` or `"2.15"`, the NATS server minor line, default `"2.15"`), `replicas` (1 or 3, default 1), `storage` (default `1Gi`, JetStream file storage per replica) and `resources` (requests 100m CPU and 256Mi memory, memory limit 512Mi), at the resource level or per instance under `instances.<env>` (`version` is not allowed per instance). Each in-cluster instance is the official `nats` Helm chart, installed as an Argo CD application that the broker's `addon-<name>-<env>` directory renders. NACK, the NATS JetStream controller, is a platform operator: it creates the streams and consumers that git declares, so `operators/apps/nack.yaml` appears when an environment runs an in-cluster broker (`operators: owner` leaves it to the cluster owner, and `/platform:doctor` has a row `operator nack` and one `broker <name> (<env>)` row per in-cluster broker).
  - Binding. A broker carries an events API when the API names it with `apis.<api>.broker: <name>`, or, without that key, when the system has exactly one broker. With two or more brokers an events API must choose one; `broker` on an API that is not an events API, or naming something that is not a broker, fails the render. An events API in a system with no broker stays unbound: the render prints a note that names the API and `/resource:add <name> --type broker` and gives the components nothing. An API name must be a lowercase DNS label to be bound, because it names the stream.
  - Implicit use. The provider and the consumers of a bound events API use its broker without listing it in `uses`; listing it changes nothing. Listing a broker that carries none of the component's events APIs fails the render, and a component's `env` may not set a variable the broker gives it.
  - Names. For the events API `<api>` of system `<system>`, the stream is `<system>-<api>` with the subjects `<system>.<api>.>`. Each consuming component has a durable pull consumer named after the component. The stream keeps messages for 7 days (file storage, oldest first when the volume is full). A consumer must acknowledge a message within 30 s, otherwise it is delivered again, without a limit on redeliveries.
  - Environment contract. A component that provides or consumes a bound events API gets `NATS_URL`, `NATS_USER` and `NATS_PASSWORD` from its own Secret `<system>-<name>-<component>-app` (keys `url`, `user`, `password`), not from a shared one; spec 120 relies on this Secret as its contract. With two brokers the prefix rule applies (`BUS_NATS_URL`). For every events API it provides or consumes it also gets `EVENTS_<API>_STREAM` (`<system>-<api>`) and `EVENTS_<API>_SUBJECT_PREFIX` (`<system>.<api>`), and `EVENTS_<API>_CONSUMER` (the component name) when it consumes the API; `<API>` is the API name in upper case with `-` becoming `_`. Last, `NATS_INBOX_PREFIX` is `_INBOX.<component>`.
  - Rights. Every component has its own user, with a password that External Secrets generates once in the cluster. The provider of an API may publish under `<system>.<api>.>`. A consumer may only fetch from and acknowledge on its own consumer. Every user may subscribe only to its own inbox prefix `_INBOX.<component>.>`. The default inbox `_INBOX.>` would let one component read what another fetches, so a client must pass `NATS_INBOX_PREFIX` as its inbox prefix; the example below does.
  - Monitoring. The server's monitoring endpoint, `http://<system>-<name>.<system>-<env>.svc:8222/jsz?accounts=true&streams=true&consumers=true`, lists per stream the stored messages and per consumer `num_pending` (not yet delivered) and `num_ack_pending` (delivered, not yet acknowledged). It needs no login and is reachable only inside the cluster.
  - Example. A provider and a consumer each use half of this Python code (`nats-py`). No template ships publisher or subscriber code.

```python
import asyncio, os
import nats

async def main():
    nc = await nats.connect(os.environ["NATS_URL"], user=os.environ["NATS_USER"], password=os.environ["NATS_PASSWORD"],
                            inbox_prefix=os.environ["NATS_INBOX_PREFIX"])
    js = nc.jetstream()
    # provider of the events API `orders`: publish under its subject prefix
    await js.publish(os.environ["EVENTS_ORDERS_SUBJECT_PREFIX"] + ".created", b'{"id": 42}')
    # consumer: read through the component's own durable consumer, acknowledge within 30 s
    sub = await js.pull_subscribe_bind(durable=os.environ["EVENTS_ORDERS_CONSUMER"], stream=os.environ["EVENTS_ORDERS_STREAM"])
    for msg in await sub.fetch(10, timeout=5):
        print(msg.subject, msg.data)
        await msg.ack()
    await nc.close()

asyncio.run(main())
```

  - Removal. Streams and consumers hold messages, so nothing deletes them: not a render, not an Argo CD sync, not `/resource:remove`. `/resource:remove` is refused while an events API is bound to the broker. When you remove an events API or a consumer, the render prints a note such as `stream <system>-<api> is no longer declared; it and its messages stay on the broker until you delete them`, and the stream or consumer stays until a person deletes it. To delete one by hand, use the `nats` command line against the broker (`nats stream rm <system>-<api>`, `nats consumer rm <system>-<api> <component>`), or `kubectl delete stream.jetstream.nats.io` and `consumer.jetstream.nats.io` objects for the ones that NACK still holds. Removing the broker resource itself leaves its server, its volumes and its data in the cluster in the same way.
  - External broker. With `external: true` the platform renders no server and creates nothing on the broker: the owner creates the streams and consumers, and the render prints each name to create (stream `<system>-<api>` with its subjects, file storage and a maximum age of 7 days, and the durable consumers, pull with explicit acknowledgement and an ack wait of 30 s). Each component with an events API reads its own entry from the secret store, by default under `{system}-{env}-{resource}-{component}` (`remote.path` also accepts `{component}`), with the keys `url`, `user` and `password`. Use any NATS service with JetStream, such as Synadia Cloud or your own cluster. A path without `{component}` makes every component read the same entry, so they share one user and the rights are the broker owner's business. `replicas`, `storage` and `resources` are refused on an external broker.
  - Limits. Broker data is part of the environment backup (see [BACKUP-AND-RESTORE.md](BACKUP-AND-RESTORE.md)), with nothing to configure. A new component user restarts the broker pods; with one replica that is a short outage that clients ride out by reconnecting, and the messages stay on the volume. Changing `replicas` from 1 to 3 turns a single server into a cluster; start production with 3 rather than switching later. `storage` cannot change on a running broker in place: delete its StatefulSet with `kubectl delete statefulsets.apps <system>-<name> -n <system>-<env> --cascade=orphan`, then sync (an existing volume is reused, and a larger `storage` does not resize it). Going down a minor version (`2.15` to `2.14`) is not refused before spec 121, and a server may not read the files of a newer one.
- `external: true` means the resource lives outside the cluster. The platform renders no database, only an External Secrets `ExternalSecret` that fills `<system>-<name>-app` from the secret store, so components see the same contract. `remote` (`path`, `refreshInterval`) says where in the store; the default path is `{system}-{env}-{resource}`, and `remote` needs `external: true`. `instances.<env>` may override `external` and `remote`, for example an in-cluster database in dev and an external one in prod.
- Prefix rule: a component that uses exactly one resource of a type gets the bare variables (`DATABASE_URL`, `PGHOST`, ...). With two or more resources of that type, every variable is prefixed with the upper-cased resource name, `-` becoming `_`: `uses: [orders-db, users-db]` yields `ORDERS_DB_DATABASE_URL`, `USERS_DB_PGHOST` and so on, and no bare `DATABASE_URL`. The variables are the same in every environment, in-cluster or external.
- `operators: owner` on an environment (the only value) says the cluster owner installs the operators there. Otherwise the platform installs them from the repo's `operators/` folder (`operators/root.yaml`, applied once per cluster with `devbox run bootstrap`; `cluster-up` does it locally).
- `autonomy` (optional, off by default: every environment is at `observe`) says what an engine may do on its own in an Environment: `level` (`observe`, `advise`, `propose`, `act`, `improve`; prod at most `act`), `engine`, `autoMerge`, `riskGate`, `budget`, `window` and `undoWindow`. On an Instance, `autonomy: {max: <level>}` can only lower it; the top-level `autonomy: {paused: true}` pauses every environment. A system that declares any of it also gets `applications/<system>/autonomy.json`, which an engine reads. `/system:autonomy` shows and changes it; every key and default is in [autonomy.md](autonomy.md).
- Every name in `uses` is a resource or a library of the system; an API has exactly one provider.

## Commands follow the nouns

Every command names the thing it acts on; the same verbs work for a system and for a component. `/component:fix` is the quick-task pipeline: it ships a small change or a bug fix without a spec. `/component:check` is the read-only quality and security check.

| Noun | Verbs |
|---|---|
| `system` | `new` · `set` · `status` · `spec` · `plan` · `ship` · `restore` |
| `component` | `new` · `add` · `set` · `remove` (`add` and `set` take `--provides` and `--consumes`) · `spec` · `plan` · `build` · `verify` · `check` · `ship` · `fix` · `release` |
| `api` | `list` (`check` comes with spec 110) |
| `resource` | `add` · `remove` · `backup` · `restore` |
| `cluster` | `new` · `add` · `remove` (`/cluster:new`, `/cluster:add`, `/cluster:remove`) |
| `instance` | `promote <component> --to <env>` · `secret set <component>/<env>` · `verify` |
| `issue` | `triage` · `report` |
| `platform` | `doctor` · `update` · `fleet` · `runs` · `retro` · `ui` |

The contract check of an API is not built yet: it comes with spec 110.

## 4.7 features on the model

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

## The model in 4.7

![The domain model as built in 4.7.0](img/model-today.svg)

As built in 4.7.0, in the platform's own names:

- **Composition was solid.** The 4.7 concepts in the table below each had a file, a schema and an identity. The work was naming, not structure.
- **Names drifted in four places:** one thing had three names; the services file and the new-system manifest disagreed on service and component; add-ons were also called backing services; pin and image tag.
- **Environment was the gap.** It is the axis every delivery command works on (pin, promote, smoke, status, alerts), yet the list of environments was hard-coded in `render.py` and an environment's settings were spread over four keys in one file, per-environment maps in another and the overlay paths. Service × environment and database × environment had no names.
- **Three relations were missing:** which services use a library, which services provide or consume an API (only prose in the plan), and who owns what. 5.0 adds them.

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
