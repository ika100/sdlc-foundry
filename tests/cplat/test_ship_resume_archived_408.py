"""#408: `/component:ship`'s finish step archives an escalated run too. Resuming the spec then started a new run at phase
`pr` without the PR and merge commit it already had, so deploy refused and `ship pr` would open a duplicate PR. A start of
the same spec now resumes the archived escalated run."""
import json

import ship
from test_ship import SHA, repo  # noqa: F401  (pytest fixture)


def _escalate_and_finish(repo):  # noqa: F811
    ship.start(repo, "7", True)
    st = ship.load_state(repo)
    st.update({"phase": "deploy", "pr": "https://github.com/acme/shop-api/pull/3", "merge_sha": SHA})
    ship.save_state(repo, st)
    ship.escalate(repo, "pin-dev failed on main: GITOPS_TOKEN gets HTTP 403", cause="environment")
    return ship.finish(repo)


def test_a_start_after_finish_resumes_the_escalated_run_with_its_pr(repo):  # noqa: F811
    archived = _escalate_and_finish(repo)
    assert not ship.state_path(repo).exists()
    st = ship.start(repo, "7", True)
    assert st["phase"] == "deploy" and st["merge_sha"] == SHA and st["pr"].endswith("/pull/3")
    assert not st.get("escalated")
    assert not archived.exists() and ship.state_path(repo).is_file()


def test_a_run_that_finished_done_is_not_revived(repo):  # noqa: F811
    ship.start(repo, "7", True)
    st = ship.load_state(repo)
    st["phase"] = "done"
    ship.save_state(repo, st)
    ship.finish(repo)
    assert ship.revive_escalated(repo, "007-price-alerts") is None


def test_only_the_newest_archive_counts(repo):  # noqa: F811
    old = _escalate_and_finish(repo)
    newer = old.with_name(old.name.replace(old.stem.rsplit("-", 1)[-1], "29991231235959"))
    newer.write_text(json.dumps({**json.loads(old.read_text()), "phase": "done", "escalated": None}))
    assert ship.revive_escalated(repo, json.loads(old.read_text())["spec"]) is None
