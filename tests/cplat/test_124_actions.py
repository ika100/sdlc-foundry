"""Spec 124 acceptance tests: `cplat system autonomy undo` and `approve`, and the dev rollback of `cplat instance promote`
(AC-124.15, AC-124.16, AC-124.17).

Contract: design.md "`cplat system autonomy …`" (undo, approve) and "The rollback of AC-124.15". The world is the gitops-app checkout of
test_124_command; `autonomy_actions.gh` and `autonomy_actions.pr_wait` are replaced (see autonomy_support's header)."""
import json
import re

import pytest
import yaml

import cplat
import gitops
import promote
from autonomy_support import APP, AutoStore, ago, audit_event, declared_system, engines, iso, now, run_record, store  # noqa: F401
from system_fixtures import files, git
from test_124_command import cmd, recorded, world  # noqa: F401  (world is a fixture)
from test_commands_114 import pin, promote_repo, run  # noqa: F401  (promote_repo is a fixture)

PREV = "sha-" + "a" * 40
NEW = "sha-" + "b" * 40


class ActGh:
    """Replaces `autonomy_actions.gh`."""

    def __init__(self):
        self.calls, self.pr_state, self.pr_title = [], "OPEN", "Fix the rounding of the cart total"
        self.review_refused = False

    def __call__(self, args):
        args = [str(a) for a in args]
        self.calls.append(args)
        if args[:2] == ["api", "user"]:
            return "eike\n"
        if args[:2] == ["pr", "view"]:
            return json.dumps({"id": "PR_kwDOabc", "number": int(args[2]), "state": self.pr_state, "title": self.pr_title,
                               "url": f"https://github.com/acme/shop-api/pull/{args[2]}"})
        if "graphql" in args and "revertPullRequest" in " ".join(args):
            return json.dumps({"data": {"revertPullRequest": {"revertPullRequest": {"number": 90, "url": "https://github.com/acme/shop-api/pull/90"}}}})
        return ""

    def has(self, *words):
        return [c for c in self.calls if all(w in " ".join(c) for w in words)]


@pytest.fixture()
def acts(world, monkeypatch, store):
    g = ActGh()
    waits = []
    world.acts, world.waits, world.store = g, waits, store
    try:
        import autonomy_actions
        monkeypatch.setattr(autonomy_actions, "gh", g)
        monkeypatch.setattr(autonomy_actions, "pr_wait", lambda number, repo: waits.append((number, repo)) or 0)
    except ImportError:
        pass
    promoted = []
    monkeypatch.setattr(promote, "main", lambda argv: promoted.append(list(argv)) or 0)
    world.promoted = promoted
    return world


def event(kind="merge", env="dev", hours=3, **kw):
    ev = audit_event(kind, env=env, at=ago(hours=hours), **kw)
    return ev


# ---------------- AC-124.16: undo ----------------

def test_undoing_a_merge_reverts_it_with_a_revert_pull_request_ac_124_16(acts, capsys):  # AC-124.16
    """AC-124.16: undoing a merge reverts it with a revert pull request."""
    ev = event("merge")
    acts.store.add_event(ev)
    rc, out, err = cmd(acts, "undo", ev["event_id"], capsys=capsys)
    assert rc == 0, err
    [g] = acts.acts.has("revertPullRequest")
    joined = " ".join(g)
    assert "PR_kwDOabc" in joined and f"Revert \"{acts.acts.pr_title}\"" in joined and f"Undo of {ev['event_id']} by eike (spec 124)." in joined
    assert "https://github.com/acme/shop-api/pull/90" in out


def test_the_undo_is_audited_and_the_action_stays_as_it_was_ac_124_16(acts, capsys):  # AC-124.16
    """AC-124.16: the undo is audited and the action stays as it was."""
    ev = event("merge")
    acts.store.add_event(ev)
    before = dict(acts.store.files)
    assert cmd(acts, "undo", ev["event_id"]) == 0
    new = {k: v for k, v in acts.store.files.items() if k not in before}
    [(path, text)] = new.items()
    undo = json.loads(text)
    assert path.startswith("audit/") and undo["kind"] == "undo" and undo["undoes"] == ev["event_id"] and undo["actor"]["name"] == "eike"
    assert all(acts.store.files[k] == v for k, v in before.items()), "the undone event is not rewritten"


def test_undoing_a_rollback_pins_the_previous_version_back_through_the_promote_command_ac_124_16(acts):  # AC-124.16
    """AC-124.16: undoing a rollback pins the previous version back through the promote command."""
    ev = event("rollback", obj={"type": "instance", "version": PREV, "previous": NEW, "number": None, "url": None}, component_="api")
    acts.store.add_event(ev)
    assert cmd(acts, "undo", ev["event_id"]) == 0
    [argv] = acts.promoted
    assert "api" in argv and argv[argv.index("--to") + 1] == "dev" and argv[argv.index("--version") + 1] == NEW and "--pr" in argv


def test_undoing_a_promotion_in_prod_uses_version_and_in_staging_sha_ac_124_16(acts):  # AC-124.16
    """AC-124.16: undoing a promotion in prod uses version and in staging sha."""
    prod = event("promotion", env="prod", obj={"type": "instance", "version": "1.4.0", "previous": "1.3.0", "number": None, "url": None}, component_="api")
    acts.store.add_event(prod)
    assert cmd(acts, "undo", prod["event_id"]) == 0
    [argv] = acts.promoted
    assert argv[argv.index("--to") + 1] == "prod" and argv[argv.index("--version") + 1] == "1.3.0"
    acts.promoted.clear()
    stg = event("promotion", env="staging", eid="20261026T060000Z-ai-ops-bbbbbbbb",
                obj={"type": "instance", "version": NEW, "previous": "sha-" + "c" * 40, "number": None, "url": None}, component_="api")
    acts.store.add_event(stg)
    assert cmd(acts, "undo", stg["event_id"]) == 0
    [argv] = acts.promoted
    assert argv[argv.index("--to") + 1] == "staging" and "--sha" in argv and ("c" * 40) in argv[argv.index("--sha") + 1]


def test_undoing_a_dismissal_reopens_the_issue_with_a_comment_ac_124_16(acts):  # AC-124.16
    """AC-124.16: undoing a dismissal reopens the issue with a comment."""
    ev = event("dismissal", obj={"type": "issue", "repo": "acme/shop-api", "number": 57, "url": "https://github.com/acme/shop-api/issues/57"})
    acts.store.add_event(ev)
    assert cmd(acts, "undo", ev["event_id"]) == 0
    [reopen] = acts.acts.has("issue", "reopen")
    joined = " ".join(reopen)
    assert "57" in reopen and "acme/shop-api" in reopen and f"Reopened: undo of {ev['event_id']} by eike." in joined


def test_an_undo_after_the_window_is_refused_with_the_reason_ac_124_16(acts, capsys):  # AC-124.16
    """AC-124.16: an undo after the window is refused with the reason."""
    ev = event("merge", hours=25)
    acts.store.add_event(ev)
    before = dict(acts.store.files)
    rc, _, err = cmd(acts, "undo", ev["event_id"], capsys=capsys)
    assert rc == 1 and "the undo window of 24h has passed" in err
    assert not acts.acts.has("revertPullRequest") and acts.store.files == before and acts.promoted == []


def test_an_undo_of_something_a_person_did_or_that_was_undone_is_refused_ac_124_16(acts, capsys):  # AC-124.16
    """AC-124.16: an undo of something a person did or that was undone is refused."""
    person = event("merge", name="eike", eid="20261026T060000Z-cplat-aaaaaaaa")
    acts.store.add_event(person)
    rc, _, err = cmd(acts, "undo", person["event_id"], capsys=capsys)
    assert rc == 1 and "not done on its own" in err
    ev = event("merge")
    acts.store.add_event(ev)
    acts.store.add_event(audit_event("undo", name="eike", env="dev", at=ago(hours=1), undoes=ev["event_id"], eid="20261026T080000Z-cplat-bbbbbbbb"))
    rc, _, err = cmd(acts, "undo", ev["event_id"], capsys=capsys)
    assert rc == 1 and "already undone by eike" in err


def test_an_unknown_event_is_refused_ac_124_16(acts, capsys):  # AC-124.16
    """AC-124.16: an unknown event is refused."""
    rc, _, err = cmd(acts, "undo", "20261026T000000Z-ai-ops-ffffffff", capsys=capsys)
    assert rc == 1 and "20261026T000000Z-ai-ops-ffffffff" in err


def test_undo_dry_run_json_lists_what_it_would_do_and_changes_nothing_ac_124_16(acts, capsys):  # AC-124.16
    """AC-124.16: undo dry run json lists what it would do and changes nothing."""
    ev = event("merge")
    acts.store.add_event(ev)
    before = dict(acts.store.files)
    rc, out, err = cmd(acts, "undo", ev["event_id"], "--dry-run", "--json", capsys=capsys)
    assert rc == 0, err
    assert json.loads(out)["will_do"] and not acts.acts.has("revertPullRequest") and acts.store.files == before


# ---------------- AC-124.17: approve ----------------

def fix_run(pr=88, **kw):
    return run_record(started=ago(minutes=30), pr={"number": pr, "url": f"https://github.com/acme/shop-api/pull/{pr}"}, **kw)


def test_approve_reviews_then_merges_when_every_check_passed_ac_124_17(acts, capsys):  # AC-124.17
    """AC-124.17: approve reviews then merges when every check passed."""
    acts.store.add_run(fix_run())
    rc, out, err = cmd(acts, "approve", "acme/shop-api#88", capsys=capsys)
    assert rc == 0, err
    [review] = acts.acts.has("pr", "review")
    assert review[:3] == ["pr", "review", "88"] and "-R" in review and "acme/shop-api" in review and "--approve" in review
    assert "Approved by eike in the review decision (spec 124)." in " ".join(review)
    assert acts.waits == [(88, "acme/shop-api")], "cplat pr wait <n> -R <repo> --merge"
    order = [c for c in acts.acts.calls if c[:2] == ["pr", "review"]]
    assert order, "review comes before the merge wait"


def test_approve_is_audited_ac_124_17(acts):  # AC-124.17
    """AC-124.17: approve is audited."""
    acts.store.add_run(fix_run())
    assert cmd(acts, "approve", "acme/shop-api#88") == 0
    [ev] = [json.loads(t) for k, t in acts.store.files.items() if k.startswith("audit/")]
    assert ev["kind"] == "approve" and ev["actor"]["name"] == "eike" and ev["object"]["number"] == 88 and ev["object"]["repo"] == "acme/shop-api"


def test_approve_needs_an_engine_fix_run_for_that_pull_request_ac_124_17(acts, capsys):  # AC-124.17
    """AC-124.17: approve needs an engine fix run for that pull request."""
    acts.store.add_run(fix_run(pr=88))
    rc, _, err = cmd(acts, "approve", "acme/shop-api#99", capsys=capsys)
    assert rc == 1 and "99" in err and not acts.acts.has("pr", "review") and acts.waits == []


def test_approve_refuses_a_pull_request_that_is_not_open_ac_124_17(acts, capsys):  # AC-124.17
    """AC-124.17: approve refuses a pull request that is not open."""
    acts.store.add_run(fix_run())
    acts.acts.pr_state = "MERGED"
    rc, _, err = cmd(acts, "approve", "acme/shop-api#88", capsys=capsys)
    assert rc == 1 and not acts.acts.has("pr", "review") and acts.waits == []


def test_approve_dry_run_changes_nothing_ac_124_17(acts, capsys):  # AC-124.17
    """AC-124.17: approve dry run changes nothing."""
    acts.store.add_run(fix_run())
    rc, out, err = cmd(acts, "approve", "acme/shop-api#88", "--dry-run", "--json", capsys=capsys)
    assert rc == 0, err
    assert json.loads(out)["will_do"] and not acts.acts.has("pr", "review") and acts.waits == []


# ---------------- AC-124.15: the dev rollback ----------------

def pin_dev(repo, tag, msg):
    k = repo / APP / "overlays" / "dev" / "api" / "kustomization.yaml"
    k.write_text(yaml.safe_dump({"resources": ["deployment.yaml"], "images": [{"name": "ghcr.io/acme/api", "newTag": tag}]}, sort_keys=False))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


@pytest.fixture()
def dev_history(promote_repo):
    pin_dev(promote_repo, PREV, "pin dev a")
    pin_dev(promote_repo, "1.3.0", "pin dev release")
    pin_dev(promote_repo, NEW, "pin dev b")
    return promote_repo


def test_dev_can_be_pinned_back_to_a_tag_it_ran_before_ac_124_15(dev_history, capsys):  # AC-124.15
    """AC-124.15: dev can be pinned back to a tag it ran before."""
    rc, out, err = run("instance", "promote", "api", "--to", "dev", "--version", PREV, "--repo-dir", dev_history, capsys=capsys)
    assert rc == 0, err
    assert pin(dev_history, "dev", "api") == PREV
    assert pin(dev_history, "staging", "api").startswith("sha-"), "only dev is touched"


def test_a_rollback_opens_one_pin_pull_request_with_the_word_rollback_ac_124_15(dev_history, monkeypatch):  # AC-124.15
    """AC-124.15: a rollback opens one pin pull request with the word rollback."""
    seen = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: seen.append((branch, title, body)) or "https://github.com/acme/shop-gitops/pull/5")
    assert run("instance", "promote", "api", "--to", "dev", "--version", PREV, "--pr", "--repo-dir", dev_history) == 0
    [(branch, title, body)] = seen
    assert "rollback" in title.lower() and PREV in (title + body)


def test_a_release_tag_dev_ran_before_is_accepted_ac_124_15(dev_history):  # AC-124.15
    """AC-124.15: a release tag dev ran before is accepted."""
    assert run("instance", "promote", "api", "--to", "dev", "--version", "1.3.0", "--repo-dir", dev_history) == 0
    assert pin(dev_history, "dev", "api") == "1.3.0"


def test_a_tag_dev_never_ran_is_refused_with_the_documented_message_ac_124_15(dev_history, capsys):  # AC-124.15
    """AC-124.15: a tag dev never ran is refused with the documented message."""
    other = "sha-" + "9" * 40
    before = files(dev_history)
    rc, _, err = run("instance", "promote", "api", "--to", "dev", "--version", other, "--repo-dir", dev_history, capsys=capsys)
    assert rc == 1
    assert f"{other} is not a version dev ran before; dev follows main (a rollback pins only a previous dev version)" in err
    assert files(dev_history) == before


def test_to_dev_without_a_version_keeps_todays_error_ac_124_15(dev_history, capsys):  # AC-124.15
    """AC-124.15: to dev without a version keeps todays error."""
    rc, _, err = run("instance", "promote", "api", "--to", "dev", "--repo-dir", dev_history, capsys=capsys)
    assert rc == 1 and "dev follows main" in err


def test_a_dev_rollback_is_for_one_component_not_all_ac_124_15(dev_history, capsys):  # AC-124.15
    """AC-124.15: a dev rollback is for one component not all."""
    rc, _, err = run("instance", "promote", "--all", "--to", "dev", "--version", PREV, "--repo-dir", dev_history, capsys=capsys)
    assert rc == 1


def test_the_dry_run_names_the_previous_and_the_new_tag_ac_124_15(dev_history, capsys):  # AC-124.15
    """AC-124.15: the dry run names the previous and the new tag."""
    before = files(dev_history)
    rc, out, err = run("instance", "promote", "api", "--to", "dev", "--version", PREV, "--dry-run", "--json", "--repo-dir", dev_history, capsys=capsys)
    assert rc == 0, err
    assert PREV in out and NEW in out
    assert files(dev_history) == before
