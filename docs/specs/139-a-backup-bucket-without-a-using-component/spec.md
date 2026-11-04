---
spec_id: 139-a-backup-bucket-without-a-using-component
title: A backup bucket without a using component
status: draft
priority: P1
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

- **AC-139.1** Given a bucket that is the `backup.to` of a database instance in `<env>` and that no component in `<env>`
  uses, when render runs, then it creates that bucket's instance in `<env>` and its credentials only for the backup machinery
  (the database's ObjectStore), and render succeeds.
- **AC-139.2** Given such a bucket, when a component runs in `<env>` without `uses` of it, then the component's pods receive
  none of the bucket's S3_*/AWS_* variables.
- **AC-139.3** Given an existing system where a component uses the backup bucket only to make render pass, when its owner
  removes that `uses`, then render, the backups and `/resource:restore` still work, and the changelog says how to migrate.
- **AC-139.4** Given the platform's tests, when they run, then the rendered manifests of a system with a backup-only bucket
  are frozen like the existing render tests, and the e2e backups test covers a bucket no component uses.

## Non-goals

- No change to the backup schedule, retention or restore commands.
- No new resource types.

## Open questions

1. **Should a database instance exist in an environment before any component runs there (the second half of #418)?**
   - (a) *Not in this spec (recommended):* backups of an environment start with its first component; this spec only removes
     the `uses` the backup bucket needed. Declaring instances per environment ahead of time is a feature for a later spec.
   - (b) *In this spec:* allow `resources.<r>.instances.<env>` to create the instance (database and bucket) without a
     component, so prod backups and a restore drill can be set up before the first promotion.

## Changelog

- 2026-11-05 created (tracks #418); draft, waiting for the answer to the open question
