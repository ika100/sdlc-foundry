"""#505: one prod promotion carries the release of several components (`--version api=v1.2.0,web=v0.1.0`), instead of one PR per
component that conflict on system.yaml and the ApplicationSet; the single-component `--version vX.Y.Z` keeps working."""
import pytest

import core
import evidence
import gitops
import promote
from test_gitops import SHA, commit, composed, gh, gitops_repo, matching_registry, pin  # noqa: F401  (fixtures)


@pytest.fixture()
def both_in_staging(gitops_repo, gh, monkeypatch):  # noqa: F811
    gh.git_tags["acme/todo-web"] = ["v0.1.0"]
    gh.image_tags["todo-web"] |= {"0.1.0", "sha-" + SHA}
    gh.image_tags["todo-api"].add("sha-" + SHA)
    matching_registry(monkeypatch, gh)
    monkeypatch.setattr(evidence, "summary", lambda svc, version, staging_tag: evidence.Evidence(service=svc["name"], version=version))
    composed(gitops_repo, "todo-api")
    composed(gitops_repo, "todo-web")
    promote.main(["--all", "--to", "staging", "--repo-dir", str(gitops_repo)])
    commit(gitops_repo, "promote")
    return gitops_repo


def test_one_prod_pr_pins_each_component_to_its_own_version(both_in_staging, monkeypatch):
    opened = []
    monkeypatch.setattr(gitops, "open_pr", lambda repo, branch, title, body: opened.append((branch, title, body)) or "https://x/pull/1")
    assert promote.main(["--to", "prod", "--version", "todo-api=v1.2.0,todo-web=v0.1.0", "--pr", "--repo-dir", str(both_in_staging)]) == 0
    assert (pin(both_in_staging, "prod", "todo-api"), pin(both_in_staging, "prod", "todo-web")) == ("1.2.0", "0.1.0")
    assert len(opened) == 1 and "todo-api todo-web" in opened[0][1]
    assert "- todo-api: `1.2.0`" in opened[0][2] and "- todo-web: `0.1.0`" in opened[0][2]


def test_named_components_without_a_version_take_their_newest_release(both_in_staging):
    promote.main(["todo-api", "todo-web", "--to", "prod", "--version", "todo-web=v0.1.0", "--repo-dir", str(both_in_staging)])
    assert (pin(both_in_staging, "prod", "todo-api"), pin(both_in_staging, "prod", "todo-web")) == ("1.3.0", "0.1.0")


def test_the_single_component_form_still_works(both_in_staging):
    promote.main(["todo-api", "--to", "prod", "--version", "v1.2.0", "--repo-dir", str(both_in_staging)])
    assert pin(both_in_staging, "prod", "todo-api") == "1.2.0"


@pytest.mark.parametrize("argv,msg", [
    (["todo-api", "todo-web", "--version", "v1.2.0"], "release of one component"),
    (["todo-api", "--version", "todo-web=v0.1.0"], "does not include"),
    (["--version", "todo-api=v1.2.0,todo-api=v1.3.0"], "twice"),
    (["--version", "todo-api=,todo-web=v0.1.0"], "is not <component>=vX.Y.Z"),
    (["--version", "todo-api=1.2"], "must look like vX.Y.Z"),
])
def test_bad_version_lists_are_refused(both_in_staging, argv, msg):
    with pytest.raises(core.PlatformError, match=msg) as e:
        promote.main([*argv, "--to", "prod", "--repo-dir", str(both_in_staging)])
    assert e.value.hint or msg != "release of one component"
    assert gitops.rendered_changes(both_in_staging) == []          # refused before anything is written
