"""Spec 164: the journey 7 findings (#595–#600)."""
import json

import pytest

import envwait
from test_143_envwait import World, git
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)

BACKUP_YAML = """system: shop
owner: acme
environments:
  dev: {host: '{component}.localhost'}
  prod: {}
components:
  todo-api: {type: service, lang: python, repo: acme/todo-api, uses: [postgres], instances: {dev: {}, prod: {}}}
  todo-web: {type: website, lang: typescript, repo: acme/todo-web, instances: {dev: {}, prod: {}}}
resources:
  backups: {type: bucket}
  postgres:
    type: database
    instances:
      prod:
        backup: {to: backups, schedule: "0 3 * * *", retention: 30d}
"""


@pytest.fixture()
def w(tmp_path, monkeypatch, capsys):
    world = World(tmp_path, monkeypatch, capsys)
    (world.repo / "applications" / "shop" / "system.yaml").write_text(BACKUP_YAML)
    git(world.repo, "commit", "-qam", "backups")
    world.rev = git(world.repo, "rev-parse", "HEAD")
    return world


def names(targets):
    return sorted(t.app for t in targets)


# ---------------- AC-164.1 (#600): the prod promotion waits for the databases and buckets it renders ----------------

def test_a_named_wait_stays_narrow_and_a_full_wait_covers_the_backup_bucket(w):
    """AC-164.1"""
    _, named, _ = envwait.env_targets(w.repo, None, w.rev, "prod", ["todo-api"])
    _, full, _ = envwait.env_targets(w.repo, None, w.rev, "prod", [])
    assert names(named) == ["todo-api-prod"]                          # spec 143: named components limit the wait
    assert {"addon-backups-prod", "addon-postgres-prod"} <= set(names(full))

def test_the_prod_promotion_waits_for_the_whole_environment():
    """AC-164.1"""
    from pathlib import Path
    text = (Path(__file__).parents[2] / "plugins" / "instance" / "commands" / "promote.md").read_text()
    assert "`cplat system wait --env prod --refresh`" in text and "<component…> --refresh`" not in text


# ---------------- AC-164.2 (#599): a recipe that takes arguments passes them ----------------

def test_the_gitops_pin_recipe_passes_its_arguments():
    """AC-164.2: devbox 0.19 runs a script without appending the arguments, so the recipe passes "$@" itself."""
    from pathlib import Path
    scripts = json.loads((Path(__file__).parents[2] / "templates" / "gitops-app" / "devbox.json").read_text())["shell"]["scripts"]
    assert scripts["pin"].endswith('"$@"')


# ---------------- AC-164.3 (#598): staging tests the release's build when main adds only its bookkeeping ----------------

from test_gitops import composed, gh, gitops_repo, pin  # noqa: E402,F401  (fixtures)

BASE = "d" * 40


def test_staging_takes_the_release_build_when_main_adds_only_release_bookkeeping(gitops_repo, gh):
    """AC-164.3"""
    import promote
    gh.compare["acme/todo-api"] = {"status": "ahead", "base": BASE,
                                   "titles": ["chore(release): v1.3.1 changelog and next development version"]}
    gh.image_tags["todo-api"] |= {"sha-" + BASE[:7], "sha-" + BASE}
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "--to", "staging", "--repo-dir", str(gitops_repo)])
    assert pin(gitops_repo, "staging", "todo-api") == "sha-" + BASE


def test_staging_takes_main_when_a_change_follows_the_release(gitops_repo, gh):
    """AC-164.3"""
    import promote
    from test_gitops import SHA
    gh.compare["acme/todo-api"] = {"status": "ahead", "base": BASE,
                                   "titles": ["chore(release): v1.3.1 changelog and next development version", "fix: a bug"]}
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "--to", "staging", "--repo-dir", str(gitops_repo)])
    assert pin(gitops_repo, "staging", "todo-api") == "sha-" + SHA[:7]


def test_an_explicit_sha_is_pinned_as_given(gitops_repo, gh):
    """AC-164.3"""
    import promote
    gh.compare["acme/todo-api"] = {"status": "ahead", "base": BASE, "titles": ["chore(release): v1.3.1 changelog"]}
    gh.image_tags["todo-api"] |= {"sha-" + "e" * 7, "sha-" + "e" * 40}
    composed(gitops_repo, "todo-api")
    promote.main(["todo-api", "--to", "staging", "--sha", "e" * 40, "--repo-dir", str(gitops_repo)])
    assert pin(gitops_repo, "staging", "todo-api") == "sha-" + "e" * 40


# ---------------- AC-164.4 (#596): a test change the user asked for carries its approval ----------------

def test_the_system_ship_records_a_user_requested_test_change_as_the_approval():
    """AC-164.4"""
    from pathlib import Path
    text = (Path(__file__).parents[2] / "plugins" / "system" / "commands" / "ship.md").read_text()
    step = text[text.index("When the user's answer changes a repo's acceptance test"):]
    assert "cplat spec test-diff $RED --approve" in step.split("\n")[0] and "--reason '<the user's words>'" in step.split("\n")[0]
