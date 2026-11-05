"""#423: `platform update --verify` clones the commit an environment runs before its smoke tests. A prod pin `X.Y.Z` is the
image of the git tag `vX.Y.Z`, so the clone must ask for `vX.Y.Z` (it asked for the branch `X.Y.Z`, which does not exist)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import upgradeverify


@pytest.fixture()
def clones(monkeypatch):
    calls: list[list[str]] = []

    def run(cmd, cwd=None, **_):
        calls.append(list(cmd))
        if cmd[:3] == ["gh", "repo", "clone"]:
            Path(cmd[4]).mkdir(parents=True, exist_ok=True)
        return ""

    monkeypatch.setattr(upgradeverify.core, "run", run)
    return calls


def _dir(tmp_path, tag):
    comp = SimpleNamespace(name="api", repo="acme/api")
    return upgradeverify.component_dir(comp, SimpleNamespace(tag=tag), {}, tmp_path)


def test_a_release_pin_clones_its_v_tag(tmp_path, clones):
    _dir(tmp_path, "0.1.0")
    clone = clones[0]
    assert clone[:4] == ["gh", "repo", "clone", "acme/api"]
    assert clone[clone.index("--branch") + 1] == "v0.1.0"


def test_a_sha_pin_fetches_that_commit(tmp_path, clones):
    _dir(tmp_path, "sha-" + "a" * 40)
    assert "--branch" not in clones[0]
    assert clones[1] == ["git", "fetch", "--depth", "1", "origin", "a" * 40]


def test_another_tag_is_cloned_as_it_is(tmp_path, clones):
    _dir(tmp_path, "v2.0.0-rc1")
    assert clones[0][clones[0].index("--branch") + 1] == "v2.0.0-rc1"
