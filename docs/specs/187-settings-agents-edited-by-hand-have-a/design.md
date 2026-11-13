# Design — 187 Settings agents edited by hand have a command

## Decisions

- **`--observability` joins `cplat system set`** (`scripts/cplat/systemset.py`) as one more key of `wanted`, with its
  own `check_observability` before writing. The dry run, the clean-tree check, the snapshot/restore on a failed render
  and the PR flow stay the ones `system set` already has (AC-187.1, A5).
- **The backup setting lives in a new module `scripts/cplat/dbbackupset.py`**, entered from `dbbackup.main` when any of
  `--to`, `--schedule`, `--retention` or `--off` is given (A1). `dbbackup.py` keeps the on-demand path unchanged
  (AC-187.7); only its parser grows and it dispatches. A separate module keeps the git-writing path free of the
  kubectl path: the setting path never reads or touches the cluster (AC-187.4: no backup is taken).
- **The checks copy the render's rules and wording** (`templates/gitops-app/scripts/render.py`: `check_backup`,
  `check_cron`, `RETENTION`, `validate_observability`) into `dbbackupset.py` / `systemset.py`, instead of importing the
  gitops repo's `scripts/render.py` at run time: that file is the repo's own (possibly older) copy and has side effects
  on import. The render stays the final check; a failure after writing restores the files (A5).
- **Reused helpers:** `systemset.snapshot`, `systemset.restore` and `systemset.add_key` (comment-safe insert, #429),
  `gitops.load/save/render/rendered_changes/require_clean/open_pr/slug/find_app`, `core.Report`, `core.PlatformError`
  (its `hint` prints as `fix:`).
- **Prompt bytes:** the three changed prompts (`plugins/resource/commands/add.md`, `backup.md`,
  `plugins/system/commands/set.md`) aim at no net growth (docs/rules/README.md, rule 6); the wording below is sized for
  that. `cplat platform rules check` must pass; a rebaseline is out of scope for this spec.
- No ADR: the command surface was decided by the spec (A1, A2) and spec 115's non-goal stands; nothing here outlives
  the feature as a new pattern.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/systemset.py` | `--observability lgtm\|none\|off`, `check_observability`, write/remove of the block | changed |
| `scripts/cplat/dbbackup.py` | parser gains `--to`, `--schedule`, `--retention`, `--off`, `--dry-run`, `--pr`; dispatches to `dbbackupset.run(ns)` | changed |
| `scripts/cplat/dbbackupset.py` | checks of AC-187.6, write/remove of `resources.<db>.instances.<env>.backup`, render, PR | new |
| `scripts/cplat/cplat.py` | usage lines of `system set` and `resource backup` | changed |
| `plugins/system/commands/set.md`, `plugins/resource/commands/{backup,add}.md` | usage lines and text (AC-187.8) | changed |

## Contract

### `cplat system set --env ENV --observability VALUE` (AC-187.1 to AC-187.3)

Combines with the other options of `system set` (`--promote`, `--policy`, `--host`, `--operators`); the hint
"nothing to change" now also names `--observability`. Order: environment exists → every option's check (the existing
ones, then observability) → clean tree (not on `--dry-run`) → write → render.

`check_observability(env, value, block)` where `block` is `environments.<env>.observability` (`None` and an absent key
count as an empty block). All errors exit 1 before anything is written:

| Case | message | `fix:` |
|---|---|---|
| value not in `lgtm`, `none`, `off` | `environments.<env>.observability.ui: '<value>' is not allowed` | `allowed: lgtm, none, off` |
| `lgtm` and the block has a truthy `exportTo` | `environments.<env>.observability.exportTo: ui lgtm and exportTo exclude each other (exportTo is <url>)` | `remove exportTo from system.yaml first, or keep it with --observability none` |
| `off` and the block holds keys other than `ui` | `environments.<env>.observability: off would remove <k1>, <k2>` (each key, in file order) | `--observability none (keeps the collector without a UI)` |

Writes (the `observability` mapping is a ruamel `CommentedMap`; new keys go through `add_key`):

- `lgtm` / `none`: create `observability` when absent (or `None`), then set `ui` to the value; every other key of the
  block stays unchanged. `none` is written plain (YAML 1.1 does not read `none` as null).
- `off`: remove the `observability` key of the environment. `off` on an environment without the key is a no-op for
  that option: the text says `environments.<env>.observability is not set; nothing to remove`; when it is the only
  option, the command exits 0 without writing, rendering or opening a PR.

Output (`Report`, title `system set: <env> (<system>)`): `will_do` line `set environments.<env>.observability.ui to
<value>` or `remove environments.<env>.observability`; then `regenerate ApplicationSets and manifests (render.py)`; with
`--pr` the existing `[outward]` line. JSON keys unchanged (`changed`, `pr`). The PR uses the existing branch
`system/set-<env>` and title `chore(system): set <env> <keys>` with `observability` among the keys; it contains only
`system.yaml` and generated files (`gitops.open_pr` already refuses anything else).

### `cplat resource backup <db> --env ENV [--to BUCKET] [--schedule CRON] [--retention R] [--off] [--dry-run] [--pr] [--json]` (AC-187.4 to AC-187.7)

Mode: with any of `--to`, `--schedule`, `--retention`, `--off` it is the **setting** (`dbbackupset.run(ns)`, never
reads the cluster, `--context` is ignored); without them it is the **on-demand backup**, unchanged (AC-187.7).
`--dry-run` or `--pr` without a setting option exits 1: `--dry-run and --pr belong to --to, --schedule, --retention
and --off`, `fix: an on-demand backup changes nothing in git: run it without --dry-run and --pr`.

Checks, in this order, all before writing, exit 1, nothing changes. `<key>` is `resources.<db>.instances.<env>.backup`.
They read the raw `system.yaml` (`gitops.load`), not the model, so an instance without a using component is accepted (A7).

| # | Case | message | `fix:` |
|---|---|---|---|
| 1 | `--off` with `--to`, `--schedule` or `--retention` | `<key>: --off cannot be combined with --to, --schedule or --retention` | `run --off alone` |
| 2 | `<env>` not a key of `environments` | `environments.<env>: '<env>' is not an environment of the system` | `environments: <e1>, <e2>` |
| 3 | `<db>` absent from `resources` or its type is not `database` (type defaults as in `model.py`: `postgres` without type is a database) | `resources.<db>: '<db>' is not a database resource of the system` (+ ` (it is a <type>)` when it exists) | `databases: <names or none>` |
| 4 | the instance is external (`instances.<env>.external` when set, else `resources.<db>.external`) | `resources.<db>.instances.<env>: an external database is backed up by its provider` | `set backups at the database's provider; nothing is set here` |
| 5 | `--off` and no `backup` on the instance | `<key>: there is no backup to turn off` | `nothing to do: /system:status shows the backups` |
| 6 | `--schedule`/`--retention` without `--to`, no `backup` on the instance | `<key>: --schedule and --retention need --to on an instance without backup` | `add --to <bucket> (buckets: <names or none>)` |
| 7 | `--to` not a resource of type `bucket` | `<key>.to: '<bucket>' is not a bucket resource of the system (buckets: <names or none>)` | `add one with /resource:add <name> --type bucket, or pick a listed bucket` |
| 8 | schedule not a five-field cron (render's `CRON_RANGES`/`CRON_ITEM` rules) | `<key>.schedule '<value>' is not a five-field cron expression (minute hour day-of-month month day-of-week, in UTC)` | `e.g. --schedule "0 3 * * *"` |
| 9 | retention not `^[1-9][0-9]*[dw]$` | `<key>.retention '<value>' must be <n>d or <n>w with n of at least 1` | `e.g. --retention 30d or --retention 8w` |
| 10 | render fails after the write | the render's message unchanged | the render's hint when it has one, else `system.yaml and the generated files are restored: fix what the render names and run again` |

Checks 7–9 run only for the options given; check 7 is the render's wording, 8 and 9 are the render's wording with
`<key>` as `where`. Case 10 restores with `systemset.restore(repo, snapshot)` before re-raising.

Writes (after `gitops.require_clean`, skipped on `--dry-run`):

- **New backup** (no `backup` on the instance): create `resources.<db>.instances` and `.<env>` as `CommentedMap` when
  absent, then `backup` = `{to, schedule, retention}` in that key order, block style; `schedule` defaults to
  `"0 3 * * *"` and `retention` to `30d` (A4, `model.DEFAULT_SCHEDULE`/`DEFAULT_RETENTION`). `schedule` is a
  `DoubleQuotedScalarString` (a bare `*` starts a YAML alias).
- **Existing backup**: set only the given keys; a key not given keeps its current value, and an absent key stays absent
  (AC-187.5).
- **`--off`**: delete `backup`; then delete `instances.<env>` when it became empty and `instances` when that became empty
  (as `upgrade.py` does). No `--confirm` (A6).

Output (`Report`, title `resource backup: <db>/<env> (<system>)`):

- `will_do`: `set resources.<db>.instances.<env>.backup: to <to>, schedule "<schedule>", retention <retention>` (the
  effective three values after the merge with the current ones) or `remove resources.<db>.instances.<env>.backup (backups
  already in bucket <to> are kept)`; `regenerate ApplicationSets and manifests (render.py)`; with `--pr`
  `[outward] open a pull request (branch resource/backup-…)`.
- `did`: `updated system.yaml and regenerated <n> file(s)`, and for `--off` `backups already in bucket <to> are kept;
  /resource:restore can still read them` (AC-117.22); with `--pr` `opened <url>`.
- `next_steps`: with `--pr` `review and merge the PR; the first scheduled backup runs after the sync`; without it
  `review the diff, run devbox run validate, then commit (or re-run with --pr)`.
- JSON (`--json`): the `Report` keys plus `backup` (`{"to", "schedule", "retention"}`, or `null` after `--off`),
  `kept_in` (the bucket after `--off`, else `null`), `changed` (list of paths, `[]` on `--dry-run`), `pr` (URL or `null`).

PR: branch `resource/backup-<slug(db)>-<slug(env)>`, title `chore(resource): back up <db> in <env>` or
`chore(resource): stop scheduled backups of <db> in <env>`, body naming the command; `gitops.open_pr` keeps it to
`system.yaml` and generated files.

### Prompt text (AC-187.8)

- `/resource:backup` description: `Set a database's scheduled backup or take one now. Usage: /resource:backup <db> --env
  <env> [--to <bucket>] [--schedule <cron>] [--retention <n>d|<n>w] [--off]`. Steps: with a setting option, preview with
  `--dry-run`, then run with `--pr` (one PR); without one it takes one backup now and changes nothing in git.
- `/system:set` description gains `[--observability lgtm|none|off]`; the options paragraph says what each value does
  and that `off` is refused while the block holds other keys.
- `/resource:add`: the sentence "No backups, PITR or pooling are provided (ADR-020)." becomes: database backups are set
  with `/resource:backup <db> --env <env> --to <bucket>`; PITR and pooling are not provided.
