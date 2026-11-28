"""#1109: the build of an amended, already done spec leaves a new `done` bullet in its Changelog."""
import subprocess

import amend_done
import red_scope
import spec as specmod

SPEC = """---
spec_id: 007-price-alerts
title: Price alerts
status: {status}
priority: P1
shape: service-python
---

# 007 — Price alerts

## Acceptance criteria

- **AC-007.1** Given a rule, when the price crosses it, then an email is sent.

## Changelog

{changelog}
"""
REL = "docs/specs/007-price-alerts/spec.md"
BUILT = "- 2026-10-05 created\n- 2026-10-05 done"
AMENDED = BUILT + "\n- 2026-10-09 amended (#1, decided by the user): a change"


def repo_with(tmp_path, changelog, status="done"):
    path = tmp_path / REL
    path.parent.mkdir(parents=True)
    path.write_text(SPEC.format(status=status, changelog=changelog))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def bullets(repo):
    return red_scope._bullets(specmod.find(repo, "007-price-alerts").body)


def test_the_build_of_an_amendment_adds_a_done_line(tmp_path):
    repo = repo_with(tmp_path, AMENDED)
    assert amend_done.add(repo, [REL, "scripts/cplat/red.py"]) == ["007-price-alerts"]
    last = bullets(repo)[-1]
    assert red_scope.DONE.match(last)
    assert not amend_done.pending(specmod.find(repo, "007-price-alerts"))


def test_a_second_run_adds_no_second_line(tmp_path):
    repo = repo_with(tmp_path, AMENDED)
    amend_done.add(repo, [REL, "x.py"])
    assert amend_done.add(repo, [REL, "x.py"]) == []
    assert len(bullets(repo)) == 4


def test_a_docs_only_change_is_the_amendment_not_its_build(tmp_path):
    repo = repo_with(tmp_path, AMENDED)
    assert amend_done.add(repo, [REL, "docs/changelog.d/1-x.fixed.md"]) == []
    assert len(bullets(repo)) == 3


def test_a_spec_that_was_not_amended_or_is_not_done_is_left(tmp_path):
    repo = repo_with(tmp_path, BUILT)
    assert amend_done.add(repo, [REL, "x.py"]) == []
    other = tmp_path / "b"
    other.mkdir()
    repo = repo_with(other, AMENDED, status="building")
    assert amend_done.add(repo, [REL, "x.py"]) == []
