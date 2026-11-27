"""Spec 223 test seam check: the fake `gh` and the change-quality git world behave as the acceptance tests assume."""
import subprocess

from cq223_world import fake_gh  # noqa: F401  (fixture)
from test_223_change_quality import FLEET, build


def gh(*args):
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def test_the_fake_gh_answers_the_contract_calls(fake_gh):
    fake_gh.set(fleet=FLEET, login="o", tags=["v5.23.0"]).merged(812)
    assert gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner") == (0, "ika100/sdlc-foundry", "")
    assert gh("api", "repos/x/y/pulls/812", "-q", ".merged_at")[:2] == (0, "2026-11-20T10:00:00Z")
    assert gh("api", "repos/x/y/pulls/1")[0] == 1 and "404" in gh("api", "repos/x/y/pulls/1")[2]
    assert gh("api", "repos/x/y/git/ref/tags/v5.23.0")[0] == 0 and gh("api", "repos/x/y/git/ref/tags/v9.9.9")[0] == 1
    assert gh("api", "user", "-q", ".login")[:2] == (0, "o")
    listed = gh("repo", "list", "o", "--no-archived", "--json", "f")[1]
    assert "o/a" in listed and "o/d" in listed
    shas = gh("api", "--paginate", "repos/o/a/commits?path=.platform-version", "-q", ".[].sha")[1].split()
    assert len(shas) == 3
    assert gh("api", "repos/o/a/contents/.platform-version", "-H", "Accept: raw")[1] == "platform: 5.30.1"
    assert gh("api", f"repos/o/a/contents/.platform-version?ref={shas[1]}")[1] == "platform: 5.30.0"
    assert gh("api", "repos/o/c/contents/.copier-answers.yml")[0] == 1
    assert gh("api", "repos/o/a/contents/.copier-answers.yml")[0] == 0
    fake_gh.set(down=True)
    assert gh("api", "user")[0] == 4


def test_the_world_tags_contain_the_squash_commits(tmp_path):
    root = build(tmp_path / "platform")
    tags = subprocess.run(["git", "log", "--format=%s", "v5.30.0"], cwd=root, capture_output=True, text=True).stdout
    assert "feat: two (#701)" in tags and "(#815)" not in tags
    assert subprocess.run(["git", "tag", "--contains", "HEAD~0", "--list", "v*"], cwd=root, capture_output=True, text=True).stdout.split() \
        == ["v5.31.0"]
