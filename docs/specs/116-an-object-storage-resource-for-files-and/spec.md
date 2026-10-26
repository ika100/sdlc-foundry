---
spec_id: 116-an-object-storage-resource-for-files-and
title: An object storage resource for files and backups
status: draft
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
- **AC-116.3** Given a component that uses exactly one bucket, when its instance starts, then it has the variables `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION`, `S3_FORCE_PATH_STYLE` (`true` or `false`), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (equal to `S3_REGION`) and `AWS_ENDPOINT_URL_S3` (equal to `S3_ENDPOINT`), all read from the Secret `<system>-<name>-bucket` in the instance's namespace; for an in-cluster bucket `S3_FORCE_PATH_STYLE` is `true`.
- **AC-116.4** Given a component that uses two or more buckets, when its instance starts, then each bucket's variables of AC-116.3 carry the prefix `<NAME>_` (the resource name in upper case, hyphens as underscores, for example `UPLOADS_S3_BUCKET`), and no unprefixed `S3_*` or `AWS_*` variable is set.
- **AC-116.5** Given the rendered tree and the system's repos, when a test searches them, then no access key, secret key or other bucket credential appears in git; in-cluster credentials are generated in the cluster, and the credentials of one environment's bucket are refused (access denied) by the bucket of another environment.

### Using a bucket

- **AC-116.6** Given two components that use the same bucket in the same environment, when one writes an object, then the other can read, list and delete it with its own variables; every using component has read and write access.
- **AC-116.7** Given a bucket instance with `versioning: true`, when a component overwrites an object, then the previous content is still retrievable by its version id; with `versioning: false`, only the latest content is retrievable.
- **AC-116.8** Given an object written to an in-cluster bucket, when the store's pods restart or the resource's Argo application is synced again, then the object is still readable with the same content.

### External buckets

- **AC-116.9** Given a bucket instance declared external through spec 115 (for example prod), when it is rendered, then no in-cluster store or bucket is rendered for that environment, the Secret `<system>-<name>-bucket` is filled from the secret store entry with the keys `endpoint`, `bucket`, `region`, `accessKeyId`, `secretAccessKey` and `forcePathStyle`, and the using component gets the same variable names as AC-116.3 or AC-116.4.
- **AC-116.10** Given an external bucket instance with `storage` or `versioning` set, when it is rendered, then the render fails naming the resource and environment and saying an external bucket is sized and configured at its provider.
- **AC-116.11** Given an external bucket whose store entry is missing or lacks one of the keys of AC-116.9, when the environment syncs, then the Secret `<system>-<name>-bucket` is not created and the using component's pods do not start, as for a missing database Secret (ADR-020); nothing else in the environment is affected.

### Commands and cluster

- **AC-116.12** Given `/resource:add <name> --type bucket [--storage <size>] [--versioning]`, when it runs, then it adds the resource to `resources:` and renders in one PR; `/resource:remove <name>` refuses while a component uses the bucket (naming the components), and after removal the in-cluster bucket and its data stay in the cluster until a human deletes them.
- **AC-116.13** Given a system that declares an in-cluster bucket, when the local cluster is brought up, then the object store is installed at a pinned version; on any cluster without it, `/platform:doctor` warns naming the missing store and the systems that need it.
- **AC-116.14** Given the end-to-end cluster test with a system whose component uses a bucket in dev, when it runs, then the component writes an object through its variables of AC-116.3 and reads back the same bytes, and the test fails naming the step (endpoint unreachable, access denied, content differs).

- **AC-116.15** Given the rendered tree of a system with an in-cluster bucket, when a test reads it, then every image and chart or operator version of the object store is pinned to an exact version (no `latest`, no floating or range tag) set by the platform release, and changing that version follows spec 121.

## Non-goals

- Backups: spec 117 uses a bucket as its backup target and defines what is written there and how it is restored.
- Ready-made S3 clients or configuration in the language templates; components read the variables of AC-116.3 themselves.
- Read-only access, per-component credentials or per-prefix permissions.
- Lifecycle rules (expiry, transition to colder storage), quotas beyond the volume size, replication between environments or regions, public or presigned-URL serving set up by the platform.
- Creating buckets or credentials at a cloud provider: an external bucket and its keys exist before they are put in the store.
- Copying objects between environments.
- The upgrade procedure for the object store (order through environments, backups before a major upgrade, refusing downgrades): that is spec 121.
- Defining named, typed and external resources, the `uses:` form or the per-environment external override: that is spec 115.

## Open questions

- Which store runs in-cluster buckets? (suggested: SeaweedFS, Apache-2.0, light enough for the local cluster and usable in prod; MinIO's community edition was cut down and is AGPL, Garage is also AGPL, Rook-Ceph is too heavy for a local cluster; affects AC-116.7, AC-116.8, AC-116.13)
- Do all components that use a bucket get read and write access? (suggested: yes, one set of credentials per bucket and environment; read-only per component later; alternatives: a `uses` option `access: read` with separate credentials in this spec; affects AC-116.6 and the Non-goals)
- Confirm: the credential Secret is named `<system>-<name>-bucket` and the in-cluster bucket `<system>-<name>`, and both names never change once created. (suggested: yes; affects AC-116.2, AC-116.3, AC-116.9)
- Confirm the variable set: the `S3_*` four plus `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` and `AWS_ENDPOINT_URL_S3`, so that AWS SDKs work with no code. (suggested: yes; alternatives: `S3_*` and the two keys only; affects AC-116.3, AC-116.4)
- Confirm: a component using several buckets gets prefixed variables only, and this matches spec 115's rule for several resources of one type. (suggested: yes; affects AC-116.4)
- Confirm: default `storage` is `10Gi` and `versioning` is `false`. (suggested: yes; affects AC-116.2, AC-116.12)
- Is `versioning` in this spec at all? (suggested: yes, as an on/off per instance, since spec 117 may want it for backups; alternatives: drop it and leave it to 117; affects AC-116.1, AC-116.7, AC-116.10)
- Should the language templates ship a ready client or configuration for the bucket? (suggested: no, variables only in this spec; clients in a later spec per template; affects the Non-goals)
- Confirm: in-cluster buckets are allowed in prod too (not only dev and staging). (suggested: yes, external is a choice per environment, not a rule; affects AC-116.2, AC-116.9)

## Changelog

- 2026-10-26 created
