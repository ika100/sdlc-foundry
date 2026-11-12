"""Spec 184 acceptance tests: `NAME=value devbox run <script>` commands of a plan or design are allowed verbatim (AC-184.10).

Seams: `envprefix.candidates` / `verdict` / `commands` (design.md, Contract, "Environment-prefixed commands"), and the allowlist of
`cplat headless` (dry-run output and the grants of the unit sessions of the fake world of spec 131).
"""
import json

import pytest

import preflight
from units131_support import SPEC_ID, World, git

OK = "TEST_FAKE_DELAY=2 devbox run test-fast"


class Lazy:
    def __getattr__(self, name):
        import envprefix
        return getattr(envprefix, name)


@pytest.fixture()
def ep():
    return Lazy()


# ---------------- candidates and verdict ----------------

def test_a_candidate_is_an_inline_code_span_that_starts_with_name_value_and_has_another_word_ac_184_10(ep):  # AC-184.10
    text = ("Run `TEST_FAKE_DELAY=2 devbox run test-fast`, then `devbox run test`, `FOO=1 sh -c 'x'`, and `X=1` alone;\n"
            "also `A=1 B=2 devbox run quality` and plain text FOO=1 devbox run nope.\n")
    assert ep.candidates(text) == [OK, "FOO=1 sh -c 'x'", "A=1 B=2 devbox run quality"]


@pytest.mark.parametrize("cmd", [OK, "A=1 B=2 devbox run quality", "TEST_FAKE_DELAY=2 devbox run test-fast -- tests/cplat/test_x.py",
                                 "MY_PATH=1 devbox run test", "HOMEDIR=x devbox run test", "_X1=0 devbox run lint-fix", "CI=true devbox run ci"])
def test_an_uppercase_name_before_devbox_run_is_allowed_ac_184_10(ep, cmd):  # AC-184.10
    assert ep.verdict(cmd) is None


@pytest.mark.parametrize("cmd", [
    "FOO=1 sh -c 'devbox run test'", "FOO=1 devbox shell", "FOO=1 devbox install", "FOO=1 devbox run", "FOO=1 make test",
    "FOO=1 BAR=2 python3 x.py",
])
def test_another_program_after_the_prefix_is_not_allowed_ac_184_10(ep, cmd):  # AC-184.10
    assert ep.verdict(cmd)


@pytest.mark.parametrize("cmd", [
    "FOO=1 devbox run test; rm -rf x", "FOO=1 devbox run test && echo done", "FOO=1 devbox run test || true",
    "FOO=1 devbox run test | tee out.txt", "FOO=$(id) devbox run test", "FOO=1 devbox run $(id)", "FOO=`id` devbox run test",
    "FOO=1 devbox run `id`", "FOO=1 devbox run test\nrm -rf x",
])
def test_chaining_and_substitution_are_not_allowed_ac_184_10(ep, cmd):  # AC-184.10
    assert ep.verdict(cmd)


@pytest.mark.parametrize("cmd", ["foo=1 devbox run test", "Foo=1 devbox run test", "FOO=1 bar=2 devbox run test", "1A=1 devbox run test"])
def test_a_name_that_is_not_uppercase_is_not_allowed_ac_184_10(ep, cmd):  # AC-184.10
    assert ep.verdict(cmd)


@pytest.mark.parametrize("name", ["PATH", "HOME", "SHELL", "ENV", "BASH_ENV", "NODE_OPTIONS", "PYTHONPATH",
                                  "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "DYLD_X", "CPLAT_SLOT", "CPLAT_CLAUDE",
                                  "GIT_DIR", "GIT_SSH_COMMAND", "GH_TOKEN", "GH_HOST"])
def test_a_refused_name_is_not_allowed_alone_or_among_others_ac_184_10(ep, name):  # AC-184.10
    assert ep.verdict(f"{name}=x devbox run test")
    assert ep.verdict(f"OK_NAME=1 {name}=x devbox run test")


# ---------------- commands of a spec folder ----------------

def commit_docs(repo, plan_extra="", design="", branch=None, message="docs"):
    d = repo / "docs" / "specs" / SPEC_ID
    if branch:
        git(repo, "checkout", "-q", "-B", branch)
    plan = d / "plan.md"
    plan.write_text(plan.read_text().split("\n## notes")[0] + "\n## notes\n" + plan_extra)
    if design:
        (d / "design.md").write_text(design)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


@pytest.fixture()
def w(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, plan=True)


def test_the_commands_come_from_the_committed_plan_then_design_without_duplicates_ac_184_10(w, ep):  # AC-184.10
    commit_docs(w.repo, f"Verify with `{OK}`, again `{OK}` and `FOO=1 sh -c 'x'` and `devbox run test`.\n",
                design=f"Slow path: `A=1 devbox run quality`, `FOO=1 sh -c 'x'`, `B=2 devbox run a; rm x`.\n")
    allowed, refused = ep.commands(w.repo, [SPEC_ID])
    assert allowed == [OK, "A=1 devbox run quality"]
    assert refused == ["FOO=1 sh -c 'x'", "B=2 devbox run a; rm x"]


def test_an_uncommitted_edit_allows_nothing_ac_184_10(w, ep):  # AC-184.10
    commit_docs(w.repo, f"`{OK}`\n")
    plan = w.repo / "docs" / "specs" / SPEC_ID / "plan.md"
    plan.write_text(plan.read_text() + "and `EVIL=1 devbox run ci`\n")
    assert ep.commands(w.repo, [SPEC_ID]) == ([OK], [])


def test_the_feature_branch_head_is_read_when_there_is_one_ac_184_10(w, ep):  # AC-184.10
    commit_docs(w.repo, "nothing here\n")
    assert ep.commands(w.repo, [SPEC_ID]) == ([], [])
    commit_docs(w.repo, f"`{OK}`\n", branch=f"feature/{SPEC_ID}")
    git(w.repo, "checkout", "-q", "main")
    assert ep.commands(w.repo, [SPEC_ID]) == ([OK], [])


def test_a_spec_folder_without_plan_or_design_has_no_commands_ac_184_10(tmp_path, ep):  # AC-184.10
    r = tmp_path / "bare"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "commit", "-q", "--allow-empty", "-m", "x")
    assert ep.commands(r, ["007-price-alerts"]) == ([], [])


# ---------------- cplat headless ----------------

def rules_of(out):
    return [ln[2:] for ln in out.splitlines() if ln.startswith("  ")]


@pytest.mark.parametrize("prompt", ["/component:ship 7", "/component:build 7"])
def test_the_run_allowlist_has_the_allowed_command_verbatim_and_lists_the_refused_ones_ac_184_10(w, prompt, capsys):  # AC-184.10
    commit_docs(w.repo, f"Run `{OK}`; not `FOO=1 sh -c 'x'`, not `PATH=/tmp devbox run test`, not `B=2 devbox run a && b`.\n")
    assert w.run("--dry-run", prompt=prompt) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert f"  Bash({OK})" in lines
    refused_line = next(i for i, ln in enumerate(lines) if ln.startswith("refused: "))
    assert lines[refused_line + 1:refused_line + 4] == ["not allowed: FOO=1 sh -c 'x'", "not allowed: PATH=/tmp devbox run test",
                                                        "not allowed: B=2 devbox run a && b"]
    assert not any(ln.startswith("  Bash(FOO=") or ln.startswith("  Bash(PATH=") or ln.startswith("  Bash(B=2") for ln in lines)
    assert preflight.matches(f"Bash({OK})", OK) and not preflight.matches(f"Bash({OK})", "TEST_FAKE_DELAY=3 devbox run test-fast")
    assert not preflight.matches(f"Bash({OK})", OK + "; rm -rf x")
    assert w.run("--dry-run", prompt="/component:fix the price is wrong") == 0         # a fix names no spec: no command rules
    assert f"Bash({OK})" not in capsys.readouterr().out


def test_every_unit_session_is_granted_the_command_ac_184_10(w):  # AC-184.10
    commit_docs(w.repo, f"`{OK}`\n")
    assert w.run() == 0
    assert w.sessions()
    for s in w.sessions():
        argv = s["argv"]
        assert f"Bash({OK})" in argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
        assert f"Bash({OK})" in json.loads(s["allowlist"])


def test_a_command_the_plan_unit_commits_is_allowed_from_the_next_unit_on_and_announced_once_ac_184_10(tmp_path, monkeypatch, capsys):  # AC-184.10
    w = World(tmp_path, monkeypatch, plan=False)                       # the first session writes and commits the plan
    plan = w.dir / "plan.md.txt"
    plan.write_text(plan.read_text() + f"\n## notes\nRun `{OK}`.\n")
    assert w.run() == 0
    sessions = w.sessions()
    grants = [f"Bash({OK})" in json.loads(s["allowlist"]) for s in sessions]
    assert sessions[0]["unit"] == "plan" and grants == [False] + [True] * (len(sessions) - 1)
    lines = capsys.readouterr().out.splitlines()
    assert lines.count(f"run allowlist: added {OK}") == 1
    assert [i for i, ln in enumerate(lines) if ln == f"run allowlist: added {OK}"][0] < \
        [i for i, ln in enumerate(lines) if "unit red-tests session 1" in ln][0]
