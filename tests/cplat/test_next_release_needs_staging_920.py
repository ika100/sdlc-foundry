"""#920: `cplat next` offers a deployable component's release only when `cplat component release target` can tag it: its staging
instance exists and runs a commit that is not released yet. Without a staging instance the step is the first (manual) promotion
to staging, run in the gitops repo; a library still releases from main."""
import pytest

from support_193 import BuildWorld, by_label, labels


class _Inst:
    def __init__(self, tag):
        self.tag = tag


def deployable(tmp_path, monkeypatch, promotion, *, staging=None, tagged_staging=False):
    """A service repo with one change since the start (no tag); `staging` is None (no staging instance), "head" or "old"."""
    import staging as staging_mod
    w = BuildWorld(tmp_path, monkeypatch, shape="service-python")
    w.queue()
    w.commit("a.txt", "a", "feat: create tasks (#4)")
    old = w.read_head()
    if tagged_staging:
        w.tag("v0.1.0", "2026-11-01T09:00:00")
    w.commit("b.txt", "b", "feat: list tasks (#5)")
    head = w.read_head()
    runs = {"head": head, "old": old}.get(staging or "")

    class Model:
        def staging_promotion(self, component):
            return promotion

        def instance(self, name, env):
            return _Inst("staging-tag") if env == "staging" and runs else None

    class Comp:
        name = "shop-api"

    monkeypatch.setattr(staging_mod, "_find", lambda repo, apps, svc: ("o/gitops", "applications/shop", Comp(), Model(), "o/n"))
    monkeypatch.setattr(staging_mod, "resolve", lambda slug, tag, repo=None: runs if tag == "staging-tag" else None)
    return w


@pytest.mark.parametrize("promotion", ["after-dev-smoke", "manual"])
def test_no_staging_instance_offers_the_first_promotion_not_the_release(tmp_path, monkeypatch, capsys, promotion):
    w = deployable(tmp_path, monkeypatch, promotion, staging=None)
    doc = w.doc(capsys)
    deploy = doc["build"]["deploy"]
    assert deploy["step"] == "staging" and deploy["first_staging"] is True and deploy["app"] == "o/gitops"
    assert not any(i.startswith("release:") for i in doc["waiting"]["items"])
    assert not any(q["header"] == "Release" for q in doc["questions"])
    q = doc["questions"][0]
    assert q["header"] == "Staging" and labels(q)[0] == "Promote to Staging"
    assert q["options"][0]["recommended"] is True and q["options"][0]["steps"] == ["/instance:promote shop-api --to staging"]
    assert "o/gitops" in q["question"] and "prod" not in q["question"]


def test_the_first_promotion_item_runs_in_the_gitops_repo(tmp_path, monkeypatch, capsys):
    w = deployable(tmp_path, monkeypatch, "after-dev-smoke", staging=None)
    import nextstate
    doc = w.doc(capsys)
    item = next(i for i in nextstate.collect(w.repo)["items"] if i["kind"] == "promote")
    assert item["cwd_repo"] == "o/gitops"
    assert item["consequence"]["env"] == "staging" and item["consequence"]["first"] is True
    assert "/instance:promote shop-api --to staging in o/gitops" in " ".join(doc["screen"].split())


def test_after_dev_smoke_staging_on_an_unreleased_commit_offers_the_release(tmp_path, monkeypatch, capsys):
    w = deployable(tmp_path, monkeypatch, "after-dev-smoke", staging="old")
    doc = w.doc(capsys)
    assert doc["build"]["deploy"]["step"] == "release" and doc["build"]["deploy"]["first_staging"] is False
    q = doc["questions"][0]
    assert q["header"] == "Release" and by_label(q, "Release now")["steps"] == ["/component:release"]


def test_after_dev_smoke_staging_on_a_released_commit_offers_no_release(tmp_path, monkeypatch, capsys):
    w = deployable(tmp_path, monkeypatch, "after-dev-smoke", staging="old", tagged_staging=True)
    doc = w.doc(capsys)
    assert doc["build"]["deploy"]["step"] != "release"
    assert not any(q["header"] == "Release" for q in doc["questions"])


def test_a_library_still_releases_from_main(tmp_path, monkeypatch, capsys):
    w = BuildWorld(tmp_path, monkeypatch, shape="library-python")
    w.queue()
    w.commit("a.txt", "a", "feat: parse tasks (#4)")
    w.read_head()
    q = next(q for q in w.doc(capsys)["questions"] if q["header"] == "Release")
    assert by_label(q, "Release now")["steps"] == ["/component:release"]


def test_next_reads_the_release_targets_own_check(tmp_path, monkeypatch, capsys):
    """The already-released check is `comprelease.released_as`, the one `release target` refuses with."""
    import comprelease
    w = deployable(tmp_path, monkeypatch, "after-dev-smoke", staging="old")
    monkeypatch.setattr(comprelease, "released_as", lambda repo, commit: "v9.9.9")
    assert w.doc(capsys)["build"]["deploy"]["step"] != "release"
