---
spec_id: 117-databases-and-environments-are-backed-up
title: Databases and environments are backed up and restorable
status: draft
priority: P1
---

# 117 — Databases and environments are backed up and restorable

## Problem

A system on the platform can lose its data today with no way back. The database resource runs as a CloudNativePG cluster with no backups, so a bad migration, a deleted row or a lost volume is permanent. Component volumes and the in-cluster resources added by this series (bucket, broker) are not backed up at all. Git restores every manifest, but not one byte of data. With named and external resources (spec 115) and a bucket resource as a backup target (spec 116), the platform can now back up both. Databases get continuous, point-in-time backups to a bucket. Environments get a scheduled backup of their namespace and volumes with Velero, set as an Environment property in the same way as observability (ADR-053, `docs/DOMAIN-MODEL.md`).

## Stories

- As a product owner, I want my prod database backed up continuously to a bucket I choose, so that I can recover from a bad change or a lost cluster up to a point in time.
- As a developer, I want one command that restores a database to a point in time next to the running one, so that I can check the restored data before my components switch to it.
- As an operator, I want an environment's namespace and volumes backed up on a schedule by setting `backup` on the environment, so that I can bring back files and in-cluster data that are not in git.
- As anyone looking at `/system:status`, I want to see when each backup last succeeded, so that I notice a failing backup before I need it.
- As a reader of the docs, I want to know which data each kind of backup covers, so that I don't expect a consistent database restore from an environment backup.

## Acceptance criteria

### Database backups

- **AC-117.1** Given a database resource (spec 115) whose `instances.<env>.backup` has `to` naming a bucket resource (spec 116), when the system is rendered, then the database's resource instance in `<env>` archives its write-ahead log to that bucket continuously and takes a base backup on `schedule` (a five-field cron expression in UTC). Without `schedule` it backs up daily at 03:00 UTC; without `retention` it keeps 30 days.
- **AC-117.2** Given `instances.<env>.backup` on a database, when it is rendered, then the render fails without writing anything in each of these cases, with a message naming the resource, the environment and the key: `to` is missing or is not a bucket resource of the system; the bucket has no resource instance in `<env>`; `schedule` is not a valid five-field cron expression; `retention` is not `<n>d` or `<n>w` with n ≥ 1. A key other than `to`, `schedule` and `retention` fails, listing those three.
- **AC-117.3** Given a database backed up with `retention: <window>`, when backups are older than the window, then they are deleted from the bucket, except those needed to restore any point within the window. Once the resource instance is older than the window, the earliest restore point shown by AC-117.6 is no later than now minus the window.
- **AC-117.4** Given a database resource instance without `backup`, when the system is rendered, then that instance archives nothing and writes nothing to any bucket.
- **AC-117.5** Given an external database (spec 115) with `backup` in any `instances.<env>`, when it is rendered, then the render fails with "an external database is backed up by its provider", naming the resource.
- **AC-117.6** Given `/system:status` in a gitops-app repo, when it runs, then it shows a row for each database resource instance with: the time of the last successful base backup (`never` before the first one), the state of log archiving (`ok`, or `failing` with the last error), and the earliest and latest restore points. An instance without backup shows `off`. These values are read from the cluster when the command runs and are never written to git.
- **AC-117.7** Given `cplat model show --json`, when it prints a database resource instance, then the instance has a `backup` field with `to`, `schedule` and `retention` as configured (defaults filled in), or `null` without backup. The field is added to schema 2 without changing any existing field.

### Point-in-time restore

- **AC-117.8** Given a database backed up in `<env>`, when `/resource:restore <db> --env <env> --to <time>` runs with `<time>` in RFC 3339 with an explicit offset or `latest`, then it creates a second resource instance of `<db>` in `<env>` from the bucket's backups. That instance contains every transaction committed at or before `<time>` and none committed after it. The running instance and every component keep running unchanged. The command prints the restored instance's name and the `--switch` command.
- **AC-117.9** Given a restored instance from AC-117.8 that is ready, when `/resource:restore <db> --env <env> --switch` runs, then every component in `<env>` that uses `<db>` connects to the restored instance, through the same connection Secret name and without a change to its configuration. The old instance keeps running, without connections from components, and `/system:status` shows it as `previous`.
- **AC-117.10** Given a restored instance that is not yet switched to, or a `previous` instance, when `/resource:restore <db> --env <env> --discard` runs, then that instance and its volumes are deleted. The active instance and the backups in the bucket stay unchanged.
- **AC-117.11** Given `/resource:restore` with one of these inputs, when it runs, then it changes nothing and exits 1 with the reason: a `<time>` before the earliest or after the latest restore point (the message shows both); a database without `backup` in `<env>` (naming `instances.<env>.backup`); an external database; an environment where `<db>` has no instance; a restore while a restored or `previous` instance of `<db>` already exists in `<env>` (naming `--discard`); `--switch` without a ready restored instance.
- **AC-117.12** Given a restore that does not become ready within 30 minutes or fails, when the command ends, then it reports `restore failed` with the reason and exits 1. The active instance and the components stay unchanged, and the failed instance stays for inspection until `--discard`.
- **AC-117.13** Given a switch from AC-117.9, when the restored instance runs as the active one, then it is backed up to the same bucket with the same schedule and retention. Its restore points after the switch can be restored, and restore points of the old instance stay restorable until they leave the retention window.
- **AC-117.14** Given `<env>` is `prod`, when `/resource:restore --switch`, `--discard` or `/system:restore` acts on it, then it does nothing unless `--confirm prod` is given, and without it the command prints the action it would take.

### Environment backups

- **AC-117.15** Given `environments.<env>.backup` with `to` naming a bucket resource and optional `schedule` and `retention` (same forms and defaults as AC-117.1), when the system is rendered, then `backup` is an allowed environment key next to those of AC-114.4. Velero is installed in that environment's cluster, once per cluster however many environments or systems in it set `backup`. The namespace `<system>-<env>` is backed up on the schedule, with the contents of its volumes, and kept for `retention`. An environment without `backup` gets neither.
- **AC-117.16** Given `environments.<env>.backup`, when it is rendered, then it is checked and fails as in AC-117.2, naming the environment instead of a resource.
- **AC-117.17** Given an environment backup, when it runs, then it leaves out the database resource instances (their cluster objects and volumes) and the resource instance of the target bucket itself. Every other object and volume in `<system>-<env>` is included. Specs 118 and 119 say whether cache and broker data are included.
- **AC-117.18** Given `/system:status`, when the system has an environment with `backup`, then it shows for that environment the time of the last successful backup (`never` before the first), the state of the last backup (`completed`, `partially failed` or `failed` with the reason) and the number of backups kept. An environment without `backup` shows `off`.
- **AC-117.19** Given `/system:restore <env>` without `--backup`, when it runs, then it lists that environment's backups (name, time, state), newest first, and changes nothing.
- **AC-117.20** Given `/system:restore <env> --backup <name|latest>`, when it runs, then it restores the objects and volume contents of that backup that are missing from `<system>-<env>`. If one of the backup's volumes still exists, it changes nothing and lists those volumes. With `--replace` it stops the workloads that use those volumes, replaces their contents from the backup and starts the workloads again. It never touches a database resource instance, and its output ends with "databases are not part of environment backups: restore them with /resource:restore".
- **AC-117.21** Given `/system:restore` for an environment without `backup`, a backup name that does not exist, or an environment with no backups yet, when it runs, then it changes nothing and exits 1 with the reason; an unknown name also lists the available backups.
- **AC-117.22** Given `backup` removed from an environment or a database instance, when the system is rendered, then no further backups are taken and the backups already in the bucket are not deleted. Velero is removed from a cluster when no environment in it sets `backup`.

### Defaults, checks and docs

- **AC-117.23** Given a system whose `prod` environment has no `backup`, or that has a database resource instance in `prod` without `backup`, when `/platform:doctor` runs in its gitops-app repo, then it warns "prod has no backup: <items>" and lists each item without a backup. The render still succeeds.
- **AC-117.24** Given the end-to-end test on a local kind cluster, when it runs, then it inserts row A into a backed-up database, records the time T, inserts row B, restores to T and switches, and a component reads A and not B. Then it writes a file to a component volume and an object to an in-cluster bucket that is not the backup target, takes an environment backup, deletes both, restores with `--replace`, and reads both back unchanged.
- **AC-117.25** Given the docs after this spec is built, when they are read, then `docs/DOMAIN-MODEL.md` lists `backup` as an Environment property next to observability and as a key of a database's `instances.<env>`. A backup-and-restore guide says that an environment backup is not a consistent database backup, that databases are restored only with `/resource:restore`, that external databases are backed up by their provider, and which data each kind of backup covers.

### Versions and upgrades

- **AC-117.26** Given a platform release, when a system with database or environment backups is rendered, then the database backup plugin and Velero (chart and image) run at the exact versions pinned by that release, with no version ranges and no `latest`. A key in `system.yaml` that sets their version fails the render. A change of those versions follows spec 121.
- **AC-117.27** Given `cplat system status --json`, when it runs, then each database resource instance and each environment has `backup.last_success`: the time of the last successful backup in RFC 3339 UTC, or `null` when backups are off or none has succeeded yet. It also has `backup.state` with the states of AC-117.6 and AC-117.18. Other commands (spec 121's precondition of a fresh backup) read these fields and do not query the cluster themselves.

## Non-goals

- Backing up external databases or external buckets: their provider does it.
- Restoring one environment's data into another (for example prod into staging) or into another system.
- Backing up what git and the platform recreate: cluster-wide objects, Argo CD, the platform's own addons, the cluster itself.
- Logical dumps of databases, export formats, or restoring a single table.
- Replicating a bucket to another region or provider, and encrypting backups beyond what the bucket provides.
- Scheduled restore drills that check backups automatically (only the end-to-end test of AC-117.24).
- Off-the-shelf components for the series.

## Open questions

- How does a point-in-time restore switch over? (suggested: two steps, restore alongside then `--switch`, with the old instance kept as `previous` until `--discard`; alternatives: restore and switch in one step; replace the instance in place; affects AC-117.8 to AC-117.13)
- Should backups be on by default in prod? (suggested: no, they need a bucket, so they stay off everywhere and `/platform:doctor` warns for prod; alternatives: the render fails for prod without `backup`; on whenever the system has a bucket; affects AC-117.4, AC-117.15, AC-117.23)
- Which commands restore? (suggested: `/resource:restore <db>` for databases and `/system:restore <env>` for environments; alternatives: `/instance:restore`; `/platform:restore`; affects AC-117.8 to AC-117.21)
- May a backup target be a bucket in the same cluster as the data it backs up, in prod? (suggested: yes, but `/platform:doctor` warns "prod backups live in the same cluster"; alternatives: the render fails for prod; allowed without a warning; affects AC-117.2, AC-117.16, AC-117.23)
- What does an environment restore do with volumes that still exist? (suggested: refuse and list them unless `--replace`; alternatives: always replace; restore only into an empty or missing namespace; affects AC-117.20)
- Should a failing backup open an issue? (suggested: yes, through the alert poll (spec 092) in environments with `observability.alerts` on, when log archiving or a scheduled backup has failed for more than 1 hour; alternatives: shown in `/system:status` only; affects a new criterion)
- Confirm: the defaults are a daily backup at 03:00 UTC and 30 days of retention, with retention written as `<n>d` or `<n>w`. (suggested: yes; affects AC-117.1, AC-117.2, AC-117.15)
- Confirm: destructive restore actions in prod need `--confirm prod`. (suggested: yes; alternatives: an interactive prompt; no extra guard; affects AC-117.14)
- Where does another command read the last successful backup time? (suggested: `cplat system status --json`, read live, so `cplat model show` stays a view of the files only; alternatives: a `--live` flag on `cplat model show --json`; a separate `cplat resource backups --json`; affects AC-117.7, AC-117.27)
- Confirm: restoring into another environment (prod into staging) is out of scope here. (suggested: yes, a possible follow-up spec; affects Non-goals)

## Changelog

- 2026-10-26 created
