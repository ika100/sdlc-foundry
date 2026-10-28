"""Spec 121 acceptance tests, the platform side: `cplat platform versions` (AC-121.1, .23), `cplat resource upgrade` (AC-121.6 .. .9, .11 ..
.14, .27), its verification (AC-121.8, .15, .16), restore across a major (AC-121.16), the gitops CI check (AC-121.10), the model and
status (AC-121.5, .15), `/platform:update` (AC-121.11, .20 .. .23), doctor (AC-121.18 .. .22), the cluster scripts (AC-121.4, .17), the pin
check, the release check and the release gate (AC-121.2, .23, .24, .26), the workflows and the upgrade e2e script text (AC-121.24, .25),
and the docs, plugins and changelog.

Contract: design.md (every "Contract:" section). Everything runs through `cplat.main` or the modules on hand-built checkouts with a bare
`origin`; `gh` is a script on PATH that records its arguments, the cluster is `FakeKube` behind `backupstate.kubectl`, and time is the
`clock` fixture of backup_fixtures. The upgrade e2e script is only read (it needs a cluster). Domain-like names are matched with word-bounded
regular expressions, never with `"a.b.c" in text`. Refusals must change nothing: HEAD, branches, tree and `gh` calls are compared."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import core
import cplat
from backup_fixtures import clock, kube  # noqa: F401  (fixtures)
from backup_fixtures import cnpg_backup, cnpg_cluster, objectstore
from broker_fixtures import broker, bsys
from cache_fixtures import cache
from resources_fixtures import comp, db, system
from system_fixtures import ROOT, git, mod, render, write_system
from upgrade_fixtures import (APP, CTX, DEV, NATS, OLD_PG, OPERATOR_NAMES, PG, ROW_ORDER, VK, World, applied, backed_up, cluster_file, commit_all, make_world,
                              pg_cluster, put_system, read_system, record, render_module, rerender_commit, secret, snapshot, table_rows, ts, upgrade_doc)

T = ROOT / "templates" / "gitops-app"
CLUSTER_T = ROOT / "templates" / "cluster-gitops"
TIME_LATEST = "<time|latest>"


def run_cmd(capsys, *argv):
    rc = cplat.main([*map(str, argv)])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def body_lines(pr) -> list[str]:
    return pr["body"].splitlines()


# ---------------- AC-121.1 / .23: cplat platform versions ----------------

def test_versions_prints_the_release_and_one_line_per_row_ac_121_1(capsys):  # AC-121.1
    rc, out, err = run_cmd(capsys, "platform", "versions")
    assert rc == 0, err
    lines = out.splitlines()
    assert lines[0] == f"versions table of platform {core.platform_version()}"
    body = [ln for ln in lines[1:] if ln.strip()]
    assert len(body) == len(ROW_ORDER) and all(ln.startswith("  ") for ln in body)


def cols(line: str) -> list[str]:
    return re.split(r"\s{2,}", line.strip())


def test_versions_text_columns_are_kind_name_version_ref_and_digest_ac_121_1(capsys):  # AC-121.1
    rc, out, _ = run_cmd(capsys, "platform", "versions")
    lines = {cols(ln)[1]: cols(ln) for ln in out.splitlines()[1:] if ln.strip()}
    assert lines["postgres 15 (deprecated)"] == ["image", "postgres 15 (deprecated)", "15.19", "ghcr.io/cloudnative-pg/postgresql:15.19-202610260819-standard-trixie",
                                                  "sha256:f617efc0…"]
    assert lines["postgres 17"] == ["image", "postgres 17", "17.11", "ghcr.io/cloudnative-pg/postgresql:17.11-202610260819-standard-trixie", "sha256:ed6923f9…"]
    assert lines["valkey 9"][:3] == ["image", "valkey 9", "9.1.3"] and lines["valkey 9"][4] == "sha256:3add1a33…"
    assert lines["nats"] == ["chart", "nats", "2.15.1", "https://nats-io.github.io/k8s/helm/charts nats"]
    assert lines["argo-cd"][:3] == ["manifest", "argo-cd", "v3.4.12"] and len(lines["argo-cd"]) == 4


def test_versions_text_prints_an_operator_row_with_its_operator_and_crds_ac_121_1(capsys):  # AC-121.1
    rc, out, _ = run_cmd(capsys, "platform", "versions")
    line = next(ln for ln in out.splitlines() if re.match(r"\s+chart\s+operator cloudnative-pg\b", ln))
    c = cols(line)
    assert c[:3] == ["chart", "operator cloudnative-pg", "0.29.1"] and c[3] == "https://cloudnative-pg.github.io/charts cloudnative-pg" and c[4] == "operator 1.30.1"
    assert re.match(r"crds clusters\.postgresql\.cnpg\.io v1\b", c[5])


def test_versions_lists_the_rows_in_the_table_order_ac_121_1(capsys):  # AC-121.1
    rc, out, _ = run_cmd(capsys, "platform", "versions")
    names = [cols(ln)[1].removesuffix(" (deprecated)") for ln in out.splitlines()[1:] if ln.strip()]
    assert names == ROW_ORDER


def test_versions_json_prints_the_release_and_the_rows_with_full_digests_ac_121_1(capsys):  # AC-121.1
    rc, out, _ = run_cmd(capsys, "platform", "versions", "--json")
    d = json.loads(out)
    assert rc == 0 and list(d) == ["release", "rows"] and d["release"] == core.platform_version()
    assert d["rows"] == table_rows() and next(r for r in d["rows"] if r["name"] == "postgres 17")["digest"] == PG[17].split("@")[1]


def test_versions_changelog_of_the_same_ref_prints_nothing_ac_121_23(capsys):  # AC-121.23
    rc, out, err = run_cmd(capsys, "platform", "versions", "--diff", "HEAD", "--changelog")
    assert rc == 0, err
    assert out.strip() == ""


def test_versions_diff_against_the_last_release_lists_added_and_changed_rows_ac_121_23(capsys):  # AC-121.23
    if subprocess.run(["git", "rev-parse", "-q", "--verify", "v5.3.0"], cwd=ROOT, capture_output=True).returncode != 0:
        pytest.skip("tag v5.3.0 is not available in this checkout")
    rc, out, err = run_cmd(capsys, "platform", "versions", "--diff", "v5.3.0")
    assert rc == 0, err
    lines = out.splitlines()
    assert lines and all(re.match(r"(changed|added|removed|crds) \S", ln) for ln in lines), lines
    assert any(re.match(r"changed postgres 17: 17\.11 \(digest \w{8}\) → 17\.11 \(digest ", ln) or re.match(r"changed postgres 17: ", ln) for ln in lines)
    assert any(ln.startswith("added argo-cd: ") for ln in lines) and any(ln.startswith("added k3s: ") for ln in lines)


def test_versions_changelog_lines_are_markdown_list_items_ac_121_23(capsys):  # AC-121.23
    if subprocess.run(["git", "rev-parse", "-q", "--verify", "v5.3.0"], cwd=ROOT, capture_output=True).returncode != 0:
        pytest.skip("tag v5.3.0 is not available in this checkout")
    rc, out, _ = run_cmd(capsys, "platform", "versions", "--diff", "v5.3.0", "--changelog")
    lines = out.splitlines()
    assert rc == 0 and lines and all(ln.startswith("- `") for ln in lines)
    assert "- `argo-cd` v3.4.12 (new)" in lines
    assert any(re.fullmatch(r"- `postgres 17` 17\.11 → 17\.11", ln) or ln.startswith("- `postgres 17` ") for ln in lines)


def test_versions_diff_with_an_unreadable_ref_exits_1_ac_121_23(capsys):  # AC-121.23
    rc, out, err = run_cmd(capsys, "platform", "versions", "--diff", "no-such-ref-121")
    assert rc == 1 and re.search(r"cannot read the versions table at no-such-ref-121: \S", err)


# ---------------- gitops checkouts for resource upgrade ----------------

@pytest.fixture()
def fake(tmp_path, monkeypatch, kube, clock):   # noqa: F811
    """A committed three-environment checkout (orders-db 16 with backups) with an origin, a recording gh and an in-memory cluster."""
    w = make_world(tmp_path, monkeypatch, upgrade_doc(16))
    w.kube = kube
    return w


def args(w, *rest, ctx=True):
    return ["resource", "upgrade", *rest, "--repo-dir", str(w.repo), *(["--context", CTX] if ctx else [])]


def step_state(w, dev=None, staging=None, version=16, promote=None, records=(), minutes=30, held=()):
    """Put the checkout into a state: instances.<env>.version per `dev`/`staging`, verified records, backups, held files (committed)."""
    inst = {e: {"version": v} for e, v in (("dev", dev), ("staging", staging)) if v}
    rerender_commit(w.repo, upgrade_doc(version, promote=promote, instances=inst))
    for env in held:
        p = w.repo / APP / "addons" / env / "orders-db" / "cluster.yaml"
        p.write_text(re.sub(r"imageName: \S+", f"imageName: {OLD_PG[version]}", p.read_text()))
    commit_all(w.repo, "held")
    for env, major in records:
        w.kube.put("configmap", record(env, str(major), state="verified"))
    if minutes is not False:
        backed_up(w.kube, minutes_ago=minutes)
    return w


def refused(w, capsys, argv, *needles, hint=None):
    """The command fails with exit 1, names every needle, and changes nothing (HEAD, branches, tree, gh)."""
    before, calls = snapshot(w.repo), len(w.calls())
    rc, out, err = run_cmd(capsys, *argv)
    assert rc == 1, f"expected exit 1, got {rc}: {out}{err}"
    for n in needles:
        assert n in err, f"{n!r} not in: {err}"
    if hint:
        assert f"  fix: {hint}" in err.splitlines(), err
    assert snapshot(w.repo) == before and len(w.calls()) == calls, "a refusal changes nothing"
    return err


def branch_doc(w, name) -> dict:
    return yaml.safe_load(git(w.repo, "show", f"{name}:{APP}/system.yaml"))


# ---------------- AC-121.6: the dev step ----------------

def test_the_dev_step_opens_one_pr_that_sets_the_dev_version_only_ac_121_6(fake, capsys):  # AC-121.6
    backed_up(fake.kube)
    main = fake.main_head()
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--pr"))
    assert rc == 0, err
    assert len(fake.prs()) == 1 and "resource/upgrade-orders-db-dev-17" in fake.branches()
    doc = branch_doc(fake, "resource/upgrade-orders-db-dev-17")
    db_ = doc["resources"]["orders-db"]
    assert db_["version"] == 16 and db_["instances"]["dev"]["version"] == 17
    assert "version" not in db_["instances"]["staging"] and "version" not in db_["instances"]["prod"]
    assert fake.main_head() == main, "main is untouched until the PR is merged"


def test_the_pr_title_and_description_name_environment_majors_and_the_image_ac_121_6(fake, capsys):  # AC-121.6
    stamp = backed_up(fake.kube)
    run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--pr"))
    [pr] = fake.prs()
    assert pr["title"] == "feat(resource): upgrade orders-db to 17 in dev"
    assert body_lines(pr)[:5] == [
        "Upgrade orders-db (database) in dev: 16 → 17",
        f"image: {PG[16]} → {PG[17]}",
        f"backup: last successful {stamp} (within 60 minutes)",
        f"after the merge: the platform waits up to 15 minutes for orders-db to be healthy on {PG[17]}, then runs the smoke tests of api (dev)",
        "next: /resource:upgrade orders-db --to 17 --env staging"]


def test_the_branch_commit_is_signed_off_and_changes_dev_files_only_ac_121_6(fake, capsys):  # AC-121.6
    backed_up(fake.kube)
    run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--pr"))
    branch = "resource/upgrade-orders-db-dev-17"
    assert re.search(r"(?m)^Signed-off-by: \S", git(fake.repo, "log", "-1", "--format=%B", branch))
    changed = git(fake.repo, "diff", "--name-only", f"main...{branch}").split()
    assert APP + "/system.yaml" in changed and APP + "/addons/dev/orders-db/cluster.yaml" in changed
    assert not [c for c in changed if "/addons/staging/" in c or "/addons/prod/" in c]
    assert yaml.safe_load(git(fake.repo, "show", f"{branch}:{APP}/addons/dev/orders-db/cluster.yaml"))["spec"]["imageName"] == PG[17]
    assert "# the shop system (keep this comment)" in git(fake.repo, "show", f"{branch}:{APP}/system.yaml")


def test_the_step_without_pr_leaves_the_tree_changed_and_says_how_to_verify_ac_121_6(fake, capsys):  # AC-121.6
    backed_up(fake.kube)
    head = git(fake.repo, "rev-parse", "HEAD")
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17"))
    assert rc == 0, err
    assert git(fake.repo, "rev-parse", "HEAD") == head and fake.prs() == []
    status = git(fake.repo, "status", "--porcelain")
    assert "applications/shop/system.yaml" in status and "addons/dev/orders-db/cluster.yaml" in status
    assert re.search(r"wrote the dev step: .+; apply it, then verify: cplat resource upgrade orders-db --verify --env dev", out)
    assert read_system(fake.repo)["resources"]["orders-db"]["instances"]["dev"]["version"] == 17


def test_the_step_defaults_to_the_first_environment_with_an_instance_ac_121_6(fake, capsys):  # AC-121.6
    doc = upgrade_doc(16)
    doc["components"]["api"]["instances"] = {"staging": {}, "prod": {}}
    doc["resources"]["orders-db"]["instances"]["dev"].pop("backup")
    rerender_commit(fake.repo, doc)
    backed_up(fake.kube)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--pr"))
    assert rc == 0, err
    assert fake.prs()[0]["title"] == "feat(resource): upgrade orders-db to 17 in staging"


def test_dry_run_writes_nothing_and_json_describes_the_step_ac_121_6(fake, capsys):  # AC-121.6
    backed_up(fake.kube)
    before = snapshot(fake.repo)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--dry-run", "--json"))
    assert rc == 0, err
    assert snapshot(fake.repo) == before and fake.calls() == []
    d = json.loads(out)
    assert d == {"step": "major", "resource": "orders-db", "type": "database", "env": "dev", "from": {"major": 16, "ref": PG[16]},
                 "to": {"major": 17, "ref": PG[17]}, "pr": None, "verification": None, "next": "/resource:upgrade orders-db --to 17 --env staging"}


def test_the_json_of_a_pr_names_its_url_ac_121_6(fake, capsys):  # AC-121.6
    backed_up(fake.kube)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--pr", "--json"))
    assert rc == 0, err
    assert json.loads(out)["pr"] == "https://github.com/acme/shop-gitops/pull/7"


def test_a_database_major_step_with_a_backup_starts_a_new_archive_ac_121_6(fake, capsys):  # AC-121.6
    backed_up(fake.kube)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17"))
    assert rc == 0, err
    state = yaml.safe_load((fake.repo / APP / "addons/dev/orders-db/restore-state.yaml").read_text())
    assert state == {"next": 1, "clusters": [{"name": "shop-orders-db", "role": "active"}],
                     "archives": [{"server": "shop-orders-db", "major": 16}, {"server": "shop-orders-db-pg17", "major": 17}]}
    params = cluster_file(fake.repo, "dev")["spec"]["plugins"][0]["parameters"]
    assert params == {"barmanObjectName": "shop-orders-db", "serverName": "shop-orders-db-pg17"}
    assert not (fake.repo / APP / "addons/staging/orders-db/restore-state.yaml").exists()


def test_a_second_major_step_appends_to_the_archives_ac_121_6(fake, capsys):  # AC-121.6
    backed_up(fake.kube)
    run_cmd(capsys, *args(fake, "orders-db", "--to", "17"))
    commit_all(fake.repo, "step")
    run_cmd(capsys, *args(fake, "orders-db", "--to", "18"))
    state = yaml.safe_load((fake.repo / APP / "addons/dev/orders-db/restore-state.yaml").read_text())
    assert [a["major"] for a in state["archives"]] == [16, 17, 18] and state["archives"][-1]["server"] == "shop-orders-db-pg18"


# ---------------- AC-121.7: staging, prod and the folding step ----------------

def test_the_staging_step_moves_staging_after_a_verified_dev_ac_121_7(fake, capsys):  # AC-121.7
    step_state(fake, dev=17, records=[("dev", 17)])
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--env", "staging", "--pr"))
    assert rc == 0, err
    doc = branch_doc(fake, "resource/upgrade-orders-db-staging-17")
    inst = doc["resources"]["orders-db"]["instances"]
    assert inst["dev"]["version"] == 17 and inst["staging"]["version"] == 17 and "version" not in inst["prod"]
    [pr] = fake.prs()
    assert pr["title"] == "feat(resource): upgrade orders-db to 17 in staging"
    assert body_lines(pr)[0] == "Upgrade orders-db (database) in staging: 16 → 17"


def test_the_prod_step_folds_the_entries_into_the_resource_version_ac_121_7(fake, capsys):  # AC-121.7
    step_state(fake, dev=17, staging=17, records=[("dev", 17), ("staging", 17)])
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--env", "prod", "--pr"))
    assert rc == 0, err
    res = branch_doc(fake, "resource/upgrade-orders-db-prod-17")["resources"]["orders-db"]
    assert res["version"] == 17
    assert all("version" not in res["instances"][e] for e in ("dev", "staging", "prod"))
    assert all(res["instances"][e]["backup"] == DEV for e in ("dev", "staging", "prod")), "the other instance keys stay"


def test_a_folded_instance_left_empty_is_removed_ac_121_7(tmp_path, monkeypatch, kube, clock):  # noqa: F811  # AC-121.7
    # a cache has no backup: its entries hold only `version`, so folding leaves nothing and the instances key goes
    cdoc = system({"sessions": cache(version=8, instances={"dev": {"version": 9}, "staging": {"version": 9}})}, {"api": comp("api", ["sessions"])})
    w = make_world(tmp_path, monkeypatch, cdoc)
    w.kube = kube
    kube.put("configmap", record("dev", "9", image=VK[9], resource="sessions", state="verified"), record("staging", "9", image=VK[9], resource="sessions", state="verified"))
    rc = cplat.main(["resource", "upgrade", "sessions", "--to", "9", "--env", "prod", "--repo-dir", str(w.repo), "--context", CTX, "--pr"])
    assert rc == 0
    res = branch_doc(w, "resource/upgrade-sessions-prod-9")["resources"]["sessions"]
    assert res["version"] == 9 and "instances" not in res


# ---------------- AC-121.9: the earlier environment must be ready ----------------

def test_staging_is_refused_while_dev_runs_the_old_major_ac_121_9(fake, capsys):  # AC-121.9
    step_state(fake)
    refused(fake, capsys, args(fake, "orders-db", "--to", "17", "--env", "staging"),
            f"dev is not ready for staging: orders-db in dev runs 16 ({PG[16]}), not 17 ({PG[17]})", hint="/resource:upgrade orders-db --to 17")


def test_staging_is_refused_while_dev_is_not_verified_ac_121_9(fake, capsys):  # AC-121.9
    step_state(fake, dev=17)
    refused(fake, capsys, args(fake, "orders-db", "--to", "17", "--env", "staging"),
            "dev is not ready for staging: orders-db in dev is on 17 but not verified", hint="cplat resource upgrade orders-db --verify --env dev")


def test_staging_is_refused_after_a_failed_verification_naming_the_check_ac_121_9(fake, capsys):  # AC-121.9
    step_state(fake, dev=17)
    fake.kube.put("configmap", record("dev", "17", state="failed", check="smoke api", at="2026-10-28T10:00:00Z"))
    refused(fake, capsys, args(fake, "orders-db", "--to", "17", "--env", "staging"),
            "dev is not ready for staging: orders-db in dev failed its verification at 2026-10-28T10:00:00Z (smoke api)",
            hint="cplat resource upgrade orders-db --verify --env dev")


def test_a_verification_of_another_image_does_not_count_ac_121_9(fake, capsys):  # AC-121.9
    step_state(fake, dev=17)
    fake.kube.put("configmap", record("dev", "17", image=PG[16] + "x", state="verified"))
    refused(fake, capsys, args(fake, "orders-db", "--to", "17", "--env", "staging"), "dev is not ready for staging: orders-db in dev is on 17 but not verified")


def test_prod_is_refused_while_staging_is_behind_and_the_hint_names_the_environment_ac_121_9(fake, capsys):  # AC-121.9
    step_state(fake, dev=17, records=[("dev", 17)])
    refused(fake, capsys, args(fake, "orders-db", "--to", "17", "--env", "prod"),
            f"staging is not ready for prod: orders-db in staging runs 16 ({PG[16]}), not 17 ({PG[17]})", hint="/resource:upgrade orders-db --to 17 --env staging")


def test_an_unreadable_record_is_reported_with_the_context_hint_ac_121_9(fake, capsys):  # AC-121.9
    step_state(fake, dev=17, minutes=False)
    fake.kube.error = (1, "Unable to connect to the server")
    err = refused(fake, capsys, args(fake, "orders-db", "--to", "17", "--env", "staging"), "dev is not ready for staging: orders-db in dev cannot be read (")
    assert "  fix: pass --context dev=<ctx>" in err.splitlines()


def test_the_nearest_earlier_environment_with_an_instance_is_checked_ac_121_9(fake, capsys):  # AC-121.9
    doc = upgrade_doc(16, instances={"dev": {"version": 17}})
    doc["components"]["api"]["instances"] = {"dev": {}, "prod": {}}
    doc["resources"]["orders-db"]["instances"]["staging"].pop("backup")
    rerender_commit(fake.repo, doc)
    backed_up(fake.kube)
    fake.kube.put("configmap", record("dev", "17", state="verified"))
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--env", "prod", "--pr"))
    assert rc == 0, err
    assert body_lines(fake.prs()[0])[0] == "Upgrade orders-db (database) in prod: 16 → 17"


# ---------------- AC-121.11: pin moves and held pins ----------------

def test_a_pin_move_replaces_the_rendered_pin_and_leaves_system_yaml_alone_ac_121_11(fake, capsys):  # AC-121.11
    step_state(fake, records=[("dev", 16)], held=("staging",), minutes=False)
    record_dev = fake.kube.store["configmap"][0]
    assert record_dev["data"]["image"] == PG[16]
    text_before = (fake.repo / APP / "system.yaml").read_text()
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "16", "--env", "staging"))
    assert rc == 0, err
    assert cluster_file(fake.repo, "staging")["spec"]["imageName"] == PG[16]
    assert (fake.repo / APP / "system.yaml").read_text() == text_before
    assert render(fake.repo, "--check").returncode == 0, "the render keeps the moved pin"


def test_a_pin_move_needs_no_backup_and_reads_none_ac_121_11(fake, capsys):  # AC-121.11
    step_state(fake, records=[("dev", 16)], held=("staging",), minutes=False)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "16", "--env", "staging"))
    assert rc == 0, err
    assert not [c for c in fake.kube.calls if re.search(r"backup|objectstore|exec", " ".join(c[0]))], "no backup was read"


def test_a_pin_move_pr_has_its_own_title_and_description_ac_121_11(fake, capsys):  # AC-121.11
    step_state(fake, records=[("dev", 16)], held=("staging",), minutes=False)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "16", "--env", "staging", "--pr"))
    assert rc == 0, err
    [pr] = fake.prs()
    assert pr["title"] == "chore(resource): move orders-db to 16.15 in staging"
    lines = body_lines(pr)
    assert lines[0] == "Move orders-db (database) in staging to this release's 16 pin"
    assert lines[1] == f"image: {OLD_PG[16]} → {PG[16]}"
    assert any(re.search(r"\bno backup check \(minor or patch move\)", ln) for ln in lines)
    assert "resource/upgrade-orders-db-staging-16" in fake.branches()
    changed = git(fake.repo, "diff", "--name-only", "main...resource/upgrade-orders-db-staging-16").split()
    assert changed == [APP + "/addons/staging/orders-db/cluster.yaml"]


def test_a_move_to_the_pin_that_runs_already_does_nothing_and_exits_0_ac_121_11(fake, capsys):  # AC-121.11
    step_state(fake, minutes=False)
    before = snapshot(fake.repo)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "16", "--env", "dev", "--pr"))
    assert rc == 0, err
    assert f"orders-db in dev already runs {PG[16]}; nothing to do" in out.splitlines()
    assert snapshot(fake.repo) == before and fake.prs() == []


def test_a_major_step_on_a_held_environment_asks_for_the_pin_move_first_ac_121_11(fake, capsys):  # AC-121.11
    step_state(fake, dev=17, records=[("dev", 17)], held=("staging",))
    refused(fake, capsys, args(fake, "orders-db", "--to", "17", "--env", "staging"),
            f"orders-db in staging still runs {OLD_PG[16]} from an earlier platform release; move it to this release's 16 pin first",
            hint="/resource:upgrade orders-db --to 16 --env staging")


# ---------------- AC-121.12: the backup guard ----------------

def test_a_database_without_a_backup_key_cannot_take_a_major_step_ac_121_12(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.12
    w = make_world(tmp_path, monkeypatch, upgrade_doc(16, backup=False))
    w.kube = kube
    refused(w, capsys, args(w, "orders-db", "--to", "17"), "orders-db in dev has no backup: resources.orders-db.instances.dev.backup is required for a major upgrade",
            hint="set it in system.yaml, then /resource:backup orders-db --env dev")


def test_a_backup_that_never_succeeded_refuses_the_step_in_dev_too_ac_121_12(fake, capsys):  # AC-121.12
    backed_up(fake.kube, minutes_ago=None)
    refused(fake, capsys, args(fake, "orders-db", "--to", "17"),
            "orders-db in dev: the last successful backup is never (more than 60 minutes ago); a major upgrade needs one from the last 60 minutes",
            hint="take one now: /resource:backup orders-db --env dev")


def test_a_backup_older_than_60_minutes_refuses_naming_its_time_ac_121_12(fake, capsys):  # AC-121.12
    stamp = backed_up(fake.kube, minutes_ago=65)
    refused(fake, capsys, args(fake, "orders-db", "--to", "17"),
            f"orders-db in dev: the last successful backup is {stamp} (more than 60 minutes ago); a major upgrade needs one from the last 60 minutes",
            hint="take one now: /resource:backup orders-db --env dev")


def test_a_backup_55_minutes_old_is_recent_enough_ac_121_12(fake, capsys):  # AC-121.12
    backed_up(fake.kube, minutes_ago=55)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17"))
    assert rc == 0, err


def test_the_guard_applies_to_the_staging_step_with_its_own_environment_ac_121_12(fake, capsys):  # AC-121.12
    step_state(fake, dev=17, records=[("dev", 17)], minutes=False)
    stamp = backed_up(fake.kube, envs=("dev", "prod"), minutes_ago=10)
    fake.kube.put("cluster", cnpg_cluster("shop-orders-db", "shop-staging"))
    fake.kube.put("objectstore", objectstore({"shop-orders-db": ts(120)}, "shop-orders-db", "shop-staging"))
    fake.kube.put("cnpg.backup", cnpg_backup("old", ns="shop-staging", stopped=ts(120)))
    refused(fake, capsys, args(fake, "orders-db", "--to", "17", "--env", "staging"), "orders-db in staging: the last successful backup is ",
            hint="take one now: /resource:backup orders-db --env staging")
    assert stamp


def test_an_unreadable_cluster_names_the_backups_that_cannot_be_read_ac_121_12(fake, capsys):  # AC-121.12
    fake.kube.error = (1, "Unable to connect to the server")
    err = refused(fake, capsys, args(fake, "orders-db", "--to", "17"), "cannot read the backups of orders-db in dev: ")
    assert re.search(r"(?m)^  fix: check the kube context: cplat system status --context dev=\S+$", err)


def test_the_backup_is_read_the_way_system_status_reports_it_ac_121_12(fake, capsys):  # AC-121.12
    stamp = backed_up(fake.kube)
    import status
    got = status.public_backups(status.collect_backups(fake.repo, None, [CTX]))
    entry = next(i for i in got["resource_instances"] if (i["resource"], i["environment"]) == ("orders-db", "dev"))
    assert entry["backup"]["last_success"] == stamp
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "17", "--dry-run"))
    assert rc == 0, err


# ---------------- AC-121.13 / .14: external, downgrade, unknown ----------------

def test_an_external_instance_is_refused_with_the_owner_text_ac_121_13(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.13
    doc = upgrade_doc(16, instances={"prod": {"external": True}})
    doc["resources"]["orders-db"]["instances"]["prod"].pop("backup")
    w = make_world(tmp_path, monkeypatch, doc)
    w.kube = kube
    refused(w, capsys, args(w, "orders-db", "--to", "17", "--env", "prod"), "orders-db is external in prod: its owner upgrades it, the platform does not")


def test_an_external_dev_is_refused_by_default_too_ac_121_13(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.13
    doc = upgrade_doc(16, instances={"dev": {"external": True}})
    doc["resources"]["orders-db"]["instances"]["dev"].pop("backup")
    w = make_world(tmp_path, monkeypatch, doc)
    w.kube = kube
    refused(w, capsys, args(w, "orders-db", "--to", "17"), "orders-db is external in dev: its owner upgrades it, the platform does not")


def test_a_downgrade_of_a_database_names_the_restore_ac_121_14(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.14
    w = make_world(tmp_path, monkeypatch, upgrade_doc(17))
    w.kube = kube
    backed_up(kube)
    refused(w, capsys, args(w, "orders-db", "--to", "16"), "orders-db in dev is on 17; 16 is lower and /resource:upgrade only moves up",
            hint=f"the way back for a database is /resource:restore orders-db --env dev --to {TIME_LATEST}")


def test_a_cache_downgrade_is_refused_without_a_restore_hint_ac_121_14(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.14
    w = make_world(tmp_path, monkeypatch, system({"sessions": cache(version=9)}, {"api": comp("api", ["sessions"])}))
    w.kube = kube
    err = refused(w, capsys, args(w, "sessions", "--to", "8"), "sessions in dev is on 9; 8 is lower and /resource:upgrade only moves up")
    assert "resource:restore" not in err


def test_a_version_outside_the_table_names_the_supported_ones_ac_121_14(fake, capsys):  # AC-121.14
    backed_up(fake.kube)
    refused(fake, capsys, args(fake, "orders-db", "--to", "19"), "version '19' is not a supported database version (15, 16, 17, 18)")


def test_a_move_to_the_same_major_is_not_a_downgrade_ac_121_14(fake, capsys):  # AC-121.14
    step_state(fake, minutes=False)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "16", "--env", "dev"))
    assert rc == 0 and "lower" not in err


def test_every_upward_postgres_jump_is_supported_ac_121_14(fake, capsys):  # AC-121.14
    backed_up(fake.kube)
    rc, out, err = run_cmd(capsys, *args(fake, "orders-db", "--to", "18", "--dry-run", "--json"))
    assert rc == 0, err
    assert json.loads(out)["to"] == {"major": 18, "ref": PG[18]}


def test_the_checks_run_in_the_designed_order_ac_121_14(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.14
    w = make_world(tmp_path, monkeypatch, upgrade_doc(17, backup=False))
    w.kube = kube
    err = refused(w, capsys, args(w, "orders-db", "--to", "16"), "is lower and /resource:upgrade only moves up")
    assert "has no backup" not in err, "the downgrade (7) comes before the backup (13)"
    refused(w, capsys, args(w, "nope", "--to", "17"), "nope is not a resource of the system (resources: orders-db, backups)")
    refused(w, capsys, args(w, "backups", "--to", "1"),
            "backups is a bucket: it has no version; its SeaweedFS image moves with the platform release (/platform:update, dev first)")


def test_an_environment_with_no_instance_is_refused_ac_121_9(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.9
    doc = upgrade_doc(16)
    doc["components"]["api"]["instances"] = {"dev": {}}
    for e in ("staging", "prod"):
        doc["resources"]["orders-db"]["instances"][e].pop("backup")
    w = make_world(tmp_path, monkeypatch, doc)
    w.kube = kube
    refused(w, capsys, args(w, "orders-db", "--to", "17", "--env", "staging"), "orders-db has no instance in staging (no component that runs in staging uses it)")


def test_a_bad_env_is_refused_ac_121_9(fake, capsys):  # AC-121.9
    refused(fake, capsys, args(fake, "orders-db", "--to", "17", "--env", "qa"), "--env must be dev, staging or prod")


def test_a_dirty_tree_is_refused_with_the_clean_tree_text_ac_121_9(fake, capsys):  # AC-121.9
    backed_up(fake.kube)
    (fake.repo / "notes.txt").write_text("x")
    err = refused(fake, capsys, args(fake, "orders-db", "--to", "17"), "the working tree has uncommitted changes")
    assert fake.prs() == []


# ---------------- AC-121.27: no backup for cache and broker ----------------

def csetup(tmp_path, monkeypatch, kube, version=8):
    w = make_world(tmp_path, monkeypatch, system({"sessions": cache(version=version)}, {"api": comp("api", ["sessions"])}))
    w.kube = kube
    return w


def test_a_cache_major_step_reads_no_backup_and_says_it_has_none_ac_121_27(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.27
    w = csetup(tmp_path, monkeypatch, kube)
    rc, out, err = run_cmd(capsys, *args(w, "sessions", "--to", "9", "--pr"))
    assert rc == 0, err
    [pr] = w.prs()
    assert pr["title"] == "feat(resource): upgrade sessions to 9 in dev"
    lines = body_lines(pr)
    assert lines[0] == "Upgrade sessions (cache) in dev: 8 → 9" and lines[1] == f"image: {VK[8]} → {VK[9]}"
    assert any(re.search(r"\bsessions has no backup\b", ln) for ln in lines) and not any(ln.startswith("backup: last successful") for ln in lines)
    assert not [c for c in kube.calls if re.search(r"backup|objectstore|cluster", " ".join(c[0]))], "no backup was read"
    assert branch_doc(w, "resource/upgrade-sessions-dev-9")["resources"]["sessions"]["instances"]["dev"]["version"] == 9


def test_a_cache_step_writes_no_restore_state_ac_121_27(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.27
    w = csetup(tmp_path, monkeypatch, kube)
    rc, out, err = run_cmd(capsys, *args(w, "sessions", "--to", "9"))
    assert rc == 0, err
    assert read_system(w.repo)["resources"]["sessions"]["instances"]["dev"]["version"] == 9
    assert not list((w.repo / APP).rglob("restore-state.yaml"))


def test_a_broker_major_step_says_it_has_no_backup_and_writes_a_string_version_ac_121_27(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.27
    w = make_world(tmp_path, monkeypatch, bsys({"bus": broker(version="2.14")}))
    w.kube = kube
    rc, out, err = run_cmd(capsys, *args(w, "bus", "--to", "2.15", "--pr"))
    assert rc == 0, err
    [pr] = w.prs()
    assert any(re.search(r"\bbus has no backup\b", ln) for ln in body_lines(pr))
    assert body_lines(pr)[0] == "Upgrade bus (broker) in dev: 2.14 → 2.15"
    assert branch_doc(w, "resource/upgrade-bus-dev-2.15")["resources"]["bus"]["instances"]["dev"]["version"] == "2.15"


def test_a_bucket_cannot_be_upgraded_ac_121_27(fake, capsys):  # AC-121.27
    refused(fake, capsys, args(fake, "backups", "--to", "2"),
            "backups is a bucket: it has no version; its SeaweedFS image moves with the platform release (/platform:update, dev first)")


def test_the_step_of_a_cache_needs_the_earlier_environment_verified_too_ac_121_27(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.27
    w = csetup(tmp_path, monkeypatch, kube)
    refused(w, capsys, args(w, "sessions", "--to", "9", "--env", "staging"), f"dev is not ready for staging: sessions in dev runs 8 ({VK[8]}), not 9 ({VK[9]})")


# ---------------- verification (AC-121.8, .15, .16) ----------------

class Smoke:
    """Replaces smoke.run_smoke: a component whose directory is named in `fail` is red, every other one passes with 2 tests."""

    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, repo, base_url, *, env="dev", **kw):
        import smoke
        self.calls.append((Path(repo).name, base_url, env))
        if Path(repo).name in self.fail:
            return smoke.SmokeResult(env, "red", base_url, failed=1, failing=["forced"], tests=[{"id": "forced", "result": "FAIL"}])
        return smoke.SmokeResult(env, "passed", base_url, passed=2, tests=[{"id": "a", "result": "PASS"}, {"id": "b", "result": "PASS"}])

    def components(self):
        return [c[0] for c in self.calls]


def component_dirs(root: Path, names=("api", "web", "other")) -> Path:
    for c in names:
        (root / c).mkdir(parents=True, exist_ok=True)
        (root / c / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"smoke": "true"}}}))
    return root


def fake_smoke(w, monkeypatch, dirs: Path, names=("api", "web", "other")):
    import smoke
    w.smoke = Smoke()
    monkeypatch.setattr(smoke, "run_smoke", w.smoke)
    monkeypatch.setattr(smoke, "liveness_probe", lambda repo: None)
    w.dirs = component_dirs(dirs, names)


@pytest.fixture()
def vw(fake, tmp_path, monkeypatch):
    fake_smoke(fake, monkeypatch, tmp_path / "components")
    return fake


def vargs(w, env="dev", *rest, comps=("api",), name="orders-db"):
    out = ["resource", "upgrade", name, "--verify", "--env", env, "--repo-dir", str(w.repo), "--context", CTX]
    for c in comps:
        out += ["--component-dir", f"{c}={w.dirs / c}"]
    return [*out, *rest]


def healthy_dev(w, env="dev", image=None, major=17, **kw):
    w.kube.put("cluster", pg_cluster(env, image=image or PG[major], major=major, **kw))
    w.kube.put("secret", secret(env))


def dev17(w, promote=None, **state):
    step_state(w, dev=17, promote=promote, minutes=False, **state)
    backed_up(w.kube, clusters=False)
    healthy_dev(w)


def lines_of(out: str) -> list[str]:
    return out.splitlines()


def test_a_verified_step_prints_the_designed_block_and_exits_0_ac_121_15(vw, capsys, clock):  # AC-121.15
    dev17(vw)
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 0, out + err
    ls = lines_of(out)
    assert ls[0] == f"upgrade orders-db in dev: verified (17, {PG[17]})"
    assert re.fullmatch(r"  ok   orders-db healthy on 17 after \d+m\d+s \(.+\)", ls[1]), ls[1]
    assert ls[2] == "  ok   Secret shop-orders-db-app kept its name"
    assert ls[3] == "  ok   smoke api (dev): 2 passed"
    assert ls[-1] == "next: /resource:upgrade orders-db --to 17 --env staging"


def test_the_health_check_waits_until_the_cluster_is_healthy_at_the_new_image_ac_121_15(vw, capsys, clock):  # AC-121.15
    step_state(vw, dev=17, minutes=False)
    backed_up(vw.kube, clusters=False)
    vw.kube.put("secret", secret("dev"))
    polls = []

    def hook(args, stdin):
        if args[:1] == ["get"] and re.fullmatch(r"clusters?\.postgresql\.cnpg\.io", args[1]) and "shop-orders-db" in args:
            polls.append(clock.now)
            ok_now = len(polls) > 3
            return 0, json.dumps(pg_cluster("dev", image=PG[17], major=17, phase="Cluster in healthy state" if ok_now else "Upgrading Postgres major version")), ""
        return None
    vw.kube.hooks.append(hook)
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 0, out + err
    assert len(polls) >= 4 and re.search(r"after 0m[1-5]\ds", out), out


@pytest.mark.parametrize("kw", [{"image": PG[16], "major": 16}, {"ready": 0}, {"phase": "Upgrading Postgres major version"}], ids=["old-image", "not-ready", "upgrading"])
def test_a_cluster_that_never_reaches_the_new_image_is_not_verified_after_15_minutes_ac_121_16(vw, capsys, clock, kw):  # AC-121.16
    step_state(vw, dev=17, minutes=False)
    backed_up(vw.kube, clusters=False)
    vw.kube.put("secret", secret("dev"))
    vw.kube.put("cluster", pg_cluster("dev", **{"image": PG[17], "major": 17, **kw}))
    start = clock.now
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 1, out + err
    assert 900 <= clock.now - start <= 960, "the wait is 15 minutes"
    ls = lines_of(out)
    assert re.fullmatch(r"upgrade orders-db in dev: NOT VERIFIED \(.+\)", ls[0])
    assert next(ln for ln in ls if ln.startswith("  FAIL")).startswith("  FAIL orders-db not healthy on 17 after 15 minutes (")
    progress = [ln for ln in ls if re.fullmatch(r"  waiting for orders-db in dev: .+ \(\d+m of 15m\)", ln)]
    assert 10 <= len(progress) <= 16 and progress[0].endswith("(1m of 15m)")


def test_not_verified_names_the_backup_the_way_back_and_that_no_later_environment_moves_ac_121_16(vw, capsys, clock):  # AC-121.16
    step_state(vw, dev=17, minutes=False)
    stamp = backed_up(vw.kube, clusters=False, minutes_ago=30)
    vw.kube.put("secret", secret("dev"))
    vw.kube.put("cluster", pg_cluster("dev", ready=0))
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 1
    ls = [ln for ln in lines_of(out) if not ln.startswith("  waiting for")]
    assert re.fullmatch(r"upgrade orders-db in dev: NOT VERIFIED \(.+\)", ls[0])
    assert ls[1].startswith("  FAIL orders-db not healthy on 17 after 15 minutes (")
    assert ls[2:] == [f"  last successful backup: {stamp}", f"  way back: /resource:restore orders-db --env dev --to {TIME_LATEST}",
                      "  no later environment is upgraded until dev is verified"]


def test_a_failed_verification_is_recorded_in_the_cluster_and_starts_no_step_ac_121_16(vw, capsys, clock):  # AC-121.16
    dev17(vw, promote="after-dev-smoke")
    vw.smoke.fail.add("api")
    before = snapshot(vw.repo)
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 1
    [cm] = applied(vw.kube)
    assert cm["data"]["state"] == "failed" and cm["data"]["check"].startswith("smoke api")
    assert snapshot(vw.repo) == before, "no staging step is written after a failure"


def test_a_missing_connection_secret_fails_the_verification_ac_121_15(vw, capsys, clock):  # AC-121.15
    step_state(vw, dev=17, minutes=False)
    backed_up(vw.kube, clusters=False)
    vw.kube.put("cluster", pg_cluster("dev", image=PG[17], major=17))
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 1
    assert re.search(r"(?m)^  FAIL Secret shop-orders-db-app\b", out)
    assert vw.smoke.calls == [], "the smoke tests come after the Secret check"


def test_a_failing_smoke_test_fails_the_verification_naming_the_component_ac_121_16(vw, capsys, clock):  # AC-121.16
    dev17(vw)
    vw.smoke.fail.add("api")
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 1
    assert re.search(r"(?m)^  FAIL smoke api \(dev\): .*forced", out)
    assert re.search(r"(?m)^  way back: /resource:restore orders-db --env dev --to <time\|latest>$", out)


def test_only_the_instances_using_the_resource_are_smoke_tested_in_components_order_ac_121_15(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.15
    doc = upgrade_doc(16, instances={"dev": {"version": 17}})
    doc["components"] = {"web": comp("web", ["orders-db", "backups"]), "other": comp("other"), "api": comp("api", ["orders-db"])}
    w = make_world(tmp_path, monkeypatch, doc)
    w.kube = kube
    fake_smoke(w, monkeypatch, tmp_path / "components")
    backed_up(kube, clusters=False)
    healthy_dev(w)
    rc, out, err = run_cmd(capsys, *vargs(w, comps=("api", "web", "other")))
    assert rc == 0, out + err
    assert w.smoke.components() == ["web", "api"], "components: order, and not `other`, which does not use orders-db"


def test_a_component_without_a_directory_or_a_repo_fails_the_smoke_check_ac_121_15(vw, capsys, clock):  # AC-121.15
    dev17(vw)
    rc, out, err = run_cmd(capsys, *vargs(vw, comps=()))
    assert rc == 1 and re.search(r"(?m)^  FAIL smoke api\b", out), out


def test_the_record_is_the_designed_config_map_applied_with_kubectl_ac_121_15(vw, capsys, clock):  # AC-121.15
    dev17(vw)
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 0
    [cm] = applied(vw.kube)
    assert cm["apiVersion"] == "v1" and cm["kind"] == "ConfigMap"
    assert cm["metadata"]["name"] == "shop-orders-db-upgrade" and cm["metadata"]["namespace"] == "shop-dev"
    assert cm["metadata"]["labels"] == {"app.kubernetes.io/name": "orders-db", "app.kubernetes.io/part-of": "shop", "app.kubernetes.io/managed-by": "cplat"}
    assert list(cm["data"]) == ["major", "image", "state", "at", "check", "release"]
    assert (cm["data"]["major"], cm["data"]["image"], cm["data"]["state"], cm["data"]["check"]) == ("17", PG[17], "verified", "")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", cm["data"]["at"]) and cm["data"]["release"] == core.platform_version()
    call = next(c for c in vw.kube.calls if c[0][:1] == ["apply"] and c[2] and "ConfigMap" in c[2])
    assert call[0][:3] == ["apply", "-f", "-"] and call[1] == CTX


def test_a_major_step_with_a_backup_starts_the_first_base_backup_of_the_new_archive_ac_121_15(vw, capsys, clock):  # AC-121.15
    dev17(vw)
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 0, out + err
    assert re.search(r"(?m)^first base backup of shop-orders-db on 17 started \(Backup shop-orders-db-first-\d{14}\)$", out), out
    assert [b["metadata"]["name"] for b in vw.kube.created("Backup")][0].startswith("shop-orders-db-first-")


def test_a_cache_is_healthy_when_the_stateful_set_is_ready_on_the_new_image_ac_121_15(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.15
    from upgrade_fixtures import statefulset
    w = make_world(tmp_path, monkeypatch, system({"sessions": cache(version=8, instances={"dev": {"version": 9}})}, {"api": comp("api", ["sessions"])}))
    w.kube = kube
    fake_smoke(w, monkeypatch, tmp_path / "components", ("api",))
    kube.put("statefulset", statefulset("dev", "shop-sessions", "valkey", VK[9]))
    kube.put("secret", secret("dev", "shop-sessions-app"))
    argv = ["resource", "upgrade", "sessions", "--verify", "--env", "dev", "--repo-dir", w.repo, "--context", CTX, "--component-dir", f"api={w.dirs / 'api'}"]
    rc, out, err = run_cmd(capsys, *argv)
    assert rc == 0, out + err
    assert lines_of(out)[0] == f"upgrade sessions in dev: verified (9, {VK[9]})"
    kube.store["statefulset"][0]["status"]["currentRevision"] = "r0"       # a rollout is still running
    rc, out, err = run_cmd(capsys, *argv)
    assert rc == 1
    assert re.search(r"(?m)^  last successful backup: none \(cache has no backup\)$", out) and "resource:restore" not in out


def test_a_broker_needs_the_secret_of_every_provider_and_consumer_ac_121_15(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.15
    from upgrade_fixtures import statefulset
    w = make_world(tmp_path, monkeypatch, bsys({"bus": broker(version="2.14", instances={"dev": {"version": "2.15"}})}))
    w.kube = kube
    fake_smoke(w, monkeypatch, tmp_path / "components", ("api", "web"))
    kube.put("statefulset", statefulset("dev", "shop-bus", "nats", NATS["2.15"]))
    kube.put("secret", secret("dev", "shop-bus-api-app"))
    argv = ["resource", "upgrade", "bus", "--verify", "--env", "dev", "--repo-dir", w.repo, "--context", CTX,
            "--component-dir", f"api={w.dirs / 'api'}", "--component-dir", f"web={w.dirs / 'web'}"]
    rc, out, err = run_cmd(capsys, *argv)
    assert rc == 1 and re.search(r"(?m)^  FAIL Secret shop-bus-web-app\b", out), out
    kube.put("secret", secret("dev", "shop-bus-web-app"))
    rc, out, err = run_cmd(capsys, *argv)
    assert rc == 0, out + err
    assert w.smoke.components()[-2:] == ["api", "web"] and "  ok   Secret shop-bus-api-app kept its name" in out and "  ok   Secret shop-bus-web-app kept its name" in out


# ---------------- AC-121.8: who starts the next step ----------------

def test_after_dev_smoke_the_staging_step_starts_by_itself_after_a_verified_dev_ac_121_8(vw, capsys, clock):  # AC-121.8
    dev17(vw, promote="after-dev-smoke")
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 0, out + err
    assert read_system(vw.repo)["resources"]["orders-db"]["instances"]["staging"]["version"] == 17
    assert re.search(r"wrote the staging step: .+; apply it, then verify: cplat resource upgrade orders-db --verify --env staging", out)


def test_with_manual_promotion_staging_waits_for_its_command_ac_121_8(vw, capsys, clock):  # AC-121.8
    dev17(vw, promote="manual")
    before = snapshot(vw.repo)
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 0, out + err
    assert snapshot(vw.repo) == before and "next: /resource:upgrade orders-db --to 17 --env staging" in lines_of(out)


def test_the_default_promotion_is_manual_ac_121_8(vw, capsys, clock):  # AC-121.8
    dev17(vw)
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 0, out + err
    assert "version" not in (read_system(vw.repo)["resources"]["orders-db"]["instances"].get("staging") or {})


def test_a_failed_dev_never_starts_staging_even_with_after_dev_smoke_ac_121_8(vw, capsys, clock):  # AC-121.8
    dev17(vw, promote="after-dev-smoke")
    vw.smoke.fail.add("api")
    rc, out, err = run_cmd(capsys, *vargs(vw))
    assert rc == 1, out + err
    assert "version" not in (read_system(vw.repo)["resources"]["orders-db"]["instances"].get("staging") or {})


def test_prod_is_never_started_by_a_verified_staging_ac_121_8(vw, capsys, clock):  # AC-121.8
    step_state(vw, dev=17, staging=17, promote="after-dev-smoke", records=[("dev", 17)], minutes=False)
    backed_up(vw.kube, clusters=False)
    healthy_dev(vw, "staging")
    rc, out, err = run_cmd(capsys, *vargs(vw, "staging"))
    assert rc == 0, out + err
    doc = read_system(vw.repo)["resources"]["orders-db"]
    assert doc["version"] == 16 and "version" not in doc["instances"]["prod"]
    assert "next: /resource:upgrade orders-db --to 17 --env prod" in lines_of(out)


def test_the_last_environment_verified_says_all_environments_are_on_the_major_ac_121_8(tmp_path, monkeypatch, kube, clock, capsys):  # noqa: F811  # AC-121.8
    w = make_world(tmp_path, monkeypatch, upgrade_doc(17))
    w.kube = kube
    fake_smoke(w, monkeypatch, tmp_path / "components", ("api",))
    backed_up(kube, clusters=False)
    healthy_dev(w, "prod")
    rc, out, err = run_cmd(capsys, "resource", "upgrade", "orders-db", "--verify", "--env", "prod", "--repo-dir", w.repo, "--context", CTX,
                           "--component-dir", f"api={w.dirs / 'api'}")
    assert rc == 0, out + err
    assert lines_of(out)[-1] == "all environments are on 17"


# ---------------- AC-121.16: restore across a major ----------------

ARCH = [{"server": "shop-orders-db", "major": 16}, {"server": "shop-orders-db-pg17", "major": 17}]


def restore_repo(tmp_path):
    from backup_fixtures import bdoc, make_repo, write_state
    repo = make_repo(tmp_path, bdoc(dbb={"dev": DEV}, db_kw={"version": 17}))
    write_state(repo, {"next": 1, "clusters": [{"name": "shop-orders-db", "role": "active"}], "archives": ARCH})
    subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True)
    commit_all(repo, "archives")
    return repo


def test_a_restore_to_a_time_before_the_upgrade_runs_the_old_major_and_says_so_ac_121_16(tmp_path, kube, clock, capsys):  # noqa: F811  # AC-121.16
    repo = restore_repo(tmp_path)
    kube.healthy_database(windows={"shop-orders-db": "2026-09-27T03:00:12Z", "shop-orders-db-pg17": "2026-10-27T09:00:00Z"})
    kube.pg_latest = "2026-10-27T10:41:02Z"
    kube.on_apply_k = lambda k, args: k.put("cluster", cnpg_cluster("shop-orders-db-g1"))
    rc, out, err = run_cmd(capsys, "resource", "restore", "orders-db", "--env", "dev", "--to", "2026-10-10T00:00:00Z", "--repo-dir", repo)
    assert rc == 0, out + err
    assert "the restored instance runs orders-db 16 (the data from before the upgrade to 17)" in (out + err).splitlines()
    state = yaml.safe_load((repo / APP / "addons/dev/orders-db/restore-state.yaml").read_text())
    assert state["clusters"][-1]["from"]["server"] == "shop-orders-db" and state["archives"] == ARCH
    assert yaml.safe_load((repo / APP / "addons/dev/orders-db/cluster-g1.yaml").read_text())["spec"]["imageName"] == PG[16]


def test_a_restore_to_a_time_after_the_upgrade_prints_no_major_line_ac_121_16(tmp_path, kube, clock, capsys):  # noqa: F811  # AC-121.16
    repo = restore_repo(tmp_path)
    kube.healthy_database(windows={"shop-orders-db-pg17": "2026-10-27T09:00:00Z"})
    kube.pg_latest = "2026-10-27T10:41:02Z"
    kube.on_apply_k = lambda k, args: k.put("cluster", cnpg_cluster("shop-orders-db-g1"))
    rc, out, err = run_cmd(capsys, "resource", "restore", "orders-db", "--env", "dev", "--to", "2026-10-27T09:30:00Z", "--repo-dir", repo)
    assert rc == 0, out + err
    assert not re.search(r"the restored instance runs orders-db \d+", out + err)
    state = yaml.safe_load((repo / APP / "addons/dev/orders-db/restore-state.yaml").read_text())
    assert state["clusters"][-1]["from"]["server"] == "shop-orders-db-pg17" and state["archives"] == ARCH, "the archives survive the restore"
    assert yaml.safe_load((repo / APP / "addons/dev/orders-db/cluster-g1.yaml").read_text())["spec"]["imageName"] == PG[17]


# ---------------- AC-121.10: the gitops CI check ----------------

def check_repo(tmp_path, base_doc):
    from backup_fixtures import make_repo
    repo = make_repo(tmp_path, base_doc)
    if (T / "scripts" / "upgrade-check.py").is_file():
        shutil.copy(T / "scripts" / "upgrade-check.py", repo / "scripts" / "upgrade-check.py")
    commit_all(repo, "base")
    return repo


def run_check(repo, doc):
    put_system(repo, doc)
    p = subprocess.run([sys.executable, "scripts/upgrade-check.py", "--base", "HEAD"], cwd=repo, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def d16(**inst):
    return upgrade_doc(16, backup=False, instances=inst)


def test_the_check_script_exists_in_the_gitops_template_ac_121_10():  # AC-121.10
    assert (T / "scripts" / "upgrade-check.py").is_file()


def test_a_pr_that_changes_the_major_in_two_environments_fails_naming_resource_and_environments_ac_121_10(tmp_path):  # AC-121.10
    repo = check_repo(tmp_path, d16())
    rc, out = run_check(repo, d16(dev={"version": 17}, staging={"version": 17}))
    assert rc == 1
    assert ("ERROR: applications/shop/system.yaml: resources.orders-db: the major changes in dev, staging at once (16 → 17); "
            "upgrade one environment per pull request with /resource:upgrade orders-db --to 17 [--env <env>]") in out.splitlines()


def test_a_hand_edit_of_the_resource_version_fails_for_every_environment_ac_121_10(tmp_path):  # AC-121.10
    repo = check_repo(tmp_path, d16())
    rc, out = run_check(repo, upgrade_doc(17, backup=False))
    assert rc == 1 and "the major changes in dev, staging, prod at once (16 → 17)" in out


def test_different_old_majors_are_listed_per_environment_ac_121_10(tmp_path):  # AC-121.10
    repo = check_repo(tmp_path, d16(dev={"version": 15}))
    rc, out = run_check(repo, upgrade_doc(17, backup=False))
    assert rc == 1 and "the major changes in dev, staging, prod at once (dev 15, staging 16, prod 16 → 17)" in out


def test_one_environment_at_a_time_passes_ac_121_10(tmp_path):  # AC-121.10
    repo = check_repo(tmp_path, d16())
    rc, out = run_check(repo, d16(dev={"version": 17}))
    assert rc == 0 and "OK: no resource changes its major in more than one environment" in out.splitlines()


def test_the_folding_step_passes_because_only_one_environment_changes_ac_121_10(tmp_path):  # AC-121.10
    repo = check_repo(tmp_path, d16(dev={"version": 17}, staging={"version": 17}))
    rc, out = run_check(repo, upgrade_doc(17, backup=False))
    assert rc == 0 and "OK: no resource changes its major in more than one environment" in out


def test_an_unrenderable_base_is_ignored_with_a_warning_ac_121_10(tmp_path):  # AC-121.10
    repo = check_repo(tmp_path, d16())
    (repo / "applications" / "shop" / "system.yaml").write_text("system: [unclosed")
    commit_all(repo, "broken base")
    rc, out = run_check(repo, d16(dev={"version": 17}, staging={"version": 17}))
    assert rc == 0 and re.search(r"(?m)^WARNING: ", out), out


def test_a_system_new_in_the_pr_passes_ac_121_10(tmp_path):  # AC-121.10
    repo = check_repo(tmp_path, d16())
    write_system(repo, {**d16(dev={"version": 17}, staging={"version": 17}), "system": "other"}, "other")
    p = subprocess.run([sys.executable, "scripts/upgrade-check.py", "--base", "HEAD"], cwd=repo, capture_output=True, text=True)
    assert p.returncode == 0 and "OK: no resource changes its major in more than one environment" in p.stdout, p.stdout + p.stderr


def test_the_gitops_template_runs_the_check_in_ci_with_the_full_history_ac_121_10():  # AC-121.10
    ci = yaml.safe_load((T / ".github" / "workflows" / "ci.yml").read_text())
    job = next((j for j in ci["jobs"].values() if j.get("name") == "upgrade-check (one environment per major)"), None)
    assert job is not None, "a job named 'upgrade-check (one environment per major)'"
    assert job["if"] == "github.event_name == 'pull_request'"
    assert any(s.get("with", {}).get("fetch-depth") == 0 for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    base = "origin/${{ github.base_ref }}"
    assert any(s.get("env", {}).get("BASE_REF") == base for s in job["steps"]) or job.get("env", {}).get("BASE_REF") == base
    assert any(s.get("run") == "devbox run upgrade-check" for s in job["steps"])


def test_the_gitops_template_has_the_upgrade_check_recipe_ac_121_10():  # AC-121.10
    scripts = json.loads((T / "devbox.json").read_text())["shell"]["scripts"]
    assert "upgrade-check" in scripts, "a recipe upgrade-check"
    cmd = scripts["upgrade-check"]
    cmd = cmd if isinstance(cmd, str) else " ".join(cmd)
    assert "scripts/upgrade-check.py" in cmd and re.search(r'--base "\$\{BASE_REF:-origin/main\}"', cmd)


# ---------------- AC-121.17: the copier answer and system new ----------------

def test_the_copier_asks_property_operators_after_resource_metrics_with_owner_as_default_ac_121_17():  # AC-121.17
    data = yaml.safe_load((T / "copier.yml").read_text())
    assert "property_operators" in data, "copier.yml asks property_operators"
    q = data["property_operators"]
    assert (q["type"], q["choices"], q["default"]) == ("str", ["install", "owner"], "owner")
    assert q["help"] == ("Who installs External Secrets, Kyverno and the LGTM dev stack on the cluster? install: the platform, as Argo CD applications under "
                         "operators/, only for what the system uses; owner: the cluster's owner (every repo created before this release keeps owner).")
    keys = list(data)
    assert keys.index("property_operators") == keys.index("resource_metrics") + 1


def test_a_new_system_answers_install_ac_121_17(tmp_path):  # AC-121.17
    import newapp
    from test_newapp import write
    req = newapp.resolve([write(tmp_path), "--no-github", "--org", "acme", "--dir", str(tmp_path / "out")])
    assert "property_operators=install" in req["entries"][0]["args"]


# ---------------- AC-121.5 / .15: the model and status ----------------

def rendered(tmp_path, doc):
    from resources_fixtures import ok
    ok(tmp_path, doc)
    return mod("model").load_dir(tmp_path / APP)


def by_inst(m):
    return {(r.resource, r.environment): r for r in m.resource_instances}


def mixed_doc():
    from broker_fixtures import events
    res = {"orders-db": db(version=16, instances={"dev": {"version": 17}, "prod": {"external": True}}), "files": {"type": "bucket"}, "sessions": cache(),
           "bus": broker()}
    comps = {"api": comp("api", ["orders-db", "files", "sessions"], provides=["orders"]), "web": comp("web", consumes=["orders"])}
    return system(res, comps, apis=events("orders"))


def test_each_in_cluster_instance_reports_its_major_and_pinned_image_ac_121_5(tmp_path):  # AC-121.5
    r = by_inst(rendered(tmp_path, mixed_doc()))
    assert (r[("orders-db", "dev")].version, r[("orders-db", "dev")].pinned) == (17, PG[17])
    assert (r[("orders-db", "staging")].version, r[("orders-db", "staging")].pinned) == (16, PG[16])
    assert (r[("sessions", "dev")].version, r[("sessions", "dev")].pinned) == (9, VK[9])
    assert (r[("bus", "dev")].version, r[("bus", "dev")].pinned) == ("2.15", NATS["2.15"])


def test_external_instances_and_buckets_report_no_major_ac_121_5(tmp_path):  # AC-121.5
    from upgrade_fixtures import SEAWEED
    r = by_inst(rendered(tmp_path, mixed_doc()))
    assert (r[("orders-db", "prod")].version, r[("orders-db", "prod")].pinned) == (None, None)
    assert (r[("files", "dev")].version, r[("files", "dev")].pinned) == (None, SEAWEED)


def test_an_instance_that_is_not_rendered_yet_has_no_pin_ac_121_5(tmp_path):  # AC-121.5
    write_system(tmp_path, mixed_doc())
    r = by_inst(mod("model").load_dir(tmp_path / APP))
    assert r[("orders-db", "dev")].pinned is None and r[("orders-db", "dev")].version == 17


def test_the_model_json_has_version_and_pinned_after_backup_ac_121_5(tmp_path, capsys):  # AC-121.5
    from resources_fixtures import ok
    ok(tmp_path, mixed_doc())
    assert cplat.main(["model", "show", "--repo-dir", str(tmp_path), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["schema"] == 2
    for r in d["resource_instances"]:
        keys = list(r)
        assert "version" in keys and "pinned" in keys, keys
        assert keys.index("version") == keys.index("backup") + 1 and keys.index("pinned") == keys.index("backup") + 2, keys
    row = next(r for r in d["resource_instances"] if (r["resource"], r["environment"]) == ("orders-db", "dev"))
    assert (row["version"], row["pinned"]) == (17, PG[17])


def test_the_model_text_does_not_change_ac_121_5(tmp_path, capsys):  # AC-121.5
    from resources_fixtures import ok
    ok(tmp_path, system({"orders-db": db(version=17)}, {"api": comp("api", ["orders-db"])}))
    assert cplat.main(["model", "show", "--repo-dir", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert not re.search(r"\bpinned\b", text) and "version 17" in text
    assert hasattr(mod("model").ResourceInstance, "__dataclass_fields__") and "pinned" in mod("model").ResourceInstance.__dataclass_fields__


@pytest.fixture()
def swp(tmp_path, monkeypatch, kube):   # noqa: F811
    import status
    monkeypatch.setattr(status, "sh", lambda cmd: None)
    from resources_fixtures import render5
    doc = system({"orders-db": db(version=16, instances={"dev": {"version": 17}}), "ext": db(instances={"prod": {"external": True}})},
                 {"api": comp("api", ["orders-db", "ext"])})
    render5(tmp_path, doc)      # not asserted here: a renderer without the instance version fails the tests that read the result
    return SimpleNamespace(repo=tmp_path, kube=kube)


def status_json(w, capsys, *extra) -> dict:
    assert cplat.main(["system", "status", "--json", "--repo-dir", str(w.repo), *extra]) == 0
    return json.loads(capsys.readouterr().out)


def vcell(d, resource, env):
    assert "resource_versions" in d, "status --json has resource_versions"
    return next(r for r in d["resource_versions"] if r["resource"] == resource)["cells"][env]


def test_status_has_one_resource_version_row_per_resource_in_declaration_order_ac_121_5(swp, capsys):  # AC-121.5
    d = status_json(swp, capsys, "--context", CTX)
    assert [(r["resource"], r["type"]) for r in d["resource_versions"]] == [("orders-db", "database"), ("ext", "database")]
    assert list(d["resource_versions"][0]["cells"]) == ["dev", "staging", "prod"]


def test_a_cell_has_major_pin_held_health_and_upgrade_ac_121_5(swp, capsys):  # AC-121.5
    swp.kube.put("cluster", pg_cluster("dev", image=PG[17], major=17))
    swp.kube.put("cluster", pg_cluster("staging", image=PG[16], major=16))
    c = vcell(status_json(swp, capsys, "--context", CTX), "orders-db", "dev")
    assert c == {"version": 17, "pinned": PG[17], "held": False, "health": "healthy", "upgrade": None}
    assert list(c) == ["version", "pinned", "held", "health", "upgrade"]


def test_the_upgrade_of_a_cell_comes_from_the_record_ac_121_15(swp, capsys):  # AC-121.15
    swp.kube.put("cluster", pg_cluster("dev", image=PG[17], major=17))
    swp.kube.put("configmap", record("dev", "17", state="verified", at="2026-10-28T10:00:00Z"))
    c = vcell(status_json(swp, capsys, "--context", CTX), "orders-db", "dev")
    assert c["upgrade"] == {"state": "verified", "major": "17", "image": PG[17], "at": "2026-10-28T10:00:00Z", "check": ""}


def test_health_is_upgrading_or_degraded_by_the_cluster_state_ac_121_5(swp, capsys):  # AC-121.5
    swp.kube.put("cluster", pg_cluster("dev", image=PG[17], major=17, phase="Upgrading Postgres major version"))
    swp.kube.put("cluster", pg_cluster("staging", image=PG[16], major=16, ready=0))
    d = status_json(swp, capsys, "--context", CTX)
    assert vcell(d, "orders-db", "dev")["health"] == "upgrading" and vcell(d, "orders-db", "staging")["health"] == "degraded"


def test_health_is_unknown_without_a_context_or_a_reachable_cluster_and_external_for_external_ac_121_5(swp, capsys):  # AC-121.5
    d = status_json(swp, capsys)
    assert vcell(d, "orders-db", "dev")["health"] == "unknown" and not swp.kube.calls
    swp.kube.error = (1, "Unable to connect")
    d = status_json(swp, capsys, "--context", CTX)
    assert vcell(d, "orders-db", "dev")["health"] == "unknown"
    assert vcell(d, "ext", "prod")["health"] == "external" and vcell(d, "ext", "prod")["pinned"] is None


def test_a_held_pin_is_flagged_against_the_table_of_this_repo_ac_121_5(swp, capsys):  # AC-121.5
    p = swp.repo / APP / "addons/staging/orders-db/cluster.yaml"
    p.write_text(p.read_text().replace(PG[16], OLD_PG[16]))
    swp.kube.put("cluster", pg_cluster("staging", image=OLD_PG[16], major=16))
    d = status_json(swp, capsys, "--context", CTX)
    assert vcell(d, "orders-db", "staging")["held"] is True and vcell(d, "orders-db", "staging")["pinned"] == OLD_PG[16]
    assert vcell(d, "orders-db", "dev")["held"] is False


def test_the_text_grid_shows_major_version_health_and_flags_ac_121_5(swp, capsys):  # AC-121.5
    for env, major in (("dev", 17), ("staging", 16), ("prod", 16)):
        swp.kube.put("cluster", pg_cluster(env, image=PG[major], major=major))
    swp.kube.put("configmap", record("dev", "17", state="verified"))
    p = swp.repo / APP / "addons/prod/orders-db/cluster.yaml"
    p.write_text(p.read_text().replace(PG[16], OLD_PG[16]))
    assert cplat.main(["system", "status", "--repo-dir", str(swp.repo), "--context", CTX]) == 0
    out = capsys.readouterr().out.splitlines()
    i = out.index(f"Resource versions (read from the cluster {CTX} now):")
    grid = [" ".join(ln.split()) for ln in out[i + 1:i + 4]]
    assert grid[0] == "resource dev staging prod"
    assert grid[1] == "orders-db 17 (17.11) healthy upgraded 16 (16.15) healthy 16 (16.15) healthy held"
    assert grid[2].endswith("external")


def test_a_failed_record_shows_in_the_cell_text_ac_121_15(swp, capsys):  # AC-121.15
    swp.kube.put("cluster", pg_cluster("dev", image=PG[17], major=17))
    swp.kube.put("configmap", record("dev", "17", state="failed", check="smoke api"))
    assert cplat.main(["system", "status", "--repo-dir", str(swp.repo), "--context", CTX]) == 0
    flat = " ".join(capsys.readouterr().out.split())
    assert "17 (17.11) healthy upgrade failed (smoke api)" in flat


# ---------------- AC-121.11 / .20 / .21 / .23: /platform:update ----------------

COPIER = """#!{python}
import shutil, sys
from pathlib import Path
args = sys.argv[1:]
if args[:1] == ["copy"] and len(args) > 2 and args[2] == ".":
    shutil.copy({new!r}, Path("scripts") / "render.py")      # the template brings the new renderer
elif args[:1] == ["copy"] and len(args) > 2:
    Path(args[2]).mkdir(parents=True, exist_ok=True)
"""


@pytest.fixture()
def uworld(tmp_path, monkeypatch):
    """A gitops-app rendered by the last release (v5.3.0), with postgres on 16, and a copier that installs this checkout's renderer."""
    old = subprocess.run(["git", "show", "v5.3.0:templates/gitops-app/scripts/render.py"], cwd=ROOT, capture_output=True, text=True)
    if old.returncode != 0:
        pytest.skip("tag v5.3.0 is not available in this checkout")
    repo = tmp_path / "gitops"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "render.py").write_text(old.stdout)
    doc = system({"postgres": db(version=16)}, {"api": comp("api", ["postgres"])})
    write_system(repo, "# the shop system\n" + yaml.safe_dump(doc, sort_keys=False))
    (repo / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/gitops-app\ngithub_org: acme\napp_name: shop\nproject_name: shop-gitops\n")
    (repo / ".platform-version").write_text("platform: 5.3.0\nshape: gitops-app\nref: main\n")
    (repo / "devbox.json").write_text(json.dumps({"shell": {"scripts": {"ci": "true"}}}))
    assert subprocess.run([sys.executable, "scripts/render.py"], cwd=repo, capture_output=True, text=True).returncode == 0
    op = repo / "operators" / "apps" / "cloudnative-pg.yaml"
    op.write_text(op.read_text().replace("targetRevision: 0.29.1", "targetRevision: 0.27.0"))
    from system_fixtures import init_git
    init_git(repo)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    copier = bin_dir / "copier"
    copier.write_text(COPIER.format(python=sys.executable, new=str(T / "scripts" / "render.py")))
    copier.chmod(copier.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return repo


def update_output(repo, capsys, *extra):
    rc = cplat.main(["platform", "update", "--repo", str(repo), *extra])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_the_update_moves_dev_to_the_table_pin_and_holds_staging_and_prod_ac_121_11(uworld, capsys):  # AC-121.11
    rc, out, err = update_output(uworld, capsys)
    assert rc == 0, out + err
    assert cluster_file(uworld, "dev", "postgres")["spec"]["imageName"] == PG[16]
    for env in ("staging", "prod"):
        assert cluster_file(uworld, env, "postgres")["spec"]["imageName"] == OLD_PG[16]


def test_the_update_report_lists_the_changes_per_environment_ac_121_11(uworld, capsys):  # AC-121.11
    rc, out, err = update_output(uworld, capsys)
    assert rc == 0, out + err
    ls = [ln.strip() for ln in out.splitlines()]
    head = next((i for i, ln in enumerate(ls) if re.fullmatch(r"versions in this system \(platform 5\.3\.0 → \S+\):", ln)), None)
    assert head is not None, out
    block = [" ".join(ln.split()) for ln in ls[head + 1:head + 5]]
    assert re.fullmatch(r"dev postgres 16: " + re.escape(OLD_PG[16]) + r" → \S+ \(moves now\)", block[0]), block
    assert block[1] == f"staging postgres 16: keeps {OLD_PG[16]} until /resource:upgrade postgres --to 16 --env staging"
    assert block[2] == f"prod postgres 16: keeps {OLD_PG[16]} until /resource:upgrade postgres --to 16 --env prod"
    assert block[3] == "cluster operator cloudnative-pg 0.27.0 → 0.29.1 (operators/apps; shared by dev, staging, prod: moves with dev's step)"


def test_the_update_json_carries_the_versions_and_the_pr_body_lists_them_ac_121_23(uworld, capsys):  # AC-121.23
    rc, out, err = update_output(uworld, capsys, "--json")
    assert rc == 0, out + err
    d = json.loads(out)
    assert d.get("versions"), "the update JSON has the versions block"
    import fleet_pr
    body = fleet_pr.pr_body("5.3.0", core.platform_version(), d, [])
    assert re.search(r"staging\s+postgres 16: keeps ", body) and "/resource:upgrade postgres --to 16 --env prod" in body


def test_a_system_with_nothing_to_move_gets_no_versions_block_ac_121_23(uworld, capsys):  # AC-121.23
    shutil.copy(T / "scripts" / "render.py", uworld / "scripts" / "render.py")
    assert subprocess.run([sys.executable, "scripts/render.py"], cwd=uworld, capture_output=True, text=True).returncode == 0
    commit_all(uworld, "already on this release")
    rc, out, err = update_output(uworld, capsys)
    assert rc == 0, out + err
    assert not re.search(r"versions in this system", out)
    assert (T / "scripts" / "upgrade-check.py").is_file(), "the same release also brings the CI check"


def test_the_update_moves_the_shared_operator_once_with_dev_ac_121_20(uworld, capsys):  # AC-121.20
    rc, out, err = update_output(uworld, capsys)
    assert rc == 0, out + err
    cluster_lines = [" ".join(ln.split()) for ln in out.splitlines() if re.match(r"\s+cluster\s+operator ", ln)]
    assert cluster_lines == ["cluster operator cloudnative-pg 0.27.0 → 0.29.1 (operators/apps; shared by dev, staging, prod: moves with dev's step)"], out
    assert len(list((uworld / "operators" / "apps").glob("cloudnative-pg.yaml"))) == 1, "one application per cluster, not one per environment"


def test_update_verify_is_an_option_with_context_and_component_dir_ac_121_21():  # AC-121.21
    import update
    h = update.build_parser().format_help()
    assert "--verify" in h and "--context" in h and "--component-dir" in h

