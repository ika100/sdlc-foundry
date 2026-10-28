"""Spec-driven agents (ADR-026, STORY-038): one format reference, tests first, a reviewer, no doc drift."""
import re

import pytest
import yaml

import core

ROOT = core.PLATFORM_ROOT
PLUGINS = ROOT / "plugins"
SKILL = PLUGINS / "svc" / "skills" / "spec-format"
CODE_PLUGINS = ["svc", "web", "svc-java", "svc-go"]


def front(path):
    return yaml.safe_load(path.read_text().split("---", 2)[1])


def test_every_plugin_root_reference_resolves_inside_its_plugin():
    refs = []
    for md in PLUGINS.rglob("*.md"):
        plugin = md.relative_to(PLUGINS).parts[0]
        for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+[\w])", md.read_text()):
            refs.append((md, PLUGINS / plugin / rel))
    assert refs, "expected the agents to reference the spec-format skill"
    missing = [f"{md.relative_to(ROOT)} -> {target.relative_to(ROOT)}" for md, target in refs if not target.exists()]
    assert not missing


def test_the_format_skill_covers_every_artifact():
    meta = front(SKILL / "SKILL.md")
    assert meta["name"] == "spec-format" and len(meta["description"]) < 400
    for ref in ("spec", "design", "plan", "verification", "testing"):
        assert (SKILL / "references" / f"{ref}.md").is_file()


def test_the_documented_plan_example_matches_what_cplat_checks():
    plan = (SKILL / "references" / "plan.md").read_text()
    meta = yaml.safe_load(plan.split("```yaml\n---\n", 1)[1].split("\n---\n```", 1)[0])
    assert {"spec_id", "shape", "spec_hash", "tasks"} <= set(meta)
    for task in meta["tasks"]:
        assert {"id", "title", "files", "covers", "parallel_safe", "depends_on"} <= set(task)


@pytest.mark.parametrize("agent", ["product-manager", "architect", "reviewer"])
def test_spec_agents_read_the_format_instead_of_restating_it(agent):
    text = (PLUGINS / "svc" / "agents" / f"{agent}.md").read_text()
    assert "${CLAUDE_PLUGIN_ROOT}/skills/spec-format/references/" in text
    assert "STORY-NNN" not in text and "docs/backlog.md" not in text


def test_product_manager_hands_questions_back_and_is_shape_agnostic():
    pm = (PLUGINS / "svc" / "agents" / "product-manager.md").read_text()
    assert "OPEN QUESTIONS:" in pm and "Python project" not in pm
    assert "Bash" not in front(PLUGINS / "svc" / "agents" / "product-manager.md")["tools"]


def test_reviewer_is_routed_and_cannot_edit_code():
    meta = front(PLUGINS / "svc" / "agents" / "reviewer.md")
    assert "Edit" not in meta["tools"] and meta["model"] == "opus"
    assert '"reviewer": "svc:reviewer"' in (ROOT / "scripts" / "cplat" / "shapecmd.py").read_text()


@pytest.mark.parametrize("plugin", CODE_PLUGINS)
def test_testers_write_acceptance_tests_first_in_their_idiom(plugin):
    text = (PLUGINS / plugin / "agents" / "tester.md").read_text()
    section = text.split("## Acceptance mode", 1)[1].split("\n## ", 1)[0]
    assert "AC-007.1" in section and "fail because the behaviour is missing" in section
    assert "docs/backlog.md" not in text


@pytest.mark.parametrize("plugin", CODE_PLUGINS)
def test_coders_never_weaken_acceptance_tests(plugin):
    assert "Never edit, skip or weaken them" in (PLUGINS / plugin / "agents" / "coder.md").read_text()


def test_agents_doc_matches_the_agent_files():
    """docs/AGENTS.md lists each plugin's agents with a model; both must match the files (drift found in the review)."""
    doc = (ROOT / "docs" / "AGENTS.md").read_text()
    blocks = re.split(r"^### `([\w-]+)` plugin.*$", doc, flags=re.M)
    listed = {}
    for plugin, body in zip(blocks[1::2], blocks[2::2]):
        for name, model in re.findall(r"^\| `(?:[\w-]+:)?([\w-]+)` \| (\w+) \|", body.split("\n## ", 1)[0], re.M):
            listed[(plugin, name)] = model
    actual = {(p.parent.parent.name, p.stem): front(p)["model"] for p in PLUGINS.glob("*/agents/*.md")}
    assert listed == actual


# ---------------- svc 3.0 commands (STORY-039) ----------------

COMMANDS = PLUGINS / "component" / "commands"


@pytest.mark.parametrize("name", ["spec", "plan", "build", "verify"])
def test_spec_commands_exist_with_a_usage_line(name):
    meta = front(COMMANDS / f"{name}.md")
    assert f"/component:{name}" in meta["description"] and len(meta["description"]) < 260


def test_spec_command_asks_the_user_and_never_approves_alone():
    text = (COMMANDS / "spec.md").read_text()
    assert "AskUserQuestion" in text and "cplat spec approve" in text and "OPEN QUESTIONS" in text
    assert "Never answer an open question on the user's behalf" in text


def test_plan_and_build_refuse_unapproved_specs():
    for name in ("plan", "build"):
        assert "spec check <id> --require approved" in (COMMANDS / f"{name}.md").read_text()


def test_build_writes_tests_first_verifies_and_resumes():
    text = (COMMANDS / "build.md").read_text()
    phases = [text.index(h) for h in ("## Phase 1 — Acceptance tests (red)", "## Phase 2 — Implement",
                                      "## Phase 3 — QA", "## Phase 4 — Verify", "## Phase 7 — Pull request")]
    assert phases == sorted(phases)
    assert "**Acceptance mode.**" in text and "agents.reviewer" in text
    assert "skip tasks with `done: true`" in text and "cplat spec task-done" in text and "set-status <id> done" in text


@pytest.mark.parametrize("name", ["fix"])
def test_small_pipelines_stop_at_a_spec_change(name):
    assert "/component:spec --amend <NNN>" in (COMMANDS / f"{name}.md").read_text()


# ---------------- app 1.0 commands (STORY-040) ----------------

APP = PLUGINS / "system"


@pytest.mark.parametrize("name", ["spec", "plan", "ship"])
def test_app_commands_exist_with_a_usage_line(name):
    meta = front(APP / "commands" / f"{name}.md")
    assert f"/system:{name}" in meta["description"] and len(meta["description"]) < 260


def test_app_plan_and_build_need_an_approved_product_spec():
    plan = (APP / "commands" / "plan.md").read_text()
    assert "spec check <id> --require approved" in plan or "spec check <spec_id> --require approved" in plan
    # /system:ship has no build step of its own: cplat system ship start refuses a spec that is not approved
    assert "a spec that is not approved" in (APP / "commands" / "ship.md").read_text()


def test_app_build_runs_each_repo_through_its_own_spec_and_never_answers_questions():
    text = (APP / "commands" / "ship.md").read_text()
    assert "/component:spec --from-plan <absolute plan path> <repo-id>" in text and "never answer them" in text
    assert "never merge" in text.lower()


def test_planner_assigns_criteria_instead_of_writing_prompts():
    text = (APP / "agents" / "planner.md").read_text()
    assert "acs: [AC-<NNN>.1" in text and "spec: <PLAN_ID>" in text and "Never restate criteria in `arguments`" in text


def test_repo_specs_come_from_the_deterministic_slice():
    text = (COMMANDS / "spec.md").read_text()
    assert "cplat spec new --from-plan <abs plan path> <repo-id>" in text and "**System context**" in text
    assert "System context" in (PLUGINS / "svc" / "agents" / "product-manager.md").read_text()


def test_build_checks_the_worktree_base_before_fanning_out():
    """AC-044.3 AC-044.4: a probe worktree off the feature head means sequential, with the reason."""
    text = (COMMANDS / "build.md").read_text()
    probe = text.split("### 2.2 Worktree probe", 1)[1].split("### 2.3", 1)[0]
    assert "git rev-parse HEAD" in probe and "FEATURE_HEAD" in probe and 'worktree.baseRef: "head"' in probe
    assert "only that task's commits" in text


def test_app_build_runs_the_gitops_entry_itself():
    """AC-045.1 AC-045.3 AC-045.4: cplat operations in the gitops repo, merge first, no leftover worktree."""
    text = (APP / "commands" / "ship.md").read_text()
    assert "cplat component set" in text and "cplat resource add" in text and "starts before it is merged" in text
    # the worktree is removed by cplat system ship, not by the command file
    assert '"worktree", "remove"' in (ROOT / "scripts" / "cplat" / "appship.py").read_text()
    assert "is built by you in the printed worktree" in text


def test_planner_writes_gitops_operations():
    """AC-045.2"""
    text = (APP / "agents" / "planner.md").read_text()
    assert "gitops:" in text and "{uses: postgres, component:" in text


def test_criteria_stay_environment_neutral():
    """AC-056.1"""
    ref = (SKILL / "references" / "spec.md").read_text()
    assert "no host ports, local hostnames or machine paths" in ref
    assert "host ports" in (PLUGINS / "svc" / "agents" / "product-manager.md").read_text()


def test_spec_format_is_hidden_from_the_command_list():
    """AC-058.1: reference material, not a command."""
    assert front(SKILL / "SKILL.md").get("user-invocable") is False


@pytest.mark.parametrize("agent", ["product-manager", "architect", "reviewer"])
def test_agents_still_read_the_hidden_references(agent):
    """AC-058.2"""
    text = (PLUGINS / "svc" / "agents" / f"{agent}.md").read_text()
    refs = re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/(skills/spec-format/references/[\w.-]+)", text)
    assert refs and all((PLUGINS / "svc" / r).is_file() for r in refs)


def test_security_agent_summarises_unfixable_base_image_findings():
    """AC-059.2"""
    text = (PLUGINS / "shared" / "agents" / "security.md").read_text().lower()
    assert "no fix released" in text and "base image" in text and "fixable" in text


# ---------------- wave 2 (specs 046, 047, 053) ----------------

def test_app_build_waits_for_repo_agents_in_the_foreground():
    """AC-046.1: print mode stops background agents after 600 s; foreground calls in one message still run in parallel."""
    text = (APP / "commands" / "ship.md").read_text()
    assert "foreground" in text and "never `run_in_background`" in text


def test_unattended_runs_are_documented():
    """AC-046.2"""
    doc = (ROOT / "docs" / "ADOPTING.md").read_text()
    section = doc.split("## Unattended runs", 1)[1].split("\n## ", 1)[0]
    assert "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS" in section and "--permission-mode" in section and "trust" in section


def test_build_resumes_an_interrupted_task():
    """AC-047.1 AC-047.2 AC-047.3 AC-047.4"""
    text = (COMMANDS / "build.md").read_text()
    pre = text.split("## Phase 0", 1)[1].split("## Phase 1", 1)[0]
    assert "wip(<task-id>): interrupted" in pre and "git restore --staged" in pre
    assert "not `building`" in pre and "clean" in pre
    assert "squash-merge" in text.split("## Phase 7", 1)[1]


def test_planner_writes_errors_and_timeouts_into_the_contract():
    """AC-053.2"""
    text = (APP / "agents" / "planner.md").read_text()
    assert "### Errors" in text and "### Timeouts" in text and "not list" in text


# ---------------- wave 3 (specs 048, 050) ----------------

def test_build_formats_acceptance_tests_and_checks_them():
    """AC-048.1 AC-048.2"""
    text = (COMMANDS / "build.md").read_text()
    assert "cplat spec test-diff" in text and "lint-fix" in text


@pytest.mark.parametrize("plugin", CODE_PLUGINS)
def test_coders_may_format_acceptance_tests(plugin):
    """AC-048.1"""
    text = (PLUGINS / plugin / "agents" / "coder.md").read_text()
    assert "Never edit, skip or weaken them" in text and "formatting through `devbox run lint-fix` is fine" in text


def test_app_plan_pushes_the_spec_branch_and_opens_the_pr():
    """AC-050.1"""
    text = (APP / "commands" / "plan.md").read_text()
    assert "git push -u origin docs/spec-<spec_id>" in text and "gh pr create" in text


def test_app_ship_checks_the_plan_is_on_main():
    """AC-050.2: /system:ship publishes the spec and plan to main (a PR merged on green) before any repo starts."""
    text = (APP / "commands" / "ship.md").read_text()
    assert "## Phase `publish`" in text and "not on `main`" in text
    assert "origin/main" in (ROOT / "scripts" / "cplat" / "appship.py").read_text()


# ---------------- waves 4-5 (specs 051, 052) ----------------

PR_COMMANDS = [COMMANDS / "build.md", COMMANDS / "fix.md"]


@pytest.mark.parametrize("path", PR_COMMANDS, ids=lambda p: f"{p.parent.parent.name}:{p.stem}")
def test_pipelines_end_with_a_ready_pr_command(path):
    """AC-051.1 AC-051.2: no error when gh pr create is denied; the exact command is the last line."""
    text = path.read_text()
    assert "gh pr create" in text and "PR_BODY.md" in text and "last line" in text and "not an error" in text


def test_build_asks_only_for_missing_gitops_wiring():
    """AC-052.2"""
    text = (COMMANDS / "build.md").read_text()
    assert "Provided by the system" in text and "only for" in text


def test_build_stops_on_an_acceptance_test_change():
    """AC-063.4: every `cplat spec test-diff` step in /component:build stops on exit 1 instead of judging it."""
    build = (COMMANDS / "build.md").read_text()
    steps = [p for p in re.split(r"\n(?=\d+\. |After |## )", build) if "cplat spec test-diff" in p]
    assert len(steps) >= 2
    for step in steps:
        assert re.search(r"exit 1 (means .*?: )?stop|exit 1 stops", step, re.S | re.I), step[:200]
    assert "never decide yourself that it is a false alarm" in build


STALE_DEV = re.compile(r"dev\W{0,6}(tracks|runs|follows)\W{0,6}(each image's\s+)?`?latest|`dev`: `latest`|dev already runs latest|bump-dev\.yml", re.I)


def test_nothing_claims_dev_tracks_latest():
    """AC-062.5: docs, plugins and templates describe dev following main through pin PRs."""
    hits = []
    for base in ("docs", "plugins", "templates", "site/src/content/docs"):
        for p in (ROOT / base).rglob("*"):
            if p.suffix in {".md", ".jinja", ".mdx"} and "e2e" not in p.parts and "specs" not in p.parts and p.name != "CHANGELOG.md" \
                    and not p.name.startswith("e2e-"):   # field reports quote what happened
                hits += [f"{p.relative_to(ROOT)}: {m.group(0)}" for m in STALE_DEV.finditer(p.read_text(errors="ignore"))]
    assert not hits, hits
    assert "pin PR" in (ROOT / "docs" / "HOW-IT-WORKS.md").read_text()
    assert (ROOT / "docs" / "adr" / "027-dev-follows-main-through-pin-prs.md").is_file()
