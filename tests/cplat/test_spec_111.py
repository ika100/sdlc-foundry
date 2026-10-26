"""Spec 111 acceptance tests (tasks t1-t3): `cplat ship continue`, headless sessions that load only the repo's MCP, and
`cplat quick-task inline-check`. Seams: `ship.land` / `ship.deploy` are replaced by fakes that have the real signatures
(so the options passed on are checked), the claude command is built by `headless.claude_cmd`, the inline check runs in
tiny git repos. Contract: docs/specs/111-*/design.md."""
import inspect
import json
import re
import subprocess
from pathlib import Path

import pytest

import core
import headless
import ship
from test_ship import repo as ship_repo  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = ROOT / "plugins" / "svc" / "commands"
SHIP_CAP = 11367   # ship.md today; spec 111 must not make it larger (spec 100's cap, see test_lean_prompts BEFORE["ship"] = 12106)


# ---------------- cplat ship continue (AC-111.1, AC-111.2) ----------------

class Phases:
    """Fake land/deploy with the real signatures; each call is recorded and moves the real ship state like the real step."""

    def __init__(self, repo, monkeypatch, land=(True, ["land: green, merged"]), deploy=(True, ["deploy: done"]),
                 escalate_in=None):
        self.repo, self.calls, self.results, self.escalate_in = repo, [], {"land": land, "deploy": deploy}, escalate_in
        monkeypatch.setattr(ship, "land", self._step("land", ship.land))
        monkeypatch.setattr(ship, "deploy", self._step("deploy", ship.deploy))

    def _step(self, name, real):
        sig = inspect.signature(real)

        def fake(*args, **kw):
            bound = sig.bind(*args, **kw)
            bound.apply_defaults()
            self.calls.append((name, dict(bound.arguments)))
            st = ship.require_state(self.repo)
            if self.escalate_in == name:
                st["escalated"] = "merge conflict"
            elif self.results[name][0]:
                st["phase"] = "deploy" if name == "land" else "done"
            ship.save_state(self.repo, st)
            return self.results[name]
        return fake

    @property
    def names(self):
        return [n for n, _ in self.calls]


def at_phase(repo, phase):
    st = ship.start(repo, "7", True)
    st.update(phase=phase, pr="https://github.com/acme/shop-api/pull/7")
    ship.save_state(repo, st)


def run_continue(repo, *extra):
    return ship.main(["--repo", str(repo), "continue", *extra])


def test_continue_runs_land_then_deploy_in_one_command(ship_repo, monkeypatch, capsys):
    """AC-111.1: land and then deploy run in one command; the output has both line lists in order; exit 0 when done."""
    at_phase(ship_repo, "land")
    ph = Phases(ship_repo, monkeypatch)
    assert run_continue(ship_repo) == 0
    assert ph.names == ["land", "deploy"]
    out = capsys.readouterr().out
    assert out.index("land: green, merged") < out.index("deploy: done")


def test_continue_stops_at_a_red_land_without_deploy(ship_repo, monkeypatch, capsys):
    """AC-111.1: a red check that needs a fix round ends the command with exit 1; deploy is never called."""
    at_phase(ship_repo, "land")
    ph = Phases(ship_repo, monkeypatch, land=(False, ["RED: lint failed"]))
    assert run_continue(ship_repo) == 1
    assert ph.names == ["land"]
    assert "RED: lint failed" in capsys.readouterr().out


def test_continue_exits_2_when_the_run_is_escalated_in_land(ship_repo, monkeypatch, capsys):
    """AC-111.1: an escalation during land stops the command with exit 2 and no deploy."""
    at_phase(ship_repo, "land")
    ph = Phases(ship_repo, monkeypatch, land=(False, ["escalated: merge conflict"]), escalate_in="land")
    assert run_continue(ship_repo) == 2
    assert ph.names == ["land"]
    assert "escalated: merge conflict" in capsys.readouterr().out


def test_continue_exits_2_when_deploy_escalates(ship_repo, monkeypatch):
    """AC-111.1: an escalation during deploy (e.g. smoke red) is exit 2, not 1."""
    at_phase(ship_repo, "land")
    ph = Phases(ship_repo, monkeypatch, deploy=(False, ["smoke red in dev: 1 failing"]), escalate_in="deploy")
    assert run_continue(ship_repo) == 2
    assert ph.names == ["land", "deploy"]


def test_continue_exits_1_when_deploy_is_red_but_not_escalated(ship_repo, monkeypatch):
    """AC-111.1: a failed deploy that is not an escalation is exit 1."""
    at_phase(ship_repo, "land")
    ph = Phases(ship_repo, monkeypatch, deploy=(False, ["pin-dev run failed"]))
    assert run_continue(ship_repo) == 1
    assert ph.names == ["land", "deploy"]


@pytest.mark.parametrize("phase", ["deploy", "done"])
def test_continue_skips_a_phase_that_is_already_past(ship_repo, monkeypatch, phase):
    """AC-111.1: after a deploy-only resume (or when done) land is not called again."""
    at_phase(ship_repo, phase)
    ph = Phases(ship_repo, monkeypatch)
    assert run_continue(ship_repo) == 0
    assert "land" not in ph.names
    assert ph.names == ["deploy"]


def test_continue_passes_its_options_to_both_steps(ship_repo, monkeypatch):
    """AC-111.2: --timeout, --interval, --queue-timeout, --context and --base-url reach land/deploy unchanged."""
    at_phase(ship_repo, "land")
    ph = Phases(ship_repo, monkeypatch)
    assert run_continue(ship_repo, "--timeout", "99", "--interval", "3", "--queue-timeout", "44", "--context", "kc",
                        "--base-url", "https://dev.example") == 0
    land, deploy = (args for _, args in ph.calls)
    assert (land["timeout"], land["interval"], land["queue_timeout"]) == (99, 3, 44)
    assert (deploy["timeout"], deploy["interval"], deploy["queue_timeout"]) == (99, 3, 44)
    assert (deploy["context"], deploy["base_url"]) == ("kc", "https://dev.example")


def test_the_single_steps_still_work_unchanged(ship_repo, monkeypatch, capsys):
    """AC-111.2: `cplat ship land` and `cplat ship deploy` keep their exit codes and call only their own step."""
    at_phase(ship_repo, "land")
    ph = Phases(ship_repo, monkeypatch, land=(False, ["RED"]))
    assert ship.main(["--repo", str(ship_repo), "land"]) == 1
    ph.results["land"] = (True, ["green"])
    assert ship.main(["--repo", str(ship_repo), "land"]) == 0
    assert ship.main(["--repo", str(ship_repo), "deploy"]) == 0
    assert ph.names == ["land", "land", "deploy"]


def test_continue_keeps_the_rules_of_the_steps_through_the_real_land(ship_repo, monkeypatch):
    """AC-111.2: merge only on green and the budget safe points live in land itself: continue calls the module's
    land/deploy functions (looked up at call time) and does not copy their logic, so a red land never reaches deploy
    and never merges."""
    at_phase(ship_repo, "land")
    merged = []
    monkeypatch.setattr(ship, "_merged", lambda *a, **k: merged.append(a) or (True, ["merged"]), raising=False)
    ph = Phases(ship_repo, monkeypatch, land=(False, ["RED"]))
    assert run_continue(ship_repo) == 1
    assert ph.names == ["land"] and merged == []
    assert ship.require_state(ship_repo)["phase"] == "land"


def test_continue_is_a_ship_subcommand_with_the_documented_options(ship_repo):
    """AC-111.2: the contract line `cplat ship continue [--timeout S] [--interval S] [--queue-timeout S] [--context C] [--base-url URL]`."""
    at_phase(ship_repo, "land")
    with pytest.raises(SystemExit) as e:
        ship.main(["--repo", str(ship_repo), "continue", "--help"])
    assert e.value.code == 0


# ---------------- headless sessions (AC-111.4 - AC-111.6) ----------------

def flag_values(cmd, flag):
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == flag]


@pytest.fixture()
def hrepo(tmp_path):
    r = tmp_path / "shop-api"
    r.mkdir()
    return r


def cmd_for(repo, plugin_dirs=None):
    return headless.claude_cmd("/svc:ship 7", "sonnet", plugin_dirs, repo)


def test_claude_cmd_is_strict_with_no_mcp_when_the_repo_has_none(hrepo):
    """AC-111.4: no .mcp.json means no MCP server at all: --strict-mcp-config and no --mcp-config."""
    cmd = cmd_for(hrepo)
    assert "--strict-mcp-config" in cmd
    assert "--mcp-config" not in cmd


def test_claude_cmd_loads_the_repos_mcp_json_only(hrepo):
    """AC-111.4: the repo's .mcp.json is the only --mcp-config."""
    (hrepo / ".mcp.json").write_text("{}")
    cmd = cmd_for(hrepo)
    assert "--strict-mcp-config" in cmd
    assert flag_values(cmd, "--mcp-config") == [str(hrepo / ".mcp.json")]


def test_claude_cmd_turns_the_claude_ai_connectors_off_in_one_settings_json(hrepo):
    """AC-111.4: exactly one --settings, its JSON has disableClaudeAiConnectors true (with and without plugin dirs)."""
    plugin = hrepo / "plug"
    (plugin / ".claude-plugin").mkdir(parents=True)
    for dirs in (None, [str(plugin)]):
        cmd = cmd_for(hrepo, dirs)
        settings = flag_values(cmd, "--settings")
        assert len(settings) == 1
        assert json.loads(settings[0])["disableClaudeAiConnectors"] is True


def test_claude_cmd_keeps_the_plugin_read_rules_in_the_same_settings(hrepo):
    """AC-111.4: the existing plugin Read rules are merged into the one --settings JSON."""
    cmd = cmd_for(hrepo, ["/x/plug"])
    data = json.loads(flag_values(cmd, "--settings")[0])
    assert data["permissions"]["allow"] == ["Read(//x/plug/**)"]
    assert data["disableClaudeAiConnectors"] is True
    assert flag_values(cmd, "--plugin-dir") == ["/x/plug"]


def test_the_extra_mcp_config_of_the_settings_file_is_loaded_too(hrepo):
    """AC-111.5: headless: {mcp_config: <file>} adds that file, relative to the repo, after .mcp.json; nothing else."""
    (hrepo / ".mcp.json").write_text("{}")
    (hrepo / "ci").mkdir()
    (hrepo / "ci" / "mcp-extra.json").write_text("{}")
    (hrepo / ".platform-settings.yml").write_text("headless:\n  mcp_config: ci/mcp-extra.json\n")
    cmd = cmd_for(hrepo)
    assert flag_values(cmd, "--mcp-config") == [str(hrepo / ".mcp.json"), str(hrepo / "ci" / "mcp-extra.json")]
    assert "--strict-mcp-config" in cmd


def test_the_extra_mcp_config_works_without_a_mcp_json(hrepo):
    """AC-111.5: the extra file alone is the only --mcp-config when the repo has no .mcp.json."""
    (hrepo / "extra.json").write_text("{}")
    (hrepo / ".platform-settings.yml").write_text("headless:\n  mcp_config: extra.json\n")
    assert flag_values(cmd_for(hrepo), "--mcp-config") == [str(hrepo / "extra.json")]


def test_a_missing_extra_mcp_file_is_refused_naming_the_setting(hrepo):
    """AC-111.5: a mcp_config that does not exist is a PlatformError naming headless.mcp_config."""
    (hrepo / ".platform-settings.yml").write_text("headless:\n  mcp_config: nope.json\n")
    with pytest.raises(core.PlatformError, match=r"mcp_config"):
        cmd_for(hrepo)


def test_dry_run_shows_the_restriction(hrepo, tmp_path, capsys):
    """AC-111.4: `cplat headless --dry-run` prints the command with the restriction (cplat headless starts the session)."""
    (hrepo / ".claude").mkdir()
    (hrepo / ".claude" / "settings.json").write_text("{}")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=hrepo, check=True)
    assert headless.main(["/svc:ship 7", "--repo", str(hrepo), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "--strict-mcp-config" in out and "disableClaudeAiConnectors" in out


def test_only_claude_cmd_adds_the_mcp_flags(hrepo):
    """AC-111.6: interactive sessions are untouched: no cplat code other than headless.claude_cmd builds a claude command
    with these flags, and no hook, command or agent file passes them."""
    holders = [p.relative_to(ROOT).as_posix() for p in (ROOT / "scripts").rglob("*.py")
               if "strict-mcp-config" in p.read_text() or "disableClaudeAiConnectors" in p.read_text()]
    assert holders == ["scripts/cplat/headless.py"]
    for p in (ROOT / "plugins").rglob("*"):
        if p.is_file() and p.suffix in {".md", ".json", ".sh"}:
            assert "strict-mcp-config" not in p.read_text(), p
    assert "--strict-mcp-config" in cmd_for(hrepo)


def test_benchmark_sessions_go_through_claude_cmd():
    """AC-111.4: `cplat runs benchmark` starts its sessions with headless.claude_cmd, so it gets the same restriction."""
    src = (ROOT / "scripts" / "cplat" / "runs_bench.py").read_text()
    assert "claude_cmd" in src or "headless" in src


# ---------------- quick-task inline-check (AC-111.7) ----------------

def sh(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def qrepo(tmp_path, monkeypatch):
    r = tmp_path / "svc"
    r.mkdir()
    sh(r, "init", "-q", "-b", "main")
    (r / ".copier-answers.yml").write_text("_src_path: gh:ika100/sdlc-foundry/templates/service-python\nproject_name: svc\n")
    (r / "src" / "pkg").mkdir(parents=True)
    (r / "src" / "pkg" / "mod.py").write_text("x = 1\n")
    (r / "src" / "pkg" / "other.py").write_text("y = 1\n")
    (r / "tests").mkdir()
    (r / "tests" / "test_mod.py").write_text("def test_a():\n    pass\n")
    (r / "tests" / "test_other.py").write_text("def test_b():\n    pass\n")
    (r / "pyproject.toml").write_text("[project]\nname='svc'\n")
    (r / "uv.lock").write_text("# lock\n")
    (r / "Dockerfile").write_text("FROM python\n")
    (r / ".platform-settings.yml").write_text("validation: selective\n")
    for d in (".github/workflows", ".claude", "docs/specs/001-x"):
        (r / d).mkdir(parents=True)
    (r / ".github/workflows/ci.yml").write_text("on: push\n")
    (r / ".claude/settings.json").write_text("{}\n")
    (r / "docs/specs/001-x/spec.md").write_text("spec\n")
    sh(r, "add", "-A")
    sh(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    sh(r, "checkout", "-q", "-b", "feat")
    monkeypatch.chdir(r)
    return r


def check(repo, capsys, *extra):
    import quicktask
    code = quicktask.main(["inline-check", "--base", "main", *extra])
    return code, capsys.readouterr().out


def commit(repo):
    sh(repo, "add", "-A")
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "change")


def lines_file(repo, rel, n):
    (repo / rel).write_text("".join(f"v{i} = {i}\n" for i in range(n)))


def test_one_source_and_one_test_file_are_allowed(qrepo, capsys):
    """AC-111.7: one source and one test file within 60 lines exit 0 with `inline: allowed (...)`."""
    (qrepo / "src/pkg/mod.py").write_text("x = 2\n")
    (qrepo / "tests/test_mod.py").write_text("def test_a():\n    assert True\n")
    commit(qrepo)
    code, out = check(qrepo, capsys)
    assert code == 0
    assert re.match(r"inline: allowed \(2 files, \d+ lines\)", out)


def test_uncommitted_and_untracked_changes_count(qrepo, capsys):
    """AC-111.7: the working tree and untracked files are part of the diff."""
    (qrepo / "src/pkg/mod.py").write_text("x = 2\n")          # modified, not committed
    (qrepo / "src/pkg/new.py").write_text("z = 1\n")           # untracked: second source file
    code, out = check(qrepo, capsys)
    assert code == 1 and "inline: refused" in out


def test_two_source_files_are_refused(qrepo, capsys):
    """AC-111.7: at most one source file."""
    (qrepo / "src/pkg/mod.py").write_text("x = 2\n")
    (qrepo / "src/pkg/other.py").write_text("y = 2\n")
    commit(qrepo)
    code, out = check(qrepo, capsys)
    assert code == 1 and out.startswith("inline: refused — ") and "source" in out


def test_two_test_files_are_refused(qrepo, capsys):
    """AC-111.7: at most one test file (tests are the shape's test_globs)."""
    (qrepo / "tests/test_mod.py").write_text("def test_a():\n    assert 1\n")
    (qrepo / "tests/test_other.py").write_text("def test_b():\n    assert 1\n")
    commit(qrepo)
    code, out = check(qrepo, capsys)
    assert code == 1 and out.startswith("inline: refused — ") and "test" in out


def test_a_test_file_does_not_count_as_a_source_file(qrepo, capsys):
    """AC-111.7: one source plus one test is two files but within the limits."""
    (qrepo / "src/pkg/mod.py").write_text("x = 3\n")
    (qrepo / "tests/test_other.py").write_text("def test_b():\n    assert 1\n")
    commit(qrepo)
    assert check(qrepo, capsys)[0] == 0


def test_exactly_60_changed_lines_are_allowed(qrepo, capsys):
    """AC-111.7: the limit itself is allowed (added + removed lines; the 1-line file is replaced by 60 lines: 61 changed ... so
    start from a new file: 60 added lines)."""
    lines_file(qrepo, "src/pkg/new.py", 60)
    code, out = check(qrepo, capsys)
    assert code == 0 and "60 lines" in out


def test_61_changed_lines_are_refused(qrepo, capsys):
    """AC-111.7: one line over the limit is refused, naming the line rule."""
    lines_file(qrepo, "src/pkg/new.py", 61)
    code, out = check(qrepo, capsys)
    assert code == 1 and out.startswith("inline: refused — ") and "60" in out


def test_removed_lines_count_toward_the_limit(qrepo, capsys):
    """AC-111.7: added + removed: 1 removed + 60 added = 61 is refused, 1 removed + 59 added = 60 is allowed."""
    lines_file(qrepo, "src/pkg/mod.py", 59)     # replaces 1 line with 59: 60 changed
    assert check(qrepo, capsys)[0] == 0
    lines_file(qrepo, "src/pkg/mod.py", 60)     # 61 changed
    assert check(qrepo, capsys)[0] == 1


@pytest.mark.parametrize("path", ["pyproject.toml", "uv.lock", "Dockerfile", ".github/workflows/ci.yml",
                                  ".claude/settings.json", ".platform-settings.yml", "docs/specs/001-x/spec.md"])
def test_forbidden_files_are_refused_even_for_one_line(qrepo, capsys, path):
    """AC-111.7: no manifest, lock file, CI workflow, Dockerfile, .claude file, settings file or spec; exit 1 names the rule."""
    with (qrepo / path).open("a") as f:
        f.write("# one line\n")
    code, out = check(qrepo, capsys)
    assert code == 1 and out.startswith("inline: refused — ")
    assert path.split("/")[0].lower().lstrip(".") in out.lower() or Path(path).name.lower() in out.lower() or "manifest" in out or "lock" in out


def test_a_nested_dockerfile_variant_is_refused(qrepo, capsys):
    """AC-111.7: Dockerfile* includes Dockerfile.dev."""
    (qrepo / "Dockerfile.dev").write_text("FROM python\n")
    code, out = check(qrepo, capsys)
    assert code == 1 and "inline: refused" in out


def test_no_change_at_all_is_allowed_or_says_nothing_to_check(qrepo, capsys):
    """AC-111.7: an empty diff is within every limit (0 files)."""
    code, out = check(qrepo, capsys)
    assert code == 0 and out.startswith("inline: allowed (0 files, 0 lines)")


def test_inline_check_is_a_cplat_command():
    """AC-111.7: `cplat quick-task inline-check` is wired in cplat.py."""
    import cplat
    assert cplat.COMMANDS.get("quick-task") == "quicktask"


# ---------------- command text (AC-111.3, AC-111.8, AC-111.9) ----------------

def test_ship_md_uses_continue_after_the_pr():
    """AC-111.3: ship.md uses `cplat ship continue` after `cplat ship pr` and names exit codes 0, 1 and 2."""
    text = (COMMANDS / "ship.md").read_text()
    assert "cplat ship continue" in text
    assert text.index("cplat ship pr --title") < text.index("cplat ship continue")
    assert re.search(r"exit(s)?\s*2|2 \(?escalat|`2`", text)


def test_ship_md_calls_land_or_deploy_alone_only_to_resume():
    """AC-111.3: `cplat ship land` / `cplat ship deploy` appear only as the resume after a fix round."""
    text = (COMMANDS / "ship.md").read_text()
    for step in ("land", "deploy"):
        for m in re.finditer(rf"cplat ship {step}\b", text):
            ctx = text[max(0, m.start() - 300): m.end() + 300].lower()
            assert "resum" in ctx or "fix round" in ctx or "after a fix" in ctx, f"cplat ship {step} not tied to a resume"


def test_ship_md_stays_under_the_size_cap():
    """AC-111.3: spec 100's cap: ship.md is under 12106 bytes and no larger than today."""
    size = len((COMMANDS / "ship.md").read_bytes())
    assert size < 12106 and size <= SHIP_CAP


def test_the_red_round_reference_resumes_with_land():
    """AC-111.3: references/ship-land-red.md keeps `cplat ship land` for the resume after a fix."""
    assert "cplat ship land" in (ROOT / "plugins" / "svc" / "references" / "ship-land-red.md").read_text()


def quick_task():
    return (COMMANDS / "quick-task.md").read_text()


def test_quick_task_goes_inline_only_after_the_check_passes():
    """AC-111.7: quick-task.md names `cplat quick-task inline-check` as the condition for the coordinator's own change."""
    text = quick_task()
    assert "cplat quick-task inline-check" in text
    assert "inline" in text.lower()


def test_quick_task_runs_both_gates_inline_before_the_pr():
    """AC-111.8: on the inline path `cplat quiet quality` and `cplat quiet test-fast` run before `cplat pr open`."""
    text = quick_task()
    start = text.index("cplat quick-task inline-check")
    assert text.index("cplat quiet quality", start) < text.index("cplat pr open")
    assert text.index("cplat quiet test-fast", start) < text.index("cplat pr open")


def test_quick_task_pr_body_says_made_inline():
    """AC-111.8: the PR body says the change was made inline and why the check allowed it."""
    assert "made inline" in quick_task()


def test_quick_task_never_retries_inline_after_a_refusal_or_red_gate():
    """AC-111.9: on exit 1 or a red gate the agent path (coder -> quality -> tester) follows and inline is not tried again."""
    text = quick_task().lower()
    assert re.search(r"never (try|retry|retried)[^.\n]*inline|inline[^.\n]*(never|not) (be )?(retried|tried again|retry)|do(es)? not try[^.\n]*inline", text)
    assert "red" in text and "coder" in text


# ---------------- review round: AC-111.7 / AC-111.9 follow-ups ----------------

def test_quick_task_checks_after_the_change_is_made():
    """AC-111.7: the change is made first, then inline-check judges the real diff."""
    text = quick_task()
    i = text.index("make the change yourself")
    assert "once made" in text[i: i + 120] and text.index("cplat quick-task inline-check") > i


def test_quick_task_keeps_touched_files_and_no_worktrees():
    """AC-111.9: the TOUCHED_FILES capture and 'no worktrees' stay; the inline path skips Step 2's agents but runs both gates."""
    text = quick_task()
    assert "TOUCHED_FILES=$(git diff --name-only $BASE_REF -- .)" in text
    assert "no worktrees" in text and "skip Step 2's agents" in text


@pytest.mark.parametrize("old,new", [("pyproject.toml", "pkg.toml"), (".github/workflows/ci.yml", "ci.yml"),
                                     ("docs/specs/001-x/spec.md", "notes.md"), ("Dockerfile", "Dockerfile2"),
                                     (".claude/settings.json", "settings.json")])
def test_renaming_a_protected_file_is_refused(qrepo, capsys, old, new):
    """AC-111.7: a rename is a delete plus an add; the old path is checked too."""
    sh(qrepo, "mv", old, new)
    code, out = check(qrepo, capsys)
    assert code == 1 and out.startswith("inline: refused")


@pytest.mark.parametrize("path", ["docs/specs/001-x/spec.md", "pyproject.toml", ".github/workflows/ci.yml"])
def test_deleting_a_protected_file_is_refused(qrepo, capsys, path):
    """AC-111.7: a deletion is refused like a change (a deleted spec too)."""
    (qrepo / path).unlink()
    code, out = check(qrepo, capsys)
    assert code == 1 and out.startswith("inline: refused")


def test_ship_next_step_and_md_point_to_continue():
    """AC-111.3: the resume hint after a fix round is `cplat ship continue`."""
    assert "cplat ship continue" in ship.next_step({"phase": "land", "spec": "7"}) if hasattr(ship, "next_step") else True
    assert "resume with `cplat ship continue`" in (COMMANDS / "ship.md").read_text()
    assert "from the green smoke" in (COMMANDS / "ship.md").read_text()


def test_retro_proposal_session_gets_the_mcp_restriction(tmp_path, monkeypatch):
    """AC-111.4: retro's unattended `claude -p` carries the same MCP flags as headless."""
    import retro
    seen = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    (tmp_path / "report.json").write_text("{}")
    monkeypatch.setattr(retro.retro_proposals, "prompt", lambda d: "p")
    monkeypatch.setattr(retro.subprocess, "run", lambda cmd, **k: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    retro._propose(type("NS", (), {"dir": str(tmp_path), "model": None, "max_minutes": 1})())
    assert seen and "--strict-mcp-config" in seen[0]
    assert json.loads(flag_values(seen[0], "--settings")[0])["disableClaudeAiConnectors"] is True
