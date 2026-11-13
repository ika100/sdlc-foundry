"""`cplat resource query <db> --env <env> [--copy g<N>] "<sql>" [--json]`: read one SQL statement from a database (spec 195).

The statement runs in the pod of the primary, as the application role, in a read-only transaction with a 60 second limit; the
database enforces read-only. cplat counts the statements first (exactly one), shows at most 1000 rows as a plain table or JSON."""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import re
from pathlib import Path

import backupstate
import gitops
import model
from core import PlatformError

CLUSTER_KIND = "clusters.postgresql.cnpg.io"
NULL_TOKEN = "__cplat_null_7f3a__"
MAX_ROWS = 1000
EXEC_TIMEOUT_S = 90
POD_SCRIPT = ('IFS= read -r PGPASSWORD; export PGPASSWORD; PGAPPNAME=cplat-resource-query; export PGAPPNAME; '
              f'exec psql -X -q -w -h localhost -U "$1" -d "$2" -v ON_ERROR_STOP=1 --csv -P null={NULL_TOKEN} '
              '-c "SET statement_timeout = \'60s\'" -c "BEGIN TRANSACTION READ ONLY" -c "$3" -c "ROLLBACK"')
COPY_RE = re.compile(r"^g([1-9]\d*)$")
TAG_RE = re.compile(r"\$(?:[A-Za-z_\u0080-￿][A-Za-z0-9_\u0080-￿]*)?\$")
PSQL_PREFIX = re.compile(r"^psql:.*?:\d+: ")
STATUS = "check it with /system:status"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cplat resource query", description=__doc__)
    p.add_argument("name", help="the database resource")
    p.add_argument("sql", help="exactly one SQL statement")
    p.add_argument("--env", required=True)
    p.add_argument("--copy", metavar="gN", help="query the restored copy g<N> instead of the active instance")
    p.add_argument("--json", action="store_true")
    p.add_argument("--app")
    p.add_argument("--repo-dir", default=".")
    p.add_argument("--context", help="kube context (default: the current one)")
    return p


def _ident(ch: str) -> bool:
    return ch.isalnum() or ch in "_$"


def count_statements(sql: str) -> int:
    """Number of statements in `sql`: pieces between `;` outside quotes and comments that hold more than blanks and comments.
    A small lexer, not a parser; where unsure it counts high."""
    n, i, size, has = 0, 0, len(sql), False
    while i < size:
        ch = sql[i]
        if ch == ";":
            n += has
            has = False
            i += 1
        elif ch.isspace():
            i += 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = size if j < 0 else j + 1
        elif sql.startswith("/*", i):
            depth, i = 1, i + 2
            while i < size and depth:
                if sql.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif sql.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
        elif ch == "'":
            esc = i > 0 and sql[i - 1] in "eE" and (i < 2 or not _ident(sql[i - 2]))
            i, has = _skip_quoted(sql, i, "'", esc), True
        elif ch == '"':
            i, has = _skip_quoted(sql, i, '"', False), True
        elif ch == "$" and not (i > 0 and _ident(sql[i - 1])) and (m := TAG_RE.match(sql, i)):
            end = sql.find(m.group(0), m.end())
            i, has = (size if end < 0 else end + len(m.group(0))), True
        else:
            has = True
            i += 1
    return n + has


def _skip_quoted(sql: str, i: int, q: str, backslash: bool) -> int:
    """Index after the quoted span starting at `i` (the end of the text when it is unterminated)."""
    i += 1
    while i < len(sql):
        if backslash and sql[i] == "\\":
            i += 2
        elif sql[i] == q:
            if sql.startswith(q, i + 1):
                i += 2
            else:
                return i + 1
        else:
            i += 1
    return len(sql)


def _roles(system: str, db: str, state: dict | None) -> dict[str, str]:
    roles = {c["name"]: c["role"] for c in (state or {}).get("clusters") or []}
    roles.setdefault(f"{system}-{db}", "active")
    return roles


def _copies(system: str, db: str, state: dict | None) -> list[tuple[int, str]]:
    prefix = f"{system}-{db}-g"
    found = [(int(n[len(prefix):]), r) for n, r in _roles(system, db, state).items()
             if n.startswith(prefix) and n[len(prefix):].isdigit()]
    return sorted(found)


def check_args(ns: argparse.Namespace, m: model.Model) -> model.ResourceInstance:
    db, env = ns.name, ns.env
    if env not in model.ENVIRONMENTS:
        raise PlatformError(f"--env must be {', '.join(model.ENVIRONMENTS[:-1])} or {model.ENVIRONMENTS[-1]}", hint="pass one of them")
    res = {r.name: r for r in m.resources}
    if db not in res:
        raise PlatformError(f"{db} is not a resource of the system (resources: {', '.join(res) or 'none'})", hint="list them with /system:status")
    if res[db].type != "database":
        raise PlatformError(f"{db} is a {res[db].type}: /resource:query reads databases only", hint="query a database resource")
    ri = next((i for i in m.resource_instances if i.resource == db and i.environment == env), None)
    if ri is None:
        envs = [i.environment for i in m.resource_instances if i.resource == db]
        raise PlatformError(f"{db} has no instance in {env} (no component that runs in {env} uses it)",
                            hint=f"it runs in: {', '.join(envs)}" if envs else f"no environment runs {db} yet")
    if ri.external:
        raise PlatformError(f"{db} in {env} is an external database: /resource:query reads only databases the platform runs",
                            hint="query it with your provider's tools")
    count = count_statements(ns.sql)
    if count == 0:
        raise PlatformError("no SQL statement given", hint=f'/resource:query {db} --env {env} "SELECT …"')
    if count > 1:
        raise PlatformError(f"one statement per query, found {count}", hint="send each statement in its own /resource:query call")
    if ns.copy is not None and not COPY_RE.match(ns.copy):
        raise PlatformError(f"--copy takes a generation like g2, got '{ns.copy}'", hint="the generations are in /system:status")
    return ri


def _decode(secret: dict, key: str) -> str | None:
    raw = (secret.get("data") or {}).get(key)
    if not raw:
        return None
    try:
        return base64.b64decode(raw).decode()
    except ValueError:
        return None


def _read_result(out: str) -> tuple[list[str], list[list[str | None]], bool]:
    records = list(csv.reader(io.StringIO(out)))
    if not records:
        return [], [], False
    rows = [[None if c == NULL_TOKEN else c for c in r] for r in records[1:]]
    return records[0], rows[:MAX_ROWS], len(rows) > MAX_ROWS


def _fail(rc: int, out: str, err: str, instance: str) -> PlatformError:
    lines = (err or "").splitlines()
    first = next((k for k, ln in enumerate(lines) if "ERROR:" in ln), None)
    shown = "\n".join(PSQL_PREFIX.sub("", ln) for ln in lines[first:]) if first is not None else ""
    if rc == 124 or "canceling statement due to statement timeout" in (err or ""):
        return PlatformError("the query ran longer than 60 seconds and was cancelled; nothing was changed",
                             hint="narrow it (a WHERE clause or LIMIT) and run it again")
    if first is None:
        return PlatformError(f"cannot run the query on {instance}: {backupstate._why(rc, err, out)}",
                             hint="check the instance with /system:status")
    if "read-only transaction" in (err or ""):
        return PlatformError(f"the database refused the statement (the session is read-only; nothing was changed): {shown}",
                             hint="/resource:query only reads; change data through a component or a migration")
    return PlatformError(f"the database refused the statement (nothing was changed): {shown}", hint="correct the statement and run it again")


def _cell(v: str | None) -> str:
    return (v or "").replace("\n", "\\n")


def render_text(instance: str, role: str, env: str, columns: list[str], rows: list[list[str | None]], truncated: bool) -> str:
    lines = [f"on {instance} ({role}) in {env}"]
    if columns:
        table = [[_cell(c) for c in columns], *([_cell(c) for c in r] for r in rows)]
        widths = [max(len(r[k]) for r in table if k < len(r)) for k in range(len(columns))]
        lines += [" | ".join(c.ljust(widths[k]) for k, c in enumerate(r)).rstrip() for r in table]
    lines.append(f"{len(rows)} rows")
    if truncated:
        lines.append(f"truncated at {MAX_ROWS} rows")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    repo = Path(ns.repo_dir).resolve()
    app_dir = gitops.find_app(repo, ns.app)
    m = model.load_dir(app_dir)
    check_args(ns, m)
    system, db, env, ctx = app_dir.name, ns.name, ns.env, ns.context
    try:
        state = backupstate.restore_state(app_dir, env, db)
    except backupstate.StateError as e:
        raise PlatformError(str(e)) from e
    roles = _roles(system, db, state)
    if ns.copy is None:
        instance = backupstate.cluster_roles(system, db, state)["active"]
    else:
        instance = f"{system}-{db}-{ns.copy}"
        if instance not in roles or instance == f"{system}-{db}":
            copies = _copies(system, db, state)
            if copies:
                raise PlatformError(f"{db}/{env} has no copy {ns.copy}; copies: " + ", ".join(f"g{n} ({r})" for n, r in copies),
                                    hint="see them with /system:status")
            raise PlatformError(f"{db}/{env} has no copy {ns.copy}; it has no copies",
                                hint=f"restore one with /resource:restore {db} --env {env} --to <time>")
    role = roles.get(instance, "active")
    kns = f"{system}-{env}"

    try:
        cluster = backupstate.get_json([CLUSTER_KIND, instance, "-n", kns], ctx)
    except backupstate.ReadError as e:
        raise PlatformError(f"cannot read the instance {instance}: {e}", hint=STATUS) from e
    primary = str((cluster.get("status") or {}).get("currentPrimary") or "")
    if not backupstate.cluster_ready(cluster) or not primary:
        raise PlatformError(f"{instance} is not ready ({backupstate.cluster_phase(cluster)})", hint=STATUS)
    secret_name = f"{system}-{db}-app"
    why = f"cannot read the credentials of {db}/{env} (Secret {secret_name}): "
    try:
        secret = backupstate.get_json(["secret", secret_name, "-n", kns], ctx)
    except backupstate.ReadError as e:
        raise PlatformError(why + str(e), hint=STATUS) from e
    creds = {k: _decode(secret, k) for k in ("username", "password", "dbname")}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise PlatformError(why + f"the Secret lacks {', '.join(missing)}", hint=STATUS)

    rc, out, err = backupstate.kubectl(
        ["exec", "-i", "-n", kns, primary, "-c", "postgres", "--", "sh", "-c", POD_SCRIPT, "sh",
         creds["username"], creds["dbname"], ns.sql],
        ctx, input=creds["password"] + "\n", timeout=EXEC_TIMEOUT_S)
    if rc != 0:
        raise _fail(rc, out, err, instance)
    columns, rows, truncated = _read_result(out)
    if ns.json:
        print(json.dumps({"instance": instance, "columns": columns, "rows": rows, "truncated": truncated}))
    else:
        print(render_text(instance, role, env, columns, rows, truncated))
    return 0
