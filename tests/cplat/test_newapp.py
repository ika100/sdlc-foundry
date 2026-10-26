"""new-app: manifest validation, creation order, dry-run, execute, failure and resume (no network: gh and compose are faked)."""
import subprocess
from pathlib import Path

import pytest
import yaml

import compose
import core
import newapp
import newsvc

MANIFEST = {
    "system": "shop",
    "owner": "team-shop",
    "components": [
        {"name": "shop-web", "description": "Frontend", "type": "website", "lang": "typescript"},
        {"name": "shop-go", "description": "Webhooks", "type": "service", "lang": "go"},
        {"name": "shop-models", "description": "Shared models", "type": "library", "lang": "python"},
        {"name": "shop-api", "description": "API", "type": "service", "lang": "python"},
    ],
}


def write(tmp_path, manifest=None, **override):
    data = {**(manifest or MANIFEST), **override}
    f = tmp_path / "system.yml"
    f.write_text(yaml.safe_dump(data))
    return str(f)


def resolve(tmp_path, *extra, **override):
    return newapp.resolve([write(tmp_path, **override), "--no-github", "--org", "acme", "--dir", str(tmp_path / "out"), *extra])


# ---------------- validation ----------------

@pytest.mark.parametrize("mutate,msg", [
    (lambda m: m.update(system="Bad_Name"), "invalid system name"),
    (lambda m: m.update(extra=1), "unknown key"),
    (lambda m: m.update(components=[]), "non-empty list"),
    (lambda m: m.update(visibility="secret"), "private or public"),
    (lambda m: m["components"].append({"name": "shop-api", "description": "d", "type": "service", "lang": "go"}), "used twice"),
    (lambda m: m["components"].append({"name": "shop", "description": "d", "type": "service", "lang": "go"}), "the gitops repo name"),
    (lambda m: m["components"].append({"name": "x-gitops", "description": "d", "type": "gitops", "lang": "app"}), "not a valid component type"),
    (lambda m: m["components"].append({"name": "x-rust", "description": "d", "type": "service", "lang": "rust"}), "not a valid component type"),
    (lambda m: m["components"].append({"name": "x-java", "description": "d", "type": "service", "lang": "java", "data": {"nope": "1"}}), "no option 'nope'"),
    (lambda m: m["components"].append({"name": "x-bad", "description": "d", "type": "service", "lang": "go", "color": "red"}), "unknown key"),
    (lambda m: m["components"].append({"name": "x-nodesc", "type": "service", "lang": "go"}), "`description` is required"),
])
def test_bad_manifests_fail_before_anything_happens(tmp_path, mutate, msg):
    manifest = yaml.safe_load(yaml.safe_dump(MANIFEST))
    mutate(manifest)
    with pytest.raises(core.PlatformError, match=msg):
        resolve(tmp_path, manifest=manifest)
    assert not (tmp_path / "out").exists()


def test_validation_errors_name_the_component_and_carry_a_hint(tmp_path):
    manifest = yaml.safe_load(yaml.safe_dump(MANIFEST))
    manifest["components"][0]["lang"] = "rust"
    with pytest.raises(core.PlatformError) as e:
        resolve(tmp_path, manifest=manifest)
    assert str(e.value).startswith("component 'shop-web':") and "valid:" in str(e.value)


def test_existing_directory_is_refused(tmp_path):
    (tmp_path / "out" / "shop-api").mkdir(parents=True)
    (tmp_path / "out" / "shop-api" / "f").write_text("x")
    with pytest.raises(core.PlatformError, match="shop-api: .*not empty"):
        resolve(tmp_path)


def test_public_needs_github(tmp_path):
    with pytest.raises(core.PlatformError, match="need GitHub"):
        resolve(tmp_path, visibility="public")


def test_existing_github_repo_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(newapp.core, "has_gh", lambda: True)
    monkeypatch.setattr(newapp, "_remote_exists", lambda slug: slug == "acme/shop-api")
    with pytest.raises(core.PlatformError, match="acme/shop-api already exists") as e:
        newapp.resolve([write(tmp_path), "--org", "acme", "--dir", str(tmp_path / "out")])
    assert "--resume" in e.value.hint


# ---------------- order and preview ----------------

def test_creation_order_is_computed_not_taken_from_the_file(tmp_path):
    req = resolve(tmp_path)
    assert [e["name"] for e in req["entries"]] == ["shop-gitops", "shop-models", "shop-api", "shop-go", "shop-web"]
    assert req["deployable"] == ["shop-api", "shop-go", "shop-web"]  # the library is never composed


def test_services_are_linked_to_the_app_and_the_library_is_not(tmp_path):
    req = resolve(tmp_path)
    by = {e["name"]: e["req"] for e in req["entries"]}
    assert by["shop-api"]["app"] == "acme/shop-gitops" and by["shop-web"]["app"] == "acme/shop-gitops"
    assert by["shop-models"]["app"] is None and by["shop-gitops"]["app"] is None


def test_dry_run_creates_nothing_and_lists_every_repo(tmp_path, capsys):
    assert newapp.main([write(tmp_path), "--no-github", "--org", "acme", "--dir", str(tmp_path / "out"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and all(n in out for n in ("shop-gitops (gitops-app)", "shop-models (library-python)", "shop-web (web-nextjs)"))
    assert "print its command if the pull request cannot be opened" in out
    assert not (tmp_path / "out").exists()


def test_dry_run_announces_the_single_compose_pr(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(newapp.core, "has_gh", lambda: True)
    monkeypatch.setattr(newapp, "_remote_exists", lambda slug: False)
    newapp.main([write(tmp_path), "--org", "acme", "--dir", str(tmp_path / "out"), "--dry-run"])
    out = capsys.readouterr().out
    assert "[outward] open one pull request in acme/shop-gitops adding to system.yaml: shop-api, shop-go, shop-web" in out
    assert "create PRIVATE GitHub repo acme/shop-api" in out


# ---------------- execute, failure, resume ----------------

class Fakes:
    def __init__(self, monkeypatch, fail_on=None):
        self.created, self.composed, self.fail_on = [], [], fail_on
        monkeypatch.setattr(newapp.newsvc, "execute", self.execute)
        monkeypatch.setattr(newapp.compose, "main", self.compose_main)
        monkeypatch.setattr(newapp.core, "has_gh", lambda: True)
        monkeypatch.setattr(newapp, "_remote_exists", lambda slug: False)

    def execute(self, req):
        if req["name"] == self.fail_on:
            raise core.PlatformError("gh repo create failed: boom")
        self.created.append(req["name"])
        (req["target"]).mkdir(parents=True)
        (req["target"] / ".copier-answers.yml").write_text(f"_src_path: gh:ika100/sdlc-foundry/templates/{req['template']}\n")
        r = core.Report(title="x")
        r.did.append(f"created {req['name']}")
        r.undo.append(f"rm -rf {req['target']}")
        return r

    def compose_main(self, argv):
        self.composed.append(argv)
        print("opened https://github.com/acme/shop/pull/7")
        return 0


def run_args(tmp_path, *extra):
    return [write(tmp_path), "--org", "acme", "--dir", str(tmp_path / "out"), *extra]


def test_execute_creates_in_order_then_composes_once(tmp_path, monkeypatch, capsys):
    fakes = Fakes(monkeypatch)
    assert newapp.main(run_args(tmp_path)) == 0
    assert fakes.created == ["shop-gitops", "shop-models", "shop-api", "shop-go", "shop-web"]
    assert fakes.composed == [["add", "shop-api", "shop-go", "shop-web", "--repo-dir", str(tmp_path / "out" / "shop-gitops"), "--pr"]]
    out = capsys.readouterr().out
    assert "https://github.com/acme/shop/pull/7" in out and "To undo" in out


def test_failure_reports_what_exists_and_stops_before_composing(tmp_path, monkeypatch):
    fakes = Fakes(monkeypatch, fail_on="shop-api")
    with pytest.raises(core.PlatformError) as e:
        newapp.main(run_args(tmp_path))
    msg = str(e.value)
    assert "shop-api failed" in msg and "created: shop-gitops, shop-models" in msg and "not started: shop-go, shop-web" in msg
    assert "--resume" in e.value.hint and "rm -rf" in e.value.hint
    assert fakes.composed == []


def test_resume_skips_existing_repos_and_finishes(tmp_path, monkeypatch, capsys):
    fakes = Fakes(monkeypatch, fail_on="shop-api")
    with pytest.raises(core.PlatformError):
        newapp.main(run_args(tmp_path))
    fakes.fail_on, fakes.created = None, []
    assert newapp.main(run_args(tmp_path, "--resume")) == 0
    assert fakes.created == ["shop-api", "shop-go", "shop-web"]  # shop-gitops and shop-models were not recreated
    assert len(fakes.composed) == 1
    assert "shop-gitops: already exists, skipped" in capsys.readouterr().out


def test_compose_failure_is_reported_with_the_manual_command(tmp_path, monkeypatch):
    Fakes(monkeypatch)

    def boom(argv):
        raise core.PlatformError("topic missing")
    monkeypatch.setattr(newapp.compose, "main", boom)
    with pytest.raises(core.PlatformError, match="repos created, but wiring them") as e:
        newapp.main(run_args(tmp_path))
    assert "/component:add shop-api shop-go shop-web --pr" in e.value.hint


def test_no_github_prints_the_compose_command(tmp_path, monkeypatch, capsys):
    Fakes(monkeypatch)

    def cannot_open(argv):
        raise core.PlatformError("no remote to open the pull request on")
    monkeypatch.setattr(newapp.compose, "main", cannot_open)
    assert newapp.main([write(tmp_path), "--no-github", "--org", "acme", "--dir", str(tmp_path / "out")]) == 0
    assert "/component:add shop-api shop-go shop-web --pr" in capsys.readouterr().out


@pytest.mark.slow
def test_real_local_render_of_a_small_app(tmp_path):
    manifest = {"system": "mini", "owner": "team-mini", "components": [{"name": "mini-lib", "description": "lib", "type": "library", "lang": "python"},
                                              {"name": "mini-api", "description": "api", "type": "service", "lang": "go"}]}
    f = tmp_path / "system.yml"
    f.write_text(yaml.safe_dump(manifest))
    assert newapp.main([str(f), "--no-github", "--skip-tasks", "--org", "acme", "--dir", str(tmp_path)]) == 0
    for name, shape in (("mini-gitops", "gitops-app"), ("mini-lib", "library-python"), ("mini-api", "service-go")):
        out = subprocess.run(["bash", str(core.PLATFORM_ROOT / "scripts/detect-shape.sh"), str(tmp_path / name)], text=True, capture_output=True).stdout.strip()
        assert out == shape
    assert "acme/mini" in (tmp_path / "mini-api" / ".platform-app.yml").read_text()
    assert not (tmp_path / "mini-lib" / ".platform-app.yml").exists()


def test_a_new_product_names_one_token_step_for_all_services(tmp_path, monkeypatch, capsys):
    """AC-062.4: one token, set in every deployable component."""
    Fakes(monkeypatch)
    assert newapp.main(run_args(tmp_path)) == 0
    out = capsys.readouterr().out
    step = next(ln for ln in out.splitlines() if "GITOPS_TOKEN" in ln)
    assert "acme/shop-gitops" in step and "for r in shop-api shop-go shop-web" in step and "gh secret set GITOPS_TOKEN -R acme/$r" in step
