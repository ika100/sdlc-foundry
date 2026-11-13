---
spec_id: 187-settings-agents-edited-by-hand-have-a
title: Settings agents edited by hand have a command
status: done
priority: P1
shape: platform
---

# 187 — Settings agents edited by hand have a command

## Problem

Two settings of a gitops-app's `system.yaml` have no command: the backup of a database instance
(`resources.<db>.instances.<env>.backup`, spec 117, spec 139) and an environment's observability UI
(`environments.<env>.observability`). In journey 11 the coordinator therefore edited `system.yaml` by hand twice: after
`/resource:add backups --type bucket` it added `backup: {to: backups, schedule: "0 3 * * *", retention: 30d}` under the prod
instance of `postgres`, and it added `observability: {ui: lgtm}` to dev and staging. A hand edit skips the dry run, the
checks before writing and the one-PR flow of the commands, takes longer, and is reported as a platform gap in every journey.
The `/resource:add` command also still tells the agent that no backups are provided, which has been false since spec 117.

## Stories

- As the coordinator of a journey, I want to turn on the lgtm UI for an environment with `/system:set`, so that I preview,
  check and open the PR the same way as for every other environment setting.
- As the owner of a system, I want to back up a database instance to a bucket with one command, so that a wrong bucket name,
  schedule or retention is refused before anything is written.
- As an agent reading `/resource:add`, I want its text to say where backups are set, so that I do not conclude that the
  platform has no backups.

## Acceptance criteria

- **AC-187.1** Given a gitops-app repo, when `cplat system set --env <env> --observability lgtm` runs, then
  `environments.<env>.observability.ui` is `lgtm` (the `observability` block is created when absent; its other keys, such as
  `alerts` and `rules`, stay unchanged), the manifests are rendered, and the output names the change; with `--dry-run` it
  prints the same change and writes nothing; with `--pr` it opens one PR that changes only `system.yaml` and generated files.
- **AC-187.2** Given an environment with an `observability` block, when `cplat system set --env <env> --observability none`
  runs, then `ui` is `none` and the other keys stay; when `--observability off` runs and the block holds no key other than
  `ui`, then the `observability` key is removed from the environment; when the block holds other keys, then `off` exits 1,
  changes nothing and names each of those keys with the fix `--observability none` (keeps the collector without a UI).
- **AC-187.3** Given `cplat system set --observability <value>`, when the value is not `lgtm`, `none` or `off`, or the value is
  `lgtm` while the environment's block has `exportTo`, then it exits 1 before writing, `system.yaml` and the generated files
  stay unchanged, and the message names the key (`environments.<env>.observability.ui` or `…exportTo`) and the allowed values
  or the conflict.
- **AC-187.4** Given a database resource and a bucket resource, when `cplat resource backup <db> --env <env> --to <bucket>`
  runs, then `resources.<db>.instances.<env>.backup` holds `to: <bucket>`, `schedule` (`--schedule C`, default `"0 3 * * *"`)
  and `retention` (`--retention R`, default `30d`), the manifests are rendered, and no backup is taken in the cluster; with
  `--dry-run` it prints the three values and writes nothing; with `--pr` it opens one PR that changes only `system.yaml` and
  generated files.
- **AC-187.5** Given a database instance that already has `backup`, when `cplat resource backup <db> --env <env>` runs with
  only some of `--to`, `--schedule` and `--retention`, then only those values change and the others keep their current values;
  when it runs with `--off`, then the `backup` key is removed, the manifests are rendered, and the output says that backups
  already in the bucket are kept (AC-117.22).
- **AC-187.6** Given `cplat resource backup` with `--to`, `--schedule`, `--retention` or `--off`, when one of these holds, then
  it exits 1, `system.yaml` and the generated files stay unchanged, and the message names the key and carries a `fix:` line:
  `<bucket>` is not a bucket resource of the system (the message lists the buckets); `<db>` is not a database resource; the
  database is external ("an external database is backed up by its provider"); `<env>` is not an environment of the system;
  the schedule is not a five-field cron expression; the retention is not `<n>d` or `<n>w` with n of at least 1; `--schedule`
  or `--retention` without `--to` on an instance without `backup`; `--off` on an instance without `backup`; `--off` together
  with another of these options; or the render fails after the change (the files are restored).
- **AC-187.7** Given `cplat resource backup <db> --env <env>` without `--to`, `--schedule`, `--retention` and `--off`, when it
  runs, then it takes an on-demand backup and changes nothing in git, exactly as AC-117.31 and AC-117.32 define.
- **AC-187.8** Given the platform's commands after this spec is built, when an agent reads `/resource:add`, then it is told
  that database backups are set with `/resource:backup <db> --env <env> --to <bucket>` and that PITR and pooling are not
  provided, and no longer that backups are not provided; `/system:set` and `/resource:backup` name their new options in their
  usage line.

## Non-goals

- A command for `environments.<env>.backup` (Velero backups of an environment); it can follow in a later spec the same way.
- A command for the other observability keys (`exportTo`, `headersSecret`, `alerts`, `rules`, `queryURL`,
  `alertmanagerURL`); they stay hand-edited in `system.yaml`.
- A `/resource:set` command: spec 115 decided against it, so the database backup setting lives on `/resource:backup`.
- Changing several environments in one run or one PR: one environment per run, as `/system:set` already does.
- Measuring the journey: whether the coordinator uses the commands is seen in the next journey, not tested here.

## Assumptions

- **A1** The database backup setting is configured through `/resource:backup` with `--to`, `--schedule`, `--retention` and
  `--off` (it changes git and opens a PR), while the call without them keeps taking an on-demand backup (other option: a new
  `/resource:set <db> --env <env> --backup-to <bucket>`, which reverses spec 115's non-goal; affects AC-187.4 to AC-187.7).
- **A2** `--observability` takes `lgtm`, `none` and `off`: `none` keeps the collector without a UI, `off` removes the block
  (other option: only `lgtm` and `off`; affects AC-187.1 to AC-187.3).
- **A3** `--observability off` refuses when the block holds keys other than `ui` instead of deleting alert rules and
  endpoints silently (other option: remove the whole block anyway; affects AC-187.2).
- **A4** A new backup writes `schedule` and `retention` explicitly with the defaults of AC-117.1, so that `system.yaml` shows
  what runs (other option: write only `to` and let the render fill the defaults; affects AC-187.4).
- **A5** The checks of AC-187.6 run before anything is written, with the same wording as the render's checks, and a render
  failure after writing restores the files as `/system:set` does today (other option: rely on the render alone; affects
  AC-187.3, AC-187.6).
- **A6** Removing a backup with `--off` needs no `--confirm prod`, because it deletes no data and the PR is reviewed (other
  option: require `--confirm prod` as AC-117.14 does for restores; affects AC-187.5).
- **A7** Setting a backup for an environment where no component uses the database yet is allowed; whether the render accepts it
  stays as spec 139 defines (other option: refuse it in `cplat`; affects AC-187.4).

## Open questions

None.

## Changelog

- 2026-11-12 created
- 2026-11-12 approved
- 2026-11-12 building
- 2026-11-12 done
