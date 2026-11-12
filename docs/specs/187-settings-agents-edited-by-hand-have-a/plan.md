---
spec_id: 187-settings-agents-edited-by-hand-have-a
shape: platform
spec_hash: 2aad77a45042
summary: "`cplat system set --observability` and the backup setting on `cplat resource backup`, so neither needs a hand edit of system.yaml"
tasks:
  - id: t1
    title: "`cplat system set --observability lgtm|none|off`"
    files: [scripts/cplat/systemset.py]
    covers: [AC-187.1, AC-187.2, AC-187.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "`cplat resource backup` sets, changes and removes a database instance's backup"
    files: [scripts/cplat/dbbackupset.py, scripts/cplat/dbbackup.py]
    covers: [AC-187.4, AC-187.5, AC-187.6, AC-187.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Commands, usage lines, docs, versions and changelog
    files: [plugins/resource/commands/add.md, plugins/resource/commands/backup.md, plugins/system/commands/set.md, docs/rules/plugins/resource/commands/add.yml, docs/rules/plugins/resource/commands/backup.yml, docs/rules/plugins/system/commands/set.yml, scripts/cplat/cplat.py, plugins/resource/README.md, plugins/system/README.md, docs/BACKUP-AND-RESTORE.md, docs/USER-JOURNEY.md, plugins/resource/.claude-plugin/plugin.json, plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/187-settings-commands.added.md]
    covers: [AC-187.8]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 187 Settings agents edited by hand have a command

The contract is [design.md](design.md). All three tasks are independent: t3 changes text only and names the options the
contract fixes, so it does not wait for the code.

## t1 — `cplat system set --observability lgtm|none|off`

**Files:** scripts/cplat/systemset.py
**Covers:** AC-187.1, AC-187.2, AC-187.3
**Goal:** one more environment setting in `system set`: `--observability` sets `environments.<env>.observability.ui` to
`lgtm` or `none` (creating the block, keeping its other keys) or removes the block with `off`, with the dry run, the
checks before writing, the restore on a failed render and the one-PR flow the command already has.

**Implementation notes:**
- Add `--observability VALUE` to `build_parser` and to `wanted`; extend the "nothing to change" hint and the module
  docstring.
- `check_observability(env, value, block)` per design.md (three errors, exact messages and `fix:` hints); call it with
  the environment's current block after the other checks, before `require_clean`.
- `off` on an environment without the key: a no-op line; when it is the only option, exit 0 without writing,
  rendering or a PR.
- Write: `lgtm`/`none` through `add_key(conf, "observability", CommentedMap())` when absent or `None`, then
  `add_key(block, "ui", value)`; `off` pops `observability`.
- `will_do` lines per design.md; the existing PR branch/title carry `observability` among the keys.

**Done when:** the acceptance tests for AC-187.1 to AC-187.3 pass, the existing `tests/cplat/test_system_set.py` stays
green, and `devbox run test-fast` passes.

## t2 — `cplat resource backup` sets, changes and removes a database instance's backup

**Files:** scripts/cplat/dbbackupset.py, scripts/cplat/dbbackup.py
**Covers:** AC-187.4, AC-187.5, AC-187.6, AC-187.7
**Goal:** `cplat resource backup <db> --env <env>` with `--to`, `--schedule`, `--retention` or `--off` writes or removes
`resources.<db>.instances.<env>.backup`, renders and optionally opens one PR, without touching the cluster; without
those options it takes the on-demand backup exactly as today.

**Implementation notes:**
- `dbbackup.build_parser`: add `--to`, `--schedule`, `--retention`, `--off`, `--dry-run`, `--pr`; in `main`, dispatch to
  `dbbackupset.run(ns)` when a setting option is given, and refuse `--dry-run`/`--pr` without one (design.md). The
  on-demand path below stays byte-for-byte the same in behaviour (AC-187.7).
- `dbbackupset.py`: checks 1–9 of design.md in that order on the raw `system.yaml` (`gitops.load`); copy the render's
  cron rules (`CRON_RANGES`, `CRON_ITEM`, the step check) and `RETENTION` with their wording.
- Merge with the current `backup`: new backup writes all three keys with defaults (`DoubleQuotedScalarString` schedule);
  an existing one changes only the given keys; `--off` deletes `backup` and then empty `instances.<env>` / `instances`.
- Write path: `require_clean` (not on `--dry-run`), `systemset.snapshot`, `gitops.save`, `gitops.render`; on a render
  `PlatformError` `systemset.restore` and re-raise with the hint of design.md case 10.
- Output and JSON keys (`backup`, `kept_in`, `changed`, `pr`) per design.md; `--off` says the backups already in the
  bucket are kept.
- PR: `gitops.open_pr(repo, "resource/backup-<db>-<env>", title, body)` with the titles of design.md.

**Done when:** the acceptance tests for AC-187.4 to AC-187.7 pass, the existing `tests/cplat/test_backup_117_cmds.py`
stays green (AC-187.7), and `devbox run test-fast` passes.

## t3 — Commands, usage lines, docs, versions and changelog

**Files:** plugins/resource/commands/add.md, plugins/resource/commands/backup.md, plugins/system/commands/set.md,
docs/rules/plugins/resource/commands/add.yml, docs/rules/plugins/resource/commands/backup.yml,
docs/rules/plugins/system/commands/set.yml, scripts/cplat/cplat.py, plugins/resource/README.md,
plugins/system/README.md, docs/BACKUP-AND-RESTORE.md, docs/USER-JOURNEY.md, plugins/resource/.claude-plugin/plugin.json,
plugins/system/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/changelog.d/187-settings-commands.added.md
**Covers:** AC-187.8
**Goal:** an agent reading the commands learns where backups and the observability UI are set, and the usage lines name
the new options.

**Implementation notes:**
- `add.md`: replace "No backups, PITR or pooling are provided (ADR-020)." with the design.md sentence pointing to
  `/resource:backup <db> --env <env> --to <bucket>`.
- `backup.md`: new description/usage line and the two-mode steps of design.md (setting: `--dry-run`, then `--pr`, one
  PR; without options: one backup now, nothing in git); `set.md`: usage gains `[--observability lgtm|none|off]`, the
  options paragraph says what each value does.
- Keep the three prompts' combined bytes at or below today's by tightening wording in the same files; every new rule
  sentence carries a reason and gets an entry in its `docs/rules/plugins/...yml` file; `cplat platform rules check`
  passes (links, slash commands and `cplat` commands resolve).
- `cplat.py` docstring: the `system set` and `resource backup` usage lines name the new options.
- READMEs of both plugins, `docs/BACKUP-AND-RESTORE.md` ("Declare it": the command next to the YAML) and the
  observability row of `docs/USER-JOURNEY.md` name the commands; no spec numbers in guides.
- Bump `resource` and `system` minor versions in their `plugin.json` and in `marketplace.json`; changelog fragment per
  `docs/changelog.d/README.md`.

**Done when:** the acceptance tests for AC-187.8 pass, `cplat platform rules check` and `devbox run validate` pass, and
`cplat platform pr-check` reports no plugin-version or changelog failure.
