# Design — 195 A restored copy is checked without kubectl

## Decisions

- **New module `scripts/cplat/dbquery.py`, routed as `cplat resource query`** (A1). It shares nothing writable with
  `dbrestore.py`: it never touches git, never writes to the cluster and has no `--dry-run` (there is nothing to
  preview) and no `--confirm` option (A7, AC-195.3).
- **The statement runs through `kubectl exec … psql` inside the instance's own primary pod, called by cplat** (the
  session never calls kubectl; `backupstate._latest` already uses this path). cplat's machine needs no `psql` and no
  Postgres driver, and the psql in the pod always matches the server major (15 to 18).
- **Connects as the application role** (A3): user name, password and database name come from the keys `username`,
  `password` and `dbname` of the Secret `<system>-<db>-app`. Every generation was bootstrapped with that Secret
  (`render.py` `database_cluster`: `initdb`/`recovery` owner `<db>`, `secret: <system>-<db>-app`), so the same
  credentials open the active instance, a restored and a previous one. The connection goes to `localhost` in the pod
  (CloudNativePG's `host all all all scram-sha-256` rule); `enableSuperuserAccess: false` stays untouched.
- **The password goes in on stdin, never in argv**, so it shows up neither in a local `ps` nor in the pod's process
  list: a `sh -c` script reads one line into `PGPASSWORD` and then `exec`s psql. The role, the database name and the
  user's SQL go in as positional parameters of that script (`"$1"`, `"$2"`, `"$3"`), so no shell interprets them.
- **Read-only is enforced by the database** (A2): psql runs `-c "SET statement_timeout = '60s'"`,
  `-c "BEGIN TRANSACTION READ ONLY"`, `-c "<sql>"`, `-c "ROLLBACK"` in one session with `ON_ERROR_STOP=1`. Any write
  (INSERT/UPDATE/DELETE/DDL, `nextval()`, a writing function, `EXPLAIN ANALYZE` of a write, `CALL`/`DO` that tries to
  commit or to switch the transaction to read-write) fails inside the read-only transaction. The SQL is passed with
  `-c`, never on stdin, so a psql meta-command (`\!`, `\copy`, `\i`) in it reaches the server as text and fails as a
  syntax error instead of running in the pod.
- **Exactly one statement, counted by cplat before anything is sent** (A6). The server would run `COMMIT; SET
  default_transaction_read_only = off; INSERT …` sent as one `-c` string, so a multi-statement string is the one way
  out of the read-only transaction; cplat refuses it. The count uses a small lexer (below), not a SQL parser: it only
  decides "one or more"; the read-only transaction still decides what may run. Where the lexer is unsure it counts
  high (a false refusal, never a second statement sent).
- **Caps** (A4): the server cancels the statement after 60 s (`statement_timeout`); the kubectl call has a 90 s
  timeout as a backstop (`backupstate.kubectl` returns 124). cplat shows at most 1000 rows; it reads psql's output
  whole (bounded by the 60 s statement limit), so a very large result costs memory on the operator's machine, which
  is accepted for a drill tool.
- **Copies by generation only** (A5): `--copy g<N>` means the instance `<system>-<db>-g<N>` listed in
  `restore-state.yaml`. The original instance `<system>-<db>` has no generation: while it is active it is the
  default, and once it is `previous` (after a switch to a restored copy) `--copy` cannot name it, as the spec names
  copies `<system>-<db>-g<N>` only (AC-195.2).
- **Restore's check step** (AC-195.5): `dbrestore.py` prints
  `check it: /resource:query <db> --env <env> --copy g<N> "SELECT …"` in place of the kubectl line, and its `--to`
  `will_do` line says "else applied directly" instead of "else kubectl apply -k", so no output of a restore names
  kubectl (also not in `--json` or `--dry-run`).
- No ADR: the command and its safety model are fixed by the spec (A1 to A7); the kubectl-exec-psql path already
  exists in `backupstate`, so no new pattern outlives the feature.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `scripts/cplat/dbquery.py` | parser, checks, statement count, target instance, the exec call, output parsing and rendering | new |
| `scripts/cplat/cplat.py` | `NOUNS["resource"]["query"] = ("dbquery", [])`; the usage line in the docstring | changed |
| `scripts/cplat/dbrestore.py` | the `check it:` line and the `will_do` wording after `--to` | changed |
| `plugins/resource/commands/query.md` | the `/resource:query` slash command | new |
| `tests/e2e/run.sh` | the restore drill checks the copy with `cplat resource query` | changed |

## Contract

### Command

```
cplat resource query <db> --env <env> [--copy g<N>] "<sql>" [--json] [--app APP] [--repo-dir DIR] [--context C]
/resource:query <db> --env <env> [--copy g<N>] "<sql>" [--json]
```

`<db>` and `<sql>` are positional (in this order); the options may stand anywhere. There is no `--confirm`,
`--dry-run` or `--limit` (argparse rejects them, exit 2). Run in the gitops-app repo (`gitops.find_app`).

### Checks, in this order

Each failure: nothing is sent to the database, stderr carries `ERROR: <message>` and `  fix: <hint>` (the
`PlatformError` handler of `cplat.py`), exit 1. Checks 1 to 6 read only `system.yaml`, `restore-state.yaml` and the
arguments; no kubectl call happens before check 7.

| # | Condition | Message | fix: |
|---|---|---|---|
| 1 | `--env` not in dev, staging, prod | `--env must be dev, staging or prod` | `pass one of them` |
| 2 | `<db>` not a resource | `<db> is not a resource of the system (resources: <names or none>)` | `list them with /system:status` |
| 3 | `<db>` not of type database | `<db> is a <type>: /resource:query reads databases only` | `query a database resource` |
| 4 | no instance of `<db>` in `<env>` | `<db> has no instance in <env> (no component that runs in <env> uses it)` | `it runs in: <envs>` or `no environment runs <db> yet` |
| 5 | the instance is external | `<db> in <env> is an external database: /resource:query reads only databases the platform runs` | `query it with your provider's tools` |
| 6a | the SQL holds no statement (empty, blanks, comments) | `no SQL statement given` | `/resource:query <db> --env <env> "SELECT …"` |
| 6b | more than one statement | `one statement per query, found <n>` | `send each statement in its own /resource:query call` |
| 6c | `--copy` not of the form `g<N>` (N ≥ 1) | `--copy takes a generation like g2, got '<value>'` | `the generations are in /system:status` |
| 6d | `g<N>` not in `restore-state.yaml` of `<db>/<env>` | `<db>/<env> has no copy g<N>; copies: g1 (restored), g2 (previous)` or `<db>/<env> has no copy g<N>; it has no copies` | `see them with /system:status` or `restore one with /resource:restore <db> --env <env> --to <time>` |
| 7 | the cluster cannot be read, is not Ready, or has no `status.currentPrimary` | `cannot read the instance <instance>: <reason>` or `<instance> is not ready (<phase>)` | `check it with /system:status` |
| 8 | the Secret `<system>-<db>-app` cannot be read or lacks `username`, `password` or `dbname` | `cannot read the credentials of <db>/<env> (Secret <system>-<db>-app): <reason>` | `check it with /system:status` |

An invalid `restore-state.yaml` raises its `backupstate.StateError` text as the message (as `dbrestore` does). 6d
lists every cluster of the state named `<system>-<db>-g<N>`, ascending by N, each with its role (`active`,
`restored`, `previous`); a `--copy` naming the active generation is allowed and queries it.

### Target

- Without `--copy`: `backupstate.cluster_roles(system, db, state)["active"]` (`<system>-<db>` without a state file).
- With `--copy g<N>`: `<system>-<db>-g<N>`. Namespace `<system>-<env>`.
- Pod: the cluster's `status.currentPrimary`, read with `backupstate.get_json(["clusters.postgresql.cnpg.io",
  <instance>, "-n", <ns>], context)`; readiness via `backupstate.cluster_ready` / `cluster_phase`.
- The Secret: `backupstate.get_json(["secret", "<system>-<db>-app", "-n", <ns>], context)`, base64-decoded.

### The one database call

Exactly one `backupstate.kubectl` call runs the statement (the test seam):

```python
backupstate.kubectl(
    ["exec", "-i", "-n", ns, primary, "-c", "postgres", "--",
     "sh", "-c", POD_SCRIPT, "sh", username, dbname, sql],
    context, input=password + "\n", timeout=90)

POD_SCRIPT = ('IFS= read -r PGPASSWORD; export PGPASSWORD; PGAPPNAME=cplat-resource-query; export PGAPPNAME; '
              f'exec psql -X -q -w -h localhost -U "$1" -d "$2" -v ON_ERROR_STOP=1 --csv -P null={NULL_TOKEN} '
              '-c "SET statement_timeout = \'60s\'" -c "BEGIN TRANSACTION READ ONLY" -c "$3" -c "ROLLBACK"')
```

- `sql` is the argument exactly as given (a trailing `;` is fine for psql `-c`). The password never appears in the
  argument list.
- `NULL_TOKEN` is a module constant of plain ASCII letters, digits and underscores that real data does not hold
  (e.g. `__cplat_null_7f3a__`); a CSV cell equal to it is NULL.

### Reading the result

- **rc 0:** stdout is psql CSV. Empty stdout (a statement without a result set): columns `[]`, rows `[]`. Otherwise
  the first CSV record is the header and every further record a row; cells are the text PostgreSQL prints,
  `NULL_TOKEN` becomes NULL. The first 1000 rows are kept; `truncated` is true when there were more.
- **rc ≠ 0:** the database error is the stderr lines from the first one containing `ERROR:` on, each with psql's
  `psql:<where>: ` prefix removed (e.g. `ERROR:  cannot execute INSERT in a read-only transaction`). Exit 1 with:

| Case | Message | fix: |
|---|---|---|
| stderr contains `canceling statement due to statement timeout`, or rc 124 | `the query ran longer than 60 seconds and was cancelled; nothing was changed` | `narrow it (a WHERE clause or LIMIT) and run it again` |
| stderr contains `read-only transaction` (AC-195.3) | `the database refused the statement (the session is read-only; nothing was changed): <database error>` | `/resource:query only reads; change data through a component or a migration` |
| any other `ERROR:` (an SQL error) | `the database refused the statement (nothing was changed): <database error>` | `correct the statement and run it again` |
| no `ERROR:` line (connection, kubectl, missing pod) | `cannot run the query on <instance>: <backupstate._why(rc, err, out)>` | `check the instance with /system:status` |

### Output

Text (stdout, exit 0):

```
on <instance> (<role>) in <env>
<col1> | <col2>
<v11>  | <v12>
…
<n> rows
truncated at 1000 rows          (only when truncated)
```

- `<role>` is `active`, `restored` or `previous` (AC-195.2: the output names the instance it ran on).
- Cells are left-aligned and padded to the column's widest cell (header and shown rows), joined by ` | `; trailing
  spaces of each line are removed. NULL prints as an empty cell; a newline in a value prints as `\n`.
- `<n>` is the number of rows shown, always followed by `rows` (`0 rows`, `1 rows`, `1000 rows`), as AC-195.1 writes it.
- A statement without a result set prints the first line and `0 rows`.

JSON (`--json`, stdout, exit 0), exactly these keys:

```json
{"instance": "shop-orders-db-g1", "columns": ["id", "name"], "rows": [["1", "a"], ["2", null]], "truncated": false}
```

Values are strings (PostgreSQL's text form) or `null`. Errors print as text on stderr also with `--json`.

### Statement count (`count_statements(sql: str) -> int`)

Scan left to right; a `;` outside the following spans ends a piece; the result is the number of pieces that hold
anything but whitespace and comments:

- `'…'` with `''` as an escaped quote; `E'…'`/`e'…'` additionally with `\'` and `\\` escapes;
- `"…"` with `""`;
- `$tag$…$tag$`, where `tag` is empty or an identifier not starting with a digit (`$1` is a parameter, not a quote);
- `-- …` to the end of the line; `/* … */`, nested.

An unterminated span runs to the end of the text (one piece; the server then reports the syntax error).

### `/resource:restore --to` (AC-195.5)

The lines after a ready restored instance become:

```
restored <db>/<env> to <when> as <system>-<db>-g<N>; components still use <active>
check it: /resource:query <db> --env <env> --copy g<N> "SELECT …"
switch to it: /resource:restore <db> --env <env> --switch
```

`…` is the single character U+2026. The `--to` `will_do` line reads
`commit '<title>' and bring it to <ns> (Argo CD pull request if addon-<db>-<env> exists, else applied directly)`.

## Data

None: no file in git and no object in the cluster changes.
