---
spec_id: 116-an-object-storage-resource-for-files-and
title: An object storage resource for files and backups
status: building
priority: P1
---

# 116 — An object storage resource for files and backups

## Problem

A component that stores files (uploads, exports, generated reports) has nowhere to put them on the platform today: 5.0 (spec 114) offers one resource, `postgres`, and a pod's own volume is lost or not shared when it moves or scales. Teams either put files into the database or hand-write storage manifests and credentials per system, which is what ADR-020 set out to avoid. Spec 115 makes resources named, typed and optionally external; this spec adds the second type, an S3-compatible `bucket`, with a stable connection contract so the same component code talks to an in-cluster store in dev and to a cloud bucket (AWS S3, Cloudflare R2, GCS interoperability) in prod. It is also the storage that spec 117 will write backups to, so it has to exist first.

## Stories

- As a developer, I want to declare a bucket in `system.yaml` and list it under my component's `uses:`, so that my component gets an S3 endpoint, bucket name and credentials without me writing manifests or handling keys.
- As a developer, I want the same environment variables in every environment, whether the bucket runs in the cluster or at a cloud provider, so that my code does not change between dev and prod.
- As a product owner, I want two components of my system to share one bucket, so that one can write files the other serves.
- As an operator, I want prod to use a provider's bucket through the store-backed external mechanism of spec 115, so that durability and capacity are the provider's job, while dev runs everything in the local cluster.
- As an operator, I want removing a bucket resource to keep its data until a human deletes it, so that a wrong edit cannot destroy files.

## Acceptance criteria

### Declaring and rendering

- **AC-116.1** Given `resources.<name>` with `type: bucket` (keys `storage`, `versioning`, and `instances.<env>` overriding `storage` and `versioning`, plus the external keys of spec 115), when it is rendered, then it is accepted; any other key fails naming the resource, the key and the allowed keys, and a `versioning` value other than `true` or `false` fails naming the two values.
- **AC-116.2** Given an in-cluster bucket resource, when it is rendered, then each environment where a running component uses it gets exactly one bucket named `<system>-<name>` with the declared `storage` capacity (default `10Gi`, `versioning` default `false`), and an environment where no running component uses it gets no bucket; a `<system>-<name>` that is not a valid S3 bucket name (3 to 63 characters, lowercase letters, digits and hyphens) fails the render naming the name and the rule.
- ~~**AC-116.3**~~ withdrawn 2026-10-26: the Secret is named by the one rule for every resource type (`<system>-<name>-app`); replaced by AC-116.16.
- **AC-116.16** Given a component that uses exactly one bucket, when its instance starts, then it has the variables `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION`, `S3_FORCE_PATH_STYLE` (`true` or `false`), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (equal to `S3_REGION`) and `AWS_ENDPOINT_URL_S3` (equal to `S3_ENDPOINT`), all read from the Secret `<system>-<name>-app` in the instance's namespace, whose keys are `endpoint`, `bucket`, `region`, `forcePathStyle`, `accessKeyId` and `secretAccessKey`; for an in-cluster bucket `S3_FORCE_PATH_STYLE` is `true`. The Secret's name and the bucket name `<system>-<name>` never change once created.
- **AC-116.20** Given 5.0's closed lists of resource types and names (AC-114.19, AC-114.15 and AC-114.36, which stay as approved), when this spec is built, then `bucket` is added to them as a 5.x extension: `type: bucket` renders, a component may list a bucket under `uses:`, and `/resource:add --type bucket` works, while every other value those lists refuse is still refused with the same messages.
- **AC-116.4** Given a component that uses two or more buckets, when its instance starts, then each bucket's variables of AC-116.16 carry the prefix `<NAME>_` (the resource name in upper case, hyphens as underscores, for example `UPLOADS_S3_BUCKET`), and no unprefixed `S3_*` or `AWS_*` variable is set.
- **AC-116.5** Given the rendered tree and the system's repos, when a test searches them, then no access key, secret key or other bucket credential appears in git; in-cluster credentials are generated in the cluster, and the credentials of one environment's bucket are refused (access denied) by the bucket of another environment.

### Using a bucket

- **AC-116.6** Given two components that use the same bucket in the same environment, when one writes an object, then the other can read, list and delete it with its own variables; every using component has read and write access.
- **AC-116.7** Given a bucket instance with `versioning: true`, when a component overwrites an object, then the previous content is still retrievable by its version id; with `versioning: false`, only the latest content is retrievable.
- **AC-116.8** Given an object written to an in-cluster bucket, when the store's pods restart or the resource's Argo application is synced again, then the object is still readable with the same content.

### External buckets

- ~~**AC-116.9**~~ withdrawn 2026-10-26: Secret name and store path follow the rules settled for every resource type; replaced by AC-116.17.
- **AC-116.17** Given a bucket instance declared external through spec 115 (for example prod), when it is rendered, then no in-cluster store or bucket is rendered for that environment, the Secret `<system>-<name>-app` is filled from the secret store entry at `{system}-{env}-{resource}` (spec 115's default path) whose keys mirror the Secret's keys of AC-116.16, and the using component gets the same variable names as AC-116.16 or AC-116.4.
- **AC-116.10** Given an external bucket instance with `storage` or `versioning` set, when it is rendered, then the render fails naming the resource and environment and saying an external bucket is sized and configured at its provider.
- ~~**AC-116.11**~~ withdrawn 2026-10-26: Secret renamed to `<system>-<name>-app`; replaced by AC-116.18.
- **AC-116.18** Given an external bucket whose store entry is missing or lacks one of the keys of AC-116.17, when the environment syncs, then the Secret `<system>-<name>-app` is not created and the using component's pods do not start, as for a missing database Secret (ADR-020); nothing else in the environment is affected.

### Commands and cluster

- **AC-116.12** Given `/resource:add <name> --type bucket [--storage <size>] [--versioning]`, when it runs, then it adds the resource to `resources:` and renders in one PR; `/resource:remove <name>` refuses while a component uses the bucket (naming the components), and after removal the in-cluster bucket and its data stay in the cluster until a human deletes them.
- ~~**AC-116.13**~~ withdrawn 2026-10-26: the platform installs the store on every cluster, not only locally; replaced by AC-116.19.
- **AC-116.19** Given a system with an in-cluster bucket in an environment, when it is rendered, then that environment's cluster gets SeaweedFS as a platform-owned Argo CD application pinned to the version of spec 121's versions table, and a cluster with no in-cluster bucket gets none; given `environments.<env>.operators: owner`, then no store application is rendered for that environment and `/platform:doctor` reports, for that environment, whether the installed store is missing, at the expected version or at another version (naming both versions).
- **AC-116.14** Given the end-to-end cluster test with a system whose component uses a bucket in dev, when it runs, then the component writes an object through its variables of AC-116.16 and reads back the same bytes, and the test fails naming the step (endpoint unreachable, access denied, content differs).
- **AC-116.15** Given the rendered tree of a system with an in-cluster bucket, when a test reads it, then every image and chart or operator version of the object store is pinned to an exact version (no `latest`, no floating or range tag) set by the platform release, and changing that version follows spec 121.

## Non-goals

- Backups: spec 117 uses a bucket as its backup target and defines what is written there and how it is restored.
- Ready-made S3 clients or configuration in the language templates; components read the variables of AC-116.16 themselves.
- Amending spec 114: it stays as approved; `bucket` is an additive 5.x extension of its closed lists (AC-116.20).
- Read-only access, per-component credentials or per-prefix permissions.
- Lifecycle rules (expiry, transition to colder storage), quotas beyond the volume size, replication between environments or regions, public or presigned-URL serving set up by the platform.
- Creating buckets or credentials at a cloud provider: an external bucket and its keys exist before they are put in the store.
- Copying objects between environments.
- The upgrade procedure for the object store (order through environments, backups before a major upgrade, refusing downgrades): that is spec 121.
- Defining named, typed and external resources, the `uses:` form or the per-environment external override: that is spec 115.

## Open questions

- ~~Which store runs in-cluster buckets?~~ Answered: SeaweedFS, installed by the platform as a pinned Argo CD application per cluster when needed; an environment can opt out with `operators: owner`. See AC-116.19.
- ~~Do all components that use a bucket get read and write access?~~ Answered: yes, one set of credentials per bucket and environment. See AC-116.6 and Non-goals.
- ~~Confirm the Secret and bucket names.~~ Answered: one rule for every resource type, Secret `<system>-<name>-app`, bucket `<system>-<name>`, never changed. See AC-116.2, AC-116.16, AC-116.17.
- ~~Confirm the variable set.~~ Answered: the four `S3_*` plus the four `AWS_*` variables. See AC-116.16.
- ~~Confirm prefixed variables for several buckets.~~ Answered: yes, spec 115's `<NAME>_` rule. See AC-116.4.
- ~~Confirm defaults.~~ Answered: `storage` 10Gi, `versioning` false. See AC-116.2 and AC-116.12.
- ~~Is `versioning` in this spec?~~ Answered: yes, on/off per instance. See AC-116.1 and AC-116.7.
- ~~Template clients?~~ Answered: no, variables only. See Non-goals.
- ~~Confirm in-cluster buckets in prod.~~ Answered: allowed; external is a per-environment choice. See AC-116.2 and AC-116.17.

## Changelog

- 2026-10-26 created
- 2026-10-26 open questions answered; Secret renamed to `<system>-<name>-app`, external store path and keys per spec 115, store installed per cluster as a pinned Argo CD application with `operators: owner` opt-out, extension of spec 114's closed lists stated (AC-116.3, .9, .11, .13 withdrawn; AC-116.16 to AC-116.20 added)
- 2026-10-26 approved
- 2026-10-27 building
