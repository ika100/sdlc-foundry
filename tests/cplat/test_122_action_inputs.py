"""Spec 122, AC-122.18: what flows from a console request into a command is checked, so a value is never an option or a second command."""
import pytest

from console import actions

OBJ = {"type": "spec", "repo": "acme/shop-api", "spec": "012-checkout", "component": "shop-api", "version": "1.4.0", "issue": 57}


@pytest.mark.parametrize("repo", ["--upload-pack=x/y", "acme/../etc", "acme", "acme/shop api", "-acme/x"])
def test_a_repo_that_is_not_an_owner_name_slug_is_refused(repo):
    with pytest.raises(ValueError):
        actions.command_for("clone", {**OBJ, "repo": repo}, {})


@pytest.mark.parametrize("kind,obj,args", [
    ("promote", OBJ, {"to": "prod --force"}),
    ("promote", {**OBJ, "version": "1.4.0; rm -rf /"}, {"to": "prod"}),
    ("more-budget", OBJ, {"limit": "cost", "value": "10 --x"}),
    ("more-budget", OBJ, {"limit": "everything", "value": "10"}),
    ("approve-ship", OBJ, {"budget": "lots"}),
    ("fix", {**OBJ, "issue": "57 && echo"}, {}),
    ("approve", {**OBJ, "spec": "../x"}, {}),
    ("model", OBJ, {"command": "rm -rf ~"}),
    ("model", OBJ, {"command": "/component:fix something else"}),
    ("amend", OBJ, {"text": "x" * 3000}),
])
def test_values_that_do_not_fit_their_pattern_are_refused(kind, obj, args):
    with pytest.raises(ValueError):
        actions.command_for(kind, obj, args)


def test_free_text_becomes_one_line_and_model_commands_pass():
    argv, _, _ = actions.command_for("amend", OBJ, {"text": "first line\nsecond   line"})
    assert "first line second line" in argv[3]
    argv, _, _ = actions.command_for("model", OBJ, {"command": "/component:add shop-api --provides shop-api-rest"})
    assert argv[3] == "/component:add shop-api --provides shop-api-rest"
