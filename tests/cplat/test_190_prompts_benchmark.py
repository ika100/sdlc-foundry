"""Spec 190 acceptance tests for the prompt and benchmark criteria: the approval summaries (AC-190.5), the product-manager rule and
the `spec-environments` benchmark case with its `environments_kept` result check (AC-190.6), the `/instance:promote` command text and
the promotion guide (AC-190.7).

Prompts and guides are tested by structure, as `docs/rules/README.md` asks: the command, flag and field names the text must carry
(each one is code or a reader's handle, never a sentence of prose), never a sentence of wording. The benchmark check runs on a tmp
clone with `runs_bench.run` replaced, as in the explore-stop tests."""
import json
import re

import pytest

import core
import runs
import runs_bench

ROOT = core.PLATFORM_ROOT
PLUGINS = ROOT / "plugins"
GUIDE = ROOT / "site" / "src" / "content" / "docs" / "scenarios" / "promote-safely.md"
TASKS = ROOT / "scripts" / "cplat" / "benchmark" / "tasks.json"
HEAD = "a" * 40


def text(path):
    return path.read_text()


def paragraphs(path):
    return [p for p in re.split(r"\n\s*\n", text(path))]


# ---------------- AC-190.5: the approval summaries ----------------

@pytest.mark.parametrize("plugin", ["component", "system"])
def test_the_approval_summary_shows_the_limit_through_cplat_spec_show(plugin):  # AC-190.5
    body = text(PLUGINS / plugin / "commands" / "spec.md")
    assert "cplat spec show" in body and "Environment limit" in body


# ---------------- AC-190.6: the product-manager rule ----------------

def test_the_product_manager_names_the_limit_and_writes_the_field():  # AC-190.6
    body = text(PLUGINS / "svc" / "agents" / "product-manager.md")
    assert "limits to" in body
    assert "environments:" in body


def test_the_spec_format_documents_the_field():  # AC-190.6
    body = text(PLUGINS / "svc" / "skills" / "spec-format" / "references" / "spec.md")
    assert "environments:" in body


# ---------------- AC-190.6: the benchmark case ----------------

def test_the_task_asks_for_a_change_in_every_environment():  # AC-190.6
    task = json.loads(text(TASKS))["workflows"]["spec-environments"]
    assert task["prompt"].startswith("/component:spec ")
    for env in ("dev", "staging", "prod"):
        assert env in task["prompt"], env
    assert task["task_version"] == 1 and task["max_runs"] == 2 and task["max_minutes"] == 20 and task["plugins"] == ["component"]
    assert runs_bench.EXPECTED["spec-environments"] == "spec"


def test_the_usage_line_names_the_workflow():  # AC-190.6
    assert "spec-environments" in (runs.__doc__ or "")


BENCH_SPEC = """---
spec_id: 003-guest-access
title: Guest access
status: draft
priority: P1
{field}---

# 003 — Guest access

## Problem

Guests need access in dev, staging and prod, which limits to nobody.

## Acceptance criteria

- **AC-003.1** Given a guest, when they open the app, then they see the list.

## Non-goals

- None

## Assumptions

{assumptions}

## Open questions

{questions}

## Changelog

- 2026-11-15 created
"""


@pytest.fixture()
def clone(tmp_path, monkeypatch):
    """A clone whose git answers `diff --diff-filter=A` with the spec files in `added`."""
    state = {"added": [], "calls": []}

    def run(cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        state["calls"].append(cmd)
        if cmd[:2] == ["git", "diff"]:
            return 0, "".join(f"{p}\n" for p in state["added"]), ""
        return 0, "", ""
    monkeypatch.setattr(runs_bench, "run", run)
    state["clone"] = tmp_path

    def add(field="", assumptions="- None", questions="- None", name="003-guest-access"):
        d = tmp_path / "docs" / "specs" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.md").write_text(BENCH_SPEC.format(field=field, assumptions=assumptions, questions=questions))
        state["added"].append(f"docs/specs/{name}/spec.md")
    state["add"] = add
    return state


def check(state):
    return runs_bench.environments_kept({"head": HEAD}, state["clone"])


def test_no_spec_written_is_reported(clone):  # AC-190.6
    assert check(clone) == "no spec written"
    (diff,) = [c for c in clone["calls"] if c[:2] == ["git", "diff"]]
    assert HEAD in diff and "--diff-filter=A" in diff and diff[-1] == "docs/specs"


def test_a_spec_for_every_environment_passes(clone):  # AC-190.6
    clone["add"]()
    assert check(clone) is None
    clone["add"](field="environments: [dev, staging, prod]\n", name="004-other")
    assert check(clone) is None


def test_a_spec_that_limits_an_environment_fails_naming_the_spec_and_the_set(clone):  # AC-190.6
    clone["add"](field="environments: [dev]\n")
    why = check(clone)
    assert why == "003-guest-access limits environments: dev"


def test_a_suggested_answer_that_limits_fails_with_the_bullet(clone):  # AC-190.6
    clone["add"](questions="- May guests use the app? (suggested: yes, limits to dev; alternatives: no)")
    why = check(clone)
    assert why.startswith("003-guest-access suggests an environment limit: - ") or why.startswith("003-guest-access suggests an environment limit: ")
    assert "limits to dev" in why and len(why) <= 200


def test_an_assumption_that_limits_fails(clone):  # AC-190.6
    clone["add"](assumptions="- **A1** Anonymous use is limits to dev for now.")
    assert "suggests an environment limit" in check(clone)


def test_the_bullet_is_cut_at_120_characters(clone):  # AC-190.6
    clone["add"](questions="- " + "x" * 300 + " limits to dev")
    clone["add"](questions="- limits to dev " + "y" * 300, name="004-other")
    for why in (check(clone),):
        assert "suggests an environment limit" in why
        assert len(why.split(": ", 1)[1]) <= 130


def test_the_word_outside_questions_and_assumptions_is_not_a_suggestion(clone):  # AC-190.6
    clone["add"]()          # the Problem section of the fixture says "which limits to nobody"
    assert check(clone) is None


def test_result_hands_the_spec_workflow_to_the_check(clone):  # AC-190.6
    clone["add"](field="environments: [prod]\n")
    why = runs_bench.result("spec-environments", "acme/sample", {"head": HEAD, "newest_pr": 0}, clone["clone"])
    assert why == "003-guest-access limits environments: prod"


# ---------------- AC-190.7: /instance:promote and the guide ----------------

PROMOTE = PLUGINS / "instance" / "commands" / "promote.md"


@pytest.mark.parametrize("doc", [PROMOTE, GUIDE])
def test_the_docs_state_rule_refusal_dry_run_and_override(doc):  # AC-190.7
    body = text(doc)
    assert "environments:" in body                      # the rule: the field of the spec
    assert "environment limit" in body                  # the refusal line
    assert "REFUSED:" in body and "--dry-run" in body   # the dry-run output
    assert "--accept-environment-limit" in body         # the override


def test_the_override_is_a_hard_rule_of_a_person():  # AC-190.7
    body = text(PROMOTE)
    assert "--accept-environment-limit" in body and "REFUSED:" in body and "**Hard rule:**" in body
    assert any("**Hard rule:**" in line and "--accept-environment-limit" in line for line in body.splitlines()), \
        "the Hard rule sentence names the flag"
