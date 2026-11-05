---
spec_id: 139-a-backup-bucket-without-a-using-component
title: A backup bucket without a using component
status: done
priority: P1
tracks: [418]
shape: platform
---

# 139 — A backup bucket without a using component

## Problem

`resources.<db>.instances.<env>.backup: {to: backups}` fails render unless a component that runs in `<env>` lists `backups`
in `uses` (`the bucket backups has no resource instance in prod (a component that runs in prod must use it)`). So, to back up
prod, a component (in the demo of 2026-11-04, the task API) has to use the backup bucket. It then receives the bucket's
S3_*/AWS_* credentials in every environment it runs in, and a compromised app can delete its own backups. Also, a database
and its bucket exist in an environment only once a component that uses them runs there, so backups and a restore drill
cannot be set up before the first prod promotion (#418).

Tracks #418.

## Stories

- As the owner of a system, I want to back up a database to a bucket no component uses, so that the app cannot read or delete
  its own backups.
- As the owner of a system, I want to set up backups for an environment before the first component is promoted there, so that
  prod is backed up from its first day.

## Acceptance criteria

- **AC-139.1** Given a bucket that is the `backup.to` of `environments.<env>.backup` or of a database instance in `<env>`, and
  that no component in `<env>` uses, when render runs, then it succeeds and creates that bucket's instance in `<env>` with its
  credentials only for the backup machinery (the database's ObjectStore, Velero's storage location): an in-cluster bucket gets
  its addon, an external bucket the ExternalSecret of its credentials in the addon directory instead of a component's overlay.
  This replaces, for backup targets, the AC-117.2 and AC-117.16 failure "the bucket has no resource instance in `<env>`".
- **AC-139.2** Given such a bucket, when a component runs in `<env>` without `uses` of it, then the component's pods receive
  none of the bucket's S3_*/AWS_* variables.
- **AC-139.3** Given an existing system where a component uses the backup bucket only to make render pass, when its owner
  removes that `uses`, then render, the backups and `/resource:restore` still work, and the changelog says how to migrate.
- **AC-139.4** Given the platform's tests, when they run, then the rendered manifests of a system with a backup-only bucket
  are frozen like the existing render tests, and the e2e backups test covers a bucket no component uses.
- **AC-139.5** Given a backup-only bucket instance, when `cplat` reads the system (`/system:status`, `/resource:restore`), then
  the model lists that bucket instance in `<env>` exactly as render creates it.

## Non-goals

- No change to the backup schedule, retention or restore commands.
- No new resource types.
- No resource instances declared per environment before any component runs there (the second half of #418): a database
  instance still exists in `<env>` only once a component that uses it runs there, so its backups start with that component.
  A later spec may add `resources.<r>.instances.<env>` without a component.

## Open questions

1. ~~Should a database instance exist in an environment before any component runs there (the second half of #418)?~~
   Answered by the user: (a), not in this spec; only the `uses` the backup bucket needed is removed (Non-goals).

## Changelog

- 2026-11-05 created (tracks #418); draft, waiting for the answer to the open question
- 2026-11-05 amended: open question answered by the user: (a)
- 2026-11-05 approved
- 2026-11-05 building
- 2026-11-05 done
