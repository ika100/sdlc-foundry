"""Spec 195 acceptance tests: `cplat resource query` (AC-195.1 to .4) and the check step of `/resource:restore --to` (AC-195.5).

Contract: design.md "Contract" (checks in order, the one `backupstate.kubectl` exec call, error mapping, output format,
`count_statements`, restore output lines). The cluster is `FakeKube` behind the kubectl seam of `backupstate`; the pod's psql
is a hook on the `exec` verb. Nothing touches the network."""
import base64
import csv
import io
import json

import pytest

import cplat
from backup_fixtures import (bdoc, clock, cnpg_cluster, kube, make_repo, objectstore, restored_state, switched_state,  # noqa: F401  (fixtures)
                             tree_state, write_state)

DEV = {"to": "backups"}
PW = "s3cr3t-pw"
DB_ERR = "psql:cplat:1: ERROR:  cannot execute INSERT in a read-only transaction"


def b64(s):
    return base64.b64encode(s.encode()).decode()


def run(*argv, capsys):
    rc = cplat.main([*map(str, argv)])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


class Pod:
    """The psql in the pod: answers every `exec` with the configured (rc, stdout, stderr)."""

    def __init__(self, kube):
        self.kube = kube
        self.reply = (0, "", "")
        kube.hooks.append(self._hook)

    def _hook(self, args, stdin):
        if args and args[0] == "exec":
            return self.reply
        return None

    def csv(self, header, rows):
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
        self.reply = (0, buf.getvalue(), "")

    @property
    def execs(self):
        return [c for c in self.kube.calls if c[0] and c[0][0] == "exec"]


def world(kube, ns="shop-dev", names=("shop-orders-db",), secret=True):
    kube.put("cluster", *[cnpg_cluster(n, ns=ns) for n in names])
    if secret:
        kube.put("secret", {"metadata": {"name": "shop-orders-db-app", "namespace": ns},
                            "data": {"username": b64("shop_user"), "password": b64(PW), "dbname": b64("shop")}})
    return Pod(kube)


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path, bdoc(dbb={"dev": DEV, "prod": DEV}))


def query(repo, capsys, sql="SELECT id, name FROM t", *extra, env="dev", name="orders-db"):
    return run("resource", "query", name, "--env", env, sql, "--repo-dir", repo, *extra, capsys=capsys)


# ======================= AC-195.1: a plain table, JSON, the 1000 row cap =======================

def test_query_prints_a_plain_table_and_the_row_count_ac_195_1(repo, kube, capsys):  # AC-195.1
    pod = world(kube)
    pod.csv(["id", "name"], [["1", "a"], ["22", "bb"]])
    rc, out, err = query(repo, capsys)
    assert rc == 0, err
    assert out.splitlines() == ["on shop-orders-db (active) in dev", "id | name", "1  | a", "22 | bb", "2 rows"]


def test_query_prints_null_as_an_empty_cell_and_a_newline_escaped_ac_195_1(repo, kube, capsys):  # AC-195.1
    from dbquery import NULL_TOKEN
    pod = world(kube)
    pod.csv(["id", "name"], [["1", NULL_TOKEN], ["2", "x\ny"]])
    rc, out, err = query(repo, capsys)
    assert rc == 0, err
    assert out.splitlines()[1:] == ["id | name", "1  |", "2  | x\\ny", "2 rows"]


def test_query_counts_one_row_as_1_rows_and_a_statement_without_result_as_0_rows_ac_195_1(repo, kube, capsys):  # AC-195.1
    pod = world(kube)
    pod.csv(["n"], [["7"]])
    rc, out, _ = query(repo, capsys, "SELECT 7 AS n")
    assert rc == 0 and out.splitlines()[-1] == "1 rows"
    pod.reply = (0, "", "")
    rc, out, _ = query(repo, capsys, "SELECT 1 WHERE false")
    assert rc == 0 and out.splitlines() == ["on shop-orders-db (active) in dev", "0 rows"]


def test_query_json_has_exactly_instance_columns_rows_truncated_ac_195_1(repo, kube, capsys):  # AC-195.1
    from dbquery import NULL_TOKEN
    pod = world(kube)
    pod.csv(["id", "name"], [["1", "a"], ["2", NULL_TOKEN]])
    rc, out, err = query(repo, capsys, "SELECT id, name FROM t", "--json")
    assert rc == 0, err
    assert json.loads(out) == {"instance": "shop-orders-db", "columns": ["id", "name"], "rows": [["1", "a"], ["2", None]], "truncated": False}


def test_query_shows_at_most_1000_rows_and_says_so_ac_195_1(repo, kube, capsys):  # AC-195.1
    pod = world(kube)
    pod.csv(["n"], [[str(i)] for i in range(1001)])
    rc, out, err = query(repo, capsys, "SELECT n FROM big")
    lines = out.splitlines()
    assert rc == 0, err
    assert lines[-2:] == ["1000 rows", "truncated at 1000 rows"]
    assert len(lines) == 1 + 1 + 1000 + 2
    rc, out, _ = query(repo, capsys, "SELECT n FROM big", "--json")
    d = json.loads(out)
    assert rc == 0 and d["truncated"] is True and len(d["rows"]) == 1000 and d["rows"][-1] == ["999"]


def test_exactly_1000_rows_are_not_truncated_ac_195_1(repo, kube, capsys):  # AC-195.1
    pod = world(kube)
    pod.csv(["n"], [[str(i)] for i in range(1000)])
    rc, out, _ = query(repo, capsys, "SELECT n FROM big")
    assert rc == 0 and out.splitlines()[-1] == "1000 rows" and "truncated" not in out


def test_the_statement_goes_into_the_pod_in_one_exec_with_the_password_on_stdin_ac_195_1(repo, kube, capsys):  # AC-195.1
    pod = world(kube)
    pod.csv(["id"], [["1"]])
    rc, _, err = query(repo, capsys, "SELECT id FROM t WHERE x = 'a;b'")
    assert rc == 0, err
    [(args, _ctx, stdin)] = pod.execs
    assert args[:9] == ["exec", "-i", "-n", "shop-dev", "shop-orders-db-1", "-c", "postgres", "--", "sh"]
    assert args[-4:] == ["sh", "shop_user", "shop", "SELECT id FROM t WHERE x = 'a;b'"]
    assert stdin == PW + "\n" and not any(PW in a for a in args)
    from dbquery import POD_SCRIPT
    script = args[10]
    assert script == POD_SCRIPT
    assert "BEGIN TRANSACTION READ ONLY" in script and "statement_timeout" in script and "ON_ERROR_STOP=1" in script
    order = [script.index(p) for p in ("SET statement_timeout", "BEGIN TRANSACTION READ ONLY", '-c "$3"', "ROLLBACK")]
    assert order == sorted(order)
    assert kube.writes() == []


def test_the_context_option_reaches_the_kubectl_calls_ac_195_1(repo, kube, capsys):  # AC-195.1
    pod = world(kube)
    pod.csv(["id"], [["1"]])
    rc, _, err = query(repo, capsys, "SELECT 1", "--context", "kind-x")
    assert rc == 0, err
    assert kube.calls and all(c[1] == "kind-x" for c in kube.calls)


def test_query_has_no_confirm_dry_run_or_limit_option_ac_195_1(repo, kube, capsys):  # AC-195.1
    pod = world(kube)
    pod.csv(["n"], [["1"]])
    assert query(repo, capsys, "SELECT 1")[0] == 0, "the command exists and runs without them"
    for opt in (["--confirm", "prod"], ["--dry-run"], ["--limit", "5"]):
        try:
            rc, _, _ = query(repo, capsys, "SELECT 1", *opt)
        except SystemExit as e:
            rc = e.code
        assert rc == 2, opt


# ======================= AC-195.2: --copy g<N> =======================

def copy_world(repo, kube, state=None):
    write_state(repo, state or restored_state())
    return world(kube, names=("shop-orders-db", "shop-orders-db-g1"))


def test_copy_runs_against_the_generation_instance_and_names_it_ac_195_2(repo, kube, capsys):  # AC-195.2
    pod = copy_world(repo, kube)
    pod.csv(["id"], [["1"]])
    rc, out, err = query(repo, capsys, "SELECT id FROM t", "--copy", "g1")
    assert rc == 0, err
    assert out.splitlines()[0] == "on shop-orders-db-g1 (restored) in dev"
    [(args, _, _)] = pod.execs
    assert args[2:5] == ["-n", "shop-dev", "shop-orders-db-g1-1"]


def test_copy_json_names_the_copy_instance_ac_195_2(repo, kube, capsys):  # AC-195.2
    pod = copy_world(repo, kube)
    pod.csv(["id"], [["1"]])
    rc, out, err = query(repo, capsys, "SELECT id FROM t", "--copy", "g1", "--json")
    assert rc == 0, err
    assert json.loads(out)["instance"] == "shop-orders-db-g1"


def test_without_copy_the_active_generation_is_queried_after_a_switch_ac_195_2(repo, kube, capsys):  # AC-195.2
    pod = copy_world(repo, kube, switched_state())
    pod.csv(["id"], [["1"]])
    rc, out, err = query(repo, capsys, "SELECT id FROM t")
    assert rc == 0, err
    assert out.splitlines()[0] == "on shop-orders-db-g1 (active) in dev"
    assert pod.execs[0][0][4] == "shop-orders-db-g1-1"


def test_copy_of_a_previous_generation_is_labelled_previous_ac_195_2(repo, kube, capsys):  # AC-195.2
    state = {"next": 3, "clusters": [
        {"name": "shop-orders-db-g1", "role": "previous", "until": "2026-10-27T12:02:13Z",
         "from": {"server": "shop-orders-db", "to": "latest"}},
        {"name": "shop-orders-db-g2", "role": "active", "from": {"server": "shop-orders-db-g1", "to": "latest"}}]}
    write_state(repo, state)
    pod = world(kube, names=("shop-orders-db-g1", "shop-orders-db-g2"))
    pod.csv(["id"], [["1"]])
    rc, out, err = query(repo, capsys, "SELECT id FROM t", "--copy", "g1")
    assert rc == 0, err
    assert out.splitlines()[0] == "on shop-orders-db-g1 (previous) in dev"


# ======================= AC-195.3: read-only, enforced by the database =======================

def test_a_write_is_refused_by_the_database_and_exits_1_with_its_error_ac_195_3(repo, kube, capsys):  # AC-195.3
    pod = world(kube)
    pod.reply = (1, "", DB_ERR + "\n")
    before = tree_state(repo)
    rc, out, err = query(repo, capsys, "INSERT INTO t VALUES (1)")
    assert rc == 1 and out == ""
    assert "ERROR:  cannot execute INSERT in a read-only transaction" in err
    assert "psql:cplat:1:" not in err
    assert "the database refused the statement (the session is read-only; nothing was changed)" in err
    assert "fix: /resource:query only reads; change data through a component or a migration" in err
    assert tree_state(repo) == before and kube.writes() == []


def test_a_write_to_a_copy_is_refused_the_same_way_ac_195_3(repo, kube, capsys):  # AC-195.3
    pod = copy_world(repo, kube)
    pod.reply = (1, "", DB_ERR + "\n")
    rc, out, err = query(repo, capsys, "DELETE FROM t", "--copy", "g1")
    assert rc == 1 and "read-only transaction" in err and "fix:" in err


def test_prod_needs_no_confirmation_for_a_query_ac_195_3(repo, kube, capsys):  # AC-195.3
    pod = world(kube, ns="shop-prod")
    pod.csv(["id"], [["1"]])
    rc, out, err = query(repo, capsys, "SELECT id FROM t", env="prod")
    assert rc == 0, err
    assert out.splitlines()[0] == "on shop-orders-db (active) in prod" and pod.execs[0][0][3] == "shop-prod"


@pytest.mark.parametrize("sql", [
    "SELECT 1; INSERT INTO t VALUES (1)",
    "COMMIT; SET default_transaction_read_only = off; DELETE FROM t",
    "SELECT 1;SELECT 2;",
    "SELECT 1 /* a ; b */ ; SELECT 2",
])
def test_more_than_one_statement_is_refused_before_anything_is_sent_ac_195_3(repo, kube, capsys, sql):  # AC-195.3
    pod = world(kube)
    rc, out, err = query(repo, capsys, sql)
    assert rc == 1 and "one statement per query, found " in err and "fix:" in err
    assert pod.execs == [] and kube.writes() == []


@pytest.mark.parametrize("sql, n", [
    ("SELECT 1", 1),
    ("SELECT 1;", 1),
    ("SELECT 1; SELECT 2", 2),
    ("SELECT ';'", 1),
    ("SELECT 'it''s; fine'", 1),
    ("SELECT E'a\\';b'; SELECT 2", 2),
    ('SELECT "a;b" FROM t', 1),
    ("SELECT $$a;b$$", 1),
    ("SELECT $tag$a;b$tag$; SELECT 2", 2),
    ("SELECT $1; SELECT 2", 2),
    ("SELECT 1 -- ; x\n", 1),
    ("SELECT 1 /* ; /* nested ; */ ; */", 1),
    ("SELECT 1;  -- trailing comment", 1),
    ("", 0),
    ("   ", 0),
    ("-- only a comment", 0),
    ("/* c */ ;", 0),
    (";;", 0),
])
def test_count_statements_counts_pieces_outside_quotes_and_comments_ac_195_3(sql, n):  # AC-195.3
    from dbquery import count_statements
    assert count_statements(sql) == n


# ======================= AC-195.4: refusals change nothing and say why =======================

def refused(repo, kube, capsys, sql="SELECT 1", *extra, env="dev", name="orders-db", pod=None):
    before = tree_state(repo)
    rc, out, err = query(repo, capsys, sql, *extra, env=env, name=name)
    assert rc == 1 and out == "", (out, err)
    assert "ERROR:" in err and "fix:" in err, err
    assert tree_state(repo) == before and kube.writes() == []
    if pod is not None:
        assert pod.execs == []
    return err


def test_an_env_that_is_not_dev_staging_or_prod_is_refused_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = world(kube)
    assert "--env must be dev, staging or prod" in refused(repo, kube, capsys, env="qa", pod=pod)


def test_a_name_that_is_not_a_resource_is_refused_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = world(kube)
    err = refused(repo, kube, capsys, name="nope", pod=pod)
    assert "nope is not a resource of the system (resources: orders-db, backups)" in err and "/system:status" in err


def test_a_resource_that_is_not_a_database_is_refused_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = world(kube)
    err = refused(repo, kube, capsys, name="backups", pod=pod)
    assert "backups is a bucket: /resource:query reads databases only" in err


def test_an_environment_without_an_instance_is_refused_ac_195_4(tmp_path, kube, capsys):  # AC-195.4
    from resources_fixtures import comp
    repo = make_repo(tmp_path, bdoc(dbb={"dev": DEV}, comps={"api": comp("api", ["orders-db", "backups"], envs=("dev",))}))
    pod = world(kube, ns="shop-prod")
    err = refused(repo, kube, capsys, env="prod", pod=pod)
    assert "orders-db has no instance in prod (no component that runs in prod uses it)" in err and "it runs in: dev" in err


def test_an_external_database_is_refused_ac_195_4(tmp_path, kube, capsys):  # AC-195.4
    repo = make_repo(tmp_path, bdoc(dbb={"dev": DEV}, db_kw={"instances": {"prod": {"external": True}}}))
    pod = world(kube, ns="shop-prod")
    err = refused(repo, kube, capsys, env="prod", pod=pod)
    assert "orders-db in prod is an external database: /resource:query reads only databases the platform runs" in err
    assert "provider's tools" in err


@pytest.mark.parametrize("sql", ["", "   ", "-- nothing", "/* nothing */;"])
def test_a_statement_that_holds_no_sql_is_refused_ac_195_4(repo, kube, capsys, sql):  # AC-195.4
    pod = world(kube)
    assert "no SQL statement given" in refused(repo, kube, capsys, sql, pod=pod)


@pytest.mark.parametrize("value", ["1", "g0", "gx", "G1", "shop-orders-db-g1", "g"])
def test_a_copy_that_is_not_a_generation_is_refused_ac_195_4(repo, kube, capsys, value):  # AC-195.4
    pod = world(kube)
    assert f"--copy takes a generation like g2, got '{value}'" in refused(repo, kube, capsys, "SELECT 1", "--copy", value, pod=pod)


def test_a_copy_that_does_not_exist_lists_the_existing_copies_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = copy_world(repo, kube)
    err = refused(repo, kube, capsys, "SELECT 1", "--copy", "g7", pod=pod)
    assert "orders-db/dev has no copy g7; copies: g1 (restored)" in err and "/system:status" in err


def test_a_copy_without_any_copies_says_none_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = world(kube)
    err = refused(repo, kube, capsys, "SELECT 1", "--copy", "g1", pod=pod)
    assert "orders-db/dev has no copy g1; it has no copies" in err and "/resource:restore orders-db --env dev --to <time>" in err


def test_an_instance_that_is_not_ready_is_refused_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = Pod(kube)
    kube.put("cluster", cnpg_cluster("shop-orders-db", ready=False, message="Setting up primary"))
    err = refused(repo, kube, capsys, pod=pod)
    assert "shop-orders-db is not ready (Setting up primary)" in err and "/system:status" in err


def test_a_cluster_that_cannot_be_read_is_refused_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = Pod(kube)
    err = refused(repo, kube, capsys, pod=pod)
    assert "cannot read the instance shop-orders-db: " in err


def test_credentials_that_cannot_be_read_are_refused_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = world(kube, secret=False)
    err = refused(repo, kube, capsys, pod=pod)
    assert "cannot read the credentials of orders-db/dev (Secret shop-orders-db-app): " in err


def test_credentials_without_a_password_are_refused_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = Pod(kube)
    kube.put("cluster", cnpg_cluster("shop-orders-db"))
    kube.put("secret", {"metadata": {"name": "shop-orders-db-app", "namespace": "shop-dev"}, "data": {"username": b64("u"), "dbname": b64("d")}})
    err = refused(repo, kube, capsys, pod=pod)
    assert "cannot read the credentials of orders-db/dev (Secret shop-orders-db-app): " in err


def test_an_sql_error_prints_the_database_error_and_exits_1_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = world(kube)
    pod.reply = (1, "", 'psql:cplat:1: ERROR:  relation "nope" does not exist\nLINE 1: SELECT * FROM nope\n')
    err = refused(repo, kube, capsys, "SELECT * FROM nope")
    assert 'the database refused the statement (nothing was changed): ERROR:  relation "nope" does not exist' in err
    assert "correct the statement and run it again" in err and "psql:cplat" not in err


def test_a_query_over_60_seconds_is_reported_as_cancelled_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = world(kube)
    pod.reply = (1, "", "psql:cplat:1: ERROR:  canceling statement due to statement timeout\n")
    err = refused(repo, kube, capsys, "SELECT pg_sleep(120)")
    assert "the query ran longer than 60 seconds and was cancelled; nothing was changed" in err
    assert "narrow it (a WHERE clause or LIMIT) and run it again" in err


def test_a_kubectl_timeout_is_reported_as_cancelled_too_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = world(kube)
    pod.reply = (124, "", "kubectl timed out")
    err = refused(repo, kube, capsys, "SELECT pg_sleep(120)")
    assert "the query ran longer than 60 seconds and was cancelled; nothing was changed" in err


def test_a_failure_without_a_database_error_names_the_instance_ac_195_4(repo, kube, capsys):  # AC-195.4
    pod = world(kube)
    pod.reply = (1, "", 'Error from server (NotFound): pods "shop-orders-db-1" not found\n')
    err = refused(repo, kube, capsys)
    assert "cannot run the query on shop-orders-db: " in err and "not found" in err
    assert "check the instance with /system:status" in err


def test_an_invalid_state_file_is_reported_not_ignored_ac_195_4(repo, kube, capsys):  # AC-195.4
    p = write_state(repo, {"next": 2, "clusters": "broken"})
    assert p.is_file()
    pod = world(kube)
    before = tree_state(repo)
    rc, out, err = query(repo, capsys, "SELECT 1", "--copy", "g1")
    assert rc == 1 and out == "" and "ERROR:" in err  # the Contract defines no fix: for a StateError
    assert "restore-state.yaml" in err
    assert tree_state(repo) == before and kube.writes() == [] and pod.execs == []


# ======================= AC-195.5: restore prints a query as its check step =======================

WINDOW = "2026-09-27T03:00:12Z"


def restore_world(kube):
    kube.put("cluster", cnpg_cluster("shop-orders-db"))
    kube.put("objectstore", objectstore({"shop-orders-db": WINDOW}))
    kube.pg_latest = "2026-10-27T10:41:02Z"
    kube.on_apply_k = lambda k, args: k.put("cluster", cnpg_cluster("shop-orders-db-g1"))


def test_restore_prints_the_query_command_as_the_check_step_ac_195_5(repo, kube, capsys):  # AC-195.5
    restore_world(kube)
    rc, out, err = run("resource", "restore", "orders-db", "--env", "dev", "--repo-dir", repo, "--to", "2026-10-27T09:59:00Z", capsys=capsys)
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    assert rc == 0, err
    assert 'check it: /resource:query orders-db --env dev --copy g1 "SELECT …"' in lines
    assert "switch to it: /resource:restore orders-db --env dev --switch" in lines


def test_no_output_of_a_restore_names_kubectl_ac_195_5(repo, kube, capsys):  # AC-195.5
    restore_world(kube)
    rc, out, err = run("resource", "restore", "orders-db", "--env", "dev", "--repo-dir", repo, "--to", "2026-10-27T09:59:00Z", capsys=capsys)
    assert rc == 0, err
    assert "kubectl" not in (out + err).lower()
    assert "check it: /resource:query" in out


def test_a_dry_run_and_the_json_report_of_a_restore_name_no_kubectl_ac_195_5(repo, kube, capsys):  # AC-195.5
    restore_world(kube)
    rc, out, err = run("resource", "restore", "orders-db", "--env", "dev", "--repo-dir", repo, "--to", "2026-10-27T09:59:00Z", "--dry-run", capsys=capsys)
    assert rc == 0, err
    assert "will_do" in out and "kubectl" not in (out + err).lower()
    assert "else applied directly" in out
    rc, out, err = run("resource", "restore", "orders-db", "--env", "dev", "--repo-dir", repo, "--to", "2026-10-27T09:59:00Z", "--json", capsys=capsys)
    assert rc == 0, err
    assert "kubectl" not in (out + err).lower()
