"""Spec 190 acceptance tests: an `environments:` limit in spec front matter that `spec check` validates, `spec show` and
`spec approve` display, `cplat instance promote` refuses (with a person's reasoned override) and automatic staging respects.

Contract: design.md (envlimit.py lines, `--accept-environment-limit`, `REFUSED:` dry-run lines, JSON keys). Seams are the ones of the
digest tests (test_promote_digest), the staging deploy tests (test_staging_093_ship) and the joint ship tests (test_144_joint_pr).
Nothing imports `envlimit`: every test goes through a public command, so only the missing behaviour fails them."""
import json
import subprocess

import pytest
import yaml

import gitops
import spec
from test_gitops import commit, composed, gh, gitops_repo, pin  # noqa: F401  (fixtures)
from test_promote_digest import attempt, unchanged
from test_spec import make

SPEC_ID = "042-anonymous-use"
TITLE = "Anonymous use"
REASON = "Login ships next week and the person accepts it."

LIMIT_SPEC = """---
spec_id: {spec_id}
title: {title}
status: {status}
priority: P1
{field}---

# {num}

## Problem

Anonymous use of the app.

## Acceptance criteria

- **AC-{num}.1** Given a visitor, when they open the app, then they see the list.

## Non-goals

- None

## Open questions

None.

## Changelog

- 2026-11-01 created
"""


def limit_line(spec_id=SPEC_ID, envs="dev", target="staging", title=TITLE):
    return f"environment limit: {spec_id} allows {envs}, not {target} ({title})"


def write_spec(root, spec_id=SPEC_ID, title=TITLE, status="building", field="environments: [dev]\n"):
    d = root / "docs" / "specs" / spec_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.md").write_text(LIMIT_SPEC.format(spec_id=spec_id, title=title, status=status, field=field, num=spec_id[:3]))


# ---------------- AC-190.1: spec check ----------------

@pytest.fixture(autouse=True)
def no_shape(monkeypatch):
    monkeypatch.setattr(spec, "repo_shape", lambda root: None)


def with_field(tmp_path, field, status="approved"):
    make(tmp_path, status=status)
    p = tmp_path / "docs" / "specs" / "007-price-alerts" / "spec.md"
    p.write_text(p.read_text().replace("priority: P1\n", f"priority: P1\n{field}\n"))


def check(tmp_path, capsys):
    rc = spec.main(["--repo", str(tmp_path), "check"])
    return rc, capsys.readouterr().out


@pytest.mark.parametrize("field,bad", [("environments: [dev, qa]", "qa"), ("environments: [staging, prod, qa-2]", "qa-2")])
def test_an_unknown_environment_is_an_error_naming_spec_and_value(tmp_path, capsys, field, bad):  # AC-190.1
    with_field(tmp_path, field)
    rc, out = check(tmp_path, capsys)
    assert rc == 1 and "007-price-alerts" in out and bad in out and "environments" in out


@pytest.mark.parametrize("field,got", [("environments: []", "[]"), ("environments:", "null"), ("environments: dev", "dev")])
def test_an_empty_or_malformed_list_is_an_error_naming_the_spec(tmp_path, capsys, field, got):  # AC-190.1
    with_field(tmp_path, field)
    rc, out = check(tmp_path, capsys)
    assert rc == 1 and "007-price-alerts" in out
    assert "environments must be a non-empty list out of dev, staging, prod" in out and f"(got {got})" in out


@pytest.mark.parametrize("status", ["draft", "building", "done"])
def test_the_field_is_checked_for_every_status(tmp_path, capsys, status):  # AC-190.1
    with_field(tmp_path, "environments: [qa]", status=status)
    rc, out = check(tmp_path, capsys)
    assert rc == 1 and "qa" in out


def test_a_valid_field_passes_and_no_field_limits_nothing(tmp_path, capsys):  # AC-190.1
    with_field(tmp_path, "environments: [dev, staging]")
    assert check(tmp_path, capsys)[0] == 0
    assert spec.main(["--repo", str(tmp_path), "show", "007-price-alerts"]) == 0      # show is new: red until it exists
    assert "Environment limit: dev, staging (promotion to prod is refused)" in capsys.readouterr().out


def test_a_spec_without_the_field_shows_no_limit_line(tmp_path, capsys):  # AC-190.1
    make(tmp_path, status="approved")
    assert check(tmp_path, capsys)[0] == 0
    assert spec.main(["--repo", str(tmp_path), "show", "007-price-alerts"]) == 0
    out = capsys.readouterr().out
    assert "007-price-alerts" in out and "Environment limit" not in out
    assert spec.main(["--repo", str(tmp_path), "show", "007-price-alerts", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["environments"] is None


# ---------------- AC-190.5: spec show / approve / list ----------------

def test_show_prints_the_limit_line(tmp_path, capsys):  # AC-190.5
    with_field(tmp_path, "environments: [dev]")
    assert spec.main(["--repo", str(tmp_path), "show", "007-price-alerts"]) == 0
    out = capsys.readouterr().out
    assert "Environment limit: dev (promotion to staging, prod is refused)" in out
    assert "Price alerts" in out


def test_show_json_carries_the_environments(tmp_path, capsys):  # AC-190.5
    with_field(tmp_path, "environments: [dev, staging]")
    assert spec.main(["--repo", str(tmp_path), "show", "007-price-alerts", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["id"] == "007-price-alerts" and row["environments"] == ["dev", "staging"]


def test_list_json_rows_carry_the_environments(tmp_path, capsys):  # AC-190.5
    with_field(tmp_path, "environments: [prod]")
    assert spec.main(["--repo", str(tmp_path), "list", "--all", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["environments"] == ["prod"]


def test_approve_prints_the_limit_line(tmp_path, capsys):  # AC-190.5
    with_field(tmp_path, "environments: [dev]", status="draft")
    assert spec.main(["--repo", str(tmp_path), "approve", "007"]) == 0
    out = capsys.readouterr().out
    assert "007-price-alerts: approved" in out
    assert "Environment limit: dev (promotion to staging, prod is refused)" in out


def test_approve_json_carries_status_and_environments(tmp_path, capsys):  # AC-190.5
    with_field(tmp_path, "environments: [dev]", status="draft")
    assert spec.main(["--repo", str(tmp_path), "approve", "007", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["id"] == "007-price-alerts" and got["status"] == "approved" and got["environments"] == ["dev"]


def test_approve_without_the_field_prints_no_limit_line(tmp_path, capsys):  # AC-190.5
    make(tmp_path, status="draft")
    assert spec.main(["--repo", str(tmp_path), "approve", "007", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["environments"] is None


# ---------------- AC-190.2: promote refuses ----------------

@pytest.fixture()
def limited(gitops_repo, gh):  # noqa: F811
    """A gitops-app with todo-api composed and a building system spec that allows dev only."""
    composed(gitops_repo, "todo-api")
    write_spec(gitops_repo)
    commit(gitops_repo, "system spec")
    return gitops_repo


def to(repo, target="staging", *extra):
    return ["todo-api", "--to", target, "--repo-dir", str(repo), *extra]


def staging_pinned(repo):
    try:
        return pin(repo, "staging", "todo-api")
    except FileNotFoundError:
        return None


@pytest.fixture()
def opened(monkeypatch):
    bodies = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: bodies.append(body) or "https://github.com/acme/g/pull/9")
    return bodies


def test_a_limited_target_is_refused_and_changes_nothing(limited, capsys):  # AC-190.2
    rc, out = attempt(to(limited), capsys)
    assert rc == 1 and unchanged(limited) and staging_pinned(limited) is None
    assert limit_line() in out
    assert "--accept-environment-limit" in out and "--amend 042" in out      # the two ways on


def test_a_limited_target_with_pr_opens_no_pr(limited, opened, capsys):  # AC-190.2
    rc, out = attempt(to(limited, "staging", "--pr"), capsys)
    assert rc == 1 and opened == [] and unchanged(limited) and limit_line() in out


def test_prod_is_limited_too_and_all_is_checked(limited, capsys):  # AC-190.2
    rc, out = attempt(["--all", "--to", "prod", "--repo-dir", str(limited)], capsys)
    assert rc == 1 and limit_line(target="prod") in out and unchanged(limited)


def test_a_spec_allowing_the_target_does_not_limit_it(limited, capsys):  # AC-190.2
    write_spec(limited, field="environments: [dev, staging]\n")
    commit(limited, "widen")
    rc, out = attempt(to(limited, "staging", "--dry-run", "--json"), capsys)
    got = json.loads(out)
    assert rc == 0 and got["environment_limits"] == [] and "environment limit:" not in out


@pytest.mark.parametrize("status,limits", [("building", True), ("done", True), ("draft", False), ("approved", False),
                                           ("superseded", False)])
def test_only_a_building_or_done_spec_limits(limited, capsys, status, limits):  # AC-190.2
    write_spec(limited, status=status)
    subprocess.run(["git", "add", "-A"], cwd=limited, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "status"], cwd=limited, check=True)
    rc, out = attempt(to(limited, "staging", "--dry-run", "--json"), capsys)
    got = json.loads(out)
    assert (rc == 1) is limits and (len(got["environment_limits"]) == 1) is limits


def test_a_spec_without_the_field_limits_nothing(limited, capsys):  # AC-190.2
    write_spec(limited, field="")
    commit(limited, "no field")
    rc, out = attempt(to(limited, "staging", "--dry-run", "--json"), capsys)
    assert rc == 0 and json.loads(out)["environment_limits"] == []


def test_one_line_per_limiting_spec_and_one_fix_naming_both(limited, capsys):  # AC-190.2
    write_spec(limited, "051-no-export", "No export", status="done", field="environments: [dev, staging]\n")
    commit(limited, "second")
    rc, out = attempt(to(limited, "prod"), capsys)
    assert rc == 1
    assert limit_line(target="prod") in out and limit_line("051-no-export", "dev, staging", "prod", "No export") in out
    assert "--amend 042" in out and "--amend 051" in out


def test_the_dry_run_shows_refused_lines_and_a_fix_line_and_exits_1(limited, capsys):  # AC-190.2
    rc, out = attempt(to(limited, "staging", "--dry-run"), capsys)
    assert rc == 1 and unchanged(limited) and staging_pinned(limited) is None
    assert f"REFUSED: {limit_line()}" in out and "fix:" in out


def test_the_dry_run_json_lists_the_limits_and_exits_1(limited, capsys):  # AC-190.2
    rc, out = attempt(to(limited, "staging", "--dry-run", "--json"), capsys)
    assert rc == 1
    (lim,) = json.loads(out)["environment_limits"]
    assert lim["spec"] == SPEC_ID and lim["title"] == TITLE and lim["environments"] == ["dev"]
    assert lim["target"] == "staging" and lim["accepted"] is False


def test_a_dev_rollback_is_never_refused(limited, capsys):  # AC-190.2
    """The spec allows staging only, so dev is outside its list; a rollback to a real previous dev pin still goes through."""
    write_spec(limited, field="environments: [staging]\n")
    for tag in ("1.2.0", "1.3.0"):
        k = limited / "applications/todo/overlays/dev/todo-api/kustomization.yaml"
        data = yaml.safe_load(k.read_text())
        data["images"][0]["newTag"] = tag
        k.write_text(yaml.safe_dump(data, sort_keys=False))
        commit(limited, f"pin dev {tag}")
    rc, out = attempt(to(limited, "dev", "--version", "1.2.0", "--dry-run"), capsys)
    assert rc == 0 and "environment limit" not in out and "REFUSED" not in out


# ---------------- AC-190.3: the override ----------------

def test_the_override_proceeds_and_records_the_reason(limited, capsys):  # AC-190.3
    rc, out = attempt(to(limited, "staging", "--accept-environment-limit", REASON), capsys)
    assert rc == 0 and staging_pinned(limited) is not None
    assert f"environment limit accepted: {SPEC_ID} (dev): {REASON}" in out


def test_the_override_puts_the_line_in_the_pr_body(limited, opened, capsys):  # AC-190.3
    rc, out = attempt(to(limited, "staging", "--pr", "--accept-environment-limit", REASON), capsys)
    assert rc == 0 and len(opened) == 1
    line = f"environment limit accepted: {SPEC_ID} (dev): {REASON}"
    assert line in out and line in opened[0]


def test_the_override_in_a_dry_run_shows_the_accepted_line_and_exits_0(limited, capsys):  # AC-190.3
    rc, out = attempt(to(limited, "staging", "--dry-run", "--json", "--accept-environment-limit", REASON), capsys)
    got = json.loads(out)
    assert rc == 0 and unchanged(limited)
    assert any(f"environment limit accepted: {SPEC_ID} (dev): {REASON}" in s for s in got["will_do"])
    (lim,) = got["environment_limits"]
    assert lim["accepted"] is True and lim["reason"] == REASON


def test_one_flag_covers_every_limiting_spec(limited, capsys):  # AC-190.3
    write_spec(limited, "051-no-export", "No export", field="environments: [dev, prod]\n")
    commit(limited, "second")
    rc, out = attempt(to(limited, "staging", "--dry-run", "--accept-environment-limit", REASON), capsys)
    assert rc == 0
    assert f"environment limit accepted: {SPEC_ID} (dev): {REASON}" in out
    assert f"environment limit accepted: 051-no-export (dev, prod): {REASON}" in out


@pytest.mark.parametrize("reason", ["", "ok", "no full stop here", "two words."])
def test_a_short_reason_is_refused_before_anything_is_read(tmp_path, capsys, reason):  # AC-190.3
    """The repo does not exist: only an argument-time refusal can name the reason."""
    rc, out = attempt(["todo-api", "--to", "staging", "--repo-dir", str(tmp_path / "nowhere"), "--accept-environment-limit", reason], capsys)
    assert rc != 0 and "--accept-environment-limit" in out and "reason" in out.lower() and "unrecognized" not in out


@pytest.mark.parametrize("reason", ["Accepted on purpose!", "Is it really intended?"])
def test_other_sentence_ends_are_accepted(limited, capsys, reason):  # AC-190.3
    assert attempt(to(limited, "staging", "--accept-environment-limit", reason), capsys)[0] == 0


def test_a_short_reason_with_a_limit_changes_nothing(limited, capsys):  # AC-190.3
    rc, out = attempt(to(limited, "staging", "--accept-environment-limit", "no."), capsys)
    assert rc != 0 and unchanged(limited) and staging_pinned(limited) is None and "unrecognized" not in out


def test_the_flag_without_a_limit_changes_nothing(gitops_repo, gh, capsys):  # AC-190.3  # noqa: F811
    composed(gitops_repo, "todo-api")
    capsys.readouterr()                                   # composed() printed to the same capture
    rc, out = attempt(to(gitops_repo, "staging", "--dry-run", "--json", "--accept-environment-limit", REASON), capsys)
    assert rc == 0 and json.loads(out)["environment_limits"] == [] and "environment limit" not in out


