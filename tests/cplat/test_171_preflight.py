"""Spec 171 acceptance tests: the preflight of an unattended run refuses a repo without an allowlist (AC-171.1), and the platform
repo's committed settings hold the library template's allowlist (AC-171.2).

Seams: `preflight.check` / `preflight.check_repo` on the 131 world (a real git repo, `gh` stub, replaced settings layers);
`headless.main` on the 131 `World` (a fake `claude`); `scripts/check-settings.py` as a process on a temporary tree and on the
real repository.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_headless_131 import w  # noqa: F401  (fixture)
from test_preflight_131 import install, pf, world  # noqa: F401  (fixtures, helpers)
from test_runs import clock, mem, store, stored  # noqa: F401  (fixtures)
from units131_support import SPEC_ID

ROOT = Path(__file__).resolve().parents[2]
MIN_BASH, MIN_READ = "Bash(cplat *)", "Read(~/.claude/plugins/**)"
DEVBOX_ONLY = ["Bash(devbox run *)"]


def put_settings(repo, allow=None, raw=None):
    path = repo / ".claude" / "settings.json"
    path.parent.mkdir(exist_ok=True)
    if raw is not None:
        path.write_text(raw)
    else:
        path.write_text(json.dumps({} if allow is None else {"permissions": {"allow": allow}}))
    return path


def verdict(world):
    install(world)
    return pf().check(world.repo, "/component:ship", [SPEC_ID])


# ---------------- AC-171.1: no allowlist, no session ----------------

@pytest.mark.parametrize("allow, raw", [
    (None, None),                                    # no permissions at all
    ([], None),                                      # an empty allow list
    (DEVBOX_ONLY, None),                             # allow rules, but neither of the two a session needs first
    (None, "{not json"),                             # an unreadable file counts as no allow rules
])
def test_a_file_without_the_two_minimum_rules_fails_the_preflight_naming_both(world, allow, raw):  # AC-171.1
    put_settings(world.repo, allow, raw)
    f = verdict(world)
    assert f is not None and f.category == "no-repo-allowlist"
    assert f.line().startswith(f"preflight failed: no-repo-allowlist: {MIN_BASH} and {MIN_READ}")
    assert f.reason() == "preflight failed: no-repo-allowlist"


def test_a_missing_read_rule_is_the_only_rule_named(world):  # AC-171.1
    put_settings(world.repo, [MIN_BASH, *DEVBOX_ONLY])
    f = verdict(world)
    assert f.category == "no-repo-allowlist"
    assert f.line().startswith(f"preflight failed: no-repo-allowlist: {MIN_READ}")
    assert MIN_BASH not in f.line()


def test_a_missing_cplat_rule_is_the_only_rule_named(world):  # AC-171.1
    put_settings(world.repo, [MIN_READ, *DEVBOX_ONLY])
    f = verdict(world)
    assert f.category == "no-repo-allowlist"
    assert f.line().startswith(f"preflight failed: no-repo-allowlist: {MIN_BASH}")
    assert MIN_READ not in f.line()


@pytest.mark.parametrize("allow", [
    [MIN_BASH, MIN_READ],
    ["Bash(cplat:*)", MIN_READ],
    ["Bash", "Read"],
    ["Bash(*)", "Read(**)"],
    [MIN_BASH, f"Read({Path.home()}/.claude/plugins/**)"],
    [MIN_BASH, "Read(~/.claude/**)"],
])
def test_rules_that_allow_cplat_and_the_plugins_pass_the_minimum(world, allow):  # AC-171.1
    put_settings(world.repo, allow)
    assert verdict(world) is None


def test_only_allow_rules_of_the_committed_file_count(world):  # AC-171.1
    world.user.write_text(json.dumps({"permissions": {"allow": [MIN_BASH, MIN_READ]}}))     # the user's own settings
    put_settings(world.repo, DEVBOX_ONLY)
    assert verdict(world).category == "no-repo-allowlist"
    put_settings(world.repo, DEVBOX_ONLY)
    path = world.repo / ".claude" / "settings.json"
    path.write_text(json.dumps({"permissions": {"allow": DEVBOX_ONLY, "deny": [MIN_READ]}}))   # a deny rule is no allow rule
    assert verdict(world).category == "no-repo-allowlist"


def test_the_repos_of_a_system_ship_are_checked_the_same_way(world):  # AC-171.1
    put_settings(world.repo, DEVBOX_ONLY)
    install(world)
    f = pf().check_repo(world.repo, "acme/shop-api")
    assert f is not None and f.category == "no-repo-allowlist" and MIN_BASH in f.line()
    put_settings(world.repo, [MIN_BASH, MIN_READ])
    assert pf().check_repo(world.repo, "acme/shop-api") is None


def test_an_unattended_run_without_an_allowlist_starts_no_session_and_costs_nothing(w, store, capsys):  # AC-171.1
    settings = put_settings(w.repo, DEVBOX_ONLY)
    before = settings.read_bytes()
    assert w.run() == 1
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("preflight failed: ")]
    assert len(lines) == 1
    assert lines[0].startswith(f"preflight failed: no-repo-allowlist: {MIN_BASH} and {MIN_READ}")
    assert w.sessions() == []
    rec = stored(store)[-1]
    assert rec["outcome"] == "escalated" and rec["escalation"]["cause"] == "environment"
    assert rec["escalation"]["reason"] == "preflight failed: no-repo-allowlist"
    assert rec["budget"]["used"]["invocations"] == 0 and rec["budget"]["used"]["cost"] == 0
    assert settings.read_bytes() == before                      # AC-131.9: no settings file is written


def test_an_unattended_run_with_the_two_rules_starts_its_sessions(w, capsys):  # AC-171.1
    put_settings(w.repo, [MIN_BASH, MIN_READ, *DEVBOX_ONLY])
    w.run("--max-runs", "1")
    assert "preflight failed" not in capsys.readouterr().out
    assert len(w.sessions()) == 1


# ---------------- AC-171.2: the platform repo's allowlist ----------------

def rules(path, kind):
    return json.loads(Path(path).read_text()).get("permissions", {}).get(kind, [])


@pytest.mark.parametrize("kind", ["allow", "ask"])
def test_the_platform_settings_hold_every_rule_of_the_library_template(kind):  # AC-171.2
    template = rules(ROOT / "templates" / "library-python" / ".claude" / "settings.json", kind)
    have = set(rules(ROOT / ".claude" / "settings.json", kind))
    assert template, "the template has rules of this kind"
    assert [r for r in template if r not in have] == []


def test_the_platform_settings_keep_the_worktree_key_and_take_no_plugin_keys():  # AC-171.2
    data = json.loads((ROOT / ".claude" / "settings.json").read_text())
    assert data.get("worktree") == {"baseRef": "head"} and "$schema" in data
    assert "extraKnownMarketplaces" not in data and "enabledPlugins" not in data
    assert "defaultMode" not in data.get("permissions", {})


def run_check(root):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "check-settings.py"), "--root", str(root)],
                          capture_output=True, text=True, check=False)


def tree(tmp_path, template, platform):
    for rel, data in ((".claude/settings.json", platform), ("templates/library-python/.claude/settings.json", template)):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(data if isinstance(data, str) else json.dumps(data))
    return tmp_path


TEMPLATE = {"permissions": {"allow": ["Bash(cplat *)", "Read(~/.claude/plugins/**)"], "ask": ["Bash(git reset *)"]}}


def test_the_check_names_each_template_rule_the_platform_file_lacks(tmp_path):  # AC-171.2
    root = tree(tmp_path, TEMPLATE, {"permissions": {"allow": ["Bash(cplat *)"]}})
    res = run_check(root)
    assert res.returncode == 1
    lines = res.stdout.splitlines()
    assert ".claude/settings.json lacks the library template's allow rule \"Read(~/.claude/plugins/**)\"" in " ".join(lines)
    assert ".claude/settings.json lacks the library template's ask rule \"Bash(git reset *)\"" in " ".join(lines)
    assert sum(ln.startswith("ERROR: ") for ln in lines) == 2 and lines[-1] == "FAILED: 2 rule(s) missing"


def test_the_check_passes_when_the_platform_file_holds_every_rule(tmp_path):  # AC-171.2
    platform = {"worktree": {"baseRef": "head"}, "permissions": {**TEMPLATE["permissions"], "allow": [*TEMPLATE["permissions"]["allow"], "Bash(ls)"]}}
    res = run_check(tree(tmp_path, TEMPLATE, platform))
    assert res.returncode == 0
    assert res.stdout.strip() == "OK: .claude/settings.json holds the library template's 2 allow and 1 ask rules"


def test_the_check_reports_an_unreadable_file_as_one_error_line(tmp_path):  # AC-171.2
    res = run_check(tree(tmp_path, TEMPLATE, "{not json"))
    assert res.returncode == 1
    lines = res.stdout.splitlines()
    assert len(lines) == 1 and lines[0].startswith("ERROR: ") and ".claude/settings.json" in lines[0]


def test_the_check_passes_on_this_repository():  # AC-171.2
    res = run_check(ROOT)
    template = ROOT / "templates" / "library-python" / ".claude" / "settings.json"
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.strip() == (f"OK: .claude/settings.json holds the library template's {len(rules(template, 'allow'))} allow "
                                  f"and {len(rules(template, 'ask'))} ask rules")


def test_validate_and_ci_run_the_settings_check():  # AC-171.2
    devbox = json.loads((ROOT / "devbox.json").read_text())["shell"]["scripts"]
    assert "scripts/check-settings.py" in devbox["validate"]
    assert "scripts/check-settings.py" in (ROOT / "scripts" / "ci-local.sh").read_text()
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    job = re.search(r"^  validate-shapes:\n(.*?)(?=^  [a-z0-9-]+:\n)", ci, re.S | re.M)
    assert job and "scripts/check-settings.py" in job.group(1)


def test_the_preflight_of_a_headless_ship_in_the_platform_repo_passes(w, capsys):  # AC-171.2
    platform = (ROOT / ".claude" / "settings.json").read_text()
    assert MIN_BASH in rules(ROOT / ".claude" / "settings.json", "allow")
    put_settings(w.repo, raw=platform)
    w.run("--max-runs", "1")
    assert "preflight failed" not in capsys.readouterr().out
    assert len(w.sessions()) == 1
