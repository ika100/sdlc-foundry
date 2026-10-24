"""Regressions for the update's `lost` list: a `ci` from this platform version, and invalid JSON in a replaced file."""
import json

import gates
import update
from test_update_lost import STEP, OLD_CI, commit, edit_devbox, go, pair, rd  # noqa: F401


def test_a_ci_of_this_version_with_an_extra_gate_is_not_a_replaced_recipe(pair, monkeypatch, capsys):
    repo, base = pair
    edit_devbox(repo, ci=OLD_CI + " && devbox run chart-lint && " + STEP, **{"chart-lint": "helm lint"})
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    assert out["devbox"]["moved_to_ci_extra"] == ["chart-lint"]
    assert not [e for e in out["lost"] if e["entry"] == "scripts ci"] and out["devbox"]["replaced"] == []
    assert rd(repo)["shell"]["scripts"]["ci-extra"] == "devbox run chart-lint"


def test_invalid_json_in_settings_is_listed_as_lost(pair, monkeypatch, capsys):
    repo, base = pair
    (repo / ".claude" / "settings.json").write_text("{ not json")
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    e = [x for x in out["lost"] if x["file"] == ".claude/settings.json"]
    assert len(e) == 1 and e[0]["kind"] == "file" and e[0]["entry"] is None and "git show HEAD~1:.claude/settings.json" in e[0]["where"]


def test_invalid_json_in_devbox_is_listed_as_lost(pair, monkeypatch, capsys):
    repo, base = pair
    (repo / "devbox.json").write_text("{ not json")
    commit(repo)
    out = go(repo, monkeypatch, capsys, base)
    e = [x for x in out["lost"] if x["file"] == "devbox.json"]
    assert len(e) == 1 and e[0]["kind"] == "file" and "git show HEAD~1:devbox.json" in e[0]["where"]
    json.loads((repo / "devbox.json").read_text())
