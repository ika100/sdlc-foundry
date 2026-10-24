"""Spec 096: `cplat fleet update` brings every platform repo to the installed release.

GitHub is faked (see fleet_world.py): `fleet.gh` answers the design's exact argument lists, `fleet.clone` clones a local bare repo,
`pr.wait` and `fleet.sleep` are replaced. The update itself is the real `update.resolve` + `update.execute`.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

import core
import cplat
import runs
import update
from fleet_world import LABEL, OLD, TARGET, git, row, seed, world  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[2]
URL1 = "https://github.com/{}/pull/1"
MAJOR_OLD = "3.9.0"


def own_test_recipe(work):
    f = work / "devbox.json"
    d = json.loads(f.read_text())
    d["shell"]["scripts"]["test"] = "go test ./... -v"
    f.write_text(json.dumps(d, indent=2) + "\n")


def drop_an_answer(work):
    """The repo's answers lack a question the template has since gained (it has a default): the update adds it."""
    f = work / ".copier-answers.yml"
    f.write_text("\n".join(ln for ln in f.read_text().splitlines() if not ln.startswith("platform_marketplace_ref:")) + "\n")


def cells(line):
    return [c for c in re.split(r"\s{2,}", line.strip()) if c]


# ---------------- AC-096.1: which repos ----------------

def test_only_stamped_platform_repos_of_the_owner_are_considered(world):  # AC-096.1
    world.add("acme/todo")
    world.add("acme/plain", platform=False)                                           # no stamp, no answers
    world.add("acme/nostamp", stamp=False)                                            # answers but no .platform-version
    world.add("acme/foreign", src="gh:other/stuff/templates/not-a-platform-shape")    # stamp, but another template
    world.add("acme/old-one", archived=True)
    world.add("acme/forked", fork=True)
    world.add("someone/else")                                                         # another owner
    rc, doc, _ = world.json()
    assert [r["repo"] for r in doc["repos"]] == ["acme/todo"] and doc["owners"] == ["acme"]
    for slug in ("acme/plain", "acme/nostamp", "acme/foreign", "acme/old-one", "acme/forked", "someone/else"):
        assert ("clone", slug) not in world.log and not world.calls_for(slug, "pr", "create")
        assert not any(slug in r["repo"] for r in doc["repos"])
    assert ["repo", "list", "acme", "--no-archived", "--source", "--json", "nameWithOwner,isArchived,isFork,defaultBranchRef",
            "--limit", "1000"] in world.calls
    assert ["api", "user", "-q", ".login"] in world.calls


def test_the_default_owner_is_the_gh_login_and_owner_is_repeatable(world):  # AC-096.1
    world.add("acme/a", TARGET)
    world.add("zed/b", TARGET)
    world.login = "acme"
    _, doc, _ = world.json()
    assert doc["owners"] == ["acme"] and [r["repo"] for r in doc["repos"]] == ["acme/a"]
    world.calls.clear()
    _, doc, _ = world.json("--owner", "acme", "--owner", "zed", "--owner", "acme")
    assert doc["owners"] == ["acme", "zed", "acme"] or doc["owners"] == ["acme", "zed"]
    assert [r["repo"] for r in doc["repos"]] == ["acme/a", "zed/b"]
    assert ["api", "user", "-q", ".login"] not in world.calls


def test_no_gh_login_is_an_error_before_anything_runs(world):  # AC-096.1
    world.login = ""
    rc, out, err = world.run()
    assert rc == 1 and "gh is not logged in" in err and "gh auth login" in err
    assert not world.writes() and not world.log


def test_a_failing_repo_list_is_an_error(world):  # AC-096.1
    world.add("acme/a")
    world.list_error["acme"] = "HTTP 502: bad gateway\nmore"
    rc, out, err = world.run()
    assert rc == 1 and "cannot list repos of acme: HTTP 502: bad gateway" in err and not world.log


def test_the_command_is_registered_and_has_a_slash_command():  # AC-096.1
    assert cplat.COMMANDS["fleet"] == "fleet"
    cmd = (ROOT / "plugins" / "shared" / "commands" / "fleet.md").read_text()
    assert "cplat fleet update" in cmd and "$ARGUMENTS" in cmd


def test_fleet_takes_only_the_update_subcommand(world):  # AC-096.1
    import fleet
    with pytest.raises(SystemExit) as e:
        fleet.main(["bogus"])
    assert e.value.code == 2


# ---------------- AC-096.2: up to date ----------------

def test_a_repo_at_or_beyond_the_target_is_up_to_date_and_untouched(world):  # AC-096.2
    world.add("acme/same", TARGET)
    world.add("acme/newer", "99.0.0")
    rc, doc, _ = world.json()
    assert rc == 0 and doc["target"] == TARGET
    for slug in ("acme/same", "acme/newer"):
        r = row(doc, slug)
        assert r["outcome"] == "up to date" and r["pr"] is None and r["reason"] is None
        assert ("clone", slug) not in world.log and world.branches(slug) == ["main"]
    assert row(doc, "acme/same")["from"] == TARGET and not world.writes()


def test_an_update_that_changes_nothing_is_up_to_date(world, monkeypatch):  # AC-096.2
    world.add("acme/noop", "4.3.0")
    monkeypatch.setattr(update, "execute", lambda req: core.Report(title="nothing", did=["nothing changed"]))
    rc, doc, _ = world.json()
    assert rc == 0 and row(doc, "acme/noop")["outcome"] == "up to date" and not world.calls_for("acme/noop", "pr", "create")
    assert world.branches("acme/noop") == ["main"]


def test_ref_must_be_the_installed_version(world):  # AC-096.2
    world.add("acme/todo")
    rc, out, err = world.run("--ref", "v99.0.0")
    assert rc == 1 and f"--ref v99.0.0 is not the platform this command runs ({TARGET})" in err
    assert "CPLAT_REF=v99.0.0 cplat fleet update --ref v99.0.0" in err
    assert not world.log and not world.writes()
    rc, out, err = world.run("--ref", "v99.0.0", "--dry-run")
    assert rc == 1 and "is not the platform this command runs" in err and not world.log
    rc, out, err = world.run("--ref", "latest")
    assert rc == 1 and "ERROR" in err and not world.log
    rc, doc, _ = world.json("--ref", f"v{TARGET}")
    assert rc == 0 and doc["ref"] in (f"v{TARGET}", TARGET)


# ---------------- AC-096.3: the update is update-service's, in a PR ----------------

def test_a_behind_repo_gets_update_services_commit_on_a_pushed_branch_and_one_pr(world, tmp_path):  # AC-096.3
    world.add("acme/todo")
    world.wait_result = lambda slug, url: (False, [f"RED: 1 of 2 check(s) failed on {url}: build"])   # keep it simple: stays open
    rc, doc, _ = world.json()
    p = world.pr_for("acme/todo")
    branch = p["headRefName"]
    assert re.fullmatch(r"chore/platform-update-\d{8}(-\d+)?", branch) and branch in world.branches("acme/todo")
    assert p["title"] == f"chore: platform update {OLD} → {TARGET}"
    assert row(doc, "acme/todo")["pr"] == p["url"]
    bare = world.repos["acme/todo"]["bare"]
    assert git(bare, "log", "-1", "--format=%s", branch) == f"chore: update skeleton from platform {TARGET}"
    assert git(bare, "rev-list", "--count", f"main..{branch}") == "1"
    # the same commit /shared:update-service makes on a plain clone of the repo
    ref = tmp_path / "reference"
    subprocess.run(["git", "clone", "-q", str(bare), str(ref)], check=True)
    git(ref, "checkout", "-q", "main")
    git(ref, "checkout", "-q", "-b", "reference")
    update.execute(update.resolve(["--repo", str(ref), "--skip-tasks"]))
    assert git(bare, "rev-parse", f"{branch}^{{tree}}") == git(ref, "rev-parse", "HEAD^{tree}")
    assert git(bare, "show", f"{branch}:.platform-version").count(f"platform: {TARGET}") == 1
    assert git(bare, "rev-parse", "main") == git(bare, "rev-parse", "main")                    # the default branch is not moved
    assert len(world.calls_for("acme/todo", "pr", "create")) == 1


def test_the_pr_body_is_the_update_report(world):  # AC-096.3
    world.add("acme/todo")
    world.wait_result = lambda slug, url: (False, [f"RED: 1 of 2 check(s) failed on {url}: build"])
    world.json()
    body = world.pr_for("acme/todo")["body"]
    assert body.startswith("<!-- cplat-fleet -->") and len(body) <= 60000
    assert f"{OLD} → {TARGET}" in body
    for heading in ("### Changed files", "### devbox.json", "### Overwritten customisations (spec 086)", "### Follow-up steps",
                    f"### Platform changes {OLD} → {TARGET}"):
        assert heading in body, heading
    assert "`.platform-version`" in body
    assert "kept:" in body and "replaced by the template:" in body
    assert f"## [{TARGET}]" in body or TARGET in body.split("### Platform changes", 1)[1]


def test_project_owned_files_are_left_to_the_repo(world):  # AC-096.3
    world.add("acme/todo", mutate=lambda w: (w / "README.md").write_text("# my own readme\n"))
    world.wait_result = lambda slug, url: (False, [f"RED: 1 of 2 check(s) failed on {url}: build"])
    world.json()
    branch = world.pr_for("acme/todo")["headRefName"]
    assert git(world.repos["acme/todo"]["bare"], "show", f"{branch}:README.md") == "# my own readme"


# ---------------- AC-096.15: routine updates merge ----------------

def test_a_routine_update_waits_for_ci_and_is_merged(world):  # AC-096.15
    world.add("acme/todo")
    rc, doc, _ = world.json("--timeout", "120")
    r = row(doc, "acme/todo")
    assert rc == 0 and r["outcome"] == "merged" and r["reason"] is None and r["from"] == OLD and r["to"] == TARGET
    (call,) = world.waits
    clone, url, merge, timeout, interval, queue, slug = call
    assert url == r["pr"] == world.pr_for("acme/todo")["url"] and merge is True and timeout == 120 and slug == "acme/todo"
    assert interval == 20
    assert not world.comments("acme/todo") and not world.pr_for("acme/todo")["labels"]
    assert not world.calls_for("acme/todo", "label", "create")


def test_the_default_ci_wait_is_an_hour(world):  # AC-096.15
    world.add("acme/todo")
    world.json()
    assert world.waits[0][3] == 3600


def test_the_clone_is_removed_when_the_repo_is_finished(world):  # AC-096.15
    world.add("acme/todo")
    world.json()
    assert not world.waits[0][0].exists()


# ---------------- AC-096.16: customisations ----------------

def test_a_replaced_customisation_keeps_the_pr_open_with_label_and_comment(world):  # AC-096.16
    world.add("acme/todo", mutate=own_test_recipe)
    rc, out, _ = world.run()
    p = world.pr_for("acme/todo")
    assert rc == 1 and not world.waits
    assert [lb["name"] for lb in p["labels"]] == [LABEL]
    assert ["label", "create", LABEL, "-R", "acme/todo", "--color", "D93F0B", "--description",
            "A platform fleet update needs a person (spec 096)"] in world.calls
    (comment,) = world.comments("acme/todo")
    assert comment.startswith("<!-- cplat-fleet -->") and "local customisation" in comment
    assert "devbox.json" in comment and "scripts test" in comment
    assert re.search(r"acme/todo.*left open: local customisation.*" + re.escape(p["url"]), out)


def test_every_listed_customisation_is_named_in_the_comment(world):  # AC-096.16
    def two(work):
        own_test_recipe(work)
        (work / ".golangci.yml").write_text("# my lint config\n")
    world.add("acme/todo", mutate=two)
    world.json()
    (comment,) = world.comments("acme/todo")
    assert "scripts test" in comment and "`.golangci.yml`" in comment


def test_a_missing_label_is_created_and_a_failing_create_is_ignored(world, monkeypatch):  # AC-096.16
    world.add("acme/todo", mutate=own_test_recipe)
    orig = world.gh

    def gh(args, **k):
        if list(args[:2]) == ["label", "create"]:
            world.calls.append(list(args))
            return 1, "", "already exists"
        return orig(args, **k)
    world.gh = gh
    rc, doc, _ = world.json()
    assert row(doc, "acme/todo")["outcome"] == "left open" and [lb["name"] for lb in world.pr_for("acme/todo")["labels"]] == [LABEL]


# ---------------- AC-096.6: red, conflict, no checks ----------------

def test_red_ci_leaves_the_pr_open_with_the_failing_check(world):  # AC-096.6
    world.add("acme/todo")
    world.wait_result = lambda slug, url: (False, [f"RED: 2 of 5 check(s) failed on {url}: build, lint", "log..."])
    rc, doc, _ = world.json()
    r = row(doc, "acme/todo")
    assert rc == 1 and r["outcome"] == "left open" and r["reason"] == "red CI: build, lint"
    assert [lb["name"] for lb in world.pr_for("acme/todo")["labels"]] == [LABEL]
    (comment,) = world.comments("acme/todo")
    assert "red CI: build, lint" in comment and comment.startswith("<!-- cplat-fleet -->")


def test_a_merge_conflict_is_left_open_without_waiting(world):  # AC-096.6
    world.add("acme/todo")
    world.mergeable["acme/todo"] = ["CONFLICTING"]
    rc, doc, _ = world.json()
    r = row(doc, "acme/todo")
    assert rc == 1 and r["outcome"] == "left open" and r["reason"] == "merge conflict" and not world.waits
    assert "merge conflict" in world.comments("acme/todo")[0]
    assert [lb["name"] for lb in world.pr_for("acme/todo")["labels"]] == [LABEL]


def test_an_unknown_mergeable_is_re_read_with_a_pause_and_then_ignored(world):  # AC-096.6
    world.add("acme/todo")
    world.mergeable["acme/todo"] = ["UNKNOWN", "UNKNOWN", "MERGEABLE"]
    _, doc, _ = world.json()
    assert row(doc, "acme/todo")["outcome"] == "merged" and world.sleeps == [3, 3]
    world.add("acme/other")
    world.mergeable["acme/other"] = ["UNKNOWN"]
    world.sleeps.clear()
    _, doc, _ = world.json("--only", "acme/other")
    assert row(doc, "acme/other")["outcome"] == "merged" and world.sleeps == [3] * 10


def test_a_merge_that_fails_on_a_conflict_is_a_merge_conflict(world):  # AC-096.6
    world.add("acme/todo")
    world.mergeable["acme/todo"] = ["MERGEABLE", "CONFLICTING"]

    def boom(slug, url):
        raise core.PlatformError("merging " + url + " failed: not mergeable")
    world.wait_result = boom
    _, doc, _ = world.json()
    assert row(doc, "acme/todo")["reason"] == "merge conflict"


@pytest.mark.parametrize("message, reason", [
    ("no CI checks on https://x/pull/1 after 60s", "no CI checks"),
    ("checks on https://x/pull/1 are still pending after 3600s", "CI still pending after 3600s"),
    ("merging https://x/pull/1 failed: policy\nmore", "merge failed: merging https://x/pull/1 failed: policy"),
    ("https://x/pull/1 was closed without merging", "CI wait failed: https://x/pull/1 was closed without merging"),
])
def test_ci_wait_errors_are_left_open_with_a_reason(world, message, reason):  # AC-096.6
    world.add("acme/todo")

    def boom(slug, url):
        raise core.PlatformError(message)
    world.wait_result = boom
    rc, doc, _ = world.json()
    r = row(doc, "acme/todo")
    assert rc == 1 and r["outcome"] == "left open" and r["reason"] == reason
    assert r["pr"] and [lb["name"] for lb in world.pr_for("acme/todo")["labels"]] == [LABEL]


def test_the_label_is_not_added_twice_and_the_comment_is_not_repeated(world):  # AC-096.6
    world.add("acme/todo")
    world.wait_result = lambda slug, url: (False, [f"RED: 1 of 2 check(s) failed on {url}: build"])
    world.json()
    world.json()
    assert len(world.prs("acme/todo")) == 1
    assert len(world.comments("acme/todo")) == 1
    assert [lb["name"] for lb in world.pr_for("acme/todo")["labels"]] == [LABEL]


# ---------------- AC-096.7: major versions ----------------

def test_a_major_update_is_never_merged_and_points_to_the_changelog(world):  # AC-096.7
    world.add("acme/todo", MAJOR_OLD)
    rc, doc, _ = world.json()
    r = row(doc, "acme/todo")
    major = int(TARGET.split(".")[0])
    assert rc == 1 and r["outcome"] == "left open" and r["reason"] == f"major version 3 → {major}"
    assert not world.waits and r["pr"]
    (comment,) = world.comments("acme/todo")
    assert f"Major platform update {MAJOR_OLD} → {TARGET} is never merged automatically" in comment
    assert f"migration notes for {major}.0.0" in comment
    assert f"https://github.com/ika100/sdlc-foundry/blob/v{TARGET}/docs/CHANGELOG.md" in comment
    assert [lb["name"] for lb in world.pr_for("acme/todo")["labels"]] == [LABEL]


def test_a_major_update_with_customisations_gives_both_reasons_in_one_comment(world):  # AC-096.7
    world.add("acme/todo", MAJOR_OLD, mutate=own_test_recipe)
    _, doc, _ = world.json()
    assert row(doc, "acme/todo")["reason"].startswith("local customisation; major version 3")
    (comment,) = world.comments("acme/todo")
    assert "This update overwrote what the repo added (spec 086):" in comment and "Major platform update" in comment


def test_an_unreadable_stamp_counts_as_a_major_update(world):  # AC-096.7
    world.add("acme/todo", mutate=lambda w: (w / ".platform-version").write_text("# no version here\nshape: service-go\n"))
    _, doc, _ = world.json()
    r = row(doc, "acme/todo")
    assert r["from"] == "none" and r["outcome"] == "left open" and r["reason"].startswith("major version unknown")
    assert not world.waits


# ---------------- AC-096.8: an existing fleet PR is updated ----------------

def test_a_second_run_updates_the_open_pr_and_keeps_its_label(world):  # AC-096.8
    world.add("acme/todo")
    world.wait_result = lambda slug, url: (False, [f"RED: 1 of 2 check(s) failed on {url}: build"])
    world.json()
    first = dict(world.pr_for("acme/todo"))
    labels = [lb["name"] for lb in first["labels"]]
    assert labels == [LABEL]
    world.wait_result = lambda slug, url: (True, [f"merged {url}"])
    world.calls.clear()
    rc, doc, _ = world.json()
    p = world.pr_for("acme/todo")                               # still exactly one PR
    assert p["url"] == first["url"] and row(doc, "acme/todo")["pr"] == first["url"] and row(doc, "acme/todo")["outcome"] == "merged"
    assert not world.calls_for("acme/todo", "pr", "create")
    assert [lb["name"] for lb in p["labels"]] == [LABEL]
    assert [c for c in world.calls if c[:2] == ["pr", "edit"] and "--title" in c]
    assert not [c for c in world.calls if "--remove-label" in c]
    assert [b for b in world.branches("acme/todo") if b.startswith("chore/platform-update-")] == [first["headRefName"]]
    bare = world.repos["acme/todo"]["bare"]
    assert git(bare, "rev-list", "--count", f"main..{first['headRefName']}") == "1"


def test_a_pr_with_manual_commits_is_not_force_pushed(world):  # AC-096.8
    world.add("acme/todo")
    world.wait_result = lambda slug, url: (False, [f"RED: 1 of 2 check(s) failed on {url}: build"])
    world.json()
    branch = world.pr_for("acme/todo")["headRefName"]
    bare = world.repos["acme/todo"]["bare"]
    work = world.tmp / "person"
    subprocess.run(["git", "clone", "-q", "-b", branch, str(bare), str(work)], check=True)
    (work / "FIX.md").write_text("a person fixed something\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "fix the build by hand")
    git(work, "push", "-q", "origin", branch)
    tip = git(bare, "rev-parse", branch)
    world.wait_result = lambda slug, url: (True, [f"merged {url}"])
    world.waits.clear()
    rc, doc, _ = world.json()
    r = row(doc, "acme/todo")
    assert rc == 1 and r["outcome"] == "left open" and r["reason"] == f"manual commits on {branch}"
    assert git(bare, "rev-parse", branch) == tip and not world.waits


# ---------------- AC-096.9: failures do not stop the fleet ----------------

def test_a_failing_repo_is_reported_and_the_rest_is_processed(world):  # AC-096.9
    world.add("acme/a-denied")
    world.add("acme/b-fine")
    world.clone_error["acme/a-denied"] = "permission denied\nsecond line"
    rc, doc, _ = world.json()
    assert rc == 1
    a, b = row(doc, "acme/a-denied"), row(doc, "acme/b-fine")
    assert a["outcome"] == "failed" and a["reason"] == "clone of acme/a-denied failed: permission denied" and a["pr"] is None
    assert b["outcome"] == "merged"
    assert world.branches("acme/a-denied") == ["main"]


def test_unreadable_answers_fail_that_repo_only(world):  # AC-096.9
    world.add("acme/a-broken")
    world.add("acme/b-fine")
    world.read_error[("acme/a-broken", ".copier-answers.yml")] = "HTTP 500: server error\nboom"
    rc, doc, _ = world.json()
    a = row(doc, "acme/a-broken")
    assert rc == 1 and a["outcome"] == "failed" and a["reason"] == "cannot read .copier-answers.yml: HTTP 500: server error"
    assert row(doc, "acme/b-fine")["outcome"] == "merged"


def test_a_template_step_error_is_failed_with_its_first_line(world, monkeypatch):  # AC-096.9
    world.add("acme/a-bad")
    world.add("acme/b-fine")
    real = update.execute

    def execute(req):
        if req["repo"].name.endswith("a-bad") or "a-bad" in str(req["repo"]) or not getattr(execute, "done", False):
            execute.done = True
            raise core.PlatformError("copier exploded\ntraceback...")
        return real(req)
    monkeypatch.setattr(update, "execute", execute)
    rc, doc, _ = world.json()
    a = row(doc, "acme/a-bad")
    assert rc == 1 and a["outcome"] == "failed" and a["reason"] == "copier exploded" and a["pr"] is None
    assert row(doc, "acme/b-fine")["outcome"] == "merged"
    assert not world.calls_for("acme/a-bad", "pr", "create")


def test_a_failing_pr_call_is_failed_with_the_step(world):  # AC-096.9
    world.add("acme/a-nopr")
    world.add("acme/b-fine")
    orig = world.gh

    def gh(args, **k):
        if list(args[:2]) == ["pr", "create"] and "acme/a-nopr" in args:
            world.calls.append(list(args))
            return 1, "", "GraphQL: Resource not accessible\nmore"
        return orig(args, **k)
    world.gh = gh
    rc, doc, _ = world.json()
    a = row(doc, "acme/a-nopr")
    assert rc == 1 and a["outcome"] == "failed" and "Resource not accessible" in a["reason"] and "\n" not in a["reason"]
    assert row(doc, "acme/b-fine")["outcome"] == "merged"


def test_an_exception_without_a_message_names_its_class(world, monkeypatch):  # AC-096.9
    world.add("acme/a-bad")

    def boom(req):
        raise KeyError()
    monkeypatch.setattr(update, "execute", boom)
    _, doc, _ = world.json()
    assert row(doc, "acme/a-bad")["outcome"] == "failed" and "KeyError" in row(doc, "acme/a-bad")["reason"]


# ---------------- AC-096.10: dry run ----------------

def test_a_dry_run_changes_nothing_and_says_what_would_happen(world):  # AC-096.10
    world.add("acme/a-behind")
    world.add("acme/b-current", TARGET)
    world.add("acme/c-major", MAJOR_OLD)
    rc, doc, _ = world.json("--dry-run")
    assert rc == 0 and doc["dry_run"] is True
    assert row(doc, "acme/a-behind")["outcome"] == "would update" and row(doc, "acme/a-behind")["from"] == OLD \
        and row(doc, "acme/a-behind")["to"] == TARGET
    assert row(doc, "acme/b-current")["outcome"] == "up to date"
    c = row(doc, "acme/c-major")
    assert c["outcome"] == "would update" and "major version: the PR will stay open" in c["next"]
    assert not world.log and not world.writes() and not [c for c in world.calls if c[:2] == ["pr", "view"]]
    assert all(world.branches(s) == ["main"] for s in world.repos)
    assert not (runs.state_dir() / "buffer.jsonl").exists() and not list((runs.state_dir() / "active").glob("*"))


def test_a_dry_run_names_an_open_fleet_pr_and_lists_skips(world):  # AC-096.10
    world.add("acme/todo")
    world.repos["acme/todo"]["prs"].append({"number": 4, "url": URL1.format("acme/todo").replace("/1", "/4"),
                                            "headRefName": "chore/platform-update-20260101", "labels": []})
    world.add("acme/plain", platform=False)
    world.add("acme/gone", archived=True)
    _, doc, _ = world.json("--dry-run", "--only", "acme/todo", "--only", "acme/plain", "--only", "acme/gone")
    assert "would update open PR https://github.com/acme/todo/pull/4" in row(doc, "acme/todo")["next"]
    assert row(doc, "acme/plain")["outcome"] == "skipped" and row(doc, "acme/plain")["reason"] == "not a platform repo"
    assert row(doc, "acme/gone")["outcome"] == "skipped" and row(doc, "acme/gone")["reason"] == "archived"
    rc, out, _ = world.run("--dry-run")
    assert "dry run, nothing was changed" in out.splitlines()[0]
    assert not world.writes()


# ---------------- AC-096.11: report and exit code ----------------

def test_the_report_has_a_row_per_repo_and_a_count_per_outcome(world):  # AC-096.11
    world.add("acme/a-merged")
    world.add("acme/b-current", TARGET)
    world.add("acme/c-open", mutate=own_test_recipe)
    rc, out, _ = world.run()
    lines = out.splitlines()
    assert lines[0].startswith(f"Fleet update to platform {TARGET} (owners: acme)")
    assert cells(next(ln for ln in lines if ln.strip().startswith("repo")))[:5] == ["repo", "from", "to", "outcome", "PR"]
    a = cells(next(ln for ln in lines if "acme/a-merged" in ln))
    assert a == ["acme/a-merged", OLD, TARGET, "merged", "https://github.com/acme/a-merged/pull/1"]
    b = cells(next(ln for ln in lines if "acme/b-current" in ln))
    assert b == ["acme/b-current", TARGET, "-", "up to date", "-"]
    c = cells(next(ln for ln in lines if "acme/c-open" in ln))
    assert c[3] == "left open: local customisation" and c[4] == "https://github.com/acme/c-open/pull/1"
    assert lines[-1] == "3 repo(s): up to date 1, merged 1, left open 1" and rc == 1


def test_no_platform_repos_found(world):  # AC-096.11
    world.add("acme/plain", platform=False)
    rc, out, _ = world.run()
    assert rc == 0 and "no platform repos found" in out
    rc, doc, _ = world.json()
    assert doc["repos"] == [] and doc["counts"] == {} and doc["exit"] == 0


def test_exit_codes(world):  # AC-096.11
    world.add("acme/a", TARGET)
    world.add("acme/b")
    rc, doc, _ = world.json()
    assert rc == 0 and doc["exit"] == 0 and doc["counts"] == {"up to date": 1, "merged": 1}
    world.add("acme/c", MAJOR_OLD)
    rc, doc, _ = world.json("--only", "acme/c")
    assert rc == 1 and doc["exit"] == 1 and doc["counts"] == {"left open": 1}
    world.clone_error["acme/d"] = "no"
    world.add("acme/d")
    rc, doc, _ = world.json("--only", "acme/d")
    assert rc == 1 and doc["counts"] == {"failed": 1}


def test_json_is_the_only_thing_on_stdout_and_has_the_documented_shape(world):  # AC-096.11
    world.add("acme/todo")
    rc, out, err = world.run("--json")
    doc = json.loads(out)                                                      # progress goes to stderr, not into the document
    assert set(doc) == {"target", "ref", "owners", "only", "dry_run", "repos", "counts", "exit"}
    assert set(doc["repos"][0]) == {"repo", "from", "to", "outcome", "reason", "pr", "next"}
    assert doc["only"] == [] and doc["ref"] is None and doc["target"] == TARGET
    assert doc["repos"][0]["pr"] == "https://github.com/acme/todo/pull/1"


def test_counts_follow_the_fixed_order(world):  # AC-096.11
    world.add("acme/a-open", mutate=own_test_recipe)
    world.add("acme/b-merged")
    world.add("acme/c-current", TARGET)
    world.add("acme/d-failed")
    world.clone_error["acme/d-failed"] = "nope"
    _, out, _ = world.run()
    assert out.splitlines()[-1] == "4 repo(s): up to date 1, merged 1, left open 1, failed 1"


# ---------------- AC-096.12: run record ----------------

def buffered():
    f = runs.state_dir() / "buffer.jsonl"
    return [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()] if f.is_file() else []


def test_the_fleet_run_is_recorded_with_each_repos_outcome(world):  # AC-096.12
    world.add("acme/a-open", mutate=own_test_recipe)
    world.add("acme/b-merged")
    rc, doc, _ = world.json()
    (rec,) = [r for r in buffered() if r["kind"] == "fleet"]
    assert rec["outcome"] == "escalated" and rec["escalation"]["reason"] == "1 repo(s) left open for review"
    assert rec["fleet"]["target"] == TARGET and rec["fleet"]["counts"] == {"merged": 1, "left open": 1}
    by = {e["id"]: e for e in rec["repos"]}
    assert by["acme/a-open"]["outcome"] == "left open" and by["acme/a-open"]["reason"] == "local customisation"
    assert by["acme/a-open"]["pr"] == row(doc, "acme/a-open")["pr"] and by["acme/a-open"]["from"] == OLD
    assert by["acme/b-merged"]["outcome"] == "merged" and by["acme/b-merged"]["to"] == TARGET
    assert not [r for r in buffered() if r["kind"] != "fleet"]


@pytest.mark.parametrize("setup, outcome", [("ok", "done"), ("fail", "failed")])
def test_the_fleet_record_ends_done_or_failed(world, setup, outcome):  # AC-096.12
    world.add("acme/a", TARGET if setup == "ok" else OLD)
    world.clone_error["acme/a"] = "denied"
    world.json()
    (rec,) = buffered()
    assert rec["kind"] == "fleet" and rec["outcome"] == outcome


def test_an_unreachable_run_store_changes_neither_output_nor_exit_code(world, monkeypatch):  # AC-096.12
    world.add("acme/a-open", mutate=own_test_recipe)
    world.add("acme/b-merged")
    rc0, doc0, _ = world.json()
    for slug in world.repos:
        world.repos[slug]["prs"].clear()
        world.repos[slug]["n"] = 0
        subprocess.run(["git", "branch", "-D", *[b for b in world.branches(slug) if b != "main"]], cwd=world.repos[slug]["bare"],
                       capture_output=True)
    monkeypatch.setenv("CPLAT_RUNS_REPO", "acme/runs")

    def down(slug):
        raise OSError("store unreachable")
    monkeypatch.setattr(runs, "open_store", down)
    rc1, doc1, err = world.json()
    assert (rc1, doc1) == (rc0, doc0)


def test_a_discovery_error_finishes_the_record_failed(world):  # AC-096.12
    world.add("acme/a")
    world.list_error["acme"] = "HTTP 502"
    rc, out, err = world.run()
    assert rc == 1
    (rec,) = buffered()
    assert rec["kind"] == "fleet" and rec["outcome"] == "failed"


def test_fleet_does_not_make_nested_waits_its_children(world, monkeypatch):  # AC-096.12
    monkeypatch.setenv("CPLAT_RUN_PARENT", "")
    seen = []
    world.add("acme/a")
    orig = world.wait

    def wait(*a, **k):
        import os
        seen.append(os.environ.get("CPLAT_RUN_PARENT"))
        return orig(*a, **k)
    monkeypatch.setattr(__import__("pr"), "wait", wait)
    world.json()
    assert not any(seen)


# ---------------- AC-096.13: --only ----------------

def test_only_processes_exactly_the_named_repos(world):  # AC-096.13
    world.add("acme/a")
    world.add("acme/b")
    world.add("acme/c")
    rc, doc, _ = world.json("--only", "acme/c", "--only", "acme/a", "--owner", "ignored")
    assert [r["repo"] for r in doc["repos"]] == ["acme/a", "acme/c"] and doc["only"] == ["acme/c", "acme/a"]
    assert ("clone", "acme/b") not in world.log and not [c for c in world.calls if c[:2] == ["repo", "list"]]
    assert ["repo", "view", "acme/a", "--json", "nameWithOwner,isArchived,isFork,defaultBranchRef"] in world.calls


def test_a_named_repo_that_is_not_a_platform_repo_is_skipped(world):  # AC-096.13
    world.add("acme/plain", platform=False)
    world.add("acme/foreign", src="gh:other/stuff/templates/nothing")
    rc, doc, _ = world.json("--only", "acme/plain", "--only", "acme/foreign")
    assert rc == 0
    for slug in ("acme/plain", "acme/foreign"):
        r = row(doc, slug)
        assert r["outcome"] == "skipped" and r["reason"] == "not a platform repo" and r["pr"] is None
    _, out, _ = world.run("--only", "acme/plain")
    assert "skipped: not a platform repo" in out and out.splitlines()[-1] == "1 repo(s): skipped 1"


def test_an_unreadable_or_malformed_only_value(world):  # AC-096.13
    world.add("acme/a")
    rc, out, err = world.run("--only", "not-a-slug")
    assert rc == 1 and "ERROR" in err and not world.calls
    rc, doc, _ = world.json("--only", "acme/missing")
    assert row(doc, "acme/missing")["outcome"] == "failed" and row(doc, "acme/missing")["reason"].startswith("cannot read acme/missing")


# ---------------- AC-096.14: follow-up steps ----------------

@pytest.mark.parametrize("hold", [False, True])
def test_follow_up_steps_are_relayed_whether_or_not_the_pr_merged(world, hold):  # AC-096.14
    world.add("acme/todo", MAJOR_OLD if hold else OLD, mutate=drop_an_answer)
    rc, doc, _ = world.json()
    r = row(doc, "acme/todo")
    assert r["outcome"] == ("left open" if hold else "merged")
    assert any(s.startswith("new template answers took their defaults") for s in r["next"])
    assert not any(s.startswith("run the repo's checks:") or s.startswith("platform changes since your version") for s in r["next"])


def test_follow_ups_are_printed_under_the_repos_row(world):  # AC-096.14
    world.add("acme/a-todo", mutate=drop_an_answer)
    world.add("acme/b-plain")
    _, out, _ = world.run()
    lines = out.splitlines()
    i = next(i for i, ln in enumerate(lines) if "acme/a-todo" in ln)
    assert lines[i + 1].strip().startswith("next: new template answers took their defaults") and lines[i + 1].startswith("      next:")
    j = next(i for i, ln in enumerate(lines) if "acme/b-plain" in ln)
    assert not lines[j + 1].strip().startswith("next:")
    body = world.pr_for("acme/a-todo")["body"]
    assert "new template answers took their defaults" in body.split("### Follow-up steps")[1].split("###")[0]


# ---------------- AC-096.17: one at a time, alphabetical ----------------

def test_repos_are_processed_one_at_a_time_in_alphabetical_order(world):  # AC-096.17
    for slug in ("zed/last", "acme/b", "Mixed/case", "acme/a", "acme/c"):
        world.add(slug)
    world.run("--owner", "zed", "--owner", "acme", "--owner", "Mixed", "--owner", "acme")
    order = [s for _, s in world.log]
    grouped = [s for i, s in enumerate(order) if i == 0 or order[i - 1] != s]
    assert grouped == ["acme/a", "acme/b", "acme/c", "Mixed/case", "zed/last"]       # case-insensitive; no interleaving; no repeats
    for slug in grouped:
        assert [k for k, s in world.log if s == slug] == ["clone", "create", "wait"]


def test_a_repo_is_finished_including_its_ci_wait_before_the_next_starts(world):  # AC-096.17
    world.add("acme/a")
    world.add("acme/b")
    seen = []

    def wait(slug, url):
        seen.append((slug, [c for c in world.calls if c[:2] == ["pr", "create"] and "acme/b" in c], ("clone", "acme/b") in world.log))
        return True, ["merged"]
    world.wait_result = wait
    world.json()
    assert seen[0] == ("acme/a", [], False) and seen[1][0] == "acme/b"


def test_the_only_time_limit_is_each_prs_own_ci_wait(world):  # AC-096.17
    world.add("acme/a")
    world.json("--timeout", "45")
    assert world.waits[0][3] == 45
