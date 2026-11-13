---
spec_id: 195-a-restored-copy-is-checked-without
shape: platform
spec_hash: a73c10652594
summary: "`cplat resource query` runs one read-only statement on a database instance (active or a `g<N>` copy) as the application role; `/resource:restore` points to it instead of kubectl"
tasks:
  - id: t1
    title: "`cplat resource query`: checks, read-only exec as the app role, table and JSON output"
    files: [scripts/cplat/dbquery.py, scripts/cplat/cplat.py]
    covers: [AC-195.1, AC-195.2, AC-195.3, AC-195.4]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: "`/resource:restore --to` prints the query command as its check step"
    files: [scripts/cplat/dbrestore.py, tests/cplat/test_backup_117_restore.py]
    covers: [AC-195.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: "`/resource:query` command, register entry, docs, versions and changelog"
    files: [plugins/resource/commands/query.md, docs/rules/plugins/resource/commands/query.yml, plugins/resource/commands/restore.md, docs/rules/plugins/resource/commands/restore.yml, docs/rules/register.yml, plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, .claude-plugin/marketplace.json, docs/BACKUP-AND-RESTORE.md, templates/gitops-app/CLAUDE.md.jinja, tests/cplat/test_plugins_114.py, docs/changelog.d/195-resource-query.added.md]
    covers: [AC-195.1]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t4
    title: The e2e restore drill checks the copy with `cplat resource query`
    files: [tests/e2e/run.sh]
    covers: [AC-195.2, AC-195.3, AC-195.5]
    parallel_safe: true
    depends_on: [t1, t2]
    done: true
---

# Plan — 195 A restored copy is checked without kubectl

The contract is [design.md](design.md). t1 and t2 share no file and need nothing from each other: t2 only changes
two output strings. t3 waits for t1 because `cplat platform rules check` resolves every `cplat <noun> <verb>` a
prompt names, so `query.md` cannot pass it before the route exists. t4 runs the real command on a cluster, so it
waits for t1 and t2.

## t1 — `cplat resource query`: checks, read-only exec as the app role, table and JSON output

**Files:** scripts/cplat/dbquery.py, scripts/cplat/cplat.py
**Covers:** AC-195.1, AC-195.2, AC-195.3, AC-195.4
**Goal:** a new module that runs exactly one SQL statement against the active instance or a `g<N>` copy of a
database in an environment, inside a read-only transaction with a 60 s statement limit, as the application role,
and prints a plain table (or the JSON object) capped at 1000 rows, with every failure a `PlatformError` with a
`fix:` hint.

**Implementation notes:**
- `build_parser()`: positional `name`, `sql`; `--env` (required), `--copy`, `--json`, `--app`, `--repo-dir`
  (default `.`), `--context`; no `--confirm`/`--dry-run`.
- `count_statements(sql)`: the lexer of design.md (quotes, `E''`, `""`, dollar quotes, `--` and nested `/* */`).
- `main`: `gitops.find_app`, `model.load_dir`, then checks 1 to 6 of design.md in that order (no kubectl before
  check 7); `backupstate.restore_state` for the active name, the copies and their roles (`cluster_roles` plus the
  state's `clusters`).
- Checks 7 and 8: the cluster via `backupstate.get_json` (Ready, `status.currentPrimary`), the Secret
  `<system>-<db>-app` via `backupstate.get_json`, base64-decode `username`, `password`, `dbname`.
- The single `backupstate.kubectl` exec call exactly as design.md specifies (`POD_SCRIPT`, `NULL_TOKEN`,
  password on stdin only, `timeout=90`).
- Parse rc 0 with `csv.reader`; keep 1000 rows, set `truncated`; map rc ≠ 0 to the four error cases of design.md
  (timeout and rc 124, read-only, other `ERROR:`, no `ERROR:`), stripping the `psql:<where>: ` prefix.
- Render text (`on <instance> (<role>) in <env>`, padded ` | ` columns, `\n` for newlines, `<n> rows`,
  `truncated at 1000 rows`) or JSON with exactly `instance`, `columns`, `rows`, `truncated`.
- `cplat.py`: `NOUNS["resource"]["query"] = ("dbquery", [])` and a usage line in the module docstring next to
  `resource restore`.

**Done when:** the acceptance tests for AC-195.1 to AC-195.4 pass (they fake `backupstate.kubectl` and
`backupstate.get_json`), and `devbox run test-fast` passes.

## t2 — `/resource:restore --to` prints the query command as its check step

**Files:** scripts/cplat/dbrestore.py, tests/cplat/test_backup_117_restore.py
**Covers:** AC-195.5
**Goal:** after a ready restored instance, the next steps name `/resource:query <db> --env <env> --copy g<N>
"SELECT …"` and no output of a restore contains `kubectl`.

**Implementation notes:**
- In the `ns.to` branch of `main`, replace the `check it: kubectl …` line with the design.md line; `g<N>` is
  `base_state['next']` (the generation of `name`); drop the then unused `dbname`.
- The `--to` `will_do` line ends "else applied directly" instead of "else kubectl apply -k" (design.md).
- `tests/cplat/test_backup_117_restore.py` line 233 pins the old spec 117 line, which AC-195.5 replaces: change the
  expected string to the new check line and comment it `# spec 195: AC-195.5 replaces the kubectl check step`.

**Done when:** the acceptance tests for AC-195.5 pass, the other `tests/cplat/test_backup_117*.py` tests stay
green, and `devbox run test-fast` passes.

## t3 — `/resource:query` command, register entry, docs, versions and changelog

**Files:** plugins/resource/commands/query.md, docs/rules/plugins/resource/commands/query.yml,
plugins/resource/commands/restore.md, docs/rules/plugins/resource/commands/restore.yml, docs/rules/register.yml,
plugins/resource/README.md, plugins/resource/.claude-plugin/plugin.json, .claude-plugin/marketplace.json,
docs/BACKUP-AND-RESTORE.md, templates/gitops-app/CLAUDE.md.jinja, tests/cplat/test_plugins_114.py,
docs/changelog.d/195-resource-query.added.md
**Covers:** AC-195.1
**Goal:** `/resource:query` exists as a thin command that runs `cplat resource query <ARGS>` and relays its output,
and the guides point a restore drill to it instead of kubectl.

**Implementation notes:**
- `query.md`: description with the usage line of design.md; body runs `cplat resource query <ARGS>` (no dry run:
  it only reads) and relays the table whole; the standard "Read `cplat`'s output whole …" and issue-report lines as
  in `restore.md`. No `--confirm prod` step (A7).
- Every rule sentence carries a reason and an entry in `docs/rules/plugins/resource/commands/query.yml` (copy R2/R3
  of `restore.yml`); `cplat platform rules check` passes (the slash command and `cplat resource query` resolve).
- Prompt bytes: offset the new file by tightening `restore.md` (e.g. step 3 names `/resource:query` for the check
  and drops repeated wording; update `restore.yml` quotes if a rule sentence changes). If the total still exceeds
  `baseline.prompt_bytes`, raise it per docs/rules/README.md "Raise the baseline" (benchmarks, then
  `cplat platform rules rebaseline --reason "resource query command (spec 195)"`), which writes `register.yml`.
- `README.md` of the plugin: a `/resource:query` row; `docs/BACKUP-AND-RESTORE.md` "Restore a database": step 1
  says `--to` prints the `/resource:query … --copy g<n>` check, plus a short "Check a copy" example; no spec numbers.
- `templates/gitops-app/CLAUDE.md.jinja` task table: a row "Read a database (read-only) | `/resource:query <db>
  --env <env> [--copy g<N>] "<sql>"`", so agents in a gitops repo use it instead of kubectl.
- `tests/cplat/test_plugins_114.py`: `WORKING["resource"]` gains `query`, the total becomes 44 (comment: spec 195).
- Bump `resource` 1.10.0 → 1.11.0 in `plugin.json` (description names `/resource:query`) and `marketplace.json`;
  changelog fragment per `docs/changelog.d/README.md`.

**Done when:** `cplat platform rules check`, `devbox run validate` and `tests/cplat/test_plugins_114.py` pass, and
`cplat platform pr-check` reports no plugin-version or changelog failure.

## t4 — The e2e restore drill checks the copy with `cplat resource query`

**Files:** tests/e2e/run.sh
**Covers:** AC-195.2, AC-195.3, AC-195.5
**Goal:** prove on a real cluster what the unit tests fake: the psql CSV, the NULL token, the stdin password and the
read-only transaction on PostgreSQL in the CloudNativePG image.

**Implementation notes:**
- In the "Database point in time" step, after the restore succeeded: assert its output contains
  `/resource:query postgres --env dev --copy g1` and no `kubectl`.
- `$cplat resource query postgres --env dev --copy g1 "select v from e2e_rows order by v" --json "${rargs[@]}"`
  returns rows `[["A"]]` and instance `e2e-postgres-g1`; the same without `--copy` returns `A`, `B` (the active
  instance).
- `$cplat resource query postgres --env dev "insert into e2e_rows values ('C')" "${rargs[@]}"` exits 1 with
  `read-only` in its output, and the table on the active instance still holds `A,B` (read with the existing `pg`
  helper).
- `select null::text as n` returns `[[null]]` in JSON (the NULL token works in the image's psql).

**Done when:** `bash -n tests/e2e/run.sh` passes and the e2e job is green on the PR (the step runs in the backup
part that already exercises the restore).
