"""#752: `cplat spec test-diff <base>` crashed with a traceback (git diff exit 128) when the base was not a commit of the repo,
for example a red-tests commit squashed away. It now refuses with the reason and how to find the base."""
import subprocess

import pytest

import core
import spec


def test_a_base_that_is_not_a_commit_is_refused_with_a_hint(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "--allow-empty", "-m", "i"],
                   check=True)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(core.PlatformError) as e:
        spec.main(["test-diff", "0123456789abcdef0123456789abcdef01234567"])
    assert "is not a commit of this repository" in str(e.value) and "acceptance tests for" in (e.value.hint or "")
