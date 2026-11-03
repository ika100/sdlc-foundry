"""#337: two specs planned in parallel must not pick the same ADR number."""
import subprocess

import adr
import spec


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, check=True, capture_output=True)


def write(repo, name):
    (repo / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "adr" / name).write_text("# ADR\n")


def world(tmp_path):
    """origin with main (ADR-001) and a pushed branch other/x that adds ADR-002; a clone on feature/y."""
    origin, repo = tmp_path / "origin.git", tmp_path / "repo"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    git(repo, "remote", "add", "origin", str(origin))
    write(repo, "001-first.md")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "switch", "-qc", "other/x")
    write(repo, "002-theirs.md")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "theirs")
    git(repo, "push", "-q", "origin", "other/x")
    git(repo, "switch", "-q", "main")
    git(repo, "switch", "-qc", "feature/y")
    git(repo, "fetch", "-q", "origin")
    return repo


def test_the_next_number_skips_numbers_other_branches_hold_337(tmp_path):
    repo = world(tmp_path)
    assert adr.next_number(repo, with_prs=False) == 3
    assert spec.main(["--repo", str(repo), "adr-next", "--offline"]) == 0


def test_a_number_another_branch_uses_is_a_check_error_337(tmp_path, capsys):
    repo = world(tmp_path)
    write(repo, "002-mine.md")
    errors = adr.clashes(repo)
    assert len(errors) == 1 and "ADR-002" in errors[0] and "origin/other/x" in errors[0] and "adr-next" in errors[0]
    assert spec.main(["--repo", str(repo), "check"]) == 1
    assert "ADR-002" in capsys.readouterr().out


def test_a_free_number_passes_and_a_number_used_twice_here_fails_337(tmp_path):
    repo = world(tmp_path)
    write(repo, "003-mine.md")
    assert adr.clashes(repo) == []
    write(repo, "001-again.md")             # what a merge of two PRs with the same number leaves behind
    errors = adr.clashes(repo)
    assert len(errors) == 1 and "ADR-001 is used by 2 files" in errors[0]


def test_the_plan_hands_the_architect_a_free_number_337():
    import core
    plan = (core.PLATFORM_ROOT / "plugins" / "component" / "commands" / "plan.md").read_text()
    architect = (core.PLATFORM_ROOT / "plugins" / "svc" / "agents" / "architect.md").read_text()
    assert "cplat spec adr-next" in plan and "ADR_NEXT" in plan and "ADR_NEXT" in architect
