"""#946: in a component repo `cplat next` offered the prod promotion as "<component> 0.1.0 is verified in staging" and recommended
it, although no staging smoke had run (staging was not exposed). The prod question now says "verified" only with a green
staging smoke record of the release, and without one it recommends holding the promotion back."""
import pytest

import nextbuild
import runs
import status
from support_193 import BuildWorld, labels
from test_next_backup_before_prod_861 import MISSING, promote_item


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = BuildWorld(tmp_path, monkeypatch)
    w.queue()
    return w


def prod_question(world, capsys, consequence):
    world.dispatch_item(promote_item({"env": "prod", "missing_backups": [], **consequence}))
    return next(q for q in world.doc(capsys)["questions"] if q["header"] == "Prod")


def test_without_a_staging_smoke_the_question_holds_prod_back_946(world, capsys):
    q = prod_question(world, capsys, {"staging_smoke": "none"})
    assert labels(q) == ["Hold it back", "Promote to Prod anyway", "Show details"]
    assert q["options"][0]["recommended"] is True and not q["options"][0]["steps"]
    assert q["options"][1]["steps"] == ["/instance:promote web --to prod --version v1.2.0"], "promoting stays a choice"
    assert "verified" not in q["question"] and "no green staging smoke result" in q["question"]


def test_a_red_staging_smoke_is_named_946(world, capsys):
    q = prod_question(world, capsys, {"staging_smoke": "failed"})
    assert q["options"][0]["label"] == "Hold it back" and "failed its staging smoke (failed)" in q["question"]


@pytest.mark.parametrize("smoke", ["passed", "passed-on-retry", None])
def test_a_green_or_unknown_smoke_keeps_the_promotion_recommended_946(world, capsys, smoke):
    q = prod_question(world, capsys, {"staging_smoke": smoke})
    assert labels(q) == ["Promote to Prod", "Show details", "Not now"] and "is verified in staging" in q["question"]


def test_a_missing_backup_still_comes_first_946(world, capsys):
    world.dispatch_item(promote_item({"env": "prod", "missing_backups": MISSING, "staging_smoke": "none"}))
    q = next(q for q in world.doc(capsys)["questions"] if q["header"] == "Prod")
    assert labels(q) == ["Set the backup first", "Hold it back", "Promote to Prod anyway", "Show details"]
    assert "verified" not in q["question"] and "has no backup" in q["question"]


def test_the_component_prod_item_carries_the_staging_smoke_946(monkeypatch):
    deploy = {"step": "prod", "component": "api", "version": "v0.1.0", "app": "o/gitops"}
    monkeypatch.setattr(runs, "configured_repo", lambda: None)
    assert nextbuild.promote_item("o/api", deploy, "t")["consequence"]["staging_smoke"] is None, "no run store: unknown"
    monkeypatch.setattr(runs, "configured_repo", lambda: "o/runs")
    seen = []
    monkeypatch.setattr(status, "_smoke", lambda repo, tag, env: seen.append((repo, tag, env)))
    assert nextbuild.promote_item("o/api", deploy, "t")["consequence"]["staging_smoke"] == "none"
    assert seen == [("o/api", "v0.1.0", "staging")]
    monkeypatch.setattr(status, "_smoke", lambda repo, tag, env: {"outcome": "passed"})
    assert nextbuild.promote_item("o/api", deploy, "t")["consequence"]["staging_smoke"] == "passed"
    staging = nextbuild.promote_item("o/api", {**deploy, "step": "staging", "version": "abc1234"}, "t")
    assert "staging_smoke" not in staging["consequence"], "only the prod step needs the staging evidence"
