"""Spec 184: helpers of the land tests for the ADR index and the rule register (not a test file).

The land world of spec 171 (`land171_world.World`: a bare repository for GitHub, a `gh` stub, a fake clock) plus:

  `seed(world, files)`    files that exist on `main` and on the feature branch before the sides diverge
  `on_branch(world, ..)`  a commit of the feature branch, pushed (the head of the pull request)
  `on_main(world, ..)`    a commit on `main` by another person
  `land(world, entry, capsys)`  one land by either entry, `(rc, out, err)`
"""
import subprocess

from land171_world import BRANCH, PR_URL, git, make_world  # noqa: F401  (re-exported)

BASE_INDEX = """# Architecture decision records

Intro text of the index.

| ADR | Decision |
|---|---|
| [001](001-first.md) | First decision |
| [002](002-second.md) | Second decision |
| [003](003-third.md) | Third decision |

Closing note of the index.
"""


def adr_file(number: str, title: str) -> str:
    return f"# ADR-{number}: {title}\n\nStatus: accepted\n\nContext and decision of {title}.\n"


def row(number: str, slug: str, text: str) -> str:
    return f"| [{number}]({number}-{slug}.md) | {text} |\n"


def with_rows(index: str, *rows: str) -> str:
    """`index` with `rows` after its last table row."""
    lines = index.splitlines(keepends=True)
    last = max(i for i, ln in enumerate(lines) if ln.startswith("| ["))
    return "".join(lines[:last + 1] + list(rows) + lines[last + 1:])


def base_adrs() -> dict[str, str]:
    return {"docs/adr/README.md": BASE_INDEX, "docs/adr/001-first.md": adr_file("001", "First"),
            "docs/adr/002-second.md": adr_file("002", "Second"), "docs/adr/003-third.md": adr_file("003", "Third")}


def _write(root, files: dict[str, str | None]) -> None:
    for name, text in files.items():
        p = root / name
        if text is None:
            git(root, "rm", "-q", "-f", name)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def seed(world, files: dict[str, str]) -> None:
    """Commit `files` to main (pushed) and merge main into the feature branch (pushed): both sides start from them."""
    git(world.repo, "checkout", "-q", "main")
    _write(world.repo, files)
    git(world.repo, "add", "-A")
    git(world.repo, "commit", "-qm", "docs: the common base")
    git(world.repo, "push", "-q", "origin", "main")
    git(world.repo, "checkout", "-q", BRANCH)
    git(world.repo, "merge", "-q", "--no-edit", "main")
    git(world.repo, "push", "-q", "origin", BRANCH)
    git(world.other, "pull", "-q", "--ff-only", "origin", "main")


def on_branch(world, files: dict[str, str | None], msg="docs: the feature's change") -> None:
    _write(world.repo, files)
    git(world.repo, "add", "-A")
    git(world.repo, "commit", "-qm", msg)
    git(world.repo, "push", "-q", "origin", BRANCH)


def on_main(world, files: dict[str, str | None], msg="docs: another person's change") -> None:
    git(world.other, "config", "user.name", "Other")
    git(world.other, "config", "user.email", "other@example.test")
    git(world.other, "pull", "-q", "--ff-only", "origin", "main")
    _write(world.other, files)
    git(world.other, "add", "-A")
    git(world.other, "commit", "-qm", msg)
    git(world.other, "push", "-q", "origin", "main")


def conflicts(world) -> bool:
    res = subprocess.run(["git", "--git-dir", str(world.bare), "merge-tree", "--write-tree", "main", BRANCH], capture_output=True)
    return res.returncode == 1


def land(world, entry, capsys):
    capsys.readouterr()
    rc = world.land(entry)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def merged_head(world) -> str:
    (merged,) = world.events("merged")
    return merged["head"]


def show(world, head: str, path: str) -> str | None:
    res = subprocess.run(["git", "--git-dir", str(world.bare), "show", f"{head}:{path}"], capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else None


def assert_landed_by_a_signed_merge_of_main(world, before: str, head: str) -> None:
    """The land merged main into the branch, signed it off, pushed on top (no force) and judged the new head's checks first."""
    assert head != before
    assert len(world.bare_git("rev-list", "--parents", "-n", "1", head).split()) == 3
    assert "Signed-off-by:" in world.bare_git("log", "-1", "--format=%B", head)
    git(world.bare, "merge-base", "--is-ancestor", before, head)
    order = [(c["kind"], c["sha"] if c["kind"] == "checks" else c["head"]) for c in world.calls() if c.get("kind") in ("checks", "merged")]
    assert ("checks", head) in order and order.index(("checks", head)) < order.index(("merged", head))


def assert_stopped_clean(world, tip: str, head: str, err: str) -> None:
    """The land stopped as `rebase is a human decision`; no half-merged checkout, nothing pushed, nothing merged."""
    assert world.events("merged") == []
    assert "rebase is a human decision" in err
    assert git(world.repo, "status", "--porcelain") == ""
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=world.repo, capture_output=True).returncode != 0
    assert git(world.repo, "rev-parse", "HEAD") == tip and world.pr_head() == head


__all__ = ["BRANCH", "PR_URL", "git", "make_world"]
