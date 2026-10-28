"""A repository generated before the v3.0.0 rename (marketplace ika100-claude) is migrated by cplat platform update."""
import json
import subprocess

import update


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


def test_update_service_moves_a_legacy_repo_to_the_new_marketplace(tmp_path, new_service):
    new_service(["legacy-go", "desc", "--type", "service", "--lang", "go", "--no-github", "--skip-tasks", "--dir", str(tmp_path), "--org", "acme"])
    repo = tmp_path / "legacy-go"
    # make it look like a v2.x repository
    settings = repo / ".claude" / "settings.json"
    settings.write_text(settings.read_text().replace("sdlc-foundry", "ika100-claude").replace("ika100/sdlc-foundry", "ika100/claude-platform"))
    answers = repo / ".copier-answers.yml"
    answers.write_text(answers.read_text().replace("ika100/sdlc-foundry", "ika100/claude-platform"))
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "legacy")
    assert "ika100-claude" in settings.read_text()

    assert update.main(["--repo", str(repo), "--skip-tasks", "--migrate"]) == 0

    new = json.loads(settings.read_text())
    assert "sdlc-foundry" in new["extraKnownMarketplaces"] and "ika100-claude" not in settings.read_text()
    assert all(key.endswith("@sdlc-foundry") for key in new["enabledPlugins"])
    assert new["extraKnownMarketplaces"]["sdlc-foundry"]["source"]["repo"] == "ika100/sdlc-foundry"
    assert "_src_path: gh:ika100/sdlc-foundry/templates/service-go" in answers.read_text()
