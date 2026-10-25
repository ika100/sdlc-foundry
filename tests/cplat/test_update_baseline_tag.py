"""The baseline (spec 086) renders from a platform checkout without tags: the marketplace clone cplat runs from."""
import io
import subprocess
import tarfile

import update


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_a_tag_missing_from_a_shallow_clone_is_fetched_before_the_archive(tmp_path):
    origin = tmp_path / "origin"
    (origin / "templates" / "t").mkdir(parents=True)
    (origin / "templates" / "t" / "f.txt").write_text("old\n")
    git(origin, "init", "-q", "-b", "main")
    git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1")
    git(origin, "tag", "v1.0.0")
    (origin / "templates" / "t" / "f.txt").write_text("new\n")
    git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "v2")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--depth", "1", "--no-tags", f"file://{origin}", str(clone))
    assert subprocess.run(["git", "rev-parse", "-q", "--verify", "v1.0.0"], cwd=clone, capture_output=True).returncode != 0

    data = update._archive("v1.0.0", "templates/t", clone)

    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        assert tar.extractfile("templates/t/f.txt").read() == b"old\n"
